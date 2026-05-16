"""
tab_gsf.py
==========

Sub-aba "GSF" (Fator de Ajuste do MRE) da aba Geração.

Mostra a serie historica do Generation Scaling Factor (GSF) realizado
do SIN, com destaque visual pra meses de Energia Secundaria (GSF > 100%).

Formula validada empiricamente na Fase 0 (12/12 hits +/-0.5pp contra
15 pontos oficiais Power BI CCEE + InfoPLD):

    GSF_mes = sum(GERACAO_MRE) / sum(GARANTIA_FISICA_MRE)

Documentacao completa: docs/SPEC_gsf_v1.md
Data loader: data_loaders/ccee_gsf.py

Fases internas (sprint GSF Fase 2):
    2A — esqueleto: render minimo + chamada teste do loader
    2B — grafico Plotly linha temporal (este commit)
    2C — tabela HTML ultimos 12 meses
    2D — period controls
    2E — polimento final (hover, markers, KPIs)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_loaders.ccee_gsf import load_gsf_mensal
from utils.paleta_bradesco import (
    COR_TEXTO,
    COR_TEXTO_SECUND,
    COR_DESTAQUE,
    COR_SUCESSO,
    plotly_layout_defaults,
)


# Cores derivadas com alpha 15% pros preenchimentos de area semantica.
# rgba inline em vez de utility pq sao usados so neste componente
# e os hex base (COR_DESTAQUE = #CC092F, COR_SUCESSO = #2E7D32) sao
# canonicos da paleta — mudancas na paleta refletem aqui via reedicao
# manual destes 2 strings (low risk, pouco volume).
_FILL_DEFICIT = "rgba(204, 9, 47, 0.15)"      # COR_DESTAQUE @ 15%
_FILL_SECUNDARIA = "rgba(46, 125, 50, 0.15)"  # COR_SUCESSO @ 15%
_TRANSPARENT = "rgba(0,0,0,0)"


def _construir_figura_gsf(df: pd.DataFrame) -> go.Figure:
    """Monta a figura Plotly do GSF mensal com areas semanticas
    deficit/secundaria.

    Padrao classico Plotly de "fill condicional" usando 4 traces:
        baseline -> y_baixo (fill='tonexty' = deficit, vermelho)
        baseline -> y_alto  (fill='tonexty' = secundaria, verde)
    Linha principal preta vai POR CIMA como ultimo trace.
    """
    x = df.index
    y_gsf_pct = (df["gsf"].values * 100).astype(float)
    y_baseline_100 = np.full(len(df), 100.0)
    # Para cada ponto: min(GSF, 100) define o teto da area deficit
    y_baixo = np.minimum(y_gsf_pct, 100.0)
    # max(GSF, 100) define o topo da area secundaria
    y_alto = np.maximum(y_gsf_pct, 100.0)

    fig = go.Figure()

    # ---- Area DEFICIT (entre baseline 100 e y_baixo) ----
    # Trace 1: baseline invisivel pra referencia do fill
    fig.add_trace(go.Scatter(
        x=x, y=y_baseline_100,
        mode="lines",
        line=dict(color=_TRANSPARENT, width=0),
        showlegend=False,
        hoverinfo="skip",
        name="_baseline_deficit",
    ))
    # Trace 2: y_baixo com fill pra cima ate trace 1
    fig.add_trace(go.Scatter(
        x=x, y=y_baixo,
        mode="lines",
        line=dict(color=_TRANSPARENT, width=0),
        fill="tonexty",
        fillcolor=_FILL_DEFICIT,
        name="Déficit",
        hoverinfo="skip",
    ))

    # ---- Area SECUNDARIA (entre baseline 100 e y_alto) ----
    # Trace 3: baseline novamente (necessario pq tonexty conecta com previa)
    fig.add_trace(go.Scatter(
        x=x, y=y_baseline_100,
        mode="lines",
        line=dict(color=_TRANSPARENT, width=0),
        showlegend=False,
        hoverinfo="skip",
        name="_baseline_secundaria",
    ))
    # Trace 4: y_alto com fill pra baixo ate trace 3
    fig.add_trace(go.Scatter(
        x=x, y=y_alto,
        mode="lines",
        line=dict(color=_TRANSPARENT, width=0),
        fill="tonexty",
        fillcolor=_FILL_SECUNDARIA,
        name="Energia Secundária",
        hoverinfo="skip",
    ))

    # ---- Linha PRINCIPAL GSF (POR CIMA dos fills) ----
    fig.add_trace(go.Scatter(
        x=x, y=y_gsf_pct,
        mode="lines",
        line=dict(color=COR_TEXTO, width=2),
        name="GSF mensal",
        hovertemplate=(
            "%{x|%b/%Y}<br>"
            "GSF: %{y:.2f}%"
            "<extra></extra>"
        ),
    ))

    # ---- Paridade GF 100% (linha de referencia horizontal) ----
    fig.add_hline(
        y=100,
        line=dict(color=COR_TEXTO_SECUND, width=1, dash="dash"),
        annotation=dict(
            text="Paridade GF (100%)",
            font=dict(color=COR_TEXTO_SECUND, size=11),
            xanchor="right",
            yanchor="bottom",
        ),
        annotation_position="top right",
    )

    # ---- Layout ----
    layout = plotly_layout_defaults()
    fig.update_layout(
        **layout,
        title=dict(
            text="Fator de Ajuste do MRE (GSF) — SIN",
            font=dict(size=16),
        ),
        height=460,
        hovermode="x unified",
    )
    fig.update_xaxes(title_text="")
    fig.update_yaxes(
        title_text="GSF (%)",
        tickformat=".1f",
        ticksuffix="%",
    )

    return fig


def render_aba_gsf() -> None:
    """Entry point da sub-aba GSF (chamada de app.py)."""
    # Header padrao do projeto
    st.markdown("# GSF — FATOR DE AJUSTE DO MRE")
    st.markdown(
        '<div style="border-bottom: 2px solid #313131; '
        'margin: 0 0 -1.5rem 0;"></div>',
        unsafe_allow_html=True,
    )

    # Carregar dados
    with st.spinner("Carregando GSF (cold ~25s na 1ª vez; warm-disk ~0.06s)..."):
        df = load_gsf_mensal()

    if df.empty:
        st.error("load_gsf_mensal() retornou DataFrame vazio.")
        return

    # Gráfico principal
    fig = _construir_figura_gsf(df)
    st.plotly_chart(fig, use_container_width=True)

    # Debug colapsado (legado da Fase 2A — diagnostico do retorno)
    with st.expander("Diagnóstico do `load_gsf_mensal()` (Fase 2A)",
                     expanded=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Linhas (meses)", f"{len(df)}")
        with col2:
            st.metric("Primeiro mês", df.index.min().strftime("%Y-%m"))
        with col3:
            st.metric("Último mês", df.index.max().strftime("%Y-%m"))
        st.markdown("**Últimos 3 meses (tail):**")
        st.dataframe(df.tail(3), use_container_width=True)
