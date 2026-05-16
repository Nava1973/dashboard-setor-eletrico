"""
inspect_geracao_uhe_v2.py — Phase 0 caminho A.

Hipotese: GERACAO_UHE_V2 contem a geracao mensal por usina (MWh ou MWmed).
Cruzando com lista de usinas MRE (MRE_GF_MODULADA_USINA), calculamos GSF SIN:

    GSF = sum(geracao_uhe_mre_mwmed) / GARANTIA_FISICA_REDE_BASICA_mwmed
ou
    GSF = sum(geracao_uhe_mre_mwh) / (GF_REDE_BASICA_mwmed * horas_mes)

Meses-alvo (com valores oficiais CCEE):
    jul/2025 -> 69,33%
    fev/2025 -> 110,96%
    jan/2026 -> 81,21%

Tolerancia: +/- 1pp em 2 de 3 -> confirma fonte.
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
    "Accept": "application/json,text/csv,*/*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": "https://dadosabertos.ccee.org.br/",
}
BASE = "https://dadosabertos.ccee.org.br/api/3/action"


# Do v2: GF_REDE_BASICA_MWmed por mes (apurado MRE_MENSAL).
# Estes valores ja foram baixados e validados.
GF_REDE_BASICA_POR_MES = {
    "202407": 47928.744076,
    "202502": 52753.576430,
    "202507": 52697.708953,
    "202601": 59592.613111,
    "202602": 55441.537635,
}
# Pontos oficiais CCEE (Power BI) — referencia
GSF_OFICIAL = {
    "202407": 84.975,
    "202502": 110.957,
    "202507": 69.330,
    "202601": 81.207,
    "202602": 100.318,
}


def get_json(url, params=None):
    r = http.get(url, params=params or {}, headers=BROWSER_HEADERS,
                 impersonate="chrome", timeout=60)
    r.raise_for_status()
    return r.json()


def ckan_paginated(resource_id: str, max_rows: int = 500000,
                   filters: dict | None = None) -> Optional[pd.DataFrame]:
    """Pagina datastore_search. filters={} usa CKAN filtering server-side."""
    base = f"{BASE}/datastore_search"
    rows = []
    offset = 0
    limit = 1000
    while True:
        params = {"resource_id": resource_id, "limit": limit, "offset": offset}
        if filters:
            import json as _json
            params["filters"] = _json.dumps(filters)
        try:
            r = http.get(base, params=params, headers=BROWSER_HEADERS,
                         impersonate="chrome", timeout=90)
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            print(f"    ! offset={offset}: {type(e).__name__}: {e}")
            return pd.DataFrame(rows) if rows else None
        if not payload.get("success"):
            print(f"    ! payload success=false")
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
    print("PHASE 0 CAMINHO A — TESTE GERACAO_UHE_V2 + MRE list")
    print("=" * 75)

    # ----------------------------------------------------------
    # 1. Descobrir pacote GERACAO_UHE_V2
    # ----------------------------------------------------------
    print("\n[1] Descobrir pacote GERACAO_UHE_V2 no CKAN:")
    pkg_uhe = None
    for q in ["geracao uhe", "geracao_uhe", "geracao_uhe_v2"]:
        try:
            data = get_json(f"{BASE}/package_search", {"q": q, "rows": 200})
        except Exception as e:
            print(f"    ! {q}: {type(e).__name__}: {e}")
            continue
        if not data.get("success"):
            continue
        for p in data["result"]["results"]:
            n = (p.get("name") or "").upper()
            t = (p.get("title") or "").upper()
            if "GERACAO_UHE" in n or "GERACAO_UHE" in t:
                print(f"    encontrado: title={p.get('title')!r} "
                      f"name={p.get('name')!r} id={p.get('id')}")
                # priorizar V2
                if "V2" in n or "V2" in t:
                    pkg_uhe = p
                elif pkg_uhe is None:
                    pkg_uhe = p

    if pkg_uhe is None:
        print("  ! nao encontrei GERACAO_UHE_V2 — abortando")
        return

    print(f"\n  Selecionado: {pkg_uhe.get('name')!r}")
    print(f"  ID: {pkg_uhe.get('id')}")
    notes = pkg_uhe.get("notes") or ""
    if notes:
        print(f"  Notes (300 chars): {notes[:300]}")

    resources = pkg_uhe.get("resources", [])
    print(f"  Recursos: {len(resources)}")
    import re
    YEAR_RE = re.compile(r"(20\d{2})")
    csv_resources = []
    for r in resources:
        nm = r.get("name") or ""
        fmt = (r.get("format") or "").upper()
        rid = r.get("id") or ""
        m = YEAR_RE.search(nm) or YEAR_RE.search(r.get("url") or "")
        ano = int(m.group(1)) if m else None
        print(f"    - name={nm[:45]:45} fmt={fmt:6} ano={ano} id={rid[:8]}")
        if fmt == "CSV" and ano in (2024, 2025, 2026):
            csv_resources.append((ano, nm, rid))

    if not csv_resources:
        print("  ! nenhum CSV pra 2024/2025/2026")
        return

    # ----------------------------------------------------------
    # 2. Baixar 2025 e 2026 inteiros
    # ----------------------------------------------------------
    print("\n[2] Baixando GERACAO_UHE_V2 2025 e 2026 (inteiros):")
    dfs_uhe = {}
    for ano, nm, rid in csv_resources:
        if ano not in (2025, 2026):
            continue
        print(f"\n  Baixando {nm!r} (rid={rid[:8]})...")
        t0 = time.time()
        df = ckan_paginated(rid, max_rows=500000)
        elapsed = time.time() - t0
        if df is None or df.empty:
            print(f"    ! vazio (tempo: {elapsed:.1f}s)")
            continue
        print(f"    OK: {len(df):,} linhas em {elapsed:.1f}s, "
              f"{df.shape[1]} colunas")
        dfs_uhe[ano] = df

    if not dfs_uhe:
        print("  ! nenhum ano baixado")
        return

    # ----------------------------------------------------------
    # 3. Inspecao do schema
    # ----------------------------------------------------------
    df_sample = next(iter(dfs_uhe.values()))
    print("\n[3] SCHEMA do GERACAO_UHE_V2 (sample do primeiro ano baixado):")
    print(f"  Colunas:")
    for c in df_sample.columns:
        non_null = df_sample[c].notna().sum()
        ex = df_sample[c].dropna().head(3).tolist()
        ex_str = ", ".join(repr(x)[:25] for x in ex)
        print(f"    {c!r:35} dtype={str(df_sample[c].dtype):12} "
              f"non_null={non_null:6}  ex: {ex_str}")
    print(f"\n  Head(3):")
    print(df_sample.head(3).to_string())

    # ----------------------------------------------------------
    # 4. Detectar colunas-chave
    # ----------------------------------------------------------
    print("\n[4] Detectar colunas-chave:")
    col_mes = None
    col_geracao = None
    col_usina = None
    col_perfil_agente = None
    col_parcela = None
    col_sigla = None

    for c in df_sample.columns:
        cn = str(c).upper()
        if col_mes is None and ("MES" in cn or "ANOMES" in cn):
            col_mes = c
        if col_geracao is None and ("GERACAO" in cn or "VALOR" in cn
                                     or "VOLUME" in cn or "ENERGIA" in cn):
            col_geracao = c
        if col_usina is None and ("USINA" in cn or "PARCELA" in cn
                                   or "EMPREEND" in cn):
            col_usina = c
        if col_perfil_agente is None and (
            "COD_PERF_AGENTE" in cn or "COD_AGENTE" in cn
            or "PERFIL_AGENTE" in cn
        ):
            col_perfil_agente = c
        if col_parcela is None and ("PARCELA" in cn or "COD_PARCELA" in cn):
            col_parcela = c
        if col_sigla is None and ("SIGLA" in cn):
            col_sigla = c

    print(f"  mes_referencia       -> {col_mes!r}")
    print(f"  geracao              -> {col_geracao!r}")
    print(f"  usina/parcela        -> {col_usina!r}")
    print(f"  cod_perfil_agente    -> {col_perfil_agente!r}")
    print(f"  cod_parcela          -> {col_parcela!r}")
    print(f"  sigla                -> {col_sigla!r}")

    # tentativa adicional pra geracao numerica
    cols_num_candidatas = []
    for c in df_sample.columns:
        try:
            vals = pd.to_numeric(df_sample[c], errors="coerce").dropna()
            if len(vals) > 100 and vals.max() > 10:
                cols_num_candidatas.append((c, vals.mean(), vals.max()))
        except Exception:
            continue
    print(f"\n  Colunas numericas candidatas (top 5 por max):")
    cols_num_candidatas.sort(key=lambda x: -x[2])
    for c, mean, mx in cols_num_candidatas[:8]:
        print(f"    {c!r:40} mean={mean:>12.2f} max={mx:>12.2f}")

    # ----------------------------------------------------------
    # 5. Baixar lista de usinas MRE de MRE_GF_MODULADA_USINA
    # ----------------------------------------------------------
    print("\n[5] Baixar lista de usinas MRE de MRE_GF_MODULADA_USINA:")
    # 2025 e 2026 (mesma estrutura)
    pkg_mre = get_json(f"{BASE}/package_show",
                       {"id": "de057e31-780b-4530-ba4a-e03a29c3b6e3"})
    pkg_mre = pkg_mre.get("result", {})
    res_mre = [r for r in pkg_mre.get("resources", [])
               if (r.get("format") or "").upper() == "CSV"]
    res_mre_ord = sorted(res_mre, key=lambda x: x.get("name") or "",
                         reverse=True)
    dfs_mre = []
    for r in res_mre_ord[:2]:  # 2025 + 2026
        nm = r.get("name")
        rid = r.get("id")
        print(f"  Baixando {nm!r} (rid={rid[:8]})...")
        df_m = ckan_paginated(rid, max_rows=100000)
        if df_m is not None:
            print(f"    {len(df_m):,} linhas")
            dfs_mre.append(df_m)
    if not dfs_mre:
        print("  ! falhou")
        return
    df_mre_full = pd.concat(dfs_mre, ignore_index=True)
    df_mre_full["MES_REFERENCIA"] = df_mre_full["MES_REFERENCIA"].astype(str)
    print(f"  Total consolidado: {len(df_mre_full):,} (perfil-usina-mes)")
    print(f"  Colunas: {list(df_mre_full.columns)}")
    print(f"  Range meses: {df_mre_full['MES_REFERENCIA'].min()} a "
          f"{df_mre_full['MES_REFERENCIA'].max()}")

    # ----------------------------------------------------------
    # 6. Calcular GSF para os 3 meses-alvo testando 2 formulas
    # ----------------------------------------------------------
    print("\n" + "=" * 75)
    print("[6] CALCULAR GSF para meses-alvo (jul/2025, fev/2025, jan/2026)")
    print("    + extras: jul/2024, fev/2026")
    print("=" * 75)

    # consolida GERACAO_UHE_V2
    df_uhe_full = pd.concat(dfs_uhe.values(), ignore_index=True)
    if col_mes:
        df_uhe_full[col_mes] = df_uhe_full[col_mes].astype(str)
    print(f"  GERACAO_UHE consolidado: {len(df_uhe_full):,} linhas")

    if not col_geracao or not col_mes:
        print("  ! Sem coluna de geracao ou mes — abortando")
        return

    # converter geracao pra float
    df_uhe_full["_gen_num"] = pd.to_numeric(
        df_uhe_full[col_geracao], errors="coerce",
    )
    print(f"  Range geracao: {df_uhe_full['_gen_num'].min():.4f} a "
          f"{df_uhe_full['_gen_num'].max():,.2f}")

    # horas por mes
    def horas_mes(mref):
        ano = int(mref[:4])
        mes = int(mref[4:6])
        return pd.Timestamp(f"{ano}-{mes:02d}-01").days_in_month * 24

    meses_alvo = ["202407", "202502", "202507", "202601", "202602"]

    # ---- Tentativa A: usar TODAS as usinas
    print("\n--- TENTATIVA A: somar TODA a geracao UHE (sem filtrar MRE) ---")
    print(f"{'mes':>6}  {'sum_gen':>16}  {'GF_RB(MWm)':>10}  "
          f"{'horas':>5}  {'F1_E/G':>9}  {'F2_E/(G*h)':>10}  "
          f"{'oficial':>8}")
    for m in meses_alvo:
        sub = df_uhe_full[df_uhe_full[col_mes] == m]
        if sub.empty:
            print(f"  {m}: nao encontrado em GERACAO_UHE_V2")
            continue
        soma = sub["_gen_num"].sum()
        gf = GF_REDE_BASICA_POR_MES.get(m)
        h = horas_mes(m)
        f1 = soma / gf if gf else None
        f2 = soma / (gf * h) if gf else None
        oficial = GSF_OFICIAL.get(m)
        print(f"  {m}  {soma:>16,.2f}  {gf:>10.2f}  {h:>5}  "
              f"{f1*100:>8.2f}%  {f2*100:>9.2f}%  {oficial:>7.2f}%")

    # ---- Tentativa B: filtrar apenas usinas que aparecem no MRE
    print("\n--- TENTATIVA B: somar APENAS usinas que aparecem no MRE ---")
    # Identificar coluna de join no df_mre_full
    # MRE_GF_MODULADA_USINA tem: COD_PERF_AGENTE, COD_PARCELA_USINA
    # GERACAO_UHE_V2 provavelmente tambem
    print(f"  Procurar chaves de join...")
    print(f"  df_mre cols: {list(df_mre_full.columns)}")
    print(f"  df_uhe cols: {list(df_uhe_full.columns)}")

    # join candidate
    join_perf = None
    join_parc = None
    for c in df_uhe_full.columns:
        cn = str(c).upper()
        if "COD_PERF_AGENTE" in cn:
            join_perf = c
            break
    for c in df_uhe_full.columns:
        cn = str(c).upper()
        if "COD_PARCELA" in cn:
            join_parc = c
            break

    print(f"  UHE_V2 join_perf={join_perf!r}, join_parc={join_parc!r}")

    if join_perf and join_parc:
        # Set de chaves MRE por mes
        df_mre_full["__chave"] = (
            df_mre_full["COD_PERF_AGENTE"].astype(str) + "|" +
            df_mre_full["COD_PARCELA_USINA"].astype(str)
        )
        df_uhe_full["__chave"] = (
            df_uhe_full[join_perf].astype(str) + "|" +
            df_uhe_full[join_parc].astype(str)
        )
        print(f"  Chaves unicas MRE: {df_mre_full['__chave'].nunique()}")
        print(f"  Chaves unicas UHE: {df_uhe_full['__chave'].nunique()}")
        # intersecao
        inter = set(df_mre_full["__chave"]) & set(df_uhe_full["__chave"])
        print(f"  Intersecao: {len(inter)} chaves")
        print(f"\n{'mes':>6}  {'sum_gen_MRE':>16}  {'GF_RB(MWm)':>10}  "
              f"{'horas':>5}  {'F1_E/G':>9}  {'F2_E/(G*h)':>10}  "
              f"{'oficial':>8}")
        for m in meses_alvo:
            # MRE deste mes
            mre_mes = set(
                df_mre_full[df_mre_full["MES_REFERENCIA"] == m]["__chave"]
            )
            sub = df_uhe_full[
                (df_uhe_full[col_mes] == m)
                & (df_uhe_full["__chave"].isin(mre_mes))
            ]
            if sub.empty:
                print(f"  {m}: sub vazia (mre_mes={len(mre_mes)})")
                continue
            soma = sub["_gen_num"].sum()
            gf = GF_REDE_BASICA_POR_MES.get(m)
            h = horas_mes(m)
            f1 = soma / gf if gf else None
            f2 = soma / (gf * h) if gf else None
            oficial = GSF_OFICIAL.get(m)
            print(f"  {m}  {soma:>16,.2f}  {gf:>10.2f}  {h:>5}  "
                  f"{f1*100:>8.2f}%  {f2*100:>9.2f}%  {oficial:>7.2f}%")
    else:
        print("  ! UHE_V2 sem COD_PERF_AGENTE/COD_PARCELA — sem join MRE")

    print("\n[FIM]")


if __name__ == "__main__":
    main()
