"""
Dashboard do Setor Elétrico Brasileiro
Aba 1: PLD Médio Diário por Submercado

Design: Bauhaus clássico — paleta de cores primárias fiel aos tapetes
de Josef Albers (azul cobalto, vermelho cádmio, amarelo cromo).
Tipografia: Bebas Neue (condensada, impactante) + Inter (legibilidade).

Fonte: CCEE - Portal Dados Abertos
https://dadosabertos.ccee.org.br/dataset/pld_media_diaria
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import timedelta

from auth import require_login, logout_button
from data_loader import (
    load_pld_media_diaria,
    load_pld_horaria,
    load_pld_media_semanal,
    load_pld_media_mensal,
    load_reservatorios,
    load_ena,
    clear_cache,
)

# Mapa de granularidade → loader. Usado por get_pld_df().
# Fase 1: só "diario" é ativado (session_state hardcoded).
# Fases 2-3 vão trocar a chave via dropdown no título do gráfico.
GRANULARIDADES = {
    "horario": load_pld_horaria,
    "diario":  load_pld_media_diaria,
    "semanal": load_pld_media_semanal,
    "mensal":  load_pld_media_mensal,
}


def get_pld_df(granularidade: str):
    """Retorna o DataFrame PLD da granularidade selecionada."""
    return GRANULARIDADES[granularidade]()

# =============================================================================
# CONFIGURAÇÃO DA PÁGINA
# =============================================================================
st.set_page_config(
    page_title="Dashboard Setor Elétrico",
    page_icon="▲",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =============================================================================
# PALETA BAUHAUS CLÁSSICA
# =============================================================================
# Cores mais próximas do Bauhaus histórico (Itten, Albers, Kandinsky).
BAUHAUS_RED = "#D62828"      # vermelho cádmio — quente, puro
BAUHAUS_YELLOW = "#F6BD16"   # amarelo cromo — saturado, sem laranjado
BAUHAUS_BLUE = "#2A6F97"     # azul petróleo — distinto do preto, suave aos olhos
BAUHAUS_BLACK = "#1A1A1A"    # preto tinteiro, não "puro"
BAUHAUS_CREAM = "#F5F1E8"    # creme (papel) em vez de branco estéril
BAUHAUS_GRAY = "#4A4A4A"     # cinza escuro legível sobre creme (antes #6B6B6B ficou fraco)
BAUHAUS_LIGHT = "#E8E3D4"    # creme mais escuro pra elementos sutis

# Atribuição por submercado
CORES_SUBMERCADO = {
    "SE": BAUHAUS_RED,
    "S": BAUHAUS_BLUE,
    "NE": BAUHAUS_YELLOW,
    "N": BAUHAUS_BLACK,
    "Média BR": BAUHAUS_GRAY,
}

SUBMERCADOS_ORD = ["SE", "S", "NE", "N"]

# =============================================================================
# CSS — TIPOGRAFIA + COMPONENTES
# =============================================================================
st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;600&display=swap');
    @import url('https://fonts.googleapis.com/icon?family=Material+Icons');

    /* Tipografia geral */
    html, body, [class*="css"], .stMarkdown, .stText, p, span, div, label {{
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    }}

    /* Títulos — Bebas Neue: condensada, alto impacto, muito Bauhaus.
       Cor PRETA forçada pra contrastar com o fundo creme da página. */
    h1, h2, h3, h4,
    .main h1, .main h2, .main h3, .main h4,
    [data-testid="stAppViewContainer"] h1,
    [data-testid="stAppViewContainer"] h2,
    [data-testid="stAppViewContainer"] h3,
    [data-testid="stAppViewContainer"] h4 {{
        font-family: 'Bebas Neue', 'Inter', sans-serif !important;
        font-weight: 400 !important;
        letter-spacing: 0.02em !important;
        color: {BAUHAUS_BLACK} !important;
    }}
    /* Inclui o elemento real do título dentro do Streamlit */
    h1 *, h2 *, h3 *, h4 * {{
        color: {BAUHAUS_BLACK} !important;
    }}
    h1 {{
        font-size: 2rem !important;
        line-height: 1 !important;
        border-left: 7px solid {BAUHAUS_RED};
        padding-left: 12px;
        margin-top: 0 !important;
        margin-bottom: 0 !important;
    }}
    h3 {{
        font-size: 1rem !important;
        letter-spacing: 0.05em !important;
        border-bottom: 2px solid {BAUHAUS_BLACK};
        padding-bottom: 3px;
        margin-top: 0.8rem !important;
        margin-bottom: 0.4rem !important;
    }}

    /* Fundo da página */
    .stApp {{
        background: {BAUHAUS_CREAM};
    }}

    /* Botão nativo do Streamlit para sidebar — customizar visual mantendo click.
       Múltiplos seletores porque o Streamlit usa nomes diferentes dependendo
       da versão e do estado (aberto vs fechado). */
    /* Botão NATIVO de FECHAR/ABRIR sidebar — deixar padrão do Streamlit.
       Customizar esses botões leva a inconsistências entre estados aberto/fechado. */
    [data-testid="stSidebar"] {{
        background: #1A1A1A !important;
        border-right: 4px solid {BAUHAUS_YELLOW};
    }}
    [data-testid="stSidebar"] * {{
        color: {BAUHAUS_CREAM} !important;
    }}
    [data-testid="stSidebar"] h3 {{
        color: {BAUHAUS_YELLOW} !important;
        border-bottom: 2px solid {BAUHAUS_YELLOW};
    }}
    [data-testid="stSidebar"] hr {{
        border-top: 1px solid rgba(246, 189, 22, 0.3) !important;
    }}
    /* Botão na sidebar: amarelo com texto preto (contraste garantido) */
    [data-testid="stSidebar"] .stButton > button {{
        background: {BAUHAUS_YELLOW} !important;
        color: {BAUHAUS_BLACK} !important;
        border: 2px solid {BAUHAUS_YELLOW} !important;
    }}
    [data-testid="stSidebar"] .stButton > button * {{
        color: {BAUHAUS_BLACK} !important;
    }}
    [data-testid="stSidebar"] .stButton > button:hover {{
        background: {BAUHAUS_RED} !important;
        color: {BAUHAUS_CREAM} !important;
        border-color: {BAUHAUS_RED} !important;
    }}
    [data-testid="stSidebar"] .stButton > button:hover * {{
        color: {BAUHAUS_CREAM} !important;
    }}
    /* Radio da sidebar (navegação) — texto claro sobre fundo azul */
    [data-testid="stSidebar"] [data-testid="stRadio"] label,
    [data-testid="stSidebar"] [data-testid="stRadio"] label p,
    [data-testid="stSidebar"] [data-testid="stRadio"] label span {{
        color: {BAUHAUS_CREAM} !important;
    }}
    /* Se algum elemento tiver fundo claro na sidebar, força texto escuro */
    [data-testid="stSidebar"] input,
    [data-testid="stSidebar"] select,
    [data-testid="stSidebar"] textarea {{
        background: {BAUHAUS_CREAM} !important;
        color: {BAUHAUS_BLACK} !important;
    }}
    /* Links na sidebar */
    [data-testid="stSidebar"] a {{
        color: {BAUHAUS_YELLOW} !important;
        text-decoration: underline;
    }}
    /* Caption específica na sidebar — mais legível */
    [data-testid="stSidebar"] .stCaption,
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {{
        color: rgba(245, 241, 232, 0.75) !important;
    }}

    /* KPIs — cards compactos */
    [data-testid="stMetric"] {{
        background: {BAUHAUS_CREAM};
        border: 2px solid {BAUHAUS_BLACK};
        padding: 8px 12px;
        border-radius: 0;
    }}
    [data-testid="stMetric"] [data-testid="stMetricValue"],
    [data-testid="stMetric"] [data-testid="stMetricValue"] *,
    [data-testid="stMetric"] [data-testid="stMetricValue"] div {{
        font-family: 'Bebas Neue', sans-serif !important;
        font-size: 1.45rem !important;
        color: {BAUHAUS_BLACK} !important;
        letter-spacing: 0.02em !important;
    }}
    /* Labels dos KPIs (SE, S, NE, N, MÉDIA BR) — PRETO forçado */
    [data-testid="stMetric"] [data-testid="stMetricLabel"],
    [data-testid="stMetric"] [data-testid="stMetricLabel"] *,
    [data-testid="stMetric"] [data-testid="stMetricLabel"] p,
    [data-testid="stMetric"] [data-testid="stMetricLabel"] div,
    [data-testid="stMetric"] label,
    [data-testid="stMetric"] label * {{
        text-transform: uppercase !important;
        font-size: 0.85rem !important;
        letter-spacing: 0.16em !important;
        font-weight: 700 !important;
        color: {BAUHAUS_BLACK} !important;
    }}

    /* Botões principais (fora da sidebar) — altura igual aos date inputs */
    .stButton > button {{
        border-radius: 0 !important;
        border: 2px solid {BAUHAUS_BLACK} !important;
        background: {BAUHAUS_CREAM} !important;
        color: {BAUHAUS_BLACK} !important;
        font-family: 'Bebas Neue', sans-serif !important;
        letter-spacing: 0.08em;
        font-size: 1rem !important;
        padding: 0 10px !important;
        min-height: 2.4rem !important;
        height: 2.4rem !important;
        transition: all 0.15s ease !important;
    }}
    .stButton > button:hover {{
        background: {BAUHAUS_YELLOW} !important;
        color: {BAUHAUS_BLACK} !important;
    }}

    /* Inputs de data — mesma altura 2.4rem dos botões */
    .stDateInput > div > div {{
        border-radius: 0 !important;
        border: 2px solid {BAUHAUS_BLACK} !important;
        background: {BAUHAUS_CREAM};
        height: 2.4rem !important;
        min-height: 2.4rem !important;
    }}
    .stDateInput input {{
        font-family: 'Inter', sans-serif !important;
        color: {BAUHAUS_BLACK} !important;
        padding: 0 0.6rem !important;
        font-size: 0.9rem !important;
        height: 2.4rem !important;
        line-height: 2.4rem !important;
    }}
    /* Alinhamento caixas de data pela base com botões de atalho.
       A caixa de data tem label "Data inicial"/"Data final" em cima (~1.5rem).
       Subimos o widget inteiro essa altura pra base coincidir com a dos botões. */
    .stDateInput,
    [data-testid="stDateInput"] {{
        margin-top: -1.5rem !important;
    }}
    /* Labels "Data inicial" e "Data final" — compactos pra não esticar a caixa */
    .stDateInput label,
    .stDateInput label *,
    .stDateInput label p,
    [data-testid="stWidgetLabel"],
    [data-testid="stWidgetLabel"] *,
    [data-testid="stWidgetLabel"] p {{
        color: {BAUHAUS_BLACK} !important;
        font-weight: 600 !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 0.75rem !important;
        margin-bottom: 2px !important;
        line-height: 1.2 !important;
    }}

    /* Bloco principal — compacto, sobe o título PLD pro topo */
    .block-container {{
        padding-top: 0 !important;
        padding-bottom: 2rem;
        max-width: 1000px;
    }}
    /* Header Streamlit — deixar padrão */
    /* Remove padding/margin do primeiro elemento da página pra subir tudo */
    .block-container > div:first-child {{
        padding-top: 0 !important;
        margin-top: 0 !important;
    }}
    /* Também força o main container a subir */
    [data-testid="stAppViewContainer"] .main .block-container {{
        padding-top: 0 !important;
    }}

    /* Caption — usar cinza escuro forte, legível sobre creme.
       Aplicamos só na área principal (sidebar sobrescreve depois). */
    [data-testid="stAppViewContainer"] .main .stCaption,
    [data-testid="stAppViewContainer"] .main [data-testid="stCaptionContainer"],
    [data-testid="stAppViewContainer"] .main [data-testid="stCaptionContainer"] *,
    .main .stCaption,
    .main [data-testid="stCaptionContainer"],
    .main [data-testid="stCaptionContainer"] * {{
        font-family: 'Inter', sans-serif !important;
        text-transform: uppercase !important;
        letter-spacing: 0.1em !important;
        font-size: 0.75rem !important;
        color: #2E2E2E !important;  /* cinza bem escuro */
        font-weight: 500 !important;
    }}

    /* ===== CHECKBOX — dessaturar o rosa via filter grayscale ===== */
    /* Labels com fundo transparente */
    [data-testid="stAppViewContainer"] .stCheckbox label,
    [data-testid="stAppViewContainer"] .stCheckbox label p,
    [data-testid="stAppViewContainer"] .stCheckbox label div {{
        background: transparent !important;
        background-color: transparent !important;
    }}
    [data-testid="stAppViewContainer"] .stCheckbox label p {{
        font-family: 'Inter', sans-serif !important;
        font-size: 0.92rem !important;
        font-weight: 600 !important;
        color: {BAUHAUS_BLACK} !important;
    }}
    /* Quadradinho desmarcado: borda preta */
    [data-testid="stAppViewContainer"] .stCheckbox label > span:first-child {{
        border: 2px solid {BAUHAUS_BLACK} !important;
        border-radius: 0 !important;
    }}
    /* TRUQUE: aplicamos filter grayscale APENAS no quadradinho (primeiro span do label)
       Isso dessatura qualquer cor rosa/vermelha pra cinza, sem precisar detectar estado */
    [data-testid="stAppViewContainer"] .stCheckbox label > span:first-child {{
        filter: grayscale(1) brightness(0.6) contrast(5) !important;
    }}

    /* Alinhamento vertical: centraliza texto do label com o quadradinho */
    [data-testid="stAppViewContainer"] .stCheckbox label {{
        display: flex !important;
        align-items: center !important;
    }}
    [data-testid="stAppViewContainer"] .stCheckbox label p {{
        margin: 0 !important;
        line-height: 1 !important;
        position: relative;
        top: 3px;
    }}

    /* Botões "primary" do Streamlit (atalhos de período ativos em PLD e
       Reservatórios): amarelo Bauhaus com borda preta. Hover = vermelho. */
    .stButton > button[kind="primary"] {{
        background: {BAUHAUS_YELLOW} !important;
        color: {BAUHAUS_BLACK} !important;
        border: 2px solid {BAUHAUS_BLACK} !important;
        font-weight: 700 !important;
    }}
    .stButton > button[kind="primary"]:hover {{
        background: {BAUHAUS_RED} !important;
        color: {BAUHAUS_CREAM} !important;
        border-color: {BAUHAUS_BLACK} !important;
    }}

    /* Divisor */
    hr {{
        border: none !important;
        border-top: 3px solid {BAUHAUS_BLACK} !important;
        margin: 2.5rem 0 1.5rem 0 !important;
    }}

    /* Rodapé — usar classe própria com espaçamento claro */
    .rodape {{
        font-family: 'Inter', sans-serif;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        font-size: 0.7rem;
        color: {BAUHAUS_GRAY};
        text-align: center;
        padding: 1rem 0;
        line-height: 1.8;  /* evita sobreposição */
    }}
    .rodape span {{
        display: inline-block;
        margin: 0 0.6rem;
    }}

    /* Faixa decorativa no topo */
    .bauhaus-stripe {{
        display: flex;
        height: 8px;
        margin-bottom: 1.8rem;
    }}
    .bauhaus-stripe > div {{
        flex: 1;
    }}

    /* Botão de download CSV — estilo Bauhaus */
    .stDownloadButton > button {{
        background: {BAUHAUS_YELLOW} !important;
        color: {BAUHAUS_BLACK} !important;
        border: 2px solid {BAUHAUS_BLACK} !important;
        border-radius: 0 !important;
        font-family: 'Bebas Neue', sans-serif !important;
        letter-spacing: 0.08em !important;
        font-size: 1rem !important;
        padding: 10px 18px !important;
    }}
    .stDownloadButton > button:hover {{
        background: {BAUHAUS_RED} !important;
        color: {BAUHAUS_CREAM} !important;
    }}
    .stDownloadButton > button *,
    .stDownloadButton > button p {{
        color: inherit !important;
    }}
    </style>

    <div class="bauhaus-stripe">
        <div style="background: {BAUHAUS_RED};"></div>
        <div style="background: {BAUHAUS_YELLOW};"></div>
        <div style="background: {BAUHAUS_BLUE};"></div>
        <div style="background: {BAUHAUS_BLACK};"></div>
    </div>
    """,
    unsafe_allow_html=True,
)

