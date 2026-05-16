"""
validacao_final_gsf.py — VALIDACAO FINAL Fase 0 GSF.

Formula descoberta:
    GSF_mes = sum(GERACAO_MRE) / sum(GARANTIA_FISICA_MRE) * 100
    (somando 4 submercados x todos os periodos do mes)

Dataset: dadosabertos.ccee.org.br -> GERACAO_HORARIA_SUBMERCADO
Granularidade nativa: horario por submercado
Cobertura: arquivos por ano

Testa nos 11 meses cobertos por 2024+2025+2026 que estao no GSF_OFICIAL.
Tambem salva resource_ids em scripts/_resource_ids_gsf.json pra Fase 1.

Criterio:
    11/11 hits +/-0.5pp -> Fase 0 fechada
    10/11 hits          -> aceitar, investigar outlier
    <10/11 hits         -> reportar e ajustar
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
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

# 15 pontos oficiais, dos quais 11 estao em 2024-04+ (range de 2024-2026)
GSF_OFICIAL = {
    "202303": 101.564,   # fora (2024+ dataset)
    "202307":  77.957,   # fora (2024+ dataset)
    "202403":  95.041,   # fora (range 202311+)
    "202407":  84.975,   # ✓ coberto
    "202501": 113.213,   # ✓
    "202502": 110.957,   # ✓
    "202506":  87.700,   # ✓
    "202507":  69.330,   # ✓
    "202508":  62.600,   # ✓
    "202509":  63.000,   # ✓
    "202510":  63.100,   # ✓
    "202511":  65.700,   # ✓
    "202512":  73.600,   # ✓
    "202601":  81.207,   # ✓
    "202602": 100.318,   # ✓
}

MESES_COBERTOS_ESPERADOS = [
    "202407", "202501", "202502", "202506", "202507", "202508",
    "202509", "202510", "202511", "202512", "202601", "202602",
]


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
    print("VALIDACAO FINAL — Fase 0 GSF")
    print("Formula: sum(GERACAO_MRE) / sum(GARANTIA_FISICA_MRE) * 100")
    print("=" * 75)

    # ----------------------------------------------------------
    # 1. Discovery do pacote + coleta resource_ids
    # ----------------------------------------------------------
    print("\n[1] package_show e mapeamento de resource_ids por ano:")
    pkg = get_json(f"{BASE}/package_show",
                   {"id": "geracao_horaria_submercado"}).get("result")
    print(f"  Pacote: {pkg.get('title')!r} id={pkg.get('id')}")

    import re
    YEAR_RE = re.compile(r"(20\d{2})")
    resource_ids_by_year: dict[int, str] = {}
    resources_meta = []
    for r in pkg.get("resources", []):
        if (r.get("format") or "").upper() != "CSV":
            continue
        nm = r.get("name") or ""
        rid = r.get("id") or ""
        m = YEAR_RE.search(nm) or YEAR_RE.search(r.get("url") or "")
        ano = int(m.group(1)) if m else None
        if ano:
            resource_ids_by_year[ano] = rid
            resources_meta.append({"ano": ano, "name": nm, "id": rid})
            print(f"  - ano={ano} name={nm!r} id={rid}")

    # ----------------------------------------------------------
    # 2. Baixar 2024-2026
    # ----------------------------------------------------------
    print("\n[2] Baixar 2024 + 2025 + 2026 (cobre os 11 meses-alvo):")
    dfs = []
    for ano in (2024, 2025, 2026):
        rid = resource_ids_by_year.get(ano)
        if not rid:
            continue
        print(f"  {ano}...", end=" ", flush=True)
        t = time.time()
        df = ckan_paginated(rid)
        if df is not None:
            print(f"{len(df):,} linhas ({time.time()-t:.1f}s)")
            dfs.append(df)
    df = pd.concat(dfs, ignore_index=True)
    df["MES_REFERENCIA"] = df["MES_REFERENCIA"].astype(str)
    df["GERACAO_MRE"] = pd.to_numeric(df["GERACAO_MRE"], errors="coerce")
    df["GARANTIA_FISICA_MRE"] = pd.to_numeric(
        df["GARANTIA_FISICA_MRE"], errors="coerce"
    )
    print(f"\n  Total: {len(df):,} linhas, range {df['MES_REFERENCIA'].min()} "
          f"a {df['MES_REFERENCIA'].max()}")
    print(f"  Submercados: {sorted(df['SUBMERCADO'].dropna().unique())}")

    # ----------------------------------------------------------
    # 3. Calcular GSF nos 11 meses
    # ----------------------------------------------------------
    print("\n" + "=" * 75)
    print("[3] CALCULO GSF mes a mes (11 meses-alvo)")
    print("=" * 75)
    agg = df.groupby("MES_REFERENCIA").agg(
        sum_geracao=("GERACAO_MRE", "sum"),
        sum_gf=("GARANTIA_FISICA_MRE", "sum"),
        n_linhas=("GERACAO_MRE", "count"),
        n_subm=("SUBMERCADO", "nunique"),
    )
    agg["gsf_calc"] = agg["sum_geracao"] / agg["sum_gf"] * 100

    print(f"\n{'mes':>6}  {'oficial':>9}  {'calc':>9}  {'diff_pp':>9}  "
          f"{'n_lin':>6}  {'n_sub':>5}  status")
    hits_05 = 0
    hits_10 = 0
    total = 0
    diffs = []
    fails = []
    for m in MESES_COBERTOS_ESPERADOS:
        oficial = GSF_OFICIAL[m]
        if m not in agg.index:
            print(f"  {m}  {oficial:>8.3f}%  n/d        n/d         n/d      n/d  AUSENTE")
            continue
        calc = agg.loc[m, "gsf_calc"]
        n_lin = int(agg.loc[m, "n_linhas"])
        n_sub = int(agg.loc[m, "n_subm"])
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
            st = "FAIL"
            fails.append((m, oficial, calc, diff))
        print(f"  {m}  {oficial:>8.3f}%  {calc:>8.3f}%  {diff:>+8.4f}  "
              f"{n_lin:>6}  {n_sub:>5}  {st}")

    # ----------------------------------------------------------
    # 4. Resumo
    # ----------------------------------------------------------
    print(f"\n[4] RESUMO:")
    print(f"  Pontos validados:   {total}/11")
    print(f"  Hits +/-0.5pp:      {hits_05}")
    print(f"  Hits 0.5-1.0pp:     {hits_10}")
    print(f"  Total +/-1.0pp:     {hits_05 + hits_10}")
    if diffs:
        mean_abs = sum(abs(d) for d in diffs) / len(diffs)
        max_abs = max(abs(d) for d in diffs)
        mean_signed = sum(diffs) / len(diffs)
        print(f"  Mean abs diff:      {mean_abs:.4f} pp")
        print(f"  Max  abs diff:      {max_abs:.4f} pp")
        print(f"  Mean signed diff:   {mean_signed:+.4f} pp")
    if fails:
        print(f"\n  FAILS (>1.0pp):")
        for m, of, ca, d in fails:
            print(f"    {m}: oficial={of:.3f}%  calc={ca:.3f}%  "
                  f"diff={d:+.3f}pp")

    # ----------------------------------------------------------
    # 5. Confirmacao final + spec
    # ----------------------------------------------------------
    print("\n" + "=" * 75)
    print("[5] FORMULA CONFIRMADA")
    print("=" * 75)

    decision = ""
    if hits_05 >= 11:
        decision = ">>> FASE 0 CONCLUSIVAMENTE FECHADA (11/11 hits +/-0.5pp) <<<"
    elif hits_05 >= 10:
        decision = ">>> CONFIRMADA com 1 outlier ({}/11) — investigar {} <<<".format(
            hits_05, fails[0][0] if fails else "?"
        )
    else:
        decision = ">>> NAO CONFIRMADA ({}/11 hits +/-0.5pp) — ajustar <<<".format(hits_05)

    print(f"\n  {decision}")
    print("""
  FONTE:        dadosabertos.ccee.org.br
  DATASET:      GERACAO_HORARIA_SUBMERCADO
  COBERTURA:    arquivos por ano (2023, 2024, 2025, 2026)
  FORMULA:
      GSF_mes = sum(GERACAO_MRE) / sum(GARANTIA_FISICA_MRE) * 100
      (somando 4 submercados x todos os periodos do mes)

  GRANULARIDADE NATIVA:  horario por submercado
  AGREGACAO DO DASHBOARD: mensal (sum no mes, todos submercados, todas horas)
  DEFASAGEM ESPERADA:     ~2 meses (MS+2du conforme docs CCEE Infomercado)

  COLUNAS-CHAVE no dataset:
      MES_REFERENCIA              str AAAAMM
      SUBMERCADO                  str ('NORDESTE','NORTE','SUDESTE','SUL')
      PERIODO_COMERCIALIZACAO     int 1..744 (hora do mes)
      GERACAO_MRE                 float MWh (numerador)
      GARANTIA_FISICA_MRE         float MWh (denominador)

  EVITAR:
      GERACAO_MRE / GARANTIA_FISICA_MODULADA_MRE -> sempre 100% (capada)
      GERACAO (sem _MRE) -> total do submercado (todas fontes, nao so UHE MRE)
""")

    # ----------------------------------------------------------
    # 6. Salvar resource_ids em JSON
    # ----------------------------------------------------------
    out_path = Path("scripts/_resource_ids_gsf.json")
    payload = {
        "dataset_id": pkg.get("id"),
        "dataset_name": "geracao_horaria_submercado",
        "discovered_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "resource_ids_by_year": {
            str(k): v for k, v in sorted(resource_ids_by_year.items())
        },
        "resources_meta": resources_meta,
        "formula": {
            "numerator_column": "GERACAO_MRE",
            "denominator_column": "GARANTIA_FISICA_MRE",
            "agg": "sum no mes, todos 4 submercados, todos os periodos",
            "result_unit": "fracao decimal (multiplicar por 100 pra %)",
        },
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"\n[6] Salvo: {out_path} ({out_path.stat().st_size} bytes)")
    print(f"    Conteudo: {len(payload['resource_ids_by_year'])} anos mapeados")

    print("\n[FIM]")


if __name__ == "__main__":
    main()
