"""
inspect_balanco.py — descoberta Fase A do dataset Balanço de Energia nos Subsistemas.

Objetivo: validar URL pattern, schema real, cobertura anual e unidades do dataset
`balanco-energia-subsistema` do ONS. Baixa 1 ano pequeno (2016) por inteiro pra
confirmar dtypes e range de valores, e smoke-testa um ano recente (2024) pros
números conhecidos da spec (SIN ~75-80 GWmed, solar+eólica ~22-25% etc).

Como rodar (da raiz):
  venv/Scripts/python.exe scripts/inspect_balanco.py
"""
from __future__ import annotations
import sys
import io
import re
import traceback

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from curl_cffi import requests as http
    CURL_OK = True
except ImportError:
    import requests as http
    CURL_OK = False

import pandas as pd


def _get(url, **kwargs):
    if CURL_OK:
        return http.get(url, impersonate="chrome", timeout=120, **kwargs)
    return http.get(url, timeout=120, **kwargs)


def section(title):
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


CKAN_BASE = "https://dados.ons.org.br/api/3/action"
pkg_id = "balanco-energia-subsistema"

# URL pattern declarado na spec (seção 3.2) — slug do dataset em S3 é
# `balanco_energia_subsistema_ho` (com sufixo _ho = horário).
PARQUET_URL = "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/balanco_energia_subsistema_ho/BALANCO_ENERGIA_SUBSISTEMA_{ano}.parquet"
XLSX_URL    = "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/balanco_energia_subsistema_ho/BALANCO_ENERGIA_SUBSISTEMA_{ano}.xlsx"
CSV_URL     = "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/balanco_energia_subsistema_ho/BALANCO_ENERGIA_SUBSISTEMA_{ano}.csv"


# -------------------------------------------------------------------------
# 1) CKAN package_show — lista TODOS os resources por ano+formato
# -------------------------------------------------------------------------
section("1) CKAN package_show — cobertura detalhada por ano/formato")

resources = []
try:
    r = _get(f"{CKAN_BASE}/package_show", params={"id": pkg_id})
    print(f"  HTTP {r.status_code}")
    if r.status_code == 200:
        payload = r.json()
        if payload.get("success"):
            resources = payload["result"]["resources"]
            # Imprime metadados do pacote
            result = payload["result"]
            print(f"  title    : {result.get('title')}")
            print(f"  license  : {result.get('license_title')}")
            print(f"  freq     : {result.get('frequency')}")
            print(f"  modified : {result.get('metadata_modified')}")
except Exception:
    traceback.print_exc()

print(f"  total resources: {len(resources)}")

# Matriz ano × formato
matriz = {}
for res in resources:
    name = res.get("name") or ""
    fmt = (res.get("format") or "?").upper()
    m = re.search(r"(\d{4})", name)
    if m:
        ano = int(m.group(1))
        matriz.setdefault(ano, {})[fmt] = res.get("url")

anos = sorted(matriz.keys())
if anos:
    print(f"  anos cobertos: {anos[0]}-{anos[-1]} ({len(anos)} anos)")
    formatos_all = sorted({f for row in matriz.values() for f in row.keys()})
    header = f"    ano    " + "  ".join(f"{f:>8}" for f in formatos_all)
    print(header)
    for ano in anos:
        row = matriz[ano]
        cells = "  ".join("   OK   " if f in row else "   --   " for f in formatos_all)
        print(f"    {ano}   {cells}")


# -------------------------------------------------------------------------
# 2) Testar HEAD/GET por ano
# -------------------------------------------------------------------------
section("2) Teste HEAD/GET por ano — parquet / xlsx / csv")

anos_teste = [2000, 2005, 2010, 2015, 2016, 2018, 2020, 2021, 2022, 2023, 2024, 2025, 2026]
print(f"  {'ano':6} {'parquet':>14} {'xlsx':>14} {'csv':>14}")
for ano in anos_teste:
    row = []
    for url_fmt in (PARQUET_URL, XLSX_URL, CSV_URL):
        try:
            r = _get(url_fmt.format(ano=ano))
            if r.status_code == 200 and len(r.content) > 500:
                row.append(f"{len(r.content):>10} B")
            else:
                row.append(f"HTTP {r.status_code:>8}")
        except Exception as e:
            row.append(f"ERR:{type(e).__name__[:8]}")
    print(f"  {ano:6} {row[0]:>14} {row[1]:>14} {row[2]:>14}")


