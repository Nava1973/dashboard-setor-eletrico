"""
utils_curtailment.py
====================

Cálculos de curtailment para o dashboard.

Metodologia: definição pública do ONS, conforme Power BI oficial em
https://www.ons.org.br/Paginas/faq_curtailment.aspx (Acompanhamento das
Restrições de Geração UEE/UFV).

==================================================================
FÓRMULA (ONS, definição pública)
==================================================================

Para cada linha do ONS (passo semi-horário, valores em MWmed):

    Numerador (frustrado, coluna Q do template ONS):
        IF razao_vazio:
            FRUSTRADO_MWH = 0
        ELSE:
            FRUSTRADO_MWH = MAX(MIN(disponibilidade, geracao_ref) - geracao, 0) * 0.5

    Denominador (geração potencial):
        OUTPUT_MWH      = geracao * 0.5
        DENOM_POTENCIAL = sum(OUTPUT_MWH) + sum(FRUSTRADO_MWH)
                        = Geração Verificada + GNRa total
                        = Output + (CNF + ENE + REL)

    % Curtailment = sum(FRUSTRADO_MWH) / DENOM_POTENCIAL
                  = (CNF + ENE + REL) / (Output + CNF + ENE + REL)

==================================================================
DECOMPOSIÇÃO POR TIPO DE RAZÃO (REL/CNF/ENE):
==================================================================
    Cada razão usa o MESMO denominador (DENOM_POTENCIAL):

        % REL = sum(FRUSTRADO_MWH onde razao=REL) / DENOM_POTENCIAL
        % CNF = sum(FRUSTRADO_MWH onde razao=CNF) / DENOM_POTENCIAL
        % ENE = sum(FRUSTRADO_MWH onde razao=ENE) / DENOM_POTENCIAL

    Soma fechada: % REL + % CNF + % ENE = % Curtailment
    (matematicamente consistente — mesmo denominador, numeradores
    disjuntos somando ao numerador total).

==================================================================
NOTA SOBRE RESSARCIMENTO (REN 1030/2022)
==================================================================
    O ressarcimento financeiro segue regras específicas da ANEEL
    conforme razão (REL ressarcível, ENE não-ressarcível, CNF
    parcial). Este módulo expõe volume físico de curtailment, NÃO
    quantifica ressarcimento financeiro. Para análise estilo
    BBI Utilities (% perda não-ressarcível), calcular separadamente;
    não substituir a métrica pública.

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

from datetime import date, timedelta
from typing import Iterable, Optional

import pandas as pd


# Razões "operativas" (excluindo PAR por padrão)
RAZOES_OPERATIVAS = ("REL", "CNF", "ENE")
RAZOES_TODAS = ("REL", "CNF", "ENE", "PAR")

# Abreviações de mês em pt-BR (usado nos labels da SPEC v2 §6/§7)
_MESES_PT_ABREV = (
    "jan", "fev", "mar", "abr", "mai", "jun",
    "jul", "ago", "set", "out", "nov", "dez",
)


def _label_mes_curto(d: date) -> str:
    """Retorna 'mai/26' (mês abreviado pt-BR + ano com 2 dígitos)."""
    return f"{_MESES_PT_ABREV[d.month - 1]}/{d.year % 100:02d}"


def _label_trimestre_curto(d: date) -> str:
    """Retorna '2T 26' (número do trimestre + ano com 2 dígitos).

    Trimestres calendário ISO: 1T=jan-mar, 2T=abr-jun, 3T=jul-set, 4T=out-dez.

    Convenção BR (B3, ITR/DFP da CVM, jornais financeiros): número
    ANTES da letra T. "T2" é convenção anglo, evitada aqui.
    """
    n_trim = ((d.month - 1) // 3) + 1
    return f"{n_trim}T {d.year % 100:02d}"


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
    Calcula % de curtailment (definição pública do ONS).

    Fórmula:
        denom_potencial = sum(OUTPUT_MWH) + sum(FRUSTRADO_MWH)
                        = Geração Verificada + GNRa total
                        = geração potencial (Output + CNF + ENE + REL)

        pct_total        = sum(FRUSTRADO_MWH) / denom_potencial
                         = (CNF + ENE + REL) / denom_potencial
        pct_por_razao[r] = f_r / denom_potencial

    Soma fechada: pct_por_razao[CNF] + pct_por_razao[ENE]
                + pct_por_razao[REL] = pct_total
    (mesmo denominador, numeradores disjuntos somando ao total).

    Returns:
        dict com chaves:
            output_mwh             : geração realizada (sum OUTPUT_MWH)
            ref_total_mwh          : alias backward-compat = output_mwh
            frustrado_mwh          : numerador (CNF + ENE + REL)
            frustrado_filtrado_mwh : numerador apenas das `razoes` solicitadas
            denom_potencial_mwh    : Output + frustrado (geração potencial)
            pct_total              : frustrado_mwh / denom_potencial
            pct_filtrado           : frustrado_filtrado / denom_potencial
            pct_por_razao          : dict {razao: f_r / denom_potencial}
            n_linhas               : número de linhas processadas
    """
    if len(df) == 0 or "FRUSTRADO_MWH" not in df.columns:
        return {
            "output_mwh": 0.0,
            "ref_total_mwh": 0.0,  # alias backward-compat
            "frustrado_mwh": 0.0,
            "frustrado_filtrado_mwh": 0.0,
            "denom_potencial_mwh": 0.0,
            "pct_total": 0.0,
            "pct_filtrado": 0.0,
            "pct_por_razao": {},
            "n_linhas": 0,
        }

    df_calc = _filtrar_par(df, incluir_par)

    output_total = float(df_calc["OUTPUT_MWH"].sum())
    frustrado_total = float(df_calc["FRUSTRADO_MWH"].sum())  # CNF + ENE + REL
    denom_potencial = output_total + frustrado_total          # geração potencial

    razoes_decomp = list(RAZOES_TODAS) if incluir_par else list(RAZOES_OPERATIVAS)
    f_por_razao = {
        r: float(_frustrado_por_razao(df_calc, [r]).sum())
        for r in razoes_decomp
    }

    frustrado_filtrado = float(_frustrado_por_razao(df_calc, razoes).sum())

    pct_total = (frustrado_total / denom_potencial) if denom_potencial > 0 else 0.0
    pct_filtrado = (frustrado_filtrado / denom_potencial) if denom_potencial > 0 else 0.0

    pct_por_razao = {
        r: ((f_por_razao[r] / denom_potencial) if denom_potencial > 0 else 0.0)
        for r in razoes_decomp
    }

    return {
        "output_mwh": output_total,
        "ref_total_mwh": output_total,  # alias backward-compat (UI antiga)
        "frustrado_mwh": frustrado_total,
        "frustrado_filtrado_mwh": frustrado_filtrado,
        "denom_potencial_mwh": denom_potencial,
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
    Monta série temporal agregada por período (definição ONS).

    Fórmula por período:
        DENOM_POTENCIAL = OUTPUT_MWH + FRUSTRADO_TOTAL_MWH
                        = Geração Verificada + GNRa total
                        (= Output + CNF + ENE + REL)

        PCT_TOTAL    = FRUSTRADO_TOTAL_MWH / DENOM_POTENCIAL
                       = (CNF + ENE + REL) / denom_potencial
        PCT_<razao>  = FRUSTRADO_<razao> / DENOM_POTENCIAL

    Soma fechada: PCT_REL + PCT_CNF + PCT_ENE = PCT_TOTAL.

    Pré-requisito: df já passou por adicionar_chave_periodo().

    Returns:
        DataFrame com colunas:
            PERIODO_CHAVE, PERIODO_LABEL, PERIODO_INICIO, PERIODO_FIM,
            OUTPUT_MWH                : geração realizada do período
            REF_FINAL_MWH             : alias backward-compat = OUTPUT_MWH
            DENOM_POTENCIAL_MWH       : Output + frustrado (geração potencial)
            FRUSTRADO_TOTAL_MWH       : numerador (CNF + ENE + REL)
            FRUSTRADO_REL_MWH, FRUSTRADO_CNF_MWH, FRUSTRADO_ENE_MWH,
            PCT_TOTAL                 : frustrado_total / denom_potencial
            PCT_REL, PCT_CNF, PCT_ENE : cada razão / denom_potencial
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

    # Denominador (geração potencial) = Output + frustrado_total do período
    g["DENOM_POTENCIAL_MWH"] = g["OUTPUT_MWH"] + g["FRUSTRADO_TOTAL_MWH"]
    denom = g["DENOM_POTENCIAL_MWH"].replace(0, pd.NA)

    # PCT_TOTAL = frustrado_total / denom (inclui CNF + ENE + REL, fórmula ONS).
    g["PCT_TOTAL"] = (g["FRUSTRADO_TOTAL_MWH"] / denom).fillna(0.0)
    for r in razoes_decomp:
        g[f"PCT_{r}"] = (g[f"FRUSTRADO_{r}_MWH"] / denom).fillna(0.0)

    g = g.sort_values("PERIODO_INICIO").reset_index(drop=True)
    return g


# ---------------------------------------------------------------------------
# Janelas de período (convenção da SPEC v2 da aba Curtailment §5)
# ---------------------------------------------------------------------------


def _inicio_mes(d: date) -> date:
    """Primeiro dia do mês de d."""
    return date(d.year, d.month, 1)


def _inicio_trimestre(d: date) -> date:
    """Primeiro dia do trimestre que contém d.

    Trimestres ISO: T1=jan-mar, T2=abr-jun, T3=jul-set, T4=out-dez.

    Movido de components/tab_curtailment.py em 2026-05-04 (G.5):
    `calcular_periodos_curtailment` precisa pra calcular janelas
    trimestrais. Mesma família de helpers temporais que `_inicio_mes`.
    Callers em components/tab_curtailment.py atualizados pra importar
    daqui. TODO sessão futura: scripts/medir_memoria_caminho1.py e
    scripts/validar_cache_janela_ampla.py têm cópias locais — podem
    importar daqui também.
    """
    mes_inicio = ((d.month - 1) // 3) * 3 + 1
    return date(d.year, mes_inicio, 1)


def _inicio_trimestre_anterior(d: date, n: int) -> date:
    """Primeiro dia do trimestre N trimestres antes do trimestre de d."""
    inicio_q_atual = _inicio_trimestre(d)
    ano = inicio_q_atual.year
    mes = inicio_q_atual.month - n * 3
    while mes <= 0:
        mes += 12
        ano -= 1
    return date(ano, mes, 1)


def _inicio_mes_anterior(d: date, n: int) -> date:
    """Primeiro dia do mês N meses antes do mês de d (n=0 → mês de d).

    Movido de components/tab_curtailment.py em 2026-05-04 (G.7):
    `calcular_periodos_curtailment` precisa pra calcular janela LTM
    (Last Twelve Months — 12 meses fechados anteriores ao mês de
    max_d). Caller anterior em tab_curtailment.py (presets MENSAL)
    continua, agora importando daqui. Mesma família dos outros
    helpers temporais (_inicio_mes, _inicio_trimestre*).
    """
    ano = d.year
    mes = d.month - n
    while mes <= 0:
        mes += 12
        ano -= 1
    return date(ano, mes, 1)


def calcular_periodos_curtailment(max_d: date) -> dict:
    """
    Retorna 8 janelas ancoradas em max_d (3 meses + 4 trimestres + LTM).

    Usado pela aba Curtailment v2 (SPEC §5 + Fase G.5/G.7) pra montar
    a tabela "Por usina" com 8 colunas de valor: 3 últimos meses
    (corrente parcial + 2 fechados) + 4 trimestres (corrente parcial
    + 3 fechados, cobre comparação YoY) + 1 LTM (Last Twelve Months
    fechados — janela rolling de 12 meses calendário fechados,
    excluindo mês corrente parcial).

    Renomeada de `calcular_3_periodos` em 2026-05-04 (G.5) — nome novo
    reflete realidade pós-extensão. Caller único em produção é
    `_calcular_linhas_unidade` em tab_curtailment.py.

    Returns:
        {
            # 3 meses (chaves preservadas pra rastreabilidade histórica)
            'mes_corrente':   {label, label_curto, sufixo_parcial, ini, fim, dias},
            'mes_anterior':   {label, label_curto, sufixo_parcial: "", ...},
            'penultimo':      {label, label_curto, sufixo_parcial: "", ...},
            # 4 trimestres (G.5)
            'tri_corrente':   {label, label_curto, sufixo_parcial, ini, fim, dias},
            'tri_anterior_1': {label, label_curto, sufixo_parcial: "", ...},
            'tri_anterior_2': {label, label_curto, sufixo_parcial: "", ...},
            'tri_anterior_3': {label, label_curto, sufixo_parcial: "", ...},
            # 1 LTM (G.7)
            'ultimos_12m':    {label, label_curto, segunda_linha, ini, fim, dias},
        }

    Campos de label (SPEC v2 §6 + G.5/G.7):
        - label_curto:    "abr/26" pros meses, "2T 26" pros trimestres,
                          "Últimos" pro LTM.
        - sufixo_parcial: "(até DD/MM)" em mes_corrente E tri_corrente
          (ambos parciais). "" nos demais. Convenção: 2ª linha do header
          em peso visual SUTIL (col-sufixo CSS — opacity 0.85, fonte
          menor).
        - segunda_linha:  "12 meses" no LTM. Convenção: 2ª linha do
          header em peso visual IGUAL ao label principal (col-sub-label
          CSS — descrição essencial da janela, não detalhe sufixado).
        - MUTEX: sufixo_parcial e segunda_linha NUNCA usados juntos no
          mesmo período. Helper de render no caller (_header_cell)
          escolhe um dos dois conforme presença.

    Edge cases:
        - max_d perto do dia 1 do mês: mes_corrente fica com 1-2 dias.
        - max_d no dia 1 do trimestre (1/jan, 1/abr, 1/jul, 1/out):
          tri_corrente fica com 1 dia. SPEC G.5 aceita.
        - LTM independente de onde max_d cai no mês — janela termina
          sempre no último dia do mês ANTERIOR ao mês de max_d.
          Estável durante o mês corrente.
    """
    # ─── 3 meses ───
    corrente_ini = _inicio_mes(max_d)
    corrente_fim = max_d

    anterior_fim = corrente_ini - timedelta(days=1)
    anterior_ini = _inicio_mes(anterior_fim)

    penultimo_fim = anterior_ini - timedelta(days=1)
    penultimo_ini = _inicio_mes(penultimo_fim)

    # ─── 4 trimestres ───
    tri_corrente_ini = _inicio_trimestre(max_d)
    tri_corrente_fim = max_d

    tri_ant_1_ini = _inicio_trimestre_anterior(max_d, 1)
    tri_ant_1_fim = tri_corrente_ini - timedelta(days=1)

    tri_ant_2_ini = _inicio_trimestre_anterior(max_d, 2)
    tri_ant_2_fim = tri_ant_1_ini - timedelta(days=1)

    tri_ant_3_ini = _inicio_trimestre_anterior(max_d, 3)
    tri_ant_3_fim = tri_ant_2_ini - timedelta(days=1)

    # ─── LTM (Last Twelve Months — 12 meses calendário fechados) ───
    # Convenção financeira BR (DRE LTM, EBITDA LTM): janela termina no
    # último dia do mês ANTERIOR ao mês de max_d, indo para trás 12
    # meses. Sempre 12 meses calendário fechados — sem mês corrente
    # parcial. Dado totalmente "limpo".
    ltm_fim = corrente_ini - timedelta(days=1)         # último dia do mês anterior
    ltm_ini = _inicio_mes_anterior(max_d, 12)          # primeiro dia 12 meses antes

    def _entry(
        label: str, label_curto: str,
        ini: date, fim: date,
        sufixo_parcial: str = "",
        segunda_linha: str = "",
    ) -> dict:
        return {
            "label": label,
            "label_curto": label_curto,
            "sufixo_parcial": sufixo_parcial,
            "segunda_linha": segunda_linha,
            "ini": ini,
            "fim": fim,
            "dias": (fim - ini).days + 1,
        }

    sufixo_parcial = f"(até {max_d.strftime('%d/%m')})"

    return {
        # 3 meses
        "mes_corrente": _entry(
            "Mês corrente", _label_mes_curto(corrente_fim),
            corrente_ini, corrente_fim,
            sufixo_parcial=sufixo_parcial,
        ),
        "mes_anterior": _entry(
            "Mês anterior", _label_mes_curto(anterior_fim),
            anterior_ini, anterior_fim,
        ),
        "penultimo": _entry(
            "Penúltimo mês", _label_mes_curto(penultimo_fim),
            penultimo_ini, penultimo_fim,
        ),
        # 4 trimestres
        "tri_corrente": _entry(
            "Trimestre corrente", _label_trimestre_curto(tri_corrente_fim),
            tri_corrente_ini, tri_corrente_fim,
            sufixo_parcial=sufixo_parcial,
        ),
        "tri_anterior_1": _entry(
            "Trimestre anterior", _label_trimestre_curto(tri_ant_1_fim),
            tri_ant_1_ini, tri_ant_1_fim,
        ),
        "tri_anterior_2": _entry(
            "2 trimestres atrás", _label_trimestre_curto(tri_ant_2_fim),
            tri_ant_2_ini, tri_ant_2_fim,
        ),
        "tri_anterior_3": _entry(
            "3 trimestres atrás", _label_trimestre_curto(tri_ant_3_fim),
            tri_ant_3_ini, tri_ant_3_fim,
        ),
        # 1 LTM (G.7) — segunda_linha em vez de sufixo_parcial (mutex)
        "ultimos_12m": _entry(
            "Últimos 12 meses", "Últimos",
            ltm_ini, ltm_fim,
            segunda_linha="12 meses",
        ),
    }


def pct_no_periodo(
    df: pd.DataFrame,
    data_ini: date,
    data_fim: date,
    razao: Optional[str] = None,
) -> Optional[float]:
    """
    Pct curtailment na janela [data_ini, data_fim] (ambas inclusive).

    Filtra df por DATA, chama calcular_pct_curtailment, devolve o pct
    pedido. Convenção do projeto (PAR excluído por default) preservada.

    Args:
        razao: None → pct_total. Senão "ENE" / "CNF" / "REL".
               PAR não é suportado (excluído por convenção do projeto;
               passar PAR levanta ValueError).

    Returns:
        Float em [0, 1] OU None se denom_potencial == 0 (janela vazia
        ou sem geração potencial). Distinção é importante:
          - 0.0   = "tem dados na janela, zero curtailment dessa razão"
          - None  = "sem dados na janela"
    """
    if razao is not None and razao not in {"ENE", "CNF", "REL"}:
        raise ValueError(
            f"razao inválida: {razao!r}. Use None (total) ou um de "
            f"'ENE'/'CNF'/'REL'. PAR não é suportado."
        )

    if "DATA" not in df.columns:
        return None

    sub = df[(df["DATA"] >= data_ini) & (df["DATA"] <= data_fim)]
    r = calcular_pct_curtailment(sub)

    if r["denom_potencial_mwh"] == 0:
        return None

    if razao is None:
        return r["pct_total"]
    return r["pct_por_razao"].get(razao, 0.0)


# ---------------------------------------------------------------------------
# Tests inline — roda com:
#     venv\Scripts\python.exe utils/utils_curtailment.py
#
# Imports do topo do arquivo (datetime, pd) já cobrem o teste — datetime é
# dependência de produção (tipo de retorno + aritmética em
# calcular_periodos_curtailment), não é só de teste.
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # sys.stdout.reconfigure pra evitar UnicodeEncodeError no shell Windows
    # cp1252 (armadilha 4.4 do CLAUDE.md). sys é exclusivo do teste — não é
    # dependência de produção do módulo.
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 70)
    print("TESTE 1: calcular_periodos_curtailment — caso normal (max_d = 2026-04-15)")
    print("=" * 70)
    p = calcular_periodos_curtailment(date(2026, 4, 15))
    for k, v in p.items():
        print(f"  {k:14s}: {v['label']:20s} {v['ini']} → {v['fim']} ({v['dias']:>2}d)")
    # ─── 3 meses ───
    assert p["mes_corrente"]["ini"] == date(2026, 4, 1)
    assert p["mes_corrente"]["fim"] == date(2026, 4, 15)
    assert p["mes_corrente"]["dias"] == 15
    assert p["mes_anterior"]["ini"] == date(2026, 3, 1)
    assert p["mes_anterior"]["fim"] == date(2026, 3, 31)
    assert p["mes_anterior"]["dias"] == 31
    assert p["penultimo"]["ini"] == date(2026, 2, 1)
    assert p["penultimo"]["fim"] == date(2026, 2, 28)  # 2026 não é bissexto
    assert p["penultimo"]["dias"] == 28
    assert p["mes_corrente"]["label_curto"] == "abr/26"
    assert p["mes_corrente"]["sufixo_parcial"] == "(até 15/04)"
    assert p["mes_anterior"]["label_curto"] == "mar/26"
    assert p["mes_anterior"]["sufixo_parcial"] == ""
    assert p["penultimo"]["label_curto"] == "fev/26"
    assert p["penultimo"]["sufixo_parcial"] == ""
    # ─── 4 trimestres (G.5) ───
    # max_d = 15/04/2026 → 2T 26 corrente parcial (abr-jun, só abr até dia 15)
    assert p["tri_corrente"]["ini"] == date(2026, 4, 1)
    assert p["tri_corrente"]["fim"] == date(2026, 4, 15)
    assert p["tri_corrente"]["dias"] == 15
    assert p["tri_corrente"]["label_curto"] == "2T 26"
    assert p["tri_corrente"]["sufixo_parcial"] == "(até 15/04)"
    # 1T 26 fechado (jan-mar 2026)
    assert p["tri_anterior_1"]["ini"] == date(2026, 1, 1)
    assert p["tri_anterior_1"]["fim"] == date(2026, 3, 31)
    assert p["tri_anterior_1"]["dias"] == 31 + 28 + 31  # 90
    assert p["tri_anterior_1"]["label_curto"] == "1T 26"
    assert p["tri_anterior_1"]["sufixo_parcial"] == ""
    # 4T 25 fechado (out-dez 2025)
    assert p["tri_anterior_2"]["ini"] == date(2025, 10, 1)
    assert p["tri_anterior_2"]["fim"] == date(2025, 12, 31)
    assert p["tri_anterior_2"]["label_curto"] == "4T 25"
    # 3T 25 fechado (jul-set 2025)
    assert p["tri_anterior_3"]["ini"] == date(2025, 7, 1)
    assert p["tri_anterior_3"]["fim"] == date(2025, 9, 30)
    assert p["tri_anterior_3"]["label_curto"] == "3T 25"
    # ─── LTM (G.7) ───
    # max_d=15/04/2026 → janela [01/04/2025, 31/03/2026] (12 meses
    # calendário fechados, exclui abr/2026 corrente parcial)
    assert p["ultimos_12m"]["ini"] == date(2025, 4, 1)
    assert p["ultimos_12m"]["fim"] == date(2026, 3, 31)
    assert p["ultimos_12m"]["dias"] == 365  # 2025 não-bissexto
    assert p["ultimos_12m"]["label_curto"] == "Últimos"
    assert p["ultimos_12m"]["segunda_linha"] == "12 meses"
    assert p["ultimos_12m"]["sufixo_parcial"] == ""  # mutex com segunda_linha
    print("  OK")

    print()
    print("=" * 70)
    print("TESTE 2: calcular_periodos_curtailment — edge §10.2 (max_d = 2026-05-02)")
    print("=" * 70)
    p = calcular_periodos_curtailment(date(2026, 5, 2))
    for k, v in p.items():
        print(f"  {k:14s}: {v['label']:20s} {v['ini']} → {v['fim']} ({v['dias']:>2}d)")
    assert p["mes_corrente"]["ini"] == date(2026, 5, 1)
    assert p["mes_corrente"]["fim"] == date(2026, 5, 2)
    assert p["mes_corrente"]["dias"] == 2  # só 1 e 2 de maio
    assert p["mes_anterior"]["ini"] == date(2026, 4, 1)
    assert p["mes_anterior"]["fim"] == date(2026, 4, 30)
    assert p["mes_anterior"]["dias"] == 30
    assert p["penultimo"]["fim"] == date(2026, 3, 31)
    assert p["penultimo"]["dias"] == 31
    assert p["mes_corrente"]["label_curto"] == "mai/26"
    assert p["mes_corrente"]["sufixo_parcial"] == "(até 02/05)"
    # Trimestres: max_d=02/05/2026 ainda no 2T 26 (abr-jun)
    assert p["tri_corrente"]["ini"] == date(2026, 4, 1)
    assert p["tri_corrente"]["fim"] == date(2026, 5, 2)
    assert p["tri_corrente"]["dias"] == 30 + 2  # abr inteiro + 2 dias mai
    assert p["tri_corrente"]["label_curto"] == "2T 26"
    # ─── LTM (G.7) ───
    # max_d=02/05/2026 → janela [01/05/2025, 30/04/2026] (12 meses
    # fechados terminando em abr/2026, exclui mai/2026 corrente parcial)
    assert p["ultimos_12m"]["ini"] == date(2025, 5, 1)
    assert p["ultimos_12m"]["fim"] == date(2026, 4, 30)
    assert p["ultimos_12m"]["dias"] == 365
    assert p["ultimos_12m"]["label_curto"] == "Últimos"
    assert p["ultimos_12m"]["segunda_linha"] == "12 meses"
    print("  OK — mes_corrente com 2 dias é detectável via 'dias' field")

    print()
    print("=" * 70)
    print("TESTE 3: calcular_periodos_curtailment — virada de ano (max_d = 2026-01-15)")
    print("=" * 70)
    p = calcular_periodos_curtailment(date(2026, 1, 15))
    for k, v in p.items():
        print(f"  {k:14s}: {v['label']:20s} {v['ini']} → {v['fim']} ({v['dias']:>2}d)")
    assert p["mes_corrente"]["ini"] == date(2026, 1, 1)
    assert p["mes_corrente"]["fim"] == date(2026, 1, 15)
    assert p["mes_anterior"]["ini"] == date(2025, 12, 1)
    assert p["mes_anterior"]["fim"] == date(2025, 12, 31)
    assert p["mes_anterior"]["dias"] == 31
    assert p["penultimo"]["ini"] == date(2025, 11, 1)
    assert p["penultimo"]["fim"] == date(2025, 11, 30)
    assert p["penultimo"]["dias"] == 30
    assert p["mes_corrente"]["label_curto"] == "jan/26"
    assert p["mes_corrente"]["sufixo_parcial"] == "(até 15/01)"
    assert p["mes_anterior"]["label_curto"] == "dez/25"
    assert p["mes_anterior"]["sufixo_parcial"] == ""
    assert p["penultimo"]["label_curto"] == "nov/25"
    assert p["penultimo"]["sufixo_parcial"] == ""
    # Trimestres: max_d=15/01/2026 → 1T 26 corrente parcial (jan 1-15)
    assert p["tri_corrente"]["ini"] == date(2026, 1, 1)
    assert p["tri_corrente"]["fim"] == date(2026, 1, 15)
    assert p["tri_corrente"]["label_curto"] == "1T 26"
    # 4T 25 fechado (out-dez 2025)
    assert p["tri_anterior_1"]["ini"] == date(2025, 10, 1)
    assert p["tri_anterior_1"]["fim"] == date(2025, 12, 31)
    assert p["tri_anterior_1"]["label_curto"] == "4T 25"
    # 3T 25 fechado (jul-set 2025)
    assert p["tri_anterior_2"]["ini"] == date(2025, 7, 1)
    assert p["tri_anterior_2"]["fim"] == date(2025, 9, 30)
    assert p["tri_anterior_2"]["label_curto"] == "3T 25"
    # 2T 25 fechado (abr-jun 2025)
    assert p["tri_anterior_3"]["ini"] == date(2025, 4, 1)
    assert p["tri_anterior_3"]["fim"] == date(2025, 6, 30)
    assert p["tri_anterior_3"]["label_curto"] == "2T 25"
    # ─── LTM (G.7) ───
    # max_d=15/01/2026 → janela [01/01/2025, 31/12/2025] (ano 2025
    # completo, exclui jan/2026 corrente parcial). Virada de ano OK.
    assert p["ultimos_12m"]["ini"] == date(2025, 1, 1)
    assert p["ultimos_12m"]["fim"] == date(2025, 12, 31)
    assert p["ultimos_12m"]["dias"] == 365
    assert p["ultimos_12m"]["label_curto"] == "Últimos"
    assert p["ultimos_12m"]["segunda_linha"] == "12 meses"
    print("  OK — virada de ano: ano 25 vs 26 corretos + trimestres atravessam virada")

    print()
    print("=" * 70)
    print("TESTE 4: pct_no_periodo — df mockado (3 dias, 2 razões)")
    print("=" * 70)
    # ENE total = 50, CNF total = 30, OUTPUT total = 200
    # denom = 200 + 80 = 280
    # pct_total = 80/280 ≈ 0.2857; pct_ENE = 50/280; pct_CNF = 30/280; pct_REL = 0
    df_mock = pd.DataFrame([
        {"DATA": date(2026, 4, 1), "RAZAO": "ENE", "FRUSTRADO_MWH": 20.0, "OUTPUT_MWH": 70.0},
        {"DATA": date(2026, 4, 2), "RAZAO": "ENE", "FRUSTRADO_MWH": 30.0, "OUTPUT_MWH": 80.0},
        {"DATA": date(2026, 4, 3), "RAZAO": "CNF", "FRUSTRADO_MWH": 30.0, "OUTPUT_MWH": 50.0},
    ])
    pct_total = pct_no_periodo(df_mock, date(2026, 4, 1), date(2026, 4, 3))
    pct_ene   = pct_no_periodo(df_mock, date(2026, 4, 1), date(2026, 4, 3), razao="ENE")
    pct_cnf   = pct_no_periodo(df_mock, date(2026, 4, 1), date(2026, 4, 3), razao="CNF")
    pct_rel   = pct_no_periodo(df_mock, date(2026, 4, 1), date(2026, 4, 3), razao="REL")
    print(f"  pct_total = {pct_total:.4f} (esperado: {80/280:.4f})")
    print(f"  pct_ENE   = {pct_ene:.4f} (esperado: {50/280:.4f})")
    print(f"  pct_CNF   = {pct_cnf:.4f} (esperado: {30/280:.4f})")
    print(f"  pct_REL   = {pct_rel:.4f} (esperado: 0.0000 — sem REL na janela)")
    assert abs(pct_total - 80/280) < 1e-9
    assert abs(pct_ene   - 50/280) < 1e-9
    assert abs(pct_cnf   - 30/280) < 1e-9
    assert pct_rel == 0.0
    print(f"  OK — soma fechada: {pct_ene + pct_cnf + pct_rel:.4f} == {pct_total:.4f}")

    print()
    print("=" * 70)
    print("TESTE 5: pct_no_periodo — janela vazia (denom == 0)")
    print("=" * 70)
    pct_vazio = pct_no_periodo(df_mock, date(2026, 5, 1), date(2026, 5, 31))
    print(f"  pct (mai/2026, sem dados no mock) = {pct_vazio!r}")
    assert pct_vazio is None
    print("  OK — None distingue 'sem dados' de 0.0 'tem dados, zero'")

    print()
    print("=" * 70)
    print("TESTE 6: pct_no_periodo — razão inválida levanta ValueError")
    print("=" * 70)
    try:
        pct_no_periodo(df_mock, date(2026, 4, 1), date(2026, 4, 3), razao="PAR")
        raise AssertionError("Esperava ValueError pra razao='PAR'")
    except ValueError as e:
        print(f"  ValueError esperado: {e}")
    print("  OK")

    print()
    print("Todos os testes passaram.")
