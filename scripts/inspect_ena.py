"""
inspect_ena.py — descoberta Fase A do dataset ENA.

Objetivo: validar se existe dataset ENA agregado por subsistema no CKAN ONS,
inspecionar schema, unidade (MWmed vs MWmês vs MWh), presença de linha SIN
e range de valores.

Como rodar (da raiz):
  venv/Scripts/python.exe scripts/inspect_ena.py
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
        return http.get(url, impersonate="chrome", timeout=60, **kwargs)
    return http.get(url, timeout=60, **kwargs)


def section(title):
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


CKAN_BASE = "https://dados.ons.org.br/api/3/action"
pkg_id = "ena-diario-por-subsistema"


# -------------------------------------------------------------------------
# 1) CKAN package_show — lista TODOS os resources por ano+formato
# -------------------------------------------------------------------------
section("1) CKAN package_show — cobertura detalhada por ano/formato")

resources = []
try:
    r = _get(f"{CKAN_BASE}/package_show", params={"id": pkg_id})
    if r.status_code == 200:
        payload = r.json()
        if payload.get("success"):
            resources = payload["result"]["resources"]
except Exception:
    traceback.print_exc()

print(f"  total resources: {len(resources)}")

# Matriz ano × formato
matriz = {}
for res in resources:
    name = res.get("name") or ""
    fmt = (res.get("format") or "?").upper()
    # Extrair ano do nome
    m = re.search(r"(\d{4})", name)
    if m:
        ano = int(m.group(1))
        matriz.setdefault(ano, {})[fmt] = res.get("url")

anos = sorted(matriz.keys())
if anos:
    print(f"  anos cobertos: {anos[0]}–{anos[-1]} ({len(anos)} anos)")
    formatos_all = sorted({f for row in matriz.values() for f in row.keys()})
    header = f"    ano    " + "  ".join(f"{f:>8}" for f in formatos_all)
    print(header)
    for ano in anos:
        row = matriz[ano]
        cells = "  ".join("   ✓    " if f in row else "   —    " for f in formatos_all)
        print(f"    {ano}   {cells}")


# -------------------------------------------------------------------------
# 2) Testar download parquet por ano (confirmar quais existem mesmo)
# -------------------------------------------------------------------------
section("2) Teste HEAD/GET por ano — parquet e xlsx")

# URL pattern (virtual-hosted style S3)
PARQUET_URL = "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/ena_subsistema_di/ENA_DIARIO_SUBSISTEMA_{ano}.parquet"
XLSX_URL    = "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/ena_subsistema_di/ENA_DIARIO_SUBSISTEMA_{ano}.xlsx"
CSV_URL     = "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/ena_subsistema_di/ENA_DIARIO_SUBSISTEMA_{ano}.csv"

anos_teste = [2000, 2005, 2010, 2015, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026]
print(f"  {'ano':6} {'parquet':>12} {'xlsx':>12} {'csv':>12}")
for ano in anos_teste:
    row = []
    for url_fmt, label in [(PARQUET_URL, "parquet"), (XLSX_URL, "xlsx"), (CSV_URL, "csv")]:
        try:
            r = _get(url_fmt.format(ano=ano))
            if r.status_code == 200 and len(r.content) > 500:
                row.append(f"{len(r.content):>8} B")
            else:
                row.append(f"{r.status_code:>12}")
        except Exception as e:
            row.append(f"ERR:{type(e).__name__[:6]}")
    print(f"  {ano:6} {row[0]:>12} {row[1]:>12} {row[2]:>12}")


# -------------------------------------------------------------------------
# 3) Inspecionar schema parquet 2025 (já validado funciona)
# -------------------------------------------------------------------------
section("3) Schema parquet 2025")

try:
    r = _get(PARQUET_URL.format(ano=2025))
    df25 = pd.read_parquet(io.BytesIO(r.content))
    print(f"  shape: {df25.shape}")
    print(f"  cols : {list(df25.columns)}")
    print(f"\n  dtypes:")
    for c, dt in df25.dtypes.items():
        print(f"    {c:40} {dt}")
    print(f"\n  subsistemas únicos: {sorted(df25['id_subsistema'].unique().tolist())}")
    print(f"  range datas: {df25['ena_data'].min()} .. {df25['ena_data'].max()}")

    # Amostra de SIN somado
    print(f"\n  SIN CALCULADO (soma simples dos 4) — 3 datas amostra:")
    for d in ["2025-01-15", "2025-07-02", "2025-12-20"]:
        row = df25[df25["ena_data"] == d]
        if row.empty:
            continue
        total_bruta = row["ena_bruta_regiao_mwmed"].sum()
        total_armaz = row["ena_armazenavel_regiao_mwmed"].sum()
        print(f"    {d}  SIN_bruta={total_bruta:10.1f} MWmed   SIN_armazenavel={total_armaz:10.1f} MWmed")
        for _, r2 in row.iterrows():
            print(
                f"      {r2['id_subsistema']:3} bruta={r2['ena_bruta_regiao_mwmed']:9.1f}  "
                f"armaz={r2['ena_armazenavel_regiao_mwmed']:9.1f}  "
                f"%MLT_bruta={r2['ena_bruta_regiao_percentualmlt']:6.2f}"
            )
except Exception:
    traceback.print_exc()


# -------------------------------------------------------------------------
# 4) Se parquet só 2021+, testar se XLSX ou CSV de anos antigos tem mesmo schema
# -------------------------------------------------------------------------
section("4) Schema ANOS ANTIGOS (xlsx 2015 / csv 2015)")

try:
    r = _get(XLSX_URL.format(ano=2015))
    print(f"  xlsx 2015: HTTP {r.status_code}, size {len(r.content)} B")
    if r.status_code == 200 and len(r.content) > 500:
        df15 = pd.read_excel(io.BytesIO(r.content))
        print(f"    shape: {df15.shape}")
        print(f"    cols : {list(df15.columns)}")
        print(f"    head(3):")
        print(df15.head(3).to_string())
except Exception:
    print("  xlsx falhou:")
    traceback.print_exc()

try:
    r = _get(CSV_URL.format(ano=2015))
    print(f"\n  csv 2015: HTTP {r.status_code}, size {len(r.content)} B")
    if r.status_code == 200 and len(r.content) > 500:
        for sep in [";", ","]:
            try:
                df15c = pd.read_csv(io.BytesIO(r.content), sep=sep, encoding="utf-8-sig")
                if df15c.shape[1] >= 3:
                    print(f"    (sep='{sep}') shape: {df15c.shape}")
                    print(f"    cols : {list(df15c.columns)}")
                    print(f"    head(3):")
                    print(df15c.head(3).to_string())
                    break
            except Exception:
                continue
except Exception:
    print("  csv falhou:")
    traceback.print_exc()


section("FIM")
