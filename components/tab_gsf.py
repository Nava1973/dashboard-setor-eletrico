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
    2D — period controls: date_input De/Ate, default 12M
    2D++ — refator (este commit): selectbox de periodo (MM/AAAA mensal,
           "1T26" trimestral) + granularidade Mensal/Trimestral, layout
           7 colunas do padrao Modulacao
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


def _construir_label_trimestre(ts: pd.Timestamp) -> str:
    """'2026-01-01' (start of 1T26) -> '1T26'."""
    ts = pd.Timestamp(ts)
    trim = (ts.month - 1) // 3 + 1
    return f"{trim}T{ts.year % 100:02d}"


# =============================================================================
# Granularidade (Fase 2D+)
# =============================================================================

LABELS_GRANULARIDADE = {
    "mensal":     "Mensal",
    "trimestral": "Trimestral",
}
_GRANULARIDADES = tuple(LABELS_GRANULARIDADE.keys())

# Offset em meses pra computar data_ini default a partir de data_fim.
# Mensal 12 = mantem comportamento aprovado em 2D (13 month-starts visiveis).
# Trimestral 21 = exatamente 8 trimestres (start-of-quarter da janela).
_DEFAULT_OFFSET_MESES = {
    "mensal":     12,
    "trimestral": 21,
}


def _marcar_datas_custom_gsf() -> None:
    """on_change dos date_inputs: marca que o usuario mexeu nas datas.

    Enquanto gsf_datas_custom eh False, trocar de granularidade re-deriva
    a janela pro default da nova granularidade (sempre mostra ate o
    ultimo periodo disponivel). Quando True, a janela custom persiste
    entre granularidades — soh muda a agregacao subjacente.
    """
    st.session_state["gsf_datas_custom"] = True


def _agregar_trimestral(df_mensal: pd.DataFrame) -> pd.DataFrame:
    """Agrega df mensal -> trimestral. Index = start-of-quarter.

    GSF recalculado do trimestre (sum / sum), NAO media de GSFs mensais
    — semantica contabil correta.

    Drop de trimestres incompletos NO INICIO (n_meses < 3) — exceto o
    ultimo, que pode ser parcial (trim em andamento).
    """
    # 'QS' = quarter start frequency. Index resultante eh start-of-quarter
    # (jan/abr/jul/out) — alinhado com convencao do projeto (1o dia do periodo).
    agg = df_mensal.groupby(pd.Grouper(freq="QS")).agg(
        sum_geracao_mre_mwh=("sum_geracao_mre_mwh", "sum"),
        sum_gf_mre_mwh=("sum_gf_mre_mwh", "sum"),
        fonte_dado=("fonte_dado", "first"),
        n_meses=("gsf", "count"),
    )
    if agg.empty:
        agg["gsf"] = []
        return agg.drop(columns=["n_meses"])

    # Drop incompletos no INICIO; preserva o ultimo mesmo se parcial.
    max_idx = agg.index.max()
    mask = (agg["n_meses"] >= 3) | (agg.index == max_idx)
    agg = agg[mask].copy()

    agg["gsf"] = agg["sum_geracao_mre_mwh"] / agg["sum_gf_mre_mwh"]
    agg = agg.drop(columns=["n_meses"])
    agg.index.name = "mes_ref"
    return agg


def _converter_periodo(ts, granularidade: str) -> pd.Timestamp:
    """Snap ts pro start-of-period da granularidade.

    mensal:     start-of-month (1o dia do mes que contem ts)
    trimestral: start-of-quarter (1o dia do trim que contem ts)

    Usado na troca de granularidade quando gsf_datas_custom=True —
    converte as datas custom (uma "ancora") pro 1o dia do periodo
    correspondente na nova granularidade.
    """
    ts = pd.Timestamp(ts)
    if granularidade == "trimestral":
        return ts.to_period("Q").start_time
    return ts.to_period("M").start_time


def _snap_to_options(ts, options: list) -> pd.Timestamp:
    """Garante que ts existe em options; senao snap pro mais proximo <= ts
    (ou primeiro/ultimo nas bordas).

    Usado como clamp defensivo antes de instanciar selectbox: cobre
    (a) migracao de tipo (date -> Timestamp ao reabrir sessao 2D)
    (b) dataset shrinking entre granularidades
    (c) qualquer valor de state que nao seja exatamente igual a um option

    Streamlit lanca exception "value is not in options" se a key do
    selectbox tem valor fora da lista — esse snap previne isso.
    """
    if not options:
        return pd.Timestamp(ts)
    ts = pd.Timestamp(ts)
    options_sorted = sorted(options)
    if ts in options_sorted:
        return ts
    if ts <= options_sorted[0]:
        return options_sorted[0]
    if ts >= options_sorted[-1]:
        return options_sorted[-1]
    # ts no meio do range mas nao bate exato: snap pro maior <= ts
    valid = [o for o in options_sorted if o <= ts]
    return valid[-1] if valid else options_sorted[0]


