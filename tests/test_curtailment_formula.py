"""Smoke tests da fórmula de curtailment.

2 asserts:
  1. Fórmula BBI sintética (calcular_pct_curtailment, 3 razões)
  2. Fórmula Sheet1 do template ONS (_padronizar do loader, 1 linha)
"""

import pandas as pd
import pytest

from utils.utils_curtailment import calcular_pct_curtailment
from data_loaders.data_loader_curtailment import _padronizar


def test_bbi_formula_3_razoes_sinteticas():
    """3 linhas (CNF/ENE/REL) frustrado=100 cada, sum(output)=1000.
    BBI: pct_total = (CNF+ENE) / (Output + frustrado_total)."""
    df = pd.DataFrame({
        "RAZAO":         ["CNF", "ENE", "REL"],
        "FRUSTRADO_MWH": [100.0, 100.0, 100.0],
        "OUTPUT_MWH":    [1000.0, 0.0, 0.0],
    })
    r = calcular_pct_curtailment(df)

    assert r["denom_bbi_mwh"] == pytest.approx(1300.0)
    assert r["pct_total"] == pytest.approx(200 / 1300)
    assert r["pct_por_razao"]["CNF"] == pytest.approx(100 / 1300)
    assert r["pct_por_razao"]["ENE"] == pytest.approx(100 / 1300)
    assert r["pct_por_razao"]["REL"] == pytest.approx(100 / 1300)

    soma_razoes = sum(r["pct_por_razao"].values())
    assert abs(soma_razoes - r["pct_total"]) > 0.01  # inconsistência intencional


def test_loader_frustrado_calc_matches_sheet1_template():
    """Cálculo de FRUSTRADO_MWH em _padronizar bate com Sheet1:
        IF(razao_vazio, 0, MAX(MIN(disp, ref) - geracao, 0)) × 0.5

    Linha sintética: geracao=50, disp=100, ref=80, razao=ENE
        MIN(100, 80) = 80
        80 - 50 = 30
        MAX(30, 0) = 30
        × 0.5 (passo semi-horário) = 15.0
    """
    df_raw = pd.DataFrame({
        "din_instante":               ["2026-04-15 12:00:00"],
        "val_geracao":                [50.0],
        "val_disponibilidade":        [100.0],
        "val_geracaoreferencia":      [80.0],
        "val_geracaoreferenciafinal": [80.0],
        "cod_razaorestricao":         ["ENE"],
    })
    out = _padronizar(df_raw, fonte="solar")

    assert len(out) == 1
    assert out["FRUSTRADO_MWH"].iloc[0] == pytest.approx(15.0)
    assert out["OUTPUT_MWH"].iloc[0] == pytest.approx(50.0 * 0.5)
    assert out["RAZAO"].iloc[0] == "ENE"
