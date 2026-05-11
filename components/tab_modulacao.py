"""
tab_modulacao.py
================

Aba MODULAÇÃO do dashboard do setor elétrico.

Calcula spread de captura mensal por (submercado, fonte):
    spread = PLD médio ponderado pela geração − PLD médio flat
           = Σh(mwmed × pld) / Σh(mwmed)  −  Σh(pld) / N_h

Interpretação:
  - Positivo: fonte gera mais nas horas caras (ganha vs flat).
  - Negativo: fonte gera mais nas horas baratas (perde vs flat).

Fontes: hidro, eólica, solar.
Submercados: SE, S, NE, N (PLD não cobre SIN).
Período: 2022-01-01 até última hora da interseção balanço × PLD.
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

# Mês mínimo "completo" pra evitar último mês parcial.
# 28 dias × 24h = 672 horas (limite inferior — fev em ano comum).
MIN_HORAS_MES_COMPLETO = 28 * 24


# =============================================================================
# Mês PT-BR (sem depender de locale do sistema — Cloud usa Linux)
# =============================================================================

MESES_PT = {
    1: "jan", 2: "fev", 3: "mar", 4: "abr", 5: "mai", 6: "jun",
    7: "jul", 8: "ago", 9: "set", 10: "out", 11: "nov", 12: "dez",
}


def _fmt_mes_aa(ts) -> str:
    """'mai/26' a partir de Timestamp/datetime."""
    ts = pd.Timestamp(ts)
    return f"{MESES_PT[ts.month]}/{ts.year % 100:02d}"


# =============================================================================
# Disk cache 24h — TTL maior que o default 6h porque PLD demora a fechar.
# Reusa fábrica do data_loader.py (decisão 5.15).
# =============================================================================

(
    _get_modulacao_path,
    _is_modulacao_cache_fresh,
    _try_read_modulacao,
    _try_write_modulacao,
) = _make_disk_cache_helpers("modulacao_spread_mensal", ttl_sec=60 * 60 * 24)


# =============================================================================
# Cálculo principal — cache 2-layer (RAM 30d + disk 24h)
# =============================================================================

@st.cache_data(
    ttl=60 * 60 * 24 * 30,
    show_spinner="Calculando spread de captura mensal...",
)
def _calcular_spread_mensal() -> pd.DataFrame:
    """Calcula spread mensal por (ano_mes, submercado, fonte).

    Retorno: DataFrame com colunas
        ano_mes        datetime64  primeiro dia do mês
        submercado     str         {SE, S, NE, N}
        fonte          str         {hidro, eolica, solar}
        spread_rs_mwh  float       R$/MWh
        mwmed_medio    float       MWmed médio no mês (sinaliza representatividade)
        n_horas        int         total de horas no mês (sanity)
    """
    df_disk = _try_read_modulacao()
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
    # Renomeia pra 'data_hora' pra casar com balanço.
    df_pld = load_pld_horaria()
    df_pld = df_pld[
        (df_pld["data"] >= CUTOFF_DATA)
        & (df_pld["submercado"].isin(ORDEM_SUBMERCADOS))
    ][["data", "submercado", "pld"]].copy()
    df_pld = df_pld.rename(columns={"data": "data_hora"})

    # --- Merge inner por (data_hora, submercado) ---
    df = df_bal.merge(df_pld, on=["data_hora", "submercado"], how="inner")

    # --- Agregação mensal ---
    df["ano_mes"] = df["data_hora"].dt.to_period("M").dt.to_timestamp()
    df["mwmed_pld"] = df["mwmed"] * df["pld"]

    g = df.groupby(["ano_mes", "submercado", "fonte"]).agg(
        num=("mwmed_pld", "sum"),
        den_pond=("mwmed", "sum"),
        sum_pld=("pld", "sum"),
        n_horas=("pld", "count"),
        mwmed_medio=("mwmed", "mean"),
    ).reset_index()

    # Defensivo contra divisão por zero (solar tem mwmed=0 em ~50% das horas,
    # mas den_pond mensal sempre é positivo pq agrega 700+ horas; ainda assim).
    g["pld_pond"] = np.where(
        g["den_pond"] > 0, g["num"] / g["den_pond"], np.nan,
    )
    g["pld_flat"] = np.where(
        g["n_horas"] > 0, g["sum_pld"] / g["n_horas"], np.nan,
    )
    g["spread_rs_mwh"] = g["pld_pond"] - g["pld_flat"]

    # Drop meses parciais (último mês pode estar incompleto).
    g = g[g["n_horas"] >= MIN_HORAS_MES_COMPLETO].copy()

    out = g[
        ["ano_mes", "submercado", "fonte", "spread_rs_mwh",
         "mwmed_medio", "n_horas"]
    ].sort_values(["ano_mes", "submercado", "fonte"]).reset_index(drop=True)

    _try_write_modulacao(out)
    return out


# =============================================================================
# Controle de período — 2 botões (12M default | Máx) alinhados à direita
# =============================================================================

def _render_period_controls_mod(df_spread: pd.DataFrame):
    """Renderiza botões 12M (default) | Máx, key_prefix='btn_mod_'.

    Estado: st.session_state['mod_periodo_preset'] em {'12M', 'Máx'}.
    Retorna: (data_ini, data_fim) — Timestamps de 1º dia do mês.
    """
    max_d = df_spread["ano_mes"].max()
    min_d = df_spread["ano_mes"].min()

    if pd.isna(max_d) or pd.isna(min_d):
        return min_d, max_d

    target_12m = max_d - pd.DateOffset(months=11)
    presets = {
        "12M": max(target_12m, min_d),
        "Máx": min_d,
    }

    preset_atual = st.session_state.get("mod_periodo_preset", "12M")

    # Layout: spacer largo + 2 botões à direita.
    cols = st.columns([6, 1, 1])
    for i, label in enumerate(presets.keys()):
        with cols[i + 1]:
            tipo = "primary" if label == preset_atual else "secondary"
            if st.button(
                label, key=f"btn_mod_{label}",
                type=tipo, use_container_width=True,
            ):
                st.session_state["mod_periodo_preset"] = label
                st.rerun()

    return presets[preset_atual], max_d


# =============================================================================
# Render de UM gráfico (chamado 4× — uma vez por submercado)
# =============================================================================

def _render_grafico_submercado(df_mes: pd.DataFrame, submercado: str) -> None:
    """Título Bauhaus + grouped bar com 3 fontes pra UM submercado."""
    if df_mes.empty:
        return

    df_mes = df_mes.sort_values("ano_mes").copy()

    # --- Título Bauhaus (padrão tab_curtailment.py:636) ---
    periodo_min = _fmt_mes_aa(df_mes["ano_mes"].min())
    periodo_max = _fmt_mes_aa(df_mes["ano_mes"].max())
    periodo_str = (
        periodo_min if periodo_min == periodo_max
        else f"{periodo_min} a {periodo_max}"
    )

    st.markdown(
        f'<div style="display:flex; justify-content:space-between; '
        f'align-items:baseline; '
        f"font-family:'Bebas Neue', sans-serif; "
        f'font-size:1.1rem; letter-spacing:0.08em; color:{BAUHAUS_BLACK}; '
        f'margin: 2.6rem 0 0.3rem 0; padding-bottom:3px; '
        f'border-bottom: 2px solid {BAUHAUS_BLACK};">'
        f'<span>SPREAD DE CAPTURA · {submercado}</span>'
        f'<span>{periodo_str}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # --- Subtítulo Inter (padrão decisão 5.22) ---
    st.markdown(
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.9rem; color:{BAUHAUS_BLACK}; font-weight:500; '
        f'letter-spacing:0.04em; margin:0 0 0.5rem 0;">'
        f'Mensal · PLD ponderado pela geração − PLD flat (R$/MWh)'
        f'</div>',
        unsafe_allow_html=True,
    )

    # X labels pré-formatados (categorial — preserva ordem cronológica).
    df_mes["x_label"] = df_mes["ano_mes"].apply(_fmt_mes_aa)

    fig = go.Figure()
    for fonte in FONTES_ALVO:
        sub = df_mes[df_mes["fonte"] == fonte]
        if sub.empty:
            continue
        cor = CORES_FONTE_MOD[fonte]
        label = LABELS_FONTE_MOD[fonte]
        label_fix = label.ljust(12).replace(" ", "&nbsp;")

        # Hover: customdata com decimal BR (foolproof vs depender de separators).
        customdata = np.array([
            f"R$ {v:.2f}/MWh".replace(".", ",") if pd.notna(v) else "—"
            for v in sub["spread_rs_mwh"]
        ])

        fig.add_trace(go.Bar(
            x=sub["x_label"],
            y=sub["spread_rs_mwh"],
            name=label,
            marker=dict(color=cor),
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
        separators=",.",   # Decimal BR no eixo Y (vírgula = decimal, ponto = milhar)
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
    """Renderiza a aba Modulação completa: 4 gráficos empilhados (SE/S/NE/N)."""
    # Título h1 (mesmo padrão das outras abas: app.py:2192, 2785, 3741)
    st.markdown("# MODULAÇÃO")

    # Caption explicativa (Inter italic cinza)
    st.markdown(
        '<div style="font-family:\'Inter\', sans-serif; '
        'font-size:0.85rem; color:#6B6B6B; font-style:italic; '
        'margin:0 0 0.8rem 0;">'
        'Spread de captura (R$/MWh) = PLD médio ponderado pela geração mensal '
        '<strong>menos</strong> PLD médio flat. Positivo = fonte gera mais nas '
        'horas caras. Negativo = gera mais nas horas baratas.'
        '</div>',
        unsafe_allow_html=True,
    )

    df_spread = _calcular_spread_mensal()
    if df_spread.empty:
        st.warning("Sem dados de spread disponíveis no momento.")
        return

    data_ini, data_fim = _render_period_controls_mod(df_spread)
    df_filtrado = df_spread[
        (df_spread["ano_mes"] >= data_ini)
        & (df_spread["ano_mes"] <= data_fim)
    ]
    if df_filtrado.empty:
        st.warning("Sem dados no período selecionado.")
        return

    for sub in ORDEM_SUBMERCADOS:
        df_sub = df_filtrado[df_filtrado["submercado"] == sub]
        if df_sub.empty:
            continue
        _render_grafico_submercado(df_sub, sub)
