"""
diagnostico_geracao_horaria.py — diagnostico cirurgico das colunas.

Sem testar hipoteses — so imprimir numeros brutos pra 3 meses
representativos (surplus, deficit profundo, deficit moderado).

Meses:
  - 202602 (oficial 100.32%, surplus leve / neutro)
  - 202507 (oficial  69.33%, deficit profundo)
  - 202407 (oficial  84.97%, deficit moderado)

Colunas a inspecionar:
  GERACAO, GERACAO_MRE, GF_MRE, GF_MOD_MRE, FLUXO_ENERGIA_MRE,
  GF_SAZONALIZADA_MRE, GF_SAZONALIZADA_MRE_SEM_GF, GF_SAZONALIZADA_MRE_COM_GF,
  GF_SAZONALIZADA_NAO_HIDRO_COM_GF,
  GF_SAZONALIZADA_NAO_HIDRO_IA_IIA_SEM_GF,
  GF_SAZONALIZADA_NAO_HIDRO_IB_IIB_IIC_III_SEM_GF
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

RESOURCE_IDS = {
    2024: "9d619679",  # vou pegar full via package_show pra confirmar
    2025: "eeafc24a",
    2026: "4ff8ad16",
}

GSF_OFICIAL = {
    "202407":  84.975,
    "202507":  69.330,
    "202602": 100.318,
}


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


def main():
    print("=" * 75)
    print("DIAGNOSTICO — colunas GERACAO_HORARIA_SUBMERCADO")
    print("=" * 75)

    # ----------------------------------------------------------
    # Baixar 2024-2026 (cobre todos os 3 meses-alvo)
    # ----------------------------------------------------------
    print("\n[Download] GERACAO_HORARIA_SUBMERCADO 2024+2025+2026:")
    pkg = get_json(f"{BASE}/package_show",
                   {"id": "geracao_horaria_submercado"}).get("result")
    dfs = []
    for r in pkg.get("resources", []):
        if r.get("format", "").upper() != "CSV":
            continue
        nm = r.get("name") or ""
        rid = r.get("id")
        # so 2024+
        if not any(y in nm for y in ["2024", "2025", "2026"]):
            continue
        print(f"  {nm}...", end=" ", flush=True)
        t = time.time()
        df = ckan_paginated(rid)
        if df is not None:
            print(f"{len(df):,} ({time.time()-t:.1f}s)")
            dfs.append(df)
    df = pd.concat(dfs, ignore_index=True)
    df["MES_REFERENCIA"] = df["MES_REFERENCIA"].astype(str)

    # converter numericas
    cols_num = [
        "GERACAO", "GERACAO_MRE", "GARANTIA_FISICA_MRE",
        "GARANTIA_FISICA_MODULADA_MRE", "FLUXO_ENERGIA_MRE",
        "GARANTIA_FISICA_SAZONALIZADA_MRE",
        "GARANTIA_FISICA_SAZONALIZADA_MRE_SEM_GF",
        "GARANTIA_FISICA_SAZONALIZADA_MRE_COM_GF",
        "GARANTIA_FISICA_SAZONALIZADA_NAO_HIDRO_COM_GF",
        "GARANTIA_FISICA_SAZONALIZADA_NAO_HIDRO_IA_IIA_SEM_GF",
        "GARANTIA_FISICA_SAZONALIZADA_NAO_HIDRO_IB_IIB_IIC_III_SEM_GF",
    ]
    for c in cols_num:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    print(f"\n  Total: {len(df):,} linhas")
    print(f"  Range: {df['MES_REFERENCIA'].min()} a {df['MES_REFERENCIA'].max()}")

    # ----------------------------------------------------------
    # SECAO A: somas mensais (4 submercados x todas as horas)
    # ----------------------------------------------------------
    for mes_alvo in ["202407", "202507", "202602"]:
        oficial = GSF_OFICIAL[mes_alvo]
        print("\n" + "=" * 75)
        print(f"[{mes_alvo}] oficial = {oficial:.3f}%")
        print("=" * 75)
        sub = df[df["MES_REFERENCIA"] == mes_alvo]
        if sub.empty:
            print("  ! mes nao no dataset")
            continue
        n_linhas = len(sub)
        n_subm = sub["SUBMERCADO"].nunique()
        n_per = sub["PERIODO_COMERCIALIZACAO"].nunique()
        print(f"  Linhas: {n_linhas}  Submercados: {n_subm}  "
              f"Periodos: {n_per}")
        print(f"  Submercados presentes: "
              f"{sorted(sub['SUBMERCADO'].dropna().unique())}")

        # SUM por coluna (todos os submercados)
        print(f"\n  SOMA por coluna (4 submercados, {n_per} horas):")
        for c in cols_num:
            if c not in sub.columns:
                continue
            v = sub[c].sum()
            print(f"    {c:>55}  {v:>18,.2f}")

        # razao GERACAO / GERACAO_MRE
        sum_g = sub["GERACAO"].sum()
        sum_g_mre = sub["GERACAO_MRE"].sum()
        razao = sum_g / sum_g_mre if sum_g_mre else None
        print(f"\n  Razao GERACAO / GERACAO_MRE = "
              f"{razao:.4f}" if razao else "  Razao = n/d")

        # ratios
        print(f"\n  RATIOS (numerador / denominador):")
        num_options = [
            ("GERACAO_MRE", sum_g_mre),
            ("GERACAO", sum_g),
            ("GERACAO_MRE - FLUXO_ENERGIA_MRE",
             sum_g_mre - sub["FLUXO_ENERGIA_MRE"].sum()),
        ]
        den_options = []
        for c in ["GARANTIA_FISICA_MRE", "GARANTIA_FISICA_MODULADA_MRE",
                  "GARANTIA_FISICA_SAZONALIZADA_MRE",
                  "GARANTIA_FISICA_SAZONALIZADA_MRE_SEM_GF",
                  "GARANTIA_FISICA_SAZONALIZADA_MRE_COM_GF",
                  "GARANTIA_FISICA_SAZONALIZADA_NAO_HIDRO_COM_GF"]:
            if c in sub.columns:
                den_options.append((c, sub[c].sum()))

        print(f"\n    {'NUM':40}  {'DEN':50}  {'ratio%':>9}  diff_oficial")
        for nm_n, vn in num_options:
            for nm_d, vd in den_options:
                if vd == 0 or pd.isna(vd):
                    continue
                ratio = vn / vd * 100
                diff = ratio - oficial
                marker = " ✓" if abs(diff) < 0.5 else ("  " if abs(diff) > 5 else " ~")
                print(f"    {nm_n:40}  {nm_d:50}  {ratio:>8.2f}%  "
                      f"{diff:+8.3f}{marker}")

    # ----------------------------------------------------------
    # SECAO B: amostra de linha individual em jul/2025 SUDESTE periodo 1
    # ----------------------------------------------------------
    print("\n" + "=" * 75)
    print("[SAMPLE] Linha individual: 202507 SUDESTE periodo 1")
    print("=" * 75)
    sub_smp = df[
        (df["MES_REFERENCIA"] == "202507")
        & (df["SUBMERCADO"] == "SUDESTE")
        & (df["PERIODO_COMERCIALIZACAO"] == 1)
    ]
    if not sub_smp.empty:
        for _, row in sub_smp.iterrows():
            for c in sub_smp.columns:
                v = row[c]
                if isinstance(v, float):
                    print(f"    {c:>60}  =  {v:>20,.6f}")
                else:
                    print(f"    {c:>60}  =  {v!r}")

    # ----------------------------------------------------------
    # SECAO C: amostra 4 submercados em jul/2025 periodo 1 (visao SIN)
    # ----------------------------------------------------------
    print("\n" + "=" * 75)
    print("[SAMPLE SIN] 202507 periodo 1 — visao 4 submercados")
    print("=" * 75)
    sub_smp = df[
        (df["MES_REFERENCIA"] == "202507")
        & (df["PERIODO_COMERCIALIZACAO"] == 1)
    ]
    if not sub_smp.empty:
        cols_visual = [
            "SUBMERCADO", "GERACAO", "GERACAO_MRE",
            "GARANTIA_FISICA_MRE", "GARANTIA_FISICA_MODULADA_MRE",
            "FLUXO_ENERGIA_MRE",
            "GARANTIA_FISICA_SAZONALIZADA_MRE_COM_GF",
        ]
        cols_have = [c for c in cols_visual if c in sub_smp.columns]
        print(sub_smp[cols_have].to_string(index=False))
        print(f"\n  Soma horizontal (todos 4 submercados):")
        for c in cols_have:
            if c == "SUBMERCADO":
                continue
            s = sub_smp[c].sum()
            print(f"    {c:>50}  =  {s:>15,.2f}")
        # razao SIN nessa hora
        g_sin = sub_smp["GERACAO"].sum()
        g_mre_sin = sub_smp["GERACAO_MRE"].sum()
        gf_mod_sin = sub_smp["GARANTIA_FISICA_MODULADA_MRE"].sum()
        gf_saz_com_gf_sin = sub_smp[
            "GARANTIA_FISICA_SAZONALIZADA_MRE_COM_GF"
        ].sum()
        print(f"\n  Ratios nessa hora SIN:")
        print(f"    GERACAO/GF_MOD     = {g_sin/gf_mod_sin*100:.2f}%")
        print(f"    GERACAO_MRE/GF_MOD = {g_mre_sin/gf_mod_sin*100:.2f}%")
        print(f"    GERACAO/GF_SAZ_COM_GF = "
              f"{g_sin/gf_saz_com_gf_sin*100:.2f}%")
        print(f"    GERACAO_MRE/GF_SAZ_COM_GF = "
              f"{g_mre_sin/gf_saz_com_gf_sin*100:.2f}%")

    print("\n[FIM]")


if __name__ == "__main__":
    main()
