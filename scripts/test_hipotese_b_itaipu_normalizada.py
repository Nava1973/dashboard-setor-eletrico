"""
test_hipotese_b_itaipu_normalizada.py — Phase 0 Hipotese B refinada.

Premissa atualizada: GSF oficial CCEE no toggle 'Todas as Usinas' INCLUI
Itaipu, mas NORMALIZADA (nao a geracao bruta binacional).

Hipoteses:
  B1) Itaipu entra so com 50% da geracao (Tratado).
  B2) Itaipu entra so com a fracao ANDE-Eletrobras contratada.
  B3) ENTREGA_MRE_ITAIPU (do MRE_HORARIO) JA reflete a normalizacao.

Teste:
  1. Somar ENTREGA_MRE_ITAIPU por mes (MRE_HORARIO) e comparar com
     MEDICAO_GERACAO_MENSAL de Itaipu (GERACAO_UHE_V2).
  2. Calcular razao -> revela qual hipotese aplica.
  3. Recalcular GSF substituindo Itaipu por ENTREGA_MRE_ITAIPU.
  4. Criterio: 12+/15 dentro de +/-1pp.

Tambem testa B4 (50% Itaipu) e B5 (RECEBIDA tambem) como sanity checks.

Tabela GSF_OFICIAL atualizada com 15 pontos (9 Power BI + 6 InfoPLD).
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

# 15 pontos validados:
# - 9 do Power BI CCEE (https://www.ccee.org.br/en/dados-e-analises/dados-geracao)
# - 6 do InfoPLD novo (3 pontos em comum batem ate 0.03pp com Power BI)
# Excluidos: mar/26 (94.6%) e abr/26 (102.0%) do InfoPLD — sao projecoes DECOMP,
# nao realizado.
GSF_OFICIAL = {
    # do Power BI CCEE
    "202303": 101.564,
    "202307":  77.957,
    "202403":  95.041,
    "202407":  84.975,
    "202501": 113.213,
    "202502": 110.957,
    "202507":  69.330,
    "202601":  81.207,
    "202602": 100.318,
    # do InfoPLD (validados contra Power BI nos 3 meses em comum)
    "202506":  87.700,
    "202508":  62.600,
    "202509":  63.000,
    "202510":  63.100,
    "202511":  65.700,
    "202512":  73.600,
}

ITAIPU_COD_PARCELA = 416


def get_json(url, params=None):
    r = http.get(url, params=params or {}, headers=BROWSER_HEADERS,
                 impersonate="chrome", timeout=60)
    r.raise_for_status()
    return r.json()


def ckan_paginated(resource_id: str, max_rows: int = 5_000_000) -> Optional[pd.DataFrame]:
    base = f"{BASE}/datastore_search"
    rows = []
    offset = 0
    limit = 1000
    while True:
        try:
            r = http.get(
                base,
                params={"resource_id": resource_id, "limit": limit, "offset": offset},
                headers=BROWSER_HEADERS, impersonate="chrome", timeout=180,
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
    print("HIPOTESE B REFINADA — Itaipu via ENTREGA_MRE_ITAIPU (MRE_HORARIO)")
    print("=" * 75)

    # ----------------------------------------------------------
    # 0. Pre-flight: tamanho do MRE_HORARIO
    # ----------------------------------------------------------
    print("\n[0] Pre-flight: tamanho do MRE_HORARIO")
    pkg_h = get_json(f"{BASE}/package_show",
                     {"id": "e64640a5-309a-49e4-82c0-b0a95ff514d0"})
    pkg_h = pkg_h.get("result", {})
    res_h = sorted(
        [r for r in pkg_h.get("resources", [])
         if (r.get("format") or "").upper() == "CSV"],
        key=lambda x: x.get("name") or "", reverse=True,
    )
    print(f"  Recursos CSV: {len(res_h)}")
    for r in res_h:
        sz = r.get("size") or 0
        print(f"    - {r.get('name')!r}  size={sz}")

    # ----------------------------------------------------------
    # 1. Baixar MRE_HORARIO inteiro
    # ----------------------------------------------------------
    print("\n[1] Baixar MRE_HORARIO (todos os anos disponiveis):")
    dfs_h = []
    for r in res_h:
        nm = r.get("name")
        rid = r.get("id")
        print(f"  {nm}...", end=" ")
        t = time.time()
        df = ckan_paginated(rid)
        if df is not None:
            print(f"{len(df):,} linhas ({time.time()-t:.1f}s)")
            dfs_h.append(df)
        else:
            print("FAIL")

    df_h = pd.concat(dfs_h, ignore_index=True)
    df_h["MES_REFERENCIA"] = df_h["MES_REFERENCIA"].astype(str)
    for c in ("ENTREGA_MRE_ITAIPU", "RECEBIDA_MRE_ITAIPU",
              "ENERGIA_SECUNDARIA", "ENTREGA_MRE", "RECEBIDA_MRE"):
        if c in df_h.columns:
            df_h[c] = pd.to_numeric(df_h[c], errors="coerce")
    print(f"\n  Total MRE_HORARIO: {len(df_h):,} linhas")
    print(f"  Meses cobertos: {df_h['MES_REFERENCIA'].min()} a "
          f"{df_h['MES_REFERENCIA'].max()}")
    print(f"  Numero meses distintos: {df_h['MES_REFERENCIA'].nunique()}")

    # ----------------------------------------------------------
    # 2. Baixar GERACAO_UHE_V2 (numerador)
    # ----------------------------------------------------------
    print("\n[2] Baixar GERACAO_UHE_V2:")
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
    df_uhe_v2 = df_uhe[
        df_uhe["PARTICIPANTE_MRE"].astype(str).str.strip().str.upper() == "SIM"
    ].copy()

    # ----------------------------------------------------------
    # 3. Baixar MRE_MENSAL (GF_RB)
    # ----------------------------------------------------------
    print("\n[3] Baixar MRE_MENSAL (GF):")
    dfs_mre = []
    for ano, rid in MRE_MENSAL_IDS.items():
        df = ckan_paginated(rid)
        if df is not None:
            dfs_mre.append(df)
    df_mre = pd.concat(dfs_mre, ignore_index=True)
    df_mre["MES_REFERENCIA"] = df_mre["MES_REFERENCIA"].astype(str)
    df_mre["GARANTIA_FISICA_REDE_BASICA"] = pd.to_numeric(
        df_mre["GARANTIA_FISICA_REDE_BASICA"], errors="coerce"
    )
    gf_map = df_mre.set_index("MES_REFERENCIA")[
        "GARANTIA_FISICA_REDE_BASICA"
    ].to_dict()

    # ----------------------------------------------------------
    # 4. Comparar ENTREGA_MRE_ITAIPU vs MEDICAO Itaipu
    # ----------------------------------------------------------
    print("\n" + "=" * 75)
    print("[4] COMPARAR ENTREGA_MRE_ITAIPU somada vs MEDICAO Itaipu (UHE_V2)")
    print("=" * 75)

    df_h_agg = df_h.groupby("MES_REFERENCIA").agg(
        sum_entrega_itaipu=("ENTREGA_MRE_ITAIPU", "sum"),
        sum_recebida_itaipu=("RECEBIDA_MRE_ITAIPU", "sum"),
        sum_entrega_total=("ENTREGA_MRE", "sum"),
        sum_recebida_total=("RECEBIDA_MRE", "sum"),
        sum_energia_secundaria=("ENERGIA_SECUNDARIA", "sum"),
        n_periodos=("ENTREGA_MRE_ITAIPU", "count"),
    )

    df_itaipu_v2 = df_uhe_v2[df_uhe_v2["COD_PARCELA_USINA"] == ITAIPU_COD_PARCELA]
    itaipu_geracao_por_mes = df_itaipu_v2.groupby("MES_REFERENCIA")[
        "MEDICAO_GERACAO_MENSAL"
    ].sum().to_dict()

    print(f"\n{'mes':>6}  {'horario_entr':>14}  {'horario_receb':>14}  "
          f"{'uhe_v2_itaipu':>14}  {'razao_E/G':>9}  {'razao_R/G':>9}")
    meses_alvo = sorted(GSF_OFICIAL.keys())
    for m in meses_alvo:
        ger_uhe = itaipu_geracao_por_mes.get(m)
        if m not in df_h_agg.index:
            ger_str = f"{ger_uhe:>14,.0f}" if ger_uhe else "n/d"
            print(f"  {m}: nao em MRE_HORARIO (uhe_v2={ger_str})")
            continue
        row = df_h_agg.loc[m]
        e = row["sum_entrega_itaipu"]
        rcb = row["sum_recebida_itaipu"]
        razao_e = (e / ger_uhe) if ger_uhe else None
        razao_r = (rcb / ger_uhe) if ger_uhe else None
        ger_str = f"{ger_uhe:>14,.0f}" if ger_uhe else "         n/d  "
        e_str = f"{e:>14,.0f}" if pd.notna(e) else "         n/d  "
        r_str = f"{rcb:>14,.0f}" if pd.notna(rcb) else "         n/d  "
        re_str = f"{razao_e:.4f}" if razao_e is not None else "n/d"
        rr_str = f"{razao_r:.4f}" if razao_r is not None else "n/d"
        print(f"  {m}  {e_str}  {r_str}  {ger_str}  "
              f"{re_str:>9}  {rr_str:>9}")

    # ----------------------------------------------------------
    # 5. Calcular GSF com varias variantes
    # ----------------------------------------------------------
    print("\n" + "=" * 75)
    print("[5] GSF COM VARIANTES DE NORMALIZACAO DE ITAIPU")
    print("=" * 75)
    print("""
  V2_norm      = baseline (Itaipu 100% como MEDICAO)
  B3_entr      = substituir Itaipu por ENTREGA_MRE_ITAIPU
  B3_net       = substituir Itaipu por (ENTREGA - RECEBIDA)_ITAIPU
  B1_50pct     = Itaipu * 0.5
