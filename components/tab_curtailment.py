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

Granularidades: Diária, Semanal, Mensal, Trimestral.
Presets de período: 30D, 90D, 6M, 12M, Máx.

Mapeamento de proprietário:
    Fonte primária: data/Excel_Curtailment_Base.xlsx
    Aliases manuais: data/aliases_curtailment.csv
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
    "Semanal":    "SEMANAL",
    "Mensal":     "MENSAL",
    "Trimestral": "TRIMESTRAL",
}

# =============================================================================
# Presets de período por granularidade.
# - Diária/Semanal: presets em dias contados pra trás (sem encaixe).
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
    "SEMANAL": {
        "default": "6M",
        "presets": [
            ("30D",  lambda mx: mx - timedelta(days=30),  False),
            ("90D",  lambda mx: mx - timedelta(days=90),  False),
            ("6M",   lambda mx: mx - timedelta(days=180), False),
            ("12M",  lambda mx: mx - timedelta(days=365), False),
            ("Máx",  None, True),
        ],
    },
    "MENSAL": {
        "default": "12M",
        "presets": [
            ("1M",   lambda mx: _inicio_mes_anterior(mx, 0),  False),
            ("3M",   lambda mx: _inicio_mes_anterior(mx, 2),  False),
            ("6M",   lambda mx: _inicio_mes_anterior(mx, 5),  False),
            ("12M",  lambda mx: _inicio_mes_anterior(mx, 11), False),
            ("Máx",  None, True),
        ],
    },
    "TRIMESTRAL": {
        "default": "24M",
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
# encaixam em fronteira de mês/trimestre, Diária e Semanal não encaixam.
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
}
.curt-kpi-label {
    font-family: 'Inter', sans-serif;
    font-size: 0.85rem;
    text-transform: uppercase;
    letter-spacing: 0.16em;
    color: #1A1A1A;
    font-weight: 700;
    line-height: 1.2;
}
.curt-kpi-value {
    display: flex;
    align-items: baseline;
    margin-top: 0.15rem;
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
):
    """KPIs + série temporal de % curtailment por tipo de restrição.

    df: DataFrame COM rateio aplicado e JÁ filtrado por janela e fonte
        conforme escolha do usuário nos controles globais.
    """
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
    # Trimestral/Semanal (poucos pontos), mas vai ficar amontoado em
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
# Sub-aba: Por estado (mapa choropleth)
# =============================================================================


