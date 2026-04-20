"""
discover_ccee_ids.py — utilitário de manutenção (NÃO é executado pelo app).

Descobre os UUIDs de recurso CKAN da CCEE para os datasets de PLD (diário,
horário, semanal, mensal) por ano, consultando a API pública de dadosabertos.

Quando rodar:
  - Quando a CCEE publicar um novo ano (ex: jan/2027, aparecem CSVs 2027)
  - Se algum resource_id do data_loader.py quebrar (CCEE reemitiu)
  - Pra auditar/validar a tabela RESOURCE_IDS_BY_DATASET

Como rodar (da raiz do projeto):
  venv/Scripts/python.exe scripts/discover_ccee_ids.py

Saída: imprime os resource_ids por (dataset, ano) + JSON final pronto pra
colar em data_loader.py → RESOURCE_IDS_BY_DATASET.

Estratégia: package_search pra achar os pacotes e filtra por TITLE/NAME
exato (PLD_MEDIA_DIARIA, PLD_HORARIO, etc.) pra evitar contaminação
entre datasets. Usa curl_cffi impersonate=chrome + BROWSER_HEADERS
iguais aos do data_loader.py (CCEE bloqueia requests padrão via Akamai).
"""
from __future__ import annotations
import json
import re

from curl_cffi import requests as http

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

WANTED = {
    "diaria":  ["PLD_MEDIA_DIARIA"],
    "horaria": ["PLD_HORARIO"],
    "semanal": ["PLD_MEDIA_SEMANAL"],
    "mensal":  ["PLD_MEDIA_MENSAL"],
}
YEAR_RE = re.compile(r"(20\d{2})")


def get_json(url, params=None):
    r = http.get(url, params=params or {}, headers=BROWSER_HEADERS,
                 impersonate="chrome", timeout=60)
    r.raise_for_status()
    return r.json()


def find_package(titles):
    """Busca genérica e retorna o pacote cujo title/name casa exato (case-insensitive)."""
    # Busca com uma palavra-chave forte que trará o pacote
    for q in ["pld"]:
        data = get_json(f"{BASE}/package_search", {"q": q, "rows": 200})
        if not data.get("success"):
            continue
        for p in data["result"]["results"]:
            t = (p.get("title") or "").upper()
            n = (p.get("name") or "").upper()
            for want in titles:
                if t == want.upper() or n == want.upper():
                    return p
    return None


def extract_year(*texts):
    for t in texts:
        if not t:
            continue
        m = YEAR_RE.search(str(t))
        if m:
            y = int(m.group(1))
            if 2001 <= y <= 2099:
                return y
    return None


def main():
    per_dataset = {}

    for dataset, titles in WANTED.items():
        print(f"\n=== {dataset.upper()} (buscando {titles}) ===")
        pkg = find_package(titles)
        if not pkg:
            print("  nao encontrado")
            continue

        print(f"  pacote: title={pkg.get('title')!r} name={pkg.get('name')!r} "
              f"id={pkg.get('id')}")
        resources = pkg.get("resources", [])
        print(f"  recursos: {len(resources)}")

        ids_por_ano: dict[int, str] = {}
        for res in resources:
            ano = extract_year(res.get("name"), res.get("description"),
                               res.get("url"))
            fmt = (res.get("format") or "").upper()
            print(f"    - name={str(res.get('name'))[:40]:40} fmt={fmt:6} "
                  f"ano={ano} id={(res.get('id') or '')[:8]}")
            if ano is None:
                continue
            if fmt and fmt not in ("CSV",):
                continue
            rid = res.get("id")
            if rid and ano not in ids_por_ano:
                ids_por_ano[ano] = rid

        per_dataset[dataset] = ids_por_ano
        if ids_por_ano:
            print(f"  >>> resource_ids CSV por ano:")
            for ano in sorted(ids_por_ano):
                print(f"       {ano}: {ids_por_ano[ano]}")

    print("\n\n=== RESUMO (JSON) ===")
    print(json.dumps({k: {str(a): v for a, v in d.items()}
                      for k, d in per_dataset.items()}, indent=2))


if __name__ == "__main__":
    main()
