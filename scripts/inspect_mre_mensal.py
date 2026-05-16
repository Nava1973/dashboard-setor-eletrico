"""
inspect_mre_mensal.py — Phase 0 do sprint GSF.

Descobre o dataset MRE_MENSAL no portal CCEE Dados Abertos, baixa o CSV
do ano mais recente disponivel, inspeciona o schema real, calcula GSF
para 3 meses e confirma que FATOR_REDUCAO_ACUMULADO NAO eh o GSF.

Saida: relatorio impresso no stdout pra colar no chat / commitar como
docs/MRE_MENSAL_phase0.md.

Como rodar (da raiz do projeto):
    venv\\Scripts\\python.exe scripts\\inspect_mre_mensal.py
"""
from __future__ import annotations

import io
import json
import sys
from typing import Optional

import pandas as pd
from curl_cffi import requests as http


# ASCII puro pra evitar a armadilha 4.6 do CLAUDE.md (PowerShell + cp1252)
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


def get_json(url: str, params: dict | None = None) -> dict:
    r = http.get(
        url, params=params or {}, headers=BROWSER_HEADERS,
        impersonate="chrome", timeout=60,
    )
    r.raise_for_status()
    return r.json()


def find_package(name_hint: str) -> Optional[dict]:
    """Busca generica e devolve pacote cujo title/name contem a hint."""
    for q in ["mre", "ajuste mre", "fator de ajuste"]:
        data = get_json(f"{BASE}/package_search", {"q": q, "rows": 200})
        if not data.get("success"):
            continue
        for p in data["result"]["results"]:
            t = (p.get("title") or "").upper()
            n = (p.get("name") or "").upper()
            if name_hint.upper() in t or name_hint.upper() in n:
                return p
    return None


def list_all_mre_packages() -> list[dict]:
    """Lista todos os pacotes com 'mre' no nome/titulo."""
    pkgs = []
    seen_ids = set()
    for q in ["mre", "energia secundaria", "garantia fisica"]:
        try:
            data = get_json(f"{BASE}/package_search", {"q": q, "rows": 200})
        except Exception as e:
            print(f"  ! falha buscando q={q!r}: {type(e).__name__}: {e}")
            continue
        if not data.get("success"):
            continue
        for p in data["result"]["results"]:
            t = (p.get("title") or "").upper()
            n = (p.get("name") or "").upper()
            if "MRE" in t or "MRE" in n:
                pid = p.get("id")
                if pid not in seen_ids:
                    seen_ids.add(pid)
                    pkgs.append(p)
    return pkgs


def try_ckan_paginated(resource_id: str, max_rows: int = 50000) -> Optional[pd.DataFrame]:
    """API CKAN datastore_search paginada."""
    import time

    base = f"{BASE}/datastore_search"
    all_rows = []
    offset = 0
    limit = 1000

    while True:
        try:
            r = http.get(
                base,
                params={"resource_id": resource_id, "limit": limit, "offset": offset},
                headers=BROWSER_HEADERS,
                impersonate="chrome",
                timeout=60,
            )
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            print(f"    ! CKAN offset={offset}: {type(e).__name__}: {e}")
            return pd.DataFrame(all_rows) if all_rows else None

        if not payload.get("success"):
            return None
        rows = payload.get("result", {}).get("records", [])
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < limit or len(all_rows) >= max_rows:
            break
        offset += limit
        time.sleep(0.1)

    if not all_rows:
        return None
    return pd.DataFrame(all_rows)


def try_dump(resource_id: str) -> Optional[pd.DataFrame]:
    """Fallback via /datastore/dump/{id}?bom=True."""
    url = f"https://dadosabertos.ccee.org.br/datastore/dump/{resource_id}?bom=True"
    try:
        r = http.get(
            url, headers=BROWSER_HEADERS, impersonate="chrome", timeout=60,
        )
        r.raise_for_status()
    except Exception as e:
        print(f"    ! dump: {type(e).__name__}: {e}")
        return None

    for sep in [";", ","]:
        for enc in ["utf-8-sig", "utf-8", "latin-1"]:
            try:
                df = pd.read_csv(io.BytesIO(r.content), sep=sep, encoding=enc)
                if df.shape[1] >= 3:
                    return df
            except Exception:
                continue
    return None


