"""
tab_modulacao.py
================

Aba MODULAÇÃO do dashboard do setor elétrico.

Calcula spread de captura por janela (mensal/trimestral/semanal) e por
(submercado, fonte):
    spread = PLD médio ponderado pela geração − PLD médio flat
           = Σh(mwmed × pld) / Σh(mwmed)  −  Σh(pld) / N_h

Interpretação:
  - Positivo: fonte gera mais nas horas caras (ganha vs flat).
  - Negativo: fonte gera mais nas horas baratas (perde vs flat).

Fontes: hidro, eólica, solar.
Submercados: SE, S, NE, N (PLD não cobre SIN).
Período: 2022-01-01 até última hora da interseção balanço × PLD.

Granularidades: Mensal (default), Trimestral, Semanal.
"""

from __future__ import annotations

import traceback

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_loader import (
    load_balanco_subsistema,
    load_pld_horaria,
    _make_disk_cache_helpers,
)


# =============================================================================
# Paleta Bauhaus — duplicada do app.py/tab_curtailment.py (circular import).
# Refator futuro: mover pra utils/bauhaus_palette.py (decisão 5.33 pendente).
# =============================================================================

BAUHAUS_BLACK  = "#1A1A1A"
BAUHAUS_CREAM  = "#F5F1E8"
BAUHAUS_LIGHT  = "#E8E3D4"

COR_FONTE_HIDRO  = "#4A6FA5"
COR_FONTE_EOLICA = "#8FA31E"
COR_FONTE_SOLAR  = "#F6BD16"

CORES_FONTE_MOD = {
    "hidro":  COR_FONTE_HIDRO,
    "eolica": COR_FONTE_EOLICA,
    "solar":  COR_FONTE_SOLAR,
}

LABELS_FONTE_MOD = {
    "hidro":  "Hidráulica",
    "eolica": "Eólica",
    "solar":  "Solar",
}


# =============================================================================
# Constantes do dataset
# =============================================================================

ORDEM_SUBMERCADOS = ["SE", "S", "NE", "N"]
FONTES_ALVO = ["hidro", "eolica", "solar"]
CUTOFF_DATA = pd.Timestamp("2022-01-01")

# Nome completo do submercado pra exibição no título do gráfico.
NOMES_SUBMERCADO = {
    "SE": "SUDESTE",
    "S":  "SUL",
    "NE": "NORDESTE",
    "N":  "NORTE",
}


# =============================================================================
# Granularidade — freq pandas, mínimo de horas e labels de UI
# =============================================================================

GRANULARIDADE_FREQ = {
    "mensal":     "M",
    "trimestral": "Q",
    "semanal":    "W",   # default W-SUN: semana Mon→Sun (start_time=Mon)
}

# Mínimo de horas pra considerar período completo (drop hard de períodos
# parciais — geralmente afeta apenas o último período do dataset).
GRANULARIDADE_MIN_HORAS = {
    "mensal":     28 * 24,    # 672  (fev em ano comum)
    "trimestral": 89 * 24,    # 2136 (Q1 não bissexto = 90 dias; folga de 1)
    "semanal":    7 * 24,     # 168
}

LABELS_GRANULARIDADE = {
    "mensal":     "Mensal",
    "trimestral": "Trimestral",
    "semanal":    "Semanal",
}

# Presets de período por granularidade.
# Tupla: (label, n_periodos) — n_periodos=None significa "Máx" (todo dataset).
PRESETS_POR_GRANULARIDADE = {
    "mensal": [
        ("12M", 12),
        ("Máx", None),
    ],
    "trimestral": [
        ("12M", 4),
        ("24M", 8),
    ],
    "semanal": [
        ("1M", 4),
        ("3M", 13),
    ],
}

DEFAULT_PRESET_POR_GRANULARIDADE = {
    "mensal":     "12M",
    "trimestral": "12M",
    "semanal":    "1M",
}


# =============================================================================
# Mês PT-BR (sem depender de locale do sistema — Cloud usa Linux)
# =============================================================================