# =============================================================================
# AUTENTICAÇÃO
# =============================================================================
user = require_login()
if user is None:
    st.stop()

import streamlit.components.v1 as components

# Substituir o texto dos ícones Material ("keyboard_double_arrow_right" etc.)
# por símbolos simples (>> e <<) quando o ícone não carrega.
# O botão nativo do Streamlit continua funcionando normalmente.
components.html(
    """
    <script>
    (function() {
        const doc = window.parent.document;
        const SUBSTITUICOES = {
            'keyboard_double_arrow_right': '>>',
            'keyboard_double_arrow_left': '<<',
            'chevron_right': '>',
            'chevron_left': '<',
            'arrow_forward': '>',
            'arrow_back': '<',
            'menu_open': '<<',
            'menu': '>>',
            'first_page': '<<',
            'last_page': '>>'
        };

        function substituirTextos() {
            const botoes = doc.querySelectorAll(
                '[data-testid="stSidebarCollapseButton"], ' +
                '[data-testid="stSidebarCollapsedControl"], ' +
                '[data-testid="collapsedControl"], ' +
                'button[kind="header"], ' +
                'button[kind="headerNoPadding"]'
            );
            botoes.forEach(btn => {
                const walker = doc.createTreeWalker(btn, NodeFilter.SHOW_TEXT);
                let node;
                while ((node = walker.nextNode())) {
                    const txt = node.nodeValue.trim();
                    if (SUBSTITUICOES[txt]) {
                        node.nodeValue = SUBSTITUICOES[txt];
                    }
                }
            });
        }

        // Marca botões da sidebar com atributos data-* pra CSS poder estilizar
        // especificamente o "Sair" e o "Atualizar" sem conflito.
        function marcarBotoesSidebar() {
            const sidebar = doc.querySelector('[data-testid="stSidebar"]');
            if (!sidebar) return;
            const botoes = sidebar.querySelectorAll('.stButton button');
            botoes.forEach(btn => {
                const texto = btn.textContent.trim();
                if (texto === 'Sair' || texto === 'Logout') {
                    btn.setAttribute('data-sair', 'true');
                } else if (texto === 'Atualizar') {
                    btn.setAttribute('data-atualizar', 'true');
                }
            });
        }

        substituirTextos();
        marcarBotoesSidebar();
        setInterval(() => {
            substituirTextos();
            marcarBotoesSidebar();
        }, 500);
    })();
    </script>
    """,
    height=0,
    width=0,
)

