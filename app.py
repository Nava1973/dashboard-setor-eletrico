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
BAUHAUS_BLUE = "#1D3557"     # azul cobalto profundo
BAUHAUS_BLACK = "#1A1A1A"    # preto tinteiro, não "puro"
BAUHAUS_CREAM = "#F5F1E8"    # creme (papel) em vez de branco estéril
BAUHAUS_GRAY = "#6B6B6B"
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

    /* Tipografia geral */
    html, body, [class*="css"], .stMarkdown, .stText, p, span, div, label {{
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    }}

    /* Títulos — Bebas Neue: condensada, alto impacto, muito Bauhaus */
    h1, h2, h3, h4 {{
        font-family: 'Bebas Neue', 'Inter', sans-serif !important;
        font-weight: 400 !important;
        letter-spacing: 0.02em !important;
    }}
    h1 {{
        font-size: 3rem !important;
        line-height: 1 !important;
        border-left: 10px solid {BAUHAUS_RED};
        padding-left: 16px;
        margin-bottom: 0.5rem !important;
        color: {BAUHAUS_BLACK};
    }}
    h3 {{
        font-size: 1.4rem !important;
        letter-spacing: 0.05em !important;
        color: {BAUHAUS_BLACK};
        border-bottom: 2px solid {BAUHAUS_BLACK};
        padding-bottom: 4px;
        margin-top: 2.2rem !important;
    }}

    /* Fundo da página */
    .stApp {{
        background: {BAUHAUS_CREAM};
    }}

    /* Sidebar — deixar o Streamlit cuidar do botão de abrir/fechar.
       Apenas estilizamos o interior. */
    [data-testid="stSidebar"] {{
        background: {BAUHAUS_BLUE};
        border-right: 4px solid {BAUHAUS_BLACK};
    }}
    [data-testid="stSidebar"] * {{
        color: {BAUHAUS_CREAM} !important;
    }}
    [data-testid="stSidebar"] h3 {{
        color: {BAUHAUS_YELLOW} !important;
        border-bottom: 2px solid {BAUHAUS_YELLOW};
    }}
    [data-testid="stSidebar"] hr {{
        border-top: 1px solid rgba(255,255,255,0.3) !important;
    }}
    [data-testid="stSidebar"] .stButton > button {{
        background: {BAUHAUS_YELLOW} !important;
        color: {BAUHAUS_BLACK} !important;
        border: 2px solid {BAUHAUS_BLACK} !important;
    }}
    [data-testid="stSidebar"] .stButton > button:hover {{
        background: {BAUHAUS_RED} !important;
        color: {BAUHAUS_CREAM} !important;
    }}

    /* KPIs */
    [data-testid="stMetric"] {{
        background: {BAUHAUS_CREAM};
        border: 2px solid {BAUHAUS_BLACK};
        padding: 16px 18px;
        border-radius: 0;
    }}
    [data-testid="stMetricValue"] {{
        font-family: 'Bebas Neue', sans-serif !important;
        font-size: 2rem !important;
        color: {BAUHAUS_BLACK} !important;
        letter-spacing: 0.02em;
    }}
    [data-testid="stMetricLabel"] {{
        text-transform: uppercase !important;
        font-size: 0.72rem !important;
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

    /* Bloco principal */
    .block-container {{
        padding-top: 1.5rem;
        padding-bottom: 4rem;  /* espaço para rodapé não sobrepor */
        max-width: 1400px;
    }}

    /* Caption */
    .stCaption, [data-testid="stCaptionContainer"] {{
        font-family: 'Inter', sans-serif !important;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        font-size: 0.72rem !important;
        color: {BAUHAUS_GRAY} !important;
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
                    # Formatação explícita com 2 casas decimais no hover
                    hovertemplate=(
                        f"<b>{col}</b><br>"
                        "%{x|%d/%m/%Y}<br>"
                        "R$ %{y:.2f}/MWh<extra></extra>"
                    ),
                )
            )

        # Layout Bauhaus — papel creme, tipografia impactante, geometria
        fig.update_layout(
            height=500,
            margin=dict(l=20, r=20, t=30, b=20),
            paper_bgcolor=BAUHAUS_CREAM,
            plot_bgcolor=BAUHAUS_CREAM,
            hovermode="x unified",
            # CRÍTICO para as 2 casas decimais no hover unified
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
                # Força 2 decimais nos valores do eixo Y e no hover
                tickformat=".2f",
                hoverformat=".2f",
            ),
            font=dict(family="Inter, sans-serif", size=12),
        )

        st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})

    # --- Estatísticas do período (tabela) ---
    st.markdown("### Estatísticas do período")
    stats = (
        dff.groupby("submercado")["pld"]
        .agg(["min", "mean", "max", "std"])
        .reindex(SUBMERCADOS_ORD)
        .round(2)
    )
    stats.columns = ["Mínimo", "Média", "Máximo", "Desvio-padrão"]

    # Usar column_config do Streamlit: mais confiável que Styler para
    # formatar e centralizar valores numéricos em dataframes.
    stats_reset = stats.reset_index()
    stats_reset.columns = ["Submercado", "Mínimo", "Média", "Máximo", "Desvio-padrão"]

    st.dataframe(
        stats_reset,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Submercado": st.column_config.TextColumn(
                "Submercado",
                width="small",
            ),
            "Mínimo": st.column_config.NumberColumn(
                "Mínimo",
                format="R$ %.2f",
                width="medium",
            ),
            "Média": st.column_config.NumberColumn(
                "Média",
                format="R$ %.2f",
                width="medium",
            ),
            "Máximo": st.column_config.NumberColumn(
                "Máximo",
                format="R$ %.2f",
                width="medium",
            ),
            "Desvio-padrão": st.column_config.NumberColumn(
                "Desvio-padrão",
                format="R$ %.2f",
                width="medium",
            ),
        },
    )

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
