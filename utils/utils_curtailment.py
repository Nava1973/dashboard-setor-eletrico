"""
utils_curtailment.py
====================

Cálculos de curtailment para o dashboard.

Metodologia: BBI Utilities Curtailment Tracker (financeira), validada
contra DG109 do tracker BBI (Solar Mensal Abr/26 = 25,03%).

==================================================================
FÓRMULA (BBI, financeira)
==================================================================

Para cada linha do ONS (passo semi-horário, valores em MWmed):

    Numerador (frustrado, coluna Q do template ONS):
        IF razao_vazio:
            FRUSTRADO_MWH = 0
        ELSE:
            FRUSTRADO_MWH = MAX(MIN(disponibilidade, geracao_ref) - geracao, 0) * 0.5

    Denominador (BBI):
        OUTPUT_MWH = geracao * 0.5
        DENOM_BBI  = sum(OUTPUT_MWH) + sum(FRUSTRADO_MWH)
                   = geração potencial total
                   = Output + CNF + ENE + REL (todas razões)

    % Não-Ressarcível = (CNF + ENE) / DENOM_BBI
        ↑ apenas curtailment FINANCEIRAMENTE relevante.
        REL (restrição elétrica) é ressarcida pelo ONS — não é perda
        financeira, então conceitualmente é como se a usina "tivesse
        gerado" do ponto de vista do dono. Por isso REL entra no
        denominador (geração potencial), não no numerador.

==================================================================
DECOMPOSIÇÃO POR TIPO DE RAZÃO (REL/CNF/ENE):
==================================================================
    Cada razão usa o MESMO denominador (DENOM_BBI):

        % REL = sum(FRUSTRADO_MWH onde razao=REL) / DENOM_BBI
        % CNF = sum(FRUSTRADO_MWH onde razao=CNF) / DENOM_BBI
        % ENE = sum(FRUSTRADO_MWH onde razao=ENE) / DENOM_BBI

    Atenção: % ENE + % CNF + % REL ≠ % Não-Ressarcível
        - soma das três = curtailment total bruto
        - % Não-Ressarcível exclui REL por ser ressarcível
    Inconsistência intencional — exibimos as 3 razões para
    transparência operativa, mas o KPI principal isola a perda
    financeira efetiva.

==================================================================
COLUNAS REQUERIDAS no DataFrame de entrada:
==================================================================
    FRUSTRADO_MWH   - já calculado no data_loader_curtailment
    OUTPUT_MWH      - geracao_realizada * 0.5 (já calculado no loader)
    RAZAO           - REL/CNF/ENE/PAR ou NaN

Convenção PAR (parecer de acesso):
    EXCLUÍDO por padrão - não é curtailment operativo, é restrição
    contratual prévia. Para incluir, passe `incluir_par=True`.
"""

from __future__ import annotations

from typing import Iterable, Optional

import pandas as pd


# Razões "operativas" (excluindo PAR por padrão)
RAZOES_OPERATIVAS = ("REL", "CNF", "ENE")
RAZOES_TODAS = ("REL", "CNF", "ENE", "PAR")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _filtrar_par(df: pd.DataFrame, incluir_par: bool) -> pd.DataFrame:
    """Remove linhas PAR a menos que explicitamente solicitado."""
    if incluir_par:
        return df
    return df[df["RAZAO"] != "PAR"].copy() if "RAZAO" in df.columns else df


def _frustrado_por_razao(
    df: pd.DataFrame,
    razoes: Iterable[str],
) -> pd.Series:
    """
    Retorna FRUSTRADO_MWH zerado para linhas fora das razões.

    Usa FRUSTRADO_MWH (correto, pré-calculado no loader com fórmula da Sheet1).
    """
    razoes_set = set(razoes)
    mask = df["RAZAO"].isin(razoes_set)
    return df["FRUSTRADO_MWH"].where(mask, 0.0)


# ---------------------------------------------------------------------------
# Cálculos agregados
# ---------------------------------------------------------------------------