# -------------------------------------------------------------------------
# 3) Download completo de 2016 (ano pequeno — validar schema real)
# -------------------------------------------------------------------------
section("3) Schema real — parquet 2016 (download completo)")

df16 = None
try:
    r = _get(PARQUET_URL.format(ano=2016))
    print(f"  HTTP {r.status_code}, size {len(r.content)} bytes ({len(r.content)/1024/1024:.2f} MB)")
    if r.status_code == 200 and len(r.content) > 500:
        df16 = pd.read_parquet(io.BytesIO(r.content))
        print(f"  shape: {df16.shape}")
        print(f"\n  colunas:")
        for c in df16.columns:
            print(f"    - {c}")
        print(f"\n  dtypes:")
        for c, dt in df16.dtypes.items():
            print(f"    {c:50} {dt}")
        print(f"\n  head(3):")
        print(df16.head(3).to_string())
        print(f"\n  tail(3):")
        print(df16.tail(3).to_string())
except Exception:
    traceback.print_exc()


# -------------------------------------------------------------------------
# 4) Conteúdo de 2016 — valores únicos de submercado, range temporal, NaNs
# -------------------------------------------------------------------------
section("4) Conteúdo 2016 — submercados, range temporal, NaN, unidades")

if df16 is not None:
    # Encontrar coluna de submercado (nom_subsistema ou id_subsistema)
    col_sub_candidates = [c for c in df16.columns if "subsistema" in c.lower() or "submerc" in c.lower()]
    print(f"  cols de submercado candidatas: {col_sub_candidates}")
    for c in col_sub_candidates:
        uniq = sorted(df16[c].dropna().astype(str).unique().tolist())
        print(f"    {c}: {uniq}")

    # Encontrar coluna temporal
    col_time_candidates = [c for c in df16.columns if "instante" in c.lower() or "data" in c.lower() or "din_" in c.lower()]
    print(f"\n  cols temporais candidatas: {col_time_candidates}")
    for c in col_time_candidates:
        s = df16[c]
        print(f"    {c}: dtype={s.dtype}, min={s.min()}, max={s.max()}")

    # Cardinalidade horária: registros por (dia, submercado) deveria ser 24 se horário
    if col_time_candidates and col_sub_candidates:
        ct = col_time_candidates[0]
        cs = col_sub_candidates[0]
        df16[ct] = pd.to_datetime(df16[ct], errors="coerce")
        df16["_dia"] = df16[ct].dt.date
        conta_por_dia = df16.groupby(["_dia", cs]).size().reset_index(name="n")
        print(f"\n  registros por (dia, submercado) — stats:")
        print(f"    min  : {conta_por_dia['n'].min()}")
        print(f"    max  : {conta_por_dia['n'].max()}")
        print(f"    mean : {conta_por_dia['n'].mean():.2f}")
        print(f"    mode : {conta_por_dia['n'].mode().iloc[0]}")
        df16 = df16.drop(columns=["_dia"])

    # NaNs por coluna
    print(f"\n  NaN por coluna:")
    for c, n in df16.isna().sum().items():
        pct = n / len(df16) * 100
        print(f"    {c:50} {n:>8} ({pct:5.2f}%)")

    # Range de valores nas colunas numéricas
    print(f"\n  range valores numéricos:")
    for c in df16.select_dtypes(include=["number"]).columns:
        s = df16[c]
        print(f"    {c:50} min={s.min():>12.2f}  max={s.max():>12.2f}  mean={s.mean():>12.2f}")


# -------------------------------------------------------------------------
# 5) Smoke test: números conhecidos de 2024 (spec seção 11)
# -------------------------------------------------------------------------
section("5) Smoke test 2024 — números conhecidos da spec")