def _default_janela_gsf(
    df_agg: pd.DataFrame, granularidade: str,
) -> tuple:
    """Retorna (data_ini_default, data_fim_default) como date objects
    pra inicializar gsf_data_ini/gsf_data_fim na 1a carga ou ao trocar
    granularidade sem datas custom.

    mensal: data_fim - 12 meses (~13 month-starts visiveis, igual 2D).
    trimestral: data_fim - 21 meses (exatamente 8 trimestres).
    """
    if df_agg.empty:
        # Sem dados — devolve um par seguro mesmo
        hoje = pd.Timestamp.today().normalize()
        return hoje.date(), hoje.date()
    ultimo_ts = df_agg.index.max()
    primeiro_ts = df_agg.index.min()
    offset_meses = _DEFAULT_OFFSET_MESES.get(granularidade, 12)
    data_ini_ts = ultimo_ts - pd.DateOffset(months=offset_meses)
    if data_ini_ts < primeiro_ts:
        data_ini_ts = primeiro_ts
    return data_ini_ts.date(), ultimo_ts.date()


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


def _construir_figura_gsf(
    df: pd.DataFrame, granularidade: str = "mensal",
) -> go.Figure:
    """Monta a figura Plotly do GSF com areas semanticas deficit/secundaria.

    Suporta mensal e trimestral (Fase 2D+). O eixo X adapta:
      - mensal: tickformat="%b/%y" (ex: "Nov/23"), dtick="M1"
      - trimestral: tickvals + ticktext via _construir_label_trimestre
        (ex: "1T26"). Sem dtick (1 tick por ponto).

    Padrao classico Plotly de "fill condicional" usando 4 traces:
        baseline -> y_baixo (fill='tonexty' = deficit, vermelho)
        baseline -> y_alto  (fill='tonexty' = secundaria, azul ceu)
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
    # Eixo X — adapta por granularidade (Fase 2D+).
    if granularidade == "trimestral":
        # tickvals/ticktext explicito: 1 tick por trimestre, label custom
        # "1T26" (Plotly nao tem format string nativo pra trimestre).
        tickvals_trim = list(df.index)
        ticktext_trim = [_construir_label_trimestre(ts) for ts in tickvals_trim]
        fig.update_xaxes(
            title_text="",
            tickvals=tickvals_trim,
            ticktext=ticktext_trim,
            tickangle=-45,
        )
    else:
        # Mensal: tick por mes, format compacto "Nov/23".
        fig.update_xaxes(
            title_text="",
            dtick="M1",
            tickformat="%b/%y",
            tickangle=-45,
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

    # ----- Period controls (Fase 2D++) -----
    # Padrao do componente Modulacao: layout FIXO de 7 colunas
    # [2, 1, 1, 1, 5.2, 1.5, 1.5] independente da granularidade.
    #   cols[0]    = selectbox granularidade (label collapsed)
    #   cols[1..3] = INTENCIONALMENTE VAZIOS (era pra presets na Modulacao;
    #                GSF nao expoe presets — slots preservados pra alinhar
    #                visualmente com outras abas).
    #   cols[4]    = spacer
    #   cols[5..6] = selectbox "De" / "Ate" (substituem o date_input do 2D
    #                porque GSF eh serie mensal/trimestral-nativa — dia
    #                arbitrario seria ignorado, gerando UX confusa).
    #
    # Layout FIXO + zero st.rerun() na troca de granularidade sao
    # intencionais (vide comentarios da Modulacao): rerun explicito
    # limparia keys de widget nao-renderizado naquele frame.
    st.session_state.setdefault("gsf_granularidade", "mensal")
    st.session_state.setdefault("gsf_datas_custom", False)

    cols = st.columns([2, 1, 1, 1, 5.2, 1.5, 1.5])
    with cols[0]:
        granularidade = st.selectbox(
            "Granularidade",
            options=list(_GRANULARIDADES),
            format_func=lambda g: LABELS_GRANULARIDADE[g],
            key="gsf_granularidade",
            label_visibility="collapsed",
        )
    # cols[1..3]: vazios (sem presets pro GSF — alinhamento visual).

    # Agregacao da granularidade ANTES dos selectbox de periodo (precisa
    # do df_agg pra ter as options corretas por granularidade).
    if granularidade == "trimestral":
        df_agg = _agregar_trimestral(df)
    else:
        df_agg = df

    # Init das datas (1a carga ou cleanup parcial — OR cobre ambos).
    if ("gsf_data_ini" not in st.session_state
            or "gsf_data_fim" not in st.session_state):
        di, dfim = _default_janela_gsf(df_agg, granularidade)
        st.session_state["gsf_data_ini"] = pd.Timestamp(di)
        st.session_state["gsf_data_fim"] = pd.Timestamp(dfim)

    # Detectar troca de granularidade.
    _gran_anterior = st.session_state.get("gsf_granularidade_anterior")
    houve_troca = (
        _gran_anterior is not None and _gran_anterior != granularidade
    )
    if houve_troca:
        if not st.session_state["gsf_datas_custom"]:
            # Re-derivar janela pro default da nova granularidade
            # (sempre mostra ate o ultimo periodo disponivel).
            di, dfim = _default_janela_gsf(df_agg, granularidade)
            st.session_state["gsf_data_ini"] = pd.Timestamp(di)
            st.session_state["gsf_data_fim"] = pd.Timestamp(dfim)
        else:
            # Datas custom: converter pro start-of-period da nova
            # granularidade (Mensal "Dez/2024" -> Trim "4T24" etc.).
            ini_atual = st.session_state["gsf_data_ini"]
            fim_atual = st.session_state["gsf_data_fim"]
            st.session_state["gsf_data_ini"] = _converter_periodo(
                ini_atual, granularidade,
            )
            st.session_state["gsf_data_fim"] = _converter_periodo(
                fim_atual, granularidade,
            )
    # Atualiza sempre (FORA do if) — sem isso, troca em 2 steps falha.
    st.session_state["gsf_granularidade_anterior"] = granularidade

    # Options dos selectbox = lista de start-of-period do df_agg.
    opts_periodo = list(df_agg.index)
    label_fn = (
        _construir_label_trimestre
        if granularidade == "trimestral"
        else _fmt_mes_pt
    )

    # Clamp/snap defensivo pras options atuais. Cobre 3 cenarios:
    #   (a) migracao 2D -> 2D++: state tinha date, options sao Timestamp;
    #   (b) dataset shrinking entre granularidades (trim max_d < mensal max_d);
    #   (c) qualquer valor stale fora das options atuais.
    # Streamlit lanca "value is not in options" se a key tem valor invalido —
    # esse snap garante que isso nunca acontece.
    st.session_state["gsf_data_ini"] = _snap_to_options(
        st.session_state["gsf_data_ini"], opts_periodo,
    )
    st.session_state["gsf_data_fim"] = _snap_to_options(
        st.session_state["gsf_data_fim"], opts_periodo,
    )

    with cols[5]:
        st.selectbox(
            "De",
            options=opts_periodo,
            format_func=label_fn,
            key="gsf_data_ini",
            on_change=_marcar_datas_custom_gsf,
        )
    with cols[6]:
        st.selectbox(
            "Até",
            options=opts_periodo,
            format_func=label_fn,
            key="gsf_data_fim",
            on_change=_marcar_datas_custom_gsf,
        )

    # Ler datas + swap silencioso se invertidas.
    data_ini = pd.Timestamp(st.session_state["gsf_data_ini"])
    data_fim = pd.Timestamp(st.session_state["gsf_data_fim"])
    if data_ini > data_fim:
        data_ini, data_fim = data_fim, data_ini

    # Filtragem simples: ambos sao start-of-period exatos (selectbox so
    # permite valores das options). Sem regra de "trimestre parcial"
    # — usuario escolhe trimestres inteiros, nao dias arbitrarios.
    df_grafico = df_agg[
        (df_agg.index >= data_ini) & (df_agg.index <= data_fim)
    ]
    if df_grafico.empty:
        st.warning("Período selecionado sem dados. Mostrando série completa.")
        df_grafico = df_agg

    # Gráfico principal (df_grafico filtrado + granularidade pro eixo X).
    fig = _construir_figura_gsf(df_grafico, granularidade)
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
