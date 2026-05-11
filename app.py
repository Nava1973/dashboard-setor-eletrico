"""
Dashboard do Setor Elétrico Brasileiro
Aba 1: PLD Médio Diário por Submercado

Design: Bauhaus clássico — paleta de cores primárias fiel aos tapetes
de Josef Albers (azul cobalto, vermelho cádmio, amarelo cromo).
Tipografia: Bebas Neue (condensada, impactante) + Inter (legibilidade).

Fonte: CCEE - Portal Dados Abertos
https://dadosabertos.ccee.org.br/dataset/pld_media_diaria
"""

import base64
from pathlib import Path

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from streamlit_plotly_events import plotly_events
from datetime import timedelta

from auth import require_login, logout_button

# Logo BBI horizontal branco — lido 1x no nível do módulo, usado na sidebar
_LOGO_WHITE_PATH = Path(__file__).parent / "assets" / "logos" / "bbi_horizontal_white.png"
try:
    _LOGO_WHITE_B64 = base64.b64encode(_LOGO_WHITE_PATH.read_bytes()).decode()
except Exception:
    _LOGO_WHITE_B64 = ""
from data_loader import (
    load_pld_media_diaria,
    load_pld_horaria,
    load_pld_media_mensal,
    load_reservatorios,
    load_ena,
    load_balanco_subsistema,
    is_balanco_cache_fresh,
    clear_cache,
)
from components.tab_curtailment import render_aba_curtailment
from components.tab_modulacao import render_aba_modulacao

