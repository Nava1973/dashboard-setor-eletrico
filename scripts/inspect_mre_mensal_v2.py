"""
inspect_mre_mensal_v2.py — Phase 0 do sprint GSF — APROFUNDAMENTO.

Achados do v1:
  - Pacote 'mre_mensal' tem 12 colunas, recursos 2023/2024/2025/2026
  - ENTREGA_MRE = 7.9M ordem de magnitude para mar/2026; GF_REDE_BASICA = 56k
  - Ratio ENTREGA/GF = ~140 (sem normalizacao). Nao bate com GSF realista.
  - FATOR_REDUCAO_ACUMULADO = produto exato de FATOR_PERDA_INTERNA *
    FATOR_PERDA_REDE_BASICA * FATOR_DISPONIBILIDADE -> EH SO PERDAS.
  - CUSTO_MRE * ENTREGA_MRE = VALOR_ALOCADO_MRE (exato) -> ENTREGA_MRE
    eh volume monetariamente settled, NAO geracao bruta UHE.

Este script:
  1. Baixa anos 2023-2026 completos
  2. Tenta calcular GSF de varias formas (ENTREGA/GF, ENTREGA/GF_horas,
     1-ENTREGA/GF_horas, etc.)
  3. Compara com GSF publico conhecido para meses-marco:
       - mar/2024: ~80% (drought)
       - dez/2024: ~88%
       - jul/2025: ~95-100%
       - jan/2026: ?
  4. Inspeciona MRE_HORARIO pra ver se ele tem geracao direta
  5. Imprime tabela completa de ENTREGA_MRE / GF_REDE_BASICA mes a mes
     pra inspecao visual
"""
from __future__ import annotations

import io
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


# Resource IDs descobertos no v1
RESOURCE_IDS_MRE_MENSAL = {
    2023: "cbcd5631-1a64-42f3-ad58-480c7b177388",
    2024: "5665c103-8223-47de-b581-9b3853f0609f",
    2025: "9c333d24-398f-4eda-8cc0-4e6ff95d99a4",
    2026: "37fdbdf6-77f0-40e3-93c5-60e299e68376",
}
PACKAGE_MRE_HORARIO_ID = "e64640a5-309a-49e4-82c0-b0a95ff514d0"