def calcular_pct_curtailment(
    df: pd.DataFrame,
    razoes: Iterable[str] = RAZOES_OPERATIVAS,
    incluir_par: bool = False,
) -> dict:
    """
    Calcula % de curtailment (metodologia BBI Utilities Curtailment Tracker).

    Fórmula financeira:
        denom_bbi = sum(OUTPUT_MWH) + sum(FRUSTRADO_MWH)
                  = geração potencial total (Output + CNF + ENE + REL)

        pct_total        = (CNF + ENE) / denom_bbi   ← NÃO-RESSARCÍVEL
        pct_por_razao[r] = f_r / denom_bbi           ← cada razão / mesmo denom

    Diferença vs fórmula operacional anterior:
      - Numerador exclui REL (restrição elétrica é ressarcível pelo ONS,
        não é perda financeira — entra no denominador como se a usina
        tivesse gerado).
      - Denominador é geração potencial (Output + frustrado), não
        geração realizada.

    Consequência intencional:
        pct_por_razao["ENE"] + pct_por_razao["CNF"]
            + pct_por_razao["REL"] ≠ pct_total
        Total exclui REL por ser ressarcível; cada razão é mostrada
        individualmente para transparência operativa.

    Returns:
        dict com chaves:
            output_mwh             : geração realizada (sum OUTPUT_MWH)
            ref_total_mwh          : alias backward-compat = output_mwh
            frustrado_mwh          : numerador bruto (CNF + ENE + REL)
            frustrado_filtrado_mwh : numerador apenas das `razoes` solicitadas
            denom_bbi_mwh          : geração potencial (Output + frustrado)
            pct_total              : (CNF + ENE) / denom_bbi  [não-ressarcível]
            pct_filtrado           : frustrado_filtrado / denom_bbi
            pct_por_razao          : dict {razao: f_r / denom_bbi}
            n_linhas               : número de linhas processadas
    """
    if len(df) == 0 or "FRUSTRADO_MWH" not in df.columns:
        return {
            "output_mwh": 0.0,
            "ref_total_mwh": 0.0,  # alias backward-compat
            "frustrado_mwh": 0.0,
            "frustrado_filtrado_mwh": 0.0,
            "denom_bbi_mwh": 0.0,
            "pct_total": 0.0,
            "pct_filtrado": 0.0,
            "pct_por_razao": {},
            "n_linhas": 0,
        }

    df_calc = _filtrar_par(df, incluir_par)

    # Componentes do denominador BBI
    output_total = float(df_calc["OUTPUT_MWH"].sum())
    frustrado_total = float(df_calc["FRUSTRADO_MWH"].sum())  # CNF + ENE + REL
    denom_bbi = output_total + frustrado_total               # geração potencial

    # Frustrado por razão (todas, com o mesmo denominador BBI)
    razoes_decomp = list(RAZOES_TODAS) if incluir_par else list(RAZOES_OPERATIVAS)
    f_por_razao = {
        r: float(_frustrado_por_razao(df_calc, [r]).sum())
        for r in razoes_decomp
    }

    # KPI principal: NÃO-RESSARCÍVEL = CNF + ENE (exclui REL, ressarcível).
    # PAR não entra mesmo com incluir_par=True: é uso operativo, não financeiro.
    nao_ressarcivel = f_por_razao.get("CNF", 0.0) + f_por_razao.get("ENE", 0.0)

    # Frustrado filtrado: razões solicitadas pelo caller
    frustrado_filtrado = float(_frustrado_por_razao(df_calc, razoes).sum())

    pct_total = (nao_ressarcivel / denom_bbi) if denom_bbi > 0 else 0.0
    pct_filtrado = (frustrado_filtrado / denom_bbi) if denom_bbi > 0 else 0.0

    pct_por_razao = {
        r: ((f_por_razao[r] / denom_bbi) if denom_bbi > 0 else 0.0)
        for r in razoes_decomp
    }

    return {
        "output_mwh": output_total,
        "ref_total_mwh": output_total,  # alias backward-compat (UI antiga)
        "frustrado_mwh": frustrado_total,
        "frustrado_filtrado_mwh": frustrado_filtrado,
        "denom_bbi_mwh": denom_bbi,
        "pct_total": pct_total,
        "pct_filtrado": pct_filtrado,
        "pct_por_razao": pct_por_razao,
        "n_linhas": len(df_calc),
    }


