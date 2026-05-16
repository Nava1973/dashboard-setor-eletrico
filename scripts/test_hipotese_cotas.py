"""
test_hipotese_cotas.py — Phase 0 Opcao 2 (Hipotese COTAS).

ULTIMO script de inspecao heuristica. Se nao confirmar, paramos e
buscamos evidencia externa (documento oficial CCEE).

Hipotese: o vies multiplicativo +1.5% vem de duplicacao parcial entre
parcelas COTAS (Lei 12.783/2013) e parcelas ACL/livre representando
a mesma planta fisica. Removendo COTAS (ou ACL), o vies zera.

Estrutura:
  1. Listar TODAS as colunas de GERACAO_UHE_V2 + valores unicos das
     categoricas.
  2. Buscar flag PARTICIPANTE_REGIME_COTAS ou similar.
  3. Testar 3 variantes: V2_norm, V2_excl_cotas, V2_apenas_cotas.
  4. Identificar pares (USINA, USINA COTAS) por sigla.
  5. Criterio: V2_excl_cotas com 12+/14 hits +/-1pp -> CONFIRMA.

GSF_OFICIAL: 15 pontos (9 Power BI + 6 InfoPLD).
"""
from __future__ import annotations

import re
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
    "202506":  87.700,
    "202508":  62.600,
    "202509":  63.000,
    "202510":  63.100,
    "202511":  65.700,
    "202512":  73.600,
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
    print("HIPOTESE COTAS — ULTIMO TESTE DE INSPECAO")
    print("=" * 75)

    # ----------------------------------------------------------
    # 1. Baixar GERACAO_UHE_V2 + listar TODAS as colunas + categoricas
    # ----------------------------------------------------------
    print("\n[1] BAIXAR GERACAO_UHE_V2 e listar TODAS as colunas")
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

    print(f"\n  Schema completo de GERACAO_UHE_V2:")
    print(f"  Total linhas: {len(df_uhe):,}")
    print(f"  Colunas: {list(df_uhe.columns)}")
    for c in df_uhe.columns:
        dt = df_uhe[c].dtype
        nu = df_uhe[c].nunique()
        # se categorica (poucas categorias), listar
        if nu < 20 and dt == object:
            vals = df_uhe[c].value_counts().head(10).to_dict()
            print(f"\n    {c!r} (dtype={dt}, unicos={nu}):")
            for k, v in vals.items():
                print(f"      {k!r}: {v:,}")
        else:
            sample = df_uhe[c].dropna().head(3).tolist()
            sample_s = ", ".join(repr(x)[:30] for x in sample)
            print(f"\n    {c!r} (dtype={dt}, unicos={nu})  ex: {sample_s}")

    # ----------------------------------------------------------
    # 2. Buscar flag COTAS / REGIME
    # ----------------------------------------------------------
    print("\n[2] BUSCAR FLAGS RELACIONADAS A COTAS")
    flag_cotas = None
    for c in df_uhe.columns:
        cn = str(c).upper()
        if "COTA" in cn or "REGIME" in cn:
            print(f"  Possivel flag: {c!r}")
            vals = df_uhe[c].value_counts().to_dict()
            print(f"    Valores: {vals}")
            if flag_cotas is None:
                flag_cotas = c

    # ----------------------------------------------------------
    # 3. Inspecionar siglas com "COTAS" no nome
    # ----------------------------------------------------------
    print("\n[3] PARCELAS com 'COTAS' / 'COTA' NA SIGLA")
    sigla_col = "SIGLA_PARCELA_USINA"
    mask_cotas_sigla = df_uhe[sigla_col].astype(str).str.upper().str.contains(
        r"COTA", na=False, regex=True
    )
    df_cotas = df_uhe[mask_cotas_sigla]
    print(f"  Linhas com 'COTA' na sigla: {len(df_cotas):,}")
    print(f"  Parcelas distintas: {df_cotas['COD_PARCELA_USINA'].nunique()}")
    # listar essas parcelas
    sample_cotas = df_cotas.drop_duplicates("COD_PARCELA_USINA")
    print(f"\n  Lista das parcelas COTAS (primeiras 30):")
    for _, row in sample_cotas.head(30).iterrows():
        print(f"    COD={row['COD_PARCELA_USINA']:>9}  "
              f"sigla={row[sigla_col]!r:<35}  "
              f"part_mre={row['PARTICIPANTE_MRE']!r}")

    # ----------------------------------------------------------
    # 4. Identificar pares ACL + COTAS pela sigla
    # ----------------------------------------------------------
    print("\n[4] IDENTIFICAR PARES (USINA ACL + USINA COTAS)")
    # extrair siglas base (sem "COTAS"/"ACL"/"COTA")
    def base_sigla(s):
        s = str(s).upper().strip()
        for sfx in (" COTAS", " COTA", " ACL", " LIVRE", " CCEAL"):
            if s.endswith(sfx):
                return s[:-len(sfx)].strip()
        # tambem remove sufixos com parenteses
        s = re.sub(r"\s*\([^)]+\)\s*$", "", s).strip()
        return s

    # criar mapa base -> [parcelas]
    all_parcelas = df_uhe.drop_duplicates("COD_PARCELA_USINA")
    all_parcelas = all_parcelas.copy()
    all_parcelas["_base"] = all_parcelas[sigla_col].apply(base_sigla)
    base_grupos = all_parcelas.groupby("_base").agg(
        n=("COD_PARCELA_USINA", "count"),
        siglas=(sigla_col, lambda x: list(x)),
        cods=("COD_PARCELA_USINA", lambda x: list(x)),
    )
    base_grupos_dup = base_grupos[base_grupos["n"] >= 2].sort_values("n", ascending=False)
    print(f"  Grupos com 2+ parcelas pela mesma base: {len(base_grupos_dup)}")
    print(f"\n  Primeiros 20 grupos (potenciais duplicacoes):")
    for base, row in base_grupos_dup.head(20).iterrows():
        print(f"    base={base!r}  n={row['n']}")
        for sg, cd in zip(row["siglas"], row["cods"]):
            print(f"      cod={cd:>9}  sigla={sg!r}")

    # ----------------------------------------------------------
    # 5. Sanity check: numa data, ver se ger(ACL) + ger(COTAS) excede GF
    # ----------------------------------------------------------
    print("\n[5] SANITY: somar geracao de pares ACL+COTAS em 202602")
    df_test = df_uhe[df_uhe["MES_REFERENCIA"] == "202602"].copy()
    df_test["_base"] = df_test[sigla_col].apply(base_sigla)
    bases_dup_set = set(base_grupos_dup.index.tolist())
    df_test_pares = df_test[df_test["_base"].isin(bases_dup_set)]
    grupo_test = df_test_pares.groupby("_base").agg(
        n=("COD_PARCELA_USINA", "count"),
        soma_geracao=("MEDICAO_GERACAO_MENSAL", "sum"),
        max_parcela=("MEDICAO_GERACAO_MENSAL", "max"),
    ).sort_values("soma_geracao", ascending=False)
    print(f"\n  Top 10 grupos por soma_geracao em fev/2026:")
    for base, row in grupo_test.head(10).iterrows():
        print(f"    base={base!r:<25}  n={row['n']}  "
              f"soma={row['soma_geracao']:>14,.0f}  "
              f"max_parcela={row['max_parcela']:>14,.0f}")

    # ----------------------------------------------------------
    # 6. Baixar MRE_MENSAL (GF) e testar variantes
    # ----------------------------------------------------------
    print("\n[6] Baixar MRE_MENSAL e calcular variantes:")
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

    # V2 base: PARTICIPANTE_MRE = 'Sim'
    df_v2 = df_uhe[
        df_uhe["PARTICIPANTE_MRE"].astype(str).str.strip().str.upper() == "SIM"
    ].copy()

    # Identificar parcelas COTAS (por SIGLA contendo COTA)
    cotas_cods = set(df_uhe[mask_cotas_sigla]["COD_PARCELA_USINA"].unique())
    print(f"\n  Parcelas COTAS identificadas (cods): {len(cotas_cods)}")

    df_v2_excl_cotas = df_v2[~df_v2["COD_PARCELA_USINA"].isin(cotas_cods)]
    df_v2_apenas_cotas = df_v2[df_v2["COD_PARCELA_USINA"].isin(cotas_cods)]

    # se houver flag explicita PARTICIPANTE_REGIME_COTAS, testar com ela tambem
    df_v2_excl_cotas_flag = None
    if flag_cotas:
        df_v2_excl_cotas_flag = df_v2[
            df_v2[flag_cotas].astype(str).str.strip().str.upper() != "SIM"
        ]

    # ----------------------------------------------------------
    # 7. Calcular GSF para os 15 meses com cada variante
    # ----------------------------------------------------------
    print("\n" + "=" * 75)
    print("[7] GSF: V2_norm vs V2_excl_cotas (por sigla) vs V2_apenas_cotas")
    if flag_cotas:
        print(f"    vs V2_excl_cotas_flag (por flag {flag_cotas!r})")
    print("=" * 75)

    header = (f"\n{'mes':>6} {'oficial':>9}  "
              f"{'V2_norm':>9}{'d':>7}  "
              f"{'excl_cotas':>11}{'d':>7}  "
              f"{'apenas_cotas':>13}{'d':>7}")
    if flag_cotas:
        header += "  excl_cotas_flag" + " " * 5 + "d"
    print(header)

    meses_alvo = sorted(GSF_OFICIAL.keys())
    rows_out = []
    for m in meses_alvo:
        gf = gf_map.get(m)
        if gf is None:
            print(f"  {m}  skip (sem GF — 202303)")
            continue
        h = horas_mes(m)
        oficial = GSF_OFICIAL[m]

        num_norm = df_v2[df_v2["MES_REFERENCIA"] == m][
            "MEDICAO_GERACAO_MENSAL"
        ].sum()
        num_excl = df_v2_excl_cotas[df_v2_excl_cotas["MES_REFERENCIA"] == m][
            "MEDICAO_GERACAO_MENSAL"
        ].sum()
        num_apenas = df_v2_apenas_cotas[
            df_v2_apenas_cotas["MES_REFERENCIA"] == m
        ]["MEDICAO_GERACAO_MENSAL"].sum()

        gsf_norm = num_norm / (gf * h) * 100
        gsf_excl = num_excl / (gf * h) * 100 if num_excl else 0
        gsf_apenas = num_apenas / (gf * h) * 100

        d_norm = gsf_norm - oficial
        d_excl = gsf_excl - oficial if num_excl else None
        d_apenas = gsf_apenas - oficial

        row = {
            "mes": m, "oficial": oficial,
            "norm": gsf_norm, "d_norm": d_norm,
            "excl_cotas": gsf_excl, "d_excl": d_excl,
            "apenas_cotas": gsf_apenas, "d_apenas": d_apenas,
        }

        line = (f"  {m} {oficial:>8.2f}%  "
                f"{gsf_norm:>8.2f}% {d_norm:>+6.2f}  "
                f"{gsf_excl:>10.2f}% {d_excl:>+6.2f}  "
                f"{gsf_apenas:>12.2f}% {d_apenas:>+6.2f}")

        if df_v2_excl_cotas_flag is not None:
            num_flag = df_v2_excl_cotas_flag[
                df_v2_excl_cotas_flag["MES_REFERENCIA"] == m
            ]["MEDICAO_GERACAO_MENSAL"].sum()
            gsf_flag = num_flag / (gf * h) * 100 if num_flag else 0
            d_flag = gsf_flag - oficial
            row["excl_cotas_flag"] = gsf_flag
            row["d_flag"] = d_flag
            line += f"  {gsf_flag:>15.2f}% {d_flag:>+6.2f}"

        print(line)
        rows_out.append(row)

    # ----------------------------------------------------------
    # 8. Resumo
    # ----------------------------------------------------------
    print("\n[8] RESUMO de acertos (+/-1pp):")
    variantes = [("V2_norm", "norm"), ("excl_cotas (sigla)", "excl_cotas"),
                 ("apenas_cotas", "apenas_cotas")]
    if df_v2_excl_cotas_flag is not None:
        variantes.append(("excl_cotas (flag)", "excl_cotas_flag"))

    for label, key in variantes:
        diffs = [(r[key] - r["oficial"]) for r in rows_out
                 if r.get(key) is not None]
        n = len(diffs)
        if not n:
            continue
        hits = sum(1 for d in diffs if abs(d) < 1)
        mean_abs = sum(abs(d) for d in diffs) / n
        max_abs = max(abs(d) for d in diffs)
        n_pos = sum(1 for d in diffs if d > 0)
        n_neg = sum(1 for d in diffs if d < 0)
        print(f"  {label:>22}: {hits:>2}/{n} hits, "
              f"mean={mean_abs:6.3f}pp, max={max_abs:6.3f}pp  "
              f"sinal: +{n_pos}/-{n_neg}")

    print("\n  Criterio (15 pontos, 14 cobertos):")
    print("    12+/14 hits dentro de +/-1pp -> CONFIRMA cotas")
    print("    senao -> reporta e para investigacao heuristica")

    print("\n[FIM]")


if __name__ == "__main__":
    main()