try:
    r = _get(PARQUET_URL.format(ano=2024))
    print(f"  HTTP {r.status_code}, size {len(r.content)} bytes ({len(r.content)/1024/1024:.2f} MB)")
    if r.status_code == 200 and len(r.content) > 500:
        df24 = pd.read_parquet(io.BytesIO(r.content))
        print(f"  shape: {df24.shape}")
        print(f"  cols : {list(df24.columns)}")

        # Identifica colunas por keyword — igual ao loader vai fazer
        def find_col(keywords):
            for c in df24.columns:
                if all(k in c.lower() for k in keywords):
                    return c
            return None

        col_hidro  = find_col(["hidra"])
        col_term   = find_col(["term"])
        col_eolic  = find_col(["eol"])
        col_solar  = find_col(["fotovolt"])
        col_carga  = find_col(["carga"])
        col_time   = find_col(["instante"]) or find_col(["data"])
        col_sub    = find_col(["nom", "subsistema"]) or find_col(["id", "subsistema"])

        print(f"\n  colunas identificadas:")
        print(f"    hidro  = {col_hidro}")
        print(f"    termica= {col_term}")
        print(f"    eolica = {col_eolic}")
        print(f"    solar  = {col_solar}")
        print(f"    carga  = {col_carga}")
        print(f"    tempo  = {col_time}")
        print(f"    sub    = {col_sub}")

        # Média 2024 completa — SIN = soma dos 4 submercados, depois média horária
        df24[col_time] = pd.to_datetime(df24[col_time], errors="coerce")
        # SIN = soma dos submercados por timestamp; depois média no ano todo
        by_time_sin = df24.groupby(col_time).agg(
            hidro=(col_hidro, "sum"),
            term=(col_term, "sum"),
            eol=(col_eolic, "sum"),
            sol=(col_solar, "sum"),
            carga=(col_carga, "sum"),
        )
        by_time_sin["total_ger"] = by_time_sin[["hidro", "term", "eol", "sol"]].sum(axis=1)

        media = by_time_sin.mean()
        print(f"\n  SIN 2024 (média anual de todas as horas):")
        print(f"    hidráulica     : {media['hidro']/1000:7.2f} GWmed")
        print(f"    térmica        : {media['term']/1000:7.2f} GWmed")
        print(f"    eólica         : {media['eol']/1000:7.2f} GWmed")
        print(f"    solar          : {media['sol']/1000:7.2f} GWmed")
        print(f"    geração total  : {media['total_ger']/1000:7.2f} GWmed   (spec: ~75-80)")
        print(f"    carga          : {media['carga']/1000:7.2f} GWmed   (spec: ~75-80)")
        pct_renov_var = (media['eol'] + media['sol']) / media['total_ger'] * 100
        print(f"    solar+eolica   : {pct_renov_var:5.2f}%          (spec: ~22-25)")

        # NE 2024 — participação renovável variável
        df24_ne = df24[df24[col_sub].astype(str).str.upper().str.contains("NE|NORDESTE", regex=True)]
        if not df24_ne.empty:
            ne_media = df24_ne[[col_hidro, col_term, col_eolic, col_solar]].mean()
            total_ne = ne_media.sum()
            pct_renov_ne = (ne_media[col_eolic] + ne_media[col_solar]) / total_ne * 100
            print(f"\n  NE 2024:")
            print(f"    total geração  : {total_ne/1000:7.2f} GWmed")
            print(f"    solar+eolica   : {pct_renov_ne:5.2f}%  (spec: ~80% em vários meses)")

        # Sul 2024 — termica maior que média
        df24_s = df24[df24[col_sub].astype(str).str.upper().str.strip().isin(["S", "SUL"])]
        if not df24_s.empty:
            s_media = df24_s[[col_hidro, col_term, col_eolic, col_solar]].mean()
            total_s = s_media.sum()
            pct_term_s = s_media[col_term] / total_s * 100
            pct_term_sin = media['term'] / media['total_ger'] * 100
            print(f"\n  Sul 2024:")
            print(f"    total geração  : {total_s/1000:7.2f} GWmed")
            print(f"    térmica        : {pct_term_s:5.2f}%  (SIN: {pct_term_sin:.2f}% — spec: Sul > SIN)")

except Exception:
    traceback.print_exc()


section("FIM")
