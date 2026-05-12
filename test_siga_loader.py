"""
test_siga_loader.py
===================
Teste manual standalone do data_loader_aneel_siga.

Validações:
- Cascata 3-tier (qual estratégia funcionou)
- Schema bruto (colunas, tipos, primeiras linhas)
- Valores únicos de SitFase (validar pendência §9.2 da SPEC)
- Existência de campos de capacidade (validar pendência §9.1)
- Padronização end-to-end (Series final, total em GW,
  sanity check vs ~200 GW Brasil)
- Performance (tempo de cada etapa)

NÃO rodar em produção. Apenas validação de implementação.

Execução (a partir da raiz do projeto):
    venv/Scripts/python.exe test_siga_loader.py
    OU
    python test_siga_loader.py
"""
from __future__ import annotations

import logging
import sys
import time
import traceback
from pathlib import Path

# Suprime warnings do Streamlit em script standalone (acima de ERROR)
logging.getLogger("streamlit").setLevel(logging.ERROR)

# UTF-8 no stdout (Windows cp1252 default quebra acentos/glifos)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Garante import do projeto a partir da raiz
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from data_loaders.data_loader_aneel_siga import (
    HAS_CURL_CFFI,
    DEMO_MODE,
    _get_siga_cache_path,
    _baixar_siga,
    _padronizar_siga,
)