# =============================================================================
# HELPER: controles de período (atalhos + date_inputs)
# Reusado pelas abas PLD e Reservatórios. Diferem apenas nos presets
# (1M/3M/6M/12M/Máx vs 1A/3A/5A/10A/Máx) e nas session_state keys.
# =============================================================================
def _render_period_controls(
    *,
    presets,          # list[tuple[str, int|None, bool]]: (label, delta_days, is_max)
    session_key_ini,  # str: chave em session_state pra data_ini
    session_key_fim,  # str: chave em session_state pra data_fim
    key_prefix,       # str: prefixo dos keys dos botões (ex: "btn_" ou "btn_res_")
    min_d,
    max_d,
):
    """Renderiza atalhos + 2 date_inputs numa linha, com botão "primary"
    amarelo pro preset ativo. Reset de mudança de dataset é responsabilidade
    do caller (feito antes de chamar esta função)."""
    data_ini_atual = st.session_state[session_key_ini]
    data_fim_atual = st.session_state[session_key_fim]

    # Detecta preset ativo comparando com cada entrada da lista
    preset_atual = None
    if data_fim_atual == max_d:
        for label, delta, is_max in presets:
            if is_max and data_ini_atual == min_d:
                preset_atual = label
                break
            if delta is not None and (max_d - data_ini_atual).days == delta:
                preset_atual = label
                break

    n = len(presets)
    cols = st.columns([1] * n + [0.3, 1.4, 1.4])

    for i, (label, delta, is_max) in enumerate(presets):
        with cols[i]:
            tipo = "primary" if label == preset_atual else "secondary"
            if st.button(
                label, use_container_width=True,
                key=f"{key_prefix}{label}", type=tipo,
            ):
                if is_max:
                    st.session_state[session_key_ini] = min_d
                else:
                    st.session_state[session_key_ini] = (
                        max_d - timedelta(days=delta)
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


def _wet_season_window(last_date):
    """
    Janela do período úmido relevante pros KPIs da aba ENA.
    - Se last_date está em 01-nov a 30-abr: úmido ATUAL (01-nov mais
      recente até last_date).
    - Caso contrário (mai-out): último úmido COMPLETO (01-nov do ano
      anterior a 30-abr do ano atual).
    Retorna (date_start, date_end).
    """
    y, m = last_date.year, last_date.month
    if m >= 11:
        return pd.Timestamp(year=y, month=11, day=1).date(), last_date
    if m <= 4:
        return pd.Timestamp(year=y - 1, month=11, day=1).date(), last_date
    return (
        pd.Timestamp(year=y - 1, month=11, day=1).date(),
        pd.Timestamp(year=y, month=4, day=30).date(),
    )


def _compute_kpi_mlt_pct(df_ena, subsistema_code, date_start, date_end):
    """
    KPI ponderado: ENA acumulada / MLT acumulada no período × 100.

    Pra 'SIN' agrega N+NE+S+SE (ignora a linha SIN pré-calculada pra
    deixar a agregação explícita — matematicamente equivalente).

    MLT absoluta é derivada de ena_mwmed / (ena_mlt_pct/100) por linha.
    Linhas com pct<=0, NaN em pct ou NaN em mwmed são descartadas
    (MLT indefinida).

    Retorna float (% MLT) ou NaN se dados insuficientes no período.
    """
    mask = (
        (df_ena["data"].dt.date >= date_start)
        & (df_ena["data"].dt.date <= date_end)
    )
    if subsistema_code == "SIN":
        sub_filter = df_ena["subsistema_code"].isin(["N", "NE", "S", "SE"])
    else:
        sub_filter = df_ena["subsistema_code"] == subsistema_code

    w = df_ena[mask & sub_filter]
    valid = (
        (w["ena_mlt_pct"] > 0)
        & w["ena_mwmed"].notna()
        & w["ena_mlt_pct"].notna()
    )
    w = w[valid]
    if w.empty:
        return float("nan")
    num = w["ena_mwmed"].sum()
    den = (w["ena_mwmed"] / (w["ena_mlt_pct"] / 100.0)).sum()
    if den <= 0:
        return float("nan")
    return num / den * 100.0


def _add_wet_season_bands(fig, *, date_start, date_end):
    """
    Adiciona faixas verticais azul-claras (período úmido hidrológico BR)
    ao gráfico Plotly. Período úmido = 1º nov → 30 abr do ano seguinte.
    Gera uma faixa pra cada período úmido que intersecta [date_start, date_end].
    """
    first_year = date_start.year - 1  # margem de segurança
    last_year = date_end.year
    for year in range(first_year, last_year + 1):
        ws = pd.Timestamp(year=year, month=11, day=1).date()
        we = pd.Timestamp(year=year + 1, month=4, day=30).date()
        # Só adiciona se intersecta o intervalo visível
        if we >= date_start and ws <= date_end:
            fig.add_vrect(
                x0=max(ws, date_start),
                x1=min(we, date_end),
                fillcolor="#B3D4F1",
                opacity=0.3,
                layer="below",
                line_width=0,
            )


# =============================================================================
# SIDEBAR
# =============================================================================
with st.sidebar:
    st.markdown("### Dashboard Setor Elétrico")
    st.caption(f"**{user}**")

    # Botões Sair e Atualizar — mesmo estilo: borda amarela fina, fundo transparente,
    # texto amarelo. JS marca cada um com data-sair/data-atualizar pra CSS atingir.
    st.markdown(
        """
        <style>
        /* Estilo unificado pros dois botões da sidebar — borda fina, texto leve */
        [data-testid="stSidebar"] .stButton > button[data-sair="true"],
        [data-testid="stSidebar"] .stButton > button[data-atualizar="true"] {
            background: transparent !important;
            background-color: transparent !important;
            border: 1px solid rgba(246, 189, 22, 0.6) !important;  /* amarelo 60% opacidade */
            color: #F6BD16 !important;
            font-family: 'Inter', sans-serif !important;
            font-size: 0.8rem !important;
            font-weight: 400 !important;  /* mais fino (era 500) */
            letter-spacing: 0.03em !important;
            padding: 0 !important;
            min-height: 2.2rem !important;
            height: 2.2rem !important;
            box-shadow: none !important;
            width: 100% !important;
            border-radius: 0 !important;
            margin: 0 !important;
        }
        [data-testid="stSidebar"] .stButton > button[data-sair="true"] *,
        [data-testid="stSidebar"] .stButton > button[data-atualizar="true"] * {
            color: #F6BD16 !important;
            font-weight: 400 !important;
        }
        [data-testid="stSidebar"] .stButton > button[data-sair="true"]:hover,
        [data-testid="stSidebar"] .stButton > button[data-atualizar="true"]:hover {
            background: rgba(246, 189, 22, 0.15) !important;  /* sutil */
            background-color: rgba(246, 189, 22, 0.15) !important;
            color: #F6BD16 !important;
            border: 1px solid #F6BD16 !important;
        }
        [data-testid="stSidebar"] .stButton > button[data-sair="true"]:hover *,
        [data-testid="stSidebar"] .stButton > button[data-atualizar="true"]:hover * {
            color: #F6BD16 !important;
        }
        /* Container do botão Sair — largura 100% */
        [data-testid="stSidebar"] .stButton,
        [data-testid="stSidebar"] [data-testid="stButton"],
        [data-testid="stSidebar"] .element-container {
            width: 100% !important;
        }
        /* Garante que o botão Sair (identificado via aria-label contendo Sair) seja largura completa.
           Usamos aria-label que o streamlit-authenticator define no logout. */
        [data-testid="stSidebar"] button[kind="secondary"] {
            width: 100% !important;
            min-height: 2.2rem !important;
            height: 2.2rem !important;
            background: transparent !important;
            border: 1px solid rgba(246, 189, 22, 0.6) !important;
            color: #F6BD16 !important;
            font-family: 'Inter', sans-serif !important;
            font-size: 0.8rem !important;
            font-weight: 400 !important;
            padding: 0 !important;
            border-radius: 0 !important;
            box-shadow: none !important;
        }
        [data-testid="stSidebar"] button[kind="secondary"] * {
            color: #F6BD16 !important;
        }
        [data-testid="stSidebar"] button[kind="secondary"]:hover {
            background: rgba(246, 189, 22, 0.15) !important;
            border: 1px solid #F6BD16 !important;
            color: #F6BD16 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    # Botão Sair
    logout_button(location="sidebar", key="logout_sidebar")

    st.divider()

    aba = st.radio(
        "NAVEGAÇÃO",
        ["PLD", "Reservatórios", "ENA/Chuva"],
        label_visibility="collapsed",
    )

    st.divider()
    if st.button("Atualizar", use_container_width=True):
        clear_cache()
        st.rerun()

    st.caption(
        "Dados atualizados automaticamente 1x ao dia."
    )

# Sem barra superior — Sair fica no final da sidebar (vide bloco SIDEBAR abaixo).
# Assim a página ganha espaço vertical e a topbar nativa do Streamlit (3 pontos)
# não compete com elementos customizados.
if aba == "PLD":
    # Título principal da aba, em destaque Bauhaus (barra vermelha lateral)
    st.markdown("# PLD")
    # Linha separadora preta abaixo do título — margem muito negativa puxa Período pra cima
    st.markdown(
        '<div style="border-bottom: 2px solid #1A1A1A; '
        'margin: 0 0 -1.5rem 0;"></div>',
        unsafe_allow_html=True,
    )

    # --- Carregar dados ---
    # Granularidade é atualizada pelo dropdown no título (selectbox com
    # on_change callback) antes do script rodar, então aqui já temos o
    # valor correto na session_state.
    st.session_state.setdefault("granularidade", "diario")
    granularidade = st.session_state["granularidade"]
    with st.spinner("Carregando dados da CCEE…"):
        try:
            df = get_pld_df(granularidade)
        except Exception as e:
            st.error(f"Falha ao carregar dados da CCEE: {e}")
            debug = st.session_state.get("_debug_erros", [])
            if debug:
                st.subheader("Detalhes técnicos do erro")
                for d in debug[:20]:
                    st.code(d)
            st.stop()

    if df.empty:
        st.warning("Nenhum dado disponível.")
        st.stop()

    if st.session_state.get("_demo_mode"):
        st.warning(
            "⚠️ **Modo demonstração ativo** — dados sintéticos para teste. "
            "A CCEE não respondeu. Verifique sua conexão."
        )

    # --- Controles de data ---
    min_d = df["data"].min().date()
    max_d = df["data"].max().date()

    if (
        "data_ini" not in st.session_state
        or st.session_state.get("_dataset_max") != max_d
        or st.session_state.get("_dataset_min") != min_d
    ):
        st.session_state["data_ini"] = max(min_d, max_d - timedelta(days=90))
        st.session_state["data_fim"] = max_d
        st.session_state["_dataset_max"] = max_d
        st.session_state["_dataset_min"] = min_d

    # --- Filtrar por data (usando session_state, não widgets) ---
    # Os widgets de Período ficam mais abaixo, mas o filtro precisa acontecer
    # aqui para os KPIs já mostrarem os dados corretos.
    data_ini = st.session_state["data_ini"]
    data_fim = st.session_state["data_fim"]

    if data_ini > data_fim:
        st.error("A data inicial não pode ser posterior à data final.")
        st.stop()

    mask = (df["data"].dt.date >= data_ini) & (df["data"].dt.date <= data_fim)
    dff = df.loc[mask].copy()

    if dff.empty:
        st.warning("Sem dados no intervalo selecionado.")
        st.stop()

    # --- Período (atalhos + date_inputs) — via helper reusado ---
    _render_period_controls(
        presets=[
            ("1M", 30, False),
            ("3M", 90, False),
            ("6M", 180, False),
            ("12M", 365, False),
            ("Máx", None, True),
        ],
        session_key_ini="data_ini",
        session_key_fim="data_fim",
        key_prefix="btn_",
        min_d=min_d,
        max_d=max_d,
    )

    # --- Seletor de submercados (antes do gráfico) ---
    sel_cols = st.columns([1, 1, 1, 1, 1.3, 4])
    submercados_selecionados = []
    with sel_cols[0]:
        if st.checkbox("SE", value=True, key="sel_SE"):
            submercados_selecionados.append("SE")
    with sel_cols[1]:
        if st.checkbox("S", value=True, key="sel_S"):
            submercados_selecionados.append("S")
    with sel_cols[2]:
        if st.checkbox("NE", value=True, key="sel_NE"):
            submercados_selecionados.append("NE")
    with sel_cols[3]:
        if st.checkbox("N", value=True, key="sel_N"):
            submercados_selecionados.append("N")
    with sel_cols[4]:
        mostrar_media = st.checkbox("Média BR", value=True, key="sel_media")

    if not submercados_selecionados and not mostrar_media:
        st.info("Selecione ao menos um submercado ou a Média BR para visualizar.")
    else:
        # =====================================================================
        # Título-dropdown (Fase 3 — integrado ao gráfico).
        # st.selectbox estilizado como título Bauhaus. Usa testids estáveis
        # (stSelectbox + data-baseweb="select") pra sobreviver a upgrades do
        # Streamlit. Menu aberto mantém visual default BaseWeb — preço
        # pago por robustez. Não renderizamos "· R$/MWh" aqui porque o
        # eixo Y do gráfico já mostra a unidade.
        #
        # Fluxo: on_change callback atualiza session_state["granularidade"]
        # ANTES do próximo main-script run. Assim o get_pld_df no topo do
        # bloco já lê o novo valor e o render todo usa dados coerentes.
        # =====================================================================
        LABELS_GRAN = {
            "horario": "PLD HORÁRIO",
            "diario":  "PLD MÉDIO DIÁRIO",
            "semanal": "PLD MÉDIO SEMANAL",
            "mensal":  "PLD MÉDIO MENSAL",
        }

        def _on_granularidade_change():
            st.session_state["granularidade"] = st.session_state[
                "selectbox_granularidade"
            ]

        # CSS: flatten do selectbox pra virar título Bauhaus
        st.markdown(
            """
            <style>
            [data-testid="stSelectbox"] label {
                display: none !important;
            }
            [data-testid="stSelectbox"] [data-baseweb="select"] > div {
                border: none !important;
                border-bottom: 2px solid #1A1A1A !important;
                border-radius: 0 !important;
                background: transparent !important;
                font-family: 'Bebas Neue', sans-serif !important;
                font-size: 1.1rem !important;
                letter-spacing: 0.08em !important;
                color: #1A1A1A !important;
                padding-left: 0 !important;
                min-height: 0 !important;
                cursor: pointer !important;
                width: fit-content !important;
                max-width: 100% !important;
            }
            /* Esconde chevron SVG default do BaseWeb (evita seta dupla) */
            [data-testid="stSelectbox"] [data-baseweb="select"] svg {
                display: none !important;
            }
            /* ▾ preta sempre visível, colada no texto */
            [data-testid="stSelectbox"] [data-baseweb="select"] > div::after {
                content: "▾";
                color: #1A1A1A;
                font-size: 1.7em;
                margin-left: 0.3em;
                pointer-events: none;
                line-height: 1;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        opcoes_ordem = ["horario", "diario", "semanal", "mensal"]
        st.selectbox(
            "Granularidade do PLD",
            options=opcoes_ordem,
            index=opcoes_ordem.index(st.session_state["granularidade"]),
            format_func=lambda k: LABELS_GRAN[k],
            label_visibility="collapsed",
            key="selectbox_granularidade",
            on_change=_on_granularidade_change,
        )

        # --- Preparar dados ---
        pivot = dff.pivot_table(
            index="data", columns="submercado", values="pld", aggfunc="mean"
        ).sort_index()

        submercados_presentes = [s for s in SUBMERCADOS_ORD if s in pivot.columns]
        pivot["Média BR"] = pivot[submercados_presentes].mean(axis=1)

        # --- Construir gráfico ---
        fig = go.Figure()

        series_plot = list(submercados_selecionados)
        if mostrar_media:
            series_plot.append("Média BR")

        for col in series_plot:
            if col not in pivot.columns:
                continue
            is_media = col == "Média BR"
            cor_linha = CORES_SUBMERCADO[col]
            sigla_label = col if col != "Média BR" else "BR"
            # Com fonte monoespaçada, basta padronizar todas as siglas em 2 chars.
            # Siglas de 1 char (S, N) ganham um espaço no final.
            sigla_fix = sigla_label.ljust(2)
            fig.add_trace(
                go.Scatter(
                    x=pivot.index,
                    y=pivot[col],
                    name=col,
                    mode="lines",
                    line=dict(
                        color=cor_linha,
                        width=4 if is_media else 2.5,
                        dash="dot" if is_media else "solid",
                    ),
                    # Hover com fonte monoespaçada: &nbsp; tem largura fixa,
                    # garantindo que "R$" comece na mesma coluna em todas as linhas.
                    hovertemplate=(
                        f'<span style="color:{cor_linha}; font-weight:700;">'
                        f'{sigla_fix}</span>'
                        '&nbsp;&nbsp;&nbsp;&nbsp;'
                        '<span style="color:#1A1A1A;">R$ %{y:.0f}/MWh</span>'
                        '<extra></extra>'
                    ),
                )
            )

        # Layout Bauhaus — papel creme, tipografia impactante, geometria
        fig.update_layout(
            height=290,  # reduzido ~10% (era 320) para caber melhor em tela 100%
            margin=dict(l=20, r=20, t=30, b=20),
            paper_bgcolor=BAUHAUS_CREAM,
            plot_bgcolor=BAUHAUS_CREAM,
            hovermode="x unified",  # tooltip único com todas as séries + data no topo
            hoverlabel=dict(
                bgcolor=BAUHAUS_CREAM,
                bordercolor=BAUHAUS_BLACK,
                font=dict(
                    # IBM Plex Mono: monoespaçada (permite alinhamento) mas com
                    # desenho consistente com Inter (usada no resto do dashboard).
                    family="'IBM Plex Mono', 'Courier New', monospace",
                    size=12,
                    color=BAUHAUS_BLACK,
                ),
            ),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="left",
                x=0,
                bgcolor="rgba(0,0,0,0)",
                font=dict(
                    family="Bebas Neue, sans-serif",
                    size=17,
                    color=BAUHAUS_BLACK,
                ),
            ),
            xaxis=dict(
                title=None,
                showgrid=False,
                showline=True,
                linewidth=2,
                linecolor=BAUHAUS_BLACK,
                ticks="outside",
                tickcolor=BAUHAUS_BLACK,
                tickfont=dict(
                    family="Inter, sans-serif",
                    size=13,
                    color=BAUHAUS_BLACK,
                ),
                # Formato do header do tooltip (hovermode="x unified").
                # Semanal: mostra só início da semana. CCEE não publica
                # data_fim; calcular data+6dias assumiria semana fixa,
                # então preferimos o início puro. Se o usuário quiser
                # ver o range, mudar hovermode pra "x" e passar customdata
                # por trace com fim = data + timedelta(days=6).
                hoverformat={
                    "horario": "%d/%m/%Y %H:%M",
                    "diario":  "%d/%m/%Y",
                    "semanal": "%d/%m/%Y",
                    "mensal":  "%b %Y",
                }[granularidade],
            ),
            yaxis=dict(
                title=dict(
                    text="R$/MWh",
                    font=dict(
                        family="Bebas Neue, sans-serif",
                        size=16,
                        color=BAUHAUS_BLACK,
                    ),
                ),
                showgrid=True,
                gridcolor=BAUHAUS_LIGHT,
                gridwidth=1,
                showline=True,
                linewidth=2,
                linecolor=BAUHAUS_BLACK,
                ticks="outside",
                tickcolor=BAUHAUS_BLACK,
                tickfont=dict(
                    family="Inter, sans-serif",
                    size=13,
                    color=BAUHAUS_BLACK,
                ),
                zeroline=False,
                tickformat=".0f",
                hoverformat=".0f",
            ),
            font=dict(family="Inter, sans-serif", size=12),
        )

        # Caption de performance: horário + período ≥ 180 dias pode
        # demorar alguns segundos no primeiro render (até ~230k pontos).
        periodo_dias = (data_fim - data_ini).days
        if granularidade == "horario" and periodo_dias >= 180:
            st.caption(
                "Granularidade horária com período longo — "
                "renderização pode levar alguns segundos."
            )

        st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})

    # --- KPIs + tabela de estatísticas: só em diário (Fase 4 adapta pras outras) ---
    if granularidade != "diario":
        st.caption(
            "KPIs e tabela de estatísticas disponíveis apenas em granularidade "
            "diária. Versões específicas por granularidade vêm em breve."
        )

    # --- Último dia disponível (KPIs compactos em linha única) ---
    ultima_data = dff["data"].max()
    ultimo_pld = dff[dff["data"] == ultima_data].set_index("submercado")["pld"]
    media_br_ultimo = ultimo_pld.mean()

    # Formata valores BR (vírgula decimal)
    def _fmt_br(v):
        if v is None or (hasattr(v, "__float__") and not (v == v)):
            return "—"
        return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    # Monta linha única com todos os valores, compacta, sem cards
    kpi_items = []
    for sub in SUBMERCADOS_ORD:
        val = ultimo_pld.get(sub)
        cor = CORES_SUBMERCADO.get(sub, "#1A1A1A")
        kpi_items.append(
            f'<span class="kpi-item">'
            f'<span class="kpi-label" style="background:{cor};">{sub}</span>'
            f'<span class="kpi-value">R$ {_fmt_br(val)}</span>'
            f'</span>'
        )
    # Adiciona Média BR no final
    kpi_items.append(
        f'<span class="kpi-item">'
        f'<span class="kpi-label" style="background:#6B6B6B;">BR</span>'
        f'<span class="kpi-value">R$ {_fmt_br(media_br_ultimo)}</span>'
        f'</span>'
    )

    _kpi_row_html = f"""
        <style>
        .kpi-ultimo-row {{
            display: flex;
            flex-wrap: nowrap;
            align-items: center;
            justify-content: space-between;  /* distribui items uniformemente */
            margin: 0.8rem 0 0.3rem 0;
            padding: 0.4rem 0.9rem;
            border: 2px solid #1A1A1A;
            background: #F5F1E8;
            gap: 0.4rem;
        }}
        .kpi-ultimo-header {{
            font-family: 'Inter', sans-serif;
            font-size: 0.62rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #4A4A4A;
            margin-right: 0.25rem;
            white-space: nowrap;
        }}
        .kpi-ultimo-data {{
            font-family: 'Inter', sans-serif;
            font-size: 0.72rem;
            color: #1A1A1A;
            font-weight: 600;
            white-space: nowrap;
        }}
        .kpi-item {{
            display: inline-flex;
            align-items: center;
            gap: 0.25rem;
            white-space: nowrap;  /* não quebra sigla|valor */
        }}
        .kpi-label {{
            display: inline-block;
            padding: 0.1rem 0.35rem;
            font-family: 'Inter', sans-serif;
            font-size: 0.6rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            color: #FFFFFF;
            line-height: 1.2;
        }}
        .kpi-value {{
            font-family: 'Bebas Neue', sans-serif;
            font-size: 1rem;
            color: #1A1A1A;
            letter-spacing: 0.02em;
            white-space: nowrap;
        }}
        </style>
        <div class="kpi-ultimo-row">
            <span class="kpi-ultimo-header">Último dia</span>
            <span class="kpi-ultimo-data">{ultima_data.strftime("%d/%m/%Y")}</span>
            {''.join(kpi_items)}
        </div>
        """
    if granularidade == "diario":
        st.markdown(_kpi_row_html, unsafe_allow_html=True)

    # --- Estatísticas do período (tabela) ---
    _stats_header_html = (
        f'<h3 style="margin-bottom:0.3rem;">Estatísticas do período</h3>'
        f'<div style="font-family:\'Inter\', sans-serif; font-weight:500; '
        f'font-size:0.95rem; color:#2E2E2E; margin-bottom:0.8rem;">'
        f'{data_ini.strftime("%d/%m/%Y")} — {data_fim.strftime("%d/%m/%Y")}'
        f'</div>'
    )
    if granularidade == "diario":
        st.markdown(_stats_header_html, unsafe_allow_html=True)
    stats = (
        dff.groupby("submercado")["pld"]
        .agg(["min", "mean", "max"])
        .reindex(SUBMERCADOS_ORD)
        .round(2)
    )

    def fmt_brl(v):
        if pd.isna(v):
            return "—"
        return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    # CSS da tabela — injetado separadamente (f-string só com interpolações simples)
    css_tabela = f"""
    <style>
        .bauhaus-table {{
            width: 100%;
            border-collapse: collapse;
            font-family: 'Inter', sans-serif;
            margin: 0.5rem 0 1.5rem 0;
            border: 2px solid {BAUHAUS_BLACK};
        }}
        .bauhaus-table thead tr {{
            background: {BAUHAUS_BLACK};
            color: {BAUHAUS_CREAM};
        }}
        .bauhaus-table th {{
            font-family: 'Bebas Neue', sans-serif;
            font-weight: 400;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            font-size: 0.95rem;
            padding: 12px 10px;
            text-align: center;
            border-right: 1px solid {BAUHAUS_GRAY};
            color: {BAUHAUS_CREAM};
        }}
        .bauhaus-table th:last-child {{
            border-right: none;
        }}
        .bauhaus-table td {{
            padding: 10px;
            text-align: center;
            font-size: 0.95rem;
            color: {BAUHAUS_BLACK};
            border-right: 1px solid {BAUHAUS_LIGHT};
            border-bottom: 1px solid {BAUHAUS_LIGHT};
        }}
        .bauhaus-table td:last-child {{
            border-right: none;
        }}
        .bauhaus-table tr:last-child td {{
            border-bottom: none;
        }}
        .bauhaus-table .sub-col {{
            font-family: 'Bebas Neue', sans-serif;
            font-size: 1.1rem;
            letter-spacing: 0.1em;
            background: {BAUHAUS_LIGHT};
        }}
    </style>
    """
    if granularidade == "diario":
        st.markdown(css_tabela, unsafe_allow_html=True)

    # HTML da tabela — montado com concatenação simples (sem f-string para evitar
    # conflito de chaves com CSS)
    linhas_html = ""
    for sub in SUBMERCADOS_ORD:
        if sub in stats.index:
            row = stats.loc[sub]
            linhas_html += (
                "<tr>"
                f'<td class="sub-col">{sub}</td>'
                f"<td>{fmt_brl(row['min'])}</td>"
                f"<td>{fmt_brl(row['mean'])}</td>"
                f"<td>{fmt_brl(row['max'])}</td>"
                "</tr>"
            )

    tabela_html = (
        '<table class="bauhaus-table">'
        "<thead><tr>"
        "<th>Submercado</th>"
        "<th>Mínimo</th>"
        "<th>Média</th>"
        "<th>Máximo</th>"
        "</tr></thead>"
        f"<tbody>{linhas_html}</tbody>"
        "</table>"
    )
    if granularidade == "diario":
        st.markdown(tabela_html, unsafe_allow_html=True)

    # --- Download ---
    st.markdown("### Exportar")
    # Pivotar: data nas linhas, submercados em colunas (formato "largo")
    # Ordem de colunas: N, NE, SE, S (alfabética por padrão em português)
    csv_pivot = dff.pivot_table(
        index="data",
        columns="submercado",
        values="pld",
        aggfunc="mean",
    )
    # Reordenar colunas explicitamente: N, NE, SE, S
    ordem_csv = [c for c in ["N", "NE", "SE", "S"] if c in csv_pivot.columns]
    csv_pivot = csv_pivot[ordem_csv]
    # Formatar data como DD/MM/AAAA (padrão BR)
    csv_export = csv_pivot.reset_index()
    csv_export["data"] = csv_export["data"].dt.strftime("%d/%m/%Y")
    csv_export = csv_export.rename(columns={"data": "Data"})
    # Usa separador ; e decimal , (padrão brasileiro pra Excel)
    csv = csv_export.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")
    st.download_button(
        label="Baixar dados filtrados (CSV)",
        data=csv,
        file_name=f"pld_{granularidade}_{data_ini}_{data_fim}.csv",
        mime="text/csv",
        use_container_width=False,
    )

