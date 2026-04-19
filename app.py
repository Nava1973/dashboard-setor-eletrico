"""
Dashboard do Setor Elétrico Brasileiro
Aba 1: PLD Médio Diário por Submercado

Design: Bauhaus — cores primárias (vermelho/amarelo/azul), geometria pura,
tipografia geométrica sem serifa. Forma segue função.

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
    page_title="Dashboard Setor Elétrico BR",
    page_icon="▲",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =============================================================================
# PALETA BAUHAUS
# =============================================================================
# Cores primárias puras + preto e branco. Base do movimento.
BAUHAUS_RED = "#E63946"      # vermelho Bauhaus (mais vibrante que o clássico)
BAUHAUS_YELLOW = "#FFBE0B"   # amarelo primário
BAUHAUS_BLUE = "#0077B6"     # azul primário
BAUHAUS_BLACK = "#0A0A0A"
BAUHAUS_WHITE = "#FAFAFA"
BAUHAUS_GRAY = "#757575"
BAUHAUS_LIGHT = "#EDEDED"

# Atribuição de cores por submercado
CORES_SUBMERCADO = {
    "SE": BAUHAUS_RED,         # maior mercado → vermelho (mais presente)
    "S": BAUHAUS_BLUE,
    "NE": BAUHAUS_YELLOW,
    "N": BAUHAUS_BLACK,
    "Média BR": BAUHAUS_GRAY,  # linha neutra
}

SUBMERCADOS_ORD = ["SE", "S", "NE", "N"]

# =============================================================================
# CSS — TIPOGRAFIA E COMPONENTES BAUHAUS
# =============================================================================
st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Archivo+Black&family=Space+Grotesk:wght@400;500;700&display=swap');

    /* Tipografia geral: Space Grotesk (geométrica, funcional) */
    html, body, [class*="css"], .stMarkdown, .stText, p, span, div, label {{
        font-family: 'Space Grotesk', 'Helvetica Neue', Arial, sans-serif !important;
    }}

    /* Títulos: Archivo Black — super geométrico, alto contraste */
    h1, h2, h3, h4 {{
        font-family: 'Archivo Black', 'Space Grotesk', sans-serif !important;
        font-weight: 900 !important;
        letter-spacing: -0.02em !important;
        text-transform: uppercase;
    }}

    h1 {{
        font-size: 2.6rem !important;
        line-height: 1 !important;
        border-left: 12px solid {BAUHAUS_RED};
        padding-left: 16px;
        margin-bottom: 0.5rem !important;
    }}

    h3 {{
        font-size: 1.1rem !important;
        letter-spacing: 0.05em !important;
        border-bottom: 3px solid {BAUHAUS_BLACK};
        padding-bottom: 6px;
        margin-top: 2rem !important;
    }}

    /* KPIs — blocos geométricos puros */
    [data-testid="stMetric"] {{
        background: {BAUHAUS_WHITE};
        border: 2px solid {BAUHAUS_BLACK};
        padding: 14px 16px;
        border-radius: 0;  /* sem arredondamento — Bauhaus é geométrico */
    }}
    [data-testid="stMetricValue"] {{
        font-family: 'Archivo Black', sans-serif !important;
        font-size: 1.7rem !important;
        color: {BAUHAUS_BLACK} !important;
    }}
    [data-testid="stMetricLabel"] {{
        text-transform: uppercase !important;
        font-size: 0.7rem !important;
        letter-spacing: 0.15em !important;
        font-weight: 700 !important;
        color: {BAUHAUS_BLACK} !important;
    }}

    /* Botões — retângulos puros, sem sombras */
    .stButton > button {{
        border-radius: 0 !important;
        border: 2px solid {BAUHAUS_BLACK} !important;
        background: {BAUHAUS_WHITE} !important;
        color: {BAUHAUS_BLACK} !important;
        font-family: 'Archivo Black', sans-serif !important;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-size: 0.8rem !important;
        transition: all 0.15s ease !important;
    }}
    .stButton > button:hover {{
        background: {BAUHAUS_YELLOW} !important;
        border-color: {BAUHAUS_BLACK} !important;
        color: {BAUHAUS_BLACK} !important;
        transform: translate(-2px, -2px);
        box-shadow: 4px 4px 0 {BAUHAUS_BLACK};
    }}

    /* Inputs de data */
    .stDateInput > div > div {{
        border-radius: 0 !important;
        border: 2px solid {BAUHAUS_BLACK} !important;
    }}

    /* Checkboxes */
    .stCheckbox {{
        font-family: 'Space Grotesk', sans-serif !important;
    }}

    /* Sidebar */
    [data-testid="stSidebar"] {{
        background: {BAUHAUS_LIGHT};
        border-right: 3px solid {BAUHAUS_BLACK};
    }}

    /* Tabela — centralizar números */
    [data-testid="stDataFrame"] table {{
        font-family: 'Space Grotesk', sans-serif !important;
    }}
    [data-testid="stDataFrame"] td {{
        text-align: center !important;
    }}
    [data-testid="stDataFrame"] th {{
        text-align: center !important;
        font-family: 'Archivo Black', sans-serif !important;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }}

    /* Bloco principal */
    .block-container {{
        padding-top: 1.5rem;
        max-width: 1400px;
    }}

    /* Caption */
    .stCaption, [data-testid="stCaptionContainer"] {{
        font-family: 'Space Grotesk', sans-serif !important;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-size: 0.72rem !important;
        color: {BAUHAUS_GRAY} !important;
    }}

    /* Remover linhas divisórias padrão e colocar nossas */
    hr {{
        border: none !important;
        border-top: 3px solid {BAUHAUS_BLACK} !important;
        margin: 2rem 0 !important;
    }}

    /* Faixa decorativa no topo — três formas primárias */
    .bauhaus-stripe {{
        display: flex;
        height: 8px;
        margin-bottom: 1.5rem;
    }}
    .bauhaus-stripe > div {{
        flex: 1;
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
# SIDEBAR
# =============================================================================
with st.sidebar:
    st.markdown(f"### ▲ SEB")
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
        "Os dados são atualizados automaticamente 1x ao dia. "
        "Use o botão acima para forçar recarga imediata da CCEE."
    )

# =============================================================================
# ABA: PLD MÉDIO DIÁRIO POR SUBMERCADO
# =============================================================================
if aba == "PLD Diário":
    st.markdown("# PLD Diário")
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

    # Inicializar estado (ou resetar se o dataset mudou)
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

    # Date pickers — fonte única de verdade
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
    st.markdown("### Último dia disponível")
    ultima_data = dff["data"].max()
    ultimo_pld = dff[dff["data"] == ultima_data].set_index("submercado")["pld"]

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

    st.caption(f"Referência: {ultima_data.strftime('%d/%m/%Y')}")

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
        # --- Preparar dados para o gráfico ---
        pivot = dff.pivot_table(
            index="data", columns="submercado", values="pld", aggfunc="mean"
        ).sort_index()

        # Média BR (média simples entre os 4 submercados disponíveis)
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
            fig.add_trace(
                go.Scatter(
                    x=pivot.index,
                    y=pivot[col],
                    name=col,
                    mode="lines",
                    line=dict(
                        color=CORES_SUBMERCADO[col],
                        width=4 if is_media else 2.5,
                        dash="dot" if is_media else "solid",
                    ),
                    hovertemplate=(
                        f"<b>{col}</b><br>"
                        "%{x|%d/%m/%Y}<br>"
                        "R$ %{y:,.2f}/MWh<extra></extra>"
                    ),
                )
            )

        # Layout Bauhaus — claro, geométrico, sem decorações supérfluas
        fig.update_layout(
            height=500,
            margin=dict(l=20, r=20, t=30, b=20),
            paper_bgcolor=BAUHAUS_WHITE,
            plot_bgcolor=BAUHAUS_WHITE,
            hovermode="x unified",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="left",
                x=0,
                bgcolor="rgba(0,0,0,0)",
                font=dict(
                    family="Archivo Black, sans-serif",
                    size=12,
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
                    family="Space Grotesk, sans-serif",
                    size=11,
                    color=BAUHAUS_BLACK,
                ),
            ),
            yaxis=dict(
                title=dict(
                    text="R$/MWh",
                    font=dict(
                        family="Archivo Black, sans-serif",
                        size=12,
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
                    family="Space Grotesk, sans-serif",
                    size=11,
                    color=BAUHAUS_BLACK,
                ),
                zeroline=False,
            ),
            font=dict(family="Space Grotesk, sans-serif", size=12),
        )

        st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})

    # --- Estatísticas do período ---
    st.markdown("### Estatísticas do período")
    stats = (
        dff.groupby("submercado")["pld"]
        .agg(["min", "mean", "max", "std"])
        .reindex(SUBMERCADOS_ORD)
        .round(2)
    )
    stats.columns = ["Mínimo", "Média", "Máximo", "Desvio-padrão"]
    stats.index.name = "Submercado"

    # Centraliza tudo (números e headers)
    styled = (
        stats.style
        .format("R$ {:,.2f}")
        .set_properties(**{"text-align": "center"})
        .set_table_styles(
            [
                {"selector": "th", "props": [("text-align", "center")]},
                {"selector": "td", "props": [("text-align", "center")]},
            ]
        )
    )
    st.dataframe(styled, use_container_width=True)

    # --- Download ---
    with st.expander("Baixar dados filtrados (CSV)"):
        csv = dff.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Baixar CSV",
            csv,
            file_name=f"pld_diario_{data_ini}_{data_fim}.csv",
            mime="text/csv",
        )

# =============================================================================
# RODAPÉ
# =============================================================================
st.divider()
st.caption(
    "Dashboard Setor Elétrico · Dados CCEE Portal Dados Abertos (CC-BY-4.0)"
)
