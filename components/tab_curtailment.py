"""
tab_curtailment.py
==================

Aba CURTAILMENT do dashboard do setor elétrico.

Estrutura (sub-abas internas):
    1. Visão geral       - KPIs + série temporal por tipo de restrição
    2. Por estado        - Heatmap UF × tipo                 (em construção)
    3. Por usina         - Matriz usinas × períodos          (em construção)
    4. Por grupo         - Por grupo econômico               (em construção)
    5. Debug mapeamento  - Cobertura Excel ↔ ONS             (em construção)

Granularidades: Diária, Mensal, Trimestral.
Presets de período: 30D, 90D, 6M, 12M, Máx.

Mapeamento de proprietário:
    Fonte primária: data/curtailment/unidades_geradoras.xlsx
    Aliases manuais: data/curtailment/aliases_curtailment.csv
    Rateio proporcional aplicado.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, List, Optional, Tuple

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from data_loaders.data_loader_curtailment import (
    carregar_curtailment, descobrir_ultimo_dia_disponivel,
)
from data_loaders.data_loader_grupos_excel import (
    carregar_grupos_excel, carregar_aliases, aplicar_rateio,
    EXCEL_DEFAULT_PATH,
)
from utils.utils_periodos import adicionar_chave_periodo
from utils.utils_curtailment import (
    calcular_pct_curtailment, serie_temporal,
    calcular_3_periodos, pct_no_periodo,
)


# =============================================================================
# Paleta Bauhaus (duplicada do app.py:61-76 — manter sincronizada).
# Não é importável do app.py por evitar circular import (app importa este).
# Refator futuro: mover pra utils/bauhaus_palette.py compartilhado.
# =============================================================================

BAUHAUS_RED    = "#D62828"
BAUHAUS_YELLOW = "#F6BD16"
BAUHAUS_BLUE   = "#2A6F97"
BAUHAUS_BLACK  = "#1A1A1A"
BAUHAUS_CREAM  = "#F5F1E8"
BAUHAUS_GRAY   = "#4A4A4A"
BAUHAUS_LIGHT  = "#E8E3D4"

# Cores canônicas de fontes de geração (decisão 5.33 do CLAUDE.md)
COR_FONTE_SOLAR  = "#F6BD16"
COR_FONTE_EOLICA = "#8FA31E"


# =============================================================================
# Mapeamento razão → cor + labels (briefing §2.1)
# =============================================================================

CORES_RAZAO = {
    "ENE": BAUHAUS_RED,     # energético (sobreoferta) — ~98% do total histórico
    "CNF": BAUHAUS_YELLOW,  # confiabilidade
    "REL": BAUHAUS_BLUE,    # elétrico (indisponibilidade externa)
    "PAR": BAUHAUS_BLACK,   # parecer de acesso (raramente usado, opt-in)
}

LABELS_RAZAO = {
    "ENE": "Energético",
    "CNF": "Confiabilidade",
    "REL": "Elétrico",
    "PAR": "Parecer Acesso",
}

# Granularidade UI → chave interna do utils_periodos
GRANS_UI = {
    "Diária":     "DIARIO",
    "Mensal":     "MENSAL",
    "Trimestral": "TRIMESTRAL",
}

# =============================================================================
# Presets de período por granularidade.
# - Diária: presets em dias contados pra trás (sem encaixe).
# - Mensal: encaixe em fronteira de mês (1M = mês atual desde dia 1).
# - Trimestral: encaixe em fronteira de trimestre (6M = 2 trimestres).
# Cada tuple: (label, data_ini_fn, is_max). data_ini_fn é Callable[[date], date]
# que recebe max_d e retorna data_ini esperada do preset. Pra "Máx" passa None
# (helper resolve usando min_d).
# =============================================================================

PRESETS_BY_GRAN = {
    "DIARIO": {
        "default": "30D",
        "presets": [
            ("30D",  lambda mx: mx - timedelta(days=30),  False),
            ("90D",  lambda mx: mx - timedelta(days=90),  False),
            ("6M",   lambda mx: mx - timedelta(days=180), False),
            ("12M",  lambda mx: mx - timedelta(days=365), False),
            ("Máx",  None, True),
        ],
    },
    "MENSAL": {
        "default": "3M",
        "presets": [
            ("1M",   lambda mx: _inicio_mes_anterior(mx, 0),  False),
            ("3M",   lambda mx: _inicio_mes_anterior(mx, 2),  False),
            ("6M",   lambda mx: _inicio_mes_anterior(mx, 5),  False),
            ("12M",  lambda mx: _inicio_mes_anterior(mx, 11), False),
            ("Máx",  None, True),
        ],
    },
    "TRIMESTRAL": {
        "default": "6M",
        "presets": [
            ("6M",   lambda mx: _inicio_trimestre_anterior(mx, 1),  False),
            ("12M",  lambda mx: _inicio_trimestre_anterior(mx, 3),  False),
            ("24M",  lambda mx: _inicio_trimestre_anterior(mx, 7),  False),
            ("36M",  lambda mx: _inicio_trimestre_anterior(mx, 11), False),
            ("Máx",  None, True),
        ],
    },
}


# =============================================================================
# Helpers de formatação BR
# =============================================================================


def _fmt_br_curt(v, casas: int = 0) -> str:
    """Número BR: 1.234,56 (milhar ponto, decimal vírgula)."""
    if v is None or pd.isna(v):
        return "—"
    fmt = f"{{:,.{casas}f}}"
    return fmt.format(v).replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_pct_curt(x, casas: int = 2) -> str:
    """Pct BR: '5,32%' (recebe valor 0-1, multiplica por 100)."""
    if x is None or pd.isna(x):
        return "—"
    return _fmt_br_curt(x * 100, casas) + "%"


# =============================================================================
# Helpers de fronteira temporal (mês/trimestre)
# Usados pelos presets adaptativos por granularidade — Mensal e Trimestral
# encaixam em fronteira de mês/trimestre, Diária não encaixa.
# =============================================================================


def _inicio_trimestre(d: date) -> date:
    """Primeiro dia do trimestre que contém d.

    Q1=jan-mar, Q2=abr-jun, Q3=jul-set, Q4=out-dez (calendário ISO).
    """
    mes_inicio = ((d.month - 1) // 3) * 3 + 1
    return date(d.year, mes_inicio, 1)


def _inicio_mes_anterior(d: date, n: int) -> date:
    """Primeiro dia do mês N meses antes do mês de d (n=0 → mês de d)."""
    ano = d.year
    mes = d.month - n
    while mes <= 0:
        mes += 12
        ano -= 1
    return date(ano, mes, 1)


def _inicio_trimestre_anterior(d: date, n: int) -> date:
    """Primeiro dia do trimestre N trimestres antes do trimestre de d."""
    inicio_q_atual = _inicio_trimestre(d)
    return _inicio_mes_anterior(inicio_q_atual, n * 3)


# =============================================================================
# CSS dos KPIs custom + helper (decisão 5.21 — Bebas Neue é all-caps por
# design, então "MWmed"/"MWh" precisa de unidade em Inter mixed-case
# separada do número em Bebas)
# =============================================================================

_CSS_KPI_CURT = """
<style>
.curt-kpi-card {
    background: #F5F1E8;
    border: 2px solid #1A1A1A;
    padding: 8px 12px;
    border-radius: 0;
    text-align: center;
    width: 100%;
    box-sizing: border-box;
    min-height: 6rem;
    display: flex;
    flex-direction: column;
    justify-content: center;
}
.curt-kpi-label {
    font-family: 'Inter', sans-serif;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #1A1A1A;
    font-weight: 700;
    line-height: 1.2;
    word-break: keep-all;
    overflow-wrap: normal;
    hyphens: none;
}
.curt-kpi-value {
    display: flex;
    align-items: baseline;
    justify-content: center;
    margin-top: 0.5rem;
}
.curt-kpi-value-num {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 1.45rem;
    color: #1A1A1A;
    letter-spacing: 0.02em;
    line-height: 1.1;
}
.curt-kpi-value-unit {
    font-family: 'Inter', sans-serif;
    font-size: 0.85rem;
    color: #1A1A1A;
    font-weight: 600;
    margin-left: 0.4rem;
}

