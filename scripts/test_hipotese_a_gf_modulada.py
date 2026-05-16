"""
test_hipotese_a_gf_modulada.py — Phase 0 caminho A — teste final.

Hipotese A: O denominador correto pro GSF e a soma per-usina de
GF_MODULADA_AJUSTADA_MRE (do dataset MRE_GF_MODULADA_USINA), nao
o agregado GARANTIA_FISICA_REDE_BASICA do MRE_MENSAL.

Vies observado no v2_b: +1,65% multiplicativo estavel em 8 meses.

Estrutura:
  1. Baixar MRE_MENSAL (DEN_RB), MRE_GF_MODULADA_USINA (DEN_MOD),
     GERACAO_UHE_V2 (numerador).
  2. Imprimir DEN_RB / DEN_MOD por mes. Esperado ~1,016.
  3. Recalcular GSF com DEN_MOD.
  4. Comparar com 8 pontos oficiais. Critico: 6+ dentro de +/-1pp.

NAO investiga 202303 (fora do range historico baixado).
"""
from __future__ import annotations

import sys
import time
from typing import Optional

import pandas as pd
from curl_cffi import requests as http


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,*/*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": "https://dadosabertos.ccee.org.br/",
}
BASE = "https://dadosabertos.ccee.org.br/api/3/action"


MRE_MENSAL_IDS = {
    2023: "cbcd5631-1a64-42f3-ad58-480c7b177388",
    2024: "5665c103-8223-47de-b581-9b3853f0609f",
    2025: "9c333d24-398f-4eda-8cc0-4e6ff95d99a4",
    2026: "37fdbdf6-77f0-40e3-93c5-60e299e68376",
}
GSF_OFICIAL = {
    "202303": 101.564,
    "202307":  77.957,
    "202403":  95.041,
    "202407":  84.975,
    "202501": 113.213,
    "202502": 110.957,
    "202507":  69.330,
    "202601":  81.207,
    "202602": 100.318,
}


def get_json(url, params=None):
    r = http.get(url, params=params or {}, headers=BROWSER_HEADERS,
                 impersonate="chrome", timeout=60)
    r.raise_for_status()
    return r.json()


def ckan_paginated(resource_id: str, max_rows: int = 2_000_000) -> Optional[pd.DataFrame]:
    base = f"{BASE}/datastore_search"
    rows = []
    offset = 0
    limit = 1000
    while True:
        try:
            r = http.get(
                base,
                params={"resource_id": resource_id, "limit": limit, "offset": offset},
                headers=BROWSER_HEADERS, impersonate="chrome", timeout=120,
            )
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            print(f"    ! offset={offset}: {type(e).__name__}: {e}")
            return pd.DataFrame(rows) if rows else None
        if not payload.get("success"):
            return None
        recs = payload.get("result", {}).get("records", [])
        if not recs:
            break
        rows.extend(recs)
        if len(recs) < limit or len(rows) >= max_rows:
            break
        offset += limit
        time.sleep(0.05)
    if not rows:
        return None
    return pd.DataFrame(rows)


def horas_mes(mref: str) -> int:
    ano = int(mref[:4])
    mes = int(mref[4:6])
    return pd.Timestamp(f"{ano}-{mes:02d}-01").days_in_month * 24


def main():
    print("=" * 75)
    print("TESTE HIPOTESE A — GF_MODULADA_AJUSTADA_MRE somada per-usina")
    print("=" * 75)

    # ----------------------------------------------------------
    # 1. Baixar MRE_MENSAL (DEN_RB) e MRE_GF_MODULADA_USINA (DEN_MOD)
    # ----------------------------------------------------------
    print("\n[1] Baixando MRE_MENSAL...")
    dfs = []
    for ano, rid in MRE_MENSAL_IDS.items():
        df = ckan_paginated(rid)
        if df is not None:
            dfs.append(df)
            print(f"  {ano}: {len(df):,} linhas")
    df_mre = pd.concat(dfs, ignore_index=True)
    df_mre["MES_REFERENCIA"] = df_mre["MES_REFERENCIA"].astype(str)
    df_mre["GARANTIA_FISICA_REDE_BASICA"] = pd.to_numeric(
        df_mre["GARANTIA_FISICA_REDE_BASICA"], errors="coerce"
    )

    print("\n[1b] Baixando MRE_GF_MODULADA_USINA (todos os anos):")
    pkg_mod = get_json(f"{BASE}/package_show",
                       {"id": "de057e31-780b-4530-ba4a-e03a29c3b6e3"})
    pkg_mod = pkg_mod.get("result", {})
    dfs_mod = []
    for r in pkg_mod.get("resources", []):
        if r.get("format", "").upper() != "CSV":
            continue
        nm = r.get("name")
        rid = r.get("id")
        print(f"  {nm}...", end=" ")
        df = ckan_paginated(rid)
        if df is not None:
            print(f"{len(df):,}")
            dfs_mod.append(df)
        else:
            print("FAIL")
    df_mod = pd.concat(dfs_mod, ignore_index=True)
    df_mod["MES_REFERENCIA"] = df_mod["MES_REFERENCIA"].astype(str)
    df_mod["GF_MODULADA_AJUSTADA_MRE"] = pd.to_numeric(
        df_mod["GF_MODULADA_AJUSTADA_MRE"], errors="coerce"
    )
    df_mod["GF_MODULADA_FATOR_DISPONIBILIDADE"] = pd.to_numeric(
        df_mod["GF_MODULADA_FATOR_DISPONIBILIDADE"], errors="coerce"
    )
    print(f"\n  MOD_USINA total: {len(df_mod):,} linhas")
    print(f"  Meses cobertos: {df_mod['MES_REFERENCIA'].min()} a "
          f"{df_mod['MES_REFERENCIA'].max()}")

    # ----------------------------------------------------------
    # 2. Calcular DEN_RB vs DEN_MOD por mes + razao
    # ----------------------------------------------------------
    print("\n" + "=" * 75)
    print("[2] COMPARACAO DOS DENOMINADORES por mes")
    print("=" * 75)

    den_rb_map = df_mre.set_index("MES_REFERENCIA")[
        "GARANTIA_FISICA_REDE_BASICA"
    ].to_dict()
    den_mod_map = (
        df_mod.groupby("MES_REFERENCIA")["GF_MODULADA_AJUSTADA_MRE"]
        .sum().to_dict()
    )
    # auxiliar: tambem somar GF_MODULADA_FATOR_DISPONIBILIDADE
    den_mod_fdisp_map = (
        df_mod.groupby("MES_REFERENCIA")["GF_MODULADA_FATOR_DISPONIBILIDADE"]
        .sum().to_dict()
    )

    print(f"\n{'mes':>6}  {'DEN_RB':>12}  {'DEN_MOD':>14}  "
          f"{'DEN_FDISP':>14}  {'RB/MOD':>7}  {'RB/FDISP':>8}")
    meses_alvo = sorted(GSF_OFICIAL.keys())
    razoes_rb_mod = []
    for m in meses_alvo:
        den_rb = den_rb_map.get(m)
        den_mod = den_mod_map.get(m)
        den_fdisp = den_mod_fdisp_map.get(m)
        if den_rb is None or den_mod is None:
            print(f"  {m}: skip (RB={den_rb}, MOD={den_mod})")
            continue
        razao_rb_mod = den_rb / den_mod
        razao_rb_fdisp = (den_rb / den_fdisp) if den_fdisp else None
        razoes_rb_mod.append(razao_rb_mod)
        fd_str = f"{razao_rb_fdisp:.4f}" if razao_rb_fdisp else "n/d"
        fdisp_str = f"{den_fdisp:,.2f}" if den_fdisp else "n/d"
        print(f"  {m}  {den_rb:>12,.2f}  {den_mod:>14,.2f}  "
              f"{fdisp_str:>14}  {razao_rb_mod:.4f}  {fd_str:>8}")

    if razoes_rb_mod:
        media_razao = sum(razoes_rb_mod) / len(razoes_rb_mod)
        print(f"\n  Mean(RB/MOD) = {media_razao:.4f}")
        print(f"  Expected if Hipotese A correta: ~1.0165")
        if 1.013 <= media_razao <= 1.020:
            print(f"  -> RAZAO BATE COM VIES OBSERVADO! Hipotese A apoiada.")
        else:
            print(f"  -> Razao NAO bate ({media_razao:.4f} vs esperado 1.0165).")
            print(f"     Hipotese A so explica parcialmente o vies.")

    # ----------------------------------------------------------
    # 3. Baixar GERACAO_UHE_V2 e recalcular GSF com DEN_MOD
    # ----------------------------------------------------------
    print("\n[3] Baixando GERACAO_UHE_V2 (numerador V2)...")
    pkg_uhe = get_json(f"{BASE}/package_show",
                       {"id": "0e4fdbef-7c85-44bf-a68c-cff808bd4449"})
    pkg_uhe = pkg_uhe.get("result", {})
    dfs_uhe = []
    for r in pkg_uhe.get("resources", []):
        if r.get("format", "").upper() != "CSV":
            continue
        nm = r.get("name")
        rid = r.get("id")
        print(f"  {nm}...", end=" ")
        df = ckan_paginated(rid)
        if df is not None:
            print(f"{len(df):,}")
            dfs_uhe.append(df)
        else:
            print("FAIL")
    df_uhe = pd.concat(dfs_uhe, ignore_index=True)
    df_uhe["MES_REFERENCIA"] = df_uhe["MES_REFERENCIA"].astype(str)
    df_uhe["MEDICAO_GERACAO_MENSAL"] = pd.to_numeric(
        df_uhe["MEDICAO_GERACAO_MENSAL"], errors="coerce"
    )
    # V2: PARTICIPANTE_MRE = 'Sim'
    df_uhe_v2 = df_uhe[
        df_uhe["PARTICIPANTE_MRE"].astype(str).str.strip().str.upper() == "SIM"
    ]

    # ----------------------------------------------------------
    # 4. GSF com DEN_MOD vs DEN_RB
    # ----------------------------------------------------------
    print("\n" + "=" * 75)
    print("[4] GSF RECALCULADO com DEN_MOD")
    print("=" * 75)
    print(f"\n{'mes':>6}  {'oficial':>8}  "
          f"{'V2/DEN_RB':>10}  {'diff_RB':>8}  "
          f"{'V2/DEN_MOD':>11}  {'diff_MOD':>9}  status")

    diffs_mod = []
    hits = 0
    for m in meses_alvo:
        oficial = GSF_OFICIAL[m]
        den_rb = den_rb_map.get(m)
        den_mod = den_mod_map.get(m)
        if den_rb is None or den_mod is None:
            print(f"  {m}  skip (sem GF — provavel 202303)")
            continue
        h = horas_mes(m)
        num = df_uhe_v2[df_uhe_v2["MES_REFERENCIA"] == m][
            "MEDICAO_GERACAO_MENSAL"
        ].sum()
        if num == 0:
            print(f"  {m}  skip (numerador zero — fora do dataset UHE_V2)")
            continue
        gsf_rb = num / (den_rb * h) * 100
        gsf_mod = num / (den_mod * h) * 100
        diff_rb = gsf_rb - oficial
        diff_mod = gsf_mod - oficial
        diffs_mod.append(diff_mod)
        status = "HIT" if abs(diff_mod) < 1 else "fail"
        if abs(diff_mod) < 1:
            hits += 1
        print(f"  {m}  {oficial:>7.2f}%  "
              f"{gsf_rb:>9.2f}%  {diff_rb:>+7.3f}  "
              f"{gsf_mod:>10.2f}%  {diff_mod:>+8.3f}  {status}")

    print(f"\n[5] RESUMO:")
    print(f"  Pontos testados: {len(diffs_mod)} (de 9 oficiais)")
    print(f"  Acertos com DEN_MOD dentro de +/-1pp: {hits}")
    if diffs_mod:
        print(f"  Mean abs diff: {sum(abs(d) for d in diffs_mod)/len(diffs_mod):.3f} pp")
        print(f"  Max abs diff:  {max(abs(d) for d in diffs_mod):.3f} pp")
    if hits >= 6:
        print(f"\n  >>> HIPOTESE A CONFIRMADA ({hits}/8 dentro de +/-1pp)")
        print(f"  >>> Formula final: GSF = sum(MEDICAO[PARTICIPANTE_MRE='Sim']) /")
        print(f"  >>>                     (sum(GF_MODULADA_AJUSTADA_MRE) * horas)")
    elif hits >= 3:
        print(f"\n  >>> HIPOTESE A PARCIAL ({hits}/8). Talvez fine-tune.")
    else:
        print(f"\n  >>> HIPOTESE A NAO BATE ({hits}/8). Investigar B (Itaipu).")

    print(f"\n  Nota: 202303 fora do escopo (historico baixado comeca em 202305).")
    print(f"        Sera resolvido na Fase 1 baixando o consolidado 2012-2024.")

    print("\n[FIM]")


if __name__ == "__main__":
    main()