MESES_PT = {
    1: "jan", 2: "fev", 3: "mar", 4: "abr", 5: "mai", 6: "jun",
    7: "jul", 8: "ago", 9: "set", 10: "out", 11: "nov", 12: "dez",
}


def _fmt_periodo(ts, granularidade: str) -> str:
    """Formata um Timestamp de início de período conforme granularidade.

    mensal     → 'mai/26'
    trimestral → '2T26'
    semanal    → 'S19/26'  (ISO week + ano ISO)
    """
    ts = pd.Timestamp(ts)
    if granularidade == "mensal":
        return f"{MESES_PT[ts.month]}/{ts.year % 100:02d}"
    if granularidade == "trimestral":
        q = (ts.month - 1) // 3 + 1
        return f"{q}T{ts.year % 100:02d}"
    if granularidade == "semanal":
        # ISO week numbering — ano ISO pode divergir do civil em viradas
        # de ano (S52/S53 vs S01). Usamos isocalendar pra consistência.
        iso = ts.isocalendar()
        return f"S{iso.week:02d}/{iso.year % 100:02d}"
    raise ValueError(f"Granularidade desconhecida: {granularidade!r}")


# =============================================================================
# Disk cache — 1 helper por granularidade, TTL 24h.
# Schema v2: coluna periodo_inicio (em vez de ano_mes do v1).
# Arquivos: modulacao_spread_v2_{mensal,trimestral,semanal}.parquet
# Reusa fábrica do data_loader.py (decisão 5.15).
# =============================================================================

_DISK_CACHE_HELPERS_POR_GRANULARIDADE = {
    g: _make_disk_cache_helpers(
        f"modulacao_spread_v2_{g}", ttl_sec=60 * 60 * 24,
    )
    for g in ["mensal", "trimestral", "semanal"]
}


# =============================================================================
# Cálculo principal — cache 2-layer (RAM 30d + disk 24h)
# =============================================================================

@st.cache_data(
    ttl=60 * 60 * 24 * 30,
    show_spinner="Calculando spread de captura...",
)
def _calcular_spread(granularidade: str) -> pd.DataFrame:
    """Calcula spread por (periodo_inicio, submercado, fonte).

    granularidade ∈ {'mensal', 'trimestral', 'semanal'}.

    Retorno: DataFrame com colunas
        periodo_inicio  datetime64  primeiro dia do mês/trim/semana
        submercado      str         {SE, S, NE, N}
        fonte           str         {hidro, eolica, solar}
        spread_rs_mwh   float       R$/MWh
        mwmed_medio     float       MWmed médio no período (representatividade)
        n_horas         int         total de horas no período (sanity)
    """
    if granularidade not in GRANULARIDADE_FREQ:
        raise ValueError(f"Granularidade desconhecida: {granularidade!r}")

    _, _, try_read, try_write = (
        _DISK_CACHE_HELPERS_POR_GRANULARIDADE[granularidade]
    )
    df_disk = try_read()
    if df_disk is not None:
        return df_disk

    # --- Balanço (cobertura: 2022+, horário, 5 submercados) ---
    df_bal = load_balanco_subsistema()
    df_bal = df_bal[
        (df_bal["data_hora"] >= CUTOFF_DATA)
        & (df_bal["fonte"].isin(FONTES_ALVO))
        & (df_bal["submercado"].isin(ORDEM_SUBMERCADOS))
    ][["data_hora", "submercado", "fonte", "mwmed"]].copy()

    # --- PLD horário (cobertura: 2021+, horário, 4 submercados) ---
    # ATENÇÃO: coluna de timestamp do PLD horário é 'data' (com hora dentro).
    df_pld = load_pld_horaria()
    df_pld = df_pld[
        (df_pld["data"] >= CUTOFF_DATA)
        & (df_pld["submercado"].isin(ORDEM_SUBMERCADOS))
    ][["data", "submercado", "pld"]].copy()
    df_pld = df_pld.rename(columns={"data": "data_hora"})

    # --- Merge inner por (data_hora, submercado) ---
    df = df_bal.merge(df_pld, on=["data_hora", "submercado"], how="inner")

    # --- Agregação por período (mês/trim/semana) ---
    freq = GRANULARIDADE_FREQ[granularidade]
    df["periodo_inicio"] = (
        df["data_hora"].dt.to_period(freq).dt.start_time
    )
    df["mwmed_pld"] = df["mwmed"] * df["pld"]

    g = df.groupby(["periodo_inicio", "submercado", "fonte"]).agg(
        num=("mwmed_pld", "sum"),
        den_pond=("mwmed", "sum"),
        sum_pld=("pld", "sum"),
        n_horas=("pld", "count"),
        mwmed_medio=("mwmed", "mean"),
    ).reset_index()

    # Defensivo contra divisão por zero.
    g["pld_pond"] = np.where(
        g["den_pond"] > 0, g["num"] / g["den_pond"], np.nan,
    )
    g["pld_flat"] = np.where(
        g["n_horas"] > 0, g["sum_pld"] / g["n_horas"], np.nan,
    )
    g["spread_rs_mwh"] = g["pld_pond"] - g["pld_flat"]

    # Drop períodos parciais.
    g = g[g["n_horas"] >= GRANULARIDADE_MIN_HORAS[granularidade]].copy()

    out = g[
        ["periodo_inicio", "submercado", "fonte", "spread_rs_mwh",
         "mwmed_medio", "n_horas"]
    ].sort_values(
        ["periodo_inicio", "submercado", "fonte"]
    ).reset_index(drop=True)

    try_write(out)
    return out


