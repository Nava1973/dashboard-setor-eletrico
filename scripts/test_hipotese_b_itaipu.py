"""
test_hipotese_b_itaipu.py — Phase 0 caminho A — Hipotese B.

Hipotese B: GSF SIN CCEE EXCLUI a geracao de Itaipu do numerador.
Justificativa:
  - MRE_HORARIO tem colunas separadas ENTREGA_MRE_ITAIPU / RECEBIDA_MRE_ITAIPU
  - Power BI publico CCEE tem toggle "Todas as Usinas / Exceto Itaipu"
  - Itaipu binacional tem ~600 MWmed (~1-1.5% do total) -> proximo do
    vies residual de 1.65%

Estrutura:
  1. Identificar Itaipu em GERACAO_UHE_V2 (nome + magnitude)
  2. Confirmar flags (PARTICIPANTE_MRE, TIPO_DESPACHO)
  3. Recalcular GSF excluindo Itaipu
  4. Comparar com 8 pontos oficiais
  5. Criterio: 6+/8 dentro de +/-1pp -> CONFIRMA B
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
    print("TESTE HIPOTESE B — Excluir Itaipu do numerador")
    print("=" * 75)

    # ----------------------------------------------------------
    # Download necessario
    # ----------------------------------------------------------
    print("\n[Download] MRE_MENSAL...")
    dfs = []
    for ano, rid in MRE_MENSAL_IDS.items():
        df = ckan_paginated(rid)
        if df is not None:
            dfs.append(df)
    df_mre = pd.concat(dfs, ignore_index=True)
    df_mre["MES_REFERENCIA"] = df_mre["MES_REFERENCIA"].astype(str)
    df_mre["GARANTIA_FISICA_REDE_BASICA"] = pd.to_numeric(
        df_mre["GARANTIA_FISICA_REDE_BASICA"], errors="coerce"
    )
    gf_map = df_mre.set_index("MES_REFERENCIA")["GARANTIA_FISICA_REDE_BASICA"].to_dict()
    print(f"  MRE_MENSAL: {len(df_mre)} meses (range "
          f"{df_mre['MES_REFERENCIA'].min()}-{df_mre['MES_REFERENCIA'].max()})")

    print("\n[Download] GERACAO_UHE_V2 (todos os anos)...")
    pkg = get_json(f"{BASE}/package_show",
                   {"id": "0e4fdbef-7c85-44bf-a68c-cff808bd4449"})
    pkg = pkg.get("result", {})
    dfs_uhe = []
    for r in pkg.get("resources", []):
        if r.get("format", "").upper() != "CSV":
            continue
        nm = r.get("name")
        rid = r.get("id")
        print(f"  {nm}...", end=" ")
        df = ckan_paginated(rid)
        if df is not None:
            print(f"{len(df):,}")
            dfs_uhe.append(df)
    df_uhe = pd.concat(dfs_uhe, ignore_index=True)
    df_uhe["MES_REFERENCIA"] = df_uhe["MES_REFERENCIA"].astype(str)
    df_uhe["MEDICAO_GERACAO_MENSAL"] = pd.to_numeric(
        df_uhe["MEDICAO_GERACAO_MENSAL"], errors="coerce"
    )

    # ----------------------------------------------------------
    # 1. Identificar Itaipu por NOME no mes de teste 202602
    # ----------------------------------------------------------
    print("\n" + "=" * 75)
    print("[1] IDENTIFICAR ITAIPU no mes 202602 (e tambem em todo dataset)")
    print("=" * 75)

    df_test = df_uhe[df_uhe["MES_REFERENCIA"] == "202602"].copy()
    df_test = df_test.sort_values("MEDICAO_GERACAO_MENSAL", ascending=False)

    # Top 10 maiores parcelas em 202602
    print("\n  Top 10 maiores parcelas em fev/2026 (sem filtro):")
    print(f"  {'COD_PARC':>9}  {'GERACAO_MWH':>16}  {'%_TOTAL':>7}  "
          f"{'PART_MRE':>8}  {'TIPO_DESPACHO':<35}  SIGLA")
    total = df_test["MEDICAO_GERACAO_MENSAL"].sum()
    for _, row in df_test.head(10).iterrows():
        pct = row["MEDICAO_GERACAO_MENSAL"] / total * 100
        td = str(row["TIPO_DESPACHO"])[:35]
        sigla = str(row["SIGLA_PARCELA_USINA"])
        print(f"  {row['COD_PARCELA_USINA']:>9}  "
              f"{row['MEDICAO_GERACAO_MENSAL']:>16,.2f}  "
              f"{pct:>6.2f}%  {str(row['PARTICIPANTE_MRE']):>8}  "
              f"{td:<35}  {sigla}")

    # Buscar Itaipu por nome em todo dataset
    print("\n  Linhas com 'ITAIPU' no SIGLA_PARCELA_USINA (todos os meses):")
    mask_itaipu = df_uhe["SIGLA_PARCELA_USINA"].astype(str).str.upper().str.contains("ITAIPU", na=False)
    df_itaipu = df_uhe[mask_itaipu]
    if df_itaipu.empty:
        print("  ! NENHUMA linha contem 'ITAIPU' no nome — investigar")
    else:
        print(f"  {len(df_itaipu)} linhas encontradas. Codigos parcela unicos:")
        for parc, grp in df_itaipu.groupby("COD_PARCELA_USINA"):
            sigla_unica = grp["SIGLA_PARCELA_USINA"].unique()
            part_mre = grp["PARTICIPANTE_MRE"].unique()
            tipos = grp["TIPO_DESPACHO"].unique()
            print(f"    COD_PARCELA={parc}: sigla={sigla_unica.tolist()}, "
                  f"part_mre={part_mre.tolist()}, "
                  f"tipo_despacho={tipos.tolist()}, "
                  f"n_meses={grp['MES_REFERENCIA'].nunique()}")

    # ----------------------------------------------------------
    # 2. Confirmar flags + magnitude para 202602
    # ----------------------------------------------------------
    print("\n[2] CONFIRMAR FLAGS de Itaipu no mes 202602:")
    if not df_itaipu.empty:
        df_itaipu_202602 = df_itaipu[df_itaipu["MES_REFERENCIA"] == "202602"]
        if df_itaipu_202602.empty:
            print("  ! Itaipu nao aparece em 202602 (estranho)")
        else:
            for _, row in df_itaipu_202602.iterrows():
                pct = row["MEDICAO_GERACAO_MENSAL"] / total * 100
                print(f"    COD={row['COD_PARCELA_USINA']}  "
                      f"sigla={row['SIGLA_PARCELA_USINA']!r}  "
                      f"part_MRE={row['PARTICIPANTE_MRE']!r}  "
                      f"tipo_despacho={row['TIPO_DESPACHO']!r}  "
                      f"GERACAO={row['MEDICAO_GERACAO_MENSAL']:,.2f} MWh  "
                      f"(={pct:.2f}% do total)")

    # Set de cods Itaipu pra excluir
    cod_itaipu = set(df_itaipu["COD_PARCELA_USINA"].unique())
    print(f"\n  Codigos de parcela classificados como Itaipu: {sorted(cod_itaipu)}")

    # ----------------------------------------------------------
    # 3. Recalcular GSF excluindo Itaipu
    # ----------------------------------------------------------
    print("\n" + "=" * 75)
    print("[3] GSF RECALCULADO — V2 normal vs V2 excl_itaipu")
    print("=" * 75)

    # V2: PARTICIPANTE_MRE = 'Sim'
    df_v2 = df_uhe[
        df_uhe["PARTICIPANTE_MRE"].astype(str).str.strip().str.upper() == "SIM"
    ].copy()
    df_v2_excl_itaipu = df_v2[~df_v2["COD_PARCELA_USINA"].isin(cod_itaipu)]

    print(f"\n{'mes':>6} {'oficial':>9}   "
          f"{'V2_norm':>9} {'diff_norm':>10}   "
          f"{'V2_excl':>9} {'diff_excl':>10}   status   itaipu_contrib")

    meses_alvo = sorted(GSF_OFICIAL.keys())
    diffs_excl = []
    hits = 0
    for m in meses_alvo:
        gf = gf_map.get(m)
        if gf is None:
            print(f"  {m}  skip (GF nao encontrada — provavel 202303)")
            continue
        h = horas_mes(m)
        oficial = GSF_OFICIAL[m]
        sub_norm = df_v2[df_v2["MES_REFERENCIA"] == m]
        sub_excl = df_v2_excl_itaipu[df_v2_excl_itaipu["MES_REFERENCIA"] == m]
        if sub_norm.empty:
            print(f"  {m}  skip (sem dado UHE_V2)")
            continue
        num_norm = sub_norm["MEDICAO_GERACAO_MENSAL"].sum()
        num_excl = sub_excl["MEDICAO_GERACAO_MENSAL"].sum()
        itaipu_contrib = num_norm - num_excl
        itaipu_pct_num = itaipu_contrib / num_norm * 100 if num_norm else 0

        gsf_norm = num_norm / (gf * h) * 100
        gsf_excl = num_excl / (gf * h) * 100
        diff_norm = gsf_norm - oficial
        diff_excl = gsf_excl - oficial
        diffs_excl.append(diff_excl)
        status = "HIT" if abs(diff_excl) < 1 else "fail"
        if abs(diff_excl) < 1:
            hits += 1
        print(f"  {m}  {oficial:>8.2f}%  "
              f"{gsf_norm:>8.2f}% {diff_norm:>+9.3f}   "
              f"{gsf_excl:>8.2f}% {diff_excl:>+9.3f}   {status:>5}   "
              f"{itaipu_contrib:>13,.0f} ({itaipu_pct_num:.2f}%)")

    # ----------------------------------------------------------
    # 4. Resumo + criterio
    # ----------------------------------------------------------
    print("\n[4] RESUMO HIPOTESE B:")
    print(f"  Pontos testados: {len(diffs_excl)}")
    print(f"  Acertos V2_excl_itaipu dentro de +/-1pp: {hits}/{len(diffs_excl)}")
    if diffs_excl:
        print(f"  Mean abs diff: {sum(abs(d) for d in diffs_excl)/len(diffs_excl):.3f} pp")
        print(f"  Max  abs diff: {max(abs(d) for d in diffs_excl):.3f} pp")
        # Sinal residual
        n_pos = sum(1 for d in diffs_excl if d > 0)
        n_neg = sum(1 for d in diffs_excl if d < 0)
        print(f"  Sinal: {n_pos} positivos, {n_neg} negativos")

    print(f"\n  Power BI publico CCEE tem toggle 'Todas as Usinas / Exceto")
    print(f"  Itaipu' — reforca tratamento separado de Itaipu em GSF SIN.")

    if hits >= 6:
        print(f"\n  >>> HIPOTESE B CONFIRMADA ({hits}/{len(diffs_excl)} hits)")
        print(f"  >>> Formula final: GSF = sum(MEDICAO[PARTICIPANTE_MRE='Sim'")
        print(f"  >>>                       E cod_parcela NOT IN itaipu]) /")
        print(f"  >>>                       (GF_REDE_BASICA * horas) * 100")
    elif hits >= 3:
        print(f"\n  >>> HIPOTESE B PARCIAL ({hits}). Talvez tem 'Itaipu B'")
        print(f"  >>> ou outras UHEs com regime especial.")
    else:
        print(f"\n  >>> HIPOTESE B INSUFICIENTE ({hits}/{len(diffs_excl)}).")

    print("\n[FIM]")


if __name__ == "__main__":
    main()
