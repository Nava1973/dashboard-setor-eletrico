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
    load_balanco_subsistema,
    is_balanco_cache_fresh,
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
            )
    else:
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
            "carga_total_media":   float("nan"),
            "carga_liquida_media": float("nan"),
            "rampa_max_1h":        float("nan"),
            "rampa_max_1h_ts":     None,
            "rampa_max_3h":        float("nan"),
            "rampa_max_3h_ts":     None,
            "pct_renov_var":       float("nan"),
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

    rampa_1h, ts_1h = _max_abs_with_ts(rampa_1h_series)
    rampa_3h, ts_3h = _max_abs_with_ts(rampa_3h_series)

    return {
        "carga_total_media":   carga_mean,
        "carga_liquida_media": liq_mean,
        "rampa_max_1h":        rampa_1h,
        "rampa_max_1h_ts":     ts_1h,
        "rampa_max_3h":        rampa_3h,
        "rampa_max_3h_ts":     ts_3h,
        "pct_renov_var":       pct_renov,
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
        ["PLD", "Reservatórios", "ENA/Chuva", "Geração", "Carga"],
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

    # Defesa contra widget cleanup do data_fim em single-day mode
    # (decisão 5.16 estendida): em horário com 1D ativo, o widget
    # "Data final" não é instanciado e Streamlit descarta
    # state["data_fim"]. Próximo rerun (ex: clique no botão "Último
    # dia" ou troca de granularidade) lê data_fim → KeyError.
    # Restauramos antes do reset block: assume == data_ini (consistente
    # com single-day). Se a granularidade for não-horária, o gatilho
    # `range_degenerado_fora_horario` abaixo vai capturar o estado
    # degenerado e disparar reset full pra default 90d.
    if (
        "data_fim" not in st.session_state
        and "data_ini" in st.session_state
    ):
        st.session_state["data_fim"] = st.session_state["data_ini"]

    # Gatilho extra (decisão 5.28): se user estava em horário com 1D
    # ativo (data_ini == data_fim) e troca pra Diário/Semanal/Mensal,
    # o range degenerado de 1 dia ficaria horrível nessas
    # granularidades. Reset pro default 90d nesse caso.
    range_degenerado_fora_horario = (
        granularidade != "horario"
        and "data_ini" in st.session_state
        and "data_fim" in st.session_state
        and st.session_state["data_ini"] == st.session_state["data_fim"]
    )

    if (
        "data_ini" not in st.session_state
        or st.session_state.get("_dataset_max") != max_d
        or st.session_state.get("_dataset_min") != min_d
        or range_degenerado_fora_horario
    ):
        st.session_state["data_ini"] = max(min_d, max_d - timedelta(days=90))
        st.session_state["data_fim"] = max_d
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
                # Semanal: mostra só início da semana. CCEE não publica
                # data_fim; calcular data+6dias assumiria semana fixa,
                # então preferimos o início puro. Se o usuário quiser
                # ver o range, mudar hovermode pra "x" e passar customdata
                # por trace com fim = data + timedelta(days=6).
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
                        "semanal": "%d/%m/%Y",
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

elif aba == "Geração":
    # -----------------------------------------------------------------------
    # Aba Geração — stacked area de geração por fonte (térmica/hidro/eólica/
    # solar) + linha tracejada de carga verificada. Fonte ONS balanço de
    # subsistemas. Inclui anotação da quebra metodológica de 29/04/2023
    # (carga passa a incluir MMGD).
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

    # Linha 1: estado médio do sistema (3 cards).
    kpi_l1 = st.columns(3)
    with kpi_l1[0]:
        st.markdown(
            _render_kpi_carga(
                "CARGA TOTAL MÉDIA",
                _fmt_br_carga(kpis_carga["carga_total_media"]),
                "MWmed",
                tooltip=(
                    "Soma de toda demanda elétrica do subsistema. "
                    "Inclui MMGD pós-29/04/2023."
                ),
            ),
            unsafe_allow_html=True,
        )
    with kpi_l1[1]:
        st.markdown(
            _render_kpi_carga(
                "CARGA LÍQUIDA MÉDIA",
                _fmt_br_carga(kpis_carga["carga_liquida_media"]),
                "MWmed",
                tooltip=(
                    "Carga total menos eólica e solar centralizada. "
                    "O que hidro+térmica precisa cobrir."
                ),
            ),
            unsafe_allow_html=True,
        )
    with kpi_l1[2]:
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

    # Linha 2: estresse operacional (2 cards + 1 col vazia). Cards uniformes
    # com a linha 1 (mesma largura visual), col 2 vazia preserva alinhamento.
    # Timestamps dos picos vão DENTRO de cada card via parâmetro `subtext`
    # do helper — economiza vertical e cola a info ao número que ela descreve.
    ts_1h = kpis_carga["rampa_max_1h_ts"]
    ts_3h = kpis_carga["rampa_max_3h_ts"]
    subtext_1h = (
        f"em<br>{ts_1h.strftime('%d/%m/%Y %H:%M')}"
        if ts_1h is not None else ""
    )
    subtext_3h = (
        f"em<br>{ts_3h.strftime('%d/%m/%Y %H:%M')}"
        if ts_3h is not None else ""
    )
    kpi_l2 = st.columns(3)
    with kpi_l2[0]:
        st.markdown(
            _render_kpi_carga(
                "RAMPA MÁX 1H",
                _fmt_br_carga(kpis_carga["rampa_max_1h"]),
                "MW",
                tooltip=(
                    "Maior variação de carga líquida em 1 hora. Mostra picos "
                    "instantâneos de estresse operacional."
                ),
                subtext=subtext_1h,
            ),
            unsafe_allow_html=True,
        )
    with kpi_l2[1]:
        st.markdown(
            _render_kpi_carga(
                "RAMPA MÁX 3H",
                _fmt_br_carga(kpis_carga["rampa_max_3h"]),
                "MW",
                tooltip=(
                    "Maior variação de carga líquida em 3 horas consecutivas. "
                    "Padrão internacional (duck curve), captura tipicamente "
                    "a rampa de fim de tarde."
                ),
                subtext=subtext_3h,
            ),
            unsafe_allow_html=True,
        )
    # kpi_l2[2] fica vazio (alinha visualmente com a linha 1).

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
    # Dia Típico (xaxis categorial + stackgroup) vem no Sub-bloco 5.5 —
    # validação separada. Por enquanto, st.info informativo.
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

    if granularidade_carga == "Dia Típico":
        # Stackgroup Plotly + xaxis.type="category" precisam validação
        # separada (Sub-bloco 5.5). Viz 1 acima continua funcionando em
        # Dia Típico — usuário tem fallback útil pra duck curve.
        st.info(
            "Decomposição em Dia Típico vem no Sub-bloco 5.5. "
            "Use Diária / Horária / Mensal pra ver Viz 2 nesta sessão."
        )
    else:
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
                    f"+{_fmt_br_carga(abs(v), 0)} MWmed (importação líquida)"
                    if v >= 0
                    else f"−{_fmt_br_carga(abs(v), 0)} MWmed (exportação líquida)"
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
        # Mesmo padrão da Viz 1.
        quebra_data_v2 = pd.Timestamp(2023, 4, 29)
        if (
            data_ini_efetivo_carga
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
            hoverformat=hover_fmt_carga,
        )

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

        # Sanity check de balanço (atenção 4 do prompt do user):
        #   carga ≈ (solar + eolica + hidro + termica) + intercambio
        # Tolerância: desvio médio relativo < 1%. Se quebrar, st.caption
        # vermelho discreto sinaliza pro Nava investigar pivot/dataset.
        # CHECK REMOVÍVEL após validação inicial — ver TODO abaixo.
        # TODO(Sub-bloco 5.6): após Nava confirmar que passa nos 3
        # cenários representativos (Diária 12M / Horária 7D / Mensal 5A
        # em SIN e submercado), remover este bloco.
        _topo_stack_v2 = (
            pivot_sel_carga["solar"]
            + pivot_sel_carga["eolica"]
            + pivot_sel_carga["hidro"]
            + pivot_sel_carga["termica"]
        )
        _residual_v2 = (
            pivot_sel_carga["carga"]
            - _topo_stack_v2
            - pivot_sel_carga["intercambio"]
        )
        _carga_mean = pivot_sel_carga["carga"].abs().mean()
        if _carga_mean > 0:
            _ratio_v2 = _residual_v2.abs().mean() / _carga_mean
            if _ratio_v2 > 0.01:
                st.caption(
                    f"⚠️ Balanço Viz 2: desvio médio "
                    f"{_ratio_v2 * 100:.2f}% (esperado <1%) "
                    f"em {submercado_carga}/{granularidade_carga}. "
                    f"Investigar pivot ou dataset."
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
