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

    # ====== CHECK 5 ======
    sep("CHECK 5 — Padronização end-to-end")
    try:
        t0 = time.perf_counter()
        serie = _padronizar_siga(df_raw)
        dt = time.perf_counter() - t0
        print(f"Tempo padronizar: {dt:.2f}s")
        print(f"Tipo retorno:     {type(serie).__name__}")
        print(f"Nome:             {serie.name}")
        try:
            print(f"Index name:       {serie.index.name}")
        except Exception:
            pass
        print(f"Total meses:      {len(serie):,}")
        if len(serie) > 0:
            print()
            print("Primeiras 5 entradas:")
            for idx, val in serie.head(5).items():
                try:
                    label_data = idx.strftime("%Y-%m")
                except Exception:
                    label_data = str(idx)
                print(f"  {label_data}: {val:>14,.1f} MW")
            print()
            print("Últimas 5 entradas:")
            for idx, val in serie.tail(5).items():
                try:
                    label_data = idx.strftime("%Y-%m")
                except Exception:
                    label_data = str(idx)
                print(f"  {label_data}: {val:>14,.1f} MW")
            print()
            ultimo_mw = float(serie.iloc[-1])
            ultimo_gw = ultimo_mw / 1000.0
            print(f"Valor mais recente: {ultimo_gw:.2f} GW")
            ref = 200.0  # ~200 GW Brasil (referência SIGA atual)
            diff_pct = abs(ultimo_gw - ref) / ref * 100
            status = "✓" if diff_pct < 25 else "⚠"
            print(
                f"Sanity vs ~200 GW Brasil: diff={diff_pct:.1f}% [{status}]"
            )
        else:
            print("⚠ Series vazia — verificar logs do CHECK 6.")
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