def agregar_por_dimensao(
    df: pd.DataFrame,
    dimensoes: list[str],
    razoes: Iterable[str] = RAZOES_OPERATIVAS,
    incluir_par: bool = False,
) -> pd.DataFrame:
    """
    Agrega curtailment por uma ou mais dimensões.

    Args:
        df: DataFrame com schema padrão do data_loader_curtailment
        dimensoes: lista de colunas para groupby (ex.: ['SUBMERCADO', 'FONTE'])
        razoes: razões a serem incluídas no numerador filtrado
        incluir_par: se True, inclui PAR no denominador

    Returns:
        DataFrame com colunas:
            <dimensoes...>,
            OUTPUT_MWH                  : geração realizada total (denominador)
            REF_FINAL_MWH               : alias backward-compat = OUTPUT_MWH
            FRUSTRADO_TOTAL_MWH         : numerador (todas razões operativas)
            FRUSTRADO_FILTRADO_MWH      : numerador filtrado pelas `razoes`
            PCT_TOTAL                   : pct total
            PCT_FILTRADO                : pct das razões solicitadas
            PCT_REL, PCT_CNF, PCT_ENE [, PCT_PAR]
    """
    if len(df) == 0:
        return pd.DataFrame()

    df_calc = _filtrar_par(df, incluir_par).copy()

    # Adicionar colunas auxiliares: frustrado por razão (separado, somando dá o total)
    razoes_decomp = list(RAZOES_TODAS) if incluir_par else list(RAZOES_OPERATIVAS)
    for r in razoes_decomp:
        df_calc[f"_F_{r}"] = df_calc["FRUSTRADO_MWH"].where(
            df_calc["RAZAO"] == r, 0.0
        )

    razoes_set = set(razoes)
    df_calc["_F_FILTRADO"] = df_calc["FRUSTRADO_MWH"].where(
        df_calc["RAZAO"].isin(razoes_set), 0.0
    )

    aggs = {
        "OUTPUT_MWH": "sum",         # denominador
        "FRUSTRADO_MWH": "sum",      # numerador total
        "_F_FILTRADO": "sum",
    }
    for r in razoes_decomp:
        aggs[f"_F_{r}"] = "sum"

    g = df_calc.groupby(dimensoes, dropna=False).agg(aggs).reset_index()

    # Renomear
    g = g.rename(columns={
        "FRUSTRADO_MWH": "FRUSTRADO_TOTAL_MWH",
        "_F_FILTRADO": "FRUSTRADO_FILTRADO_MWH",
    })
    # Alias backward-compat: REF_FINAL_MWH apontava para o denominador
    g["REF_FINAL_MWH"] = g["OUTPUT_MWH"]

    # % calculados (denominador = OUTPUT_MWH = geração realizada total)
    output = g["OUTPUT_MWH"].replace(0, pd.NA)
    g["PCT_TOTAL"] = (g["FRUSTRADO_TOTAL_MWH"] / output).fillna(0.0)
    g["PCT_FILTRADO"] = (g["FRUSTRADO_FILTRADO_MWH"] / output).fillna(0.0)
    for r in razoes_decomp:
        g[f"PCT_{r}"] = (g[f"_F_{r}"] / output).fillna(0.0)

    # Limpar colunas auxiliares
    g = g.drop(columns=[f"_F_{r}" for r in razoes_decomp])

    return g