def ckan_paginated(resource_id: str, max_rows: int = 200000) -> Optional[pd.DataFrame]:
    base = f"{BASE}/datastore_search"
    rows = []
    offset = 0
    limit = 1000
    while True:
        try:
            r = http.get(
                base,
                params={"resource_id": resource_id, "limit": limit, "offset": offset},
                headers=BROWSER_HEADERS, impersonate="chrome", timeout=60,
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


def get_package(pkg_id: str) -> dict:
    r = http.get(
        f"{BASE}/package_show",
        params={"id": pkg_id},
        headers=BROWSER_HEADERS, impersonate="chrome", timeout=60,
    )
    r.raise_for_status()
    return r.json().get("result", {})


def main():
    # ============================================================
    # PARTE 1: Baixar 4 anos do MRE_MENSAL e consolidar
    # ============================================================
    print("=" * 75)
    print("PARTE 1 — Consolidar MRE_MENSAL 2023+2024+2025+2026")
    print("=" * 75)

    dfs = []
    for ano, rid in sorted(RESOURCE_IDS_MRE_MENSAL.items()):
        print(f"\n  Ano {ano}: baixando {rid[:8]}...")
        df = ckan_paginated(rid)
        if df is None or df.empty:
            print(f"    ! vazio")
            continue
        print(f"    {len(df)} linhas, {df.shape[1]} colunas")
        dfs.append(df)

    if not dfs:
        print("  ! nada baixado")
        return

    df = pd.concat(dfs, ignore_index=True)
    # tipar MES_REFERENCIA pra string padronizada
    df["MES_REFERENCIA"] = df["MES_REFERENCIA"].astype(str)
    df = df.sort_values("MES_REFERENCIA").reset_index(drop=True)
    print(f"\n  Total consolidado: {len(df)} meses")
    print(f"  Range: {df['MES_REFERENCIA'].min()} a "
          f"{df['MES_REFERENCIA'].max()}")

    # ============================================================
    # PARTE 2: Validar identidades algebricas
    # ============================================================
    print("\n" + "=" * 75)
    print("PARTE 2 — Validar identidades algebricas")
    print("=" * 75)

    # 1. FATOR_REDUCAO_ACUMULADO = produto dos 3 fatores?
    df["_fator_calc"] = (
        df["FATOR_PERDA_INTERNA"]
        * df["FATOR_PERDA_REDE_BASICA"]
        * df["FATOR_DISPONIBILIDADE"] / 10000.0
    )
    df["_fator_diff"] = df["FATOR_REDUCAO_ACUMULADO"] - df["_fator_calc"]
    diff_max = df["_fator_diff"].abs().max()
    print(f"\n  Identidade 1: FATOR_REDUCAO = INTERNA * RB * DISP / 10000")
    print(f"    max diff: {diff_max:.6f} (deve ser ~0)")
    if diff_max < 0.01:
        print(f"    -> CONFIRMADO: FATOR_REDUCAO_ACUMULADO eh produto dos 3 fatores")
    else:
        print(f"    -> NAO confirma. Sample:")
        print(df[["FATOR_PERDA_INTERNA", "FATOR_PERDA_REDE_BASICA",
                  "FATOR_DISPONIBILIDADE", "FATOR_REDUCAO_ACUMULADO",
                  "_fator_calc", "_fator_diff"]].head(3).to_string())

    # 2. VALOR_ALOCADO_MRE = ENTREGA_MRE * CUSTO_MRE?
    df["_valor_calc"] = df["ENTREGA_MRE"] * df["CUSTO_MRE"]
    df["_valor_diff_pct"] = (
        (df["VALOR_ALOCADO_MRE"] - df["_valor_calc"]).abs()
        / df["VALOR_ALOCADO_MRE"].abs().clip(lower=1)
    )
    diff_pct_max = df["_valor_diff_pct"].max()
    print(f"\n  Identidade 2: VALOR_ALOCADO = ENTREGA * CUSTO")
    print(f"    max diff%: {diff_pct_max:.4%} (deve ser ~0)")
    if diff_pct_max < 0.001:
        print(f"    -> CONFIRMADO: ENTREGA_MRE eh volume settled,")
        print(f"       NAO geracao bruta UHE")

    # 3. Relacao entre GF columns
    df["_gf_modulada_calc"] = (
        df["GARANTIA_FISICA_SAZONALIZADA_MRE"]
        * df["FATOR_REDUCAO_ACUMULADO"] / 100.0
    )
    df["_gf_modulada_diff"] = (
        df["GARANTIA_FISICA_MODULADA_FDISP"] - df["_gf_modulada_calc"]
    )
    print(f"\n  Identidade 3: GF_MODULADA_FDISP = SAZONALIZADA * FATOR_REDUCAO/100")
    print(f"    max diff: {df['_gf_modulada_diff'].abs().max():.4f}")

    # 4. GF_REDE_BASICA / SAZONALIZADA — derivar fator implicito
    df["_implicit_factor"] = (
        df["GARANTIA_FISICA_REDE_BASICA"] / df["GARANTIA_FISICA_SAZONALIZADA_MRE"]
    )
    print(f"\n  Implicit GF_REDE_BASICA/SAZONALIZADA factor:")
    print(f"    range: {df['_implicit_factor'].min():.4f} a "
          f"{df['_implicit_factor'].max():.4f}")
    print(f"    media: {df['_implicit_factor'].mean():.4f}")
    # Comparar com produto INTERNA * REDE_BASICA / 10000 (sem disponib)
    df["_internas_x_rb"] = (
        df["FATOR_PERDA_INTERNA"] * df["FATOR_PERDA_REDE_BASICA"] / 10000.0
    )
    print(f"  Comparacao com (PERDA_INTERNA * PERDA_REDE_BASICA / 10000):")
    print(f"    range: {df['_internas_x_rb'].min():.4f} a "
          f"{df['_internas_x_rb'].max():.4f}")
    print(f"    media: {df['_internas_x_rb'].mean():.4f}")
    correlation_rb = (df["_implicit_factor"] - df["_internas_x_rb"]).abs().max()
    print(f"    max diff: {correlation_rb:.4f}")
    if correlation_rb < 0.001:
        print(f"    -> CONFIRMADO: GF_REDE_BASICA = SAZONALIZADA * "
              f"PERDA_INTERNA * PERDA_REDE_BASICA / 10000")
        print(f"       (modulada SEM o fator disponibilidade)")

    # ============================================================
    # PARTE 3: Tentar varias formulas pro GSF e ver qual eh plausivel
    # ============================================================
    print("\n" + "=" * 75)
    print("PARTE 3 — Tentar varias formulas pro GSF")
    print("=" * 75)

    def horas_no_mes(mref: str) -> int:
        """Numero de horas no mes AAAAMM."""
        ano = int(mref[:4])
        mes = int(mref[4:6])
        return pd.Timestamp(f"{ano}-{mes:02d}-01").days_in_month * 24

    df["_horas_mes"] = df["MES_REFERENCIA"].apply(horas_no_mes)

    # F1: ENTREGA_MRE / GF_REDE_BASICA (espec do spec — provavel WRONG)
    df["GSF_F1_entrega_gf"] = df["ENTREGA_MRE"] / df["GARANTIA_FISICA_REDE_BASICA"]
    # F2: ENTREGA_MRE / (GF_REDE_BASICA * horas)
    df["GSF_F2_entrega_gfh"] = (
        df["ENTREGA_MRE"] / (df["GARANTIA_FISICA_REDE_BASICA"] * df["_horas_mes"])
    )
    # F3: 1 - F2 (caso ENTREGA seja deficit)
    df["GSF_F3_um_menos_F2"] = 1 - df["GSF_F2_entrega_gfh"]
    # F4: 1 - F1
    df["GSF_F4_um_menos_F1"] = 1 - df["GSF_F1_entrega_gf"]
    # F5: ENTREGA_MRE / VALOR_ALOCADO_MRE (nao deveria fazer sentido)
    # F6: GF_REDE_BASICA / GF_SAZONALIZADA — so pra checar
    # F7: O ENTREGA / GF eh em mwm e horas precisam normalizar inverso?
    df["GSF_F7_inv"] = (
        df["GARANTIA_FISICA_REDE_BASICA"] * df["_horas_mes"] / df["ENTREGA_MRE"]
    )

    print("\n  Tabela com varias formulas (todos os meses):")
    cols_show = [
        "MES_REFERENCIA", "ENTREGA_MRE", "GARANTIA_FISICA_REDE_BASICA",
        "_horas_mes",
        "GSF_F1_entrega_gf", "GSF_F2_entrega_gfh",
        "GSF_F3_um_menos_F2", "GSF_F4_um_menos_F1",
        "GSF_F7_inv",
    ]
    df_show = df[cols_show].copy()
    for c in ["GSF_F1_entrega_gf", "GSF_F2_entrega_gfh",
              "GSF_F3_um_menos_F2", "GSF_F4_um_menos_F1",
              "GSF_F7_inv"]:
        df_show[c] = df_show[c].apply(lambda x: f"{x*100:.1f}%" if pd.notna(x) else "")
    print(df_show.to_string(index=False))

    # ============================================================
    # PARTE 4: Comparar com GSF historico publico
    # ============================================================
    print("\n" + "=" * 75)
    print("PARTE 4 — Comparar com GSF historico PUBLICO conhecido")
    print("=" * 75)
    print("""
  GSF realizado (fonte: comunicados CCEE / press / Apine):
    - 2023 media: ~85-90%
    - 2024 inicio (seca): ~75-85%
    - mar/2024: ~80%
    - dez/2024: ~88-92%
    - 1S/2025: melhora (~90-98%)
    - jul/2025: ~95-100%
    - dez/2025: ~95%
    - jan-mar/2026: provavel verao umido, alto (>95%)
""")
    df_recent = df.tail(15)[
        ["MES_REFERENCIA", "GSF_F1_entrega_gf", "GSF_F2_entrega_gfh",
         "GSF_F3_um_menos_F2", "GSF_F7_inv"]
    ].copy()
    for c in df_recent.columns:
        if c != "MES_REFERENCIA":
            df_recent[c] = df_recent[c].apply(
                lambda x: f"{x*100:.1f}%" if pd.notna(x) else ""
            )
    print(df_recent.to_string(index=False))

    # ============================================================
    # PARTE 5: Inspecionar MRE_HORARIO pra ver se ele tem geracao direta
    # ============================================================
    print("\n" + "=" * 75)
    print("PARTE 5 — Inspecionar MRE_HORARIO")
    print("=" * 75)
    pkg_h = get_package(PACKAGE_MRE_HORARIO_ID)
    print(f"  Pacote: {pkg_h.get('title')!r}")
    resources = pkg_h.get("resources", [])
    print(f"  Recursos: {len(resources)}")
    # Pegar o mais recente CSV
    csv_resources = [r for r in resources
                     if (r.get("format") or "").upper() == "CSV"]
    # Buscar 2025 ou 2026 mais recente
    csv_resources_ord = sorted(
        csv_resources,
        key=lambda r: r.get("name") or "",
        reverse=True,
    )
    if csv_resources_ord:
        target = csv_resources_ord[0]
        rid = target.get("id")
        nm = target.get("name")
        print(f"  Tentando baixar: name={nm!r} id={rid[:8]}")
        # MRE_HORARIO eh enorme — pega so 5000 linhas
        df_h = ckan_paginated(rid, max_rows=5000)
        if df_h is not None:
            print(f"  Linhas baixadas (amostra): {len(df_h)}")
            print(f"  Colunas: {list(df_h.columns)}")
            print(f"  Dtypes:")
            print(df_h.dtypes.to_string())
            print(f"  Head(5):")
            print(df_h.head(5).to_string())

    # ============================================================
    # PARTE 6: Inspecionar tambem MRE_GF_MODULADA_USINA
    # ============================================================
    print("\n" + "=" * 75)
    print("PARTE 6 — Inspecionar MRE_GF_MODULADA_USINA")
    print("=" * 75)
    pkg_u = get_package("de057e31-780b-4530-ba4a-e03a29c3b6e3")
    print(f"  Pacote: {pkg_u.get('title')!r}")
    resources = pkg_u.get("resources", [])
    print(f"  Recursos: {len(resources)}")
    csv_resources = [r for r in resources
                     if (r.get("format") or "").upper() == "CSV"]
    csv_resources_ord = sorted(
        csv_resources,
        key=lambda r: r.get("name") or "",
        reverse=True,
    )
    if csv_resources_ord:
        target = csv_resources_ord[0]
        rid = target.get("id")
        nm = target.get("name")
        print(f"  Tentando baixar amostra: name={nm!r} id={rid[:8]}")
        df_u = ckan_paginated(rid, max_rows=5000)
        if df_u is not None:
            print(f"  Linhas baixadas (amostra): {len(df_u)}")
            print(f"  Colunas: {list(df_u.columns)}")
            print(f"  Dtypes:")
            print(df_u.dtypes.to_string())
            print(f"  Head(5):")
            print(df_u.head(5).to_string())

    print("\n[FIM Phase 0 v2]")


if __name__ == "__main__":
    main()
