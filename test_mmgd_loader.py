"""
test_mmgd_loader.py
===================
Teste manual standalone do data_loader_aneel_mmgd.

Validações:
- Import do módulo + constante MMGD_ANCHORS
- Carga da Series (load_mmgd_anual)
- Schema (tipo, name, index name, dtype)
- Sanity vs EPE PDGD release abr/2026 (dez/2024 = 36.200 MW; dez/2025 = 45.000 MW)
- Monotonicidade crescente
- Janela inicial dez/2022 (Lei 14.300)

NÃO faz download — anchor points hardcoded. Tempo esperado <1s.

Execução (a partir da raiz do projeto):
    venv/Scripts/python.exe test_mmgd_loader.py
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

# UTF-8 no stdout (Windows cp1252 default quebra acentos/glifos)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Garante import do projeto a partir da raiz
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import pandas as pd


def sep(titulo: str) -> None:
    print()
    print("=" * 70)
    print(f"  {titulo}")
    print("=" * 70)


def main() -> int:
    sep("TEST MMGD LOADER — anchor points anuais EPE PDGD")

    # ====== CHECK 1 — Import ======
    sep("CHECK 1 — Import")
    try:
        from data_loaders.data_loader_aneel_mmgd import (
            load_mmgd_anual,
            MMGD_ANCHORS,
        )
        print("✓ Import OK")
        print(f"  MMGD_ANCHORS tem {len(MMGD_ANCHORS)} entradas")
        assert len(MMGD_ANCHORS) == 5, (
            f"Esperado 5 anchors (4 PDGD + 1 carry-forward), got {len(MMGD_ANCHORS)}"
        )
    except Exception as e:
        print(f"✗ CHECK 1 falhou: {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1

    # ====== CHECK 2 — Carregar Series ======
    sep("CHECK 2 — load_mmgd_anual()")
    try:
        serie = load_mmgd_anual()
        print(f"Tipo:        {type(serie).__name__}")
        print(f"Nome:        {serie.name}")
        print(f"Index name:  {serie.index.name}")
        print(f"Tamanho:     {len(serie)}")
        print(f"Dtype:       {serie.dtype}")
        print()
        print("Conteúdo:")
        for idx, val in serie.items():
            print(
                f"  {idx.strftime('%Y-%m')}: "
                f"{val:>10,.1f} MW  ({val/1000:.2f} GW)"
            )
    except Exception as e:
        print(f"✗ CHECK 2 falhou: {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1

    # ====== CHECK 3 — Schema ======
    sep("CHECK 3 — Schema")
    try:
        assert isinstance(serie, pd.Series), (
            f"Esperado Series, got {type(serie).__name__}"
        )
        assert serie.name == "CAP_MMGD_MW", (
            f"Nome esperado CAP_MMGD_MW, got {serie.name}"
        )
        assert serie.index.name == "ANO_MES", (
            f"Index esperado ANO_MES, got {serie.index.name}"
        )
        assert serie.dtype.kind == "f", (
            f"Esperado float, got {serie.dtype}"
        )
        print("✓ Schema validado (Series / CAP_MMGD_MW / ANO_MES / float)")
    except AssertionError as e:
        print(f"✗ CHECK 3 falhou: {e}")
        return 1

    # ====== CHECK 4 — Sanity vs EPE PDGD ======
    sep("CHECK 4 — Sanity vs EPE PDGD")
    try:
        dez_2024 = serie.loc["2024-12-01"]
        dez_2025 = serie.loc["2025-12-01"]
        abr_2026 = serie.loc["2026-04-01"]
        diff_2024 = abs(dez_2024 - 36200.0)
        diff_2025 = abs(dez_2025 - 45000.0)
        diff_abr_2026 = abs(abr_2026 - 45000.0)
        print(
            f"dez/2024: {dez_2024:,.1f} MW "
            f"(esperado ~36.200) diff={diff_2024:.1f}"
        )
        print(
            f"dez/2025: {dez_2025:,.1f} MW "
            f"(esperado ~45.000) diff={diff_2025:.1f}"
        )
        print(
            f"abr/2026: {abr_2026:,.1f} MW "
            f"(esperado carry-forward ~45.000) diff={diff_abr_2026:.1f}"
        )
        assert diff_2024 < 1.0, "Valor dez/2024 deveria ser 36.200 ± 1 MW"
        assert diff_2025 < 1.0, "Valor dez/2025 deveria ser 45.000 ± 1 MW"
        assert diff_abr_2026 < 1.0, "Valor abr/2026 deveria ser 45.000 ± 1 MW"
        print("✓ Sanity passou")
    except AssertionError as e:
        print(f"✗ CHECK 4 falhou: {e}")
        return 1
    except KeyError as e:
        print(f"✗ CHECK 4 falhou — chave ausente: {e}")
        return 1

    # ====== CHECK 5 — Monotonicidade ======
    sep("CHECK 5 — Monotonicidade (crescente)")
    try:
        valores = serie.values
        monotonico = all(
            valores[i] <= valores[i + 1] for i in range(len(valores) - 1)
        )
        assert monotonico, "Valores deveriam ser monotonicamente crescentes"
        print("✓ Série é monotonicamente crescente")
    except AssertionError as e:
        print(f"✗ CHECK 5 falhou: {e}")
        return 1

    # ====== CHECK 6 — Janela (primeira + última data) ======
    sep("CHECK 6 — Janela (dez/2022 → abr/2026)")
    try:
        primeiro = serie.index.min()
        assert primeiro == pd.Timestamp("2022-12-01"), (
            f"Esperado dez/2022, got {primeiro}"
        )
        print(f"✓ Primeira data: {primeiro.strftime('%Y-%m-%d')} (Lei 14.300)")

        ultimo = serie.index.max()
        assert ultimo == pd.Timestamp("2026-04-01"), (
            f"Esperado abr/2026 como última, got {ultimo}"
        )
        print(f"✓ Última data:   {ultimo.strftime('%Y-%m-%d')} (carry-forward dez/2025)")
    except AssertionError as e:
        print(f"✗ CHECK 6 falhou: {e}")
        return 1

    sep("TODOS OS CHECKS PASSARAM")
    return 0


if __name__ == "__main__":
    sys.exit(main())