elif aba == "Reservatórios":
    st.markdown("# RESERVATÓRIOS")
    st.markdown(
        '<div style="border-bottom: 2px solid #1A1A1A; '
        'margin: 0 0 -1.5rem 0;"></div>',
        unsafe_allow_html=True,
    )

    # --- Carregar dados ---
    with st.spinner("Carregando dados do ONS…"):
        try:
            df_res = load_reservatorios()
        except Exception as e:
            st.error(f"Falha ao carregar dados do ONS: {e}")
            debug = st.session_state.get("_debug_erros", [])
            if debug:
                st.subheader("Detalhes técnicos do erro")
                for d in debug[:20]:
                    st.code(d)
            st.stop()

    if df_res.empty:
        st.warning("Nenhum dado disponível.")
        st.stop()

    # --- Controles de data ---
    min_d = df_res["data"].min().date()
    max_d = df_res["data"].max().date()

    # Default: últimos 5 anos. Reseta se o dataset mudar (troca de aba, etc.).
    if (
        "res_data_ini" not in st.session_state
        or st.session_state.get("_res_dataset_max") != max_d
        or st.session_state.get("_res_dataset_min") != min_d
    ):
        st.session_state["res_data_ini"] = max(
            min_d, max_d - timedelta(days=365 * 5)
        )
        st.session_state["res_data_fim"] = max_d
        st.session_state["_res_dataset_max"] = max_d
        st.session_state["_res_dataset_min"] = min_d

    data_ini = st.session_state["res_data_ini"]
    data_fim = st.session_state["res_data_fim"]

    if data_ini > data_fim:
        st.error("A data inicial não pode ser posterior à data final.")
        st.stop()

    # --- Filtrar por período (antes dos controles, igual ao PLD) ---
    mask = (df_res["data"].dt.date >= data_ini) & (
        df_res["data"].dt.date <= data_fim
    )
    dff_res = df_res.loc[mask].copy()

    if dff_res.empty:
        st.warning("Sem dados no intervalo selecionado.")
        st.stop()

    # --- Período (atalhos + date_inputs) — via helper reusado ---
    _render_period_controls(
        presets=[
            ("1A", 365, False),
            ("3A", 1095, False),
            ("5A", 1825, False),
            ("10A", 3650, False),
            ("Máx", None, True),
        ],
        session_key_ini="res_data_ini",
        session_key_fim="res_data_fim",
        key_prefix="btn_res_",
        min_d=min_d,
        max_d=max_d,
    )

    # Caption: última atualização (data mais recente no dataset).
    # Usa st.markdown com estilo inline em vez de st.caption pra garantir
    # cor legível (st.caption pode herdar estilos globais que deixam
    # ela quase invisível em certos contextos do Streamlit 1.56).
    ultima_data_ds = df_res["data"].max().date()
    # Duas notas em linhas separadas, mesma tipografia (caption cinza italic).
    # Renderizadas em uma única chamada st.markdown pra ficarem coladas.
    st.markdown(
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.85rem; color:#6B6B6B; font-style:italic; '
        f'margin:0.4rem 0 0 0;">'
        f'Dados atualizados diariamente pelo ONS. '
        f'Última atualização no dataset: {ultima_data_ds.strftime("%d/%m/%Y")}.'
        f'</div>'
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.85rem; color:#6B6B6B; font-style:italic; '
        f'margin:0 0 0.6rem 0;">'
        f'Faixas azuis: período úmido hidrológico (1º nov – 30 abr).'
        f'</div>',
        unsafe_allow_html=True,
    )

    # --- 5 gráficos empilhados ---
    CORES_SUBSISTEMA = {
        "SIN": BAUHAUS_GRAY,    # cinza escuro — "o total"
        "SE":  BAUHAUS_RED,
        "S":   BAUHAUS_BLUE,
        "NE":  BAUHAUS_YELLOW,
        "N":   BAUHAUS_BLACK,
    }
    ORDEM_SUBSISTEMA = ["SIN", "SE", "S", "NE", "N"]
    LABELS_SUBSISTEMA = {
        "SIN": "SIN",
        "SE":  "SUDESTE",
        "S":   "SUL",
        "NE":  "NORDESTE",
        "N":   "NORTE",
    }

    # Último valor por subsistema — do DATASET COMPLETO (não do filtrado).
    # Fica no título de cada gráfico, sempre refletindo o publicado mais
    # recente pelo ONS, independente do período selecionado.
    ultimo_por_sub = (
        df_res.sort_values("data")
        .groupby("subsistema_code")
        .tail(1)
        .set_index("subsistema_code")["ear_pct"]
    )

    data_str_ultima = ultima_data_ds.strftime("%d/%m/%Y")

    for code in ORDEM_SUBSISTEMA:
        cor = CORES_SUBSISTEMA[code]
        label = LABELS_SUBSISTEMA[code]
        ultimo = ultimo_por_sub.get(code)
        pct_str = (
            f"{ultimo:.1f}%" if ultimo is not None and pd.notna(ultimo) else ""
        )
        # Lado direito: "DD/MM/YYYY · X.X%" (data = última do dataset completo)
        right_side = (
            f"{data_str_ultima} · {pct_str}" if pct_str else data_str_ultima
        )

        # Título Bauhaus: nome à esquerda, data+% à direita, mesma linha.
        # Flex container com space-between distribui os dois extremos
        # preenchendo a largura disponível acima do gráfico.
        st.markdown(
            f'<div style="display:flex; justify-content:space-between; '
            f'align-items:baseline; '
            f'font-family:\'Bebas Neue\', sans-serif; '
            f'font-size:1.1rem; letter-spacing:0.08em; color:#1A1A1A; '
            f'margin: 1.2rem 0 0.3rem 0; padding-bottom:3px; '
            f'border-bottom: 2px solid #1A1A1A;">'
            f'<span>{label}</span>'
            f'<span>{right_side}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        ds = dff_res[dff_res["subsistema_code"] == code].sort_values("data")
        if ds.empty:
            st.caption(f"Sem dados no período para {label}.")
            continue

        fig = go.Figure()
        # Faixas azuis de período úmido (atrás das linhas, sobre o range filtrado)
        _add_wet_season_bands(fig, date_start=data_ini, date_end=data_fim)
        fig.add_trace(
            go.Scatter(
                x=ds["data"],
                y=ds["ear_pct"],
                mode="lines",
                line=dict(color=cor, width=2.5),
                name=label,
                hovertemplate=(
                    f'<span style="color:{cor}; font-weight:700;">{label}</span>'
                    '&nbsp;&nbsp;'
                    '<span style="color:#1A1A1A;">EAR %{y:.1f}%</span>'
                    '<extra></extra>'
                ),
            )
        )
        fig.update_layout(
            height=270,
            margin=dict(l=20, r=20, t=10, b=20),
            paper_bgcolor=BAUHAUS_CREAM,
            plot_bgcolor=BAUHAUS_CREAM,
            hovermode="x unified",
            hoverlabel=dict(
                bgcolor=BAUHAUS_CREAM,
                bordercolor=BAUHAUS_BLACK,
                font=dict(
                    family="'IBM Plex Mono', 'Courier New', monospace",
                    size=12, color=BAUHAUS_BLACK,
                ),
            ),
            showlegend=False,
            xaxis=dict(
                title=None, showgrid=False, showline=True,
                linewidth=2, linecolor=BAUHAUS_BLACK,
                ticks="outside", tickcolor=BAUHAUS_BLACK,
                tickfont=dict(
                    family="Inter, sans-serif",
                    size=13, color=BAUHAUS_BLACK,
                ),
                hoverformat="%d/%m/%Y",
            ),
            yaxis=dict(
                title=None,
                # Escala 0-110% compartilhada entre os 5 gráficos.
                # Acomoda picos >100% (raros, ex: N histórico ~103%) sem
                # esmagar a faixa normal (0-100%). Não usar range fixo 0-100%
                # porque o ONS publica valores reais que excedem a capacidade
                # nominal (enchentes, revisões de EARmax).
                range=[0, 110],
                showgrid=True, gridcolor=BAUHAUS_LIGHT, gridwidth=1,
                showline=True, linewidth=2, linecolor=BAUHAUS_BLACK,
                ticks="outside", tickcolor=BAUHAUS_BLACK,
                tickfont=dict(
                    family="Inter, sans-serif",
                    size=13, color=BAUHAUS_BLACK,
                ),
                zeroline=False, ticksuffix="%",
            ),
            font=dict(family="Inter, sans-serif", size=12),
        )
        st.plotly_chart(
            fig, use_container_width=True, config={"displaylogo": False},
        )

    # --- Export CSV ---
    st.markdown("### Exportar")
    csv_pivot = dff_res.pivot_table(
        index="data", columns="subsistema_code", values="ear_pct",
        aggfunc="mean",
    )
    ordem_csv = [c for c in ORDEM_SUBSISTEMA if c in csv_pivot.columns]
    csv_pivot = csv_pivot[ordem_csv]
    csv_export = csv_pivot.reset_index()
    csv_export["data"] = csv_export["data"].dt.strftime("%d/%m/%Y")
    csv_export = csv_export.rename(columns={"data": "Data"})
    csv = csv_export.to_csv(
        index=False, sep=";", decimal=",",
    ).encode("utf-8-sig")
    st.download_button(
        label="Baixar dados filtrados (CSV)",
        data=csv,
        file_name=f"reservatorios_{data_ini}_{data_fim}.csv",
        mime="text/csv",
        use_container_width=False,
    )

elif aba == "ENA/Chuva":
    st.markdown("# ENA/Chuva")
    st.markdown(
        '<div style="border-bottom: 2px solid #1A1A1A; '
        'margin: 0 0 -1.5rem 0;"></div>',
        unsafe_allow_html=True,
    )

    # --- Carregar dados ---
    with st.spinner("Carregando dados do ONS…"):
        try:
            df_ena = load_ena()
        except Exception as e:
            st.error(f"Falha ao carregar dados do ONS: {e}")
            debug = st.session_state.get("_debug_erros", [])
            if debug:
                st.subheader("Detalhes técnicos do erro")
                for d in debug[:20]:
                    st.code(d)
            st.stop()

    if df_ena.empty:
        st.warning("Nenhum dado disponível.")
        st.stop()

    # --- Controles de data ---
    min_d = df_ena["data"].min().date()
    max_d = df_ena["data"].max().date()

    # Default: últimos 5 anos. Reseta se o dataset mudar.
    if (
        "ena_data_ini" not in st.session_state
        or st.session_state.get("_ena_dataset_max") != max_d
        or st.session_state.get("_ena_dataset_min") != min_d
    ):
        st.session_state["ena_data_ini"] = max(
            min_d, max_d - timedelta(days=365 * 5)
        )
        st.session_state["ena_data_fim"] = max_d
        st.session_state["_ena_dataset_max"] = max_d
        st.session_state["_ena_dataset_min"] = min_d

    data_ini = st.session_state["ena_data_ini"]
    data_fim = st.session_state["ena_data_fim"]

    if data_ini > data_fim:
        st.error("A data inicial não pode ser posterior à data final.")
        st.stop()

    mask = (df_ena["data"].dt.date >= data_ini) & (
        df_ena["data"].dt.date <= data_fim
    )
    dff_ena = df_ena.loc[mask].copy()

    if dff_ena.empty:
        st.warning("Sem dados no intervalo selecionado.")
        st.stop()

    # --- Período (atalhos + date_inputs) — via helper reusado ---
    _render_period_controls(
        presets=[
            ("1A", 365, False),
            ("3A", 1095, False),
            ("5A", 1825, False),
            ("10A", 3650, False),
            ("Máx", None, True),
        ],
        session_key_ini="ena_data_ini",
        session_key_fim="ena_data_fim",
        key_prefix="btn_ena_",
        min_d=min_d,
        max_d=max_d,
    )

    # Notas explicativas (mesma tipografia da aba Reservatórios).
    ultima_data_ds = df_ena["data"].max().date()
    st.markdown(
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.85rem; color:#6B6B6B; font-style:italic; '
        f'margin:0.4rem 0 0 0;">'
        f'ENA em % da MLT (Média de Longo Termo — ONS). '
        f'100% indica a média histórica do mês. '
        f'Dados atualizados diariamente pelo ONS. '
        f'Última atualização: {ultima_data_ds.strftime("%d/%m/%Y")}.'
        f'</div>'
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.85rem; color:#6B6B6B; font-style:italic; '
        f'margin:0 0 0 0;">'
        f'Faixas azuis: período úmido hidrológico (1º nov – 30 abr).'
        f'</div>'
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.85rem; color:#6B6B6B; font-style:italic; '
        f'margin:0 0 0.6rem 0;">'
        f'Valores acima de 250% aparecem cortados no gráfico — '
        f'passe o mouse para ver o valor real.'
        f'</div>',
        unsafe_allow_html=True,
    )

    # --- 5 gráficos empilhados ---
    CORES_SUBSISTEMA_ENA = {
        "SIN": BAUHAUS_GRAY,    # cinza escuro — "o total"
        "SE":  BAUHAUS_RED,
        "S":   BAUHAUS_BLUE,
        "NE":  BAUHAUS_YELLOW,
        "N":   BAUHAUS_BLACK,
    }
    ORDEM_SUBSISTEMA_ENA = ["SIN", "SE", "S", "NE", "N"]
    LABELS_SUBSISTEMA_ENA = {
        "SIN": "SIN",
        "SE":  "SUDESTE",
        "S":   "SUL",
        "NE":  "NORDESTE",
        "N":   "NORTE",
    }

    # Último valor por subsistema — do DATASET COMPLETO (não do filtrado).
    ultimo_por_sub_ena = (
        df_ena.sort_values("data")
        .groupby("subsistema_code")
        .tail(1)
        .set_index("subsistema_code")["ena_mlt_pct"]
    )

    data_str_ultima = ultima_data_ds.strftime("%d/%m/%Y")

    # Eixo Y FIXO 0-250% compartilhado pelos 5 gráficos (decisão 5.7 CLAUDE.md).
    # Range derivado-do-filtro seria esticado por picos raros (ENA pode chegar
    # a ~1000% da MLT em eventos hidrológicos excepcionais, achatando toda a
    # faixa 0-200% que é onde 95% dos dados vivem). Valores acima de 250% NÃO
    # são filtrados — ficam cortados visualmente e o hover segue mostrando o
    # valor real (ver 3ª nota explicativa acima).
    Y_RANGE_ENA = [0, 250]

    # CSS dos KPI cards (injetado uma vez antes do loop). Estilo local à
    # aba ENA — se precisar reusar noutra aba, mover pro bloco CSS global
    # do topo do arquivo e renomear as classes.
    st.markdown(
        """
        <style>
        .ena-kpi-card {
            text-align: center;
            padding: 0.15rem 0.3rem;
        }
        .ena-kpi-label {
            font-family: 'Inter', sans-serif;
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #6B6B6B;
            font-weight: 600;
            margin-bottom: 0.15rem;
            white-space: nowrap;
            line-height: 1.2;
        }
        .ena-kpi-value {
            font-family: 'Bebas Neue', sans-serif;
            font-size: 1.4rem;
            color: #1A1A1A;
            letter-spacing: 0.02em;
            line-height: 1.1;
        }
        .ena-kpi-separator {
            border-bottom: 1px solid #E0E0E0;
            margin: 0.2rem 0 0.6rem 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Janelas dos KPIs — fixas (referência = última data do dataset, não
    # o filtro de período). Calculadas 1 vez antes do loop.
    _kpi_windows = [
        ("Último mês",
         ultima_data_ds - timedelta(days=30),  ultima_data_ds),
        ("Últimos 3 meses",
         ultima_data_ds - timedelta(days=90),  ultima_data_ds),
        ("Últimos 12 meses",
         ultima_data_ds - timedelta(days=365), ultima_data_ds),
        ("Período úmido atual",
         *_wet_season_window(ultima_data_ds)),
    ]

    for code in ORDEM_SUBSISTEMA_ENA:
        cor = CORES_SUBSISTEMA_ENA[code]
        label = LABELS_SUBSISTEMA_ENA[code]
        ultimo = ultimo_por_sub_ena.get(code)
        if ultimo is not None and pd.notna(ultimo):
            # Zero decimais na aba ENA (contraste com EAR que usa .1f).
            val_str = f"{int(round(ultimo))}%"
        else:
            val_str = ""
        right_side = (
            f"{data_str_ultima} · {val_str}" if val_str
            else data_str_ultima
        )

        st.markdown(
            f'<div style="display:flex; justify-content:space-between; '
            f'align-items:baseline; '
            f'font-family:\'Bebas Neue\', sans-serif; '
            f'font-size:1.1rem; letter-spacing:0.08em; color:#1A1A1A; '
            f'margin: 1.2rem 0 0.3rem 0; padding-bottom:3px; '
            f'border-bottom: 2px solid #1A1A1A;">'
            f'<span>{label}</span>'
            f'<span>{right_side}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # 4 KPIs ponderados (ENA acumulada / MLT acumulada × 100) pro
        # subsistema, entre o título Bauhaus e o gráfico.
        kpi_cols = st.columns([1, 1, 1, 1])
        for (kpi_label, d_start, d_end), col in zip(_kpi_windows, kpi_cols):
            value = _compute_kpi_mlt_pct(df_ena, code, d_start, d_end)
            kpi_val_str = (
                f"{int(round(value))}%" if pd.notna(value) else "—"
            )
            with col:
                st.markdown(
                    f'<div class="ena-kpi-card">'
                    f'<div class="ena-kpi-label">{kpi_label}</div>'
                    f'<div class="ena-kpi-value">{kpi_val_str}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        st.markdown(
            '<div class="ena-kpi-separator"></div>',
            unsafe_allow_html=True,
        )

        ds = dff_ena[dff_ena["subsistema_code"] == code].sort_values("data")
        if ds.empty:
            st.caption(f"Sem dados no período para {label}.")
            continue

        fig = go.Figure()
        # Faixas azuis de período úmido — mesma função dos Reservatórios
        _add_wet_season_bands(fig, date_start=data_ini, date_end=data_fim)
        # Linha de referência em 100% (média histórica MLT). Tracejada cinza
        # suave — indica "exatamente na média do mês", acima = chuva acima
        # do normal, abaixo = seco em relação ao histórico.
        fig.add_hline(
            y=100,
            line_dash="dash",
            line_color="#6B6B6B",
            line_width=1.2,
            opacity=0.45,
        )
        fig.add_trace(
            go.Scatter(
                x=ds["data"],
                y=ds["ena_mlt_pct"],
                mode="lines",
                line=dict(color=cor, width=2.5),
                name=label,
                hovertemplate=(
                    f'<span style="color:{cor}; font-weight:700;">{label}</span>'
                    '&nbsp;&nbsp;'
                    '<span style="color:#1A1A1A;">ENA %{y:.0f}% MLT</span>'
                    '<extra></extra>'
                ),
            )
        )
        fig.update_layout(
            height=270,
            margin=dict(l=20, r=20, t=10, b=20),
            paper_bgcolor=BAUHAUS_CREAM,
            plot_bgcolor=BAUHAUS_CREAM,
            # separators=",." → decimal vírgula, milhar ponto (padrão BR).
            # Aplica aos d3-format strings como %{y:.0f} no hovertemplate/tick.
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
            showlegend=False,
            xaxis=dict(
                title=None, showgrid=False, showline=True,
                linewidth=2, linecolor=BAUHAUS_BLACK,
                ticks="outside", tickcolor=BAUHAUS_BLACK,
                tickfont=dict(
                    family="Inter, sans-serif",
                    size=13, color=BAUHAUS_BLACK,
                ),
                hoverformat="%d/%m/%Y",
            ),
            yaxis=dict(
                title=None,
                # Range fixo 0-250%. Ver bloco Y_RANGE_ENA acima.
                range=Y_RANGE_ENA,
                showgrid=True, gridcolor=BAUHAUS_LIGHT, gridwidth=1,
                showline=True, linewidth=2, linecolor=BAUHAUS_BLACK,
                ticks="outside", tickcolor=BAUHAUS_BLACK,
                tickfont=dict(
                    family="Inter, sans-serif",
                    size=13, color=BAUHAUS_BLACK,
                ),
                zeroline=False,
                tickformat=".0f",
                ticksuffix="%",
            ),
            font=dict(family="Inter, sans-serif", size=12),
        )
        st.plotly_chart(
            fig, use_container_width=True, config={"displaylogo": False},
        )

    # --- Export CSV ---
    # Valores em % MLT (mesma métrica dos gráficos). Colunas mantêm nomes
    # curtos (SIN/SE/S/NE/N) — unidade fica implícita pelo filename
    # `ena_*.csv` + pela nota explicativa acima. Documentado no CLAUDE.md.
    st.markdown("### Exportar")
    csv_pivot = dff_ena.pivot_table(
        index="data", columns="subsistema_code", values="ena_mlt_pct",
        aggfunc="mean",
    )
    # Ordem: SIN, SE, S, NE, N (mesma dos gráficos)
    ordem_csv = [c for c in ORDEM_SUBSISTEMA_ENA if c in csv_pivot.columns]
    csv_pivot = csv_pivot[ordem_csv]
    csv_export = csv_pivot.reset_index()
    csv_export["data"] = csv_export["data"].dt.strftime("%d/%m/%Y")
    csv_export = csv_export.rename(columns={"data": "Data"})
    csv = csv_export.to_csv(
        index=False, sep=";", decimal=",",
    ).encode("utf-8-sig")
    st.download_button(
        label="Baixar dados filtrados (CSV)",
        data=csv,
        file_name=f"ena_{data_ini}_{data_fim}.csv",
        mime="text/csv",
        use_container_width=False,
    )

# =============================================================================
# RODAPÉ — com espaçamento claro para evitar sobreposição
# =============================================================================
st.markdown(
    """
    <hr>
    <div class="rodape">
        <span>Dashboard Setor Elétrico</span>
        <span>·</span>
        <span>Dados: CCEE Portal Dados Abertos</span>
        <span>·</span>
        <span>Licença CC-BY-4.0</span>
    </div>
    """,
    unsafe_allow_html=True,
)
