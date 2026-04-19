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

from auth import require_login
from data_loader import load_pld_media_diaria, clear_cache

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
    @import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@400;500;600;700&display=swap');
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
        font-size: 3rem !important;
        line-height: 1 !important;
        border-left: 10px solid {BAUHAUS_RED};
        padding-left: 16px;
        margin-bottom: 0.5rem !important;
    }}
    h3 {{
        font-size: 1.4rem !important;
        letter-spacing: 0.05em !important;
        border-bottom: 2px solid {BAUHAUS_BLACK};
        padding-bottom: 4px;
        margin-top: 2.2rem !important;
    }}

    /* Fundo da página */
    .stApp {{
        background: {BAUHAUS_CREAM};
    }}

    /* Botão nativo do Streamlit para sidebar — ESCONDER completamente.
       O texto "keyboard_double_arrow_right" aparece quando Material Icons
       não carrega, e CSS+JS não conseguem sobrescrever de forma confiável.
       Solução: escondemos e renderizamos nosso próprio botão via JS. */
    [data-testid="stSidebarCollapseButton"],
    [data-testid="stSidebarCollapsedControl"],
    button[kind="header"][data-testid="baseButton-headerNoPadding"] {{
        display: none !important;
        visibility: hidden !important;
        width: 0 !important;
        height: 0 !important;
        opacity: 0 !important;
        pointer-events: none !important;
    }}

    /* Nosso botão custom de toggle — posicionado fixo no canto superior esquerdo */
    #bauhaus-sidebar-toggle {{
        position: fixed !important;
        top: 12px !important;
        left: 12px !important;
        z-index: 999999 !important;
        width: 40px !important;
        height: 40px !important;
        background: {BAUHAUS_YELLOW} !important;
        border: 2px solid {BAUHAUS_BLACK} !important;
        border-radius: 0 !important;
        cursor: pointer !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 1.6rem !important;
        font-weight: 700 !important;
        color: {BAUHAUS_BLACK} !important;
        line-height: 1 !important;
        padding: 0 !important;
        user-select: none !important;
    }}
    #bauhaus-sidebar-toggle:hover {{
        background: {BAUHAUS_RED} !important;
        color: {BAUHAUS_CREAM} !important;
    }}
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

    /* KPIs — cards com borda preta, reduzidos (~80%) */
    [data-testid="stMetric"] {{
        background: {BAUHAUS_CREAM};
        border: 2px solid {BAUHAUS_BLACK};
        padding: 10px 14px;
        border-radius: 0;
    }}
    [data-testid="stMetric"] [data-testid="stMetricValue"],
    [data-testid="stMetric"] [data-testid="stMetricValue"] *,
    [data-testid="stMetric"] [data-testid="stMetricValue"] div {{
        font-family: 'Bebas Neue', sans-serif !important;
        font-size: 1.5rem !important;
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
        font-size: 0.68rem !important;
        letter-spacing: 0.18em !important;
        font-weight: 700 !important;
        color: {BAUHAUS_BLACK} !important;
    }}

    /* Botões principais (fora da sidebar) */
    .stButton > button {{
        border-radius: 0 !important;
        border: 2px solid {BAUHAUS_BLACK} !important;
        background: {BAUHAUS_CREAM} !important;
        color: {BAUHAUS_BLACK} !important;
        font-family: 'Bebas Neue', sans-serif !important;
        letter-spacing: 0.08em;
        font-size: 1rem !important;
        padding: 8px 12px !important;
        transition: all 0.15s ease !important;
    }}
    .stButton > button:hover {{
        background: {BAUHAUS_YELLOW} !important;
        color: {BAUHAUS_BLACK} !important;
    }}

    /* Inputs de data */
    .stDateInput > div > div {{
        border-radius: 0 !important;
        border: 2px solid {BAUHAUS_BLACK} !important;
        background: {BAUHAUS_CREAM};
    }}
    .stDateInput input {{
        font-family: 'Inter', sans-serif !important;
        color: {BAUHAUS_BLACK} !important;
    }}
    /* Labels "Data inicial" e "Data final" — PRETO forçado */
    .stDateInput label,
    .stDateInput label *,
    .stDateInput label p,
    [data-testid="stWidgetLabel"],
    [data-testid="stWidgetLabel"] *,
    [data-testid="stWidgetLabel"] p {{
        color: {BAUHAUS_BLACK} !important;
        font-weight: 600 !important;
        font-family: 'Inter', sans-serif !important;
    }}

    /* Bloco principal */
    .block-container {{
        padding-top: 1.5rem;
        padding-bottom: 4rem;  /* espaço para rodapé não sobrepor */
        max-width: 1400px;
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

# =============================================================================
# JS HOTFIX — limpa texto "keyboard_double_arrow_right" dos botões de sidebar
# que aparecem quando Material Icons não carrega. Também roda em mudanças.
# =============================================================================
st.markdown(
    """
    <script>
    (function() {
        // Cria nosso próprio botão de toggle da sidebar e esconde o nativo.
        // Motivo: o botão nativo mostra "keyboard_double_arrow_right" quando
        // Material Icons não carrega, e CSS não consegue sobrescrever.
        function setupBotaoCustom() {
            // Checa se já foi criado
            if (document.getElementById('bauhaus-sidebar-toggle')) {
                return;
            }
            const btn = document.createElement('button');
            btn.id = 'bauhaus-sidebar-toggle';
            btn.setAttribute('aria-label', 'Abrir/fechar menu lateral');
            btn.innerHTML = '‹';  // será atualizado baseado no estado
            btn.onclick = function() {
                // Tenta encontrar e clicar no botão nativo (mesmo escondido, funciona)
                const alvos = [
                    document.querySelector('[data-testid="stSidebarCollapseButton"]'),
                    document.querySelector('[data-testid="stSidebarCollapsedControl"]'),
                    document.querySelector('button[kind="header"]')
                ];
                for (const alvo of alvos) {
                    if (alvo) {
                        alvo.click();
                        break;
                    }
                }
            };
            document.body.appendChild(btn);
        }

        function atualizarSeta() {
            const btn = document.getElementById('bauhaus-sidebar-toggle');
            if (!btn) return;
            const sidebar = document.querySelector('[data-testid="stSidebar"]');
            if (!sidebar) return;
            // Se sidebar está visível (aberta), seta aponta pra esquerda (fechar)
            // Se está escondida (aria-expanded=false ou display=none), aponta pra direita (abrir)
            const rect = sidebar.getBoundingClientRect();
            const estaAberta = rect.width > 50;  // heurística: aberta tem ~300px
            btn.innerHTML = estaAberta ? '‹' : '›';
        }

        function init() {
            setupBotaoCustom();
            atualizarSeta();
        }

        // Executa ao carregar e observa mudanças no DOM
        init();
        const observer = new MutationObserver(function() {
            init();
        });
        observer.observe(document.body, { childList: true, subtree: true, attributes: true });
    })();
    </script>
    """,
    unsafe_allow_html=True,
)

# =============================================================================
# SIDEBAR
# =============================================================================
with st.sidebar:
    st.markdown("### Dashboard Setor Elétrico")
    st.caption(f"Usuário: **{user}**")
    st.divider()

    aba = st.radio(
        "NAVEGAÇÃO",
        ["PLD Diário"],
        label_visibility="collapsed",
    )

    st.divider()
    st.caption("ATUALIZAÇÃO")
    if st.button("Forçar atualização", use_container_width=True):
        clear_cache()
        st.rerun()

    st.caption(
        "Dados atualizados automaticamente 1x ao dia. "
        "Use o botão acima para recarregar a CCEE."
    )

# =============================================================================
# ABA: PLD MÉDIO DIÁRIO POR SUBMERCADO
# =============================================================================
if aba == "PLD Diário":
    st.markdown("# PLD DIÁRIO")
    st.caption(
        "Preço de Liquidação das Diferenças por submercado · "
        "Fonte: CCEE Dados Abertos"
    )

    # --- Carregar dados ---
    with st.spinner("Carregando dados da CCEE…"):
        try:
            df = load_pld_media_diaria()
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
    ):
        st.session_state["data_ini"] = max(min_d, max_d - timedelta(days=90))
        st.session_state["data_fim"] = max_d
        st.session_state["_dataset_max"] = max_d

    st.markdown("### Período")

    # Atalhos
    st.caption("Atalhos")
    cb1, cb2, cb3, cb4, cb5, _ = st.columns([1, 1, 1, 1, 1, 5])
    with cb1:
        if st.button("7d", use_container_width=True):
            st.session_state["data_ini"] = max_d - timedelta(days=7)
            st.session_state["data_fim"] = max_d
            st.rerun()
    with cb2:
        if st.button("30d", use_container_width=True):
            st.session_state["data_ini"] = max_d - timedelta(days=30)
            st.session_state["data_fim"] = max_d
            st.rerun()
    with cb3:
        if st.button("90d", use_container_width=True):
            st.session_state["data_ini"] = max_d - timedelta(days=90)
            st.session_state["data_fim"] = max_d
            st.rerun()
    with cb4:
        if st.button("1A", use_container_width=True):
            st.session_state["data_ini"] = max_d - timedelta(days=365)
            st.session_state["data_fim"] = max_d
            st.rerun()
    with cb5:
        if st.button("Máx", use_container_width=True):
            st.session_state["data_ini"] = min_d
            st.session_state["data_fim"] = max_d
            st.rerun()

    col_a, col_b = st.columns(2)
    with col_a:
        data_ini = st.date_input(
            "Data inicial",
            min_value=min_d,
            max_value=max_d,
            key="data_ini",
        )
    with col_b:
        data_fim = st.date_input(
            "Data final",
            min_value=min_d,
            max_value=max_d,
            key="data_fim",
        )

    if data_ini > data_fim:
        st.error("A data inicial não pode ser posterior à data final.")
        st.stop()

    # --- Filtrar por data ---
    mask = (df["data"].dt.date >= data_ini) & (df["data"].dt.date <= data_fim)
    dff = df.loc[mask].copy()

    if dff.empty:
        st.warning("Sem dados no intervalo selecionado.")
        st.stop()

    # --- KPIs (valores mais recentes) ---
    ultima_data = dff["data"].max()
    ultimo_pld = dff[dff["data"] == ultima_data].set_index("submercado")["pld"]

    # Título com data embaixo, em linha separada para garantir respiro
    st.markdown(
        f'<h3 style="margin-top:2.2rem; margin-bottom:0.3rem;">'
        f'Último dia disponível'
        f'</h3>'
        f'<div style="font-family:\'Inter\', sans-serif; font-weight:500; '
        f'font-size:1.25rem; letter-spacing:0.02em; color:#2E2E2E; '
        f'margin-top:0; margin-bottom:1.2rem;">'
        f'{ultima_data.strftime("%d/%m/%Y")}'
        f'</div>',
        unsafe_allow_html=True,
    )

    cols = st.columns(5)
    for i, sub in enumerate(SUBMERCADOS_ORD):
        with cols[i]:
            val = ultimo_pld.get(sub)
            st.metric(
                label=sub,
                value=f"R$ {val:,.2f}" if val is not None else "—",
            )
    with cols[4]:
        media_br = ultimo_pld.mean()
        st.metric(label="MÉDIA BR", value=f"R$ {media_br:,.2f}")

    # --- Seletor de submercados ---
    st.markdown("### Série histórica")

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
                    # Hover: sigla colorida à esquerda, valor alinhado à direita.
                    # Usamos padding com espaços unicode pra forçar alinhamento
                    # mesmo em fonte proporcional (aproximação que funciona bem
                    # com sigla curta + valor padronizado).
                    hovertemplate=(
                        f'<span style="color:{cor_linha}; font-weight:700; '
                        f'display:inline-block; min-width:40px;">'
                        f'{sigla_label}</span>'
                        '<span style="color:#1A1A1A; display:inline-block; '
                        'min-width:110px; text-align:right;">'
                        'R$ %{y:.0f}/MWh</span>'
                        '<extra></extra>'
                    ),
                )
            )

        # Layout Bauhaus — papel creme, tipografia impactante, geometria
        fig.update_layout(
            height=400,  # reduzido (antes 500)
            margin=dict(l=20, r=20, t=30, b=20),
            paper_bgcolor=BAUHAUS_CREAM,
            plot_bgcolor=BAUHAUS_CREAM,
            hovermode="x unified",  # tooltip único com todas as séries + data no topo
            hoverlabel=dict(
                bgcolor=BAUHAUS_CREAM,
                bordercolor=BAUHAUS_BLACK,
                font=dict(
                    family="Inter, sans-serif",
                    size=13,
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
                    size=14,
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
                    size=11,
                    color=BAUHAUS_BLACK,
                ),
            ),
            yaxis=dict(
                title=dict(
                    text="R$/MWh",
                    font=dict(
                        family="Bebas Neue, sans-serif",
                        size=14,
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
                    size=11,
                    color=BAUHAUS_BLACK,
                ),
                zeroline=False,
                # Zero decimais no eixo Y (e no hover unified)
                tickformat=".0f",
                hoverformat=".0f",
            ),
            font=dict(family="Inter, sans-serif", size=12),
        )

        st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})

    # --- Estatísticas do período (tabela) ---
    st.markdown("### Estatísticas do período")
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
    st.markdown(tabela_html, unsafe_allow_html=True)

    # --- Download ---
    st.markdown("### Exportar")
    csv = dff.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Baixar dados filtrados (CSV)",
        data=csv,
        file_name=f"pld_diario_{data_ini}_{data_fim}.csv",
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