/* Variantes de cor pra cards KPI (sub-aba "Por estado").
   Default (sem modifier class) mantém preto BAUHAUS_BLACK. */
.curt-kpi-card.variante-vermelho .curt-kpi-value-num { color: #D62828; }
.curt-kpi-card.variante-azul .curt-kpi-value-num { color: #2A6F97; }
.curt-kpi-card.variante-cinza .curt-kpi-value-num { color: #4A4A4A; }

/* Tabs internas (st.tabs) — fix de cor pra legibilidade.
   Nota: seletor .stTabs é global, mas como o CSS só muda COR DE TEXTO
   (não layout/tamanho/padding), o impacto em outras abas que usem
   st.tabs é benéfico (legibilidade) ou neutro. */
.stTabs [data-baseweb="tab"] p {
    color: #1A1A1A !important;
    font-weight: 500;
}
.stTabs [data-baseweb="tab"][aria-selected="true"] p {
    color: #D62828 !important;
    font-weight: 700;
}
</style>
"""


def _render_kpi_curt(
    label: str, num: str, unit: str = "", variante: str = "default",
) -> str:
    """Renderiza card KPI Bauhaus.

    variante: "default" (preto, padrão da visão geral), "vermelho", "azul",
    "cinza" — controla cor do número via CSS modifier class.
    """
    unit_html = (
        f'<span class="curt-kpi-value-unit">{unit}</span>' if unit else ""
    )
    classe = "curt-kpi-card"
    if variante != "default":
        classe += f" variante-{variante}"
    return (
        f'<div class="{classe}">'
        f'<div class="curt-kpi-label">{label}</div>'
        f'<div class="curt-kpi-value">'
        f'<span class="curt-kpi-value-num">{num}</span>{unit_html}'
        f'</div></div>'
    )


def _placeholder_em_construcao():
    """Placeholder elegante pras sub-abas vazias (Por estado / Por usina /
    Por grupo) — substitui st.info() por div Inter italic centralizado."""
    st.markdown(
        '<div style="font-family:\'Inter\', sans-serif; '
        'font-size:0.95rem; color:#6B6B6B; font-style:italic; '
        'padding: 2rem 0; text-align:center;">'
        'Sub-aba em construção — disponível em breve.'
        '</div>',
        unsafe_allow_html=True,
    )


# =============================================================================
# Helper de período (versão simplificada de app.py:638 — sem single-day mode).
# Decisão 5.6 documenta o helper original. Versão completa fica no app.py por
# enquanto pra evitar circular import. Refator pra módulo compartilhado é
# roadmap futuro.
# =============================================================================


def _render_period_controls_curt(
    *,
    presets: List[Tuple[str, Optional[Callable[[date], date]], bool]],
    session_key_ini: str,
    session_key_fim: str,
    key_prefix: str,
    min_d: date,
    max_d: date,
):
    """N botões de preset + 2 date_inputs em 1 linha. Botão primary
    (amarelo via CSS global do app.py) quando preset ativo.

    Cada tuple do preset: (label, data_ini_fn, is_max).
    - data_ini_fn(max_d) -> date: retorna data_ini esperada do preset.
    - is_max=True: data_ini = min_d (data_ini_fn pode ser None).
    """
    data_ini_atual = st.session_state[session_key_ini]
    data_fim_atual = st.session_state[session_key_fim]

    # Detecta preset ativo: data_fim ancorada em max_d e data_ini bate com
    # data_ini_target (pós-clamp). Clamp em min_d aplicado simetricamente
    # aqui e no clique pra que botão amarelo destaque mesmo após clamp.
    preset_atual = None
    if data_fim_atual == max_d:
        for label, data_ini_fn, is_max in presets:
            if is_max:
                if data_ini_atual == min_d:
                    preset_atual = label
                    break
            else:
                data_ini_target = max(min_d, data_ini_fn(max_d))
                if data_ini_atual == data_ini_target:
                    preset_atual = label
                    break

    n = len(presets)
    cols = st.columns([1] * n + [0.3, 1.4, 1.4])

    for i, (label, data_ini_fn, is_max) in enumerate(presets):
        with cols[i]:
            tipo = "primary" if label == preset_atual else "secondary"
            help_text = (
                f"Máx — desde {min_d.strftime('%d/%m/%Y')}" if is_max else None
            )
            if st.button(
                label, use_container_width=True,
                key=f"{key_prefix}{label}", type=tipo, help=help_text,
            ):
                if is_max:
                    st.session_state[session_key_ini] = min_d
                else:
                    # Clamp em min_d como defesa em profundidade (decisão 5.27)
                    st.session_state[session_key_ini] = max(
                        min_d, data_ini_fn(max_d)
                    )
                st.session_state[session_key_fim] = max_d
                st.rerun()

    with cols[n + 1]:
        st.date_input(
            "Data inicial", min_value=min_d, max_value=max_d,
            key=session_key_ini,
        )
    with cols[n + 2]:
        st.date_input(
            "Data final", min_value=min_d, max_value=max_d,
            key=session_key_fim,
        )


# =============================================================================
# Sub-aba: Visão geral
# =============================================================================


def _render_visao_geral(
    df: pd.DataFrame,
    granularidade: str,
    granularidade_ui: str,
    fonte_label: str,
    data_ini: date,
    data_fim: date,
    *,
    filtro_unidade: Optional[str] = None,
    filtro_grupo: Optional[str] = None,
    titulo_contexto: Optional[str] = None,
):
    """KPIs + série temporal de % curtailment por tipo de restrição.

    df: DataFrame COM rateio aplicado e JÁ filtrado por janela e fonte
        conforme escolha do usuário nos controles globais.

    Filtros opcionais (modo drill-down — SPEC §8):
        filtro_unidade: se passado, filtra df por NOME_USINA_DASH == valor.
        filtro_grupo:   se passado, filtra df por PROPRIETARIO == valor.
        Apenas um dos dois pode ser não-nulo (ValueError se ambos).
        Quando ambos None, comportamento é 100% idêntico ao chamado original.

    titulo_contexto: aceito mas NÃO renderizado nesta fase. Reservado pro
        breadcrumb/badge da Fase E (SPEC §8.2: "Curtailment › Por grupo ›
        Engie (Eólica)"). Manter na assinatura agora pra fechar o contrato
        completo da função em uma fase só.
    """
    if filtro_unidade is not None and filtro_grupo is not None:
        raise ValueError(
            "filtro_unidade e filtro_grupo são mutuamente exclusivos — "
            "passar apenas um (ou nenhum)."
        )

    if filtro_unidade is not None:
        df = df[df["NOME_USINA_DASH"] == filtro_unidade]
    elif filtro_grupo is not None:
        df = df[df["PROPRIETARIO"] == filtro_grupo]

    # =========================================================================
    # KPIs — 4 cards Bauhaus (% Total / % Energ / % Confiab / % Elétr)
    # =========================================================================
    r = calcular_pct_curtailment(df)
    pct_total = r["pct_total"]
    pct_ene = r["pct_por_razao"].get("ENE", 0.0)
    pct_cnf = r["pct_por_razao"].get("CNF", 0.0)
    pct_rel = r["pct_por_razao"].get("REL", 0.0)

    # Header dos KPIs (padrão da Carga, app.py:4231).
    # TODO: quando "Por estado" for implementado, "(SIN)" troca pra
    # UF selecionada (BAHIA/RN/etc) dinamicamente.
    st.markdown(
        '<div style="font-family:\'Inter\', sans-serif; '
        'font-size:0.85rem; color:#6B6B6B; font-style:italic; '
        'margin:0.6rem 0 0.5rem 0;">'
        'Indicadores do período selecionado (SIN).'
        '</div>',
        unsafe_allow_html=True,
    )

    kpi_cols = st.columns(4)
    with kpi_cols[0]:
        st.markdown(
            _render_kpi_curt("% CURTAILMENT", _fmt_pct_curt(pct_total)),
            unsafe_allow_html=True,
        )
    with kpi_cols[1]:
        st.markdown(
            _render_kpi_curt("% ENERGÉTICO", _fmt_pct_curt(pct_ene)),
            unsafe_allow_html=True,
        )
    with kpi_cols[2]:
        st.markdown(
            _render_kpi_curt("% CONFIABILIDADE", _fmt_pct_curt(pct_cnf)),
            unsafe_allow_html=True,
        )
    with kpi_cols[3]:
        st.markdown(
            _render_kpi_curt("% ELÉTRICO", _fmt_pct_curt(pct_rel)),
            unsafe_allow_html=True,
        )

    # =========================================================================
    # Título Bauhaus do gráfico (mesmo padrão Carga/Geração)
    # =========================================================================
    periodo_str = (
        f"{data_ini.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}"
    )
    st.markdown(
        f'<div style="display:flex; justify-content:space-between; '
        f'align-items:baseline; '
        f"font-family:'Bebas Neue', sans-serif; "
        f'font-size:1.1rem; letter-spacing:0.08em; color:#1A1A1A; '
        f'margin: 2.6rem 0 0.3rem 0; padding-bottom:3px; '
        f'border-bottom: 2px solid #1A1A1A;">'
        # TODO: quando "Por estado" for implementado, "SIN" troca pra
        # localizacao_label.upper() (BAHIA/RN/etc) dinamicamente.
        f'<span>CURTAILMENT POR TIPO DE RESTRIÇÃO · {fonte_label.upper()} · SIN</span>'
        f'<span>{periodo_str}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # =========================================================================
    # Tag de granularidade (decisão 5.22)
    # =========================================================================
    st.markdown(
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.9rem; color:#1A1A1A; font-weight:500; '
        f'letter-spacing:0.04em; margin:0 0 0.5rem 0;">'
        f'{granularidade_ui} · % curtailment'
        f'</div>',
        unsafe_allow_html=True,
    )

    # =========================================================================
    # Série temporal: barras empilhadas por razão (ENE / CNF / REL)
    # =========================================================================
    df_p = adicionar_chave_periodo(df, granularidade)
    s = serie_temporal(df_p)

    if len(s) == 0:
        st.warning("Sem dados de curtailment no período selecionado.")
        return  # sub-aba sem dados — não mata as outras (issue do user)

    fig = go.Figure()
    razoes_ordem = ["ENE", "CNF", "REL"]
    for razao in razoes_ordem:
        col_pct = f"PCT_{razao}"
        if col_pct not in s.columns:
            continue
        cor = CORES_RAZAO[razao]
        label_razao = LABELS_RAZAO[razao]
        # Padded label pra alinhamento monospace no hover unified
        label_fix = label_razao.ljust(15).replace(" ", "&nbsp;")
        fig.add_trace(go.Bar(
            x=s["PERIODO_LABEL"],
            y=s[col_pct] * 100,
            name=label_razao,
            marker=dict(color=cor),
            hovertemplate=(
                f'<span style="color:{cor}; font-weight:700;">'
                f'{label_fix}</span>'
                '&nbsp;&nbsp;'
                '<span style="color:#1A1A1A;">%{y:.2f}%</span>'
                '<extra></extra>'
            ),
        ))

    # TODO(curtailment): xaxis.type="category" funciona bem em Mensal/
    # Trimestral (poucos pontos), mas vai ficar amontoado em
    # Diária + 12M (~365 labels). Resolver na próxima iteração com
    # detecção condicional: granularidade=="DIARIO" → datetime + hoverformat
    # como na Geração; senão → category. Issue conhecida documentada.
    fig.update_layout(
        barmode="stack",
        height=450,
        margin=dict(l=20, r=20, t=40, b=20),
        paper_bgcolor=BAUHAUS_CREAM,
        plot_bgcolor=BAUHAUS_CREAM,
        separators=",.",
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=BAUHAUS_CREAM,
            bordercolor=BAUHAUS_BLACK,
            font=dict(
                family="'IBM Plex Mono', 'Courier New', monospace",
                size=12, color=BAUHAUS_BLACK,
            ),
        ),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.02,
            xanchor="left", x=0,
            bgcolor="rgba(0,0,0,0)",
            font=dict(
                family="Bebas Neue, sans-serif",
                size=19, color=BAUHAUS_BLACK,
            ),
        ),
        xaxis=dict(
            title=None, showgrid=False, showline=True,
            linewidth=2, linecolor=BAUHAUS_BLACK,
            ticks="outside", tickcolor=BAUHAUS_BLACK,
            tickfont=dict(
                family="Inter, sans-serif",
                size=13, color=BAUHAUS_BLACK,
            ),
            type="category",  # PERIODO_LABEL é string ("Abr/25" etc.)
        ),
        yaxis=dict(
            title=None,
            showgrid=True, gridcolor=BAUHAUS_LIGHT, gridwidth=1,
            showline=True, linewidth=2, linecolor=BAUHAUS_BLACK,
            ticks="outside", tickcolor=BAUHAUS_BLACK,
            tickfont=dict(
                family="Inter, sans-serif",
                size=13, color=BAUHAUS_BLACK,
            ),
            zeroline=False,
            ticksuffix="%",
            tickformat=",.1f",
        ),
        font=dict(family="Inter, sans-serif", size=12),
    )

    st.plotly_chart(
        fig, use_container_width=True, config={"displaylogo": False},
    )

    # =========================================================================
    # Expander glossário — perto do gráfico (UX: dúvida surge no contexto visual)
    # =========================================================================
    with st.expander("ⓘ Como é calculado"):
        st.markdown(
            "**Metodologia adotada**: definição pública do ONS, conforme "
            "dashboard oficial em https://www.ons.org.br/Paginas/faq_curtailment.aspx "
            "(Acompanhamento das Restrições de Geração UEE/UFV).\n\n"
            "**Numerador**: GNRa (Geração Não Realizada apurada) por razão "
            "ou total, em MWh.\n\n"
            "**Denominador**: geração potencial total (MWh) = "
            "`Geração Verificada + GNRa total` = `Output + (CNF + ENE + REL)`. "
            "Representa o que a usina poderia ter gerado se não houvesse restrição.\n\n"
            "**% Curtailment** = (CNF + ENE + REL) / (Output + CNF + ENE + REL)\n\n"
            "**Decomposição por razão**: cada razão é exibida com o **mesmo "
            "denominador**, então `% ENE + % CNF + % REL = % Curtailment` "
            "(matematicamente consistente).\n\n"
            "**Tipos de restrição**:\n"
            "- **ENE** (energético): sobreoferta de energia no sistema\n"
            "- **CNF** (confiabilidade): restrição por confiabilidade operativa\n"
            "- **REL** (elétrico/indisponibilidade externa): restrição em "
            "instalações externas (Rede Básica/DITs)\n"
            "- **PAR** (parecer de acesso): restrição contratual prévia "
            "(excluído por padrão)\n\n"
            "**Nota sobre ressarcimento (REN 1030/2022)**: o ressarcimento "
            "financeiro segue regras específicas da ANEEL conforme razão "
            "(REL ressarcível, ENE não-ressarcível, CNF parcialmente). "
            "Esse dashboard mostra volume físico de curtailment, não "
            "quantifica ressarcimento financeiro.\n\n"
            "**Comparação com Power BI público do ONS**: pequenas diferenças "
            "(~2-3%) podem ocorrer ao comparar com o Power BI público do ONS. "
            "O dashboard consome o dataset oficial de Constrained-off (ONS "
            "Dados Abertos, conforme REN 1030/2022), idêntico ao consultado "
            "pelo Power BI ONS. O gap residual é inerente a possíveis "
            "cruzamentos adicionais ou refinamentos na apresentação do "
            "Power BI ONS, e não pode ser eliminado apenas no dashboard."
        )

    # =========================================================================
    # Botão download CSV (alinhado à direita)
    # =========================================================================
    df_export = s.copy()
    # Multiplicar PCT_* por 100 pra exportar como % (ex: 5,32% em vez de 0,0532)
    for col in [c for c in df_export.columns if c.startswith("PCT_")]:
        df_export[col] = df_export[col] * 100

    rename_csv = {
        "PERIODO_LABEL":         "Período",
        "PERIODO_INICIO":        "Início",
        "PERIODO_FIM":           "Fim",
        "OUTPUT_MWH":            "Output (MWh)",
        "REF_FINAL_MWH":         "Ref Final (MWh)",
        "FRUSTRADO_TOTAL_MWH":   "Frustrado Total (MWh)",
        "FRUSTRADO_REL_MWH":     "Frustrado REL (MWh)",
        "FRUSTRADO_CNF_MWH":     "Frustrado CNF (MWh)",
        "FRUSTRADO_ENE_MWH":     "Frustrado ENE (MWh)",
        "PCT_TOTAL":             "% Curtailment",
        "PCT_REL":               "% Elétrico",
        "PCT_CNF":               "% Confiabilidade",
        "PCT_ENE":               "% Energético",
    }
    df_export = df_export.rename(columns=rename_csv)
    csv = df_export.to_csv(
        index=False, sep=";", decimal=",",
    ).encode("utf-8-sig")

    fonte_slug = (
        fonte_label.lower()
        .replace("ó", "o")
        .replace("â", "a")
    )
    filename = (
        f"curtailment_{granularidade.lower()}_{fonte_slug}_"
        f"{data_ini.strftime('%Y%m%d')}_{data_fim.strftime('%Y%m%d')}.csv"
    )

    col_dl_l, col_dl_r = st.columns([3, 1])
    with col_dl_r:
        st.download_button(
            "Baixar CSV",
            data=csv,
            file_name=filename,
            mime="text/csv",
            use_container_width=True,
        )


# =============================================================================
# Sub-aba: Por unidade — SPEC §6 (C.1: Total apenas, sem hover, sem click)
# =============================================================================

_CSS_TABELA_UNIDADES = """
<style>
.curt-tab-unid-wrap {
    max-height: 600px;
    overflow-y: auto;
    border: 2px solid #1A1A1A;
    background: #F5F1E8;
    margin: 0.5rem 0 1rem 0;
    /* Scrollbar Bauhaus (Firefox) */
    scrollbar-width: auto;
    scrollbar-color: #1A1A1A #F5F1E8;
}
/* Scrollbar Bauhaus (Chrome/Edge/Safari) — escopada, não vaza pra outros containers */
.curt-tab-unid-wrap::-webkit-scrollbar {
    width: 12px;
}
.curt-tab-unid-wrap::-webkit-scrollbar-track {
    background: #F5F1E8;
}
.curt-tab-unid-wrap::-webkit-scrollbar-thumb {
    background: #1A1A1A;
    border: 2px solid #F5F1E8;
}
.curt-tab-unid {
    width: 100%;
    border-collapse: collapse;
    /* Larguras fixas — header maior do mês corrente ("até XX/XX") não
       distorce as 3 colunas numéricas (decisão Smoke 2 da Sessão C.1). */
    table-layout: fixed;
    font-family: 'Inter', sans-serif;
    font-size: 0.85rem;
}
/* 22% Unidade + 22% Proprietário + 18% × 3 períodos = 100% */
.curt-tab-unid th:nth-child(1), .curt-tab-unid td:nth-child(1) { width: 22%; }
.curt-tab-unid th:nth-child(2), .curt-tab-unid td:nth-child(2) { width: 22%; }
.curt-tab-unid th.col-num, .curt-tab-unid td.col-num { width: 18%; }
.curt-tab-unid thead th {
    position: sticky;
    top: 0;
    background: #1A1A1A;
    color: #F5F1E8;
    font-family: 'Inter', sans-serif;
    font-size: 0.85rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    text-align: left;
    padding: 10px 14px;
    border-bottom: 2px solid #1A1A1A;
    z-index: 10;
}
.curt-tab-unid thead th.col-num {
    text-align: right;
}
/* Sufixo "(até DD/MM)" do mês corrente em 2ª linha do header — menor,
   normal weight, não-uppercase pra contrastar com o "MAI/26" principal. */
.curt-tab-unid thead th .col-sufixo {
    display: block;
    font-size: 0.7rem;
    font-weight: 400;
    text-transform: none;
    letter-spacing: 0;
    margin-top: 2px;
    opacity: 0.85;
}
.curt-tab-unid tbody td {
    padding: 10px 14px;
    border-bottom: 1px solid #E8E3D4;
    color: #1A1A1A;
    vertical-align: top;
    /* Trunca nomes muito longos com ellipsis em vez de quebrar (table-layout
       fixed obrigaria quebra automática feia). */
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.curt-tab-unid tbody td.col-num {
    font-family: 'JetBrains Mono', 'Courier New', monospace;
    text-align: right;
    white-space: nowrap;
}
.curt-tab-unid tbody td.col-prop-other {
    color: #6B6B6B;
    font-style: italic;
}
.curt-tab-unid tbody tr:last-child td {
    border-bottom: none;
}
</style>
"""

# Display do PROPRIETARIO "outros" (SPEC §6.6).
# 2 variantes coexistem na base atual: "Other" (do Excel — proprietário
# cadastrado como genérico) e "Other (sem mapeamento)" (gerado por
# aplicar_rateio quando linha do ONS não casa com nenhum nome do Excel).
# Match por prefixo cobre ambos + variantes futuras ("Other (excluído)",
# etc.) sem atualizar constante. Trade-off: se aparecer um proprietário
# legítimo cujo nome começa com "Other" (improvável; análise atual
# confirma que não ocorre), entraria no balde.
_PROP_OTHER_LABEL = "Outros"


def _is_proprietario_outros(prop) -> bool:
    """True se o PROPRIETARIO deve cair no balde 'Outros / Não classificado'."""
    if prop is None or pd.isna(prop):
        return True
    return str(prop).strip().lower().startswith("other")


@st.cache_data(show_spinner=False)
def _calcular_linhas_unidade(df: pd.DataFrame) -> list:
    """Calcula pct_total nos 3 períodos pra cada unidade do df.

    Decisões de produto (SPEC §6 + confirmação Nava):
    - Suprime unidades sem dado em NENHUM dos 3 períodos (todas pcts None).
    - Ordenação: decrescente por pct mês corrente; unidades sem dado no mês
      corrente vão pro fim em ordem alfabética.
    - PROPRIETARIO display fica pro caller (este helper retorna o valor cru).

    Cacheado: o cálculo é determinístico em df, e roda ~810× pct_no_periodo
    (~270 unidades × 3 períodos). Cache evita repetir em reruns que não
    mudam df_filtrado (ex: troca de granularidade global, navegação entre
    sub-abas).
    """
    if len(df) == 0 or df["DATA"].isna().all():
        return []

    max_d = pd.Timestamp(df["DATA"].max()).date()
    periodos = calcular_3_periodos(max_d)

    linhas = []
    for nome_usina, sub in df.groupby("NOME_USINA_DASH"):
        prop = sub["PROPRIETARIO"].iloc[0]
        pcts = {
            k: pct_no_periodo(sub, p["ini"], p["fim"])
            for k, p in periodos.items()
        }
        if all(v is None for v in pcts.values()):
            continue
        linhas.append({
            "unidade": nome_usina,
            "proprietario": prop,
            "mes_corrente": pcts["mes_corrente"],
            "mes_anterior": pcts["mes_anterior"],
            "penultimo": pcts["penultimo"],
        })

    linhas.sort(key=lambda r: (
        r["mes_corrente"] is None,
        -(r["mes_corrente"] or 0.0),
        r["unidade"],
    ))
    return linhas


def _montar_html_tabela_unidades(periodos: dict, linhas: list) -> str:
    """Monta string HTML da tabela. CSS em _CSS_TABELA_UNIDADES."""
    rows_html = []
    for r in linhas:
        is_other = _is_proprietario_outros(r["proprietario"])
        prop_class = "col-prop-other" if is_other else ""
        prop_label = _PROP_OTHER_LABEL if is_other else r["proprietario"]
        rows_html.append(
            '<tr>'
            f'<td>{r["unidade"]}</td>'
            f'<td class="{prop_class}">{prop_label}</td>'
            f'<td class="col-num">{_fmt_pct_curt(r["mes_corrente"])}</td>'
            f'<td class="col-num">{_fmt_pct_curt(r["mes_anterior"])}</td>'
            f'<td class="col-num">{_fmt_pct_curt(r["penultimo"])}</td>'
            '</tr>'
        )

    def _header_cell(p: dict) -> str:
        sufixo = p.get("sufixo_parcial", "")
        sufixo_html = (
            f'<span class="col-sufixo">{sufixo}</span>' if sufixo else ""
        )
        return f'<th class="col-num">{p["label_curto"]}{sufixo_html}</th>'

    headers = (
        '<thead><tr>'
        '<th>Unidade</th>'
        '<th>Proprietário</th>'
        f'{_header_cell(periodos["mes_corrente"])}'
        f'{_header_cell(periodos["mes_anterior"])}'
        f'{_header_cell(periodos["penultimo"])}'
        '</tr></thead>'
    )
    body = f'<tbody>{"".join(rows_html)}</tbody>'
    return (
        '<div class="curt-tab-unid-wrap">'
        '<table class="curt-tab-unid">'
        f'{headers}{body}'
        '</table></div>'
    )


def _render_por_unidade(df: pd.DataFrame) -> None:
    """Sub-aba "Por usina" — tabela de unidades com curtailment nos 3 períodos.

    C.1: só coluna Total, sem seletor de razão, sem hover, sem click.
    Próximas sub-fases adicionam: C.2 seletor, C.3 tooltip rico, C.4 click.
    """
    if len(df) == 0 or df["DATA"].isna().all():
        st.info("Sem dados pra esta combinação de filtros.")
        return

    max_d = pd.Timestamp(df["DATA"].max()).date()
    periodos = calcular_3_periodos(max_d)
    linhas = _calcular_linhas_unidade(df)

    if not linhas:
        st.info(
            "Nenhuma unidade com curtailment registrado nos 3 períodos analisados."
        )
        return

    st.markdown(
        '<div style="font-family:\'Inter\', sans-serif; '
        'font-size:0.85rem; color:#6B6B6B; font-style:italic; '
        'margin:0.6rem 0 0.5rem 0;">'
        'Cada linha é uma unidade geradora com algum corte registrado pelo '
        'ONS em pelo menos um dos 3 períodos. Unidades sem ocorrências de '
        'curtailment não aparecem. % calculado sobre geração potencial da '
        'unidade no período.'
        '</div>',
        unsafe_allow_html=True,
    )

    st.markdown(_CSS_TABELA_UNIDADES, unsafe_allow_html=True)
    st.markdown(
        _montar_html_tabela_unidades(periodos, linhas),
        unsafe_allow_html=True,
    )


# =============================================================================
# Sub-aba: Por estado (mapa choropleth)
# =============================================================================


@st.cache_data
def _carregar_geojson_estados() -> dict:
    """Carrega GeoJSON simplificado dos 27 estados BR (data/curtailment/brazil_states.geojson).

    Cache por sessão Streamlit evita re-leitura/parse do arquivo a cada rerun.
    Chave de join: properties.sigla casa direto com df_post.UF (12/12 match).
    """
    import json
    from pathlib import Path
    return json.loads(
        Path("data/curtailment/brazil_states.geojson").read_text(encoding="utf-8")
    )


def _nome_estado(uf: str) -> str:
    """Retorna nome do estado em português (ex: 'BA' → 'Bahia').

    Usa GeoJSON cacheado via _carregar_geojson_estados.
    Fallback: retorna a própria UF se não encontrar.
    """
    gj = _carregar_geojson_estados()
    for f in gj["features"]:
        if f["properties"]["sigla"] == uf:
            return f["properties"]["name"]
    return uf


def _calcular_kpis_escopo(df: pd.DataFrame) -> dict:
    """Calcula % curtailment + decomposição por razão (fórmula ONS).

        % X = sum(FRUSTRADO_X) / (sum(FRUSTRADO_TOTAL) + sum(OUTPUT))

    Retorna ratios 0-1 (não percentuais 0-100) — compatível com
    _fmt_pct_curt que multiplica por 100 ao formatar.

    Garantia matemática: pct_ene + pct_cnf + pct_rel == pct_total.
    """
    fr_total = float(df["FRUSTRADO_MWH"].sum())
    ot_total = float(df["OUTPUT_MWH"].sum())
    denom = fr_total + ot_total
    if denom <= 0:
        return {"pct_total": 0.0, "pct_ene": 0.0, "pct_cnf": 0.0, "pct_rel": 0.0}
    fr_ene = float(df.loc[df["RAZAO"] == "ENE", "FRUSTRADO_MWH"].sum())
    fr_cnf = float(df.loc[df["RAZAO"] == "CNF", "FRUSTRADO_MWH"].sum())
    fr_rel = float(df.loc[df["RAZAO"] == "REL", "FRUSTRADO_MWH"].sum())
    return {
        "pct_total": fr_total / denom,
        "pct_ene":   fr_ene   / denom,
        "pct_cnf":   fr_cnf   / denom,
        "pct_rel":   fr_rel   / denom,
    }


def _render_kpis_por_estado(
    df_filtrado: pd.DataFrame,
    uf_selecionada: Optional[str],
    fonte_label: str,
) -> None:
    """Renderiza row de KPIs reativos por estado.

    - uf_selecionada=None  → 4 cards do Brasil agregado.
    - uf_selecionada='XX'  → 5 cards (4 do estado + 1 do Brasil pra comparação).

    Cores Bauhaus:
      - Card 1 (% Curtailment do escopo): vermelho — destaque principal
      - Cards 2/3/4 (ENE/CNF/REL): azul — decomposição secundária
      - Card 5 (% Brasil, só em modo estado): cinza — referência
    """
    kpis_br = _calcular_kpis_escopo(df_filtrado)

    if uf_selecionada is None:
        label_total = "Curtailment Brasil"
        cols = st.columns(4)
        valores = kpis_br
    else:
        df_estado = df_filtrado[df_filtrado["UF"] == uf_selecionada]
        valores = _calcular_kpis_escopo(df_estado)
        label_total = f"Curtailment {uf_selecionada}"
        cols = st.columns(5)

    with cols[0]:
        st.markdown(
            _render_kpi_curt(
                label_total, _fmt_pct_curt(valores["pct_total"]),
                variante="vermelho",
            ),
            unsafe_allow_html=True,
        )
    with cols[1]:
        st.markdown(
            _render_kpi_curt(
                "Energético<br>(ENE)", _fmt_pct_curt(valores["pct_ene"]),
                variante="azul",
            ),
            unsafe_allow_html=True,
        )
    with cols[2]:
        st.markdown(
            _render_kpi_curt(
                "Confiabilidade<br>(CNF)", _fmt_pct_curt(valores["pct_cnf"]),
                variante="azul",
            ),
            unsafe_allow_html=True,
        )
    with cols[3]:
        st.markdown(
            _render_kpi_curt(
                "Elétrico<br>(REL)", _fmt_pct_curt(valores["pct_rel"]),
                variante="azul",
            ),
            unsafe_allow_html=True,
        )

    if uf_selecionada is not None:
        with cols[4]:
            st.markdown(
                _render_kpi_curt(
                    "Curtailment Brasil",
                    _fmt_pct_curt(kpis_br["pct_total"]),
                    variante="cinza",
                ),
                unsafe_allow_html=True,
            )


def _render_mapa_estado(
    df_filtrado: pd.DataFrame,
    fonte_label: str,
) -> go.Figure:
    """Mapa choropleth do Brasil com % Curtailment por UF.

    - Estados COM dados: gradiente Bauhaus creme→amarelo→vermelho.
    - Estados SEM dados: cinza claro com tooltip "sem curtailment no período".
    - Hover rico no trace colorido: % Curtailment + Frustrado (MWh + MWmed).

    Função NÃO chama st.plotly_chart — retorna go.Figure pra integrador
    decidir layout (st.columns etc).

    Args:
        df_filtrado: DataFrame pós-aplicar_rateio + filtro fonte/janela.
                     Precisa colunas UF, FRUSTRADO_MWH, OUTPUT_MWH, DATA_HORA.
        fonte_label: "Solar" ou "Eólica" (futuro: usar em título).
    """
    gj = _carregar_geojson_estados()
    todas_siglas = [f["properties"]["sigla"] for f in gj["features"]]
    nomes_pt = {f["properties"]["sigla"]: f["properties"]["name"]
                for f in gj["features"]}

    # Agrega por UF (denominador = Output + Frustrado, fórmula ONS)
    agg = df_filtrado.groupby("UF", dropna=False).agg(
        FRUSTRADO_MWH=("FRUSTRADO_MWH", "sum"),
        OUTPUT_MWH=("OUTPUT_MWH", "sum"),
    ).reset_index()
    denom = agg["FRUSTRADO_MWH"] + agg["OUTPUT_MWH"]
    agg["PCT"] = (agg["FRUSTRADO_MWH"] / denom.replace(0, pd.NA) * 100).fillna(0)

    # Horas reais do período pra calcular MWmed (span de DATA_HORA)
    if "DATA_HORA" in df_filtrado.columns and len(df_filtrado) > 0:
        horas = max(
            (df_filtrado["DATA_HORA"].max() - df_filtrado["DATA_HORA"].min())
            .total_seconds() / 3600,
            0.5,
        )
    else:
        horas = 1.0
    agg["MWMED"] = agg["FRUSTRADO_MWH"] / horas
    agg["NOME_PT"] = agg["UF"].map(lambda u: nomes_pt.get(u, u))
    agg["FRUSTRADO_FMT"] = agg["FRUSTRADO_MWH"].apply(lambda v: _fmt_br_curt(v, 0))
    agg["MWMED_FMT"] = agg["MWMED"].apply(lambda v: _fmt_br_curt(v, 0))

    cd_colored = list(zip(
        agg["NOME_PT"], agg["FRUSTRADO_FMT"], agg["MWMED_FMT"],
    ))

    # Trace 1: estados sem dados (cinza, background)
    ufs_sem = [s for s in todas_siglas if s not in agg["UF"].values]
    trace_cinza = go.Choropleth(
        geojson=gj,
        featureidkey="properties.sigla",
        locations=ufs_sem,
        z=[0] * len(ufs_sem),
        colorscale=[[0, "#E5E5E5"], [1, "#E5E5E5"]],
        showscale=False,
        customdata=[[nomes_pt[u]] for u in ufs_sem],
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "sem curtailment no período<extra></extra>"
        ),
        marker=dict(line=dict(color=BAUHAUS_BLACK, width=0.5)),
        name="sem dados",
    )

    # Trace 2: estados com dados (gradiente Bauhaus, foreground)
    trace_colored = go.Choropleth(
        geojson=gj,
        featureidkey="properties.sigla",
        locations=agg["UF"].tolist(),
        z=agg["PCT"].tolist(),
        colorscale=[[0, BAUHAUS_CREAM], [0.5, BAUHAUS_YELLOW], [1, BAUHAUS_RED]],
        customdata=cd_colored,
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "% Curtailment: %{z:.2f}%<br>"
            "Frustrado: %{customdata[1]} MWh "
            "(%{customdata[2]} MWmed)<extra></extra>"
        ),
        marker=dict(line=dict(color=BAUHAUS_BLACK, width=0.5)),
        colorbar=dict(
            title=dict(
                text="% Curt.",
                font=dict(family="Inter, sans-serif", size=12,
                          color=BAUHAUS_BLACK),
            ),
            thickness=12, len=0.7,
            tickfont=dict(family="Inter, sans-serif", size=10,
                          color=BAUHAUS_BLACK),
            ticksuffix="%", tickformat=".1f",
        ),
        name="com dados",
    )

    fig = go.Figure(data=[trace_cinza, trace_colored])
    fig.update_geos(
        visible=False,
        fitbounds="locations",
        projection_type="mercator",
    )
    fig.update_layout(
        height=500,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor=BAUHAUS_CREAM,
        plot_bgcolor=BAUHAUS_CREAM,
        font=dict(family="Inter, sans-serif", size=12, color=BAUHAUS_BLACK),
        hoverlabel=dict(
            bgcolor=BAUHAUS_CREAM,
            bordercolor=BAUHAUS_BLACK,
            font=dict(family="Inter, sans-serif", size=12,
                      color=BAUHAUS_BLACK),
        ),
    )
    return fig


# =============================================================================
# Wrapper cacheado: filter por fonte + aplicar_rateio
#
# Performance crítica: aplicar_rateio em 3.6M linhas (Solar+Eólica) custava
# 17s por chamada. Filter por fonte ANTES do rateio reduz pra 1.1M (Solar)
# ou 2.5M (Eólica), e o cache evita re-execução em reruns sem mudança de
# (data_ini, data_fim, fonte_label).
#
# Decisões:
# - Args com prefix _ são ignorados pelo Streamlit no hashing (convenção
#   oficial docs) — chave de cache fica em (data_ini, data_fim, fonte_label),
#   3 escalares, hash trivial (~10ms vs ~1s pra hashear df 3.6M linhas).
# - TTL=6h alinha com carregar_curtailment upstream (data_loader_curtailment.
#   py:524) — wrapper não fica mais stale que loader.
# - Filter ANTES do rateio é matematicamente equivalente (validado em
#   scripts/validar_filter_antes_rateio.py): merge usa FONTE como chave,
#   cross-fonte = 0 por construção; rateio é multiplicação element-wise;
#   usinas em rateio múltiplo (18 casos, incl. 7 híbridos) preservam
#   exato número de linhas + volumes.
# =============================================================================


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def _aplicar_rateio_cached(
    data_ini: date,
    data_fim: date,
    fonte_label: str,
    _df_curt_raw: pd.DataFrame,
    _df_grupos: pd.DataFrame,
    _aliases: dict,
) -> pd.DataFrame:
    """Filter por FONTE + aplicar_rateio, cacheado por (janela, fonte)."""
    fonte_code = "SOLAR" if fonte_label == "Solar" else "EOLICA"
    df_curt_filtrado = _df_curt_raw[_df_curt_raw["FONTE"] == fonte_code]
    return aplicar_rateio(df_curt_filtrado, _df_grupos, _aliases)


# =============================================================================
# Wrapper top-level: janela ampla 15M com Categorical
#
# Caminho 1 (decisão de sessão 2026-05-04): cachear o df_curt_raw consolidado
# de uma janela ampla (~15M = 5 trimestres = 1 corrente parcial + 4 fechados,
# cobre comparação YoY pra qualquer trimestre). Visão Geral filtra slice em
# memória pros presets curtos; Por usina/Por grupo usam direto (15M cobre
# os 12M que pediam antes — calcular_3_periodos só usa os 3 últimos meses
# anyway).
#
# Categorical OBRIGATÓRIO em USINA/RAZAO/FONTE/SUBMERCADO/UF:
# - Sem Categorical: footprint estimado ~750MB → OOM no Cloud free tier 1GB
#   (mesmo motivo que removeu sub-aba Por estado em 2abd77b).
# - Com Categorical: footprint estimado ~180-220MB. Margem confortável.
# - USINA tem ~700 únicos, RAZAO 4, FONTE 2, SUBMERCADO 4, UF ~13 — todos
#   altíssimo grau de repetição em ~3.6M+ linhas, ganho típico 5-10×.
#
# Decisões de chave de cache:
# - 3 args escalares (date, date, tuple) — hash trivial.
# - TTL 6h alinha com carregar_curtailment upstream (não fica mais stale).
# - Sem hash_funcs custom (args primitivos imutáveis).
#
# Cold start estimado (Cloud free tier): 40-45s na 1ª chamada da sessão.
# Trocas subsequentes (preset, sub-aba): <1s (cache hit).
# Ganho colateral: _aplicar_rateio_cached agora é chamado com (janela_ampla,
# fonte) → cache hit em qualquer troca, não só Por usina ↔ Por grupo.
# =============================================================================


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def _carregar_curtailment_janela_ampla(
    data_ini_ampla: date,
    data_fim_ampla: date,
    fontes: tuple = ("eolica", "solar"),
) -> pd.DataFrame:
    """Carrega janela ampla 15M e converte strings pra Categorical."""
    df = carregar_curtailment(data_ini_ampla, data_fim_ampla, fontes)
    if len(df) == 0:
        return df
    for col in ("USINA", "RAZAO", "FONTE", "SUBMERCADO", "UF"):
        if col in df.columns:
            df[col] = df[col].astype("category")
    return df


# =============================================================================
# Função principal da aba
# =============================================================================


def render_aba_curtailment() -> None:
    """Wrapper defensivo. Captura crash e exibe stack trace na tela em vez
    de propagar pra Streamlit (que mostraria 'Oh no' no lugar)."""
    try:
        _render_aba_curtailment_impl()
    except Exception:
        import traceback
        st.error("⚠️ Erro ao carregar aba Curtailment (debug ativo)")
        st.code(traceback.format_exc(), language="python")
        st.caption(
            "Este erro foi capturado para investigação. "
            "Por favor, copie o stack trace acima e reporte."
        )
        # NOTA: sem re-raise para preservar st.error/st.code na tela.
        # O Streamlit capturaria a exception e mostraria "Oh no" no lugar.


def _render_aba_curtailment_impl() -> None:
    """Renderiza a aba completa de Curtailment."""

    # ---- Título h1 (padrão das outras abas: app.py:2192, 2785, 3741) ----
    st.markdown("# CURTAILMENT")

    # ---- Caption explicativa (Inter italic cinza, padrão Bauhaus) ----
    st.markdown(
        '<div style="font-family:\'Inter\', sans-serif; '
        'font-size:0.85rem; color:#6B6B6B; font-style:italic; '
        'margin:0 0 0.8rem 0;">'
        'Restrições de geração (constrained-off) em usinas eólicas e solares '
        'do SIN. Dados ONS desde 2022.'
        '</div>',
        unsafe_allow_html=True,
    )

    # =========================================================================
    # Mapeamento de proprietários (Excel + aliases) — rápido, ~1s
    # =========================================================================
    with st.spinner("Carregando mapeamento de proprietários…"):
        df_grupos = carregar_grupos_excel()
        aliases = carregar_aliases()

    if len(df_grupos) == 0:
        st.warning(
            f"Excel `{EXCEL_DEFAULT_PATH}` não carregado. Curtailment será "
            f"mostrado sem proprietários (todos como 'Other')."
        )

    # =========================================================================
    # Descobrir último dia disponível ANTES dos controles (ancora max_d).
    # Necessário pra que a presets ancorem corretamente sem baixar dataset
    # inteiro upfront. Usa cache do helper se disponível, senão fallback today.
    # =========================================================================
    with st.spinner("Verificando última data disponível no ONS…"):
        try:
            ultimo_dia = descobrir_ultimo_dia_disponivel("eolica")
        except Exception:
            ultimo_dia = None
        if ultimo_dia is None:
            ultimo_dia = date.today()

    # Range válido: dataset cobre desde 2022 (briefing). max_d = último dia
    # ONS publicado. Padrão Reservatórios/ENA/Carga: ancorar em data real do
    # dataset, não today.
    min_d_curt = date(2022, 1, 1)
    max_d_curt = ultimo_dia

    # ---- Registrar CSS dos KPIs (1× por render) ----
    st.markdown(_CSS_KPI_CURT, unsafe_allow_html=True)

    # =========================================================================
    # SUB-ABA selector — 3 st.button customizados em vez de st.segmented_control.
    # Razão: segmented_control não expõe atributo estável distinguindo ativo
    # de inativo (testado: aria-pressed/checked/selected todos vazios; classes
    # Emotion são instáveis — armadilha 4.3 do CLAUDE.md). 3 st.button +
    # type="primary"/"secondary" usam atributo HTML semântico (kind=) e
    # geram class .st-key-<key> no element-container (pattern já validado
    # no projeto, ver app.py:455-463 e decisão Sessão 4a).
    #
    # CSS: inverte hierarquia visual — ativo fica BRANCO com borda preta
    # (destaca sobre cream do app); inativos ficam pretos com texto cream.
    # Escopado via [class*="st-key-btn_curt_subaba_"] — não vaza pra outros
    # botões type="primary" da página (presets de período mantêm amarelo).
    # =========================================================================
    st.markdown("""
    <style>
    [class*="st-key-btn_curt_subaba_"] button[kind="primary"] {
        background-color: #FFFFFF !important;
        color: #1A1A1A !important;
        border: 2px solid #1A1A1A !important;
        border-radius: 0 !important;
        box-shadow: none !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 700 !important;
    }
    [class*="st-key-btn_curt_subaba_"] button[kind="secondary"] {
        background-color: #1A1A1A !important;
        color: #F5F1E8 !important;
        border: 2px solid #1A1A1A !important;
        border-radius: 0 !important;
        box-shadow: none !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 600 !important;
    }
    [class*="st-key-btn_curt_subaba_"] button:hover {
        opacity: 0.9;
    }
    </style>
    """, unsafe_allow_html=True)

    if "curt_sub_aba" not in st.session_state:
        st.session_state["curt_sub_aba"] = "Visão geral"

    opcoes_subaba = ["Visão geral", "Por usina", "Por grupo"]
    cols_subaba = st.columns(3)
    for i, nome in enumerate(opcoes_subaba):
        with cols_subaba[i]:
            ativo = st.session_state["curt_sub_aba"] == nome
            if st.button(
                nome,
                type="primary" if ativo else "secondary",
                key=f"btn_curt_subaba_{i}",
                use_container_width=True,
            ):
                st.session_state["curt_sub_aba"] = nome
                st.rerun()

    sub_aba = st.session_state["curt_sub_aba"]

    # =========================================================================
    # CONTROLES GLOBAIS — fonte sempre visível; granularidade + período só
    # na "Visão geral" (sub-abas "Por usina" e "Por grupo" usam períodos
    # fixos mensais via calcular_3_periodos — controles não fazem nada nelas).
    # =========================================================================
    if sub_aba == "Visão geral":
        ctrl_cols = st.columns(2)
        with ctrl_cols[0]:
            fonte_label = st.selectbox(
                "Fonte",
                ["Solar", "Eólica"],
                index=0,
                key="curt_fonte",
            )
        with ctrl_cols[1]:
            granularidade_ui = st.selectbox(
                "Granularidade",
                list(GRANS_UI.keys()),
                index=1,  # default: Mensal
                key="curt_granularidade",
            )
        granularidade = GRANS_UI[granularidade_ui]

        # Spacer: CSS global de app.py:353 aplica margin-top:-1.5rem em
        # .stDateInput. Sem este spacer, labels dos date_inputs sobrepõem
        # a Linha 1. NÃO REMOVER sem testar visualmente.
        st.markdown(
            '<div style="height:1.5rem"></div>', unsafe_allow_html=True,
        )

        # --- Reset de janela ao trocar granularidade ---
        prev_gran = st.session_state.get("curt_granularidade_anterior")
        trocou_gran = prev_gran is not None and prev_gran != granularidade

        def _aplicar_default_periodo_curt(gran_key, mn, mx):
            cfg = PRESETS_BY_GRAN[gran_key]
            default_label = cfg["default"]
            for label, data_ini_fn, is_max in cfg["presets"]:
                if label == default_label:
                    if is_max:
                        st.session_state["curt_data_ini"] = mn
                    else:
                        st.session_state["curt_data_ini"] = max(
                            mn, data_ini_fn(mx)
                        )
                    st.session_state["curt_data_fim"] = mx
                    return

        if "curt_data_ini" not in st.session_state or trocou_gran:
            _aplicar_default_periodo_curt(granularidade, min_d_curt, max_d_curt)
        if "curt_data_fim" not in st.session_state:
            st.session_state["curt_data_fim"] = max_d_curt
        st.session_state["curt_granularidade_anterior"] = granularidade

        _render_period_controls_curt(
            presets=PRESETS_BY_GRAN[granularidade]["presets"],
            session_key_ini="curt_data_ini",
            session_key_fim="curt_data_fim",
            key_prefix="btn_curt_",
            min_d=min_d_curt,
            max_d=max_d_curt,
        )
        data_ini = st.session_state["curt_data_ini"]
        data_fim = st.session_state["curt_data_fim"]
        if data_ini > data_fim:
            st.error("Data inicial maior que data final.")
            st.stop()
    else:
        # "Por usina" / "Por grupo": controles ocultos, fonte sozinha + janela
        # forçada de 12M (cobre os 3 períodos da SPEC §5 com folga).
        fonte_label = st.selectbox(
            "Fonte",
            ["Solar", "Eólica"],
            index=0,
            key="curt_fonte",
        )
        # TODO (Fase F polimento): data_ini/data_fim calculados aqui ficam
        # ÓRFÃOS pós-refator do Caminho 1 — Por usina/Por grupo passaram a
        # usar a janela ampla 15M direto via _carregar_curtailment_janela_ampla
        # (calcular_3_periodos só usa os 3 últimos meses, então a janela
        # extra não muda nada matematicamente). Aceitável agora pra manter
        # diff cirúrgico; limpar em sessão futura.
        data_fim = max_d_curt
        data_ini = max(min_d_curt, max_d_curt - timedelta(days=365))
        granularidade = None
        granularidade_ui = None

    # =========================================================================
    # Carregar curtailment via wrapper de janela ampla (15M = 5 trimestres).
    # Visão Geral filtra slice em memória pros presets curtos; Por usina/
    # Por grupo usam direto. Detalhes da decisão no cabeçalho do
    # _carregar_curtailment_janela_ampla.
    # =========================================================================
    data_ini_ampla = max(
        min_d_curt, _inicio_trimestre_anterior(max_d_curt, 4)
    )

    with st.spinner(
        "Carregando dados de curtailment do ONS "
        "(1ª chamada da sessão: pode levar 40-60s)…"
    ):
        df_curt_raw_amplo = _carregar_curtailment_janela_ampla(
            data_ini_ampla=data_ini_ampla,
            data_fim_ampla=max_d_curt,
            fontes=("eolica", "solar"),
        )

    if df_curt_raw_amplo is None or len(df_curt_raw_amplo) == 0:
        st.error(
            "Não foi possível carregar dados de curtailment para esta janela. "
            "Tente outro período ou verifique a conexão com o ONS."
        )
        return

    # ---- Filter por fonte + Aplicar rateio (cacheado por janela_ampla+fonte) ----
    # Chamado SEMPRE com (data_ini_ampla, max_d_curt) — não com a janela curta
    # da Visão Geral. Razão: cache key fica (janela_ampla, fonte_label) = 2
    # entradas por sessão (Solar + Eólica). Cache hit em qualquer troca de
    # preset OU sub-aba, não só Por usina ↔ Por grupo. Equivalência matemática
    # validada em scripts/validar_cache_janela_ampla.py — rateio é
    # multiplicação element-wise, slice posterior por DATA é distributivo.
    df_filtrado_amplo = _aplicar_rateio_cached(
        data_ini_ampla, max_d_curt, fonte_label,
        df_curt_raw_amplo, df_grupos, aliases,
    )

    # Visão Geral: filter por DATA pra janela curta selecionada (ms).
    # Por usina/Por grupo: usam o df_filtrado_amplo direto (15M cobre os
    # 12M antigos; calcular_3_periodos só usa os 3 últimos meses).
    if sub_aba == "Visão geral":
        df_filtrado = df_filtrado_amplo[
            (df_filtrado_amplo["DATA"] >= data_ini)
            & (df_filtrado_amplo["DATA"] <= data_fim)
        ]
    else:
        df_filtrado = df_filtrado_amplo

    if len(df_filtrado) == 0:
        st.warning("Sem dados pra esta combinação de filtros.")
        st.stop()

    # =========================================================================
    # DESPACHO — segmented_control acima escolheu sub_aba; render só da
    # escolhida. Sub-aba "Por estado" foi removida em commit 2abd77b
    # (OOM no Cloud free tier 1GB). Funções _render_mapa_estado,
    # _carregar_geojson_estados, _render_kpis_por_estado, _nome_estado
    # ficam órfãs (dead code) — remover em sessão futura.
    # data/curtailment/brazil_states.geojson permanece no repo.
    # =========================================================================
    if sub_aba == "Visão geral":
        _render_visao_geral(
            df_filtrado, granularidade, granularidade_ui, fonte_label,
            data_ini, data_fim,
        )
    elif sub_aba == "Por usina":
        _render_por_unidade(df_filtrado)
    else:  # "Por grupo"
        _placeholder_em_construcao()