def main():
    print("=" * 70)
    print("PHASE 0 — INSPECAO DATASET MRE_MENSAL (CCEE Dados Abertos)")
    print("=" * 70)

    # --- 1. Discovery: pacotes com MRE no titulo
    print("\n[1] DISCOVERY — pacotes MRE encontrados no CKAN CCEE:")
    pkgs = list_all_mre_packages()
    if not pkgs:
        print("  ! Nenhum pacote MRE encontrado. Tente variantes na busca.")
        return
    for p in pkgs:
        print(f"  - title={p.get('title')!r}")
        print(f"    name={p.get('name')!r}")
        print(f"    id={p.get('id')}")
        resources = p.get("resources", [])
        print(f"    recursos: {len(resources)}")

    # --- 2. Foco em MRE_MENSAL especificamente
    print("\n[2] BUSCA ESPECIFICA — pacote MRE_MENSAL:")
    pkg = None
    for p in pkgs:
        n = (p.get("name") or "").upper()
        if n == "MRE_MENSAL" or "MRE_MENSAL" in n:
            pkg = p
            break
    if not pkg:
        # Tenta tambem por title
        for p in pkgs:
            t = (p.get("title") or "").upper().replace(" ", "_")
            if "MRE_MENSAL" in t:
                pkg = p
                break

    if not pkg:
        print("  ! Pacote MRE_MENSAL nao encontrado. Pacotes disponiveis acima.")
        print("  ! Vou tentar usar o primeiro pacote MRE encontrado.")
        if pkgs:
            pkg = pkgs[0]
        else:
            return

    print(f"  Pacote selecionado: title={pkg.get('title')!r} name={pkg.get('name')!r}")
    print(f"  ID: {pkg.get('id')}")

    # --- 3. Listar recursos do pacote
    print("\n[3] RECURSOS DO PACOTE:")
    resources = pkg.get("resources", [])
    csv_resources = []
    for res in resources:
        nm = res.get("name") or ""
        fmt = (res.get("format") or "").upper()
        url = res.get("url") or ""
        rid = res.get("id") or ""
        print(f"  - name={nm[:50]:50} fmt={fmt:6} id={rid[:8]}")
        if fmt == "CSV":
            csv_resources.append((nm, rid, url))

    if not csv_resources:
        print("  ! Nenhum recurso CSV. Abortando.")
        return

    # --- 4. Escolher o ano mais recente
    print("\n[4] ESCOLHA DO RECURSO MAIS RECENTE:")
    import re
    YEAR_RE = re.compile(r"(20\d{2})")
    csv_resources_with_year = []
    for nm, rid, url in csv_resources:
        m = YEAR_RE.search(nm) or YEAR_RE.search(url)
        ano = int(m.group(1)) if m else None
        csv_resources_with_year.append((ano, nm, rid, url))

    csv_resources_with_year.sort(key=lambda x: (x[0] or 0), reverse=True)
    for ano, nm, rid, url in csv_resources_with_year[:6]:
        print(f"  - ano={ano} name={nm[:45]:45} id={rid[:8]}")

    ano_alvo, nm_alvo, rid_alvo, url_alvo = csv_resources_with_year[0]
    print(f"\n  >>> Alvo: ano={ano_alvo} name={nm_alvo!r} resource_id={rid_alvo}")

    # --- 5. Baixar via cascade
    print(f"\n[5] DOWNLOAD via cascade (ano={ano_alvo}):")
    df = None
    fonte = None

    print("  Tentativa 1: CKAN datastore_search paginado...")
    df = try_ckan_paginated(rid_alvo)
    if df is not None and not df.empty:
        fonte = "ckan_api"
        print(f"    -> OK: {len(df):,} linhas via CKAN")
    else:
        print("    -> falhou ou vazio")
        print("  Tentativa 2: dump endpoint...")
        df = try_dump(rid_alvo)
        if df is not None and not df.empty:
            fonte = "dump"
            print(f"    -> OK: {len(df):,} linhas via dump")
        else:
            print("    -> falhou")
            print("  Tentativa 3: URL direta...")
            try:
                r = http.get(
                    url_alvo, headers=BROWSER_HEADERS,
                    impersonate="chrome", timeout=60,
                )
                r.raise_for_status()
                for sep in [";", ","]:
                    for enc in ["utf-8-sig", "utf-8", "latin-1"]:
                        try:
                            df_try = pd.read_csv(
                                io.BytesIO(r.content), sep=sep, encoding=enc,
                            )
                            if df_try.shape[1] >= 3:
                                df = df_try
                                fonte = "url_direta"
                                break
                        except Exception:
                            continue
                    if df is not None:
                        break
                if df is not None:
                    print(f"    -> OK: {len(df):,} linhas via URL direta")
                else:
                    print("    -> falhou")
            except Exception as e:
                print(f"    -> falhou: {type(e).__name__}: {e}")

    if df is None or df.empty:
        print("\n  ! Nenhuma estrategia funcionou. Abortando inspecao.")
        return

    # --- 6. Inspecao de schema
    print("\n" + "=" * 70)
    print(f"[6] SCHEMA REAL (fonte={fonte}, linhas={len(df):,})")
    print("=" * 70)

    print("\n  Colunas:")
    for col in df.columns:
        non_null = df[col].notna().sum()
        sample = df[col].dropna().head(3).tolist()
        sample_str = ", ".join(repr(x)[:30] for x in sample)
        print(f"    {col!r:35} dtype={str(df[col].dtype):12} "
              f"non_null={non_null:6}  ex: {sample_str}")

    print("\n  Tipos detectados (dtypes):")
    print(df.dtypes.to_string())

    print("\n  Head(5):")
    print(df.head(5).to_string())

    # --- 7. MES_REFERENCIA: formato?
    print("\n[7] FORMATO DE MES_REFERENCIA:")
    col_mes = None
    for cand in ["MES_REFERENCIA", "MES_REF", "ANO_REF", "ANOMES"]:
        if cand in df.columns:
            col_mes = cand
            break
    if col_mes is None:
        # Procura por substring
        for c in df.columns:
            if "MES" in str(c).upper() or "REF" in str(c).upper():
                col_mes = c
                break

    if col_mes:
        valores_unicos = df[col_mes].dropna().unique()[:5]
        print(f"  Coluna usada: {col_mes!r}")
        print(f"  Valores unicos (5 primeiros): {list(valores_unicos)}")
        print(f"  dtype: {df[col_mes].dtype}")
        print(f"  Total de valores unicos: {df[col_mes].nunique()}")
    else:
        print("  ! Nao encontrei coluna de mes-referencia. Verificar manualmente.")

    # --- 8. Filtros e cardinalidade
    print("\n[8] FILTROS / CARDINALIDADE — linhas por MES_REFERENCIA:")
    if col_mes:
        contagem = df[col_mes].value_counts().sort_index()
        print(f"  Numero de meses distintos: {len(contagem)}")
        print(f"  Linhas por mes (5 primeiras):")
        print(contagem.head(5).to_string())
        print(f"  Linhas por mes (5 ultimas):")
        print(contagem.tail(5).to_string())
        n_por_mes = contagem.iloc[-3:].mean()
        print(f"\n  Media de linhas por mes (3 ultimos): {n_por_mes:.1f}")
        if n_por_mes > 1.5:
            print("  ! Multiplas linhas por mes — verificar colunas de filtro")
            for c in df.columns:
                cn = str(c).upper()
                if any(k in cn for k in ["OBJETIVO", "STATUS", "TIPO", "VERSAO",
                                          "PERFIL", "CENARIO", "CONTABIL"]):
                    print(f"    Coluna candidata a filtro: {c!r} "
                          f"unicos={df[c].nunique()} "
                          f"ex: {df[c].dropna().unique()[:5].tolist()}")

    # --- 9. CAMPOS-CHAVE: ENTREGA_MRE, GARANTIA_FISICA_REDE_BASICA,
    #                     FATOR_REDUCAO_ACUMULADO
    print("\n[9] CAMPOS-CHAVE PARA CALCULO DO GSF:")
    cols_relevantes = {}
    for c in df.columns:
        cn = str(c).upper()
        if "ENTREGA" in cn and "MRE" in cn:
            cols_relevantes["entrega"] = c
        elif "GARANTIA" in cn and ("FISICA" in cn or "REDE" in cn):
            cols_relevantes.setdefault("gf", c)
        elif "FATOR" in cn and ("REDUCAO" in cn or "AJUSTE" in cn):
            cols_relevantes.setdefault(cn.lower(), c)

    for k, v in cols_relevantes.items():
        sample = df[v].dropna().head(3).tolist()
        print(f"  {k:30} -> {v!r}  ex: {sample}")

    # --- 10. Calculo do GSF para 3 meses recentes
    print("\n[10] CALCULO DO GSF — ENTREGA_MRE / GARANTIA_FISICA_REDE_BASICA:")
    col_entrega = cols_relevantes.get("entrega")
    col_gf = cols_relevantes.get("gf")
    if col_entrega and col_gf and col_mes:
        # Locale numerico — converter vingula -> ponto se for string
        def to_float(v):
            if pd.isna(v):
                return None
            s = str(v).strip().replace(".", "").replace(",", ".")
            try:
                return float(s)
            except Exception:
                try:
                    return float(str(v).replace(",", "."))
                except Exception:
                    return None

        df_calc = df.copy()
        df_calc["entrega_num"] = df_calc[col_entrega].apply(to_float)
        df_calc["gf_num"] = df_calc[col_gf].apply(to_float)
        # Se tivermos varias linhas por mes, somar
        agg = df_calc.groupby(col_mes).agg(
            entrega=("entrega_num", "sum"),
            gf=("gf_num", "sum"),
        ).sort_index()
        agg["gsf"] = agg["entrega"] / agg["gf"]
        print(agg.tail(6).to_string())
        print("\n  >>> GSF calculado (3 meses mais recentes):")
        for idx, row in agg.tail(3).iterrows():
            pct = row["gsf"] * 100 if row["gsf"] is not None else None
            print(f"    {idx}: ENTREGA={row['entrega']:>12,.2f}  "
                  f"GF={row['gf']:>12,.2f}  "
                  f"GSF={pct:>6.2f}%" if pct else "    nao calc")
    else:
        print("  ! Faltam colunas necessarias. Verificar manualmente.")

    # --- 11. FATOR_REDUCAO_ACUMULADO != GSF
    print("\n[11] CHECK CRITICO — FATOR_REDUCAO_ACUMULADO NAO eh o GSF:")
    col_fator = None
    for c in df.columns:
        cn = str(c).upper()
        if "FATOR" in cn and "REDUCAO" in cn:
            col_fator = c
            break

    if col_fator:
        def to_float(v):
            if pd.isna(v):
                return None
            s = str(v).strip().replace(".", "").replace(",", ".")
            try:
                return float(s)
            except Exception:
                try:
                    return float(str(v).replace(",", "."))
                except Exception:
                    return None

        valores = df[col_fator].apply(to_float).dropna()
        if len(valores) > 0:
            print(f"  Coluna: {col_fator!r}")
            print(f"  Estatisticas:")
            print(f"    min  = {valores.min():.4f}")
            print(f"    max  = {valores.max():.4f}")
            print(f"    mean = {valores.mean():.4f}")
            print(f"    median = {valores.median():.4f}")
            print(f"  Amostra (10):")
            print(f"    {valores.head(10).tolist()}")
            if 0.85 <= valores.mean() <= 0.99:
                print("  >>> CONFIRMADO: range ~0,85-0,99 — eh o fator de "
                      "perdas (interno x rede basica x disponib).")
                print("                  NAO eh o GSF (que deveria variar"
                      " bem mais amplamente, ex: 0,75 a 1,15).")
            else:
                print("  ! Range fora do esperado para fator de perdas.")
                print("  ! Investigar manualmente.")
    else:
        print("  Coluna FATOR_REDUCAO nao encontrada — provavelmente "
              "esta sob outro nome.")

    # --- 12. Encoding e locale
    print("\n[12] ENCODING / LOCALE NUMERICO:")
    # Pegar primeira coluna numerica string
    if col_entrega:
        amostra = df[col_entrega].dropna().head(5).astype(str).tolist()
        print(f"  Amostra de {col_entrega!r} (raw): {amostra}")
        tem_virgula = any("," in str(v) for v in amostra)
        tem_ponto = any("." in str(v) for v in amostra)
        print(f"  Tem virgula: {tem_virgula} | Tem ponto: {tem_ponto}")
        if tem_virgula and not tem_ponto:
            print("  -> Decimal pt-BR (virgula). Necessario tratar no loader.")
        elif tem_ponto:
            print("  -> Decimal en-US (ponto). Padrao do pandas funciona.")

    # --- 13. Resumo final
    print("\n" + "=" * 70)
    print("[13] RESUMO PARA SPEC / CLAUDE.MD")
    print("=" * 70)
    print(f"  Pacote name: {pkg.get('name')!r}")
    print(f"  Pacote ID: {pkg.get('id')}")
    print(f"  Recursos CSV identificados: {len(csv_resources)}")
    print(f"  Anos detectados: {sorted({y for y, *_ in csv_resources_with_year if y})}")
    print(f"  Ano alvo: {ano_alvo}")
    print(f"  Fonte de download: {fonte}")
    print(f"  Colunas mais provaveis para GSF:")
    print(f"    mes_ref = {col_mes!r}")
    print(f"    entrega_mre = {cols_relevantes.get('entrega')!r}")
    print(f"    gf_rede_basica = {cols_relevantes.get('gf')!r}")
    print(f"  Total de colunas: {df.shape[1]}")
    print(f"  Total de linhas (no recurso): {df.shape[0]:,}")

    # JSON pra colar em ccee_mre.py
    print("\n[14] RESOURCE_IDS POR ANO (JSON pra colar):")
    ids_map = {}
    for ano, nm, rid, url in csv_resources_with_year:
        if ano:
            ids_map[ano] = rid
    print(json.dumps({str(a): rid for a, rid in sorted(ids_map.items())}, indent=2))

    print("\n[FIM Phase 0]")


if __name__ == "__main__":
    main()
