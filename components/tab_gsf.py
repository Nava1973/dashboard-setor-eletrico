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
    2B — grafico Plotly linha temporal
    2B+ — refinos: cor secundaria azul ceu, eixo X mensal, footnote
    2B++ — refinos finais: legenda topo, eixo Y sem decimal, hover preto
    2C — tabela HTML ultimos 12 meses
    2C+ — micro-fix: remove data duplicada no hover unified
    2D — period controls (este commit): date_input De/Ate, default 12M
    2E — polimento final (hover, markers, KPIs)

Notas de design:
    - Area "Deficit" usa COR_DESTAQUE (#CC092F vermelho Bradesco) opacidade 15%.
    - Area "Energia Secundaria" usa #87CEEB (sky blue) opacidade 30% —
      escolhido por feedback UX (verde COR_SUCESSO testado mas trocado
      por preferencia estetica de "abundancia clara").
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
    COR_BORDA_SUTIL,
    COR_FONTE_MMGD,
    plotly_layout_defaults,
)


# PT-BR (Plotly usa ingles no strftime — mapa manual evita locale dependency)
_MESES_PT_BR = {
    1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr",  5: "Mai", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez",
}


def _fmt_mes_pt(ts: pd.Timestamp) -> str:
    """'2026-03-01' -> 'Mar/2026'."""
    return f"{_MESES_PT_BR[ts.month]}/{ts.year}"


# Cores derivadas pros preenchimentos de area semantica.
# rgba inline em vez de utility pq sao usados so neste componente.
# Deficit: COR_DESTAQUE (#CC092F vermelho Bradesco) @ 15%.
# Secundaria: #87CEEB (sky blue) @ 30% — azul ceu = abundancia semantica
#   positiva. Verde (COR_SUCESSO #2E7D32) testado em iteracao anterior e
#   trocado por feedback UX. Alpha 30% (vs 15% do deficit) pq azul claro
#   ficaria fraco demais com 15%.
_FILL_DEFICIT = "rgba(204, 9, 47, 0.15)"        # COR_DESTAQUE @ 15%
_FILL_SECUNDARIA = "rgba(135, 206, 235, 0.30)"  # azul ceu — abundancia semantica positiva
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
        # hovermode="x unified" do layout ja injeta a data como header do
        # tooltip — incluir "%{x|...}" no template duplica o mes.
        hovertemplate=(
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
    # Sobrescreve legend dos defaults pra colocar no topo horizontal
    # (libera ~15% de largura util pro plot — refino 2B++ R1).
    layout["legend"] = dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1,
        font=dict(color=COR_TEXTO),
        bgcolor="rgba(0,0,0,0)",  # transparente, sem caixa
    )
    fig.update_layout(
        **layout,
        title=dict(
            text="Fator de Ajuste do MRE (GSF) — SIN",
            font=dict(size=16),
        ),
        height=460,
        hovermode="x unified",
        # Hover label: fonte maior e preta pra contraste maximo (R3).
        hoverlabel=dict(
            font=dict(size=14, color="#000000"),
        ),
    )
    fig.update_xaxes(
        title_text="",
        dtick="M1",            # 1 tick por mes (todos os meses visiveis)
        tickformat="%b/%y",    # formato compacto: "Nov/23"
        tickangle=-45,         # rotaciona pra caber sem sobrepor
    )
    fig.update_yaxes(
        title_text="GSF (%)",
        # tickformat ".0f" gera "90%" (sem decimal) nos eixos (R2).
        # Hover da linha principal mantem 2 decimais via hovertemplate
        # ("%{y:.2f}%") — precisao tecnica preservada no tooltip.
        tickformat=".0f",
        ticksuffix="%",
    )

    return fig


