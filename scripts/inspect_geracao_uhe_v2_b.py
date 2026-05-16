"""
inspect_geracao_uhe_v2_b.py — Phase 0 caminho A — refinamento.

Hipotese: GSF_SIN = sum(MEDICAO_GERACAO_MENSAL_MWh) / (GF_REDE_BASICA_MWm * horas)
ja eh quase certa. O vies de +3-5pp se deve a soma de multiplos
EVENTO_CONTABIL por (mes, parcela). Solucao: filtrar pro evento mais
recente por parcela em cada mes.

Tambem testa filtros adicionais:
    - PARTICIPANTE_MRE == 'Sim' (suspeita: ja todos sao)
    - STATUS_OPERACAO_USINA == 'Ativo'
    - TIPO_DESPACHO especifico

Tambem amplia pra 2024 (extra cobertura) e tenta jul/2024 / mar/2023.
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
    "Accept": "application/json,text/csv,*/*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": "https://dadosabertos.ccee.org.br/",
}
BASE = "https://dadosabertos.ccee.org.br/api/3/action"


# Resource IDs descobertos
GERACAO_UHE_V2 = {
    "2012-2024": "721aa775",  # nao usamos no smoke test; baixar de outro arquivo
    2025: "233f2e7c-...",  # vou descobrir ids exatos via package_show
    2026: "2b097181-...",
}
MRE_MENSAL_IDS = {
    2023: "cbcd5631-1a64-42f3-ad58-480c7b177388",
    2024: "5665c103-8223-47de-b581-9b3853f0609f",
    2025: "9c333d24-398f-4eda-8cc0-4e6ff95d99a4",
    2026: "37fdbdf6-77f0-40e3-93c5-60e299e68376",
}

# Pontos oficiais CCEE
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


def ckan_paginated(resource_id: str, max_rows: int = 1_000_000) -> Optional[pd.DataFrame]:
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


def parse_evento_ord(evento: str) -> tuple[int, int, int]:
    """Extrai (ano, mes, ordinal) do EVENTO_CONTABIL pra ordenar.
    Ex: '2025_01 - 3ª RECONTABILIZAÇÃO' -> (2025, 1, 3)
        '2024_07 - APURAÇÃO' -> (2024, 7, 0)  [base, antes das recontab]
        '2024_07 - CONTABILIZAÇÃO INICIAL' -> (2024, 7, 0)
    Quanto MAIOR o ordinal, mais recente.
    """
    if not evento:
        return (0, 0, -1)
    e = str(evento).upper()
    # ano_mes na frente
    m = re.match(r"(\d{4})_(\d{2})", e)
    ano = int(m.group(1)) if m else 0
    mes = int(m.group(2)) if m else 0
    # ordinal de recontab
    mr = re.search(r"(\d+)\s*[ªa\.]\s*RECONTAB", e)
    if mr:
        ordinal = int(mr.group(1))
    elif "APURAC" in e or "INICIAL" in e or "1ª " in e or "PRIMEIRA" in e:
        ordinal = 0
    else:
        ordinal = -1  # desconhecido
    return (ano, mes, ordinal)


def main():
    # ----------------------------------------------------------
    # 1. Pegar IDs exatos via package_show
    # ----------------------------------------------------------
    print("[1] Descobrindo IDs exatos via package_show:")
    pkg = get_json(f"{BASE}/package_show",
                   {"id": "0e4fdbef-7c85-44bf-a68c-cff808bd4449"})
    pkg = pkg.get("result", {})
    uhe_ids = {}
    for r in pkg.get("resources", []):
        nm = r.get("name") or ""
        if r.get("format", "").upper() != "CSV":
            continue
        m = re.search(r"v2_(\d{4})(?:_(\d{4}))?", nm)
        if m:
            if m.group(2):
                # consolidado 2012-2024
                uhe_ids["historico"] = (r.get("id"), nm,
                                         (int(m.group(1)), int(m.group(2))))
            else:
                uhe_ids[int(m.group(1))] = (r.get("id"), nm, None)
    for k, v in uhe_ids.items():
        print(f"  {k}: id={v[0][:8]}  name={v[1]!r}")

    # ----------------------------------------------------------
    # 2. Baixar 2025, 2026 e historico (2012-2024)
    # ----------------------------------------------------------
    print("\n[2] Baixando GERACAO_UHE_V2 (2025 + 2026 + historico):")
    dfs_uhe = []
    for k, (rid, nm, _) in uhe_ids.items():
        print(f"  Baixando {nm!r}...")
        t0 = time.time()
        df = ckan_paginated(rid, max_rows=2_000_000)
        elapsed = time.time() - t0
        if df is None:
            print(f"    ! vazio ({elapsed:.1f}s)")
            continue
        print(f"    {len(df):,} linhas em {elapsed:.1f}s")
        dfs_uhe.append(df)

    if not dfs_uhe:
        print("  ! sem dados")
        return
    df_uhe = pd.concat(dfs_uhe, ignore_index=True)
    df_uhe["MES_REFERENCIA"] = df_uhe["MES_REFERENCIA"].astype(str)
    df_uhe["MEDICAO_GERACAO_MENSAL"] = pd.to_numeric(
        df_uhe["MEDICAO_GERACAO_MENSAL"], errors="coerce",
    )
    print(f"\n  Total UHE consolidado: {len(df_uhe):,} linhas")
    print(f"  Meses cobertos: {df_uhe['MES_REFERENCIA'].nunique()} "
          f"({df_uhe['MES_REFERENCIA'].min()} a "
          f"{df_uhe['MES_REFERENCIA'].max()})")
    print(f"  PARTICIPANTE_MRE distribuicao:")
    print(df_uhe["PARTICIPANTE_MRE"].value_counts().to_string())
    print(f"  STATUS_OPERACAO_USINA distribuicao:")
    print(df_uhe["STATUS_OPERACAO_USINA"].value_counts().to_string())
    print(f"  TIPO_DESPACHO distribuicao:")
    print(df_uhe["TIPO_DESPACHO"].value_counts().to_string())

    # ----------------------------------------------------------
    # 3. Analise dos EVENTO_CONTABIL por mes
    # ----------------------------------------------------------
    print("\n[3] EVENTO_CONTABIL — quantos por mes?")
    counts_por_mes = (
        df_uhe.groupby("MES_REFERENCIA")["EVENTO_CONTABIL"]
        .nunique().sort_index()
    )
    print(counts_por_mes.tail(15).to_string())
    print(f"\n  Eventos unicos para 202502 (fev/2025):")
    eventos_022025 = df_uhe[df_uhe["MES_REFERENCIA"] == "202502"]["EVENTO_CONTABIL"].unique()
    for e in eventos_022025:
        ord_info = parse_evento_ord(e)
        n_parcelas = (df_uhe[
            (df_uhe["MES_REFERENCIA"] == "202502")
            & (df_uhe["EVENTO_CONTABIL"] == e)
        ]).shape[0]
        print(f"    ord={ord_info[2]:>3}  n_parcelas={n_parcelas:>4}  {e!r}")

    # ----------------------------------------------------------
    # 4. Aplicar filtro pelo evento mais recente por mes
    # ----------------------------------------------------------
    print("\n[4] Filtrar pelo EVENTO_CONTABIL mais recente por mes:")
    df_uhe["_evento_ord"] = df_uhe["EVENTO_CONTABIL"].apply(
        lambda x: parse_evento_ord(x)[2]
    )
    # Para cada mes, pega o maior ord
    ev_max_por_mes = (
        df_uhe.groupby("MES_REFERENCIA")["_evento_ord"].max()
    )
    df_uhe["_ev_max_do_mes"] = df_uhe["MES_REFERENCIA"].map(ev_max_por_mes)
    df_uhe_last_ev = df_uhe[
        df_uhe["_evento_ord"] == df_uhe["_ev_max_do_mes"]
    ].copy()
    print(f"  Linhas antes do filtro: {len(df_uhe):,}")
    print(f"  Linhas depois do filtro (last evento): {len(df_uhe_last_ev):,}")

    # ----------------------------------------------------------
    # 5. Baixar GF_REDE_BASICA pra todos os anos necessarios
    # ----------------------------------------------------------
    print("\n[5] Baixar MRE_MENSAL pra obter GARANTIA_FISICA_REDE_BASICA:")
    dfs_mre = []
    for ano, rid in MRE_MENSAL_IDS.items():
        df = ckan_paginated(rid)
        if df is not None:
            dfs_mre.append(df)
    df_mre = pd.concat(dfs_mre, ignore_index=True)
    df_mre["MES_REFERENCIA"] = df_mre["MES_REFERENCIA"].astype(str)
    df_mre["GARANTIA_FISICA_REDE_BASICA"] = pd.to_numeric(
        df_mre["GARANTIA_FISICA_REDE_BASICA"], errors="coerce",
    )
    gf_map = df_mre.set_index("MES_REFERENCIA")["GARANTIA_FISICA_REDE_BASICA"].to_dict()
    print(f"  MRE_MENSAL meses: {len(df_mre)}")

    # ----------------------------------------------------------
    # 6. Calcular GSF com varias variantes
    # ----------------------------------------------------------
    print("\n" + "=" * 75)
    print("[6] CALCULAR GSF com varias variantes")
    print("=" * 75)

    meses_alvo = sorted(GSF_OFICIAL.keys())
    print(f"\n{'mes':>6} {'oficial':>8}   "
          f"{'V0_all':>8} {'V1_lastev':>10} "
          f"{'V2_lev_mre':>10} {'V3_lev_mre_ativo':>17}")

    for m in meses_alvo:
        gf = gf_map.get(m)
        if gf is None:
            print(f"  {m}: GF nao encontrada em MRE_MENSAL")
            continue
        h = horas_mes(m)
        oficial = GSF_OFICIAL[m]

        # V0: tudo somado (com double-count de eventos)
        v0 = df_uhe[df_uhe["MES_REFERENCIA"] == m]["MEDICAO_GERACAO_MENSAL"].sum()
        v0_gsf = v0 / (gf * h) * 100 if gf else None

        # V1: last evento por mes
        v1_df = df_uhe_last_ev[df_uhe_last_ev["MES_REFERENCIA"] == m]
        v1 = v1_df["MEDICAO_GERACAO_MENSAL"].sum()
        v1_gsf = v1 / (gf * h) * 100 if gf else None

        # V2: last evento + PARTICIPANTE_MRE == 'Sim'
        v2_df = v1_df[v1_df["PARTICIPANTE_MRE"].astype(str).str.strip()
                       .str.upper() == "SIM"]
        v2 = v2_df["MEDICAO_GERACAO_MENSAL"].sum()
        v2_gsf = v2 / (gf * h) * 100 if gf else None

        # V3: V2 + STATUS_OPERACAO_USINA == 'Ativo'
        v3_df = v2_df[v2_df["STATUS_OPERACAO_USINA"].astype(str).str.strip()
                       == "Ativo"]
        v3 = v3_df["MEDICAO_GERACAO_MENSAL"].sum()
        v3_gsf = v3 / (gf * h) * 100 if gf else None

        print(f"  {m} {oficial:>7.2f}%  "
              f"{v0_gsf:>7.2f}% {v1_gsf:>9.2f}% "
              f"{v2_gsf:>9.2f}% {v3_gsf:>16.2f}%")

    # ----------------------------------------------------------
    # 7. Diferenca por mes na variante vencedora (provavel V1)
    # ----------------------------------------------------------
    print("\n[7] DIFF (V1 - oficial) — coluna final:")
    print(f"{'mes':>6} {'oficial':>8} {'V1_lastev':>10} {'diff_pp':>8}")
    diffs = []
    for m in meses_alvo:
        gf = gf_map.get(m)
        if gf is None:
            continue
        h = horas_mes(m)
        oficial = GSF_OFICIAL[m]
        v1_df = df_uhe_last_ev[df_uhe_last_ev["MES_REFERENCIA"] == m]
        v1 = v1_df["MEDICAO_GERACAO_MENSAL"].sum()
        v1_gsf = v1 / (gf * h) * 100
        d = v1_gsf - oficial
        diffs.append(d)
        ok = "OK" if abs(d) < 1 else "FAIL"
        print(f"  {m} {oficial:>7.2f}% {v1_gsf:>9.2f}% "
              f"{d:>+7.3f}  {ok}")
    if diffs:
        print(f"\n  Max abs diff: {max(abs(d) for d in diffs):.3f} pp")
        print(f"  Mean abs diff: {sum(abs(d) for d in diffs)/len(diffs):.3f} pp")
        n_ok = sum(1 for d in diffs if abs(d) < 1)
        print(f"  Dentro de +/-1pp: {n_ok}/{len(diffs)}")

    print("\n[FIM]")


if __name__ == "__main__":
    main()
