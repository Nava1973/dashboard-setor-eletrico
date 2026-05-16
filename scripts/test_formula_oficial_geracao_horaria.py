"""
test_formula_oficial_geracao_horaria.py — Phase 0 TESTE DECISIVO.

Fonte: Regras de Comercializacao CCEE, modulo MRE, item MR.2.1
        + dataset CCEE GERACAO_HORARIA_SUBMERCADO

Formula oficial:
    GSF_mes = sum(GERACAO_MRE) / sum(GARANTIA_FISICA_MODULADA_MRE)

Ambos campos:
  - vem do dataset GERACAO_HORARIA_SUBMERCADO (horario, por submercado)
  - estao "no centro de gravidade" (perdas internas + rede basica +
    fator disponibilidade ja descontados)
  - somar 4 submercados x ~720 horas/mes

Criterio: 13+/15 hits dentro de +/-0.5pp -> CONFIRMADO.
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
    print("TESTE DECISIVO — formula oficial CCEE (MR.2.1)")
    print("=" * 75)

    # ----------------------------------------------------------
    # 1. Discovery do pacote GERACAO_HORARIA_SUBMERCADO
    # ----------------------------------------------------------
    print("\n[1] Discovery: pacote GERACAO_HORARIA_SUBMERCADO no CKAN CCEE")
    pkg = None
    for q in ["geracao horaria submercado", "geracao_horaria_submercado",
              "geracao horaria"]:
        try:
            data = get_json(f"{BASE}/package_search", {"q": q, "rows": 50})
        except Exception as e:
            print(f"  ! q={q!r}: {type(e).__name__}: {e}")
            continue
        if not data.get("success"):
            continue
        for p in data["result"]["results"]:
            t = (p.get("title") or "").upper()
            n = (p.get("name") or "").upper()
            if "GERACAO_HORARIA_SUBMERCADO" in n or "GERACAO_HORARIA_SUBMERCADO" in t:
                print(f"  Encontrado: title={p.get('title')!r} "
                      f"name={p.get('name')!r} id={p.get('id')}")
                pkg = p
                break
        if pkg:
            break

    if pkg is None:
        print("  ! Pacote nao encontrado por package_search. Tentando")
        print("    package_show direto pelo name conhecido...")
        try:
            pkg = get_json(f"{BASE}/package_show",
                           {"id": "geracao_horaria_submercado"}).get("result")
            if pkg:
                print(f"  Encontrado via package_show: title={pkg.get('title')!r}")
        except Exception as e:
            print(f"  ! falhou: {type(e).__name__}: {e}")

    if pkg is None:
        print("  ! ABORTANDO — pacote nao localizado")
        return

    # Notes oficial
    notes = pkg.get("notes") or ""
    if notes:
        print(f"\n  Notes do pacote (300 chars):")
        print(f"    {notes[:300]}")

    # ----------------------------------------------------------
    # 2. Listar e baixar recursos CSV
    # ----------------------------------------------------------
    resources = pkg.get("resources", [])
    print(f"\n[2] Recursos do pacote: {len(resources)}")
    import re
    YEAR_RE = re.compile(r"(20\d{2})")
    csv_resources = []
    for r in resources:
        nm = r.get("name") or ""
        fmt = (r.get("format") or "").upper()
        rid = r.get("id") or ""
        m = YEAR_RE.search(nm) or YEAR_RE.search(r.get("url") or "")
        ano = int(m.group(1)) if m else None
        print(f"  - name={nm[:50]:50} fmt={fmt:6} ano={ano} id={rid[:8]}")
        if fmt == "CSV":
            csv_resources.append((ano, nm, rid))

    if not csv_resources:
        print("  ! Nenhum CSV — abortando")
        return

    csv_resources.sort(key=lambda x: (x[0] or 0), reverse=True)
    print(f"\n  Anos detectados: {sorted({a for a, *_ in csv_resources if a})}")

    # ----------------------------------------------------------
    # 3. Baixar TUDO
    # ----------------------------------------------------------
    print("\n[3] Baixar todos os anos disponiveis:")
    dfs = []
    for ano, nm, rid in csv_resources:
        print(f"  {nm}...", end=" ", flush=True)
        t = time.time()
        df = ckan_paginated(rid)
        if df is not None:
            print(f"{len(df):,} linhas ({time.time()-t:.1f}s)")
            dfs.append(df)
        else:
            print("FAIL")

    if not dfs:
        print("  ! Nenhum download — abortando")
        return

    df = pd.concat(dfs, ignore_index=True)
    print(f"\n  Total consolidado: {len(df):,} linhas, {df.shape[1]} colunas")
    print(f"  Colunas: {list(df.columns)}")

    # ----------------------------------------------------------
    # 4. Inspecionar schema rapidamente + identificar colunas chave
    # ----------------------------------------------------------
    print(f"\n[4] Sample head(3) + dtypes:")
    print(df.head(3).to_string())
    print(f"\n  Dtypes:")
    print(df.dtypes.to_string())

    # Detectar colunas relevantes
    col_mes = None
    col_subm = None
    col_geracao_mre = None
    col_gf_mre = None
    col_periodo = None
    for c in df.columns:
        cn = str(c).upper()
        if col_mes is None and ("MES_REF" in cn or "ANO_MES" in cn or "MES" == cn):
            col_mes = c
        if col_subm is None and ("SUBMERCADO" in cn or "SUBSIST" in cn):
            col_subm = c
        if col_geracao_mre is None and "GERACAO_MRE" in cn:
            col_geracao_mre = c
        if col_gf_mre is None and ("GARANTIA_FISICA_MODULADA_MRE" in cn
                                    or "GF_MODULADA_MRE" in cn):
            col_gf_mre = c
        if col_periodo is None and (
            "PERIODO_COMERCIALIZACAO" in cn or "HORA" in cn
        ):
            col_periodo = c

    print(f"\n  Colunas-chave identificadas:")
    print(f"    mes_referencia : {col_mes!r}")
    print(f"    submercado     : {col_subm!r}")
    print(f"    GERACAO_MRE    : {col_geracao_mre!r}")
    print(f"    GF_MOD_MRE     : {col_gf_mre!r}")
    print(f"    periodo/hora   : {col_periodo!r}")

    if col_geracao_mre is None or col_gf_mre is None:
        print("\n  ! Colunas-chave nao localizadas. Tentando substring largo:")
        for c in df.columns:
            cn = str(c).upper()
            if "GERACAO" in cn or "GARANTIA" in cn or "MRE" in cn:
                print(f"    candidato: {c!r}")
        return

    if col_mes is None:
        print("  ! Coluna de mes nao localizada — abortando")
        return

    # Cardinalidade do submercado
    if col_subm:
        print(f"\n  Valores unicos do submercado: "
              f"{df[col_subm].dropna().unique().tolist()}")

    # ----------------------------------------------------------
    # 5. Aplicar formula oficial
    # ----------------------------------------------------------
    df[col_mes] = df[col_mes].astype(str)
    df[col_geracao_mre] = pd.to_numeric(df[col_geracao_mre], errors="coerce")
    df[col_gf_mre] = pd.to_numeric(df[col_gf_mre], errors="coerce")

    # somar por mes (todos submercados + todos periodos)
    agg = df.groupby(col_mes).agg(
        sum_geracao=(col_geracao_mre, "sum"),
        sum_gf=(col_gf_mre, "sum"),
        n_linhas=(col_geracao_mre, "count"),
    )
    agg["gsf_calc"] = agg["sum_geracao"] / agg["sum_gf"] * 100
    agg = agg.sort_index()
    print(f"\n  Meses cobertos: {len(agg)} (range "
          f"{agg.index.min()} a {agg.index.max()})")

    # ----------------------------------------------------------
    # 6. Comparar com 15 pontos oficiais
    # ----------------------------------------------------------
    print("\n" + "=" * 75)
    print("[6] COMPARACAO contra 15 pontos oficiais")
    print("=" * 75)
    print(f"\n{'mes':>6}  {'oficial':>9}  {'calc':>9}  "
          f"{'diff_pp':>9}  {'n_linhas':>9}  status")

    hits_05 = 0
    hits_10 = 0
    diffs = []
    total = 0
    meses_alvo = sorted(GSF_OFICIAL.keys())
    for m in meses_alvo:
        oficial = GSF_OFICIAL[m]
        if m not in agg.index:
            print(f"  {m}  {oficial:>8.2f}%  n/d        n/d         n/d  fora")
            continue
        calc = agg.loc[m, "gsf_calc"]
        n = int(agg.loc[m, "n_linhas"])
        diff = calc - oficial
        diffs.append(diff)
        total += 1
        if abs(diff) < 0.5:
            hits_05 += 1
            st = "HIT(0.5)"
        elif abs(diff) < 1.0:
            hits_10 += 1
            st = "hit(1.0)"
        else:
            st = "fail"
        print(f"  {m}  {oficial:>8.2f}%  {calc:>8.2f}%  "
              f"{diff:>+8.3f}  {n:>9,}  {st}")

    # ----------------------------------------------------------
    # 7. Resumo
    # ----------------------------------------------------------
    print(f"\n[7] RESUMO:")
    print(f"  Pontos comparados:   {total}/{len(meses_alvo)}")
    print(f"  Hits dentro +/-0.5pp: {hits_05}")
    print(f"  Hits +/-0.5 a 1.0pp: {hits_10}")
    print(f"  Total +/-1.0pp:      {hits_05 + hits_10}")
    if diffs:
        print(f"  Mean abs diff: {sum(abs(d) for d in diffs)/len(diffs):.4f} pp")
        print(f"  Max  abs diff: {max(abs(d) for d in diffs):.4f} pp")
        print(f"  Mean diff (com sinal): {sum(diffs)/len(diffs):+.4f} pp")

    print(f"\n  Criterio: 13+/15 hits +/-0.5pp -> CONFIRMA formula oficial")
    if hits_05 >= 13:
        print(f"\n  >>> FORMULA OFICIAL CONFIRMADA ({hits_05}/{total} hits)")
        print(f"  >>> GSF = sum(GERACAO_MRE) / sum(GARANTIA_FISICA_MODULADA_MRE)")
        print(f"  >>> Fonte: GERACAO_HORARIA_SUBMERCADO, somar 4 submercados x periodos")
        print(f"  >>> Fim da Fase 0. Parte pra Fase 1 (data loader).")
    elif hits_05 >= 10:
        print(f"\n  >>> RESULTADO PARCIAL ({hits_05}/{total} <0.5pp, "
              f"{hits_05+hits_10}/{total} <1pp).")
        print(f"  >>> Investigar nuances (estado especial, filtro adicional, etc.)")
    else:
        print(f"\n  >>> NAO CONFIRMADO ({hits_05}/{total} <0.5pp).")

    # Print tambem todos os meses cobertos com gsf calc (pra contexto)
    print(f"\n[8] GSF calc por todos os meses cobertos no dataset (contexto):")
    print(agg[["sum_geracao", "sum_gf", "gsf_calc", "n_linhas"]].to_string())

    print("\n[FIM]")


if __name__ == "__main__":
    main()