@st.cache_data
def _carregar_geojson_estados() -> dict:
    """Carrega GeoJSON simplificado dos 27 estados BR (data/brazil_states.geojson).

    Cache por sessão Streamlit evita re-leitura/parse do arquivo a cada rerun.
    Chave de join: properties.sigla casa direto com df_post.UF (12/12 match).
    """
    import json
    from pathlib import Path
    return json.loads(
        Path("data/brazil_states.geojson").read_text(encoding="utf-8")
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
        label_total = "% Curtailment Brasil"
        cols = st.columns(4)
        valores = kpis_br
    else:
        df_estado = df_filtrado[df_filtrado["UF"] == uf_selecionada]
        valores = _calcular_kpis_escopo(df_estado)
        nome = _nome_estado(uf_selecionada)
        label_total = f"% Curtailment {uf_selecionada} — {nome}"
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
                "Energético (ENE)", _fmt_pct_curt(valores["pct_ene"]),
                variante="azul",
            ),
            unsafe_allow_html=True,
        )
    with cols[2]:
        st.markdown(
            _render_kpi_curt(
                "Confiabilidade (CNF)", _fmt_pct_curt(valores["pct_cnf"]),
                variante="azul",
            ),
            unsafe_allow_html=True,
        )
    with cols[3]:
        st.markdown(
            _render_kpi_curt(
                "Elétrico (REL)", _fmt_pct_curt(valores["pct_rel"]),
                variante="azul",
            ),
            unsafe_allow_html=True,
        )

    if uf_selecionada is not None:
        with cols[4]:
            st.markdown(
                _render_kpi_curt(
                    "% Curtailment Brasil",
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
# Função principal da aba
# =============================================================================


def render_aba_curtailment() -> None:
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
    # CONTROLES GLOBAIS — granularidade + fonte + período
    # (decisão E1: fora das sub-abas; afetam todas as 5)
    # =========================================================================

    # --- Linha 1: dropdowns de granularidade + fonte ---
    ctrl_cols = st.columns(2)
    with ctrl_cols[0]:
        granularidade_ui = st.selectbox(
            "Granularidade",
            list(GRANS_UI.keys()),
            index=2,  # default: Mensal
            key="curt_granularidade",
        )
    with ctrl_cols[1]:
        fonte_label = st.selectbox(
            "Fonte",
            ["Solar", "Eólica"],
            index=0,  # default: Solar (mais relevante regulatoriamente)
            key="curt_fonte",
        )

    granularidade = GRANS_UI[granularidade_ui]

    # Spacer: o CSS global do app.py:353 aplica `margin-top: -1.5rem` em
    # `.stDateInput` (assumindo date_inputs alinhados a botões, sem labels
    # acima na linha anterior). Aqui temos dropdowns na Linha 1, então os
    # labels dos date_inputs subiriam e sobreporiam a Linha 1. Spacer
    # explícito de 1.5rem compensa. NÃO REMOVER sem testar visualmente.
    st.markdown(
        '<div style="height:1.5rem"></div>', unsafe_allow_html=True,
    )

    # --- Reset de janela ao trocar granularidade ---
    # Sentinela usa a chave INTERNA (granularidade = "MENSAL" etc.), não o
    # label UI ("Mensal"), pra ficar imune a renomeação de label futura.
    prev_gran = st.session_state.get("curt_granularidade_anterior")
    trocou_gran = prev_gran is not None and prev_gran != granularidade

    def _aplicar_default_periodo_curt(gran_key, mn, mx):
        """Aplica o preset default da granularidade nos session_state das datas."""
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

    # --- Inicializar/resetar session_state das datas ---
    # Dispara em: 1ª visita (key ausente) OU troca de granularidade (reset).
    if "curt_data_ini" not in st.session_state or trocou_gran:
        _aplicar_default_periodo_curt(granularidade, min_d_curt, max_d_curt)
    if "curt_data_fim" not in st.session_state:
        st.session_state["curt_data_fim"] = max_d_curt

    # Atualiza sentinela pro próximo rerun
    st.session_state["curt_granularidade_anterior"] = granularidade

    # --- Linha 2: presets + 2 date_inputs (helper local) ---
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

    # =========================================================================
    # Carregar curtailment com a JANELA SELECIONADA pelo usuário
    # (cache do loader é por mês — chamadas incrementais ao trocar preset)
    # =========================================================================
    with st.spinner(
        "Carregando dados de curtailment do ONS "
        "(1ª chamada por janela: pode levar alguns minutos)…"
    ):
        df_curt_raw = carregar_curtailment(
            data_inicio=data_ini,
            data_fim=data_fim,
            fontes=("eolica", "solar"),
        )

    if df_curt_raw is None or len(df_curt_raw) == 0:
        st.error(
            "Não foi possível carregar dados de curtailment para esta janela. "
            "Tente outro período ou verifique a conexão com o ONS."
        )
        return

    # ---- Aplicar rateio (Excel proprietários + aliases) ----
    df_curt = aplicar_rateio(df_curt_raw, df_grupos, aliases)

    # ---- Filtrar por fonte conforme dropdown ----
    if fonte_label == "Solar":
        df_filtrado = df_curt[df_curt["FONTE"] == "SOLAR"]
    else:  # Eólica
        df_filtrado = df_curt[df_curt["FONTE"] == "EOLICA"]

    if len(df_filtrado) == 0:
        st.warning("Sem dados pra esta combinação de filtros.")
        st.stop()

    # =========================================================================
    # SUB-ABAS (decisão D2: sem emojis, texto puro)
    # =========================================================================
    tab_visao, tab_estado, tab_usina, tab_grupo = st.tabs([
        "Visão geral",
        "Por estado",
        "Por usina",
        "Por grupo",
    ])

    with tab_visao:
        _render_visao_geral(
            df_filtrado, granularidade, granularidade_ui, fonte_label,
            data_ini, data_fim,
        )
    with tab_estado:
        if df_filtrado.empty:
            st.info("Sem dados de curtailment no período selecionado.")
        else:
            ufs_disponiveis = sorted(
                df_filtrado.loc[df_filtrado["FRUSTRADO_MWH"] > 0, "UF"]
                .dropna().unique()
            )
            opcoes = ["— Brasil —"] + [
                f"{uf} — {_nome_estado(uf)}" for uf in ufs_disponiveis
            ]
            selecao = st.selectbox(
                "Selecione um estado",
                opcoes,
                key="curt_estado_select",
            )
            uf_selecionada = (
                None if selecao == "— Brasil —"
                else selecao.split(" — ")[0]
            )

            _render_kpis_por_estado(df_filtrado, uf_selecionada, fonte_label)

            fig_mapa = _render_mapa_estado(df_filtrado, fonte_label)
            st.plotly_chart(fig_mapa, use_container_width=True)
    with tab_usina:
        _placeholder_em_construcao()
    with tab_grupo:
        _placeholder_em_construcao()