# Mapa de granularidade → loader. Usado por get_pld_df().
# Fase 1: só "diario" é ativado (session_state hardcoded).
# Fases 2-3 vão trocar a chave via dropdown no título do gráfico.
GRANULARIDADES = {
    "horario": load_pld_horaria,
    "diario":  load_pld_media_diaria,
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

# Paleta canônica de fontes de geração (decisão 5.33)
# Aplicada em: aba Geração + aba Carga Viz 2.
# Não confundir com cores Bauhaus estruturais (BAUHAUS_BLUE,
# BAUHAUS_BLACK) — essas são pra UI (bordas, texto, eixos).
COR_FONTE_SOLAR   = "#F6BD16"
COR_FONTE_EOLICA  = "#8FA31E"
COR_FONTE_HIDRO   = "#4A6FA5"
COR_FONTE_TERMICA = "#A04B2E"

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

    /* Alerts (warning/info/error/success) — tema é dark, texto default
       branco fica ilegível sobre fundos amarelo/azul. Override Bauhaus
       em estratégia "container externo dita o visual + descendentes
       transparentes":
       - stAlert externo recebe TODO o visual (cream + borda preta
         sólida + margins). Borda externa virtualmente vira a única.
       - Descendentes (divs internos, baseweb notification, etc.)
         ficam com background transparent + border none + shadow none,
         deixando o cream do parent passar e matando a borda colorida
         por tipo (azul/amarelo/vermelho) que vinha desses wrappers.
       - Texto preto cobre p/span/div, mas NÃO seleciona svg/path —
         preserva a cor do ícone (⚠️/ℹ️/❌) que é a única
         diferenciação semântica que sobra. */
    [data-testid="stAlert"] {{
        margin-top: 0.8rem !important;
        margin-bottom: 0.4rem !important;
        background-color: {BAUHAUS_LIGHT} !important;
        border: 2px solid {BAUHAUS_BLACK} !important;
        border-radius: 0 !important;
        box-shadow: none !important;
        color: {BAUHAUS_BLACK} !important;
    }}
    [data-testid="stAlert"] div,
    [data-testid="stAlert"] p,
    [data-testid="stAlert"] span,
    [data-testid="stAlert"] [data-baseweb="notification"],
    [data-testid="stAlert"] [data-testid="stAlertContainer"] {{
        background-color: transparent !important;
        border: none !important;
        box-shadow: none !important;
        color: {BAUHAUS_BLACK} !important;
    }}

    /* Expander Bauhaus — mesma família do stAlert (decisão 5.23): tema dark
       herda textColor cinza-claro no conteúdo do expander, ilegível sobre
       cream. Refinamento Sessão 4a: header SEM caixa (texto puro clicável,
       não compete visualmente com KPIs acima); painel aberto ganha caixa
       só ao redor do CONTEÚDO (borda preta 2px completa + fundo cream-light).
       O chevron ▶/▼ é injetado via JS (TreeWalker troca o nome do ícone
       Material Symbols vazando como texto) — ver bloco em ~linha 525.
       Prefixo [data-testid="stExpander"] mantém escopo — não atinge
       expanders eventuais na sidebar (fundo dark + texto cream). */
    [data-testid="stExpander"] details > summary {{
        background-color: transparent !important;
        color: {BAUHAUS_BLACK} !important;
        border: none !important;
        border-radius: 0 !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 600 !important;
        padding: 0.4rem 0 !important;
    }}
    [data-testid="stExpander"] details > summary p,
    [data-testid="stExpander"] details > summary span,
    [data-testid="stExpander"] details > summary div {{
        color: {BAUHAUS_BLACK} !important;
    }}
    [data-testid="stExpanderDetails"] {{
        background-color: {BAUHAUS_LIGHT} !important;
        color: {BAUHAUS_BLACK} !important;
        border: 2px solid {BAUHAUS_BLACK} !important;
        border-radius: 0 !important;
        padding: 1rem !important;
    }}
    [data-testid="stExpanderDetails"] p,
    [data-testid="stExpanderDetails"] span,
    [data-testid="stExpanderDetails"] strong,
    [data-testid="stExpanderDetails"] em,
    [data-testid="stExpanderDetails"] li,
    [data-testid="stExpanderDetails"] div {{
        color: {BAUHAUS_BLACK} !important;
    }}

    /* Botões principais (fora da sidebar) — altura igual aos date inputs.
       Seletor é DESCENDENTE (espaço, não `>`) com filtro [kind] pra cobrir
       2 estruturas DOM:
       - Sem help=: <div class="stButton"><button kind="…">…</button></div>
       - Com help=: <div class="stButton"><div data-testid="stTooltipHoverTarget">
                       <button kind="…">…</button></div></div>
       O wrapper stTooltipHoverTarget quebra `.stButton > button` (filho
       direto), causando o bug "Máx amarelo indevido" da Sessão 4a — apenas
       Máx tem help=, então só ele perdia o estilo Bauhaus. Filtro [kind]
       evita atingir o button interno do stTooltipIcon (caso exista — não
       tem atributo kind). */
    .stButton button[kind] {{
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
    .stButton button[kind]:hover {{
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
        /* Decisão G.4 (Fase G, 2026-05-04): wide moderado.
           set_page_config(layout="wide") remove o limite default (~704px),
           mas limitamos a 1400px pra evitar esticar feio em monitores 4K.
           Sweet spot pra acomodar tabela Por usina expandida (G.5) sem
           prejudicar telas grandes. Centraliza com margin auto. */
        max-width: 1400px;
        margin: 0 auto;
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

    /* ===== Fase H.7.B-bis (calibrado H.8.A) — Gap reduzido row
       Granularidade → row 2 ===== */
    /* Estratégia idiomática Streamlit 1.36+: row 2 envolvida em
       st.container(key="...row2") que gera classe st-key-* no DOM.
       Margin-top negativo aplicado direto na classe, sem :has() (decisão 4.1)
       e sem sibling-selector (não funciona pq st.markdown fica enterrado
       em stElementContainer — ver diagnóstico DOM da Fase H.7.B).

       Calibração H.8.A: separação em 3 grupos por necessidade visual:
       - Mensal (Eneva + Sistema): 0rem (col_meio sem MWM/GWH ficou
         mais baixo, gap natural OK)
       - Eneva Trimestral: -3.5rem (subir bot ano pra alinhar com MWM/GWH
         ainda em col_meio — recalibrar na H.8.B)
       - Sistema Trimestral: 0rem (SIN não tem MWM/GWH em col_meio,
         -3.5rem sobrepunha no selectbox Granularidade) */
    /* Mensal: gap natural (col_meio agora só tem Usina, ficou mais baixo) */
    [class*="st-key-termico_eneva_mensal_row2"],
    [class*="st-key-termico_sistema_mensal_row2"] {{
        margin-top: 0rem !important;
    }}
    /* Eneva Trimestral: subir bot ano pra alinhar com MWM/GWH em col_meio
       (recalibrar na H.8.B quando MWM/GWH descer pra row 2) */
    [class*="st-key-termico_eneva_trimestral_row2"] {{
        margin-top: -3.5rem !important;
    }}
    /* Sistema Trimestral: gap natural — SIN não tem MWM/GWH em col_meio,
       row 1 mais baixa, então -3.5rem sobrepõe */
    [class*="st-key-termico_sistema_trimestral_row2"] {{
        margin-top: 0rem !important;
    }}

    /* Botões "primary" do Streamlit (atalhos de período ativos em PLD e
       Reservatórios): amarelo Bauhaus com borda preta. Hover = vermelho.
       Mesmo seletor descendente do bloco principal acima — cobre botões
       com help= (Máx) que ganham wrapper stTooltipHoverTarget. */
    .stButton button[kind="primary"] {{
        background: {BAUHAUS_YELLOW} !important;
        color: {BAUHAUS_BLACK} !important;
        border: 2px solid {BAUHAUS_BLACK} !important;
        font-weight: 700 !important;
    }}
    .stButton button[kind="primary"]:hover {{
        background: {BAUHAUS_RED} !important;
        color: {BAUHAUS_CREAM} !important;
        border-color: {BAUHAUS_BLACK} !important;
    }}

    /* Botão "Estender histórico para 2000" colado nos presets de período
       (Geração + Carga). Streamlit emite `class="st-key-{{key}}"` no
       element-container do widget quando ele recebe key=. Ataca os 2
       containers (ambas as abas usam a mesma estratégia, decisão Sessão
       4a) com margin-top negativo pra colapsar o gap default do
       stVerticalBlock. */
    .st-key-btn_gen_historico_completo,
    .st-key-btn_carga_historico_completo {{
        margin-top: -0.8rem !important;
    }}
    /* Sem borda preta — o botão é AÇÃO opcional, não navegação.
       Borda 2px do .stButton button[kind] global fazia parecer tab/sub-aba.
       Mantém background cream + hover amarelo Bauhaus do estilo padrão. */
    .st-key-btn_gen_historico_completo button[kind],
    .st-key-btn_carga_historico_completo button[kind] {{
        border: none !important;
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

# Workaround: tema dark do Streamlit injeta --background-color: #0a0d10
# DENTRO do iframe da streamlit-plotly-events, pintando o body interno
# de preto. CSS injection externo nao atravessa iframe (cross-document).
# JS injection via components.html acessa window.parent.document, encontra
# iframes da lib (allow-same-origin), e injeta <style> dentro de cada um
# overrideando --background-color pra cream Bauhaus.
import streamlit.components.v1 as components

components.html("""
<script>
function fixPlotlyEventsBg() {
    try {
        const iframes = window.parent.document.querySelectorAll(
            'iframe[title*="streamlit_plotly_events"]'
        );
        iframes.forEach(iframe => {
            const innerDoc = iframe.contentDocument || iframe.contentWindow.document;
            if (!innerDoc) return;
            // Skip se ja injetamos
            if (innerDoc.getElementById('bauhaus-bg-override')) return;
            // Injeta style override
            const style = innerDoc.createElement('style');
            style.id = 'bauhaus-bg-override';
            style.textContent = `
                :root { --background-color: #F5F1E8 !important; }
                body { background-color: #F5F1E8 !important; }
                html { background-color: #F5F1E8 !important; }
            `;
            innerDoc.head.appendChild(style);
        });
    } catch(e) {
        console.warn('Plotly events bg fix blocked:', e);
    }
}
// Roda imediatamente + polling pra capturar reruns do plotly_events.
// Polling foi removido em 02c65f1 supondo que derrubava Cloud, mas
// causa raiz era OOM (df_termico 1.19GB → ~50MB apos refactor
// dual-loader em Fase 4). Com RAM resolvida, polling pode voltar —
// elimina bordas pretas em iframes re-renderizados pos-click.
fixPlotlyEventsBg();
setInterval(fixPlotlyEventsBg, 500);
</script>
""", height=0)

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
            // Família "double arrow" + chevrons + menu = navegação de
            // sidebar/painel. Sempre usa caracteres simples << / >> pra
            // simetria visual (sidebar fechada >>, aberta <<).
            'keyboard_double_arrow_right': '>>',
            'keyboard_double_arrow_left':  '<<',
            'chevron_right':               '>>',
            'chevron_left':                '<<',
            'arrow_forward':               '>',
            'arrow_back':                  '<',
            'menu_open':                   '<<',
            'menu':                        '>>',
            'first_page':                  '<<',
            'last_page':                   '>>',
            // Família "keyboard_arrow_*" (singular) = chevrons de
            // expanders. Glifos triangulares ▶/▼/▲ preservam o sinal
            // direcional do expand/collapse, sem confundir com navegação
            // de sidebar. Identificados via DevTools no st.expander
            // (Sessão 4a) — DOM expõe como <span data-testid="stIconMaterial">.
            'keyboard_arrow_right': '▶',
            'keyboard_arrow_down':  '▼',
            'keyboard_arrow_up':    '▲',
            // Preventivos da família dos triângulos — variantes que o
            // Streamlit pode usar em outros componentes (selectbox aberto,
            // accordion não-expander, etc.).
            'arrow_drop_down': '▼',
            'arrow_drop_up':   '▲',
            'expand_more':     '▼',
            'expand_less':     '▲'
        };

        function substituirTextos() {
            const botoes = doc.querySelectorAll(
                '[data-testid="stSidebarCollapseButton"], ' +
                '[data-testid="stSidebarCollapsedControl"], ' +
                '[data-testid="collapsedControl"], ' +
                'button[kind="header"], ' +
                'button[kind="headerNoPadding"], ' +
                '[data-testid="stExpander"], ' +
                // Cobertura redundante mas explícita: o stIconMaterial
                // pode aparecer em qualquer lugar (não só dentro de
                // stExpander), então varremos diretamente também.
                '[data-testid="stIconMaterial"]'
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
    presets,                  # list[tuple[str, int|None, bool]]: (label, delta_days, is_max)
    session_key_ini,          # str: chave em session_state pra data_ini
    session_key_fim,          # str: chave em session_state pra data_fim
    key_prefix,               # str: prefixo dos keys dos botões (ex: "btn_" ou "btn_res_")
    min_d,
    max_d,
    single_day_preset_label=None,  # str|None: label do preset que ativa modo single-day (decisão 5.28)
):
    """Renderiza atalhos + 2 date_inputs numa linha, com botão "primary"
    amarelo pro preset ativo. Reset de mudança de dataset é responsabilidade
    do caller (feito antes de chamar esta função).

    `single_day_preset_label` (decisão 5.28): quando passado (ex: "1D"),
    o preset com esse label é considerado ativo se `data_ini == data_fim`
    (sobrescreve detecção por delta_days, que daria 0 = degenerado). E
    quando o modo single-day está ativo, os 2 date_inputs (data inicial/
    final) são substituídos por **1 date_input "Dia"** + **1 botão
    "Último dia"** — mesmo espaço, mesmas larguras de coluna.
    """
    data_ini_atual = st.session_state[session_key_ini]
    data_fim_atual = st.session_state[session_key_fim]

    # Modo single-day: ativo quando data_ini == data_fim e o caller
    # passou um label de preset designado.
    is_single_day_active = (
        single_day_preset_label is not None
        and data_ini_atual == data_fim_atual
    )

    # Detecta preset ativo comparando com cada entrada da lista.
    # No modo single-day, o preset designado fica ativo independente da
    # data escolhida — user pode mexer no date_input "Dia" sem perder o
    # destaque do preset.
    preset_atual = None
    if is_single_day_active:
        preset_atual = single_day_preset_label
    elif data_fim_atual == max_d:
        for label, delta, is_max in presets:
            if is_max and data_ini_atual == min_d:
                preset_atual = label
                break
            if delta is not None and (max_d - data_ini_atual).days == delta:
                preset_atual = label
                break

    n = len(presets)
    # Sessão 1.5b fix: ratio dos date_inputs adaptativo. Default 1.4 cobre
    # 4-5 presets (PLD/Reservatórios/ENA, ~161px). A partir de 6 presets a
    # fração de coluna cai abaixo do mínimo pra `dd/mm/yyyy` caber sem
    # corte (~131px), então sobe pra 1.8 (~165px). Não afeta as 3 abas
    # com presets antigos — só Geração/Carga após +10A.
    date_ratio = 1.8 if n > 5 else 1.4
    cols = st.columns([1] * n + [0.3, date_ratio, date_ratio])

    for i, (label, delta, is_max) in enumerate(presets):
        with cols[i]:
            tipo = "primary" if label == preset_atual else "secondary"
            # Tooltip dinâmico só no Máx — mostra o período real coberto
            # (varia conforme estado de gen_historico_completo nas abas
            # Carga/Geração: sem histórico ~2012, com histórico 2000).
            # Decisão 5.27. Outros presets (5A/10A) são autoexplicativos.
            help_text = (
                f"Máx — desde {min_d.strftime('%d/%m/%Y')}"
                if is_max else None
            )
            if st.button(
                label, use_container_width=True,
                key=f"{key_prefix}{label}", type=tipo,
                help=help_text,
            ):
                if is_max:
                    st.session_state[session_key_ini] = min_d
                else:
                    # Defesa em profundidade: clamp em min_d caso preset
                    # exceda o range disponível. 15A foi removido por
                    # degenerar pra Máx no dataset padrão ~14a (decisão
                    # 5.27), mas o clamp permanece — protege qualquer
                    # preset futuro contra StreamlitAPIException quando
                    # date_input é re-instanciado com value < min_value.
                    st.session_state[session_key_ini] = max(
                        min_d, max_d - timedelta(days=delta)
                    )
                st.session_state[session_key_fim] = max_d
                st.rerun()

    if is_single_day_active:
        # Callback de sincronização: quando o user muda o date_input
        # "Dia", `data_fim` precisa acompanhar `data_ini` ANTES do
        # próximo main script run (pra que o filter use ambas iguais
        # e não exiba range de 2 dias num flash). Streamlit roda
        # callbacks ANTES do main rerun.
        def _sync_single_day_fim():
            st.session_state[session_key_fim] = (
                st.session_state[session_key_ini]
            )

        # ORDEM IMPORTA: botão "Último dia" é EXECUTADO ANTES do
        # date_input — segue pattern dos botões de preset (que sabem
        # setar state[session_key_ini] e dar st.rerun()). Quando user
        # clica, o widget date_input ainda NÃO foi instanciado nesse
        # render, então o set programático é seguro (sem
        # StreamlitAPIException). Visualmente, `with cols[n+1]/[n+2]`
        # garantem date_input à esquerda + botão à direita —
        # independente da ordem de execução do código.
        with cols[n + 2]:
            if st.button(
                "Último dia", use_container_width=True,
                key=f"{key_prefix}sd_ultimo",
                help="Volta pro último dia disponível",
            ):
                st.session_state[session_key_ini] = max_d
                st.session_state[session_key_fim] = max_d
                st.rerun()

        with cols[n + 1]:
            st.date_input(
                "Dia", min_value=min_d, max_value=max_d,
                key=session_key_ini,
                on_change=_sync_single_day_fim,
                format="DD/MM/YYYY",
            )
    else:
        with cols[n + 1]:
            st.date_input(
                "Data inicial", min_value=min_d, max_value=max_d,
                key=session_key_ini,
                format="DD/MM/YYYY",
            )
        with cols[n + 2]:
            st.date_input(
                "Data final", min_value=min_d, max_value=max_d,
                key=session_key_fim,
                format="DD/MM/YYYY",
            )


def _render_period_controls_horaria(
    *,
    presets,              # list[tuple[str, int, bool]]: (label, window_dias, _)
    session_key_base,     # str: chave em session_state pra data_base
    session_key_window,   # str: chave em session_state pro window_dias (int)
    key_prefix,
    min_d,
    max_d,
):
    """Variante de _render_period_controls pro modo "data base + janela".
    Usado na aba Geração quando granularidade=Horária: janela = N dias
    terminando em data_base. 1 date_input em vez de 2. Layout da fileira
    replica o helper-range (mesmas proporções), com a última coluna vazia
    pra preservar o tamanho do campo Data base igual aos date_inputs das
    outras abas."""
    window_atual = st.session_state.get(session_key_window)

    preset_atual = None
    for label, window, _ in presets:
        if window == window_atual:
            preset_atual = label
            break

    n = len(presets)
    cols = st.columns([1] * n + [0.3, 1.4, 1.4])

    for i, (label, window, _) in enumerate(presets):
        with cols[i]:
            tipo = "primary" if label == preset_atual else "secondary"
            if st.button(
                label, use_container_width=True,
                key=f"{key_prefix}{label}", type=tipo,
            ):
                st.session_state[session_key_window] = window
                st.rerun()

    with cols[n + 1]:
        st.date_input(
            "Data base", min_value=min_d, max_value=max_d,
            key=session_key_base,
            format="DD/MM/YYYY",
        )


_MESES_BR = ["", "jan", "fev", "mar", "abr", "mai", "jun",
             "jul", "ago", "set", "out", "nov", "dez"]


def _format_periodo_br(data_ini, data_fim, granularidade):
    """String do período no formato BR por granularidade.

    Separador de range é en dash (U+2013, '–'), convenção tipográfica
    pra intervalos.

    - Mensal 1 mês:     'abr/2026'
    - Mensal ≥ 2 meses: 'mai/2025 – abr/2026'
    - Diária ≥ 2 dias:  '22/03/2026 – 21/04/2026'
    - Diária 1 dia:     '21/04/2026'
    - Horária 1D:       '21/04/2026'
    - Horária ≥ 2D mesmo ano:  '15/04 – 21/04'
    - Horária ≥ 2D virando ano: '25/12/2025 – 24/03/2026'

    strftime('%b') em pt-BR no Windows retorna inglês; por isso a tabela
    _MESES_BR manual pro caso Mensal.
    """
    if granularidade == "Mensal":
        meses_no_range = (
            (data_fim.year - data_ini.year) * 12
            + (data_fim.month - data_ini.month) + 1
        )
        fim_str = f"{_MESES_BR[data_fim.month]}/{data_fim.year}"
        if meses_no_range <= 1:
            return fim_str
        ini_str = f"{_MESES_BR[data_ini.month]}/{data_ini.year}"
        return f"{ini_str} – {fim_str}"

    if granularidade == "Horária":
        if data_ini == data_fim:
            return data_fim.strftime("%d/%m/%Y")
        # Mesmo ano: formato curto DD/MM – DD/MM. Atravessando virada de
        # ano (raro, ex: 90D ancorado em jan/fev): mantém ano nos dois
        # lados pra não ficar ambíguo.
        if data_ini.year == data_fim.year:
            return (
                f"{data_ini.strftime('%d/%m')} – "
                f"{data_fim.strftime('%d/%m')}"
            )
        return (
            f"{data_ini.strftime('%d/%m/%Y')} – "
            f"{data_fim.strftime('%d/%m/%Y')}"
        )

    # Diária — formato DD/MM/YYYY com ano em ambos os lados
    fim_str = data_fim.strftime("%d/%m/%Y")
    if data_ini == data_fim:
        return fim_str
    ini_str = data_ini.strftime("%d/%m/%Y")
    return f"{ini_str} – {fim_str}"


def _aplica_default_periodo_gen(granularidade, min_d, max_d):
    """Aplica default de período conforme granularidade (decisão 5.20).

    Defaults:
        Diária     → 1M  (max_d - 30 dias até max_d)
        Mensal     → 12M (max_d - 365 dias até max_d)
        Horária    → 1D + data_base = max_d
        Dia Típico → 30D (max_d - 30 dias até max_d) — sweet spot UX:
                     captura padrão semanal e dilui anomalias diárias.

    Pop das keys da granularidade alternativa (Horária pop quando vai
    pra Diária/Mensal/Dia Típico e vice-versa) — evita state stale no
    widget cleanup do Streamlit (decisões 5.16, 5.18, 5.19).

    Em Horária: gen_data_ini/gen_data_fim são DERIVADOS pós-helper Horária
    (linhas que espelham base/window). Não setamos aqui — eles são
    re-escritos quando o helper roda.
    """
    if granularidade == "Diária":
        st.session_state["gen_data_ini"] = max(
            min_d, max_d - timedelta(days=30)
        )
        st.session_state["gen_data_fim"] = max_d
        st.session_state.pop("gen_data_base", None)
        st.session_state.pop("gen_horaria_window_dias", None)
    elif granularidade == "Mensal":
        st.session_state["gen_data_ini"] = max(
            min_d, max_d - timedelta(days=365)
        )
        st.session_state["gen_data_fim"] = max_d
        st.session_state.pop("gen_data_base", None)
        st.session_state.pop("gen_horaria_window_dias", None)
    elif granularidade == "Dia Típico":
        st.session_state["gen_data_ini"] = max(
            min_d, max_d - timedelta(days=30)
        )
        st.session_state["gen_data_fim"] = max_d
        st.session_state.pop("gen_data_base", None)
        st.session_state.pop("gen_horaria_window_dias", None)
    else:  # Horária
        st.session_state["gen_data_base"] = max_d
        st.session_state["gen_horaria_window_dias"] = 1


def _aplica_default_periodo_carga(granularidade, min_d, max_d):
    """Análogo do _aplica_default_periodo_gen pra aba Carga (Sessão 4a).

    Defaults:
        Diária     → 1M  (preferência da aba — série temporal de demanda
                          em escala de meses é o uso mais natural)
        Mensal     → 12M (1 ano completo, mostra sazonalidade)
        Horária    → 1D + data_base = max_d
        Dia Típico → 30D (sweet spot UX da decisão 5.25)

    Pop das keys da granularidade alternativa pra evitar state stale no
    widget cleanup do Streamlit (decisões 5.16, 5.18, 5.19).
    """
    if granularidade == "Diária":
        st.session_state["carga_data_ini"] = max(
            min_d, max_d - timedelta(days=30)
        )
        st.session_state["carga_data_fim"] = max_d
        st.session_state.pop("carga_data_base", None)
        st.session_state.pop("carga_horaria_window_dias", None)
    elif granularidade == "Mensal":
        st.session_state["carga_data_ini"] = max(
            min_d, max_d - timedelta(days=365)
        )
        st.session_state["carga_data_fim"] = max_d
        st.session_state.pop("carga_data_base", None)
        st.session_state.pop("carga_horaria_window_dias", None)
    elif granularidade == "Dia Típico":
        st.session_state["carga_data_ini"] = max(
            min_d, max_d - timedelta(days=30)
        )
        st.session_state["carga_data_fim"] = max_d
        st.session_state.pop("carga_data_base", None)
        st.session_state.pop("carga_horaria_window_dias", None)
    else:  # Horária
        st.session_state["carga_data_base"] = max_d
        st.session_state["carga_horaria_window_dias"] = 1


@st.dialog("Estender histórico para 2000")
def _confirmar_historico_completo_gen():
    """Modal de confirmação pra expandir o range do dataset Geração de
    15 anos pra completo (2000-presente). Decisão 5.17 do CLAUDE.md
    (dois eixos: range do dataset vs período visível).

    Setado pelo botão "Estender histórico para 2000" nas abas Geração e
    Carga (compartilham gen_historico_completo). Confirmar marca a flag
    como True; cancelar fecha. @st.dialog requer Streamlit ≥1.32.
    """
    st.markdown(
        "Adicionar dados de **2000-2010** ao range disponível (mais 11 anos)?  \n"
        "Vai baixar mais ~12MB do ONS — pode levar ~30s na primeira vez. "
        "Em sessões seguintes carrega do cache em ~1s."
    )
    st.caption(
        "Útil pra análises históricas longas. Para uso típico (matriz "
        "atual), o range default de 15 anos cobre toda a era da eólica "
        "e solar centralizada."
    )
    col1, col2 = st.columns(2)
    if col1.button("Cancelar", use_container_width=True):
        st.rerun()
    if col2.button(
        "Carregar", type="primary", use_container_width=True,
    ):
        st.session_state["gen_historico_completo"] = True
        st.rerun()


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


def _compute_rampa_series(df_long, code, data_ini, data_fim, janela_h):
    """
    Série completa de rampas de carga líquida em janela de N horas
    (Sessão 4a — KPIs e viz 5 da aba Carga).

    Carga líquida = val_carga - val_gereolica - val_gersolar (mesmo
    instante). Rampa(t, N) = liq(t+Nh) - liq(t), com SINAL preservado
    (positivo = up-ramp = sistema precisa SUBIR geração; negativo =
    down-ramp).

    Sempre lê dado horário bruto do parquet — independente de qualquer
    granularidade de UI. Garante que rampas sejam consistentes entre
    abas e modos de display.

    Reusada por:
      - _compute_kpis_carga (max(.abs()) pra os KPIs Rampa Máx 1h/3h)
      - Viz 5 da Sessão 4b (histograma de rampas)

    Retorna pd.Series indexada por data_hora (NaN nas N últimas linhas
    por causa do shift). Series vazia se sem dados no período.
    """
    mask = (
        (df_long["submercado"] == code)
        & (df_long["data"] >= pd.Timestamp(data_ini))
        & (df_long["data"] <= pd.Timestamp(data_fim))
    )
    dff = df_long.loc[mask]
    if dff.empty:
        return pd.Series(dtype="float64")

    pivot = dff.pivot_table(
        index="data_hora", columns="fonte", values="mwmed",
        aggfunc="mean",
    ).sort_index()
    # fillna(0) só nessas 3 colunas. Semanticamente: ausência de medição
    # de eólica/solar num instante = contribuição 0 (era pré-renováveis ou
    # gap). Pra carga, ausência é raríssima (val_carga é a métrica primária
    # do dataset) — fillna(0) protege contra NaN propagar pra rampa.
    for col in ("carga", "eolica", "solar"):
        if col not in pivot.columns:
            pivot[col] = 0.0
    pivot[["carga", "eolica", "solar"]] = (
        pivot[["carga", "eolica", "solar"]].fillna(0)
    )

    liq = pivot["carga"] - pivot["eolica"] - pivot["solar"]
    return liq.shift(-janela_h) - liq


def _compute_kpis_carga(df_long, code, data_ini, data_fim):
    """
    5 KPIs da aba Carga (Sessão 4a).

    Retorna dict:
      carga_total_media   (MWmed) mean(val_carga) no período
      carga_liquida_media (MWmed) mean(val_carga - val_gereolica - val_gersolar)
      rampa_max_1h        (MW)    max(|liq(t+1h) - liq(t)|) — pico instantâneo
      rampa_max_1h_ts     (Timestamp) início da janela onde a rampa 1h foi máxima
      rampa_max_3h        (MW)    max(|liq(t+3h) - liq(t)|) — duck-curve clássica
      rampa_max_3h_ts     (Timestamp) início da janela onde a rampa 3h foi máxima
      pct_renov_var       (%)     (mean(eolica) + mean(solar)) / mean(carga) × 100

    Sempre lê dado horário bruto — rampas consistentes independente da
    granularidade de UI selecionada (decisão do plano: "rampa sempre em
    horária"). Cálculo O(N), fast (~80ms pra 15a × 8760h).

    Sem @st.cache_data — recomputo por render é barato, e a key seria
    DataFrame (não-hashable nativo, exigiria hash custom).

    Valores indisponíveis (sem dados, divisão por zero, série toda NaN)
    caem em float('nan') / None graciosamente — UI deve renderizar "—".
    """
    rampa_1h_series = _compute_rampa_series(
        df_long, code, data_ini, data_fim, janela_h=1
    )
    rampa_3h_series = _compute_rampa_series(
        df_long, code, data_ini, data_fim, janela_h=3
    )

    if rampa_1h_series.empty:
        return {
            "carga_total_media":     float("nan"),
            "carga_liquida_media":   float("nan"),
            "pico_carga_total":      float("nan"),
            "pico_carga_total_ts":   None,
            "pico_carga_liquida":    float("nan"),
            "pico_carga_liquida_ts": None,
            "rampa_max_1h":          float("nan"),
            "rampa_max_1h_ts":       None,
            "rampa_max_3h":          float("nan"),
            "rampa_max_3h_ts":       None,
            "pct_renov_var":         float("nan"),
        }

    # Recompõe pivot uma vez pras médias (evita 3º call ao filter+pivot).
    # Custo desta duplicação vs DRY: ~50ms num cenário Diária 12M, aceitável.
    mask = (
        (df_long["submercado"] == code)
        & (df_long["data"] >= pd.Timestamp(data_ini))
        & (df_long["data"] <= pd.Timestamp(data_fim))
    )
    pivot = df_long.loc[mask].pivot_table(
        index="data_hora", columns="fonte", values="mwmed",
        aggfunc="mean",
    ).sort_index()
    for col in ("carga", "eolica", "solar"):
        if col not in pivot.columns:
            pivot[col] = 0.0
    pivot[["carga", "eolica", "solar"]] = (
        pivot[["carga", "eolica", "solar"]].fillna(0)
    )

    carga_mean = pivot["carga"].mean()
    eolica_mean = pivot["eolica"].mean()
    solar_mean = pivot["solar"].mean()
    liq_mean = carga_mean - eolica_mean - solar_mean

    pct_renov = (
        (eolica_mean + solar_mean) / carga_mean * 100
        if carga_mean and carga_mean > 0 else float("nan")
    )

    def _max_abs_with_ts(s):
        s_clean = s.dropna()
        if s_clean.empty:
            return float("nan"), None
        s_abs = s_clean.abs()
        idx = s_abs.idxmax()
        return float(s_abs.loc[idx]), idx

    def _max_with_ts(s):
        """Como _max_abs_with_ts mas sem .abs() — pra picos de carga."""
        s_clean = s.dropna()
        if s_clean.empty:
            return float("nan"), None
        idx = s_clean.idxmax()
        return float(s_clean.loc[idx]), idx

    rampa_1h, ts_1h = _max_abs_with_ts(rampa_1h_series)
    rampa_3h, ts_3h = _max_abs_with_ts(rampa_3h_series)

    # Pico de carga (instantâneo horário): max sobre o pivot, com timestamp.
    serie_liq_horaria = pivot["carga"] - pivot["eolica"] - pivot["solar"]
    pico_total, ts_pico_total = _max_with_ts(pivot["carga"])
    pico_liq,   ts_pico_liq   = _max_with_ts(serie_liq_horaria)

    return {
        "carga_total_media":     carga_mean,
        "carga_liquida_media":   liq_mean,
        "pico_carga_total":      pico_total,
        "pico_carga_total_ts":   ts_pico_total,
        "pico_carga_liquida":    pico_liq,
        "pico_carga_liquida_ts": ts_pico_liq,
        "rampa_max_1h":          rampa_1h,
        "rampa_max_1h_ts":       ts_1h,
        "rampa_max_3h":          rampa_3h,
        "rampa_max_3h_ts":       ts_3h,
        "pct_renov_var":         pct_renov,
    }


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
    if _LOGO_WHITE_B64:
        st.markdown(
            f'<img src="data:image/png;base64,{_LOGO_WHITE_B64}" '
            f'class="sidebar-logo" alt="Bradesco BBI" />',
            unsafe_allow_html=True,
        )
    st.markdown(
        '<div class="sidebar-title">Dashboard Setor Elétrico</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="sidebar-username">{user}</div>',
        unsafe_allow_html=True,
    )

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

        /* Rebranding BBI — logo branco no topo da sidebar */
        [data-testid="stSidebar"] .sidebar-logo {
            display: block;
            width: 85%;
            max-width: 260px;
            height: auto;
            margin: 0.5rem 0 1.2rem 0;
        }

        /* Título da sidebar — Bebas Neue, letter-spacing e font-size
           calibrados pra abrir ar entre as letras condensadas e reduzir
           sensação de "socado". Classe própria evita colisão com a regra
           global de h3 (border-bottom Bauhaus). */
        [data-testid="stSidebar"] .sidebar-title {
            font-family: 'Bebas Neue', 'Inter', sans-serif !important;
            font-size: 1.25rem !important;
            letter-spacing: 0.20em !important;
            color: #F6BD16 !important;
            line-height: 1.15 !important;
            margin: 0.4rem 0 0.4rem 0 !important;
        }

        /* Username — Inter, cor cinza-claro próxima ao st.caption default
           (em tema dark, caption é ~rgba(250,250,250,0.6) ≈ #A0A0A0).
           margin-top empurra Nava pra baixo aproximando do Sair; margin-bottom
           zerado pra colar mais — combina com margin-top: -0.5rem do Sair. */
        [data-testid="stSidebar"] .sidebar-username {
            font-family: 'Inter', sans-serif !important;
            font-size: 1rem !important;
            font-weight: 600 !important;
            color: #A0A0A0 !important;
            margin: 0.8rem 0 0 0 !important;
        }

        /* Cabeçalho da seção de autores — Bebas Neue amarelo. font-size
           1.2rem (vs nomes em 1rem Inter) compensa visualmente o fato de
           Bebas ser condensada e parecer menor que Inter no mesmo tamanho. */
        [data-testid="stSidebar"] .sidebar-authors-label {
            font-family: 'Bebas Neue', 'Inter', sans-serif !important;
            font-size: 1.2rem !important;
            letter-spacing: 0.15em !important;
            color: #F6BD16 !important;
            margin: 0 0 0.15rem 0 !important;
        }

        /* Autores no rodapé — 1 nome por linha, alinhados à esquerda
           (mesmo padding natural do username e do caption). Separação
           visual feita via st.divider() nativo. margin-top zerado pra
           que o gap divider→primeiro-nome iguale o gap divider→botão
           Atualizar. */
        [data-testid="stSidebar"] .sidebar-authors {
            font-family: 'Inter', sans-serif !important;
            font-size: 1rem !important;
            color: #F2F2F2 !important;
            text-align: left !important;
            letter-spacing: 0.04em !important;
            line-height: 1.5 !important;
            margin: 0 0 0.5rem 0 !important;
        }

        /* Cola o botão Sair no username — Streamlit injeta margin no
           element_container do botão, que cria gap visível mesmo com
           .sidebar-username margin-bottom: 0.1rem. Margin-top negativo
           direto no button (via marker data-sair="true" do bloco JS
           abaixo) sobe o botão dentro do container sem alterar o
           container em si. Aplicado SÓ no Sair — Atualizar (data-atualizar)
           segue após divider e tem espaçamento próprio adequado. */
        [data-testid="stSidebar"] .stButton > button[data-sair="true"] {
            margin-top: -0.5rem !important;
        }

        /* Fase Nav.1 — Botões de navegação principal (sidebar) */
        [data-testid="stSidebar"] [class*="st-key-nav_aba_"] button {
            text-align: left !important;
            justify-content: flex-start !important;
            padding-left: 1rem !important;
            font-family: 'Inter', sans-serif !important;
            font-size: 0.95rem !important;
            font-weight: 500 !important;
            border: none !important;
            border-radius: 0 !important;
            margin: 0 !important;
            transition: opacity 0.15s ease !important;
        }
        /* Forçar alinhamento esquerdo no <p>/<div> filho do botão */
        [data-testid="stSidebar"] [class*="st-key-nav_aba_"] button > div,
        [data-testid="stSidebar"] [class*="st-key-nav_aba_"] button > div > p,
        [data-testid="stSidebar"] [class*="st-key-nav_aba_"] button p {
            text-align: left !important;
            width: 100% !important;
            justify-content: flex-start !important;
        }
        /* Inativo: texto cream sobre fundo preto (legível) */
        [data-testid="stSidebar"] [class*="st-key-nav_aba_"] button[kind="secondary"],
        [data-testid="stSidebar"] [class*="st-key-nav_aba_"] button[kind="secondary"] * {
            background: transparent !important;
            color: #F5F1E8 !important;
        }
        /* Hover em inativo: vira amarelo Bauhaus pra indicar selecionável */
        [data-testid="stSidebar"] [class*="st-key-nav_aba_"] button[kind="secondary"]:hover,
        [data-testid="stSidebar"] [class*="st-key-nav_aba_"] button[kind="secondary"]:hover * {
            background: #F6BD16 !important;
            color: #1A1A1A !important;
            opacity: 1 !important;
        }
        /* Forçar alinhamento esquerdo em todos os botões nav (sobrescreve regras do secondary *) */
        [data-testid="stSidebar"] [class*="st-key-nav_aba_"] button[kind="secondary"] *,
        [data-testid="stSidebar"] [class*="st-key-nav_aba_"] button[kind="primary"] * {
            text-align: left !important;
            justify-content: flex-start !important;
        }
        /* Ativo: já tinha primary amarelo - manter */
        [data-testid="stSidebar"] [class*="st-key-nav_aba_"] button[kind="primary"],
        [data-testid="stSidebar"] [class*="st-key-nav_aba_"] button[kind="primary"] * {
            background: #F6BD16 !important;
            color: #1A1A1A !important;
        }
        /* Hover em ativo: levemente mais escuro pra feedback */
        [data-testid="stSidebar"] [class*="st-key-nav_aba_"] button[kind="primary"]:hover {
            opacity: 0.9 !important;
        }
        /* Compacta gap vertical entre botões da navegação */
        [data-testid="stSidebar"] [class*="st-key-nav_aba_"],
        [data-testid="stSidebar"] [data-testid="stElementContainer"][class*="st-key-nav_aba_"] {
            margin-bottom: -1rem !important;
            margin-top: 0 !important;
        }
        /* Padding interno menor pra botões mais compactos */
        [data-testid="stSidebar"] [class*="st-key-nav_aba_"] button {
            padding-top: 0.3rem !important;
            padding-bottom: 0.3rem !important;
        }

        /* Fase Nav.2 — Sub-itens (Eneva/SIN) embaixo de Despacho Termico */
        [data-testid="stSidebar"] [class*="st-key-nav_sub_"] button {
            text-align: left !important;
            justify-content: flex-start !important;
            padding-left: 3rem !important;
            font-family: 'Inter', sans-serif !important;
            font-size: 0.85rem !important;
            font-weight: 400 !important;
            border: none !important;
            border-radius: 0 !important;
            margin: 0 !important;
            transition: opacity 0.15s ease !important;
        }
        /* Forca alinhamento esquerdo nos filhos */
        [data-testid="stSidebar"] [class*="st-key-nav_sub_"] button > div,
        [data-testid="stSidebar"] [class*="st-key-nav_sub_"] button > div > p,
        [data-testid="stSidebar"] [class*="st-key-nav_sub_"] button p {
            text-align: left !important;
            width: 100% !important;
            justify-content: flex-start !important;
        }
        /* Sub-item inativo (secondary): cinza discreto */
        [data-testid="stSidebar"] [class*="st-key-nav_sub_"] button[kind="secondary"],
        [data-testid="stSidebar"] [class*="st-key-nav_sub_"] button[kind="secondary"] * {
            background: transparent !important;
            color: #999999 !important;
        }
        /* Sub-item ativo (primary): cream + caractere │ em amarelo */
        [data-testid="stSidebar"] [class*="st-key-nav_sub_"] button[kind="primary"],
        [data-testid="stSidebar"] [class*="st-key-nav_sub_"] button[kind="primary"] * {
            background: transparent !important;
            color: #F5F1E8 !important;
            font-weight: 400 !important;
        }
        /* Primeira letra (caractere │) em amarelo Bauhaus */
        [data-testid="stSidebar"] [class*="st-key-nav_sub_"] button[kind="primary"] p::first-letter {
            color: #F6BD16 !important;
            font-weight: 700 !important;
        }
        /* Hover em sub-item: amarelo discreto */
        [data-testid="stSidebar"] [class*="st-key-nav_sub_"] button:hover,
        [data-testid="stSidebar"] [class*="st-key-nav_sub_"] button:hover * {
            color: #F6BD16 !important;
            opacity: 1 !important;
        }
        /* Forca alinhamento esquerdo (later rule wins) */
        [data-testid="stSidebar"] [class*="st-key-nav_sub_"] button[kind="secondary"] *,
        [data-testid="stSidebar"] [class*="st-key-nav_sub_"] button[kind="primary"] * {
            text-align: left !important;
            justify-content: flex-start !important;
        }
        /* Compactacao vertical + indentacao do wrapper sub-itens */
        [data-testid="stSidebar"] [class*="st-key-nav_sub_"],
        [data-testid="stSidebar"] [data-testid="stElementContainer"][class*="st-key-nav_sub_"] {
            margin-bottom: -1rem !important;
            margin-top: 0 !important;
            padding-left: 0.8rem !important;
        }
        [data-testid="stSidebar"] [class*="st-key-nav_sub_"] button {
            padding-top: 0.2rem !important;
            padding-bottom: 0.2rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    # Botão Sair
    logout_button(location="sidebar", key="logout_sidebar")

    st.divider()

    # Navegação custom — Fase Nav.1.
    # Substituiu st.radio por loop de st.button pra permitir sub-itens
    # condicionais embaixo de "Despacho Térmico" (Fase Nav.2). Layout
    # vertical, full-width, highlight Bauhaus amarelo no item ativo.
    if "aba_selecionada" not in st.session_state:
        st.session_state["aba_selecionada"] = "PLD"

    abas_principais = [
        "PLD", "Reservatórios", "ENA/Chuva", "Despacho Térmico",
        "Geração", "Carga", "Curtailment", "Modulação",
    ]

    for _aba_opcao in abas_principais:
        _is_active = (st.session_state["aba_selecionada"] == _aba_opcao)
        if st.button(
            _aba_opcao,
            key=f"nav_aba_{_aba_opcao}",
            type="primary" if _is_active else "secondary",
            use_container_width=True,
        ):
            st.session_state["aba_selecionada"] = _aba_opcao
            st.rerun()

        # Sub-itens condicionais embaixo de "Despacho Térmico" (Fase Nav.2)
        if _aba_opcao == "Despacho Térmico" and _is_active:
            # Init termico_subview se ainda nao existir
            if "termico_subview" not in st.session_state:
                st.session_state["termico_subview"] = "Eneva"
            _subviews = [("Eneva", "Eneva"), ("SIN", "Sistema")]
            for _label, _valor in _subviews:
                _is_sub_active = (st.session_state["termico_subview"] == _valor)
                # Indicador ativo: caractere │ amarelo antes do texto (Fase Nav.2)
                _label_display = f"│ {_label}" if _is_sub_active else _label
                if st.button(
                    _label_display,
                    key=f"nav_sub_{_valor}",
                    type="primary" if _is_sub_active else "secondary",
                    use_container_width=True,
                ):
                    st.session_state["termico_subview"] = _valor
                    st.rerun()

        # Sub-itens condicionais embaixo de "Geração" (decisão 5.37 — pendente
        # de doc): SIN (conteúdo histórico inalterado) + Eólica/Solar por Grupo.
        # Keys com prefixo `nav_sub_gen_` casam com o CSS `[class*="st-key-nav_sub_"]`
        # via match por prefixo — sem CSS dedicado.
        if _aba_opcao == "Geração" and _is_active:
            if "geracao_subview" not in st.session_state:
                st.session_state["geracao_subview"] = "SIN"
            _subviews_gen = [
                ("SIN", "SIN"),
                ("Eólica/Solar por Grupo", "Grupo"),
            ]
            for _label, _valor in _subviews_gen:
                _is_sub_active = (
                    st.session_state["geracao_subview"] == _valor
                )
                _label_display = (
                    f"│ {_label}" if _is_sub_active else _label
                )
                if st.button(
                    _label_display,
                    key=f"nav_sub_gen_{_valor}",
                    type="primary" if _is_sub_active else "secondary",
                    use_container_width=True,
                ):
                    st.session_state["geracao_subview"] = _valor
                    st.rerun()

    aba = st.session_state["aba_selecionada"]

    st.divider()
    if st.button("Atualizar", use_container_width=True):
        clear_cache()
        st.rerun()

    st.caption(
        "Dados atualizados automaticamente 1x ao dia."
    )

    # Autores — rodapé da sidebar (1 nome por linha, alinhados à esquerda).
    # Divider nativo cria a separação visual coerente com o resto da sidebar.
    st.divider()
    st.markdown(
        '<div class="sidebar-authors-label">BBI Utilities Team:</div>'
        '<div class="sidebar-authors">'
        'Navarrete<br>Fagundes<br>Caruso'
        '</div>',
        unsafe_allow_html=True,
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
    #
    # Backup paralelo (decisão 5.18) — defesa preventiva: se o
    # widget-state cleanup do Streamlit descartar `granularidade` ao
    # trocar de aba e voltar, o backup restaura. `granularidade` é
    # gerenciada pelo callback do selectbox, não é widget-state direto,
    # mas o pattern é barato e cobre cenários inesperados.
    _PLD_GRAN_BACKUP = "_pld_granularidade_backup"
    if (
        "granularidade" not in st.session_state
        and _PLD_GRAN_BACKUP in st.session_state
    ):
        st.session_state["granularidade"] = st.session_state[_PLD_GRAN_BACKUP]

    st.session_state.setdefault("granularidade", "diario")
    granularidade = st.session_state["granularidade"]
    st.session_state[_PLD_GRAN_BACKUP] = granularidade
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

    # Defaults de período por granularidade (decisão 5.36).
    # Fonte única da verdade — consumido pelo reset block abaixo.
    # Modos:
    #   ("single_day", None) → data_ini = data_fim = max_d (1D)
    #   ("dias", N)          → data_ini = max_d - N dias, data_fim = max_d
    _PLD_DEFAULTS_POR_GRANULARIDADE = {
        "horario": ("single_day", None),
        "diario":  ("dias", 90),
        "mensal":  ("dias", 90),
    }

    def _aplica_default_pld_inline(gran, _min_d, _max_d):
        modo, valor = _PLD_DEFAULTS_POR_GRANULARIDADE[gran]
        if modo == "single_day":
            st.session_state["data_ini"] = _max_d
            st.session_state["data_fim"] = _max_d
        elif modo == "dias":
            st.session_state["data_ini"] = max(
                _min_d, _max_d - timedelta(days=valor)
            )
            st.session_state["data_fim"] = _max_d

    # Defesa contra widget cleanup do data_fim em single-day mode
    # (decisão 5.16 estendida): em horário com 1D ativo, o widget
    # "Data final" não é instanciado e Streamlit descarta
    # state["data_fim"]. Próximo rerun (ex: clique no botão "Último
    # dia" ou troca de granularidade) lê data_fim → KeyError.
    # Restauramos antes do reset block: assume == data_ini (consistente
    # com single-day). Se a granularidade for não-horária, o gatilho
    # `range_degenerado_fora_horario` abaixo vai capturar o estado
    # degenerado e disparar reset full pra default da granularidade.
    if (
        "data_fim" not in st.session_state
        and "data_ini" in st.session_state
    ):
        st.session_state["data_fim"] = st.session_state["data_ini"]

    # Gatilho extra (decisão 5.28): se user estava em horário com 1D
    # ativo (data_ini == data_fim) e troca pra Diário/Mensal, o range
    # degenerado de 1 dia ficaria horrível nessas granularidades.
    # Reset pro default 90d (via helper, decisão 5.36) nesse caso.
    range_degenerado_fora_horario = (
        granularidade != "horario"
        and "data_ini" in st.session_state
        and "data_fim" in st.session_state
        and st.session_state["data_ini"] == st.session_state["data_fim"]
    )

    # Detecta troca pra horário (decisão 5.36 — 5º trigger do reset).
    # Cálculo ANTES do reset block pra que a flag possa ser usada lá.
    # Condição única `gran_anterior != "horario"` cobre 2 casos —
    #   (a) troca real (gran_anterior in {"diario","mensal"})
    #   (b) primeira render da sessão já em horário (gran_anterior is None)
    # Sentinela `_pld_granularidade_anterior` atualizada SEMPRE (não só
    # quando reset dispara) — comportamento mais previsível.
    # Submercados (sel_SE/S/NE/N/media) NÃO são popados — preserva
    # seleção do usuário entre granularidades (princípio de menor
    # surpresa). Default "todos marcados" só vale na 1ª criação dos
    # widgets (value=True nas linhas dos checkboxes).
    _PLD_GRAN_PREV = "_pld_granularidade_anterior"
    gran_anterior = st.session_state.get(_PLD_GRAN_PREV)
    trocou_pra_horario = (
        granularidade == "horario" and gran_anterior != "horario"
    )
    st.session_state[_PLD_GRAN_PREV] = granularidade

    # Reset block — 5 triggers, default por granularidade via helper.
    # Substitui versão antiga que aplicava 90d hardcoded em todos os
    # triggers, ignorando granularidade (causa do bug do Cenário 3).
    if (
        "data_ini" not in st.session_state
        or st.session_state.get("_dataset_max") != max_d
        or st.session_state.get("_dataset_min") != min_d
        or range_degenerado_fora_horario
        or trocou_pra_horario
    ):
        _aplica_default_pld_inline(granularidade, min_d, max_d)
        st.session_state["_dataset_max"] = max_d
        st.session_state["_dataset_min"] = min_d

    # --- Filtrar por data (usando session_state, não widgets) ---
    # Os widgets de Período ficam mais abaixo, mas o filtro precisa
    # acontecer aqui para os KPIs já mostrarem os dados corretos.
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
    # Granularidade horária ganha preset "1D" (decisão 5.28) que ativa
    # modo single-day no helper: 2 date_inputs viram 1 + botão "Último
    # dia". Outras granularidades mantêm presets atuais.
    if granularidade == "horario":
        _render_period_controls(
            presets=[
                ("1D", 0, False),
                ("1S", 7, False),
                ("1M", 30, False),
                ("3M", 90, False),
                ("Máx", None, True),
            ],
            session_key_ini="data_ini",
            session_key_fim="data_fim",
            key_prefix="btn_",
            min_d=min_d,
            max_d=max_d,
            single_day_preset_label="1D",
        )
    else:
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
        mostrar_media = st.checkbox("SIN", value=True, key="sel_media")

    if not submercados_selecionados and not mostrar_media:
        st.info("Selecione ao menos um submercado ou o SIN para visualizar.")
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

        opcoes_ordem = ["horario", "diario", "mensal"]
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

        # =====================================================================
        # KPIs do single-day mode (decisão 5.28).
        # Renderizados ENTRE o título-dropdown e o gráfico — quando
        # granularidade=horário e data_ini==data_fim (1D ativo).
        # 5 cards: PLD médio do dia / Máximo+hora / Mínimo+hora / Spread /
        # vs Média do mês. Submercado escolhido via dropdown auxiliar
        # "Detalhar KPIs:" (default SE).
        # =====================================================================
        single_day_active = (
            granularidade == "horario" and data_ini == data_fim
        )

        if single_day_active:
            st.markdown(
                """
                <style>
                .pld1d-kpi-card {
                    background: #F5F1E8;
                    border: 2px solid #1A1A1A;
                    padding: 16px;
                    border-radius: 0;
                }
                /* Header do card: label à esquerda, meta opcional à
                   direita (ex: horário "18:00" nos cards Máximo/Mínimo).
                   Cards sem meta ficam só com label — espaço à direita
                   permanece vazio sem afetar alinhamento. */
                .pld1d-kpi-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: baseline;
                    gap: 8px;
                }
                .pld1d-kpi-label {
                    font-family: 'Bebas Neue', sans-serif;
                    font-size: 11px;
                    text-transform: uppercase;
                    letter-spacing: 0.08em;
                    color: #1A1A1A;
                    font-weight: 400;
                    line-height: 1.2;
                }
                .pld1d-kpi-meta {
                    font-family: 'Inter', sans-serif;
                    font-size: 11px;
                    font-weight: 500;
                    color: #6B6B6B;
                    white-space: nowrap;
                }
                .pld1d-kpi-value-row {
                    display: flex;
                    align-items: baseline;
                    margin-top: 0.4rem;
                }
                .pld1d-kpi-currency {
                    font-family: 'Inter', sans-serif;
                    font-size: 13px;
                    font-weight: 400;
                    color: #6B6B6B;
                    vertical-align: baseline;
                    margin-right: 4px;
                }
                .pld1d-kpi-amount {
                    font-family: 'Inter', sans-serif;
                    font-size: 22px;
                    font-weight: 600;
                    color: #1A1A1A;
                    vertical-align: baseline;
                    line-height: 1.1;
                }

                /* Dropdown "Submercado dos KPIs" — 1º item da régua de
                   KPIs. Streamlit emite class="st-key-{key}" no
                   element-container do widget — usamos isso pra mirar
                   APENAS este selectbox sem afetar o dropdown global de
                   granularidade do PLD (que já tem CSS próprio em
                   app.py linhas ~1495-1525 fazendo flatten Bauhaus).
                   O wrapper recebe estilo de card (cream + borda +
                   padding); o selectbox interno fica minimalista (sem
                   borda, Inter 14px, chevron empurrado pra direita). */
                .st-key-kpi_submercado_detalhe {
                    background: #F5F1E8;
                    border: 2px solid #1A1A1A;
                    border-radius: 0;
                    padding: 16px;
                    min-height: 76px;
                    display: flex;
                    align-items: center;
                    box-sizing: border-box;
                }
                .st-key-kpi_submercado_detalhe [data-testid="stSelectbox"] {
                    width: 100%;
                }
                .st-key-kpi_submercado_detalhe [data-testid="stSelectbox"]
                [data-baseweb="select"] > div {
                    border: none !important;
                    border-bottom: none !important;
                    background: transparent !important;
                    font-family: 'Inter', sans-serif !important;
                    font-size: 14px !important;
                    font-weight: 600 !important;
                    letter-spacing: 0 !important;
                    color: #1A1A1A !important;
                    width: 100% !important;
                    max-width: 100% !important;
                }
                /* Texto do valor selecionado em Inter 22px 600 — pareia
                   com o número dos KPIs (R$ 302,38) ao lado. BaseWeb
                   aninha o valor em divs internos com font-size/weight
                   próprios, então inheritance da regra acima (font-size
                   14px no > div) não chega ao texto visível — targeting
                   via descendant selector `> div *` pega todos. Não afeta:
                   - Chevron ▾ (pseudo-element ::after do > div, não é
                     descendant — preserva tamanho atual 1.2em × 14px =
                     16.8px).
                   - SVG do BaseWeb (display:none pela regra global linha
                     1514).
                   - Opções do menu aberto (portal separado fora do
                     .st-key-…). */
                .st-key-kpi_submercado_detalhe [data-baseweb="select"]
                > div * {
                    font-size: 22px !important;
                    font-weight: 600 !important;
                    line-height: 1.1 !important;
                    color: #1A1A1A !important;
                }
                .st-key-kpi_submercado_detalhe [data-testid="stSelectbox"]
                [data-baseweb="select"] > div::after {
                    font-size: 1.2em !important;
                    margin-left: auto !important;
                }
                </style>
                """,
                unsafe_allow_html=True,
            )

            def _render_kpi_pld_1d(label, num, meta_right=""):
                """Card KPI do single-day mode. Layout:
                  [LABEL ............... meta_right]   <- header (flex)
                  [R$ XX,XX]                            <- value row

                `num` vem como HTML pronto do `_fmt_pld_1d` (spans
                currency + amount). `meta_right` opcional — usado só
                nos cards MÁXIMO/MÍNIMO pra mostrar o horário do
                pico/vale alinhado à direita do label.
                """
                meta_html = (
                    f'<span class="pld1d-kpi-meta">{meta_right}</span>'
                    if meta_right else ""
                )
                return (
                    f'<div class="pld1d-kpi-card">'
                    f'<div class="pld1d-kpi-header">'
                    f'<span class="pld1d-kpi-label">{label}</span>'
                    f'{meta_html}'
                    f'</div>'
                    f'<div class="pld1d-kpi-value-row">{num}</div>'
                    f'</div>'
                )

            def _fmt_pld_1d(v):
                """Retorna HTML com 'R$' e o número em spans separados —
                hierarquia tipográfica: R$ secundário (Inter 13px cinza),
                número primário (Inter 22px bold preto)."""
                if v is None or pd.isna(v):
                    return "—"
                n = (
                    f"{v:,.2f}"
                    .replace(",", "X").replace(".", ",").replace("X", ".")
                )
                return (
                    f'<span class="pld1d-kpi-currency">R$</span>'
                    f'<span class="pld1d-kpi-amount">{n}</span>'
                )

            # Subtítulo (largura cheia — descreve toda a régua de 5
            # colunas abaixo: dropdown de submercado + 4 KPIs).
            st.markdown(
                f'<div style="font-family:\'Inter\', sans-serif; '
                f'font-size:0.85rem; color:#6B6B6B; font-style:italic; '
                f'margin:0.6rem 0 0.4rem 0;">'
                f'Indicadores do dia '
                f'{data_ini.strftime("%d/%m/%Y")}.'
                f'</div>',
                unsafe_allow_html=True,
            )

            # Régua: dropdown de submercado (col 0) + 4 KPIs (cols 1-4).
            opcoes_sub_kpi = ["SE", "S", "NE", "N", "Média BR"]
            kpi_cols = st.columns(5)
            with kpi_cols[0]:
                sub_kpis = st.selectbox(
                    "Submercado dos KPIs",
                    options=opcoes_sub_kpi,
                    index=0,  # default SE
                    key="kpi_submercado_detalhe",
                    label_visibility="collapsed",
                    format_func=lambda x: "SIN" if x == "Média BR" else x,
                )

            # Série do dia (24 valores) pro submercado escolhido
            if sub_kpis in pivot.columns:
                serie_dia = pivot[sub_kpis].dropna()
            else:
                serie_dia = pd.Series(dtype=float)

            if serie_dia.empty:
                sub_kpis_display = "SIN" if sub_kpis == "Média BR" else sub_kpis
                st.warning(
                    f"Sem dados pro submercado {sub_kpis_display} no dia "
                    f"{data_ini.strftime('%d/%m/%Y')}."
                )
            else:
                pld_medio_dia = serie_dia.mean()
                max_val = serie_dia.max()
                max_ts = serie_dia.idxmax()
                min_val = serie_dia.min()
                min_ts = serie_dia.idxmin()
                spread = max_val - min_val

                with kpi_cols[1]:
                    st.markdown(
                        _render_kpi_pld_1d(
                            "PLD MÉDIO DIA",
                            _fmt_pld_1d(pld_medio_dia),
                        ),
                        unsafe_allow_html=True,
                    )
                with kpi_cols[2]:
                    st.markdown(
                        _render_kpi_pld_1d(
                            "MÁXIMO",
                            _fmt_pld_1d(max_val),
                            meta_right=max_ts.strftime("%H:00"),
                        ),
                        unsafe_allow_html=True,
                    )
                with kpi_cols[3]:
                    st.markdown(
                        _render_kpi_pld_1d(
                            "MÍNIMO",
                            _fmt_pld_1d(min_val),
                            meta_right=min_ts.strftime("%H:00"),
                        ),
                        unsafe_allow_html=True,
                    )
                with kpi_cols[4]:
                    st.markdown(
                        _render_kpi_pld_1d(
                            "SPREAD",
                            _fmt_pld_1d(spread),
                        ),
                        unsafe_allow_html=True,
                    )

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
            sigla_label = col if col != "Média BR" else "SIN"
            # Com fonte monoespaçada, padronizar todas as siglas em 3 chars
            # (SIN ocupa 3; SE/NE ganham 1 espaço, S/N ganham 2 espaços ao
            # final). Garante que "R$" comece na mesma coluna em todas as
            # linhas do hover unified.
            sigla_fix = sigla_label.ljust(3)
            fig.add_trace(
                go.Scatter(
                    x=pivot.index,
                    y=pivot[col],
                    name=("SIN" if col == "Média BR" else col),
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
                # Em horário + single-day (data_ini == data_fim), só
                # `HH:MM` no hover — a data é redundante porque o
                # gráfico mostra 24h de UM dia. Range > 1 dia mantém
                # data + hora pra desambiguar entre dias.
                hoverformat=(
                    "%H:%M"
                    if granularidade == "horario" and data_ini == data_fim
                    else {
                        "horario": "%d/%m/%Y %H:%M",
                        "diario":  "%d/%m/%Y",
                        "mensal":  "%b %Y",
                    }[granularidade]
                ),
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
    # Adiciona Média BR (SIN) no final — variável interna mantém nome
    kpi_items.append(
        f'<span class="kpi-item">'
        f'<span class="kpi-label" style="background:#6B6B6B;">SIN</span>'
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

elif aba == "Despacho Térmico":
    # -----------------------------------------------------------------------
    # Aba Despacho Térmico — Fase C.1 (esqueleto navegável).
    # Sub-views: Sistema (térmico Brasil) + Eneva (portfólio 11 usinas).
    # Backend pronto em data_loaders/data_loader_termico.py (Fase B). Nesta
    # fase, apenas estrutura — sem dados, gráficos ou filtros funcionais.
    # -----------------------------------------------------------------------
    # Init only if absent — preserva a escolha do usuário entre reruns.
    # Deve ser ANTES do título pra que o título dinâmico (Fase E.11) possa
    # ler o state na 1ª visita absoluta.
    if "termico_subview" not in st.session_state:
        st.session_state["termico_subview"] = "Eneva"
    _subview = st.session_state["termico_subview"]

    # Título dinâmico (Fase E.11): muda conforme sub-view ativa.
    # Lag de 1 render no click do pill — no render do click, título mostra
    # valor antigo até o st.rerun() completar (sem flicker perceptível).
    if _subview == "Sistema":
        _titulo_aba = "SIN - Despacho Termelétrico Total"
    else:
        _titulo_aba = "Eneva — Despacho Termelétrico"
    st.markdown(f"# {_titulo_aba}")
    st.markdown(
        '<div style="border-bottom: 2px solid #1A1A1A; '
        'margin: 0 0 -1.5rem 0;"></div>',
        unsafe_allow_html=True,
    )

    # === HOISTED (Fase E) — comum às 2 sub-views ===
    # Loader, imports comuns e helper KPI compartilhados pelas sub-views
    # Sistema e Eneva. Imports específicos da Eneva (USINAS_COBERTURA,
    # usina_em_operacao) ficam dentro do branch dela.
    from data_loaders.data_loader_termico import (
        carregar_termico,
        carregar_termico_horario_dia,
        MOTIVOS_COLS,
    )

    with st.spinner("Carregando dados de despacho térmico…"):
        try:
            df_term = carregar_termico(ano_ini=2022)
        except Exception as e:
            st.error(f"Falha ao carregar dados do ONS: {e}")
            debug = st.session_state.get("_debug_erros", [])
            if debug:
                st.subheader("Detalhes técnicos do erro")
                for d in debug[:20]:
                    st.code(d)
            st.stop()

    if df_term.empty:
        st.warning("Nenhum dado de despacho térmico disponível.")
        st.stop()

    # Helper compartilhado pelas 2 sub-views (Sistema e Eneva).
    # Triple-double-quote pra não precisar escapar aspas simples internas
    # do CSS (decisão da Fase C.2.3).
    def _render_kpi_termico(
        label: str, valor: str, unit: str = "",
        valor_cor: str = BAUHAUS_BLACK,
    ) -> str:
        unit_html = (
            f'<span style="font-family:\'Inter\',sans-serif; '
            f'font-size:0.85rem; font-weight:600; '
            f'color:{BAUHAUS_BLACK}; margin-left:0.4rem;">{unit}</span>'
            if unit else ""
        )
        return f"""
        <div style="background: {BAUHAUS_CREAM};
                    border: 2px solid {BAUHAUS_BLACK};
                    padding: 0.8rem 1rem; min-height: 5rem;
                    display: flex; flex-direction: column;
                    justify-content: center;">
            <div style="font-family: 'Inter', sans-serif;
                        font-size: 0.75rem; text-transform: uppercase;
                        letter-spacing: 0.16em; font-weight: 700;
                        color: {BAUHAUS_BLACK}; margin-bottom: 0.3rem;">
                {label}
            </div>
            <div>
                <span style="font-family: 'Bebas Neue', sans-serif;
                             font-size: 1.45rem; letter-spacing: 0.02em;
                             color: {valor_cor};">
                    {valor}
                </span>{unit_html}
            </div>
        </div>
        """

    # Caption do gráfico — Fase E.17 (helper local, escopo restrito ao
    # bloco térmico). Estrutura: top row com bordas top+bottom (Bebas
    # Neue, sub_label à esquerda + data à direita) + sub-caption italic
    # "Valor {adjetivo} · {unidade}" abaixo. data_html condicional por
    # granularidade: range em Mensal/Diário, data única em Horário,
    # vazio em Trimestral.
    _ADJETIVOS_TERMICO = {
        "Mensal":     "mensal",
        "Diário":     "diário",
        "Horário":    "horário",
        "Trimestral": "trimestral",
    }

    def _render_termico_chart_caption(
        sub_label: str,
        gran_label: str,
        data_ini,
        data_fim,
        unidade_label: str,
        estilo_curtailment: bool = False,
    ) -> None:
        if gran_label == "Trimestral":
            data_html = ""
        elif gran_label == "Horário":
            data_html = data_ini.strftime("%d/%m/%Y")
        else:  # Mensal, Diário
            _sep = " a " if estilo_curtailment else " - "
            data_html = (
                f"{data_ini.strftime('%d/%m/%Y')}{_sep}"
                f"{data_fim.strftime('%d/%m/%Y')}"
            )
        adjetivo = _ADJETIVOS_TERMICO.get(gran_label, gran_label.lower())
        # Header alinhado com pattern aba Carga (Fase H — Item 1):
        # sem border-top, border-bottom 2px, font-size 1.1rem, letter-
        # spacing 0.08em, padding-bottom 3px, margin 2.6rem 0 0.3rem 0.
        # Sub-caption tem 2 estilos: default (italic cinza, padrão SIN)
        # ou estilo Curtailment (Inter 500 preto, sem italic).
        if estilo_curtailment:
            sub_text = f"{gran_label} · {unidade_label}"
            sub_style = (
                "font-family: 'Inter', sans-serif; "
                "font-size: 0.9rem; "
                "color: #1A1A1A; "
                "font-weight: 500; "
                "letter-spacing: 0.04em; "
                "margin: 0 0 0.5rem 0;"
            )
        else:
            sub_text = f"Valor {adjetivo} · {unidade_label}"
            sub_style = (
                "font-family: 'Inter', sans-serif; "
                "font-style: italic; "
                "color: #6B6B6B; "
                "font-size: 0.85rem; "
                "margin: 0.4rem 0 0.3rem 0;"
            )
        st.markdown(
            f'<div style="display: flex; '
            f'justify-content: space-between; '
            f'align-items: baseline; '
            f'font-family: \'Bebas Neue\', sans-serif; '
            f'font-size: 1.1rem; '
            f'letter-spacing: 0.08em; '
            f'color: #1A1A1A; '
            f'margin: 2.6rem 0 0.3rem 0; '
            f'padding-bottom: 3px; '
            f'border-bottom: 2px solid #1A1A1A;">'
            f'<span>{sub_label}</span>'
            f'<span>{data_html}</span>'
            f'</div>'
            f'<div style="{sub_style}">'
            f'{sub_text}'
            f'</div>',
            unsafe_allow_html=True,
        )

    def _filtrar_termico_por_mes(
        df_term: pd.DataFrame,
        mes_ref: pd.Timestamp,
    ) -> pd.DataFrame:
        """Retorna copia de df_term contendo apenas linhas do mes
        especificado.

        Args:
            df_term: DataFrame top-level do loader.
            mes_ref: Timestamp representando QUALQUER dia do mes alvo.
                Comum: mes_ref = Timestamp(ano, mes, 1) ou ts.replace(day=1).

        Returns:
            DataFrame filtrado (copia) com linhas do mes mes_ref.year x
            mes_ref.month.
        """
        mask = (
            (df_term["data"].dt.year == mes_ref.year)
            & (df_term["data"].dt.month == mes_ref.month)
        )
        return df_term[mask].copy()

    def _filtrar_termico_por_dia(
        df_term: pd.DataFrame,
        dia_ref,  # date ou datetime
    ) -> pd.DataFrame:
        """Retorna copia de df_term contendo apenas linhas do dia
        especificado (24 horas).

        Args:
            df_term: DataFrame top-level do loader.
            dia_ref: date ou datetime do dia alvo.

        Returns:
            DataFrame filtrado (copia) com 24 linhas (uma por hora) por
            usina presente nesse dia.
        """
        from datetime import date, datetime
        if isinstance(dia_ref, datetime):
            dia_ref = dia_ref.date()
        mask = df_term["data"].dt.date == dia_ref
        return df_term[mask].copy()

    def _agregar_termico_sistema(
        df_filt: pd.DataFrame,
        modo: str,
        unidade: str,
    ) -> tuple[pd.DataFrame, str, str]:
        """Agrega df_filt (ja filtrado) por modo + aplica conversao de
        unidade. Retorna (agg, sufixo_unidade, fmt_hover).

        Pre-condicao: df_filt nao-vazio (caller responsavel pelo guard).

        Encapsula logica original em app.py:3895-3987 (Fase Drill.1).
        Modos suportados: "Mensal", "Diário", "Horário", "Trimestral".

        Schema do retorno:
        - agg: DataFrame com label + chave-de-bucket por modo +
               7 colunas de motivos (MOTIVOS_COLS) ja com unidade aplicada
        - sufixo_unidade: "MWm" ou "GWh" pro hovertemplate
        - fmt_hover: formato Plotly (",.0f", ",.1f", ",.2f")
        """
        import calendar

        if modo == "Mensal":
            df_filt["ano_mes"] = df_filt["data"].dt.to_period("M").dt.to_timestamp()
            agg = df_filt.groupby("ano_mes")[MOTIVOS_COLS].sum().reset_index()
            agg["label"] = agg["ano_mes"].apply(
                lambda ts: f"{_MESES_BR[ts.month]}/{str(ts.year)[2:]}"
            )
            if unidade == "MWm":
                horas = agg["ano_mes"].apply(
                    lambda ts: calendar.monthrange(ts.year, ts.month)[1] * 24
                )
                for col in MOTIVOS_COLS:
                    agg[col] = agg[col] / horas
                return agg, "MWm", ",.0f"
            else:
                for col in MOTIVOS_COLS:
                    agg[col] = agg[col] / 1000.0
                return agg, "GWh", ",.0f"

        elif modo == "Diário":
            df_filt["dia"] = df_filt["data"].dt.date
            agg = df_filt.groupby("dia")[MOTIVOS_COLS].sum().reset_index()
            agg["label"] = agg["dia"].apply(lambda d: d.strftime("%d/%m"))
            if unidade == "MWm":
                for col in MOTIVOS_COLS:
                    agg[col] = agg[col] / 24.0
                return agg, "MWm", ",.0f"
            else:
                for col in MOTIVOS_COLS:
                    agg[col] = agg[col] / 1000.0
                return agg, "GWh", ",.1f"

        elif modo == "Horário":
            # Cada linha do df_filt ja eh 1 hora — groupby por (data, hora)
            # agrega motivos quando ha multiplas usinas no mesmo instante.
            # label vai como datetime (nao string) pra que xaxis.tickformat
            # /hoverformat controlem eixo curto e tooltip rico.
            agg = (
                df_filt.groupby(["data", "hora"])[MOTIVOS_COLS]
                .sum().reset_index()
            )
            agg["instante"] = (
                agg["data"] + pd.to_timedelta(agg["hora"], unit="h")
            )
            agg["label"] = agg["instante"]
            if unidade == "MWm":
                # Cada linha do agg = 1 hora -> sum direto = MWmedio da hora
                # (denominador implicito = 1h, sem divisao).
                return agg, "MWm", ",.0f"
            else:
                for col in MOTIVOS_COLS:
                    agg[col] = agg[col] / 1000.0
                return agg, "GWh", ",.2f"

        elif modo == "Trimestral":
            df_filt["trimestre"] = df_filt["data"].dt.to_period("Q").dt.to_timestamp()
            agg = df_filt.groupby("trimestre")[MOTIVOS_COLS].sum().reset_index()
            agg["label"] = agg["trimestre"].apply(
                lambda ts: f"{((ts.month - 1) // 3) + 1}T/{str(ts.year)[2:]}"
            )
            # Filtra trims sem dados (Fase H — Item 6 bonus). Trims com
            # sum=0 vem de filter por anos+meses incluindo trims futuros.
            agg = agg[
                agg[MOTIVOS_COLS].sum(axis=1) > 0
            ].reset_index(drop=True)
            if unidade == "MWm":
                def _horas_trim(ts):
                    ano, mes = ts.year, ts.month
                    return sum(
                        calendar.monthrange(ano, m)[1] * 24
                        for m in (mes, mes + 1, mes + 2)
                    )
                horas = agg["trimestre"].apply(_horas_trim)
                for col in MOTIVOS_COLS:
                    agg[col] = agg[col] / horas
                return agg, "MWm", ",.0f"
            else:
                for col in MOTIVOS_COLS:
                    agg[col] = agg[col] / 1000.0
                return agg, "GWh", ",.0f"

        raise ValueError(f"Modo invalido: {modo!r}")

    def _construir_figura_termico_sin(
        agg: pd.DataFrame,
        gran_label: str,
        sufixo_unidade: str,
        fmt_hover: str,
        paleta: dict,
        height: int = 450,
    ) -> "go.Figure":
        """Constroi figura Plotly do grafico SIN (Mensal/Diario/
        Horario/Trimestral). Reusa em mensal e em drill-down (Fase
        Drill.2).

        Encapsula logica original em app.py:4108-4211 (Fase Drill.2.B.0).

        Args:
            agg: DataFrame agregado (saida de _agregar_termico_sistema).
                Schema: label + chave-de-bucket + 7 motivos.
            gran_label: granularidade ("Mensal"/"Diario"/"Horario"/
                "Trimestral"). Em Horario, usa Scatter stackgroup
                (area stackada). Demais usam go.Bar stacked.
            sufixo_unidade: rotulo de unidade pro hovertemplate
                ("MWm"/"GWh").
            fmt_hover: formato Plotly do valor (",.0f"/",.1f"/",.2f").
            paleta: dict {coluna: (cor_hex, label_legenda)}. Chaves
                determinam os motivos plotados (single source of
                truth — nao depende de MOTIVOS_COLS externo).
            height: altura em pixels (default 450).

        Returns:
            go.Figure pronto pra st.plotly_chart.
        """
        motivos = list(paleta.keys())
        fig = go.Figure()

        # Trace Total (Scatter invisivel) ANTES do loop pra ficar no
        # FUNDO do tooltip (decisao Fase C.2.3.1).
        agg_total = agg[motivos].sum(axis=1)
        hovertemplate_total = (
            f'<span style="color:{BAUHAUS_BLACK}; font-weight:700;">'
            f'{"Total".ljust(20).replace(" ", "&nbsp;")}</span>'
            f'&nbsp;&nbsp;'
            f'<span style="color:{BAUHAUS_BLACK}; font-weight:700;">'
            f'%{{y:{fmt_hover}}} {sufixo_unidade}</span>'
            f'<extra></extra>'
        )
        fig.add_trace(go.Scatter(
            x=agg["label"],
            y=agg_total,
            name="Total",
            mode="lines",
            line=dict(color="rgba(0,0,0,0)"),
            hovertemplate=hovertemplate_total,
            showlegend=False,
            hoverlabel=dict(
                bgcolor=BAUHAUS_CREAM,
                bordercolor=BAUHAUS_BLACK,
            ),
        ))

        for col in motivos:
            cor, label = paleta[col]
            label_pad = label.ljust(20).replace(" ", "&nbsp;")
            hovertemplate = (
                f'<span style="color:{cor}; font-weight:700;">{label_pad}</span>'
                f'&nbsp;&nbsp;'
                f'<span style="color:#1A1A1A;">%{{y:{fmt_hover}}} {sufixo_unidade}</span>'
                f'<extra></extra>'
            )
            if gran_label == "Horário":
                # Area stackada (Fase E.15) — mode="none" oculta linha,
                # fillcolor preenche entre traces consecutivos do
                # stackgroup. barmode="stack" do update_layout nao
                # afeta Scatter (so aplica a Bar).
                fig.add_trace(go.Scatter(
                    x=agg["label"],
                    y=agg[col],
                    name=label,
                    stackgroup="motivos",
                    mode="none",
                    fillcolor=cor,
                    hovertemplate=hovertemplate,
                ))
            else:
                fig.add_trace(go.Bar(
                    x=agg["label"],
                    y=agg[col],
                    name=label,
                    marker_color=cor,
                    hovertemplate=hovertemplate,
                ))

        # xaxis_kwargs condicional ao modo (Fase E.14.1):
        # em Horario, x=datetime + tickformat curto + hoverformat rico.
        xaxis_kwargs = dict(
            title=None, showgrid=False, showline=True,
            linewidth=2, linecolor=BAUHAUS_BLACK,
            ticks="outside", tickcolor=BAUHAUS_BLACK,
            tickfont=dict(family="Inter, sans-serif", size=12, color=BAUHAUS_BLACK),
        )
        if gran_label == "Horário":
            xaxis_kwargs["tickformat"] = "%H:00"
            xaxis_kwargs["hoverformat"] = "%d/%m/%Y %H:00"

        fig.update_layout(
            barmode="stack",
            height=height,
            margin=dict(l=40, r=40, t=30, b=60),
            paper_bgcolor=BAUHAUS_CREAM,
            plot_bgcolor=BAUHAUS_CREAM,
            separators=",.",
            hovermode="x unified",
            hoverlabel=dict(
                bgcolor=BAUHAUS_CREAM,
                bordercolor=BAUHAUS_BLACK,
                font=dict(family="'IBM Plex Mono', 'Courier New', monospace", size=12, color=BAUHAUS_BLACK),
            ),
            showlegend=True,
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                bgcolor="rgba(0,0,0,0)",
                font=dict(family="Inter, sans-serif", size=13, color=BAUHAUS_BLACK),
                traceorder="normal",
            ),
            xaxis=xaxis_kwargs,
            yaxis=dict(
                title=None,
                showgrid=True, gridcolor=BAUHAUS_LIGHT, gridwidth=1,
                showline=True, linewidth=2, linecolor=BAUHAUS_BLACK,
                ticks="outside", tickcolor=BAUHAUS_BLACK,
                tickfont=dict(family="Inter, sans-serif", size=12, color=BAUHAUS_BLACK),
                zeroline=False,
                tickformat=",.0f",
            ),
            font=dict(family="Inter, sans-serif", size=12),
        )

        return fig

    if st.session_state["termico_subview"] == "Sistema":
        # === Sub-view Sistema — Fase E ===
        # Caption interno removido na Fase E.11 — título dinâmico no topo
        # do bloco da aba já mostra "SIN - Despacho Termelétrico Total (MWm)".

        # Fix de alinhamento (Fase E.2 / Item 1):
        # CSS global em app.py:359-362 aplica margin-top:-1.5rem em todo
        # st.date_input pra alinhar pela base com botões de preset (cenário
        # das outras abas). No Sistema os date_inputs estão na mesma linha
        # do selectbox (que não tem o offset) — o ajuste global causa
        # desalinhamento de 1.5rem. CSS scoped por nome de key cancela só
        # nos 2 date_inputs do Sistema, sem afetar outras abas.
        st.markdown(
            """
            <style>
            .st-key-termico_sistema_data_ini,
            .st-key-termico_sistema_data_fim,
            [class*="st-key-termico_sistema_data_"] .stDateInput,
            [class*="st-key-termico_sistema_data_"] [data-testid="stDateInput"] {
                margin-top: 0 !important;
            }
            /* Botões de ano em Trimestral: compactos sem quebra de linha.
               [kind] empata especificidade com .stButton button[kind] do
               CSS global. Regras `_btn_t_` removidas na Fase H.7.D ao
               migrar trims pra st.checkbox nativo (decisão 5.48 reaplicada
               após identificar interferência do CSS scoped residual no
               bug do tick branco da H.4 — C1). Espelho da H.7.C aplicada
               no Eneva. */
            [class*="st-key-termico_sistema_btn_ano_"] button[kind] {
                white-space: nowrap !important;
                padding-left: 0.25rem !important;
                padding-right: 0.25rem !important;
                font-size: 0.85rem !important;
                min-width: 0 !important;
            }
            /* Botões de ano "colados" — sobreposição sutil de 1px cria
               aparência de segmento contínuo (Fase H — Item 4).
               border-radius: 0 garante cantos retos. */
            [class*="st-key-termico_sistema_btn_ano_"] button[kind] {
                margin-left: -10px !important;
                border-radius: 0 !important;
            }
            /* Regra `margin-top: -0.5rem` no `_btn_ano_` removida na
               Fase H.4 — B: atacava o wrapper do botão (`.stButton`),
               não o gap entre rows de st.columns. Substituída por
               spacer HTML negativo ANTES do cols_anos no bloco Python
               do Trimestral (mais previsível). */
            </style>
            """,
            unsafe_allow_html=True,
        )

        # Imports específicos do Sistema (lazy)
        import plotly.graph_objects as go
        import calendar
        from datetime import date as _date_sis

        # Sistema usa o df_term completo (todas as usinas, sem filtro Eneva).
        df_sis = df_term

        # Range disponível
        min_d_sis = df_sis["data"].min().date()
        max_d_sis = df_sis["data"].max().date()

        # Init de state
        if "termico_sistema_granularidade" not in st.session_state:
            st.session_state["termico_sistema_granularidade"] = "Mensal"
        # Migração defensiva da Fase E.1 (que removia "Horário" e mapeava
        # estado legado pra "Mensal") foi removida na Fase E.14 — "Horário"
        # voltou às opções do selectbox e o remap silencioso quebrava a
        # seleção pelo usuário.
        if "termico_sistema_unidade" not in st.session_state:
            st.session_state["termico_sistema_unidade"] = "MWm"
        # Trimestres marcados (Fase E.9): list[int] (subset de [1,2,3,4]).
        # [] = modo "ano completo" (4 trims por ano marcado);
        # [T1, T2, ...] = modo "histórico" (trims selecionados cross-anos).
        # Renomeada de termico_sistema_trimestre_comparacao (era int|None) —
        # state legado fica órfão, novo state nasce limpo como list.
        if "termico_sistema_trimestres_marcados" not in st.session_state:
            st.session_state["termico_sistema_trimestres_marcados"] = []
        # Anos selecionados pra comparação (Fase E.4): lista de inteiros.
        # Reset block (Trimestral) sobrescreve com [] na transição.
        if "termico_sistema_anos_comparacao" not in st.session_state:
            st.session_state["termico_sistema_anos_comparacao"] = list(
                range(2022, max_d_sis.year + 1)
            )
        # LTM marcado (Fase E.5): bool separado dos anos pra type-safety.
        # Default 1ª visita Trimestral: True (filter "últimos 12 meses").
        if "termico_sistema_ltm_marcado" not in st.session_state:
            st.session_state["termico_sistema_ltm_marcado"] = False

        # === Drill-down state (Fase Drill.2) ===
        # Mes selecionado pro grafico drill diario (default: ultimo mes)
        if "termico_sistema_drill_mes" not in st.session_state:
            _ultimo_dia = df_sis["data"].max()
            st.session_state["termico_sistema_drill_mes"] = (
                _ultimo_dia.replace(day=1).normalize()
            )
        # Dia selecionado pro grafico drill horario (default: ultimo dia)
        if "termico_sistema_drill_dia" not in st.session_state:
            st.session_state["termico_sistema_drill_dia"] = (
                df_sis["data"].max().date()
            )

        # Linha 1: granularidade (selectbox) + data_inicial + data_final
        # st.columns(...) cria os 4 containers; selectbox e date_inputs são
        # instanciados em momentos diferentes:
        #  - selectbox PRIMEIRO (define gran_atual usado pelo reset block)
        #  - reset block depois (escreve em state)
        #  - date_inputs por ÚLTIMO (leem state pós-reset)
        # Proporção col_g 3.6 = 6 botões × 0.6 (alinha visualmente com a
        # largura dos botões ano colados; Fase H — Item 4b).
        col_g, _spc_g, col_di, col_df = st.columns([3.6, 3.4, 1.5, 1.5])

        with col_g:
            gran_atual = st.selectbox(
                "Granularidade",
                ["Mensal", "Diário", "Horário", "Trimestral"],
                key="termico_sistema_granularidade",
            )

        # Sair de Trimestral limpa trims marcados (Fase E.3 / atualizado E.9).
        # Idempotente: re-aplica em todo render onde gran != Trimestral.
        if gran_atual != "Trimestral":
            st.session_state["termico_sistema_trimestres_marcados"] = []

        # Reset block + transição de granularidade (decisão 5.16/5.20 simplificada)
        prev_gran = st.session_state.get("_termico_sistema_last_gran")
        em_transicao = prev_gran is not None and prev_gran != gran_atual

        # Removido `data_ini not in state` (cond_a) — date_inputs com
        # disabled=True em Trimestral sofrem widget cleanup do Streamlit
        # (decisão 5.16 do CLAUDE.md), causando precisa_reset=True a cada
        # render e sobrescrevendo state via reset block (bug Fase E.5).
        # Sentinelas _dataset_max/_min cobrem o caso "1ª visita" (None ≠
        # date) sem suscetibilidade ao cleanup.
        precisa_reset = (
            st.session_state.get("_termico_sistema_dataset_max") != max_d_sis
            or st.session_state.get("_termico_sistema_dataset_min") != min_d_sis
            or em_transicao
            # Gatilho cleanup + range degenerado (decisão 5.16, Fase E.12
            # adaptada de Geração — corrigida para Despacho Térmico):
            # widget cleanup do Streamlit ao trocar sub-view DELETA keys
            # data_ini/data_fim. Sem fix, st.date_input sem value= recria
            # keys clamped pra max_value (range zero). Detecta ausência
            # da key OR range degenerado, não só comparação >= (que falha
            # quando keys foram cleaned). Excluir Trimestral (dates
            # informativas, filter ignora) e Horário (data_ini == data_fim
            # é design legítimo single-day).
            or (
                gran_atual not in ("Trimestral", "Horário")
                and (
                    "termico_sistema_data_ini" not in st.session_state
                    or "termico_sistema_data_fim" not in st.session_state
                    or st.session_state["termico_sistema_data_ini"]
                        >= st.session_state["termico_sistema_data_fim"]
                )
            )
        )

        if precisa_reset:
            if gran_atual == "Diário":
                # Diário — últimos 30 dias móveis
                st.session_state["termico_sistema_data_ini"] = max(
                    min_d_sis, max_d_sis - timedelta(days=30)
                )
                st.session_state["termico_sistema_data_fim"] = max_d_sis
            elif gran_atual == "Horário":
                # Horário — 1 dia móvel (24 barras) — Fase E.14
                st.session_state["termico_sistema_data_ini"] = max_d_sis
                st.session_state["termico_sistema_data_fim"] = max_d_sis
            elif gran_atual == "Trimestral":
                # Trimestral default (Fase E.5 / atualizado E.9): trims=[],
                # anos=[], LTM=True (modo "ano completo" com janela LTM pura).
                # Filter usa trims+anos+LTM (não data_ini/data_fim) — date_inputs
                # ficam disabled sempre em Trimestral. data_ini/data_fim
                # mantidos como fallback informativo (últimos 12 meses).
                st.session_state["termico_sistema_trimestres_marcados"] = []
                st.session_state["termico_sistema_anos_comparacao"] = []
                st.session_state["termico_sistema_ltm_marcado"] = True
                st.session_state["termico_sistema_data_ini"] = max(
                    min_d_sis, max_d_sis - timedelta(days=365)
                )
                st.session_state["termico_sistema_data_fim"] = max_d_sis
            else:
                # Mensal — default 12M (decisão Q4 reavaliada pra E.1)
                st.session_state["termico_sistema_data_ini"] = max(
                    min_d_sis, max_d_sis - timedelta(days=365)
                )
                st.session_state["termico_sistema_data_fim"] = max_d_sis
            st.session_state["_termico_sistema_dataset_max"] = max_d_sis
            st.session_state["_termico_sistema_dataset_min"] = min_d_sis

        st.session_state["_termico_sistema_last_gran"] = gran_atual

        # Period controls — só botões de preset (date_inputs estão na linha 1
        # junto com o selectbox). Layout muda por granularidade.
        # Trimestral: 4 botões 1T/2T/3T/4T do ano corrente do dataset.
        #   Trimestres futuros (data_ini > max_d_sis) ficam disabled.
        #   Trimestre corrente acumulado até hoje (data_fim = min(d_fim_t, max_d_sis)).
        # Diário: 4 botões 1D/7D/15D/30D (janela móvel ancorada em max_d_sis).
        # Mensal: 5 botões clássicos 1M/3M/6M/12M/Máx.
        if gran_atual == "Trimestral":
            ano_corrente_sis = max_d_sis.year
            trims_marcados = st.session_state["termico_sistema_trimestres_marcados"]

            # Botões toggle de ano + LTM — sempre visíveis em Trimestral
            # (Fase E.5 / atualizado E.9). Comportamento depende do modo:
            #   - "ano_completo" (trims=[]): single-select (anos+LTM mutuamente
            #     exclusivos; não pode ficar tudo vazio → força LTM).
            #   - "historico" (trims!=[]): multi-select (anos+LTM independentes).
            anos_disponiveis = sorted(df_sis["data"].dt.year.unique().tolist())
            anos_marcados = st.session_state["termico_sistema_anos_comparacao"]
            ltm_marcado = st.session_state["termico_sistema_ltm_marcado"]
            modo_trim = "historico" if trims_marcados else "ano_completo"

            # Row 2 envolvida em st.container(key=) pra CSS targeting
            # do gap (Fase H.7.B-bis). Classe `st-key-...row2` no DOM.
            with st.container(key="termico_sistema_trimestral_row2"):
                # Layout 8 cols: [0.1 spacer inicial] + 6 botões (5 anos +
                # LTM, proporção 0.55 cada = 3.3 total) + spacer 6.6.
                # Spacer inicial empurra botões pra direita pra alinhar
                # com selectbox Granularidade acima. Proporção 0.55 (vs
                # 0.5 anterior) compensa gaps internos do st.columns
                # pra LTM terminar visualmente no fim do selectbox
                # Granularidade (calibrado H.8.A).
                # Índices: cols_anos[0]=spacer, [1]=2022 ... [5]=2026,
                # [6]=LTM, [7]=spacer final.
                # Fase E.5 original.
                cols_anos = st.columns([0.1, 0.55, 0.55, 0.55, 0.55, 0.55, 0.55, 6.6])
                for i, ano in enumerate(anos_disponiveis):
                    if i >= 5:
                        break  # defesa: layout suporta até 5 anos
                    ativo_ano = ano in anos_marcados
                    with cols_anos[i + 1]:
                        if st.button(
                            str(ano),
                            use_container_width=True,
                            key=f"termico_sistema_btn_ano_{ano}",
                            type="primary" if ativo_ano else "secondary",
                        ):
                            # Click ano = toggle multi-select (Fase H — Item 6,
                            # reverte parcial decisão 5.40 — single-select foi
                            # removido). Preserva trims; **desliga LTM** ao
                            # marcar ano (Fase H.1 — Ajuste 3: UX prefere
                            # análise focada em anos específicos vs LTM puro).
                            # Quando 1º ano é marcado SEM trims explícitos,
                            # marca todos os 4 trims pra UX coerente (default
                            # = ano cheio). Edge case "tudo desmarcado" abaixo
                            # garante que LTM volte a ativar se anos vazios.
                            if ativo_ano:
                                st.session_state["termico_sistema_anos_comparacao"] = [
                                    a for a in anos_marcados if a != ano
                                ]
                            else:
                                if not trims_marcados:
                                    st.session_state["termico_sistema_trimestres_marcados"] = [1, 2, 3, 4]
                                st.session_state["termico_sistema_anos_comparacao"] = sorted(
                                    anos_marcados + [ano]
                                )
                                st.session_state["termico_sistema_ltm_marcado"] = False
                            st.rerun()

                # Botão LTM — janela móvel "últimos 4 trimestres" (Fase E.8).
                # Comportamento depende do modo (Fase E.9):
                #   - ano_completo: single-select; LTM ativo é no-op (força mantém);
                #     LTM inativo substitui ano selecionado.
                #   - historico: toggle independente.
                with cols_anos[6]:
                    if st.button(
                        "LTM",
                        use_container_width=True,
                        key="termico_sistema_btn_ano_LTM",
                        type="primary" if ltm_marcado else "secondary",
                        help="Últimos 4 trimestres (móveis)",
                    ):
                        if modo_trim == "ano_completo":
                            if ltm_marcado:
                                pass  # no-op (não pode desmarcar tudo)
                            else:
                                # Single-select: substitui ano selecionado
                                st.session_state["termico_sistema_anos_comparacao"] = []
                                st.session_state["termico_sistema_ltm_marcado"] = True
                                st.rerun()
                        else:  # historico — toggle independente
                            st.session_state["termico_sistema_ltm_marcado"] = not ltm_marcado
                            st.rerun()

                # H.7.D: trims migrados pra st.checkbox nativo (key prefix
                # `_chk_t_`). Visual herdado do filter grayscale global
                # (preto + tick branco). Lógica idêntica à H.7.C do Eneva
                # (arquitetura render-todos → coleta → decide), com
                # substituição eneva → sistema. Variável de state:
                # `termico_sistema_trimestres_marcados` (note: "trimestres",
                # não "trims" — herança histórica do nome no SIN).
                #
                # UX preservada (decisão 5.40 + ativo_visual):
                # - LTM puro (trims=[]): 4 checkboxes aparecem MARCADOS
                #   visualmente, mas filter ignora e usa só anos+LTM.
                # - Click pra desmarcar 1 trim em LTM puro → entra em
                #   modo histórico com os 3 restantes + todos anos.
                # - Click em modo histórico → toggle multi-select normal.
                # - Desmarcar último trim → força LTM puro.
                #
                # Reset session_state em transições: Streamlit "prende"
                # estado interno do checkbox após primeiro click, ignorando
                # `value=`. `del` antes de `st.rerun()` força re-render
                # respeitar value novo.
                presets_t = [(1, "1T"), (2, "2T"), (3, "3T"), (4, "4T")]
                cols_p = st.columns([1, 1, 1, 1, 6])

                # Snapshot pré-render
                trims_anteriores_real = list(trims_marcados)
                em_ltm_puro_antes = not trims_anteriores_real

                # Render checkboxes + coleta estado pós-render
                estado_visual_pos = []
                for i, (num, label) in enumerate(presets_t):
                    ativo_real = num in trims_marcados
                    ativo_visual = ativo_real or em_ltm_puro_antes
                    with cols_p[i]:
                        marcado = st.checkbox(
                            label,
                            value=ativo_visual,
                            key=f"termico_sistema_chk_t_{label}",
                        )
                        estado_visual_pos.append(marcado)

                # Calcula trims_real_pos baseado no contexto
                if em_ltm_puro_antes:
                    if all(estado_visual_pos):
                        # Permanece LTM puro
                        trims_real_pos = []
                    else:
                        # Transição LTM puro → histórico
                        trims_real_pos = [
                            num for (num, _), m in zip(presets_t, estado_visual_pos) if m
                        ]
                else:
                    # Em histórico: estado visual = estado real
                    trims_real_pos = [
                        num for (num, _), m in zip(presets_t, estado_visual_pos) if m
                    ]

                # Detecta mudança e aplica transições da decisão 5.40
                if trims_real_pos != trims_anteriores_real:
                    if em_ltm_puro_antes and trims_real_pos:
                        # LTM puro → histórico: marca TODOS anos
                        st.session_state["termico_sistema_trimestres_marcados"] = trims_real_pos
                        st.session_state["termico_sistema_anos_comparacao"] = sorted(anos_disponiveis)
                        # Reset state dos checkboxes pra próxima render
                        # respeitar value= novo (não preserva ativo_visual)
                        for _, lbl in presets_t:
                            key_chk = f"termico_sistema_chk_t_{lbl}"
                            if key_chk in st.session_state:
                                del st.session_state[key_chk]
                        st.rerun()
                    elif trims_anteriores_real and not trims_real_pos:
                        # Histórico → ano_completo: limpa anos, força LTM puro
                        st.session_state["termico_sistema_trimestres_marcados"] = []
                        st.session_state["termico_sistema_anos_comparacao"] = []
                        st.session_state["termico_sistema_ltm_marcado"] = True
                        # Reset state dos checkboxes pra próxima render
                        # mostrar todos marcados (LTM puro = ativo_visual=True)
                        for _, lbl in presets_t:
                            key_chk = f"termico_sistema_chk_t_{lbl}"
                            if key_chk in st.session_state:
                                del st.session_state[key_chk]
                        st.rerun()
                    else:
                        # Multi-select dentro de histórico (sem transição de modo)
                        st.session_state["termico_sistema_trimestres_marcados"] = sorted(trims_real_pos)
                        st.rerun()

                # Edge case "tudo desmarcado" (Fase E.5): nem anos individuais
                # nem LTM — reset automático pro default LTM. Garante que sempre
                # exista pelo menos uma fonte temporal ativa.
                if (
                    not st.session_state["termico_sistema_anos_comparacao"]
                    and not st.session_state["termico_sistema_ltm_marcado"]
                ):
                    st.session_state["termico_sistema_trimestres_marcados"] = []
                    st.session_state["termico_sistema_anos_comparacao"] = []
                    st.session_state["termico_sistema_ltm_marcado"] = True
                    st.rerun()

        elif gran_atual == "Diário":
            # Diário — presets removidos (Fase E.7). Período controlado
            # exclusivamente via date_inputs (default 30 dias móveis vem
            # do reset block; validação >30 dias é aplicada antes da
            # filtragem mais abaixo).
            pass

        elif gran_atual == "Horário":
            # Horário — sem presets (Fase E.14). Período via date_inputs
            # (default 1 dia móvel pelo reset block; validação >15 dias
            # aplicada antes da filtragem).
            pass

        else:
            # Mensal — presets reduzidos a 12M / Máx (Fase E.7).
            # Date_inputs habilitados pra range customizado.
            # .get() com default seguro contra widget cleanup do Streamlit
            # (decisão 5.16; fix Fase E.12). Default = Mensal 12M.
            data_ini_atual = st.session_state.get(
                "termico_sistema_data_ini",
                max(min_d_sis, max_d_sis - timedelta(days=365)),
            )
            data_fim_atual = st.session_state.get(
                "termico_sistema_data_fim", max_d_sis
            )
            preset_atual = None
            if data_fim_atual == max_d_sis:
                if (max_d_sis - data_ini_atual).days == 365:
                    preset_atual = "12M"
                elif data_ini_atual == min_d_sis:
                    preset_atual = "Máx"

            # Row 2 envolvida em st.container(key=) pra CSS targeting
            # do gap (Fase H.7.B-bis). Classe `st-key-...row2` no DOM.
            with st.container(key="termico_sistema_mensal_row2"):
                cols_p = st.columns([1, 1, 8])
                presets_sis = [
                    ("12M", 365, False),
                    ("Máx", None, True),
                ]
                for i, (label, delta, is_max) in enumerate(presets_sis):
                    with cols_p[i]:
                        tipo = "primary" if label == preset_atual else "secondary"
                        if st.button(
                            label,
                            use_container_width=True,
                            key=f"termico_sistema_btn_p_{label}",
                            type=tipo,
                        ):
                            if is_max:
                                st.session_state["termico_sistema_data_ini"] = min_d_sis
                            else:
                                st.session_state["termico_sistema_data_ini"] = max(
                                    min_d_sis, max_d_sis - timedelta(days=delta)
                                )
                            st.session_state["termico_sistema_data_fim"] = max_d_sis
                            st.rerun()

        # Date_inputs instanciados APÓS os period controls (Solução A da Fase
        # E.3.1). Pattern do _render_period_controls global: state escrito
        # pelos presets ANTES do widget com mesma key ser instanciado, evita
        # StreamlitAPIException. Containers col_di/col_df foram criados na
        # linha 1 (junto com selectbox via st.columns) — visual final mantém
        # date_inputs lá, só a ordem temporal de instanciação muda.
        # Em Trimestral (Fase E.16): filter sempre usa anos+LTM (não datas),
        # então date_inputs nem renderizam — col_di/col_df ficam vazios.
        # Em Horário (Fase E.15): single-day picker — 1 date_input "Data" em
        # col_di; col_df fica vazio. data_fim sincroniza com data_ini pra que
        # filtragem (data >= data_ini & data <= data_fim) pegue exatamente
        # 1 dia (24 horas). Escrita em data_fim é OK porque o widget de
        # data_fim NÃO é instanciado em Horário (key não está bound).
        if gran_atual == "Horário":
            with col_di:
                st.date_input(
                    "Data",
                    min_value=min_d_sis, max_value=max_d_sis,
                    key="termico_sistema_data_ini",
                    format="DD/MM/YYYY",
                )
            st.session_state["termico_sistema_data_fim"] = (
                st.session_state["termico_sistema_data_ini"]
            )
        elif gran_atual == "Trimestral":
            # Date_inputs não renderizam em Trimestral (Fase E.16) — filter
            # usa trims+anos+LTM. col_di/col_df ficam vazios.
            pass
        else:
            # Mensal/Diário — 2 date_inputs habilitados.
            with col_di:
                st.date_input(
                    "Data inicial",
                    min_value=min_d_sis, max_value=max_d_sis,
                    key="termico_sistema_data_ini",
                    format="DD/MM/YYYY",
                )
            with col_df:
                st.date_input(
                    "Data final",
                    min_value=min_d_sis, max_value=max_d_sis,
                    key="termico_sistema_data_fim",
                    format="DD/MM/YYYY",
                )

        # Caption "Histórico em cache" movida pra footnote pós-gráfico
        # (Fase H.2 — Ajuste 4). Ver bloco abaixo de st.plotly_chart.

        # Toggle MWm/GWh removido na Fase E.6 — Sistema fixo em MWm.
        # Branches GWh da agregação permanecem como dead code (não removidos
        # pra minimizar risco; nunca executam com unidade_sis hardcoded).
        unidade_sis = "MWm"
        # .get() com default seguro contra widget cleanup do Streamlit
        # (decisão 5.16; fix Fase E.12). Default = Mensal 12M.
        data_ini_sis = st.session_state.get(
            "termico_sistema_data_ini",
            max(min_d_sis, max_d_sis - timedelta(days=365)),
        )
        data_fim_sis = st.session_state.get(
            "termico_sistema_data_fim", max_d_sis
        )

        # Validação
        if data_ini_sis > data_fim_sis:
            st.error("Data inicial maior que data final.")
            st.stop()

        # Validação Diário — período máximo 30 dias (Fase E.7).
        if (
            gran_atual == "Diário"
            and (data_fim_sis - data_ini_sis).days > 30
        ):
            st.error(
                "Período máximo no Diário é 30 dias. Selecione um "
                "intervalo menor ou troque a granularidade."
            )
            st.stop()

        # Validação Horário >15 dias removida (Fase E.15) — single-day
        # picker garante data_ini = data_fim (0 dias).

        # Filtragem — Fase E.5/E.9: Trimestral sempre usa anos+LTM como fonte
        # temporal (não data_ini/data_fim). Modo "histórico" (trims_filt != [])
        # adiciona filtro por meses dos trimestres marcados. Modo "ano completo"
        # (trims_filt == []) usa só fonte temporal. Outras granularidades usam
        # datas explícitas como antes.
        trims_filt = st.session_state.get("termico_sistema_trimestres_marcados", [])
        anos_filt = st.session_state.get("termico_sistema_anos_comparacao", [])
        ltm_filt = st.session_state.get("termico_sistema_ltm_marcado", False)

        if gran_atual == "Trimestral":
            # Mask "fonte temporal" = anos individuais OR janela LTM (OR lógico).
            if anos_filt:
                mask_anos = df_sis["data"].dt.year.isin(anos_filt)
            else:
                mask_anos = pd.Series(False, index=df_sis.index)
            if ltm_filt:
                # LTM = trim corrente + 3 anteriores = 4 barras (Fase E.8).
                # Recuo de 9 meses do início do trim corrente cobre exatos 4 trims.
                _mes_inicial_corrente = ((max_d_sis.month - 1) // 3) * 3 + 1
                _mes_cutoff_offset = _mes_inicial_corrente - 9
                if _mes_cutoff_offset <= 0:
                    _ano_ltm = max_d_sis.year - 1
                    _mes_ltm = _mes_cutoff_offset + 12
                else:
                    _ano_ltm = max_d_sis.year
                    _mes_ltm = _mes_cutoff_offset
                ltm_cutoff = _date_sis(_ano_ltm, _mes_ltm, 1)
                mask_ltm = df_sis["data"].dt.date >= ltm_cutoff
            else:
                mask_ltm = pd.Series(False, index=df_sis.index)
            mask_temporal = mask_anos | mask_ltm

            if trims_filt:
                # Histórico: filtra por meses dos trimestres marcados AND fonte temporal.
                meses_trim = []
                for trim_num in trims_filt:
                    meses_trim.extend([
                        3 * (trim_num - 1) + 1,
                        3 * (trim_num - 1) + 2,
                        3 * (trim_num - 1) + 3,
                    ])
                mask_periodo_sis = (
                    df_sis["data"].dt.month.isin(meses_trim) & mask_temporal
                )
            else:
                # Ano completo: todos os trims dentro da fonte temporal.
                mask_periodo_sis = mask_temporal
        else:
            mask_periodo_sis = (
                (df_sis["data"].dt.date >= data_ini_sis)
                & (df_sis["data"].dt.date <= data_fim_sis)
            )
        df_filt_sis = df_sis[mask_periodo_sis].copy()

        # Modo Horario top-level (decisao 5.46): single-day picker.
        # OVERRIDE df_filt_sis com dados HORARIOS via lazy loader (Fase 4
        # dual-loader). df_sis (daily-aggregated post-Fase 2) nao tem mais
        # coluna 'hora', entao o filter acima entrega DataFrame sem ela —
        # carregar_termico_horario_dia retorna schema 14 cols incluindo 'hora'.
        if gran_atual == "Horário":
            _dia_normalizado_sis = (
                data_ini_sis
                if isinstance(data_ini_sis, _date_sis)
                else data_ini_sis.date()
            )
            df_filt_sis = carregar_termico_horario_dia(_dia_normalizado_sis)

        # Paleta de motivos (cor + label PT-BR)
        PALETA_MOTIVOS_SIS = {
            "val_verifinflexibilidade":    ("#D62828", "Inflexibilidade"),
            "val_verifordemmerito":        ("#1D3557", "Ordem de mérito"),
            "val_verifunitcommitment":     ("#F6BD16", "Unit commitment"),
            "val_verifexportacao":         ("#6B6B6B", "Exportação"),
            "val_verifgsub":               ("#A8A8A8", "GSUB"),
            "val_verifrazaoeletrica":      ("#4A4A4A", "Razão elétrica"),
            "val_verifgarantiaenergetica": ("#1A1A1A", "Garantia energética"),
        }

        # Agregação por granularidade — extraída pra _agregar_termico_sistema
        # na Fase Drill.1 (helper top do bloco térmico, ~linha 3308).
        # Produz agg_sis + sufixo_unidade_sis + fmt_hover_sis pra ambos:
        #   - KPIs (TOTAL = soma das barras visíveis via agg_sis)
        #   - Gráfico (reusa agg_sis sem recalcular)
        if df_filt_sis.empty:
            agg_sis = None
            sufixo_unidade_sis = unidade_sis
            fmt_hover_sis = ",.0f"
        else:
            agg_sis, sufixo_unidade_sis, fmt_hover_sis = _agregar_termico_sistema(
                df_filt=df_filt_sis,
                modo=gran_atual,
                unidade=unidade_sis,
            )

        # KPIs removidos na Fase E.6 — gráfico fala por si.
        # PALETA_MOTIVOS_SIS continua usada pelo gráfico (mantida acima).

        # Gráfico — agg_sis pré-calculado antes do bloco do gráfico.
        if df_filt_sis.empty:
            st.warning(
                f"Nenhum dado disponível no período "
                f"{data_ini_sis.strftime('%d/%m/%Y')} → "
                f"{data_fim_sis.strftime('%d/%m/%Y')}."
            )
        else:
            # Guard "Sem despacho" — agg vazio ou sum total = 0
            # (Fase H — Item 2). Decisão 5.24: st.info + st.stop bloqueia
            # caption + gráfico quando não há nada pra mostrar. df_filt_sis
            # NÃO está vazio aqui (else do empty acima), mas a soma dos
            # motivos pode ser zero (despacho zerado mesmo com dados).
            if agg_sis.empty or agg_sis[MOTIVOS_COLS].sum().sum() == 0:
                if gran_atual == "Horário":
                    msg_sd_sis = (
                        f"Sem despacho em {data_ini_sis.strftime('%d/%m/%Y')}."
                    )
                elif gran_atual == "Trimestral":
                    msg_sd_sis = "Sem despacho no período selecionado."
                else:
                    msg_sd_sis = (
                        f"Sem despacho no período "
                        f"{data_ini_sis.strftime('%d/%m/%Y')} → "
                        f"{data_fim_sis.strftime('%d/%m/%Y')}."
                    )
                st.info(msg_sd_sis)
                st.stop()

            # Caption do gráfico — Fase E.17 (helper top do bloco térmico).
            # Sistema sempre passa "MWmed" como rótulo de unidade
            # (granularidade variável; data_html depende de gran_atual).
            # Title estilo Curtailment: SIN · DESPACHO TERMELÉTRICO TOTAL
            # uppercase. Sub-caption muda pra Inter 500 preto (sem italic).
            _sub_label_sin = "SIN · DESPACHO TERMELÉTRICO TOTAL"
            _render_termico_chart_caption(
                sub_label=_sub_label_sin,
                gran_label=gran_atual,
                data_ini=data_ini_sis,
                data_fim=data_fim_sis,
                unidade_label="MWmed",
                estilo_curtailment=True,
            )

            # Construir figura — extraida pra _construir_figura_termico_sin
            # na Fase Drill.2.B.0 (helper top do bloco termico, ~linha 3455).
            fig_sis = _construir_figura_termico_sin(
                agg=agg_sis,
                gran_label=gran_atual,
                sufixo_unidade=sufixo_unidade_sis,
                fmt_hover=fmt_hover_sis,
                paleta=PALETA_MOTIVOS_SIS,
                height=550,
            )

            _event_mensal = plotly_events(
                fig_sis,
                click_event=True,
                select_event=False,
                hover_event=False,
                key="termico_sistema_chart_mensal",
                override_height=550,
            )

            # Handler do click (Fase Drill.2.C.1, via streamlit-plotly-events)
            # _event_mensal eh list[dict]; cada dict tem keys CamelCase
            # (curveNumber, pointNumber, x, y).
            if _event_mensal and gran_atual == "Mensal":
                _point = _event_mensal[0]
                _idx = _point.get("pointNumber")
                if _idx is not None and 0 <= _idx < len(agg_sis):
                    _novo_mes = agg_sis.iloc[_idx]["ano_mes"]
                    if hasattr(_novo_mes, "normalize"):
                        _novo_mes = _novo_mes.normalize()
                    _atual_mes = st.session_state.get(
                        "termico_sistema_drill_mes"
                    )
                    if _novo_mes != _atual_mes:
                        import calendar as _cal
                        from datetime import date as _date
                        _last_day = _cal.monthrange(
                            _novo_mes.year, _novo_mes.month
                        )[1]
                        _novo_dia = _date(
                            _novo_mes.year, _novo_mes.month, _last_day
                        )
                        st.session_state["termico_sistema_drill_mes"] = _novo_mes
                        st.session_state["termico_sistema_drill_dia"] = _novo_dia
                        st.rerun()

            # === Drill-down (Fase Drill.2.B) ===
            # Aparece apenas em modo Mensal: 2 graficos lado-a-lado
            # mostrando Diario do mes selecionado e Horario do dia
            # selecionado. Sem clique ainda — defaults via state
            # (termico_sistema_drill_mes/dia) inicializados em
            # Drill.2.A.
            if gran_atual == "Mensal":
                _drill_mes = st.session_state["termico_sistema_drill_mes"]
                _drill_dia = st.session_state["termico_sistema_drill_dia"]

                # Filtros isolados (nao usam mask_periodo_sis):
                _df_drill_diario = _filtrar_termico_por_mes(df_term, _drill_mes)
                # Drill Horario usa loader hourly lazy (carrega APENAS 1 dia,
                # ~250KB). Decisao: trocar fonte em vez de filtrar do df_term
                # agregado (que nao tem mais granularidade horaria post-Fase 2).
                from datetime import date as _date_drill
                _dia_normalizado = (
                    _drill_dia
                    if isinstance(_drill_dia, _date_drill)
                    else _drill_dia.date()
                )
                _df_drill_horario = carregar_termico_horario_dia(_dia_normalizado)

                _col_drill_dia, _col_drill_hora = st.columns(2)

                # === Drill DIARIO (esquerda) ===
                with _col_drill_dia:
                    if _df_drill_diario.empty:
                        st.info(
                            f"Sem dados para {_drill_mes.strftime('%m/%Y')}."
                        )
                    else:
                        _agg_dia, _suf_dia, _fmt_dia = _agregar_termico_sistema(
                            df_filt=_df_drill_diario,
                            modo="Diário",
                            unidade=unidade_sis,
                        )
                        _mes_label = (
                            f"{_MESES_BR[_drill_mes.month]}/"
                            f"{str(_drill_mes.year)[2:]}"
                        ).upper()
                        # primeiro e ultimo dia do mes pra range no caption
                        import calendar as _cal
                        _last_day = _cal.monthrange(
                            _drill_mes.year, _drill_mes.month
                        )[1]
                        from datetime import date as _date
                        _data_ini_dia = _date(
                            _drill_mes.year, _drill_mes.month, 1
                        )
                        _data_fim_dia = _date(
                            _drill_mes.year, _drill_mes.month, _last_day
                        )
                        # Caption customizado: tudo centralizado,
                        # sem sub-caption (Drill.2.D polish).
                        _data_ini_str = _data_ini_dia.strftime("%d/%m/%Y")
                        _data_fim_str = _data_fim_dia.strftime("%d/%m/%Y")
                        _caption_dia = (
                            f"DIÁRIO · {_mes_label} · "
                            f"{_data_ini_str} a {_data_fim_str}"
                        )
                        st.markdown(
                            f'''
                            <div style="
                                text-align: center;
                                font-family: 'Bebas Neue', sans-serif;
                                font-size: 1.1rem;
                                font-weight: 600;
                                letter-spacing: 0.04em;
                                color: #1A1A1A;
                                padding: 0.5rem 0;
                                border-bottom: 2px solid #1A1A1A;
                                margin-bottom: 0.5rem;
                            ">{_caption_dia}</div>
                            ''',
                            unsafe_allow_html=True,
                        )
                        _fig_dia = _construir_figura_termico_sin(
                            agg=_agg_dia,
                            gran_label="Diário",
                            sufixo_unidade=_suf_dia,
                            fmt_hover=_fmt_dia,
                            paleta=PALETA_MOTIVOS_SIS,
                            height=450,
                        )
                        _event_diario = plotly_events(
                            _fig_dia,
                            click_event=True,
                            select_event=False,
                            hover_event=False,
                            key="termico_sistema_chart_drill_diario",
                            override_height=450,
                        )

                        # Handler do click no drill diario (Fase Drill.2.C.2):
                        # captura point_number, identifica dia em _agg_dia,
                        # atualiza state. Sem cascata (drill_mes nao muda).
                        # Loop infinito protegido: so re-set state se valor mudou.
                        if _event_diario and gran_atual == "Mensal":
                            _point_d = _event_diario[0]
                            _idx_d = _point_d.get("pointNumber")
                            if _idx_d is not None and 0 <= _idx_d < len(_agg_dia):
                                _novo_dia = _agg_dia.iloc[_idx_d]["dia"]
                                _atual_dia = st.session_state.get(
                                    "termico_sistema_drill_dia"
                                )
                                if _novo_dia != _atual_dia:
                                    st.session_state["termico_sistema_drill_dia"] = _novo_dia
                                    st.rerun()

                # === Drill HORARIO (direita) ===
                with _col_drill_hora:
                    if _df_drill_horario.empty:
                        st.info(
                            f"Sem dados para {_drill_dia.strftime('%d/%m/%Y')}."
                        )
                    else:
                        _agg_hora, _suf_hora, _fmt_hora = _agregar_termico_sistema(
                            df_filt=_df_drill_horario,
                            modo="Horário",
                            unidade=unidade_sis,
                        )
                        _dia_label = _drill_dia.strftime("%d/%m/%Y")
                        # Caption customizado: tudo centralizado,
                        # single-day (sem range duplicado).
                        _caption_hora = f"HORÁRIO · {_dia_label}"
                        st.markdown(
                            f'''
                            <div style="
                                text-align: center;
                                font-family: 'Bebas Neue', sans-serif;
                                font-size: 1.1rem;
                                font-weight: 600;
                                letter-spacing: 0.04em;
                                color: #1A1A1A;
                                padding: 0.5rem 0;
                                border-bottom: 2px solid #1A1A1A;
                                margin-bottom: 0.5rem;
                            ">{_caption_hora}</div>
                            ''',
                            unsafe_allow_html=True,
                        )
                        _fig_hora = _construir_figura_termico_sin(
                            agg=_agg_hora,
                            gran_label="Horário",
                            sufixo_unidade=_suf_hora,
                            fmt_hover=_fmt_hora,
                            paleta=PALETA_MOTIVOS_SIS,
                            height=450,
                        )
                        st.plotly_chart(
                            _fig_hora,
                            use_container_width=True,
                            config={"displaylogo": False},
                        )

        # Caption "Histórico em cache" — footnote pós-gráfico (Fase H.2 —
        # Ajuste 4). Indentado 8 espaços (nível subview Sistema), FORA
        # do else do empty pra sempre renderizar (mesmo quando gráfico
        # foi suprimido por warning/info).
        st.markdown(
            f'<div style="font-family:\'Inter\', sans-serif; '
            f'font-size:0.85rem; color:#6B6B6B; font-style:italic; '
            f'margin:1rem 0 0 0;">'
            f'Histórico em cache: desde {min_d_sis.strftime("%d/%m/%Y")}.'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        # === Sub-view Eneva — Fase C.2.1 ===
        # Caption interno removido na Fase E.11 — título dinâmico no topo
        # do bloco da aba já mostra "Eneva — Despacho Termelétrico (GWh)".

        # Fix de alinhamento (Fase D.1.1):
        # Replica do CSS scoped do Sistema (linhas 3161-3170) — cancela
        # margin-top:-1.5rem global (app.py:359-362) pros date_inputs
        # da Eneva, que ficam na mesma linha do selectbox de granularidade
        # (não abaixo dos presets como nas outras abas). Scope via key
        # prefix garante zero impacto em outras sub-views/abas.
        st.markdown(
            """
            <style>
            .st-key-termico_eneva_data_ini,
            .st-key-termico_eneva_data_fim,
            [class*="st-key-termico_eneva_data_"] .stDateInput,
            [class*="st-key-termico_eneva_data_"] [data-testid="stDateInput"] {
                margin-top: 0 !important;
            }
            /* Botões de ano em Trimestral: compactos sem quebra de linha.
               [kind] empata especificidade com .stButton button[kind] do
               CSS global. Regras `_btn_t_` removidas na Fase H.7.C ao
               migrar trims pra st.checkbox nativo (decisão 5.48 reaplicada
               após identificar interferência do CSS scoped residual no
               bug do tick branco da H.4 — C1). */
            [class*="st-key-termico_eneva_btn_ano_"] button[kind] {
                white-space: nowrap !important;
                padding-left: 0.25rem !important;
                padding-right: 0.25rem !important;
                font-size: 0.85rem !important;
                min-width: 0 !important;
            }
            /* Botões de ano "colados" — sobreposição sutil de 1px cria
               aparência de segmento contínuo (Fase H — Item 4).
               border-radius: 0 garante cantos retos. */
            [class*="st-key-termico_eneva_btn_ano_"] button[kind] {
                margin-left: -10px !important;
                border-radius: 0 !important;
            }
            /* Regra `margin-top: -0.5rem` no `_btn_ano_` removida na
               Fase H.4 — B: atacava o wrapper do botão (`.stButton`),
               não o gap entre rows de st.columns. Substituída por
               margin-top negativo no spacer-label da H2.E (mais
               previsível e mantém compensação de altura do col_meio). */
            /* Regra `[..._btn_p_] { margin-top }` removida na Fase
               H.6 — C.4: atacava o wrapper interno do botão, não o
               `gap` do stVerticalBlock parent. Substituída por spacer
               HTML negativo ANTES do cols_p no bloco Python do Mensal
               (consistência com Sistema, mesma mecânica do Trimestral). */
            </style>
            """,
            unsafe_allow_html=True,
        )

        # Imports específicos da Eneva (carregar_termico já hoistado).
        from data_loaders.data_loader_termico import (
            USINAS_COBERTURA, usina_em_operacao,
        )

        # Filtrar só linhas Eneva pra esta sub-view
        df_eneva = df_term[df_term["usina_eneva"].notna()].copy()
        if df_eneva.empty:
            st.warning("Nenhum dado de usinas Eneva no período carregado.")
            st.stop()

        # Init de granularidade (Layout C — Fase D.1).
        # Default Mensal preserva comportamento histórico da Eneva.
        if "termico_eneva_granularidade" not in st.session_state:
            st.session_state["termico_eneva_granularidade"] = "Mensal"

        # Init de state Trimestral (Fase D.2 — replicado do Sistema).
        # Anos disponíveis: 2022..ano_corrente do dataset (mesma janela
        # do Sistema). Reset block do Trimestral força anos=[] / ltm=True
        # na transição (modo "ano completo + LTM puro" como default UX).
        if "termico_eneva_anos_comparacao" not in st.session_state:
            st.session_state["termico_eneva_anos_comparacao"] = list(
                range(2022, df_eneva["data"].max().year + 1)
            )
        # Trimestres marcados (decisão 5.39): list[int] subset de [1,2,3,4].
        # [] = modo "ano completo"; [T1, T2, ...] = modo "histórico".
        if "termico_eneva_trims_marcados" not in st.session_state:
            st.session_state["termico_eneva_trims_marcados"] = []
        # LTM marcado (decisão 5.38): bool separado dos anos pra type-safety.
        # Default 1ª visita (não-Trimestral): False; reset block do Trimestral
        # promove pra True na transição (Fase D.2 default).
        if "termico_eneva_ltm_marcado" not in st.session_state:
            st.session_state["termico_eneva_ltm_marcado"] = False

        min_d = df_eneva["data"].min().date()
        max_d = df_eneva["data"].max().date()

        # Spacer pra evitar overlap entre pills (Eneva|SIN) e date_inputs.
        # CSS global aplica margin-top: -1.5rem nos date_inputs pra alinhar
        # pela base com presets — não cancela em Despacho Térmico onde pills
        # ficam entre o título e o helper. Fase E.13. Reduzido pra 0.8rem
        # na Fase H — Item 7, depois pra 0.3rem na Fase H.3 — Ajuste 1
        # (cola mais perto das pills; o CSS scoped V3 da D.1.1 zera margin-
        # top dos dates da Eneva, então 0.3rem basta pra folga visual).
        st.markdown(
            '<div style="margin-top: 0.3rem;"></div>',
            unsafe_allow_html=True,
        )

        # === Layout C linha 1: granularidade + Usina/Toggle + dates ===
        # selectbox em col_g; Usina + Toggle dentro do col_meio (que era
        # spacer vazio até a Fase H.1 — Ajuste 1); date_inputs em
        # col_di/col_df renderizados condicionalmente APÓS os presets.
        # Proporções alinhadas com Sistema pra paridade visual.
        # col_g 3.6 = 6 botões × 0.6 (alinha selectbox com largura dos
        # botões ano colados; Fase H — Item 4b).
        col_g, col_meio, col_di, col_df = st.columns([3.6, 3.4, 1.5, 1.5])

        with col_g:
            gran_atual = st.selectbox(
                "Granularidade",
                ["Mensal", "Diário", "Horário", "Trimestral"],
                key="termico_eneva_granularidade",
            )

        # Init de Usina + Unidade (state defaults). Fora do `with col_meio`
        # pra que valores estejam disponíveis se o widget não renderizar
        # nesse render (defensivo).
        USINAS_TODAS = ["Consolidado"] + list(USINAS_COBERTURA.keys())  # 12 itens
        if "termico_eneva_usina" not in st.session_state:
            st.session_state["termico_eneva_usina"] = "Consolidado"
        # Garantir valor válido (caso USINAS_COBERTURA mude).
        if st.session_state["termico_eneva_usina"] not in USINAS_TODAS:
            st.session_state["termico_eneva_usina"] = "Consolidado"
        if "termico_eneva_unidade" not in st.session_state:
            st.session_state["termico_eneva_unidade"] = "GWh"

        # Usina + Toggle empilhados verticalmente dentro do col_meio
        # (Fase H.1 — Ajuste 1). Toggle usa cols internas [1, 1] pra
        # MWm/GWh side-by-side dentro do col_meio estreito.
        with col_meio:
            # Wrapper interno [1.5, 7, 1.5] (Fase H.2 — Ajuste B):
            # centraliza Usina + Toggle em 70% da largura do col_meio,
            # com spacers de 15% em cada lado. Toggle herda automaticamente
            # a mesma largura via cols [1, 1] aninhadas dentro do wrapper.
            _spc_l, col_usina_inner, _spc_r = st.columns([1.5, 7, 1.5])
            with col_usina_inner:
                usina_sel = st.selectbox(
                    "Usina",
                    USINAS_TODAS,
                    key="termico_eneva_usina",
                )
                # Toggle MWM/GWH na row 1 — renderizado APENAS em
                # Diário/Horário/Trimestral (Fase H.8.A). Em Mensal,
                # toggle vai pra row 2 ao lado de 12M/Máx (alinha
                # melhor visualmente). Em Trimestral, fica aqui
                # temporariamente até H.8.B mover pra sub-linha dos
                # anos. Keys idênticas às do Edit 2 — branches mutuamente
                # exclusivos via `if gran_atual` garantem que só uma
                # render acontece por vez.
                if gran_atual in ["Diário", "Horário", "Trimestral"]:
                    _unid = st.session_state["termico_eneva_unidade"]
                    col_mwm, col_gwh = st.columns([1, 1])
                    with col_mwm:
                        if st.button(
                            "MWM",
                            key="termico_eneva_btn_mwm",
                            type="primary" if _unid == "MWm" else "secondary",
                            use_container_width=True,
                        ):
                            st.session_state["termico_eneva_unidade"] = "MWm"
                            st.rerun()
                    with col_gwh:
                        if st.button(
                            "GWH",
                            key="termico_eneva_btn_gwh",
                            type="primary" if _unid == "GWh" else "secondary",
                            use_container_width=True,
                        ):
                            st.session_state["termico_eneva_unidade"] = "GWh"
                            st.rerun()
        unidade = st.session_state["termico_eneva_unidade"]

        # Reset block (decisão 5.16/5.20 — Layout C, Fase D.1).
        # Sem `data_ini not in state` (cond_a) pra evitar bug Fase E.5
        # análogo ao Sistema: date_inputs sofrem widget cleanup do
        # Streamlit em Trimestral, causando precisa_reset=True a cada
        # render. Sentinelas _dataset_max/_min cobrem 1ª visita.
        prev_gran = st.session_state.get("_termico_eneva_last_gran")
        em_transicao = prev_gran is not None and prev_gran != gran_atual

        precisa_reset = (
            st.session_state.get("_termico_eneva_dataset_max") != max_d
            or st.session_state.get("_termico_eneva_dataset_min") != min_d
            or em_transicao
            # Gatilho cleanup + range degenerado (decisão 5.16, Fase E.12
            # adaptada de Geração — corrigida para Despacho Térmico):
            # widget cleanup do Streamlit ao trocar sub-view DELETA keys
            # data_ini/data_fim. Sem fix, st.date_input sem value= recria
            # keys clamped pra max_value (range zero). Detecta ausência
            # da key OR range degenerado, não só comparação >= (que falha
            # quando keys foram cleaned). Excluir Trimestral (dates
            # informativas, filter ignora) e Horário (data_ini == data_fim
            # é design legítimo single-day).
            or (
                gran_atual not in ("Trimestral", "Horário")
                and (
                    "termico_eneva_data_ini" not in st.session_state
                    or "termico_eneva_data_fim" not in st.session_state
                    or st.session_state["termico_eneva_data_ini"]
                        >= st.session_state["termico_eneva_data_fim"]
                )
            )
        )

        if precisa_reset:
            if gran_atual == "Diário":
                # Diário — últimos 30 dias móveis
                st.session_state["termico_eneva_data_ini"] = max(
                    min_d, max_d - timedelta(days=30)
                )
                st.session_state["termico_eneva_data_fim"] = max_d
            elif gran_atual == "Horário":
                # Horário — 1 dia móvel (single-day picker, decisão 5.46)
                st.session_state["termico_eneva_data_ini"] = max_d
                st.session_state["termico_eneva_data_fim"] = max_d
            elif gran_atual == "Trimestral":
                # Trimestral default (Fase D.2 — replicado do Sistema):
                # trims=[], anos=[], ltm=True — modo "ano completo" com
                # janela LTM pura. Filter usa anos+LTM+trims (não dates).
                # data_ini/data_fim mantidos como fallback informativo
                # (últimos 12 meses — caption pode reusar).
                st.session_state["termico_eneva_trims_marcados"] = []
                st.session_state["termico_eneva_anos_comparacao"] = []
                st.session_state["termico_eneva_ltm_marcado"] = True
                st.session_state["termico_eneva_data_ini"] = max(
                    min_d, max_d - timedelta(days=365)
                )
                st.session_state["termico_eneva_data_fim"] = max_d
            else:
                # Mensal — default 12M
                st.session_state["termico_eneva_data_ini"] = max(
                    min_d, max_d - timedelta(days=365)
                )
                st.session_state["termico_eneva_data_fim"] = max_d
            st.session_state["_termico_eneva_dataset_max"] = max_d
            st.session_state["_termico_eneva_dataset_min"] = min_d

        st.session_state["_termico_eneva_last_gran"] = gran_atual

        # Period controls condicionais por granularidade (Fase D.1/D.2).
        # Mensal: 2 presets (12M/Máx) — alinhado com Sistema.
        # Diário: pass — período via date_inputs (default 30d móveis).
        # Horário: pass — single-day picker em col_di abaixo.
        # Trimestral: botões ano (5) + LTM + trims (1T..4T) com lógica
        #   contextual single↔multi-select (decisão 5.40).
        if gran_atual == "Mensal":
            data_ini_atual = st.session_state.get(
                "termico_eneva_data_ini",
                max(min_d, max_d - timedelta(days=365)),
            )
            data_fim_atual = st.session_state.get(
                "termico_eneva_data_fim", max_d
            )
            preset_atual = None
            if data_fim_atual == max_d:
                if (max_d - data_ini_atual).days == 365:
                    preset_atual = "12M"
                elif data_ini_atual == min_d:
                    preset_atual = "Máx"

            # Row 2 envolvida em st.container(key=) pra CSS targeting
            # do gap (Fase H.7.B-bis). Classe `st-key-...row2` no DOM.
            with st.container(key="termico_eneva_mensal_row2"):
                # Proporções [0.6, 0.6, 2.9, 1.155, 1.155, 3.59] alinham
                # com row 1 do Eneva [3.6, 3.4, 1.5, 1.5] (total 10):
                # - cols_p[0:2] (0.6+0.6=1.2): 12M/Máx ocupam 0-12%
                #   (compactos no início do col_g)
                # - cols_p[2] (2.9): spacer1 cobre 12-41%
                # - cols_p[3:5] (1.155+1.155=2.31): MWM/GWH ocupam 41-64.1%
                #   (calibrado iterativamente via medição JS:
                #    1.2 → diff dir -10px (transbordo)
                #    1.18 → diff dir -5px
                #    1.155 → diff dir ≈ 0px (alinhamento exato com
                #    selectbox Usina acima))
                # - cols_p[5] (3.59): spacer2 cobre 64.1-100%
                cols_p = st.columns([0.6, 0.6, 2.9, 1.155, 1.155, 3.59])
                presets_mensal = [
                    ("12M", 365, False),
                    ("Máx", None, True),
                ]
                for i, (label, delta, is_max) in enumerate(presets_mensal):
                    with cols_p[i]:
                        tipo = "primary" if label == preset_atual else "secondary"
                        if st.button(
                            label,
                            use_container_width=True,
                            key=f"termico_eneva_btn_p_{label}",
                            type=tipo,
                        ):
                            if is_max:
                                st.session_state["termico_eneva_data_ini"] = min_d
                            else:
                                st.session_state["termico_eneva_data_ini"] = max(
                                    min_d, max_d - timedelta(days=delta)
                                )
                            st.session_state["termico_eneva_data_fim"] = max_d
                            st.rerun()

                # Toggle MWM/GWH na row 2 (Fase H.8.A) — embaixo do
                # selectbox Usina, alinhado com 12M/Máx. Mesmos handlers
                # do toggle original (col_meio). Keys idênticas — branches
                # mutuamente exclusivos via `if gran_atual` no col_meio
                # garantem que só uma render acontece por vez.
                _unid = st.session_state["termico_eneva_unidade"]
                with cols_p[3]:
                    if st.button(
                        "MWM",
                        key="termico_eneva_btn_mwm",
                        type="primary" if _unid == "MWm" else "secondary",
                        use_container_width=True,
                    ):
                        st.session_state["termico_eneva_unidade"] = "MWm"
                        st.rerun()
                with cols_p[4]:
                    if st.button(
                        "GWH",
                        key="termico_eneva_btn_gwh",
                        type="primary" if _unid == "GWh" else "secondary",
                        use_container_width=True,
                    ):
                        st.session_state["termico_eneva_unidade"] = "GWh"
                        st.rerun()
        elif gran_atual == "Trimestral":
            # Botões ano + LTM + trims (decisão 5.40 — interface temporal
            # contextual single↔multi-select). Replica do Sistema linhas
            # 3344-3475 com prefix termico_eneva_*.
            anos_disponiveis = sorted(df_eneva["data"].dt.year.unique().tolist())
            anos_marcados = st.session_state["termico_eneva_anos_comparacao"]
            ltm_marcado = st.session_state["termico_eneva_ltm_marcado"]
            trims_marcados = st.session_state["termico_eneva_trims_marcados"]
            modo_trim = "historico" if trims_marcados else "ano_completo"

            # Row 2 envolvida em st.container(key=) pra CSS targeting
            # do gap (Fase H.7.B-bis). Classe `st-key-...row2` no DOM.
            with st.container(key="termico_eneva_trimestral_row2"):
                # Layout 8 cols: [0.1 spacer inicial] + 6 botões (5 anos +
                # LTM, proporção 0.55 cada = 3.3 total) + spacer 6.6.
                # Spacer inicial empurra botões pra direita pra alinhar
                # com selectbox Granularidade acima. Proporção 0.55 (vs
                # 0.5 anterior) compensa gaps internos do st.columns
                # pra LTM terminar visualmente no fim do selectbox
                # Granularidade (calibrado H.8.A).
                # Índices: cols_anos[0]=spacer, [1]=2022 ... [5]=2026,
                # [6]=LTM, [7]=spacer final.
                cols_anos = st.columns([0.1, 0.55, 0.55, 0.55, 0.55, 0.55, 0.55, 6.6])
                for i, ano in enumerate(anos_disponiveis):
                    if i >= 5:
                        break  # defesa: layout suporta até 5 anos
                    ativo_ano = ano in anos_marcados
                    with cols_anos[i + 1]:
                        if st.button(
                            str(ano),
                            use_container_width=True,
                            key=f"termico_eneva_btn_ano_{ano}",
                            type="primary" if ativo_ano else "secondary",
                        ):
                            # Click ano = toggle multi-select (Fase H — Item 6,
                            # reverte parcial decisão 5.40 — single-select foi
                            # removido). Preserva trims; **desliga LTM** ao
                            # marcar ano (Fase H.1 — Ajuste 3: UX prefere
                            # análise focada em anos específicos vs LTM puro).
                            # Quando 1º ano é marcado SEM trims explícitos,
                            # marca todos os 4 trims pra UX coerente (default
                            # = ano cheio). Edge case "tudo desmarcado" abaixo
                            # garante que LTM volte a ativar se anos vazios.
                            if ativo_ano:
                                st.session_state["termico_eneva_anos_comparacao"] = [
                                    a for a in anos_marcados if a != ano
                                ]
                            else:
                                if not trims_marcados:
                                    st.session_state["termico_eneva_trims_marcados"] = [1, 2, 3, 4]
                                st.session_state["termico_eneva_anos_comparacao"] = sorted(
                                    anos_marcados + [ano]
                                )
                                st.session_state["termico_eneva_ltm_marcado"] = False
                            st.rerun()

                # Botão LTM — janela móvel "últimos 4 trimestres" (decisão 5.38).
                # Comportamento depende do modo (decisão 5.40):
                #   - ano_completo: single-select; LTM ativo é no-op (força mantém);
                #     LTM inativo substitui ano selecionado.
                #   - historico: toggle independente.
                with cols_anos[6]:
                    if st.button(
                        "LTM",
                        use_container_width=True,
                        key="termico_eneva_btn_ano_LTM",
                        type="primary" if ltm_marcado else "secondary",
                        help="Últimos 4 trimestres (móveis)",
                    ):
                        if modo_trim == "ano_completo":
                            if ltm_marcado:
                                pass  # no-op (não pode desmarcar tudo)
                            else:
                                # Single-select: substitui ano selecionado
                                st.session_state["termico_eneva_anos_comparacao"] = []
                                st.session_state["termico_eneva_ltm_marcado"] = True
                                st.rerun()
                        else:  # historico — toggle independente
                            st.session_state["termico_eneva_ltm_marcado"] = not ltm_marcado
                            st.rerun()

                # Trims 1T/2T/3T/4T como st.checkbox nativo (Fase H.7.C).
                # Visual herdado do CSS global (filter grayscale →
                # quadradinho preto + tick branco). Restaura decisão 5.48
                # Refinamento H.1, revertida pela H.4 — C1 e agora
                # aplicada de novo após identificar causa raiz: CSS
                # scoped residual `_btn_t_` interferia. Limpeza CSS no
                # Edit 2 desta fase.
                #
                # UX preservada (decisão 5.40 + ativo_visual):
                # - LTM puro (trims=[]): 4 checkboxes aparecem MARCADOS
                #   visualmente, mas filter ignora e usa só anos+LTM.
                # - Click pra desmarcar 1 trim em LTM puro → entra em
                #   modo histórico com os 3 restantes + todos anos.
                # - Click em modo histórico → toggle multi-select normal.
                # - Desmarcar último trim → força LTM puro.
                #
                # Reset session_state em transições: Streamlit "prende"
                # estado interno do checkbox após primeiro click, ignorando
                # `value=`. `del` antes de `st.rerun()` força re-render
                # respeitar value novo.
                presets_t = [(1, "1T"), (2, "2T"), (3, "3T"), (4, "4T")]
                cols_p = st.columns([1, 1, 1, 1, 6])

                # Snapshot pré-render
                trims_anteriores_real = list(trims_marcados)
                em_ltm_puro_antes = not trims_anteriores_real

                # Render checkboxes + coleta estado pós-render
                estado_visual_pos = []
                for i, (num, label) in enumerate(presets_t):
                    ativo_real = num in trims_marcados
                    ativo_visual = ativo_real or em_ltm_puro_antes
                    with cols_p[i]:
                        marcado = st.checkbox(
                            label,
                            value=ativo_visual,
                            key=f"termico_eneva_chk_t_{label}",
                        )
                        estado_visual_pos.append(marcado)

                # Calcula trims_real_pos baseado no contexto
                if em_ltm_puro_antes:
                    if all(estado_visual_pos):
                        # Permanece LTM puro
                        trims_real_pos = []
                    else:
                        # Transição LTM puro → histórico
                        trims_real_pos = [
                            num for (num, _), m in zip(presets_t, estado_visual_pos) if m
                        ]
                else:
                    # Em histórico: estado visual = estado real
                    trims_real_pos = [
                        num for (num, _), m in zip(presets_t, estado_visual_pos) if m
                    ]

                # Detecta mudança e aplica transições da decisão 5.40
                if trims_real_pos != trims_anteriores_real:
                    if em_ltm_puro_antes and trims_real_pos:
                        # LTM puro → histórico: marca TODOS anos
                        st.session_state["termico_eneva_trims_marcados"] = trims_real_pos
                        st.session_state["termico_eneva_anos_comparacao"] = sorted(anos_disponiveis)
                        # Reset state dos checkboxes pra próxima render
                        # respeitar value= novo (não preserva ativo_visual)
                        for _, lbl in presets_t:
                            key_chk = f"termico_eneva_chk_t_{lbl}"
                            if key_chk in st.session_state:
                                del st.session_state[key_chk]
                        st.rerun()
                    elif trims_anteriores_real and not trims_real_pos:
                        # Histórico → ano_completo: limpa anos, força LTM puro
                        st.session_state["termico_eneva_trims_marcados"] = []
                        st.session_state["termico_eneva_anos_comparacao"] = []
                        st.session_state["termico_eneva_ltm_marcado"] = True
                        # Reset state dos checkboxes pra próxima render
                        # mostrar todos marcados (LTM puro = ativo_visual=True)
                        for _, lbl in presets_t:
                            key_chk = f"termico_eneva_chk_t_{lbl}"
                            if key_chk in st.session_state:
                                del st.session_state[key_chk]
                        st.rerun()
                    else:
                        # Multi-select dentro de histórico (sem transição de modo)
                        st.session_state["termico_eneva_trims_marcados"] = sorted(trims_real_pos)
                        st.rerun()

                # Edge case "tudo desmarcado" (refinamento decisão 5.20): nem
                # anos individuais nem LTM — reset automático pro default LTM
                # puro. Garante que sempre exista pelo menos uma fonte temporal
                # ativa.
                if (
                    not st.session_state["termico_eneva_anos_comparacao"]
                    and not st.session_state["termico_eneva_ltm_marcado"]
                ):
                    st.session_state["termico_eneva_trims_marcados"] = []
                    st.session_state["termico_eneva_anos_comparacao"] = []
                    st.session_state["termico_eneva_ltm_marcado"] = True
                    st.rerun()
        # Diário/Horário: sem presets (período via date_inputs).

        # Date_inputs condicionais (col_di/col_df reusados — pattern Sistema).
        # Horário: 1 date_input "Data" em col_di (single-day, decisão 5.46);
        #   data_fim sincroniza com data_ini pra filter pegar 24h.
        # Trimestral: nada (filter por anos/LTM em D.2).
        # Mensal/Diário: 2 date_inputs habilitados.
        if gran_atual == "Horário":
            with col_di:
                st.date_input(
                    "Data",
                    min_value=min_d, max_value=max_d,
                    key="termico_eneva_data_ini",
                    format="DD/MM/YYYY",
                )
            st.session_state["termico_eneva_data_fim"] = (
                st.session_state["termico_eneva_data_ini"]
            )
        elif gran_atual == "Trimestral":
            # Date_inputs não renderizam em Trimestral (D.2 vai ter ano/LTM).
            pass
        else:
            # Mensal/Diário — 2 date_inputs habilitados.
            with col_di:
                st.date_input(
                    "Data inicial",
                    min_value=min_d, max_value=max_d,
                    key="termico_eneva_data_ini",
                    format="DD/MM/YYYY",
                )
            with col_df:
                st.date_input(
                    "Data final",
                    min_value=min_d, max_value=max_d,
                    key="termico_eneva_data_fim",
                    format="DD/MM/YYYY",
                )

        # Caption "Histórico em cache" movida pra footnote pós-gráfico
        # (Fase H.2 — Ajuste 4). Ver bloco abaixo de st.plotly_chart.

        # Usina + Toggle MWm/GWh: movidos pro col_meio da linha 1
        # (Fase H.1 — Ajuste 1). Variáveis usina_sel e unidade já estão
        # definidas no escopo desde o `with col_meio:` acima.

        # Leituras defensivas (.get com default) — decisão 5.16 + Fase E.12.
        # Cobrem widget cleanup do Streamlit em transições entre layouts
        # (ex: voltar pra Mensal de Trimestral onde dates não renderizam).
        data_ini = st.session_state.get(
            "termico_eneva_data_ini",
            max(min_d, max_d - timedelta(days=365)),
        )
        data_fim = st.session_state.get("termico_eneva_data_fim", max_d)

        # Validação básica
        if data_ini > data_fim:
            st.error("Data inicial maior que data final.")
            st.stop()

        # Validação Diário — período máximo 30 dias (Fase E.7 / Layout C).
        if (
            gran_atual == "Diário"
            and (data_fim - data_ini).days > 30
        ):
            st.error(
                "Período máximo no Diário é 30 dias. Selecione um "
                "intervalo menor ou troque a granularidade."
            )
            st.stop()

        # Imports lazy + filtro compartilhado entre KPIs (descontinuados
        # na Fase E.6) e gráfico. `date` adicionado em D.2 pro cutoff LTM.
        import plotly.graph_objects as go
        import calendar
        from datetime import date
        from data_loaders.data_loader_termico import MOTIVOS_COLS

        # Filtro: período + usina. Em Trimestral, fonte temporal é
        # anos+LTM+trims (decisão 5.40 — interface contextual) — NÃO
        # data_ini/data_fim. Outras granularidades usam datas explícitas
        # como antes. Replica do filter do Sistema (linhas 3625-3672).
        if gran_atual == "Trimestral":
            trims_filt = st.session_state.get("termico_eneva_trims_marcados", [])
            anos_filt = st.session_state.get("termico_eneva_anos_comparacao", [])
            ltm_filt = st.session_state.get("termico_eneva_ltm_marcado", False)

            # Mask "fonte temporal" = anos individuais OR janela LTM (OR lógico).
            if anos_filt:
                mask_anos = df_eneva["data"].dt.year.isin(anos_filt)
            else:
                mask_anos = pd.Series(False, index=df_eneva.index)
            if ltm_filt:
                # LTM = trim corrente + 3 anteriores = 4 barras (decisão 5.38).
                # Recuo de 9 meses do início do trim corrente cobre exatos 4 trims.
                _mes_inicial_corrente = ((max_d.month - 1) // 3) * 3 + 1
                _mes_cutoff_offset = _mes_inicial_corrente - 9
                if _mes_cutoff_offset <= 0:
                    _ano_ltm = max_d.year - 1
                    _mes_ltm = _mes_cutoff_offset + 12
                else:
                    _ano_ltm = max_d.year
                    _mes_ltm = _mes_cutoff_offset
                ltm_cutoff = date(_ano_ltm, _mes_ltm, 1)
                mask_ltm = df_eneva["data"].dt.date >= ltm_cutoff
            else:
                mask_ltm = pd.Series(False, index=df_eneva.index)
            mask_temporal = mask_anos | mask_ltm

            if trims_filt:
                # Histórico: filtra por meses dos trimestres marcados AND fonte.
                meses_trim = []
                for trim_num in trims_filt:
                    meses_trim.extend([
                        3 * (trim_num - 1) + 1,
                        3 * (trim_num - 1) + 2,
                        3 * (trim_num - 1) + 3,
                    ])
                mask_periodo = (
                    df_eneva["data"].dt.month.isin(meses_trim) & mask_temporal
                )
            else:
                # Ano completo: todos os trims dentro da fonte temporal.
                mask_periodo = mask_temporal
        else:
            mask_periodo = (
                (df_eneva["data"].dt.date >= data_ini)
                & (df_eneva["data"].dt.date <= data_fim)
            )

        if usina_sel == "Consolidado":
            df_filt = df_eneva[mask_periodo].copy()
        else:
            df_filt = df_eneva[mask_periodo & (df_eneva["usina_eneva"] == usina_sel)].copy()

        # Modo Horario top-level Eneva (decisao 5.46): single-day picker.
        # OVERRIDE df_filt com dados HORARIOS via lazy loader (Fase 4 dual-loader).
        # Diferenca vs Sistema (Edit C): carrega dataset horario completo do
        # dia, depois aplica filtro de usina_eneva (notna pra Consolidado,
        # == usina_sel pra single-plant). 'date' ja importado linha 5101.
        if gran_atual == "Horário":
            _dia_normalizado_eneva = (
                data_ini
                if isinstance(data_ini, date)
                else data_ini.date()
            )
            df_horario_full = carregar_termico_horario_dia(_dia_normalizado_eneva)
            if not df_horario_full.empty:
                df_horario_eneva = df_horario_full[
                    df_horario_full["usina_eneva"].notna()
                ].copy()
                if usina_sel == "Consolidado":
                    df_filt = df_horario_eneva
                else:
                    df_filt = df_horario_eneva[
                        df_horario_eneva["usina_eneva"] == usina_sel
                    ].copy()
            else:
                df_filt = df_horario_full  # vazio, guard downstream pega

        # Paleta de motivos (cor + label PT-BR) — usada nos KPIs e no gráfico.
        PALETA_MOTIVOS_KPI = {
            "val_verifinflexibilidade":    ("#D62828", "Inflexibilidade"),
            "val_verifordemmerito":        ("#1D3557", "Ordem de mérito"),
            "val_verifunitcommitment":     ("#F6BD16", "Unit commitment"),
            "val_verifexportacao":         ("#6B6B6B", "Exportação"),
            "val_verifgsub":               ("#A8A8A8", "GSUB"),
            "val_verifrazaoeletrica":      ("#4A4A4A", "Razão elétrica"),
            "val_verifgarantiaenergetica": ("#1A1A1A", "Garantia energética"),
        }

        # KPIs removidos na Fase E.6 — gráfico fala por si.
        # PALETA_MOTIVOS_KPI continua usada pelo gráfico (mantida acima).

        # === Fase C.2.2 — gráfico stacked bar mensal ===
        # df_filt já calculado acima — reusado aqui pra evitar dupla filtragem.

        if df_filt.empty:
            # Mensagem amigável quando o filtro cai em lacuna conhecida da usina
            # (ex: LINHARES (LORM) em fev-abr/2026). Consolidado nunca cai aqui
            # via lacuna — usina_em_operacao retorna True por default permissivo.
            if usina_sel != "Consolidado":
                em_op_ini = usina_em_operacao(
                    usina_sel, data_ini.year, data_ini.month
                )
                em_op_fim = usina_em_operacao(
                    usina_sel, data_fim.year, data_fim.month
                )
            else:
                em_op_ini = True
                em_op_fim = True

            if not em_op_ini and not em_op_fim:
                st.info(
                    f"📅 **{usina_sel}** não tem dados no período selecionado "
                    f"({data_ini.strftime('%d/%m/%Y')} → "
                    f"{data_fim.strftime('%d/%m/%Y')}). "
                    f"Tente selecionar um período onde a usina esteve em "
                    f"operação, ou escolha 'Consolidado' para ver o "
                    f"portfólio completo."
                )
            else:
                st.warning(
                    f"Nenhum dado disponível para {usina_sel} no período "
                    f"{data_ini.strftime('%d/%m/%Y')} → "
                    f"{data_fim.strftime('%d/%m/%Y')}."
                )
        else:
            # 2) Agregação por granularidade (Fase D.1/D.2).
            if gran_atual == "Mensal":
                df_filt["ano_mes"] = df_filt["data"].dt.to_period("M").dt.to_timestamp()
                agg = df_filt.groupby("ano_mes")[MOTIVOS_COLS].sum().reset_index()
                # Labels PT-BR pré-construídos (Windows + Plotly + locale =
                # inglês nos %b/%B nativos; padrão é _MESES_BR — decisão 3.5).
                agg["label"] = agg["ano_mes"].apply(
                    lambda ts: f"{_MESES_BR[ts.month]}/{str(ts.year)[2:]}"
                )
                if unidade == "GWh":
                    for col in MOTIVOS_COLS:
                        agg[col] = agg[col] / 1000.0
                    sufixo_unidade = "GWh"
                    fmt_hover = ",.1f"
                elif unidade == "MWm":
                    horas = agg["ano_mes"].apply(
                        lambda ts: calendar.monthrange(ts.year, ts.month)[1] * 24
                    )
                    for col in MOTIVOS_COLS:
                        agg[col] = agg[col] / horas
                    sufixo_unidade = "MWm"
                    fmt_hover = ",.1f"
                else:
                    sufixo_unidade = "MWh"
                    fmt_hover = ",.0f"

            elif gran_atual == "Diário":
                df_filt["dia"] = df_filt["data"].dt.date
                agg = df_filt.groupby("dia")[MOTIVOS_COLS].sum().reset_index()
                agg["label"] = agg["dia"].apply(lambda d: d.strftime("%d/%m"))
                if unidade == "GWh":
                    for col in MOTIVOS_COLS:
                        agg[col] = agg[col] / 1000.0
                    sufixo_unidade = "GWh"
                    fmt_hover = ",.1f"
                elif unidade == "MWm":
                    for col in MOTIVOS_COLS:
                        agg[col] = agg[col] / 24.0
                    sufixo_unidade = "MWm"
                    fmt_hover = ",.0f"
                else:
                    sufixo_unidade = "MWh"
                    fmt_hover = ",.0f"

            elif gran_atual == "Horário":
                # Cada linha do df_filt já é 1 hora — groupby por (data, hora)
                # agrega motivos quando há múltiplas usinas no mesmo instante
                # (decisão 5.44). label vai como datetime (não string) pra que
                # xaxis.tickformat/hoverformat controlem eixo curto "HH:00" e
                # tooltip rico "DD/MM/YYYY HH:00" (decisão 5.50).
                agg = (
                    df_filt.groupby(["data", "hora"])[MOTIVOS_COLS]
                    .sum()
                    .reset_index()
                )
                agg["instante"] = (
                    agg["data"]
                    + pd.to_timedelta(agg["hora"], unit="h")
                )
                agg["label"] = agg["instante"]
                if unidade == "GWh":
                    for col in MOTIVOS_COLS:
                        agg[col] = agg[col] / 1000.0
                    sufixo_unidade = "GWh"
                    fmt_hover = ",.2f"
                elif unidade == "MWm":
                    # Cada linha do agg = 1 hora → sum direto = MWmédio
                    # da hora (denominador implícito = 1h, sem divisão).
                    sufixo_unidade = "MWm"
                    fmt_hover = ",.0f"
                else:
                    sufixo_unidade = "MWh"
                    fmt_hover = ",.0f"

            else:  # gran_atual == "Trimestral"
                # Agregação por trimestre civil (Fase D.2). Replica do
                # Sistema linhas 3757-3779 com adaptação pra unidades MWh/
                # MWm/GWh (Sistema só tem MWm).
                df_filt["trimestre"] = (
                    df_filt["data"].dt.to_period("Q").dt.to_timestamp()
                )
                agg = df_filt.groupby("trimestre")[MOTIVOS_COLS].sum().reset_index()
                # Label "1T/24" (formato com slash, alinhado com Sistema).
                agg["label"] = agg["trimestre"].apply(
                    lambda ts: f"{((ts.month - 1) // 3) + 1}T/{str(ts.year)[2:]}"
                )
                # Filtra trims sem dados (Fase H — Item 6 bonus). Trims com
                # sum=0 em todos os motivos vêm de filter por anos+meses
                # incluindo trims futuros (ex: 4T/26 ainda não chegou). Sem
                # filter, gerariam barras vazias no eixo X.
                agg = agg[
                    agg[MOTIVOS_COLS].sum(axis=1) > 0
                ].reset_index(drop=True)
                if unidade == "GWh":
                    for col in MOTIVOS_COLS:
                        agg[col] = agg[col] / 1000.0
                    sufixo_unidade = "GWh"
                    fmt_hover = ",.0f"
                elif unidade == "MWm":
                    # Horas no trimestre = soma de horas dos 3 meses.
                    # `ts` é sempre o 1º dia do trim (jan/abr/jul/out).
                    def _horas_trimestre(ts):
                        ano, mes = ts.year, ts.month
                        total = 0
                        for m in (mes, mes + 1, mes + 2):
                            total += calendar.monthrange(ano, m)[1] * 24
                        return total
                    horas = agg["trimestre"].apply(_horas_trimestre)
                    for col in MOTIVOS_COLS:
                        agg[col] = agg[col] / horas
                    sufixo_unidade = "MWm"
                    fmt_hover = ",.0f"
                else:
                    sufixo_unidade = "MWh"
                    fmt_hover = ",.0f"

            # Guard "Sem despacho" — agg vazio ou sum total = 0
            # (Fase H — Item 2). Decisão 5.24: st.info + st.stop bloqueia
            # paleta + caption + gráfico quando não há nada pra mostrar.
            if agg.empty or agg[MOTIVOS_COLS].sum().sum() == 0:
                if gran_atual == "Horário":
                    msg_sd = f"Sem despacho em {data_ini.strftime('%d/%m/%Y')}."
                elif gran_atual == "Trimestral":
                    msg_sd = "Sem despacho no período selecionado."
                else:
                    msg_sd = (
                        f"Sem despacho no período "
                        f"{data_ini.strftime('%d/%m/%Y')} → "
                        f"{data_fim.strftime('%d/%m/%Y')}."
                    )
                st.info(msg_sd)
                st.stop()

            # 3) Paleta + labels
            PALETA_MOTIVOS = {
                "val_verifinflexibilidade":    "#D62828",
                "val_verifordemmerito":        "#1D3557",
                "val_verifunitcommitment":     "#F6BD16",
                "val_verifexportacao":         "#6B6B6B",
                "val_verifgsub":               "#A8A8A8",
                "val_verifrazaoeletrica":      "#4A4A4A",
                "val_verifgarantiaenergetica": "#1A1A1A",
            }
            LABELS_MOTIVOS = {
                "val_verifinflexibilidade":    "Inflexibilidade",
                "val_verifordemmerito":        "Ordem de mérito",
                "val_verifunitcommitment":     "Unit commitment",
                "val_verifexportacao":         "Exportação",
                "val_verifgsub":               "GSUB",
                "val_verifrazaoeletrica":      "Razão elétrica",
                "val_verifgarantiaenergetica": "Garantia energética",
            }

            # 4) Caption do gráfico — Fase E.17 (helper top do bloco térmico).
            # gran_label dinâmico (Fase D.1). "MWm" mapeia pra "MWmed" no
            # rótulo (decisão da fase); GWh/MWh passam direto.
            _unidade_label_en = (
                "MWmed" if sufixo_unidade == "MWm" else sufixo_unidade
            )
            # Title estilo Curtailment: ENEVA · DESPACHO TERMELÉTRICO · {USINA}
            # uppercase. Sub-caption muda pra Inter 500 preto (sem italic).
            _usina_label = (
                usina_sel if usina_sel else "Consolidado"
            ).upper()
            _sub_label_eneva = (
                f"ENEVA · DESPACHO TERMELÉTRICO · {_usina_label}"
            )
            _render_termico_chart_caption(
                sub_label=_sub_label_eneva,
                gran_label=gran_atual,
                data_ini=data_ini,
                data_fim=data_fim,
                unidade_label=_unidade_label_en,
                estilo_curtailment=True,
            )

            # 5) Construir figura
            fig = go.Figure()

            # Trace invisível pra mostrar Total no hover unified.
            # go.Scatter (não Bar) — não participa do barmode="stack",
            # então não dobra a altura visual; aparece como linha
            # extra no tooltip unified com label "Total" em destaque.
            # Adicionado ANTES do loop dos 7 motivos pra aparecer no
            # FUNDO do tooltip (Plotly: traces adicionados primeiro
            # ficam embaixo no hover unified).
            agg_total = agg[MOTIVOS_COLS].sum(axis=1)
            hovertemplate_total = (
                f'<span style="color:{BAUHAUS_BLACK}; font-weight:700;">'
                f'{"Total".ljust(20).replace(" ", "&nbsp;")}</span>'
                f'&nbsp;&nbsp;'
                f'<span style="color:{BAUHAUS_BLACK}; font-weight:700;">'
                f'%{{y:{fmt_hover}}} {sufixo_unidade}</span>'
                f'<extra></extra>'
            )
            fig.add_trace(go.Scatter(
                x=agg["label"],
                y=agg_total,
                name="Total",
                mode="lines",
                line=dict(color="rgba(0,0,0,0)"),
                hovertemplate=hovertemplate_total,
                showlegend=False,
                hoverlabel=dict(
                    bgcolor=BAUHAUS_CREAM,
                    bordercolor=BAUHAUS_BLACK,
                ),
            ))

            # Render condicional Bar/Scatter (decisão 5.47).
            # Horário: área stackada (Scatter com stackgroup + fillcolor) —
            #   mode="none" oculta linha; barmode="stack" não afeta Scatter.
            # Mensal/Diário: barras empilhadas (Bar com barmode="stack").
            for col in MOTIVOS_COLS:
                label = LABELS_MOTIVOS[col]
                cor = PALETA_MOTIVOS[col]
                label_pad = label.ljust(20).replace(" ", "&nbsp;")
                hovertemplate = (
                    f'<span style="color:{cor}; font-weight:700;">{label_pad}</span>'
                    f'&nbsp;&nbsp;'
                    f'<span style="color:#1A1A1A;">%{{y:{fmt_hover}}} {sufixo_unidade}</span>'
                    f'<extra></extra>'
                )
                if gran_atual == "Horário":
                    fig.add_trace(go.Scatter(
                        x=agg["label"],
                        y=agg[col],
                        name=label,
                        stackgroup="motivos",
                        mode="none",
                        fillcolor=cor,
                        hovertemplate=hovertemplate,
                    ))
                else:
                    fig.add_trace(go.Bar(
                        x=agg["label"],
                        y=agg[col],
                        name=label,
                        marker_color=cor,
                        hovertemplate=hovertemplate,
                    ))

            # xaxis_kwargs condicional ao modo (decisão 5.50).
            # Em Horário, x=datetime + tickformat curto + hoverformat rico.
            xaxis_kwargs = dict(
                title=None, showgrid=False, showline=True,
                linewidth=2, linecolor=BAUHAUS_BLACK,
                ticks="outside", tickcolor=BAUHAUS_BLACK,
                tickfont=dict(family="Inter, sans-serif", size=12, color=BAUHAUS_BLACK),
            )
            if gran_atual == "Horário":
                xaxis_kwargs["tickformat"] = "%H:00"
                xaxis_kwargs["hoverformat"] = "%d/%m/%Y %H:00"

            fig.update_layout(
                barmode="stack",
                height=450,
                margin=dict(l=20, r=20, t=10, b=20),
                paper_bgcolor=BAUHAUS_CREAM,
                plot_bgcolor=BAUHAUS_CREAM,
                separators=",.",
                hovermode="x unified",
                hoverlabel=dict(
                    bgcolor=BAUHAUS_CREAM,
                    bordercolor=BAUHAUS_BLACK,
                    font=dict(family="'IBM Plex Mono', 'Courier New', monospace", size=12, color=BAUHAUS_BLACK),
                ),
                showlegend=True,
                legend=dict(
                    orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    bgcolor="rgba(0,0,0,0)",
                    font=dict(family="Inter, sans-serif", size=13, color=BAUHAUS_BLACK),
                    traceorder="normal",
                ),
                xaxis=xaxis_kwargs,
                yaxis=dict(
                    title=None,
                    showgrid=True, gridcolor=BAUHAUS_LIGHT, gridwidth=1,
                    showline=True, linewidth=2, linecolor=BAUHAUS_BLACK,
                    ticks="outside", tickcolor=BAUHAUS_BLACK,
                    tickfont=dict(family="Inter, sans-serif", size=12, color=BAUHAUS_BLACK),
                    zeroline=False,
                    tickformat=",.0f",
                ),
                font=dict(family="Inter, sans-serif", size=12),
            )

            st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})

        # Caption "Histórico em cache" — footnote pós-gráfico (Fase H.2 —
        # Ajuste 4). Indentado 8 espaços (nível subview Eneva), FORA
        # do else do empty pra sempre renderizar (mesmo quando gráfico
        # foi suprimido por warning/info/sem despacho).
        st.markdown(
            f'<div style="font-family:\'Inter\', sans-serif; '
            f'font-size:0.85rem; color:#6B6B6B; font-style:italic; '
            f'margin:1rem 0 0 0;">'
            f'Histórico em cache: desde {min_d.strftime("%d/%m/%Y")}.'
            f'</div>',
            unsafe_allow_html=True,
        )

elif aba == "Geração" and st.session_state.get("geracao_subview", "SIN") == "SIN":
    # -----------------------------------------------------------------------
    # Aba Geração — sub-view SIN (default). Stacked area de geração por fonte
    # (térmica/hidro/eólica/solar) + linha tracejada de carga verificada.
    # Fonte ONS balanço de subsistemas. Inclui anotação da quebra metodológica
    # de 29/04/2023 (carga passa a incluir MMGD).
    # Sub-view "Grupo" (Eólica/Solar por Grupo) é renderizada em branch
    # separado abaixo (componente components.tab_geracao_grupo).
    # -----------------------------------------------------------------------
    st.markdown("# GERAÇÃO")
    st.markdown(
        '<div style="border-bottom: 2px solid #1A1A1A; '
        'margin: 0 0 -1.5rem 0;"></div>',
        unsafe_allow_html=True,
    )

    # --- Carregar dados ---
    # Sessão 1.5b: range do dataset segue gen_historico_completo (sticky na
    # sessão até clear_cache). Default False → 15 anos. True (sob demanda
    # via modal) → 27 anos. @st.cache_data trata o param como key, então
    # cada variante tem entry de cache em-memória próprio.
    historico_completo_gen = st.session_state.get(
        "gen_historico_completo", False
    )
    # Spinner dinâmico (mesma lógica da Sessão 1.5, agora ciente da variante).
    if is_balanco_cache_fresh(historico_completo_gen):
        spinner_msg = "Carregando dados de geração..."
    else:
        if historico_completo_gen:
            spinner_msg = (
                "Baixando 27 anos de dados ONS (~25MB)... "
                "pode levar ~25s na primeira vez."
            )
        else:
            spinner_msg = (
                "Baixando 15 anos de dados ONS (~12MB)... "
                "pode levar ~15s na primeira vez."
            )
    with st.spinner(spinner_msg):
        try:
            df_gen = load_balanco_subsistema(
                incluir_historico_completo=historico_completo_gen,
            )
        except Exception as e:
            st.error(f"Falha ao carregar dados do ONS (balanço): {e}")
            debug = st.session_state.get("_debug_erros", [])
            if debug:
                st.subheader("Detalhes técnicos do erro")
                for d in debug[:20]:
                    st.code(d)
            st.stop()

    if df_gen.empty:
        st.warning("Nenhum dado disponível.")
        st.stop()

    ORDEM_SUBSISTEMA_GEN = ["SIN", "SE", "S", "NE", "N"]
    LABELS_SUBSISTEMA_GEN = {
        "SIN": "SIN",
        "SE":  "SUDESTE",
        "S":   "SUL",
        "NE":  "NORDESTE",
        "N":   "NORTE",
    }
    NOME_SUB_LONGO = {
        "SIN": "SIN",
        "SE":  "Sudeste/Centro-Oeste",
        "S":   "Sul",
        "NE":  "Nordeste",
        "N":   "Norte",
    }

    # Consome flag setado pelo botão "Ver curva horária deste dia" do guard
    # <2 pontos. Streamlit proíbe modificar a key de um widget já
    # instanciado no mesmo run, então o botão seta o flag + rerun, e aqui
    # (antes do selectbox abaixo ser instanciado) movemos gen_granularidade.
    if st.session_state.pop("_gen_force_horaria", False):
        st.session_state["gen_granularidade"] = "Horária"

    # Defesa preventiva contra widget-state cleanup do Streamlit (decisão
    # 5.18 do CLAUDE.md, mesmo padrão da 5.16 que cobriu gen_data_ini/fim).
    # Em reruns intermediários — particularmente durante o load pesado
    # pós-"Atualizar" — o Streamlit pode descartar widget-state de keys que
    # não foram instanciadas naquele rerun específico. Pra selectbox isso
    # leva à dessincronia visual: dropdown mostra valor antigo cached do
    # navegador, mas a variável retornada cai no default (Diária / SIN),
    # presets/gráfico renderizam errado. Workaround manual: clicar de novo
    # no dropdown.
    #
    # Backup paralelo em key NÃO widget-state preserva a escolha do user.
    # Se widget-state foi descartada mas backup existe, restauramos antes
    # do widget ser instanciado. No fim do bloco, atualizamos o backup.
    _GEN_GRAN_BACKUP = "_gen_granularidade_backup"
    _GEN_SUB_BACKUP = "_gen_submercado_backup"
    if (
        "gen_granularidade" not in st.session_state
        and _GEN_GRAN_BACKUP in st.session_state
    ):
        st.session_state["gen_granularidade"] = (
            st.session_state[_GEN_GRAN_BACKUP]
        )
    if (
        "gen_submercado" not in st.session_state
        and _GEN_SUB_BACKUP in st.session_state
    ):
        st.session_state["gen_submercado"] = (
            st.session_state[_GEN_SUB_BACKUP]
        )

    # Default da 1ª visita absoluta na sessão: Horária (decisão 5.20).
    # Setado ANTES do selectbox ser instanciado pra evitar
    # StreamlitAPIException (decisão 5.12). Sentinela `_gen_dataset_max`
    # ausente prova "nunca rodou nesta sessão" — só este reset block a
    # seta. Razão UX: usuário casual costuma querer ver "como foi
    # ontem/agora", não 12 meses de série diária.
    if "_gen_dataset_max" not in st.session_state:
        st.session_state["gen_granularidade"] = "Horária"

    # --- Controles: granularidade + submercado ---
    ctrl_cols = st.columns([1.2, 1.8, 3.2])
    with ctrl_cols[0]:
        granularidade_gen = st.selectbox(
            "Granularidade",
            ["Mensal", "Diária", "Horária", "Dia Típico"],
            index=1,  # default diária
            key="gen_granularidade",
        )
    with ctrl_cols[1]:
        submercado_gen = st.selectbox(
            "Submercado",
            ORDEM_SUBSISTEMA_GEN,
            index=0,  # default SIN
            key="gen_submercado",
            format_func=lambda c: NOME_SUB_LONGO[c],
        )

    # Atualiza backups pós-widget pra próximo rerun ter valor preservado
    # caso o cleanup dispare. Decisão 5.18 do CLAUDE.md.
    st.session_state[_GEN_GRAN_BACKUP] = granularidade_gen
    st.session_state[_GEN_SUB_BACKUP] = submercado_gen

    # --- Range disponível no dataset (baseado em data_hora) ---
    min_d_gen = df_gen["data_hora"].min().date()
    max_d_gen = df_gen["data_hora"].max().date()

    # =========================================================================
    # RESET BLOCK UNIFICADO (decisão 5.20)
    # =========================================================================
    # Aplica default da granularidade ATUAL em qualquer um destes gatilhos:
    #
    # 1. force_reset (clear_cache disparou via flag _gen_force_reset)
    # 2. 1ª visita absoluta (sentinela _gen_dataset_max ausente)
    # 3. Dataset mudou (max ou min ≠ stored)
    # 4. Transição de granularidade (prev_gran != atual, decisão 5.20)
    # 5. Em modo NÃO-Horária: gen_data_ini/gen_data_fim ausentes (5.16/5.19)
    # 6. Em modo NÃO-Horária: gen_data_ini >= gen_data_fim (range degenerado).
    #    Cobre o caso de retorno de aba quando o widget cleanup parcial do
    #    Streamlit descarta gen_data_ini (mas não gen_data_fim) — ao
    #    re-instanciar o st.date_input, ele cria a key com value clamped pra
    #    max_d, ficando == gen_data_fim. As 2 keys ficam PRESENTES (a 5ª não
    #    pega) mas com range inválido. Diagnóstico em runtime na Sessão 1.6.
    #
    # Defaults aplicados (helper top-level _aplica_default_periodo_gen):
    #   Diária     → 1M
    #   Mensal     → 12M
    #   Horária    → 1D + data_base = max_d
    #   Dia Típico → 30D (Sessão 2, decisão 5.25)
    #
    # Substitui bloco "ao sair de Horária" + auto-ajuste Mensal +
    # reset de 12M-Diária — todos absorvidos aqui. Decisão 5.14 fica como
    # histórico/superada.
    #
    # Decisão 5.19: a checagem de keys individuais (gatilhos 5 e 6) EXCLUI
    # a Horária — lá esses keys são widget-state de Diária/Mensal cujo
    # cleanup é normal/esperado.
    em_horaria = (
        st.session_state.get("gen_granularidade") == "Horária"
    )
    prev_gran_gen = st.session_state.get("_gen_last_gran")
    em_transicao = (
        prev_gran_gen is not None
        and prev_gran_gen != granularidade_gen
    )
    force_reset_gen = st.session_state.pop("_gen_force_reset", False)

    if (
        force_reset_gen
        or "_gen_dataset_max" not in st.session_state
        or st.session_state.get("_gen_dataset_max") != max_d_gen
        or st.session_state.get("_gen_dataset_min") != min_d_gen
        or em_transicao
        or (
            not em_horaria
            and (
                "gen_data_ini" not in st.session_state
                or "gen_data_fim" not in st.session_state
            )
        )
        or (
            not em_horaria
            and "gen_data_ini" in st.session_state
            and "gen_data_fim" in st.session_state
            and st.session_state["gen_data_ini"]
                >= st.session_state["gen_data_fim"]
        )
    ):
        _aplica_default_periodo_gen(granularidade_gen, min_d_gen, max_d_gen)
        st.session_state["_gen_dataset_max"] = max_d_gen
        st.session_state["_gen_dataset_min"] = min_d_gen

    st.session_state["_gen_last_gran"] = granularidade_gen

    # --- Período: modo depende da granularidade ---
    # Diária/Mensal: 2 date_inputs ancorados em presets de "últimos N dias".
    # Horária: 1 date_input (Data base) + presets de "janela de N dias
    # terminando na data base". data_ini/data_fim são derivados.
    if granularidade_gen == "Horária":
        # Inicializa estado da Horária se 1ª visita (ou após reset de
        # dataset). Inits SEPARADOS por key: gen_data_base pode virar None
        # (st.date_input retorna None se o campo for limpado), e
        # reinicializar gen_data_base nesse caso NÃO deve ressetar window,
        # senão apagaria o preset 7D/30D/90D recém-clicado.
        #
        # - gen_data_base: trata ausente E None (`not get()`). Fallback de
        #   gen_data_fim também protegido com `or` pra tratar None.
        # - window: só seta default=1 se a key é ausente (1ª visita
        #   absoluta no modo Horária).
        if not st.session_state.get("gen_data_base"):
            st.session_state["gen_data_base"] = min(
                max_d_gen,
                st.session_state.get("gen_data_fim") or max_d_gen,
            )
        if "gen_horaria_window_dias" not in st.session_state:
            st.session_state["gen_horaria_window_dias"] = 1

        presets_hora = [
            ("1D",  1,  False),
            ("7D",  7,  False),
            ("30D", 30, False),
            ("90D", 90, False),
        ]
        _render_period_controls_horaria(
            presets=presets_hora,
            session_key_base="gen_data_base",
            session_key_window="gen_horaria_window_dias",
            key_prefix="btn_gen_hora_",
            min_d=min_d_gen,
            max_d=max_d_gen,
        )

        # Deriva ini/fim a partir de base + window (janela = N dias
        # terminando na data base). Clampa ini em min_d se a janela
        # ultrapassa o início do dataset.
        window = st.session_state["gen_horaria_window_dias"]
        data_base = st.session_state["gen_data_base"]
        data_fim_gen = data_base
        data_ini_gen = max(min_d_gen, data_base - timedelta(days=window - 1))
        # Espelha no state "range" pra preservar quando voltar a Diária/Mensal
        st.session_state["gen_data_ini"] = data_ini_gen
        st.session_state["gen_data_fim"] = data_fim_gen
    else:
        data_ini_gen = st.session_state["gen_data_ini"]
        data_fim_gen = st.session_state["gen_data_fim"]

        # NOTA (Sessão 1.5b): o antigo auto-ajuste de Mensal pra 3M quando
        # período herdado < 60d (decisão 5.14) foi REMOVIDO. O reset block
        # unificado (decisão 5.20) já aplica default Mensal=12M na transição
        # de granularidade — cobre o caso Horária 1D → Mensal sem
        # workaround. 5.14 marcada como histórico/superada no CLAUDE.md.

        if data_ini_gen > data_fim_gen:
            st.error("A data inicial não pode ser posterior à data final.")
            st.stop()

        # Mensal sem "1M": 1 mês dá 1 ponto, cai no guard de <2 pontos.
        # Sessão 1.5b: presets revisados — Mensal ganha 10A; Diária
        # ganha 10A. "Máx" continua respeitando o range do dataset (15a ou
        # completo conforme gen_historico_completo). Decisão 5.17.
        # 15A removido na Sessão 4a (decisão 5.27): degenerava pra Máx no
        # dataset padrão (~14a), tooltip dinâmico do Máx esclarece o range.
        if granularidade_gen == "Mensal":
            presets_gen = [
                ("3M",  90,  False),
                ("6M",  180, False),
                ("12M", 365, False),
                ("5A",  1825, False),
                ("10A", 3650, False),
                ("Máx", None, True),
            ]
        elif granularidade_gen == "Dia Típico":
            # Sem "Máx" — descontinuidade estrutural pré-2010 (matriz
            # mudou) torna 25a sem sentido como "perfil típico". 7D é
            # o mínimo prático (cobre weekday/weekend); guard <7d
            # bloqueia seleção manual menor (decisão 5.25).
            presets_gen = [
                ("7D",  7,    False),
                ("30D", 30,   False),
                ("90D", 90,   False),
                ("6M",  180,  False),
                ("12M", 365,  False),
                ("5A",  1825, False),
            ]
        else:
            presets_gen = [
                ("1M",  30,  False),
                ("3M",  90,  False),
                ("6M",  180, False),
                ("12M", 365, False),
                ("5A",  1825, False),
                ("10A", 3650, False),
                ("Máx", None, True),
            ]
        _render_period_controls(
            presets=presets_gen,
            session_key_ini="gen_data_ini",
            session_key_fim="gen_data_fim",
            key_prefix="btn_gen_",
            min_d=min_d_gen,
            max_d=max_d_gen,
        )
        data_ini_gen = st.session_state["gen_data_ini"]
        data_fim_gen = st.session_state["gen_data_fim"]

    # --- Botão "Estender histórico para 2000" (Sessão 1.5b + 4a) ---
    # Eixo separado dos presets de período: presets navegam DENTRO do range
    # carregado; este botão EXPANDE o range. Decisão 5.17 (dois eixos).
    # Sessão 4a: rename + tooltip explicativo + estado ativo claro.
    if historico_completo_gen:
        # Estado ativo: feedback visual de que o histórico foi estendido.
        # margin-top negativo cola o texto nos botões de preset acima
        # (informação relacionada — range coberto pelo "Máx").
        st.markdown(
            '<div style="font-family:\'Inter\', sans-serif; '
            'font-size:0.8rem; color:#4A4A4A; font-weight:500; '
            'margin:-0.8rem 0 0 0;">'
            '✓ Histórico estendido ativo (desde 2000)'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        # Botão inativo cola nos presets via CSS global que ataca
        # .st-key-btn_gen_historico_completo (Streamlit emite essa class
        # no element-container quando widget tem key=). Ver bloco CSS no
        # topo do app.py.
        if st.button(
            "Estender histórico para 2000",
            key="btn_gen_historico_completo",
            help="Adiciona dados de 2000-2010 ao range disponível. "
                 "Demora ~30s na primeira vez (depois fica em cache).",
        ):
            _confirmar_historico_completo_gen()

    # --- Teto 90 dias na horária (trunca no render, avisa via warning) ---
    # Decisão: não mexer em session_state pra não confundir o usuário com
    # datas "saltando" sozinhas. Só trunca o filtro local + warning.
    periodo_dias_gen = (data_fim_gen - data_ini_gen).days
    if granularidade_gen == "Horária" and periodo_dias_gen > 90:
        st.warning(
            f"Granularidade horária limitada a 90 dias (seria "
            f"{periodo_dias_gen} dias). Mostrando os últimos 90 dias do "
            f"intervalo selecionado."
        )
        data_ini_efetivo_gen = data_fim_gen - timedelta(days=90)
    else:
        data_ini_efetivo_gen = data_ini_gen

    # --- Guard: Mensal precisa de pelo menos 2 meses ---
    # Resample 'MS' em < 60 dias gera ≤ 1 ponto. Bloqueio educativo:
    # warning + st.stop(). A decisão 5.14 (auto-ajuste silencioso) foi
    # superada pela 5.20 nas TRANSIÇÕES de granularidade; este guard
    # cobre o caso de seleção MANUAL curta dentro do modo Mensal.
    if (
        granularidade_gen == "Mensal"
        and (data_fim_gen - data_ini_efetivo_gen).days < 60
    ):
        st.warning(
            "Mensal precisa de pelo menos 2 meses. Selecione um período "
            "maior ou troque pra Diária."
        )
        st.stop()

    # --- Guard: Dia Típico precisa de pelo menos 7 dias ---
    # Mesmo padrão da 5.24: warning educativo + st.stop. < 7 dias não
    # captura padrão weekday/weekend, perfil deixa de ser "típico" e vira
    # "média de poucos dias específicos". Decisão 5.25.
    if (
        granularidade_gen == "Dia Típico"
        and (data_fim_gen - data_ini_efetivo_gen).days < 7
    ):
        st.warning(
            "Dia típico precisa de pelo menos 7 dias pra ser "
            "representativo. Selecione um período maior ou troque pra "
            "Diária pra ver dia específico."
        )
        st.stop()

    # --- Agregação temporal ---
    # Resample MEAN (MWmed é potência média, não soma).
    # Horária:    sem resample (já vem horário).
    # Diária:     'D' (1 valor por dia).
    # Mensal:     'MS' (1 valor no 1º dia do mês, alinha com PLD mensal do CCEE).
    # Dia Típico: sem resample temporal — _build_dia_tipico_submercado
    #             reagrega o pivot horário por hora-do-dia (24 linhas).
    freq_map = {
        "Horária":    None,
        "Diária":     "D",
        "Mensal":     "MS",
        "Dia Típico": None,
    }
    freq = freq_map[granularidade_gen]

    # Helper local: filtra df_gen por submercado + período, pivota (fontes em
    # colunas), aplica resample e fillna(0). Retorna None se sem dados.
    # .fillna(0) SÓ aqui no render (não no loader — preserva semântica de
    # "ausência de registro" vs "zero medido" no DataFrame público).
    # Fix #1 (Sessão 1.5): comparar contra a coluna `data` (datetime64[ns]
    # normalizado pra meia-noite, pré-computada no loader). `pd.Timestamp` na
    # condição mantém comparação vetorizada nativamente — diff vs versão
    # antiga `.dt.date >= date(...)` é ~50× (filter de ~11s/sub pra ~50ms/sub
    # no cenário Diária 12M).
    data_ini_ts = pd.Timestamp(data_ini_efetivo_gen)
    data_fim_ts = pd.Timestamp(data_fim_gen)

    def _build_pivot_submercado(code):
        mask = (
            (df_gen["submercado"] == code)
            & (df_gen["data"] >= data_ini_ts)
            & (df_gen["data"] <= data_fim_ts)
        )
        dff = df_gen.loc[mask]
        if dff.empty:
            return None
        pivot = dff.pivot_table(
            index="data_hora", columns="fonte", values="mwmed",
            aggfunc="mean",
        ).sort_index()
        if freq is not None:
            pivot = pivot.resample(freq).mean()
        for col in ["hidro", "termica", "eolica", "solar", "carga"]:
            if col not in pivot.columns:
                pivot[col] = 0.0
        pivot[["hidro", "termica", "eolica", "solar", "carga"]] = (
            pivot[["hidro", "termica", "eolica", "solar", "carga"]].fillna(0)
        )
        return pivot

    def _build_dia_tipico_submercado(code):
        """Pivot agregado por hora-do-dia (24 linhas, index "00:00".."23:00").

        Reaproveita _build_pivot_submercado (que retorna pivot horário
        quando freq=None, garantido pelo freq_map["Dia Típico"]=None) e
        aplica groupby(index.hour).mean() — média de cada fonte em cada
        hora-do-dia ao longo do período selecionado. Index final é
        string "HH:00" pra Plotly tratar X como categorial (preserva
        ordem 00→23, hover unified mostra a hora direta sem precisar
        de hoverformat). Decisão 5.25.
        """
        pivot_horario = _build_pivot_submercado(code)
        if pivot_horario is None or pivot_horario.empty:
            return None
        pivot = pivot_horario.groupby(pivot_horario.index.hour).mean()
        pivot.index = [f"{h:02d}:00" for h in pivot.index]
        pivot.index.name = "Hora"  # vira coluna no reset_index do export
        return pivot

    # Popula os 5 pivots de uma vez (1× por render) — alimenta KPIs do
    # submercado selecionado, gráfico único e export CSV dos 5. Troca de
    # dropdown vira instantânea (só muda a referência, não recomputa).
    # Em Dia Típico, despacha pro helper que reagrega por hora-do-dia.
    pivots_por_sub = {}
    _build_pivot = (
        _build_dia_tipico_submercado
        if granularidade_gen == "Dia Típico"
        else _build_pivot_submercado
    )
    for code in ORDEM_SUBSISTEMA_GEN:
        pv = _build_pivot(code)
        if pv is not None:
            pivots_por_sub[code] = pv

    pivot_sel = pivots_por_sub.get(submercado_gen)
    if pivot_sel is None:
        st.warning(
            f"Sem dados de {NOME_SUB_LONGO[submercado_gen]} "
            "no intervalo selecionado."
        )
        st.stop()

    # --- Guard: mínimo de 2 pontos pra fazer sentido o gráfico ---
    # Posicionado ANTES dos KPIs/notas/export pra bloquear tudo via
    # st.stop() — KPIs sem 2+ pontos não são informativos. Botão "Ver
    # curva horária" preservado pro caso Diária 1 dia (uso comum).
    if len(pivot_sel) < 2:
        st.info(
            "Selecione pelo menos 2 pontos para visualizar o gráfico "
            "de geração. Para ver a curva intra-diária de um dia "
            "específico, mude a granularidade para Horária."
        )
        if granularidade_gen == "Diária" and len(pivot_sel) == 1:
            # Ancora data_base no dia selecionado + window=1D
            # explicitamente pra não herdar state de visita anterior à
            # Horária. Flag _gen_force_horaria é consumida no topo do
            # bloco antes do selectbox ser instanciado (Streamlit não
            # deixa modificar a key dele aqui).
            if st.button("Ver curva horária deste dia"):
                st.session_state["_gen_force_horaria"] = True
                st.session_state["gen_data_base"] = data_fim_gen
                st.session_state["gen_horaria_window_dias"] = 1
                st.rerun()
        st.stop()

    # --- Variáveis usadas DOWNSTREAM (notas, vline da quebra, tag de
    # granularidade do título do gráfico). As notas em si são renderizadas
    # ABAIXO do gráfico (Sessão 4a — manter espaço above-the-fold pros KPIs
    # e gráfico, em vez de empurrá-los pra baixo com 3-4 linhas de contexto).
    ultima_data_gen = df_gen["data_hora"].max()
    tag_granularidade_gen = {
        "Mensal":     "Média mensal · MWmed",
        "Diária":     "Média diária · MWmed",
        "Horária":    "Valor horário · MWmed",
        "Dia Típico": (
            "Dia típico (média horária do período selecionado) · MWmed"
        ),
    }[granularidade_gen]
    quebra_data = pd.Timestamp(2023, 4, 29)

    # --- KPIs do submercado selecionado (4 cards) ---
    # Médias da janela visível, recalculadas ao trocar submercado. %renov
    # var = (eólica + solar) / geração total. Em Norte aparece ~0% (sem
    # eólica/solar expressivos), em NE ~80% — é informação correta.
    def _fmt_br_gen(v, casas=0):
        """Número BR: 1.234 (milhar ponto, decimal vírgula). Sem unidade."""
        if v is None or (hasattr(v, "__float__") and not (v == v)):
            return "—"
        fmt = f"{{:,.{casas}f}}"
        return fmt.format(v).replace(",", "X").replace(".", ",").replace("X", ".")

    ger_total_series = (
        pivot_sel["hidro"] + pivot_sel["termica"]
        + pivot_sel["eolica"] + pivot_sel["solar"]
    )
    ger_total_media = ger_total_series.mean()
    termica_media = pivot_sel["termica"].mean()
    carga_media = pivot_sel["carga"].mean()
    renov_var_media = (
        pivot_sel["eolica"].mean() + pivot_sel["solar"].mean()
    )
    pct_renov_var = (
        renov_var_media / ger_total_media * 100
        if ger_total_media and ger_total_media > 0 else float("nan")
    )

    # Caption colado nos KPIs: margin-bottom negativo neutraliza o gap
    # default do stVerticalBlock entre elementos Streamlit, deixando o
    # caption visualmente "agarrado" no bloco de KPIs (Sessão 4a).
    st.markdown(
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.85rem; color:#6B6B6B; font-style:italic; '
        f'margin:0.6rem 0 -0.8rem 0;">'
        f'Médias do período selecionado ({NOME_SUB_LONGO[submercado_gen]}).'
        f'</div>',
        unsafe_allow_html=True,
    )

    # KPIs da Geração: HTML custom (não st.metric) porque Bebas Neue é
    # all-caps por design — "MWmed" no value de st.metric renderiza como
    # "MWMED". Solução: número em Bebas Neue + unidade em Inter mixed-case.
    st.markdown(
        """
        <style>
        .gen-kpi-card {
            background: #F5F1E8;
            border: 2px solid #1A1A1A;
            padding: 8px 12px;
            border-radius: 0;
        }
        .gen-kpi-label {
            font-family: 'Inter', sans-serif;
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.16em;
            color: #1A1A1A;
            font-weight: 700;
            line-height: 1.2;
        }
        .gen-kpi-value {
            display: flex;
            align-items: baseline;
            margin-top: 0.15rem;
        }
        .gen-kpi-value-num {
            font-family: 'Bebas Neue', sans-serif;
            font-size: 1.45rem;
            color: #1A1A1A;
            letter-spacing: 0.02em;
            line-height: 1.1;
        }
        .gen-kpi-value-unit {
            font-family: 'Inter', sans-serif;
            font-size: 0.85rem;
            color: #1A1A1A;
            font-weight: 600;
            margin-left: 0.4rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    def _render_kpi_gen(label: str, num: str, unit: str = "") -> str:
        unit_html = (
            f'<span class="gen-kpi-value-unit">{unit}</span>' if unit else ""
        )
        return (
            f'<div class="gen-kpi-card">'
            f'<div class="gen-kpi-label">{label}</div>'
            f'<div class="gen-kpi-value">'
            f'<span class="gen-kpi-value-num">{num}</span>{unit_html}'
            f'</div>'
            f'</div>'
        )

    kpi_cols = st.columns(4)
    with kpi_cols[0]:
        st.markdown(
            _render_kpi_gen(
                "GERAÇÃO TOTAL", _fmt_br_gen(ger_total_media), "MWmed"
            ),
            unsafe_allow_html=True,
        )
    with kpi_cols[1]:
        # "%" colado no número — não passa por gen-kpi-value-unit.
        st.markdown(
            _render_kpi_gen(
                "% RENOV VARIÁVEL", f"{_fmt_br_gen(pct_renov_var, casas=1)}%"
            ),
            unsafe_allow_html=True,
        )
    with kpi_cols[2]:
        st.markdown(
            _render_kpi_gen(
                "TÉRMICA", _fmt_br_gen(termica_media), "MWmed"
            ),
            unsafe_allow_html=True,
        )
    with kpi_cols[3]:
        st.markdown(
            _render_kpi_gen(
                "CARGA", _fmt_br_gen(carga_media), "MWmed"
            ),
            unsafe_allow_html=True,
        )

    # =======================================================================
    # GRÁFICO — stacked area do submercado selecionado no dropdown.
    # Título Bauhaus flex (label à esquerda, data+valor à direita), linha de
    # período abaixo, legenda sempre visível. Altura 450px (meio termo entre
    # PLD/500 e layout empilhado anterior/270).
    # =======================================================================

    CORES_FONTE_GEN = {
        "termica": COR_FONTE_TERMICA,
        "hidro":   COR_FONTE_HIDRO,
        "eolica":  COR_FONTE_EOLICA,
        "solar":   COR_FONTE_SOLAR,
    }
    # Labels no HOVER são curtos (até 10 chars) pra alinhamento em monospace.
    # "Solar centralizada" na legenda deixa explícito que GD não está incluída.
    LABELS_FONTE_GEN = {
        "termica": "Térmica",
        "hidro":   "Hidráulica",
        "eolica":  "Eólica",
        "solar":   "Solar",
    }
    NOMES_LEGENDA_GEN = {
        **LABELS_FONTE_GEN,
        "solar": "Solar centralizada",
    }
    ORDEM_STACKED_GEN = ["termica", "hidro", "eolica", "solar"]

    periodo_str_gen = _format_periodo_br(
        data_ini_efetivo_gen, data_fim_gen, granularidade_gen,
    )

    if granularidade_gen == "Horária" and periodo_dias_gen >= 30:
        st.caption(
            "Granularidade horária com janela longa — "
            "renderização pode levar alguns segundos."
        )

    hover_fmt_gen = {
        "Horária":    "%d/%m/%Y %H:%M",
        "Diária":     "%d/%m/%Y",
        "Mensal":     "%b %Y",
        "Dia Típico": None,  # eixo X categorial — hoverformat não aplica
    }[granularidade_gen]

    label_sub = LABELS_SUBSISTEMA_GEN[submercado_gen]

    # margin-top aumentado de 1.2rem → 2.6rem na Sessão 4a pra separar
    # visualmente o bloco "caption + KPIs" do bloco "título + gráfico".
    st.markdown(
        f'<div style="display:flex; justify-content:space-between; '
        f'align-items:baseline; '
        f'font-family:\'Bebas Neue\', sans-serif; '
        f'font-size:1.1rem; letter-spacing:0.08em; color:#1A1A1A; '
        f'margin: 2.6rem 0 0.3rem 0; padding-bottom:3px; '
        f'border-bottom: 2px solid #1A1A1A;">'
        f'<span>{label_sub}</span>'
        f'<span>{periodo_str_gen}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.9rem; color:#1A1A1A; font-weight:500; '
        f'letter-spacing:0.04em; margin:0 0 0.5rem 0;">'
        f'{tag_granularidade_gen}'
        f'</div>',
        unsafe_allow_html=True,
    )

    fig_c = go.Figure()

    for fonte_col in ORDEM_STACKED_GEN:
        label = LABELS_FONTE_GEN[fonte_col]
        cor = CORES_FONTE_GEN[fonte_col]
        label_fix = label.ljust(10).replace(" ", "&nbsp;")
        fig_c.add_trace(
            go.Scatter(
                x=pivot_sel.index,
                y=pivot_sel[fonte_col],
                name=NOMES_LEGENDA_GEN[fonte_col],
                mode="lines",
                stackgroup="ger",
                line=dict(color=cor, width=0.8),
                fillcolor=cor,
                hovertemplate=(
                    f'<span style="color:{cor}; font-weight:700;">'
                    f'{label_fix}</span>'
                    '&nbsp;&nbsp;'
                    '<span style="color:#1A1A1A;">%{y:,.0f} MWmed</span>'
                    '<extra></extra>'
                ),
            )
        )

    carga_label_fix = "Carga".ljust(10).replace(" ", "&nbsp;")
    fig_c.add_trace(
        go.Scatter(
            x=pivot_sel.index,
            y=pivot_sel["carga"],
            name="Carga",
            mode="lines",
            line=dict(dash="dash", width=2.5, color=BAUHAUS_BLACK),
            hovertemplate=(
                f'<span style="color:{BAUHAUS_BLACK}; font-weight:700;">'
                f'{carga_label_fix}</span>'
                '&nbsp;&nbsp;'
                '<span style="color:#1A1A1A;">%{y:,.0f} MWmed</span>'
                '<extra></extra>'
            ),
        )
    )

    # Vline da quebra metodológica 29/04/2023 só faz sentido no eixo
    # temporal (Diária/Mensal/Horária) — em Dia Típico o eixo X é
    # categorial (00:00..23:00), data não bate.
    if (
        granularidade_gen != "Dia Típico"
        and data_ini_efetivo_gen <= quebra_data.date() <= data_fim_gen
    ):
        fig_c.add_vline(
            x=quebra_data,
            line_dash="dot",
            line_color=BAUHAUS_GRAY,
            line_width=1.2,
        )
        fig_c.add_annotation(
            x=quebra_data,
            y=1.02,
            yref="paper",
            text="ONS passa a incluir MMGD na carga",
            showarrow=False,
            font=dict(
                family="Inter, sans-serif",
                size=10,
                color=BAUHAUS_GRAY,
            ),
            align="center",
        )

    # Eixo X varia por granularidade: temporal (datetime, hoverformat
    # depende da granularidade) vs categorial em Dia Típico (24 strings
    # "HH:00", hovermode unified mostra a string direto).
    _xaxis_gen_dict = dict(
        title=None, showgrid=False, showline=True,
        linewidth=2, linecolor=BAUHAUS_BLACK,
        ticks="outside", tickcolor=BAUHAUS_BLACK,
        tickfont=dict(
            family="Inter, sans-serif",
            size=13, color=BAUHAUS_BLACK,
        ),
    )
    if granularidade_gen == "Dia Típico":
        _xaxis_gen_dict["type"] = "category"
    else:
        _xaxis_gen_dict["hoverformat"] = hover_fmt_gen

    fig_c.update_layout(
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
                size=17, color=BAUHAUS_BLACK,
            ),
        ),
        xaxis=_xaxis_gen_dict,
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
            tickformat=",.0f",
        ),
        font=dict(family="Inter, sans-serif", size=12),
    )

    st.plotly_chart(
        fig_c, use_container_width=True,
        config={"displaylogo": False},
    )

    # --- Notas de contexto (abaixo do gráfico) ---
    # Movidas pra cá na Sessão 4a pra preservar espaço above-the-fold dos
    # KPIs+gráfico. A 4ª nota (vline 29/04/2023) é condicional — só aparece
    # se a quebra está dentro do período visível.
    notas_gen = [
        f'Dados atualizados diariamente pelo ONS. Última atualização no '
        f'dataset: {ultima_data_gen.strftime("%d/%m/%Y %H:%M")}.',
        "A diferença entre a linha de carga e o total de geração "
        "corresponde ao intercâmbio líquido com outros subsistemas "
        "(importação/exportação) e perdas técnicas.",
        "Solar = apenas geração centralizada. MMGD não é publicada pelo "
        "ONS isoladamente — aparece embutida na carga desde 29/04/2023.",
    ]
    if data_ini_efetivo_gen <= quebra_data.date() <= data_fim_gen:
        notas_gen.append(
            "Linha pontilhada vertical em 29/04/2023: ONS passou a incluir "
            "MMGD (geração distribuída) na série de carga."
        )
    st.markdown(
        "".join(
            f'<div style="font-family:\'Inter\', sans-serif; '
            f'font-size:0.85rem; color:#6B6B6B; font-style:italic; '
            f'margin:0.4rem 0 0 0;">{n}</div>'
            for n in notas_gen
        ),
        unsafe_allow_html=True,
    )

    # --- Export CSV ---
    # Formato long-wide híbrido: 5 subsistemas empilhados verticalmente.
    # Colunas: Data | Subsistema | fonte1 | fonte2 | ... | Carga.
    # Tela ≠ CSV por design: dropdown controla o que é exibido, CSV mantém
    # os 5 submercados pra research. Reusa pivots_por_sub pré-populado.
    st.markdown("### Exportar")
    csv_cols_ord = ["hidro", "termica", "eolica", "solar", "carga"]
    csv_cols_labels = {
        "hidro":   "Hidráulica (MWmed)",
        "termica": "Térmica (MWmed)",
        "eolica":  "Eólica (MWmed)",
        "solar":   "Solar centralizada (MWmed)",
        "carga":   "Carga (MWmed)",
    }

    csv_frames = []
    for code in ORDEM_SUBSISTEMA_GEN:
        pv = pivots_por_sub.get(code)
        if pv is None:
            continue
        block = pv[csv_cols_ord].copy()
        block.insert(0, "Subsistema", LABELS_SUBSISTEMA_GEN[code])
        csv_frames.append(block)

    if csv_frames:
        if granularidade_gen == "Dia Típico":
            # Index é string "HH:00" (categorial) — sem conversão datetime.
            # Coluna chave é "Hora", não "Data".
            csv_all = (
                pd.concat(csv_frames)
                .reset_index()
                .rename(columns=csv_cols_labels)
            )
            csv_all = csv_all[
                ["Hora", "Subsistema"] + list(csv_cols_labels.values())
            ]
        else:
            csv_all = (
                pd.concat(csv_frames)
                .reset_index()
                .rename(columns={"data_hora": "Data", **csv_cols_labels})
            )
            # Formato de data por granularidade — alinhado com o eixo X
            data_fmt = {
                "Horária": "%d/%m/%Y %H:%M",
                "Diária":  "%d/%m/%Y",
                "Mensal":  "%m/%Y",
            }[granularidade_gen]
            csv_all["Data"] = pd.to_datetime(csv_all["Data"]).dt.strftime(data_fmt)
            csv_all = csv_all[
                ["Data", "Subsistema"] + list(csv_cols_labels.values())
            ]
        csv = csv_all.to_csv(
            index=False, sep=";", decimal=",",
        ).encode("utf-8-sig")

        gran_slug = {
            "Horária":    "horaria",
            "Diária":     "diaria",
            "Mensal":     "mensal",
            "Dia Típico": "dia_tipico",
        }[granularidade_gen]
        st.download_button(
            label="Baixar dados filtrados (CSV)",
            data=csv,
            file_name=(
                f"geracao_{gran_slug}_todos_subsistemas_"
                f"{data_ini_efetivo_gen}_a_{data_fim_gen}.csv"
            ),
            mime="text/csv",
            use_container_width=False,
        )

elif aba == "Geração" and st.session_state.get("geracao_subview", "SIN") == "Grupo":
    # -----------------------------------------------------------------------
    # Aba Geração — sub-view "Eólica/Solar por Grupo" (decisão 5.37 pendente).
    # Reusa o df pós-rateio da Curtailment (Caminho A) — mesma janela ampla
    # 15M e mesmo cache disco compartilhado via st.session_state["curt_janela_modo"].
    # Componentizada em components/tab_geracao_grupo.py.
    # -----------------------------------------------------------------------
    from components.tab_geracao_grupo import render_aba_geracao_grupo
    render_aba_geracao_grupo()

elif aba == "Carga":
    # -----------------------------------------------------------------------
    # Aba Carga — demanda elétrica por subsistema (val_carga do balanço ONS).
    # Reusa load_balanco_subsistema da Geração (mesmo dataset, mesmo cache).
    # Sessão 4a entrega Setup + KPIs + Glossário + Viz 1 (total vs líquida)
    # + Viz 2 (decomposição com ordem da carga líquida).
    # Sessão 4b adicionará Viz 3/4/5 (comparação anual, LDC, histograma rampas).
    # -----------------------------------------------------------------------
    st.markdown("# CARGA")
    st.markdown(
        '<div style="border-bottom: 2px solid #1A1A1A; '
        'margin: 0 0 -1.5rem 0;"></div>',
        unsafe_allow_html=True,
    )

    # --- Carregar dados ---
    # Compartilha gen_historico_completo com a aba Geração: ambas leem do
    # mesmo balanço ONS, então a flag de range (15a vs completo) é
    # naturalmente compartilhada. Trade-off conhecido: clicar "Carregar
    # histórico completo" em qualquer das 2 abas afeta a outra. Aceitável
    # — duplicar a flag obrigaria 2 disk-caches paralelos de 60MB cada.
    historico_completo_carga = st.session_state.get(
        "gen_historico_completo", False
    )
    if is_balanco_cache_fresh(historico_completo_carga):
        spinner_msg_carga = "Carregando dados de carga..."
    else:
        if historico_completo_carga:
            spinner_msg_carga = (
                "Baixando 27 anos de dados ONS (~25MB)... "
                "pode levar ~25s na primeira vez."
            )
        else:
            spinner_msg_carga = (
                "Baixando 15 anos de dados ONS (~12MB)... "
                "pode levar ~15s na primeira vez."
            )
    with st.spinner(spinner_msg_carga):
        try:
            df_carga = load_balanco_subsistema(
                incluir_historico_completo=historico_completo_carga,
            )
        except Exception as e:
            st.error(f"Falha ao carregar dados do ONS (balanço): {e}")
            debug = st.session_state.get("_debug_erros", [])
            if debug:
                st.subheader("Detalhes técnicos do erro")
                for d in debug[:20]:
                    st.code(d)
            st.stop()

    if df_carga.empty:
        st.warning("Nenhum dado disponível.")
        st.stop()

    ORDEM_SUBSISTEMA_CARGA = ["SIN", "SE", "S", "NE", "N"]
    LABELS_SUBSISTEMA_CARGA = {
        "SIN": "SIN",
        "SE":  "SUDESTE",
        "S":   "SUL",
        "NE":  "NORDESTE",
        "N":   "NORTE",
    }
    NOME_SUB_LONGO_CARGA = {
        "SIN": "SIN",
        "SE":  "Sudeste/Centro-Oeste",
        "S":   "Sul",
        "NE":  "Nordeste",
        "N":   "Norte",
    }

    # Backups paralelos pra dropdowns (decisão 5.18). Defesa preventiva
    # contra widget-state cleanup do Streamlit em ciclos pesados.
    _CARGA_GRAN_BACKUP = "_carga_granularidade_backup"
    _CARGA_SUB_BACKUP = "_carga_submercado_backup"
    if (
        "carga_granularidade" not in st.session_state
        and _CARGA_GRAN_BACKUP in st.session_state
    ):
        st.session_state["carga_granularidade"] = (
            st.session_state[_CARGA_GRAN_BACKUP]
        )
    if (
        "carga_submercado" not in st.session_state
        and _CARGA_SUB_BACKUP in st.session_state
    ):
        st.session_state["carga_submercado"] = (
            st.session_state[_CARGA_SUB_BACKUP]
        )

    # Default da 1ª visita absoluta na sessão: Diária (UX da aba Carga).
    # Diferente da Geração (Horária), porque o uso típico de Carga é
    # "como evoluiu a demanda nas últimas semanas/meses", não
    # "como foi nas últimas horas". Setado ANTES do selectbox (5.12).
    if "_carga_dataset_max" not in st.session_state:
        st.session_state["carga_granularidade"] = "Diária"

    # --- Controles: granularidade + submercado ---
    ctrl_cols_carga = st.columns([1.2, 1.8, 3.2])
    with ctrl_cols_carga[0]:
        granularidade_carga = st.selectbox(
            "Granularidade",
            ["Mensal", "Diária", "Horária", "Dia Típico"],
            index=1,  # default diária
            key="carga_granularidade",
        )
    with ctrl_cols_carga[1]:
        submercado_carga = st.selectbox(
            "Submercado",
            ORDEM_SUBSISTEMA_CARGA,
            index=0,  # default SIN
            key="carga_submercado",
            format_func=lambda c: NOME_SUB_LONGO_CARGA[c],
        )

    st.session_state[_CARGA_GRAN_BACKUP] = granularidade_carga
    st.session_state[_CARGA_SUB_BACKUP] = submercado_carga

    min_d_carga = df_carga["data_hora"].min().date()
    max_d_carga = df_carga["data_hora"].max().date()

    # =========================================================================
    # RESET BLOCK UNIFICADO (decisão 5.20) — 6 gatilhos completos.
    # Mesma estrutura do reset block da Geração (linhas ~2280-2315), com
    # keys prefixadas carga_*. Ver CLAUDE.md §5.20 + 5.16/5.19 + extensão
    # 1.6 do 6º gatilho (range degenerado >=).
    # =========================================================================
    em_horaria_carga = (
        st.session_state.get("carga_granularidade") == "Horária"
    )
    prev_gran_carga = st.session_state.get("_carga_last_gran")
    em_transicao_carga = (
        prev_gran_carga is not None
        and prev_gran_carga != granularidade_carga
    )
    force_reset_carga = st.session_state.pop("_carga_force_reset", False)

    if (
        force_reset_carga
        or "_carga_dataset_max" not in st.session_state
        or st.session_state.get("_carga_dataset_max") != max_d_carga
        or st.session_state.get("_carga_dataset_min") != min_d_carga
        or em_transicao_carga
        or (
            not em_horaria_carga
            and (
                "carga_data_ini" not in st.session_state
                or "carga_data_fim" not in st.session_state
            )
        )
        or (
            not em_horaria_carga
            and "carga_data_ini" in st.session_state
            and "carga_data_fim" in st.session_state
            and st.session_state["carga_data_ini"]
                >= st.session_state["carga_data_fim"]
        )
    ):
        _aplica_default_periodo_carga(
            granularidade_carga, min_d_carga, max_d_carga
        )
        st.session_state["_carga_dataset_max"] = max_d_carga
        st.session_state["_carga_dataset_min"] = min_d_carga

    st.session_state["_carga_last_gran"] = granularidade_carga

    # --- Período: modo depende da granularidade (idêntico à Geração) ---
    if granularidade_carga == "Horária":
        if not st.session_state.get("carga_data_base"):
            st.session_state["carga_data_base"] = min(
                max_d_carga,
                st.session_state.get("carga_data_fim") or max_d_carga,
            )
        if "carga_horaria_window_dias" not in st.session_state:
            st.session_state["carga_horaria_window_dias"] = 1

        presets_hora_carga = [
            ("1D",  1,  False),
            ("7D",  7,  False),
            ("30D", 30, False),
            ("90D", 90, False),
        ]
        _render_period_controls_horaria(
            presets=presets_hora_carga,
            session_key_base="carga_data_base",
            session_key_window="carga_horaria_window_dias",
            key_prefix="btn_carga_hora_",
            min_d=min_d_carga,
            max_d=max_d_carga,
        )

        window_carga = st.session_state["carga_horaria_window_dias"]
        data_base_carga = st.session_state["carga_data_base"]
        data_fim_carga = data_base_carga
        data_ini_carga = max(
            min_d_carga, data_base_carga - timedelta(days=window_carga - 1)
        )
        st.session_state["carga_data_ini"] = data_ini_carga
        st.session_state["carga_data_fim"] = data_fim_carga
    else:
        data_ini_carga = st.session_state["carga_data_ini"]
        data_fim_carga = st.session_state["carga_data_fim"]

        if data_ini_carga > data_fim_carga:
            st.error("A data inicial não pode ser posterior à data final.")
            st.stop()

        if granularidade_carga == "Mensal":
            # 15A removido na Sessão 4a (decisão 5.27): degenerava pra Máx
            # no dataset padrão (~14a), tooltip dinâmico do Máx esclarece
            # o range real conforme gen_historico_completo.
            presets_carga = [
                ("3M",  90,   False),
                ("6M",  180,  False),
                ("12M", 365,  False),
                ("5A",  1825, False),
                ("10A", 3650, False),
                ("Máx", None, True),
            ]
        elif granularidade_carga == "Dia Típico":
            presets_carga = [
                ("7D",  7,    False),
                ("30D", 30,   False),
                ("90D", 90,   False),
                ("6M",  180,  False),
                ("12M", 365,  False),
                ("5A",  1825, False),
            ]
        else:  # Diária
            presets_carga = [
                ("1M",  30,   False),
                ("3M",  90,   False),
                ("6M",  180,  False),
                ("12M", 365,  False),
                ("5A",  1825, False),
                ("10A", 3650, False),
                ("Máx", None, True),
            ]
        _render_period_controls(
            presets=presets_carga,
            session_key_ini="carga_data_ini",
            session_key_fim="carga_data_fim",
            key_prefix="btn_carga_",
            min_d=min_d_carga,
            max_d=max_d_carga,
        )
        data_ini_carga = st.session_state["carga_data_ini"]
        data_fim_carga = st.session_state["carga_data_fim"]

    # --- Botão "Estender histórico para 2000" (compartilhado com Geração) ---
    # margin-top negativo (texto ativo) + CSS global em st-key-btn_carga_…
    # (botão inativo) colam ambos nos presets acima — mesma estratégia da
    # Geração pra coerência visual.
    if historico_completo_carga:
        st.markdown(
            '<div style="font-family:\'Inter\', sans-serif; '
            'font-size:0.8rem; color:#4A4A4A; font-weight:500; '
            'margin:-0.8rem 0 0 0;">'
            '✓ Histórico estendido ativo (desde 2000)'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        if st.button(
            "Estender histórico para 2000",
            key="btn_carga_historico_completo",
            help="Adiciona dados de 2000-2010 ao range disponível "
                 "(compartilhado com a aba Geração — afeta as duas). "
                 "Demora ~30s na primeira vez (depois fica em cache).",
        ):
            _confirmar_historico_completo_gen()

    # --- Teto 90 dias na Horária ---
    periodo_dias_carga = (data_fim_carga - data_ini_carga).days
    if granularidade_carga == "Horária" and periodo_dias_carga > 90:
        st.warning(
            f"Granularidade horária limitada a 90 dias (seria "
            f"{periodo_dias_carga} dias). Mostrando os últimos 90 dias do "
            f"intervalo selecionado."
        )
        data_ini_efetivo_carga = data_fim_carga - timedelta(days=90)
    else:
        data_ini_efetivo_carga = data_ini_carga

    # --- Guards ---
    if (
        granularidade_carga == "Mensal"
        and (data_fim_carga - data_ini_efetivo_carga).days < 60
    ):
        st.warning(
            "Mensal precisa de pelo menos 2 meses. Selecione um período "
            "maior ou troque pra Diária."
        )
        st.stop()
    if (
        granularidade_carga == "Dia Típico"
        and (data_fim_carga - data_ini_efetivo_carga).days < 7
    ):
        st.warning(
            "Dia típico precisa de pelo menos 7 dias pra ser "
            "representativo. Selecione um período maior ou troque pra "
            "Diária pra ver dia específico."
        )
        st.stop()

    # --- Pivot helpers (mesmo padrão da Geração, com 'intercambio' incluído) ---
    # Diferença vs Geração: a Carga vai precisar de 'intercambio' na Viz 2
    # (decomposição = hidro+térmica+eólica+solar+intercâmbio = carga). Na
    # Geração, intercambio não é exposto. Mantemos os 2 pivots independentes
    # pra não acoplar; a duplicação é ~20 linhas, aceitável.
    freq_map_carga = {
        "Horária":    None,
        "Diária":     "D",
        "Mensal":     "MS",
        "Dia Típico": None,
    }
    freq_carga = freq_map_carga[granularidade_carga]

    data_ini_ts_carga = pd.Timestamp(data_ini_efetivo_carga)
    data_fim_ts_carga = pd.Timestamp(data_fim_carga)

    _COLUNAS_CARGA = ["hidro", "termica", "eolica", "solar", "carga", "intercambio"]

    def _build_pivot_carga(code):
        mask = (
            (df_carga["submercado"] == code)
            & (df_carga["data"] >= data_ini_ts_carga)
            & (df_carga["data"] <= data_fim_ts_carga)
        )
        dff = df_carga.loc[mask]
        if dff.empty:
            return None
        pivot = dff.pivot_table(
            index="data_hora", columns="fonte", values="mwmed",
            aggfunc="mean",
        ).sort_index()
        if freq_carga is not None:
            pivot = pivot.resample(freq_carga).mean()
        for col in _COLUNAS_CARGA:
            if col not in pivot.columns:
                pivot[col] = 0.0
        pivot[_COLUNAS_CARGA] = pivot[_COLUNAS_CARGA].fillna(0)
        return pivot

    def _build_dia_tipico_carga(code):
        """Reagrega pivot horário por hora-do-dia (decisão 5.25)."""
        pivot_horario = _build_pivot_carga(code)
        if pivot_horario is None or pivot_horario.empty:
            return None
        pivot = pivot_horario.groupby(pivot_horario.index.hour).mean()
        pivot.index = [f"{h:02d}:00" for h in pivot.index]
        pivot.index.name = "Hora"
        return pivot

    pivots_por_sub_carga = {}
    _build_pivot_carga_dispatch = (
        _build_dia_tipico_carga
        if granularidade_carga == "Dia Típico"
        else _build_pivot_carga
    )
    for code in ORDEM_SUBSISTEMA_CARGA:
        pv = _build_pivot_carga_dispatch(code)
        if pv is not None:
            pivots_por_sub_carga[code] = pv

    pivot_sel_carga = pivots_por_sub_carga.get(submercado_carga)
    if pivot_sel_carga is None:
        st.warning(
            f"Sem dados de {NOME_SUB_LONGO_CARGA[submercado_carga]} "
            "no intervalo selecionado."
        )
        st.stop()

    # =========================================================================
    # KPIs (Bloco 3 da Sessão 4a) — 5 cards em layout 3+2 (decisão de
    # implementação). Linha 1: estado médio do sistema (carga total,
    # líquida, % renov). Linha 2: estresse operacional (rampas 1h, 3h).
    # Agrupamento semântico tem valor analítico além de evitar 5 cards
    # apertados em 1 linha (max-width 1000px ≈ 190px/card seria estreito).
    # Tooltips via title="" no card pai (browser nativo, sem JS).
    # =========================================================================
    kpis_carga = _compute_kpis_carga(
        df_carga, submercado_carga, data_ini_efetivo_carga, data_fim_carga,
    )

    def _fmt_br_carga(v, casas=0):
        """Número BR: 1.234 (milhar ponto, decimal vírgula)."""
        if v is None or (hasattr(v, "__float__") and not (v == v)):
            return "—"
        fmt = f"{{:,.{casas}f}}"
        return fmt.format(v).replace(",", "X").replace(".", ",").replace("X", ".")

    def _fmt_ts_compact_carga(ts):
        """Formato compacto pra timestamp de pico de rampa: 'DD/MM HHh'."""
        if ts is None or (hasattr(ts, "isna") and ts.isna()):
            return ""
        return f"{ts.strftime('%d/%m')} {ts.strftime('%H')}h"

    # CSS dedicado .carga-kpi-* (cópia do .gen-kpi-* da Geração).
    # Duplicação consciente: refator pra .kpi-* genérico fica pra futuro
    # (não mexer no bloco Geração estável agora). +1 propriedade vs gen-kpi:
    # cursor:help no card quando há tooltip — sinal visual de hoverable.
    st.markdown(
        """
        <style>
        .carga-kpi-card {
            background: #F5F1E8;
            border: 2px solid #1A1A1A;
            padding: 8px 12px;
            border-radius: 0;
            min-height: 6.5rem;     /* alinha % Renov (1 row) com as multi (2 rows) */
            box-sizing: border-box; /* padding inclusive no min-height */
        }
        .carga-kpi-card[title] {
            cursor: help;
        }
        .carga-kpi-label {
            font-family: 'Inter', sans-serif;
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.16em;
            color: #1A1A1A;
            font-weight: 700;
            line-height: 1.2;
        }
        /* Row interna: número à esquerda + subtext à direita (rampas 1h/3h
           usam subtext pra mostrar timestamp do pico). Cards sem subtext
           (Carga Total/Líquida/% Renov) ficam visualmente idênticos —
           subtext é opcional via parâmetro do helper. */
        .carga-kpi-value-row {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            margin-top: 0.15rem;
            gap: 0.5rem;
        }
        .carga-kpi-value {
            display: flex;
            align-items: baseline;
        }
        .carga-kpi-value-num {
            font-family: 'Bebas Neue', sans-serif;
            font-size: 1.45rem;
            color: #1A1A1A;
            letter-spacing: 0.02em;
            line-height: 1.1;
        }
        .carga-kpi-value-unit {
            font-family: 'Inter', sans-serif;
            font-size: 0.85rem;
            color: #1A1A1A;
            font-weight: 600;
            margin-left: 0.4rem;
        }
        .carga-kpi-subtext {
            font-family: 'Inter', sans-serif;
            font-size: 0.8rem;
            color: #1A1A1A;
            text-align: right;
            line-height: 1.25;
            white-space: nowrap;
        }
        /* Card multi-linha: usado em "CARGA MÉDIA" / "PICO DE CARGA"
           (Total + Líquida) e "RAMPA MÁXIMA" (1H + 3H). Grid 2-col com
           col 1 = max-content (rótulo, largura mínima) e col 2 = auto
           (valor + unidade + ts opcional). Auto-alinha valores entre
           rows do MESMO card sem precisar min-width por preset; cada
           card tem seu próprio grid (largura da col 1 varia por preset:
           "Líquida:" wide em Carga Média/Pico, "3H:" narrow em Rampa). */
        .carga-kpi-multi-rows {
            display: grid;
            grid-template-columns: max-content auto;
            column-gap: 0.6rem;
            row-gap: 0.3rem;
            margin-top: 0.3rem;
            align-items: baseline;
        }
        .carga-kpi-multi-valor-cell {
            /* Wrapper: valor + unidade + ts juntos na mesma cell grid */
            display: inline-flex;
            align-items: baseline;
        }
        .carga-kpi-multi-rotulo {
            font-family: 'Inter', sans-serif;
            font-size: 0.85rem;
            color: #1A1A1A;
            font-weight: 600;
        }
        .carga-kpi-multi-valor {
            font-family: 'Bebas Neue', sans-serif;
            font-size: 1.25rem;
            color: #1A1A1A;
            letter-spacing: 0.02em;
        }
        .carga-kpi-multi-unit {
            font-family: 'Inter', sans-serif;
            font-size: 0.75rem;
            color: #1A1A1A;
            font-weight: 600;
            margin-left: 0.3rem;
        }
        .carga-kpi-multi-ts {
            font-family: 'Inter', sans-serif;
            font-size: 0.75rem;
            color: #6B6B6B;
            margin-left: 0.4rem;
            white-space: nowrap;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    def _render_kpi_carga(label, num, unit="", tooltip="", subtext=""):
        """Card KPI Bauhaus.

        subtext (opcional): texto pequeno à direita do número (mesma row,
        space-between). Usa <br> dentro pra quebrar em 2 linhas. Hoje é
        usado pelos cards de rampa pra mostrar 'em<br>DD/MM/YYYY HH:MM'.
        """
        unit_html = (
            f'<span class="carga-kpi-value-unit">{unit}</span>'
            if unit else ""
        )
        subtext_html = (
            f'<div class="carga-kpi-subtext">{subtext}</div>'
            if subtext else ""
        )
        title_attr = f' title="{tooltip}"' if tooltip else ""
        return (
            f'<div class="carga-kpi-card"{title_attr}>'
            f'<div class="carga-kpi-label">{label}</div>'
            f'<div class="carga-kpi-value-row">'
            f'<div class="carga-kpi-value">'
            f'<span class="carga-kpi-value-num">{num}</span>{unit_html}'
            f'</div>'
            f'{subtext_html}'
            f'</div>'
            f'</div>'
        )

    def _render_kpi_carga_multi(label, linhas, tooltip=""):
        """Card KPI Bauhaus com múltiplas linhas internas (CSS grid 2-col).

        linhas: lista de dicts com chaves:
          - rotulo: str — rótulo à esquerda (ex: "Total", "1H")
          - valor:  str — número formatado BR (ex: "79.149")
          - unit:   str opcional — unidade após o número (ex: "MWmed")
          - ts:     str opcional — timestamp compacto após a unidade
                     (ex: "19/04 16h"), em fonte menor cinza

        HTML: 1 div .carga-kpi-multi-rows (grid container) com células
        alternando rótulo/valor — grid auto-alinha valores entre rows
        do mesmo card.
        """
        title_attr = f' title="{tooltip}"' if tooltip else ""
        cells_html = ""
        for ln in linhas:
            ts_html = (
                f'<span class="carga-kpi-multi-ts">({ln["ts"]})</span>'
                if ln.get("ts") else ""
            )
            unit_html = (
                f'<span class="carga-kpi-multi-unit">{ln["unit"]}</span>'
                if ln.get("unit") else ""
            )
            cells_html += (
                f'<span class="carga-kpi-multi-rotulo">{ln["rotulo"]}:</span>'
                f'<span class="carga-kpi-multi-valor-cell">'
                f'<span class="carga-kpi-multi-valor">{ln["valor"]}</span>'
                f'{unit_html}{ts_html}'
                f'</span>'
            )
        return (
            f'<div class="carga-kpi-card"{title_attr}>'
            f'<div class="carga-kpi-label">{label}</div>'
            f'<div class="carga-kpi-multi-rows">{cells_html}</div>'
            f'</div>'
        )

    # Caption acima dos KPIs — segue padrão da Geração ("Médias do período...").
    # margin-bottom 0 (não -0.8rem como na Geração): na Carga o bloco
    # <style> dos cards foi declarado ANTES do caption (linha ~3728), então
    # só há UM gap default do stVerticalBlock entre caption e cards. Na
    # Geração, o <style> vem entre caption e cards (~2945), criando 2 gaps
    # — daí o -0.8rem agressivo lá funciona. Aqui margem zero deixa o gap
    # natural do Streamlit dar o respiro visual entre caption e KPIs.
    st.markdown(
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.85rem; color:#6B6B6B; font-style:italic; '
        f'margin:0.6rem 0 0 0;">'
        f'Indicadores do período selecionado '
        f'({NOME_SUB_LONGO_CARGA[submercado_carga]}). '
        f'Passe o mouse sobre cada KPI pra ver a definição.'
        f'</div>',
        unsafe_allow_html=True,
    )

    # 4 caixas em 1 linha. Proporção [1, 1.4, 1.4, 0.8] — Pico e Rampa
    # precisam de mais espaço pelos timestamps "(DD/MM HHh)" extras em
    # cada linha interna; % Renov é só 1 valor, comporta menos espaço.
    # Caixa 1: CARGA MÉDIA       (Total + Líquida).
    # Caixa 2: PICO DE CARGA     (Total + Líquida, com timestamp).
    # Caixa 3: RAMPA MÁXIMA      (1H + 3H, com timestamp).
    # Caixa 4: % RENOV VARIÁVEIS (1 valor — usa helper single original).
    kpi_cols = st.columns([1, 1.4, 1.4, 0.8])

    with kpi_cols[0]:
        st.markdown(
            _render_kpi_carga_multi(
                "CARGA MÉDIA",
                [
                    {
                        "rotulo": "Total",
                        "valor":  _fmt_br_carga(kpis_carga["carga_total_media"]),
                        "unit":   "MWmed",
                    },
                    {
                        "rotulo": "Líquida",
                        "valor":  _fmt_br_carga(kpis_carga["carga_liquida_media"]),
                        "unit":   "MWmed",
                    },
                ],
                tooltip=(
                    "Total: soma de toda demanda elétrica do subsistema "
                    "(inclui MMGD pós-29/04/2023). "
                    "Líquida: total menos eólica e solar centralizada — "
                    "o que hidro+térmica precisa cobrir."
                ),
            ),
            unsafe_allow_html=True,
        )

    with kpi_cols[1]:
        st.markdown(
            _render_kpi_carga_multi(
                "PICO DE CARGA",
                [
                    {
                        "rotulo": "Total",
                        "valor":  _fmt_br_carga(kpis_carga["pico_carga_total"]),
                        "unit":   "MWmed",
                        "ts":     _fmt_ts_compact_carga(
                            kpis_carga["pico_carga_total_ts"]
                        ),
                    },
                    {
                        "rotulo": "Líquida",
                        "valor":  _fmt_br_carga(kpis_carga["pico_carga_liquida"]),
                        "unit":   "MWmed",
                        "ts":     _fmt_ts_compact_carga(
                            kpis_carga["pico_carga_liquida_ts"]
                        ),
                    },
                ],
                tooltip=(
                    "Maior valor instantâneo de carga no período. "
                    "Total: pico da demanda total. "
                    "Líquida: pico do que hidro+térmica precisa cobrir."
                ),
            ),
            unsafe_allow_html=True,
        )

    with kpi_cols[2]:
        st.markdown(
            _render_kpi_carga_multi(
                "RAMPA MÁXIMA",
                [
                    {
                        "rotulo": "1H",
                        "valor":  _fmt_br_carga(kpis_carga["rampa_max_1h"]),
                        "unit":   "MW",
                        "ts":     _fmt_ts_compact_carga(
                            kpis_carga["rampa_max_1h_ts"]
                        ),
                    },
                    {
                        "rotulo": "3H",
                        "valor":  _fmt_br_carga(kpis_carga["rampa_max_3h"]),
                        "unit":   "MW",
                        "ts":     _fmt_ts_compact_carga(
                            kpis_carga["rampa_max_3h_ts"]
                        ),
                    },
                ],
                tooltip=(
                    "Maior variação de carga líquida em 1h e 3h consecutivas. "
                    "Captura picos de estresse operacional "
                    "(3h ≈ duck curve, rampa de fim de tarde)."
                ),
            ),
            unsafe_allow_html=True,
        )

    with kpi_cols[3]:
        st.markdown(
            _render_kpi_carga(
                "% RENOV VARIÁVEIS",
                f"{_fmt_br_carga(kpis_carga['pct_renov_var'], casas=1)}%",
                tooltip=(
                    "Participação de eólica+solar centralizada. Não inclui "
                    "hidro (despachável) nem MMGD."
                ),
            ),
            unsafe_allow_html=True,
        )

    # =========================================================================
    # Glossário (st.expander, fechado por default). Posicionado APÓS os
    # KPIs e ANTES das visualizações: leitura natural dos números primeiro,
    # contexto profundo sob demanda. Tooltips dos KPIs cobrem a 1ª linha
    # de definição; glossário aprofunda quando o leitor quer entender o
    # "por que importa".
    # =========================================================================
    with st.expander("ⓘ Glossário"):
        # Ordem espelha o layout dos cards (linha 1: Total/Líquida/% Renov;
        # linha 2: Rampas) + Rampa Máxima por último (texto mais longo
        # com comparação histórica 2015→2024). Capitalização dos termos
        # bate exatamente com a label dos cards pra leitor associar.
        st.markdown(
            """
**Carga Total**
Demanda elétrica medida pelo ONS. Inclui MMGD pós-29/04/2023 (geração
distribuída embutida na carga).

**Carga Líquida**
Carga total menos eólica e solar centralizada. Representa a demanda
"residual" que hidro+térmica+importação precisam cobrir. Métrica-chave
pra planejamento operacional do sistema.

**Pico de Carga**
Maior valor instantâneo de carga no período (granularidade horária).
- *Total*: maior demanda elétrica registrada (com timestamp).
- *Líquida*: maior valor que hidro+térmica precisou cobrir.

**% Renováveis Variáveis**
Participação de eólica+solar centralizada na carga total. Variáveis =
não-despacháveis (dependem do recurso natural). Não inclui hidro
(despachável via reservatórios) nem MMGD (telhados/fachadas, embutida
na carga pós-2023).

**Rampa Máxima (1h e 3h)**
Variação de carga líquida em janelas de tempo consecutivas. Indicador
de quanto a hidro+térmica precisa subir ou descer geração rapidamente
pra acompanhar a demanda.

A janela de **1h** captura picos instantâneos — momentos extremos onde
a rede precisa reagir rápido (ex: nuvem cobre uma usina solar grande
de repente).

A janela de **3h** é o padrão internacional (referência: duck curve
CAISO Califórnia 2013). Captura a rampa típica de fim de tarde, quando
solar some entre 17h-20h e hidro+térmica precisam compensar gradualmente.

Em 2015 as rampas de 3h no SIN ficavam em torno de ~5 GW. Em 2024 já
se observam picos próximos a ~20 GW — quase 4× maiores, causados pela
penetração da solar centralizada.
            """
        )

    # =========================================================================
    # VIZ 1 (Bloco 4) — Carga Total vs Carga Líquida sobrepostas.
    #
    # 2 linhas:
    #   - Carga Total   (azul Bauhaus)
    #   - Carga Líquida (vermelho Bauhaus, definida = carga - eólica - solar)
    # Área entre as 2 linhas sombreada com verde-oliva sutil (mesma cor
    # eólica do stacked da Geração) = "renováveis variáveis cobriram esse
    # gap". Trace fake na legenda documenta a semântica da área (sem ele
    # a sombra fica críptica).
    #
    # Vline 29/04/2023 só em modos temporais (Diária/Mensal/Horária) — em
    # Dia Típico o eixo X é categorial e Timestamp não bate.
    # =========================================================================
    OLIVA_RGBA_FILL    = "rgba(143, 163, 30, 0.18)"  # área entre linhas
    OLIVA_RGBA_LEGENDA = "rgba(143, 163, 30, 0.6)"   # marker fake da legenda

    tag_granularidade_carga = {
        "Mensal":     "Média mensal · MWmed",
        "Diária":     "Média diária · MWmed",
        "Horária":    "Valor horário · MWmed",
        "Dia Típico": (
            "Dia típico (média horária do período selecionado) · MWmed"
        ),
    }[granularidade_carga]

    hover_fmt_carga = {
        "Horária":    "%d/%m/%Y %H:%M",
        "Diária":     "%d/%m/%Y",
        "Mensal":     "%b %Y",
        "Dia Típico": None,  # eixo X categorial
    }[granularidade_carga]

    periodo_str_carga = _format_periodo_br(
        data_ini_efetivo_carga, data_fim_carga, granularidade_carga,
    )

    label_sub_carga = LABELS_SUBSISTEMA_CARGA[submercado_carga]

    # margin-top aumentado de 1.2rem → 2.6rem na Sessão 4a pra separar
    # visualmente o bloco "caption + KPIs" do bloco "título + gráfico".
    # Mesmo valor da Geração — coerência visual entre as 2 abas.
    st.markdown(
        f'<div style="display:flex; justify-content:space-between; '
        f'align-items:baseline; '
        f'font-family:\'Bebas Neue\', sans-serif; '
        f'font-size:1.1rem; letter-spacing:0.08em; color:#1A1A1A; '
        f'margin: 2.6rem 0 0.3rem 0; padding-bottom:3px; '
        f'border-bottom: 2px solid #1A1A1A;">'
        f'<span>{label_sub_carga} · CARGA TOTAL VS LÍQUIDA</span>'
        f'<span>{periodo_str_carga}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.9rem; color:#1A1A1A; font-weight:500; '
        f'letter-spacing:0.04em; margin:0 0 0.5rem 0;">'
        f'{tag_granularidade_carga}'
        f'</div>',
        unsafe_allow_html=True,
    )

    if granularidade_carga == "Horária" and periodo_dias_carga >= 30:
        st.caption(
            "Granularidade horária com janela longa — "
            "renderização pode levar alguns segundos."
        )

    # Série carga líquida = carga - eólica - solar (mesma instante).
    # pivot_sel_carga já tem fillna(0) nas colunas, então aritmética é segura.
    carga_total_series = pivot_sel_carga["carga"]
    carga_liquida_series = (
        pivot_sel_carga["carga"]
        - pivot_sel_carga["eolica"]
        - pivot_sel_carga["solar"]
    )

    fig_v1 = go.Figure()

    # Trace 1: Carga Total (azul, sem fill — referência pro tonexty abaixo).
    total_label_fix = "Total".ljust(11).replace(" ", "&nbsp;")
    fig_v1.add_trace(
        go.Scatter(
            x=carga_total_series.index,
            y=carga_total_series.values,
            # Trailing spaces (3) criam respiro extra na legenda — Plotly
            # não tem itemgap em legend, então este é o truque mais limpo
            # pra separar de "Carga Líquida" sem CSS.
            name="Carga Total   ",
            mode="lines",
            line=dict(color=BAUHAUS_BLUE, width=2.2),
            hovertemplate=(
                f'<span style="color:{BAUHAUS_BLUE}; font-weight:700;">'
                f'{total_label_fix}</span>'
                '&nbsp;&nbsp;'
                '<span style="color:#1A1A1A;">%{y:,.0f} MWmed</span>'
                '<extra></extra>'
            ),
        )
    )

    # Trace 2: Carga Líquida (vermelha) com fill='tonexty' → preenche
    # entre esta linha (embaixo, total > líquida) e o trace anterior
    # (carga total, em cima). Resultado: faixa verde-oliva entre as duas.
    liquida_label_fix = "Líquida".ljust(11).replace(" ", "&nbsp;")
    fig_v1.add_trace(
        go.Scatter(
            x=carga_liquida_series.index,
            y=carga_liquida_series.values,
            name="Carga Líquida   ",
            mode="lines",
            line=dict(color=BAUHAUS_RED, width=2.2),
            fill="tonexty",
            fillcolor=OLIVA_RGBA_FILL,
            hovertemplate=(
                f'<span style="color:{BAUHAUS_RED}; font-weight:700;">'
                f'{liquida_label_fix}</span>'
                '&nbsp;&nbsp;'
                '<span style="color:#1A1A1A;">%{y:,.0f} MWmed</span>'
                '<extra></extra>'
            ),
        )
    )

    # Trace fake só pra documentar a área verde na legenda. Marker square
    # verde-oliva (0.6 alpha pra ser visível como ícone), sem dado real,
    # hover desativado. Sem ele a sombra entre as linhas fica críptica.
    fig_v1.add_trace(
        go.Scatter(
            x=[None], y=[None],
            name="Renováveis variáveis cobriram",
            mode="markers",
            marker=dict(
                color=OLIVA_RGBA_LEGENDA,
                size=14,
                symbol="square",
                line=dict(color=BAUHAUS_BLACK, width=1),
            ),
            showlegend=True,
            hoverinfo="skip",
        )
    )

    # Vline 29/04/2023 (quebra MMGD — ONS passa a incluir geração distribuída
    # na série de carga). Só faz sentido em eixo temporal.
    quebra_data_carga = pd.Timestamp(2023, 4, 29)
    if (
        granularidade_carga != "Dia Típico"
        and data_ini_efetivo_carga <= quebra_data_carga.date() <= data_fim_carga
    ):
        fig_v1.add_vline(
            x=quebra_data_carga,
            line_dash="dot",
            line_color=BAUHAUS_GRAY,
            line_width=1.2,
        )
        fig_v1.add_annotation(
            x=quebra_data_carga,
            y=1.02,
            yref="paper",
            text="ONS passa a incluir MMGD na carga",
            showarrow=False,
            font=dict(
                family="Inter, sans-serif",
                size=10,
                color=BAUHAUS_GRAY,
            ),
            align="center",
        )

    _xaxis_v1_dict = dict(
        title=None, showgrid=False, showline=True,
        linewidth=2, linecolor=BAUHAUS_BLACK,
        ticks="outside", tickcolor=BAUHAUS_BLACK,
        tickfont=dict(
            family="Inter, sans-serif",
            size=13, color=BAUHAUS_BLACK,
        ),
    )
    if granularidade_carga == "Dia Típico":
        _xaxis_v1_dict["type"] = "category"
    else:
        _xaxis_v1_dict["hoverformat"] = hover_fmt_carga

    fig_v1.update_layout(
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
            # Bebas Neue 19 (vs 17 da Geração). Plotly NÃO suporta itemgap
            # em legend (testado, lança ValueError). Pra criar respiro entre
            # entradas com label longo ("Renováveis variáveis cobriram"),
            # o caminho é (a) bump no font.size — texto maior espaça
            # naturalmente — e (b) trailing spaces nos nomes dos traces
            # mais curtos (vide name="Carga Total   ").
            font=dict(
                family="Bebas Neue, sans-serif",
                size=19, color=BAUHAUS_BLACK,
            ),
        ),
        xaxis=_xaxis_v1_dict,
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
            tickformat=",.0f",
        ),
        font=dict(family="Inter, sans-serif", size=12),
    )

    st.plotly_chart(
        fig_v1, use_container_width=True,
        config={"displaylogo": False},
    )

    # =========================================================================
    # VIZ 2 (Bloco 5) — Decomposição com ordem da carga líquida.
    # Decisões 5.31 + 5.32 do CLAUDE.md.
    #
    # Stacked area com 4 camadas (de baixo pra cima):
    #   solar → eólica → hidro → térmica
    # Renováveis variáveis embaixo "abatem" da carga total — a altura
    # cumulativa solar+eólica marca a CARGA LÍQUIDA. Despacháveis
    # hidro+térmica acima cobrem o que sobra.
    #
    # Linha de carga total sobreposta (dot, preto fino) evidencia o
    # "fecho" do balanço. Em SIN, cola no topo do stack (intercâmbio
    # internacional ~0). Em submercado, gap entre topo do stack e linha
    # = intercâmbio interno.
    #
    # Intercâmbio é stack-aware híbrido (5.32):
    #   - SIN: omitido (sem trace)
    #   - Submercado: trace lines sobreposto (cinza dashdot), preserva sinal
    #
    # Dia Típico (xaxis categorial + stackgroup) implementado no Sub-bloco
    # 5.5 — pattern já validado na Geração desde Sessão 2.
    # =========================================================================

    # Cores das 4 fontes vêm da paleta canônica (constantes
    # COR_FONTE_* no topo do arquivo — decisão 5.33). Cores
    # específicas desta viz (intercâmbio + linha de fecho) ficam
    # locais.
    COR_INTERC_V2  = "#9B9B9B"  # cinza neutro (5.32)
    COR_CARGA_V2   = BAUHAUS_BLACK  # linha de fecho dotted

    # Título Bauhaus (mesmo padrão da Viz 1).
    st.markdown(
        f'<div style="display:flex; justify-content:space-between; '
        f'align-items:baseline; '
        f'font-family:\'Bebas Neue\', sans-serif; '
        f'font-size:1.1rem; letter-spacing:0.08em; color:#1A1A1A; '
        f'margin: 2.6rem 0 0.3rem 0; padding-bottom:3px; '
        f'border-bottom: 2px solid #1A1A1A;">'
        f'<span>{label_sub_carga} · COMPOSIÇÃO DA CARGA TOTAL</span>'
        f'<span>{periodo_str_carga}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.9rem; color:#1A1A1A; font-weight:500; '
        f'letter-spacing:0.04em; margin:0 0 0.5rem 0;">'
        f'{tag_granularidade_carga}'
        f'</div>',
        unsafe_allow_html=True,
    )

    fig_v2 = go.Figure()

    # Convenção desta viz (diverge da Viz 1 deliberadamente):
    # - name= recebe label LIMPO (sem trailing spaces) — legenda
    #   tem 6 entradas, fica densa o suficiente sem o truque de
    #   respiro da Viz 1.
    # - hover label usa ljust(11) + nbsp pra alinhar siglas em
    #   monospace no hovermode unified — preserva legibilidade
    #   independente de sigla curta (Solar/Hidro) ou longa
    #   (Intercâmbio, Carga total).

    # Trace 1: SOLAR (camada de baixo do stack).
    solar_lbl = "Solar".ljust(11).replace(" ", "&nbsp;")
    fig_v2.add_trace(
        go.Scatter(
            x=pivot_sel_carga.index,
            y=pivot_sel_carga["solar"].values,
            name="Solar",
            mode="lines",
            stackgroup="oferta",
            line=dict(color=COR_FONTE_SOLAR, width=0.5),
            fillcolor=COR_FONTE_SOLAR,
            hovertemplate=(
                f'<span style="color:{COR_FONTE_SOLAR}; font-weight:700;">'
                f'{solar_lbl}</span>'
                '&nbsp;&nbsp;'
                '<span style="color:#1A1A1A;">%{y:,.0f} MWmed</span>'
                '<extra></extra>'
            ),
        )
    )

    # Trace 2: EÓLICA (em cima da solar — completa renováveis variáveis).
    eolica_lbl = "Eólica".ljust(11).replace(" ", "&nbsp;")
    fig_v2.add_trace(
        go.Scatter(
            x=pivot_sel_carga.index,
            y=pivot_sel_carga["eolica"].values,
            name="Eólica",
            mode="lines",
            stackgroup="oferta",
            line=dict(color=COR_FONTE_EOLICA, width=0.5),
            fillcolor=COR_FONTE_EOLICA,
            hovertemplate=(
                f'<span style="color:{COR_FONTE_EOLICA}; font-weight:700;">'
                f'{eolica_lbl}</span>'
                '&nbsp;&nbsp;'
                '<span style="color:#1A1A1A;">%{y:,.0f} MWmed</span>'
                '<extra></extra>'
            ),
        )
    )

    # Trace 3: HIDRO (despachável, em cima das renováveis variáveis).
    hidro_lbl = "Hidro".ljust(11).replace(" ", "&nbsp;")
    fig_v2.add_trace(
        go.Scatter(
            x=pivot_sel_carga.index,
            y=pivot_sel_carga["hidro"].values,
            name="Hidro",
            mode="lines",
            stackgroup="oferta",
            line=dict(color=COR_FONTE_HIDRO, width=0.5),
            fillcolor=COR_FONTE_HIDRO,
            hovertemplate=(
                f'<span style="color:{COR_FONTE_HIDRO}; font-weight:700;">'
                f'{hidro_lbl}</span>'
                '&nbsp;&nbsp;'
                '<span style="color:#1A1A1A;">%{y:,.0f} MWmed</span>'
                '<extra></extra>'
            ),
        )
    )

    # Trace 4: TÉRMICA (topo do stack).
    termica_lbl = "Térmica".ljust(11).replace(" ", "&nbsp;")
    fig_v2.add_trace(
        go.Scatter(
            x=pivot_sel_carga.index,
            y=pivot_sel_carga["termica"].values,
            name="Térmica",
            mode="lines",
            stackgroup="oferta",
            line=dict(color=COR_FONTE_TERMICA, width=0.5),
            fillcolor=COR_FONTE_TERMICA,
            hovertemplate=(
                f'<span style="color:{COR_FONTE_TERMICA}; font-weight:700;">'
                f'{termica_lbl}</span>'
                '&nbsp;&nbsp;'
                '<span style="color:#1A1A1A;">%{y:,.0f} MWmed</span>'
                '<extra></extra>'
            ),
        )
    )

    # Trace 5: INTERCÂMBIO — só em submercado (decisão 5.32).
    # Sinal preservado: positivo = importação líquida, negativo =
    # exportação líquida. Sinal é EXPLÍCITO no hover via customdata
    # pré-computado (Plotly hovertemplate não tem if/else nativo).
    if submercado_carga != "SIN":
        interc_lbl = "Intercâmbio".ljust(11).replace(" ", "&nbsp;")
        interc_values = pivot_sel_carga["intercambio"].values
        interc_hover_strs = [
            (
                f"+{_fmt_br_carga(abs(v), 0)} MWmed (exportação líquida)"
                if v >= 0
                else f"−{_fmt_br_carga(abs(v), 0)} MWmed (importação líquida)"
            )
            for v in interc_values
        ]
        fig_v2.add_trace(
            go.Scatter(
                x=pivot_sel_carga.index,
                y=interc_values,
                name="Intercâmbio (interno)",
                mode="lines",
                line=dict(
                    color=COR_INTERC_V2, width=1.5, dash="dashdot",
                ),
                customdata=interc_hover_strs,
                hovertemplate=(
                    f'<span style="color:{COR_INTERC_V2}; font-weight:700;">'
                    f'{interc_lbl}</span>'
                    '&nbsp;&nbsp;'
                    '<span style="color:#1A1A1A;">%{customdata}</span>'
                    '<extra></extra>'
                ),
            )
        )

    # Trace 6: CARGA TOTAL sobreposta — linha dotted preta fina.
    # Adicionada POR ÚLTIMO pra ficar por cima de tudo (z-order).
    # Em SIN, cola no topo do stack. Em submercado, gap = intercâmbio.
    carga_lbl = "Carga total".ljust(11).replace(" ", "&nbsp;")
    fig_v2.add_trace(
        go.Scatter(
            x=pivot_sel_carga.index,
            y=pivot_sel_carga["carga"].values,
            name="Carga total",
            mode="lines",
            line=dict(color=COR_CARGA_V2, width=1.5, dash="dot"),
            hovertemplate=(
                f'<span style="color:{COR_CARGA_V2}; font-weight:700;">'
                f'{carga_lbl}</span>'
                '&nbsp;&nbsp;'
                '<span style="color:#1A1A1A;">%{y:,.0f} MWmed</span>'
                '<extra></extra>'
            ),
        )
    )

    # Vline 29/04/2023 (decisão 5.26 + 5.31 ponto 5).
    # Mesmo padrão da Viz 1 — pulada em Dia Típico (eixo X categorial,
    # Timestamp não bate). Sub-bloco 5.5.
    quebra_data_v2 = pd.Timestamp(2023, 4, 29)
    if (
        granularidade_carga != "Dia Típico"
        and data_ini_efetivo_carga
        <= quebra_data_v2.date()
        <= data_fim_carga
    ):
        fig_v2.add_vline(
            x=quebra_data_v2,
            line_dash="dot",
            line_color=BAUHAUS_GRAY,
            line_width=1.2,
        )
        fig_v2.add_annotation(
            x=quebra_data_v2,
            y=1.02,
            yref="paper",
            text="ONS passa a incluir MMGD na carga",
            showarrow=False,
            font=dict(
                family="Inter, sans-serif",
                size=10,
                color=BAUHAUS_GRAY,
            ),
            align="center",
        )

    # Layout matching com Viz 1 (height 450, hover unified mono,
    # legenda Bebas Neue 19, eixos Bauhaus, separators BR ",.").
    _xaxis_v2_dict = dict(
        title=None, showgrid=False, showline=True,
        linewidth=2, linecolor=BAUHAUS_BLACK,
        ticks="outside", tickcolor=BAUHAUS_BLACK,
        tickfont=dict(
            family="Inter, sans-serif",
            size=13, color=BAUHAUS_BLACK,
        ),
    )
    if granularidade_carga == "Dia Típico":
        _xaxis_v2_dict["type"] = "category"
    else:
        _xaxis_v2_dict["hoverformat"] = hover_fmt_carga

    fig_v2.update_layout(
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
        xaxis=_xaxis_v2_dict,
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
            tickformat=",.0f",
        ),
        font=dict(family="Inter, sans-serif", size=12),
    )

    st.plotly_chart(
        fig_v2, use_container_width=True,
        config={"displaylogo": False},
    )

elif aba == "Curtailment":
    render_aba_curtailment()

elif aba == "Modulação":
    render_aba_modulacao()

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
