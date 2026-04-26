"""
inspect_gd.py — descoberta Fase A do dataset Geração Distribuída (MMGD/GD).

Objetivo: validar se o ONS publica estimativa de MMGD/GD por subsistema, em
qual dataset, granularidade, cobertura temporal e schema. Também verifica se
o `balanco_energia_subsistema` (já usado) ganhou coluna nova de GD.

Como rodar (da raiz):
  venv/Scripts/python.exe scripts/inspect_gd.py
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

# Palavras-chave pra filtrar packages do CKAN
KEYWORDS = [
    "distribuid", "mmgd", "micro", "mini",
    "fotovoltaic", "telhado", "consumidor",
]


# -------------------------------------------------------------------------
# 1) package_list completo + filtro por palavras-chave
# -------------------------------------------------------------------------
section("1) CKAN package_list — busca por keywords de GD/MMGD")

candidatos = []
try:
    r = _get(f"{CKAN_BASE}/package_list")
    if r.status_code == 200:
        payload = r.json()
        if payload.get("success"):
            todos_pkgs = payload["result"]
            print(f"  total de packages no CKAN: {len(todos_pkgs)}")
            for p in todos_pkgs:
                p_low = p.lower()
                if any(k in p_low for k in KEYWORDS):
                    candidatos.append(p)
            print(f"\n  packages que matcham keywords ({len(candidatos)}):")
            for c in candidatos:
                print(f"    - {c}")
except Exception:
    traceback.print_exc()


# -------------------------------------------------------------------------
# 2) package_search via texto livre (cobre descrições, não só nomes)
# -------------------------------------------------------------------------
section("2) CKAN package_search — busca textual em descrições")

queries = ["geração distribuída", "MMGD", "micro minigeração", "fotovoltaica"]
encontrados_por_busca = set()
for q in queries:
    print(f"\n  query: '{q}'")
    try:
        r = _get(f"{CKAN_BASE}/package_search", params={"q": q, "rows": 20})
        if r.status_code == 200:
            payload = r.json()
            if payload.get("success"):
                results = payload["result"]["results"]
                print(f"    {len(results)} hits:")
                for res in results[:10]:
                    name = res.get("name", "?")
                    title = res.get("title", "?")
                    print(f"      - {name}  ({title})")
                    encontrados_por_busca.add(name)
    except Exception:
        traceback.print_exc()

# União dos candidatos
todos_candidatos = sorted(set(candidatos) | encontrados_por_busca)


# -------------------------------------------------------------------------
# 3) Inspeção de cada candidato — package_show
# -------------------------------------------------------------------------
section("3) package_show de cada candidato — schema, granularidade, cobertura")

for pkg_id in todos_candidatos:
    print(f"\n  --- {pkg_id} ---")
    try:
        r = _get(f"{CKAN_BASE}/package_show", params={"id": pkg_id})
        if r.status_code != 200:
            print(f"    HTTP {r.status_code}")
            continue
        payload = r.json()
        if not payload.get("success"):
            print(f"    success=False")
            continue
        res = payload["result"]
        print(f"    title       : {res.get('title')}")
        print(f"    notes       : {(res.get('notes') or '')[:200]}")
        print(f"    org         : {(res.get('organization') or {}).get('title', '?')}")
        tags = [t.get("name") for t in res.get("tags", [])]
        print(f"    tags        : {tags}")
        print(f"    granularidade(meta): {res.get('frequency') or res.get('update_frequency') or '?'}")

        resources = res.get("resources", [])
        print(f"    resources   : {len(resources)}")
        # Matriz ano × formato
        matriz = {}
        for rsc in resources:
            name = rsc.get("name") or ""
            fmt = (rsc.get("format") or "?").upper()
            m = re.search(r"(\d{4})", name)
            if m:
                ano = int(m.group(1))
                matriz.setdefault(ano, {})[fmt] = rsc.get("url")
            else:
                # Sem ano no nome — pode ser dataset agregado único
                matriz.setdefault("?", {})[fmt] = rsc.get("url")
        anos = sorted(matriz.keys(), key=lambda x: (isinstance(x, str), x))
        if anos:
            formatos_all = sorted({f for row in matriz.values() for f in row.keys()})
            print(f"    cobertura   : {anos[0]}–{anos[-1]} ({len(anos)} entradas)")
            print(f"    formatos    : {formatos_all}")
            # Mostra 1 URL exemplo por formato
            for fmt in formatos_all:
                url_ex = next(
                    (m.get(fmt) for m in matriz.values() if fmt in m), None
                )
                if url_ex:
                    print(f"      ex {fmt}: {url_ex}")
    except Exception:
        traceback.print_exc()


# -------------------------------------------------------------------------
# 4) Confere se o `balanco_energia_subsistema` ganhou coluna de GD
# -------------------------------------------------------------------------
section("4) balanco_energia_subsistema — schema atual tem GD?")

# URL correta: _ho (horário), não _di (que não existe)
BALANCO_URL = "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/balanco_energia_subsistema_ho/BALANCO_ENERGIA_SUBSISTEMA_{ano}.parquet"
for ano in [2024, 2025, 2026]:
    print(f"\n  --- ano {ano} ---")
    try:
        r = _get(BALANCO_URL.format(ano=ano))
        if r.status_code == 200 and len(r.content) > 500:
            df = pd.read_parquet(io.BytesIO(r.content))
            print(f"    shape: {df.shape}")
            print(f"    cols : {list(df.columns)}")
            gd_cols = [c for c in df.columns if any(
                k in c.lower() for k in ["gd", "distribuid", "mmgd", "micro", "mini", "fotovolt"]
            )]
            print(f"    colunas com keyword GD/MMGD/fotovolt: {gd_cols if gd_cols else 'NENHUMA'}")
        else:
            print(f"    HTTP {r.status_code}")
    except Exception:
        traceback.print_exc()


# -------------------------------------------------------------------------
# 4b) Notes COMPLETAS dos 4 datasets de carga — qual menciona MMGD/29-04-2023?
# -------------------------------------------------------------------------
section("4b) Notes completas dos datasets de carga (busca por menção a MMGD)")

for pkg_id in ["carga-energia", "carga-energia-verificada", "carga-mensal", "curva-carga"]:
    print(f"\n  --- {pkg_id} ---")
    try:
        r = _get(f"{CKAN_BASE}/package_show", params={"id": pkg_id})
        if r.status_code != 200:
            print(f"    HTTP {r.status_code}")
            continue
        payload = r.json()
        if not payload.get("success"):
            continue
        notes = payload["result"].get("notes") or ""
        print(f"    notes ({len(notes)} chars):")
        for line in notes.split("\n"):
            print(f"    | {line}")
    except Exception:
        traceback.print_exc()


# -------------------------------------------------------------------------
# 4c) Schema da carga-energia 2024 — checar se tem coluna MMGD/GD separada
# -------------------------------------------------------------------------
section("4c) Schema carga-energia 2024 — colunas isoladas de MMGD?")

CARGA_URL = "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/carga_energia_di/CARGA_ENERGIA_{ano}.parquet"
for ano in [2022, 2023, 2024, 2025]:
    print(f"\n  --- carga {ano} ---")
    try:
        r = _get(CARGA_URL.format(ano=ano))
        if r.status_code == 200 and len(r.content) > 500:
            df = pd.read_parquet(io.BytesIO(r.content))
            print(f"    shape: {df.shape}")
            print(f"    cols : {list(df.columns)}")
            print(f"    head(2):")
            print(df.head(2).to_string())
        else:
            print(f"    HTTP {r.status_code}")
    except Exception:
        traceback.print_exc()


# -------------------------------------------------------------------------
# 5) Sondagem: existem outros datasets com "carga" pra checar se GD vem por lá?
# -------------------------------------------------------------------------
section("5) Sondagem: packages com 'carga' (carga vs carga-líquida)")

try:
    r = _get(f"{CKAN_BASE}/package_search", params={"q": "carga", "rows": 30})
    if r.status_code == 200:
        payload = r.json()
        if payload.get("success"):
            for res in payload["result"]["results"]:
                name = res.get("name", "?")
                title = res.get("title", "?")
                print(f"    - {name}  ({title})")
except Exception:
    traceback.print_exc()


section("FIM")