def sep(title: str) -> None:
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def main() -> None:
    # ====== CHECK 1 ======
    sep("CHECK 1 — Ambiente")
    try:
        print(f"HAS_CURL_CFFI: {HAS_CURL_CFFI}")
        print(f"DEMO_MODE:     {DEMO_MODE}")
        try:
            cache_path = _get_siga_cache_path()
            print(f"Cache path:    {cache_path}")
            if cache_path is not None:
                exists = cache_path.exists()
                print(f"  Existe?      {exists}")
                if exists:
                    print(f"  Tamanho:     {cache_path.stat().st_size:,} bytes")
        except Exception as e:
            print(f"Erro lendo cache path: {type(e).__name__}: {e}")
    except Exception as e:
        print(f"CHECK 1 falhou: {type(e).__name__}: {e}")

    # ====== CHECK 2 ======
    sep("CHECK 2 — Download bruto (cascata 3-tier)")
    df_raw = None
    estrategia = "falhou"
    try:
        t0 = time.perf_counter()
        df_raw, estrategia = _baixar_siga()
        dt = time.perf_counter() - t0
        print(f"Tempo download:  {dt:.2f}s")
        print(f"Estrategia:      {estrategia}")
        if df_raw is None:
            print("Download retornou None — sem dados pra inspecionar.")
        else:
            print(f"Total linhas:    {len(df_raw):,}")
            print(f"Total colunas:   {df_raw.shape[1]}")
            print()
            print("Nomes das colunas:")
            for c in df_raw.columns:
                print(f"  - {c}")
            print()
            print("Primeiras 3 linhas (df.head(3)):")
            try:
                print(df_raw.head(3).to_string())
            except Exception as e:
                print(f"  (falha imprimindo head: {e})")
    except Exception as e:
        print(f"CHECK 2 falhou: {type(e).__name__}: {e}")
        traceback.print_exc()

    if df_raw is None or len(df_raw) == 0:
        print()
        print("⚠ df_raw vazio ou None — pulando CHECKs 3, 4, 5.")
        sep("CHECK 6 — Debug log (_debug_erros)")
        try:
            erros = st.session_state.get("_debug_erros", [])
            if not erros:
                print("(nenhuma entrada em _debug_erros)")
            for e in erros:
                print(e)
        except Exception as exc:
            print(f"Não foi possível ler debug log: {exc}")
        return

    # ====== CHECK 3 ======
    sep("CHECK 3 — Pendência §9.2 (valores exatos de SitFase)")
    try:
        col_sitfase = None
        for c in df_raw.columns:
            cu = str(c).upper()
            if (
                "DSCFASEUSINA" in cu
                or "SITFASE" in cu
                or "FASEUSINA" in cu
            ):
                col_sitfase = c
                break
        if col_sitfase is None:
            print(
                "⚠ Coluna de fase NÃO encontrada "
                "(DscFaseUsina/SitFase/FaseUsina)"
            )
        else:
            print(f"Coluna identificada: {col_sitfase}")
            print()
            print("Top 10 valores únicos (value_counts):")
            try:
                vc = df_raw[col_sitfase].value_counts().head(10)
                print(vc.to_string())
            except Exception as e:
                print(f"  (falha em value_counts: {e})")
            print()
            norm = (
                df_raw[col_sitfase].astype(str).str.strip().str.upper()
            )
            n_match = norm.isin({"OPERAÇÃO", "OPERACAO"}).sum()
            print(
                f"Linhas que batem com OPERAÇÃO/OPERACAO "
                f"(case-insens): {n_match:,}"
            )
    except Exception as e:
        print(f"CHECK 3 falhou: {type(e).__name__}: {e}")

    # ====== CHECK 4 ======
    sep("CHECK 4 — Pendência §9.1 (campos de capacidade)")
    try:
        col_outorgada = None
        col_fiscalizada = None
        for c in df_raw.columns:
            cu = str(c).upper()
            if "MDAPOTENCIAOUTORGADAKW" in cu:
                col_outorgada = c
            elif "MDAPOTENCIAFISCALIZADAKW" in cu:
                col_fiscalizada = c

        print(f"MdaPotenciaOutorgadaKw existe?    "
              f"{col_outorgada is not None}")
        if col_outorgada:
            print(f"  → coluna real: {col_outorgada}")
        print(f"MdaPotenciaFiscalizadaKw existe?  "
              f"{col_fiscalizada is not None}")
        if col_fiscalizada:
            print(f"  → coluna real: {col_fiscalizada}")
        print()

        for label, col in [("Outorgada", col_outorgada),
                           ("Fiscalizada", col_fiscalizada)]:
            if col is None:
                continue
            print(f"--- {label} ({col}) ---")
            s = df_raw[col]
            n = len(s)
            print(f"  dtype:       {s.dtype}")
            try:
                nulos = s.isna().sum()
                print(f"  nulos:       {nulos:,} ({100*nulos/n:.2f}%)")
            except Exception as e:
                print(f"  (falha em isna: {e})")
            try:
                snum_str = s.astype(str).str.replace(",", ".", regex=False)
                snum = pd.to_numeric(snum_str, errors="coerce")
                snum_nn = snum.dropna()
                if len(snum_nn) > 0:
                    print(f"  min:         {snum_nn.min():,.2f}")
                    print(f"  mediana:     {snum_nn.median():,.2f}")
                    print(f"  max:         {snum_nn.max():,.2f}")
            except Exception as e:
                print(f"  (falha em stats: {e})")
            try:
                nn = s.dropna().head(5).tolist()
                print(f"  Primeiras 5 não-nulas (raw): {nn}")
            except Exception as e:
                print(f"  (falha em head: {e})")
            print()
    except Exception as e:
        print(f"CHECK 4 falhou: {type(e).__name__}: {e}")

    # ====== CHECK 5 — Padronização end-to-end (DataFrame decomposto) ======
    sep("CHECK 5 — Padronização end-to-end (DataFrame por fonte)")
    try:
        t0 = time.perf_counter()
        df_out = _padronizar_siga(df_raw)
        dt = time.perf_counter() - t0
        print(f"Tempo padronizar:  {dt:.2f}s")
        print(f"Tipo retorno:      {type(df_out).__name__}")
        print(f"Shape:             {df_out.shape}  (linhas × colunas)")
        print(f"Index name:        {df_out.index.name}")
        print(f"Colunas (ordem):   {df_out.columns.tolist()}")

        if df_out.empty:
            print("⚠ DataFrame vazio — verificar logs do CHECK 6.")
        else:
            print()
            print("--- df.head(3) ---")
            print(df_out.head(3).to_string())
            print()
            print("--- df.tail(3) ---")
            print(df_out.tail(3).to_string())

            # Último mês: valor por fonte em GW
            ultimo = df_out.iloc[-1]
            total_mw = float(ultimo["CAP_TOTAL_MW"])
            total_gw = total_mw / 1000.0
            fontes = ["HIDRO", "TERMICA", "NUCLEAR",
                      "EOLICA", "SOLAR", "OUTRAS"]
            print()
            print(
                f"Mês mais recente: "
                f"{df_out.index[-1].strftime('%Y-%m')}"
            )
            print()
            print(f"{'Fonte':<10} {'GW':>10} {'% Total':>10}")
            print(f"{'-'*10} {'-'*10:>10} {'-'*10:>10}")
            soma_fontes_mw = 0.0
            for fonte in fontes:
                col = f"CAP_{fonte}_MW"
                val_mw = float(ultimo[col])
                val_gw = val_mw / 1000.0
                pct = (val_mw / total_mw * 100) if total_mw > 0 else 0.0
                print(f"{fonte:<10} {val_gw:>10,.2f} {pct:>9,.1f}%")
                soma_fontes_mw += val_mw
            print(f"{'-'*10} {'-'*10:>10} {'-'*10:>10}")
            print(f"{'SOMA':<10} {soma_fontes_mw/1000.0:>10,.2f}")
            print(f"{'TOTAL':<10} {total_gw:>10,.2f}")

            # Sanity 1: soma das 6 fontes ≈ CAP_TOTAL_MW (tolerância 0.01 MW)
            diff_soma = abs(soma_fontes_mw - total_mw)
            sanity_soma = "✓" if diff_soma < 0.01 else "⚠"
            print()
            print(
                f"Sanity numérica (soma das 6 ≈ TOTAL): "
                f"diff={diff_soma:.4f} MW [{sanity_soma}]"
            )

            # Sanity 2: ordem semântica HIDRO > TERMICA > EOLICA > SOLAR > NUCLEAR
            hidro = float(ultimo["CAP_HIDRO_MW"])
            termica = float(ultimo["CAP_TERMICA_MW"])
            eolica = float(ultimo["CAP_EOLICA_MW"])
            solar = float(ultimo["CAP_SOLAR_MW"])
            nuclear = float(ultimo["CAP_NUCLEAR_MW"])
            ordem_ok = (
                hidro > termica > eolica
                and solar < eolica  # SOLAR vs EOLICA pode ser próximo
                and nuclear < solar
            )
            sanity_ordem = "✓" if ordem_ok else "⚠"
            print(
                f"Sanity semântica (HIDRO>TERMICA>EOLICA, "
                f"SOLAR<EOLICA, NUCLEAR<SOLAR): [{sanity_ordem}]"
            )

            # Sanity 3: faixa total 200-240 GW
            faixa_ok = 200.0 <= total_gw <= 240.0
            sanity_faixa = "✓" if faixa_ok else "⚠"
            print(
                f"Sanity faixa (TOTAL entre 200-240 GW): "
                f"{total_gw:.2f} GW [{sanity_faixa}]"
            )
    except Exception as e:
        print(f"CHECK 5 falhou: {type(e).__name__}: {e}")
        traceback.print_exc()

    # ====== CHECK 6 ======
    sep("CHECK 6 — Debug log (_debug_erros)")
    try:
        erros = st.session_state.get("_debug_erros", [])
        if not erros:
            print("(nenhuma entrada em _debug_erros)")
        for e in erros:
            print(e)
    except Exception as exc:
        print(
            f"Não foi possível ler debug log: "
            f"{type(exc).__name__}: {exc}"
        )

    print()
    print("=" * 60)
    print("  FIM")
    print("=" * 60)


if __name__ == "__main__":
    main()