def _construir_tabela_12m(df: pd.DataFrame) -> str:
    """Constroi HTML da tabela "Detalhamento — Ultimos 12 meses".

    - Mais recente em CIMA (descending por mes)
    - Mes em PT-BR (Mar/2026)
    - GSF com 2 casas (100.32%)
    - TWh = MWh / 1_000_000 com 2 casas
    - Linhas com Energia Secundaria (GSF > 1.0) destacadas em amarelo
      claro (COR_FONTE_MMGD #FFE082)
    - Alternancia sutil (linhas pares cinza claro #FAFAFA) gerenciada
      via classe Python (nao :nth-child) pra que .secundaria sobreponha
      sem precisar !important
    """
    df_tail = df.tail(12)
    df_tail = df_tail.iloc[::-1]  # mais recente em cima

    css = f"""
    <style>
    .gsf-tab-12m {{
        width: 100%;
        border-collapse: collapse;
        font-family: 'Inter', sans-serif;
        margin-top: 0.5rem;
        margin-bottom: 0.5rem;
    }}
    .gsf-tab-12m thead th {{
        background: {COR_TEXTO};
        color: #FFFFFF;
        font-size: 13px;
        font-weight: 600;
        padding: 8px 12px;
        text-align: right;
        border: 1px solid {COR_BORDA_SUTIL};
    }}
    .gsf-tab-12m thead th.col-mes {{ text-align: left; }}
    .gsf-tab-12m tbody td {{
        padding: 8px 12px;
        font-size: 13px;
        color: {COR_TEXTO};
        border: 1px solid {COR_BORDA_SUTIL};
        text-align: right;
    }}
    .gsf-tab-12m tbody td.col-mes {{ text-align: left; font-weight: 600; }}
    .gsf-tab-12m tbody tr.row-par td {{ background: #FFFFFF; }}
    .gsf-tab-12m tbody tr.row-impar td {{ background: #FAFAFA; }}
    /* .secundaria sobrepoe a alternancia (especificidade igual, vem depois) */
    .gsf-tab-12m tbody tr.secundaria td {{ background: {COR_FONTE_MMGD}; }}
    </style>
    """

    head = (
        "<thead><tr>"
        '<th class="col-mes">Mês</th>'
        "<th>GSF (%)</th>"
        "<th>Geração MRE (TWh)</th>"
        "<th>GF MRE (TWh)</th>"
        "<th>Energia Secundária?</th>"
        "</tr></thead>"
    )

    linhas = []
    for i, (idx, row) in enumerate(df_tail.iterrows()):
        gsf = row["gsf"]
        eh_secundaria = gsf > 1.0
        classes = ["row-par" if i % 2 == 0 else "row-impar"]
        if eh_secundaria:
            classes.append("secundaria")
        cls = " ".join(classes)

        # Conversao MWh -> TWh (1 TWh = 1e6 MWh)
        ger_twh = row["sum_geracao_mre_mwh"] / 1_000_000.0
        gf_twh = row["sum_gf_mre_mwh"] / 1_000_000.0

        linhas.append(
            f'<tr class="{cls}">'
            f'<td class="col-mes">{_fmt_mes_pt(idx)}</td>'
            f"<td>{gsf * 100:.2f}%</td>"
            f"<td>{ger_twh:.2f}</td>"
            f"<td>{gf_twh:.2f}</td>"
            f'<td>{"Sim" if eh_secundaria else "Não"}</td>'
            "</tr>"
        )

    body = "<tbody>" + "".join(linhas) + "</tbody>"
    table = f'<table class="gsf-tab-12m">{head}{body}</table>'
    return css + table


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

    # ----- Period controls (Fase 2D) -----
    # Decisao: 2 date_input puros (sem shortcut buttons). UI mais limpa,
    # usuario tem controle total. Default na 1a carga = ultimos 12 meses.
    #
    # IMPORTANTE: init de session_state ANTES de instanciar widgets
    # (pattern do CLAUDE.md §5.12). Sem `value=` nos widgets — so `key=`,
    # pra evitar conflito de source of truth.
    primeiro_ts = df.index.min()
    ultimo_ts = df.index.max()
    if "gsf_data_ini" not in st.session_state:
        data_ini_default_ts = ultimo_ts - pd.DateOffset(months=12)
        if data_ini_default_ts < primeiro_ts:
            data_ini_default_ts = primeiro_ts
        st.session_state["gsf_data_ini"] = data_ini_default_ts.date()
        st.session_state["gsf_data_fim"] = ultimo_ts.date()

    col_lbl, col_de, col_ate = st.columns([1, 2, 2])
    with col_lbl:
        st.markdown("**Período:**")
    with col_de:
        st.date_input(
            "De",
            key="gsf_data_ini",
            min_value=primeiro_ts.date(),
            max_value=ultimo_ts.date(),
            format="DD/MM/YYYY",
        )
    with col_ate:
        st.date_input(
            "Até",
            key="gsf_data_fim",
            min_value=primeiro_ts.date(),
            max_value=ultimo_ts.date(),
            format="DD/MM/YYYY",
        )

    # Ler de volta e validar (se usuario inverteu ini>fim, swap silencioso)
    data_ini = st.session_state["gsf_data_ini"]
    data_fim = st.session_state["gsf_data_fim"]
    if data_ini > data_fim:
        data_ini, data_fim = data_fim, data_ini

    # Filtrar df pro grafico. df.index eh DatetimeIndex (1o dia do mes);
    # comparar via .date() pra alinhar com tipo date dos widgets.
    df_grafico = df[
        (df.index.date >= data_ini) & (df.index.date <= data_fim)
    ]
    if df_grafico.empty:
        # Defesa contra cenario "0 linhas" — nao deveria ocorrer
        # com min/max corretos, mas guarda contra edge cases.
        st.warning("Período selecionado sem dados. Mostrando série completa.")
        df_grafico = df

    # Gráfico principal (usa df_grafico filtrado)
    fig = _construir_figura_gsf(df_grafico)
    st.plotly_chart(fig, use_container_width=True)

    # Tabela "Detalhamento — Últimos 12 meses" (Fase 2C).
    # Decisao: SEMPRE fixa nos ultimos 12 meses, INDEPENDENTE dos period
    # controls do grafico. Tabela = "estado recente"; grafico = "evolucao".
    # Por isso usa `df` (completo), nao `df_grafico` (filtrado).
    st.markdown("### Detalhamento — Últimos 12 meses")
    st.markdown(_construir_tabela_12m(df), unsafe_allow_html=True)

    # Footnote com fórmula validada (R3 dos refinos 2B+)
    st.caption(
        "**Fórmula** (Regras de Comercialização CCEE, módulo MRE, "
        "item MR.2.1): GSF = Σ(GERACAO_MRE) / Σ(GARANTIA_FISICA_MRE), "
        "agregando 4 submercados × todas as horas do mês. Fonte: dataset "
        "CCEE GERACAO_HORARIA_SUBMERCADO. Validado em 12/12 meses contra "
        "valores oficiais (Power BI CCEE + InfoPLD)."
    )

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
