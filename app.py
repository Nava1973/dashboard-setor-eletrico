"""
Dashboard do Setor Elétrico Brasileiro
Aba 1: PLD Médio Diário por Submercado

Fonte: CCEE - Portal Dados Abertos
https://dadosabertos.ccee.org.br/dataset/pld_media_diaria
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, timedelta

from auth import require_login
from data_loader import load_pld_media_diaria, clear_cache

# =============================================================================
# CONFIGURAÇÃO DA PÁGINA
# =============================================================================
st.set_page_config(
    page_title="Dashboard Setor Elétrico BR",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CSS customizado - tema editorial, tipografia distintiva
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,800&display=swap');

    html, body, [class*="css"] {
        font-family: 'JetBrains Mono', monospace;
    }
    h1, h2, h3 {
        font-family: 'Fraunces', serif !important;
        font-weight: 800 !important;
        letter-spacing: -0.02em;
    }
    .stMetric {
        background: #0f1419;
        padding: 1rem;
        border-radius: 4px;
        border-left: 3px solid #e8b923;
    }
    [data-testid="stMetricValue"] {
        font-family: 'Fraunces', serif !important;
        font-size: 1.8rem !important;
    }
    [data-testid="stMetricLabel"] {
        text-transform: uppercase;
        font-size: 0.7rem !important;
        letter-spacing: 0.1em;
    }
    .block-container {
        padding-top: 2rem;
    }
    </style>
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
# SIDEBAR — NAVEGAÇÃO E CONTROLES GLOBAIS
# =============================================================================
with st.sidebar:
    st.markdown(f"### ⚡ Dashboard SEB")
    st.caption(f"Logado como: **{user}**")
    st.divider()

    aba = st.radio(
        "NAVEGAÇÃO",
        ["PLD Diário"],  # futuras: Reservatórios, Spread, Geração, etc.
        label_visibility="collapsed",
    )

    st.divider()
    st.caption("ATUALIZAÇÃO DE DADOS")
    if st.button("🔄 Forçar atualização", use_container_width=True):
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
    st.markdown("# PLD Médio Diário por Submercado")
    st.caption(
        "Preço de Liquidação das Diferenças — média diária dos preços horários. "
        "Fonte: CCEE / Portal Dados Abertos."
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
                for d in debug[:20]:  # primeiros 20 erros
                    st.code(d)
            st.stop()

    if df.empty:
        st.warning("Nenhum dado disponível.")
        st.stop()

    # Aviso se estiver em modo demo
    if st.session_state.get("_demo_mode"):
        st.warning(
            "⚠️ **Modo demonstração ativo** — a CCEE não respondeu às tentativas de "
            "download. Os dados exibidos abaixo são **sintéticos**, apenas para "
            "testar o dashboard. Para dados reais, verifique sua conexão ou aguarde "
            "a CCEE voltar a responder."
        )

    # --- Controles ---
    min_d = df["data"].min().date()
    max_d = df["data"].max().date()

    col_a, col_b, col_c = st.columns([2, 2, 3])
    with col_a:
        data_ini = st.date_input(
            "Data inicial",
            value=max(min_d, max_d - timedelta(days=180)),
            min_value=min_d,
            max_value=max_d,
        )
    with col_b:
        data_fim = st.date_input(
            "Data final",
            value=max_d,
            min_value=min_d,
            max_value=max_d,
        )
    with col_c:
        presets = st.radio(
            "Atalhos",
            ["7d", "30d", "90d", "1A", "Máx"],
            horizontal=True,
            index=2,
            label_visibility="collapsed",
        )

    # Aplicar preset (sobrescreve os date_input se clicado)
    if presets == "7d":
        data_ini = max_d - timedelta(days=7)
    elif presets == "30d":
        data_ini = max_d - timedelta(days=30)
    elif presets == "90d":
        data_ini = max_d - timedelta(days=90)
    elif presets == "1A":
        data_ini = max_d - timedelta(days=365)
    elif presets == "Máx":
        data_ini = min_d
    data_fim = max_d

    # --- Filtrar ---
    mask = (df["data"].dt.date >= data_ini) & (df["data"].dt.date <= data_fim)
    dff = df.loc[mask].copy()

    if dff.empty:
        st.warning("Sem dados no intervalo selecionado.")
        st.stop()

    # --- KPIs (valores mais recentes) ---
    st.markdown("### Último dia disponível")
    ultimo = dff.sort_values("data").iloc[-len(dff["submercado"].unique()) :]
    ultima_data = ultimo["data"].max()
    ultimo_pld = dff[dff["data"] == ultima_data].set_index("submercado")["pld"]

    cols = st.columns(5)
    submercados_ord = ["SE", "S", "NE", "N"]
    for i, sub in enumerate(submercados_ord):
        with cols[i]:
            val = ultimo_pld.get(sub)
            st.metric(
                label=f"{sub}",
                value=f"R$ {val:,.2f}" if val is not None else "—",
            )
    with cols[4]:
        media_br = ultimo_pld.mean()
        st.metric(label="MÉDIA BR", value=f"R$ {media_br:,.2f}")

    st.caption(f"Referência: {ultima_data.strftime('%d/%m/%Y')}")

    # --- Gráfico principal ---
    st.markdown("### Série histórica")

    # Pivotar para facilitar plot
    pivot = dff.pivot_table(
        index="data", columns="submercado", values="pld", aggfunc="mean"
    ).sort_index()

    # Calcular média BR (simples entre submercados presentes)
    pivot["Média BR"] = pivot[submercados_ord].mean(axis=1)

    # Paleta coesa — submercados + média destacada
    cores = {
        "SE": "#3aa0ff",
        "S": "#2ecc71",
        "NE": "#e8b923",
        "N": "#e74c3c",
        "Média BR": "#ffffff",
    }

    fig = go.Figure()
    for col in submercados_ord + ["Média BR"]:
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
                    color=cores[col],
                    width=3 if is_media else 2,
                    dash="dash" if is_media else "solid",
                ),
                hovertemplate=(
                    f"<b>{col}</b><br>"
                    "%{x|%d/%m/%Y}<br>"
                    "R$ %{y:,.2f}/MWh<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        height=520,
        margin=dict(l=10, r=10, t=30, b=10),
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15,20,25,0.4)",
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            bgcolor="rgba(0,0,0,0)",
        ),
        xaxis=dict(
            title=None,
            gridcolor="rgba(255,255,255,0.05)",
            showspikes=True,
            spikethickness=1,
            spikecolor="rgba(255,255,255,0.3)",
            spikemode="across",
        ),
        yaxis=dict(
            title="R$/MWh",
            gridcolor="rgba(255,255,255,0.05)",
            zerolinecolor="rgba(255,255,255,0.1)",
        ),
        font=dict(family="JetBrains Mono, monospace", size=12),
    )

    st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})

    st.caption(
        "💡 Clique nos itens da legenda para ocultar/mostrar submercados. "
        "Duplo-clique isola uma série."
    )

    # --- Estatísticas do período ---
    st.markdown("### Estatísticas do período selecionado")
    stats = (
        dff.groupby("submercado")["pld"]
        .agg(["min", "mean", "max", "std"])
        .reindex(submercados_ord)
        .round(2)
    )
    stats.columns = ["Mínimo", "Média", "Máximo", "Desvio-padrão"]
    stats.index.name = "Submercado"
    st.dataframe(
        stats.style.format("R$ {:,.2f}"),
        use_container_width=True,
    )

    # --- Download dos dados filtrados ---
    with st.expander("📥 Baixar dados filtrados (CSV)"):
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
    "Dashboard Setor Elétrico · Dados: CCEE Portal Dados Abertos "
    "(licença CC-BY-4.0) · Atualização diária automática"
)
