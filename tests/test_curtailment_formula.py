"""Smoke tests da fórmula de curtailment.

2 asserts:
  1. Fórmula ONS pública sintética (calcular_pct_curtailment, 3 razões)
  2. Fórmula Sheet1 do template ONS (_padronizar do loader, 1 linha)
"""

import pandas as pd
import pytest

from utils.utils_curtailment import calcular_pct_curtailment
from data_loaders.data_loader_curtailment import _padronizar
from data_loaders.data_loader_grupos_excel import aplicar_rateio


def test_ons_formula_3_razoes_sinteticas():
    """3 linhas (CNF/ENE/REL) frustrado=100 cada, sum(output)=1000.
    ONS: pct_total = (CNF+ENE+REL) / (Output + frustrado_total).
    Soma das 3 razões individuais bate com pct_total."""
    df = pd.DataFrame({
        "RAZAO":         ["CNF", "ENE", "REL"],
        "FRUSTRADO_MWH": [100.0, 100.0, 100.0],
        "OUTPUT_MWH":    [1000.0, 0.0, 0.0],
    })
    r = calcular_pct_curtailment(df)

    assert r["denom_potencial_mwh"] == pytest.approx(1300.0)
    assert r["pct_total"] == pytest.approx(300 / 1300)  # 23.08%
    assert r["pct_por_razao"]["CNF"] == pytest.approx(100 / 1300)
    assert r["pct_por_razao"]["ENE"] == pytest.approx(100 / 1300)
    assert r["pct_por_razao"]["REL"] == pytest.approx(100 / 1300)

    soma_razoes = sum(r["pct_por_razao"].values())
    assert abs(soma_razoes - r["pct_total"]) < 1e-9  # consistência matemática


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


def test_aplicar_rateio_cross_fonte_nao_duplica():
    """BABILÔNIA SUL aparece em ambas as abas (Solar+Eólica) do Excel real.
    Bug histórico: merge sem FONTE duplicava linhas eólicas com match Solar,
    inflando volume agregado em ~5% Eólica.
    Fix: merge on ["__CHAVE", "FONTE"] mantém isolamento entre fontes."""
    df_curt = pd.DataFrame({
        "USINA":                ["CONJ. BABILÔNIA SUL"],
        "FONTE":                ["EOLICA"],
        "FRUSTRADO_MWH":        [100.0],
        "OUTPUT_MWH":           [900.0],
        "GERACAO_MW":           [50.0],
        "GERACAO_REF_FINAL_MW": [60.0],
        "FRUSTRADO_MW":         [10.0],
    })
    df_grupos = pd.DataFrame({
        "NOME_NORM":    ["BABILONIASUL",         "BABILONIASUL"],
        "FONTE":        ["SOLAR",                "EOLICA"],
        "PARTICIPACAO": [1.0,                    1.0],
        "PROPRIETARIO": ["X (Solar)",            "Y (Eolica)"],
        "NOME_USINA":   ["BABILÔNIA SUL Solar",  "BABILÔNIA SUL Eólica"],
    })
    aliases = {}

    df_post = aplicar_rateio(df_curt, df_grupos, aliases)

    # Não duplicou: 1 linha Eólica → 1 linha pós-rateio (não 2)
    assert len(df_post) == 1
    # Volume preservado integralmente
    assert df_post["FRUSTRADO_MWH"].sum() == pytest.approx(100.0)
    assert df_post["OUTPUT_MWH"].sum() == pytest.approx(900.0)
    # Match correto: Eólica casou com proprietário Eólica, não Solar
    assert df_post["PROPRIETARIO"].iloc[0] == "Y (Eolica)"