def matriz_usina_periodo(
    df: pd.DataFrame,
    coluna_periodo: str,
    razoes: Iterable[str] = RAZOES_OPERATIVAS,
    incluir_par: bool = False,
    coluna_usina: str = "USINA",
    colunas_extras: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Monta a tabela 'usinas no eixo Y, períodos no eixo X' com % de
    curtailment como valor de cada célula.

    Fórmula da célula:
        % = sum(FRUSTRADO_MWH onde razao in razoes) / sum(OUTPUT_MWH)

    Args:
        df: dataframe com PERIODO_CHAVE e PERIODO_LABEL adicionados
        coluna_periodo: 'PERIODO_LABEL' (ou 'PERIODO_CHAVE')
        razoes: tipos de restrição a incluir no numerador (1+)
        coluna_usina: nome da coluna que identifica a usina
        colunas_extras: colunas adicionais a manter (ex.: GRUPO_ECONOMICO, FONTE)

    Returns:
        DataFrame pivotado: linhas = usinas, colunas = períodos, valores = %.
        Inclui colunas extras à esquerda (ex.: grupo).
    """
    if len(df) == 0:
        return pd.DataFrame()

    df_calc = _filtrar_par(df, incluir_par).copy()
    razoes_set = set(razoes)

    df_calc["_FRUSTRADO_FILTRADO"] = df_calc["FRUSTRADO_MWH"].where(
        df_calc["RAZAO"].isin(razoes_set), 0.0
    )

    dim_group = [coluna_usina, coluna_periodo]
    if colunas_extras:
        dim_group = colunas_extras + [coluna_usina, coluna_periodo]

    g = df_calc.groupby(dim_group, dropna=False).agg(
        OUTPUT=("OUTPUT_MWH", "sum"),
        FRUSTRADO=("_FRUSTRADO_FILTRADO", "sum"),
    ).reset_index()
    output = g["OUTPUT"].replace(0, pd.NA)
    g["PCT"] = (g["FRUSTRADO"] / output).fillna(0.0)

    # Pivot: períodos viram colunas
    index_cols = [coluna_usina]
    if colunas_extras:
        index_cols = colunas_extras + [coluna_usina]

    matriz = g.pivot_table(
        index=index_cols,
        columns=coluna_periodo,
        values="PCT",
        aggfunc="first",  # 1 valor por (usina, período) garantido pelo groupby
        fill_value=0.0,
    ).reset_index()

    return matriz


def serie_temporal(
    df: pd.DataFrame,
    razoes_decompor: Iterable[str] = RAZOES_OPERATIVAS,
    incluir_par: bool = False,
) -> pd.DataFrame:
    """
    Monta série temporal agregada por período (metodologia BBI).

    Fórmula por período:
        DENOM_BBI = OUTPUT_MWH + FRUSTRADO_CNF + FRUSTRADO_ENE + FRUSTRADO_REL
                  (= geração potencial do período)

        PCT_TOTAL    = (FRUSTRADO_CNF + FRUSTRADO_ENE) / DENOM_BBI
                       ← curtailment NÃO-RESSARCÍVEL apenas
        PCT_<razao>  = FRUSTRADO_<razao> / DENOM_BBI

    REL é mantido na decomposição (aparece no gráfico empilhado para
    transparência operativa), mesmo não somando ao PCT_TOTAL — REL é
    ressarcível pelo ONS, então não é perda financeira.

    Pré-requisito: df já passou por adicionar_chave_periodo().

    Returns:
        DataFrame com colunas:
            PERIODO_CHAVE, PERIODO_LABEL, PERIODO_INICIO, PERIODO_FIM,
            OUTPUT_MWH                : geração realizada do período
            REF_FINAL_MWH             : alias backward-compat = OUTPUT_MWH
            DENOM_BBI_MWH             : Output + frustrado (geração potencial)
            FRUSTRADO_TOTAL_MWH       : numerador bruto (CNF + ENE + REL)
            FRUSTRADO_REL_MWH, FRUSTRADO_CNF_MWH, FRUSTRADO_ENE_MWH,
            PCT_TOTAL                 : (CNF + ENE) / denom_bbi
            PCT_REL, PCT_CNF, PCT_ENE : cada razão / denom_bbi
    """
    if len(df) == 0 or "PERIODO_CHAVE" not in df.columns:
        return pd.DataFrame()

    df_calc = _filtrar_par(df, incluir_par).copy()

    razoes_decomp = list(razoes_decompor)
    if incluir_par and "PAR" not in razoes_decomp:
        razoes_decomp.append("PAR")

    for r in razoes_decomp:
        df_calc[f"_F_{r}"] = df_calc["FRUSTRADO_MWH"].where(
            df_calc["RAZAO"] == r, 0.0
        )

    aggs = {
        "OUTPUT_MWH": "sum",
        "FRUSTRADO_MWH": "sum",
        "PERIODO_LABEL": "first",
        "PERIODO_INICIO": "first",
        "PERIODO_FIM": "first",
    }
    for r in razoes_decomp:
        aggs[f"_F_{r}"] = "sum"

    g = df_calc.groupby("PERIODO_CHAVE", dropna=False).agg(aggs).reset_index()

    g = g.rename(columns={"FRUSTRADO_MWH": "FRUSTRADO_TOTAL_MWH"})
    for r in razoes_decomp:
        g = g.rename(columns={f"_F_{r}": f"FRUSTRADO_{r}_MWH"})
    # Alias backward-compat
    g["REF_FINAL_MWH"] = g["OUTPUT_MWH"]

    # Denominador BBI: geração potencial = Output + todo frustrado do período
    g["DENOM_BBI_MWH"] = g["OUTPUT_MWH"] + g["FRUSTRADO_TOTAL_MWH"]
    denom = g["DENOM_BBI_MWH"].replace(0, pd.NA)

    # PCT_TOTAL: somente CNF + ENE (não-ressarcível). REL ressarcível, fora.
    nao_ressarcivel = pd.Series(0.0, index=g.index)
    if "FRUSTRADO_CNF_MWH" in g.columns:
        nao_ressarcivel = nao_ressarcivel + g["FRUSTRADO_CNF_MWH"]
    if "FRUSTRADO_ENE_MWH" in g.columns:
        nao_ressarcivel = nao_ressarcivel + g["FRUSTRADO_ENE_MWH"]

    g["PCT_TOTAL"] = (nao_ressarcivel / denom).fillna(0.0)
    for r in razoes_decomp:
        g[f"PCT_{r}"] = (g[f"FRUSTRADO_{r}_MWH"] / denom).fillna(0.0)

    g = g.sort_values("PERIODO_INICIO").reset_index(drop=True)
    return g