# =============================================================================
# Resolver janela (data_ini, data_fim) a partir do preset
# =============================================================================

def _resolver_janela(df_spread: pd.DataFrame, preset_label: str,
                    granularidade: str):
    """Devolve (data_ini, data_fim) com base no preset + dataset disponível.

    n_periodos vem do PRESETS_POR_GRANULARIDADE. Se None ('Máx'), data_ini =
    início absoluto do dataset. Caso contrário, conta n_periodos do fim do
    dataset.
    """
    max_d = df_spread["periodo_inicio"].max()
    min_d = df_spread["periodo_inicio"].min()
    if pd.isna(max_d) or pd.isna(min_d):
        return min_d, max_d

    presets = PRESETS_POR_GRANULARIDADE[granularidade]
    n_periodos = dict(presets).get(preset_label)
    if n_periodos is None:
        return min_d, max_d

    periodos_unicos = sorted(df_spread["periodo_inicio"].unique())
    if not periodos_unicos:
        return min_d, max_d
    idx_ini = max(0, len(periodos_unicos) - n_periodos)
    return pd.Timestamp(periodos_unicos[idx_ini]), max_d


# =============================================================================
# Render de UM gráfico (chamado 4× — uma vez por submercado)
# =============================================================================

def _render_grafico_submercado(
    df_periodo: pd.DataFrame, submercado: str, granularidade: str,
) -> None:
    """Título Bauhaus + grouped bar com 3 fontes pra UM submercado."""
    if df_periodo.empty:
        return

    df_periodo = df_periodo.sort_values("periodo_inicio").copy()

    # --- Título Bauhaus (padrão tab_curtailment.py:636) ---
    periodo_min = _fmt_periodo(
        df_periodo["periodo_inicio"].min(), granularidade,
    )
    periodo_max = _fmt_periodo(
        df_periodo["periodo_inicio"].max(), granularidade,
    )
    periodo_str = (
        periodo_min if periodo_min == periodo_max
        else f"{periodo_min} a {periodo_max}"
    )

    nome_completo = NOMES_SUBMERCADO[submercado]
    st.markdown(
        f'<div style="display:flex; justify-content:space-between; '
        f'align-items:baseline; '
        f"font-family:'Bebas Neue', sans-serif; "
        f'font-size:1.1rem; letter-spacing:0.08em; color:{BAUHAUS_BLACK}; '
        f'margin: 2.6rem 0 0.3rem 0; padding-bottom:3px; '
        f'border-bottom: 2px solid {BAUHAUS_BLACK};">'
        f'<span>SPREAD DE MODULAÇÃO · {nome_completo}</span>'
        f'<span>{periodo_str}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # --- Subtítulo Inter (padrão decisão 5.22) ---
    gran_label = LABELS_GRANULARIDADE[granularidade]
    st.markdown(
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.9rem; color:{BAUHAUS_BLACK}; font-weight:500; '
        f'letter-spacing:0.04em; margin:0 0 0.5rem 0;">'
        f'{gran_label} · PLD ponderado pela geração (R$/MWh)'
        f'</div>',
        unsafe_allow_html=True,
    )

    # X labels pré-formatados (categorial — preserva ordem cronológica).
    df_periodo["x_label"] = df_periodo["periodo_inicio"].apply(
        lambda ts: _fmt_periodo(ts, granularidade)
    )

    fig = go.Figure()
    for fonte in FONTES_ALVO:
        sub = df_periodo[df_periodo["fonte"] == fonte]
        if sub.empty:
            continue
        cor = CORES_FONTE_MOD[fonte]
        label = LABELS_FONTE_MOD[fonte]
        label_fix = label.ljust(12).replace(" ", "&nbsp;")

        # Hover: customdata com decimal BR (foolproof vs separators).
        customdata = np.array([
            f"R$ {v:.2f}/MWh".replace(".", ",") if pd.notna(v) else "—"
            for v in sub["spread_rs_mwh"]
        ])

        # Labels acima/abaixo das barras (inteiro, sinal automático).
        bar_text = [
            f"{v:.0f}" if pd.notna(v) else ""
            for v in sub["spread_rs_mwh"]
        ]

        fig.add_trace(go.Bar(
            x=sub["x_label"],
            y=sub["spread_rs_mwh"],
            name=label,
            marker=dict(color=cor),
            text=bar_text,
            textposition="outside",
            textfont=dict(
                family="Inter, sans-serif",
                size=12,
                color=cor,
                weight="bold",
            ),
            customdata=customdata,
            hovertemplate=(
                f'<span style="color:{cor}; font-weight:700;">'
                f'{label_fix}</span>'
                '&nbsp;&nbsp;'
                f'<span style="color:{BAUHAUS_BLACK};">%{{customdata}}</span>'
                '<extra></extra>'
            ),
        ))

    # --- Linha horizontal y=0 (referência crítica pra spread) ---
    fig.add_hline(
        y=0, line=dict(color=BAUHAUS_BLACK, width=1.5, dash="solid"),
    )

    fig.update_layout(
        barmode="group",
        height=380,
        margin=dict(l=20, r=20, t=40, b=20),
        paper_bgcolor=BAUHAUS_CREAM,
        plot_bgcolor=BAUHAUS_CREAM,
        separators=",.",   # Decimal BR no eixo Y (vírgula=decimal, ponto=milhar)
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
        xaxis=dict(
            title=None, showgrid=False, showline=True,
            linewidth=2, linecolor=BAUHAUS_BLACK,
            ticks="outside", tickcolor=BAUHAUS_BLACK,
            tickfont=dict(
                family="Inter, sans-serif",
                size=12, color=BAUHAUS_BLACK,
            ),
            type="category",
        ),
        yaxis=dict(
            title=None,
            showgrid=True, gridcolor=BAUHAUS_LIGHT, gridwidth=1,
            showline=True, linewidth=2, linecolor=BAUHAUS_BLACK,
            ticks="outside", tickcolor=BAUHAUS_BLACK,
            tickfont=dict(
                family="Inter, sans-serif",
                size=12, color=BAUHAUS_BLACK,
            ),
            zeroline=False,
            tickformat=",.0f",
        ),
        font=dict(family="Inter, sans-serif", size=12),
    )

    st.plotly_chart(
        fig, use_container_width=True, config={"displaylogo": False},
    )


# =============================================================================
# Wrappers principais (padrão tab_curtailment.py / tab_geracao_grupo.py)
# =============================================================================

def render_aba_modulacao() -> None:
    """Wrapper defensivo. Captura crash e exibe stack trace na tela em vez
    de propagar pra Streamlit (que mostraria 'Oh no' no lugar)."""
    try:
        _render_aba_modulacao_impl()
    except Exception:
        st.error("⚠️ Erro ao carregar aba Modulação (debug ativo)")
        st.code(traceback.format_exc(), language="python")
        st.caption(
            "Este erro foi capturado para investigação. "
            "Por favor, copie o stack trace acima e reporte."
        )


def _render_aba_modulacao_impl() -> None:
    """Renderiza a aba Modulação: selectbox de granularidade + 2 presets de
    período + 4 gráficos empilhados (SE/S/NE/N)."""
    # Título h1 (mesmo padrão das outras abas)
    st.markdown("# MODULAÇÃO")

    # Caption explicativa (Inter italic cinza)
    st.markdown(
        '<div style="font-family:\'Inter\', sans-serif; '
        'font-size:0.85rem; color:#6B6B6B; font-style:italic; '
        'margin:0 0 0.8rem 0;">'
        'Spread de captura (R$/MWh) = PLD médio ponderado pela geração '
        '<strong>menos</strong> PLD médio flat. Positivo = fonte gera mais nas '
        'horas caras. Negativo = gera mais nas horas baratas.'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Controles: selectbox granularidade + 2 botões preset (1 linha) ---
    st.session_state.setdefault("mod_granularidade", "mensal")

    gran_opts = ["mensal", "trimestral", "semanal"]

    # Layout: selectbox à esquerda (col 0), spacer (col 1), 2 botões à direita.
    cols_ctrl = st.columns([2, 4, 1, 1])

    with cols_ctrl[0]:
        nova_gran = st.selectbox(
            "Granularidade",
            options=gran_opts,
            format_func=lambda g: LABELS_GRANULARIDADE[g],
            key="mod_granularidade_widget",
            index=gran_opts.index(st.session_state["mod_granularidade"]),
            label_visibility="collapsed",
        )

    # Detecta troca de granularidade → reseta preset pro default da nova gran.
    if nova_gran != st.session_state["mod_granularidade"]:
        st.session_state["mod_granularidade"] = nova_gran
        st.session_state["mod_periodo_preset"] = (
            DEFAULT_PRESET_POR_GRANULARIDADE[nova_gran]
        )
        st.rerun()

    granularidade = st.session_state["mod_granularidade"]

    # --- Resolver preset atual (com fallback defensivo se label inválido) ---
    presets = PRESETS_POR_GRANULARIDADE[granularidade]
    labels_validos = [p[0] for p in presets]
    default_preset = DEFAULT_PRESET_POR_GRANULARIDADE[granularidade]

    preset_atual = st.session_state.get("mod_periodo_preset", default_preset)
    if preset_atual not in labels_validos:
        preset_atual = default_preset
        st.session_state["mod_periodo_preset"] = default_preset

    # --- 2 botões de preset (cols 2 e 3) ---
    for i, (label, _) in enumerate(presets):
        with cols_ctrl[i + 2]:
            tipo = "primary" if label == preset_atual else "secondary"
            if st.button(
                label, key=f"btn_mod_{label}",
                type=tipo, use_container_width=True,
            ):
                st.session_state["mod_periodo_preset"] = label
                st.rerun()

    # --- Cálculo do spread (cache 2-layer) ---
    df_spread = _calcular_spread(granularidade)
    if df_spread.empty:
        st.warning("Sem dados de spread disponíveis no momento.")
        return

    data_ini, data_fim = _resolver_janela(
        df_spread, preset_atual, granularidade,
    )
    if pd.isna(data_ini) or pd.isna(data_fim):
        st.warning("Sem dados no período selecionado.")
        return

    df_filtrado = df_spread[
        (df_spread["periodo_inicio"] >= data_ini)
        & (df_spread["periodo_inicio"] <= data_fim)
    ]
    if df_filtrado.empty:
        st.warning("Sem dados no período selecionado.")
        return

    for sub in ORDEM_SUBMERCADOS:
        df_sub = df_filtrado[df_filtrado["submercado"] == sub]
        if df_sub.empty:
            continue
        _render_grafico_submercado(df_sub, sub, granularidade)
