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
    2A — esqueleto (este commit): render minimo + chamada teste do loader
    2B — grafico Plotly linha temporal
    2C — tabela HTML ultimos 12 meses
    2D — period controls
    2E — polimento final (hover, markers, KPIs)
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from data_loaders.ccee_gsf import load_gsf_mensal


def render_aba_gsf() -> None:
    """Entry point da sub-aba GSF (chamada de app.py)."""
    # Header padrao do projeto (mesma estrutura de "CARGA" etc.)
    st.markdown("# GSF — EM CONSTRUÇÃO")
    st.markdown(
        '<div style="border-bottom: 2px solid #313131; '
        'margin: 0 0 -1.5rem 0;"></div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Sprint GSF Fase 2A — esqueleto. Valida que o data loader "
        "funciona dentro do app real."
    )

    # Smoke test do loader
    with st.spinner("Carregando GSF (cold ~25s na 1ª vez; warm-disk ~0.06s)..."):
        df = load_gsf_mensal()

    if df.empty:
        st.error("load_gsf_mensal() retornou DataFrame vazio.")
        return

    st.markdown("### Diagnóstico do retorno do `load_gsf_mensal()`")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Linhas (meses)", f"{len(df)}")
    with col2:
        st.metric("Primeiro mês", df.index.min().strftime("%Y-%m"))
    with col3:
        st.metric("Último mês", df.index.max().strftime("%Y-%m"))

    st.markdown("**Últimos 3 meses (tail):**")
    st.dataframe(df.tail(3), use_container_width=True)