""")

    sum_geracao_sem_itaipu_por_mes = (
        df_uhe_v2[df_uhe_v2["COD_PARCELA_USINA"] != ITAIPU_COD_PARCELA]
        .groupby("MES_REFERENCIA")["MEDICAO_GERACAO_MENSAL"].sum().to_dict()
    )

    print(f"\n{'mes':>6} {'oficial':>9}  {'V2_norm':>9}{'d_norm':>7}  "
          f"{'B3_entr':>9}{'d':>7}  {'B3_net':>9}{'d':>7}  "
          f"{'B1_50pct':>10}{'d':>7}")

    rows_out = []
    for m in meses_alvo:
        gf = gf_map.get(m)
        if gf is None:
            print(f"  {m}  skip (sem GF — provavel 202303)")
            continue
        h = horas_mes(m)
        oficial = GSF_OFICIAL[m]

        sem_itaipu = sum_geracao_sem_itaipu_por_mes.get(m, 0)
        itaipu_uhe = itaipu_geracao_por_mes.get(m, 0)

        # V2_norm: Itaipu 100%
        num_norm = sem_itaipu + itaipu_uhe
        gsf_norm = num_norm / (gf * h) * 100 if num_norm else None

        # B3: substituir Itaipu por ENTREGA_MRE_ITAIPU
        if m in df_h_agg.index:
            entrega_it = df_h_agg.loc[m, "sum_entrega_itaipu"]
            receb_it = df_h_agg.loc[m, "sum_recebida_itaipu"]
        else:
            entrega_it = None
            receb_it = None

        if entrega_it is not None and pd.notna(entrega_it):
            num_b3_entr = sem_itaipu + entrega_it
            gsf_b3_entr = num_b3_entr / (gf * h) * 100
            num_b3_net = sem_itaipu + entrega_it - (receb_it or 0)
            gsf_b3_net = num_b3_net / (gf * h) * 100
        else:
            gsf_b3_entr = None
            gsf_b3_net = None

        # B1: Itaipu * 0.5
        num_b1 = sem_itaipu + itaipu_uhe * 0.5
        gsf_b1 = num_b1 / (gf * h) * 100 if num_b1 else None

        diff_norm = (gsf_norm - oficial) if gsf_norm else None
        diff_b3_entr = (gsf_b3_entr - oficial) if gsf_b3_entr else None
        diff_b3_net = (gsf_b3_net - oficial) if gsf_b3_net else None
        diff_b1 = (gsf_b1 - oficial) if gsf_b1 else None

        def fmt(v):
            return f"{v:>+6.2f}" if v is not None else "  n/d "
        def fmtg(v):
            return f"{v:>8.2f}%" if v is not None else "  n/d  "

        print(f"  {m} {oficial:>8.2f}%  "
              f"{fmtg(gsf_norm)}{fmt(diff_norm)}  "
              f"{fmtg(gsf_b3_entr)}{fmt(diff_b3_entr)}  "
              f"{fmtg(gsf_b3_net)}{fmt(diff_b3_net)}  "
              f"{fmtg(gsf_b1)}{fmt(diff_b1)}")

        rows_out.append({
            "mes": m, "oficial": oficial,
            "norm": gsf_norm,
            "B3_entr": gsf_b3_entr, "B3_net": gsf_b3_net,
            "B1_50pct": gsf_b1,
        })

    # ----------------------------------------------------------
    # 6. Resumo / hits por variante
    # ----------------------------------------------------------
    print("\n[6] RESUMO de acertos (+/-1pp):")
    if rows_out:
        for variant in ("norm", "B3_entr", "B3_net", "B1_50pct"):
            diffs = [r[variant] - r["oficial"] for r in rows_out
                     if r[variant] is not None]
            n = len(diffs)
            if not n:
                continue
            hits = sum(1 for d in diffs if abs(d) < 1)
            mean_abs = sum(abs(d) for d in diffs) / n
            max_abs = max(abs(d) for d in diffs)
            sign_pos = sum(1 for d in diffs if d > 0)
            sign_neg = sum(1 for d in diffs if d < 0)
            print(f"  {variant:>12}: {hits:>2}/{n} hits, "
                  f"mean={mean_abs:6.3f}pp, max={max_abs:6.3f}pp  "
                  f"sinal: +{sign_pos}/-{sign_neg}")

    print("\n  Criterio (15 pontos validados):")
    print("    12+/15 hits dentro de +/-1pp -> CONFIRMA")
    print("     8-11/15 hits                 -> parcial")
    print("    <8/15 hits                    -> rejeita")

    print("\n[FIM]")


if __name__ == "__main__":
    main()
