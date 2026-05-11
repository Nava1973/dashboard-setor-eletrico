"""
tab_geracao_grupo.py
====================

Sub-aba "Eólica/Solar por Grupo" da aba Geração.

Mostra geração verificada (MWm ou GWh) por grupo econômico, decomposta
em Eólica + Solar como colunas agrupadas (barmode="group").

Caminho A (decisão 5.37): reusa o df pós-rateio da Curtailment
(coluna OUTPUT_MWH) em vez de carregar geracao-usina-2 standalone.
Mesmas usinas (Tipo I, II-B, II-C) — universo coincide com o Excel.

Estrutura:
- Granularidades: Diária / Mensal / Trimestral
- Presets: 30D/90D/6M/12M/Máx (Diária), 1M/3M/6M/12M/Máx (Mensal),
           6M/12M/24M/Máx (Trimestral)
- Janela ampla compartilhada com Curtailment via curt_janela_modo
  (state em st.session_state, mesmo cache disco)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, List, Optional, Tuple

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from data_loaders.data_loader_curtailment import (
    descobrir_ultimo_dia_disponivel,
)
from data_loaders.data_loader_grupos_excel import (
    carregar_grupos_excel, carregar_aliases,
)
from utils.utils_periodos import adicionar_chave_periodo
from utils.utils_curtailment import (
    _inicio_trimestre_anterior, _inicio_mes_anterior,
)

# Reuso da Curtailment pra compartilhar cache de janela ampla + modal
# de expansão. NÃO duplicar essas funções — a Curtailment está estável,
# qualquer divergência (TTL, chave de cache, struct do modal) quebra o
# compartilhamento do cache disco entre as 2 abas.
from components.tab_curtailment import (
    _carregar_curtailment_janela_ampla,
    _aplicar_rateio_cached,
    _confirmar_expansao_curt,
    _data_ini_ampla_efetiva,
)


# =============================================================================
# Paleta Bauhaus (duplicada de app.py — manter sincronizada).
# Cores canônicas de fontes de geração via decisão 5.33.
# =============================================================================

BAUHAUS_RED    = "#D62828"
BAUHAUS_YELLOW = "#F6BD16"
BAUHAUS_BLUE   = "#2A6F97"
BAUHAUS_BLACK  = "#1A1A1A"
BAUHAUS_CREAM  = "#F5F1E8"
BAUHAUS_GRAY   = "#4A4A4A"
BAUHAUS_LIGHT  = "#E8E3D4"

COR_FONTE_SOLAR  = "#F6BD16"
COR_FONTE_EOLICA = "#8FA31E"


# =============================================================================
# Granularidades e presets.
# Duplicação intencional com tab_curtailment.GRANS_UI / PRESETS_BY_GRAN —
# manter sincronizado manualmente até refactor futuro pra
# utils/_period_controls.py compartilhado (separação > DRY nessa fase).
# =============================================================================

GRANS_UI = {
    "Diária":     "DIARIO",
    "Mensal":     "MENSAL",
    "Trimestral": "TRIMESTRAL",
}

PRESETS_BY_GRAN = {
    "DIARIO": {
        "default": "30D",
        "presets": [
            ("30D", lambda mx: mx - timedelta(days=30),  False),
            ("90D", lambda mx: mx - timedelta(days=90),  False),
            ("6M",  lambda mx: mx - timedelta(days=180), False),
            ("12M", lambda mx: mx - timedelta(days=365), False),
            ("Máx", None, True),
        ],
    },
    "MENSAL": {
        "default": "12M",
        "presets": [
            ("1M",  lambda mx: _inicio_mes_anterior(mx, 0),  False),
            ("3M",  lambda mx: _inicio_mes_anterior(mx, 2),  False),
            ("6M",  lambda mx: _inicio_mes_anterior(mx, 5),  False),
            ("12M", lambda mx: _inicio_mes_anterior(mx, 11), False),
            ("Máx", None, True),
        ],
    },
    "TRIMESTRAL": {
        "default": "12M",
        "presets": [
            ("6M",  lambda mx: _inicio_trimestre_anterior(mx, 1), False),
            ("12M", lambda mx: _inicio_trimestre_anterior(mx, 3), False),
            ("24M", lambda mx: _inicio_trimestre_anterior(mx, 7), False),
            ("Máx", None, True),
        ],
    },
}


_GRUPOS_PRIORIZADOS = (
    "Alupar", "Auren", "Copel", "CPFL",
    "Engie", "Eneva", "Equatorial", "Neoenergia",
)


# =============================================================================
# Selectbox de grupos (Caminho 3 da Curtailment, simplificado):
# - SEM "Brasil (SIN)" (escopo da sub-aba é POR GRUPO, não agregado)
# - SEM unidades individuais
# - Priorizados primeiro, restante alfabético
# =============================================================================


@st.cache_data(show_spinner=False)
def _construir_opcoes_grupos() -> list:
    df_g = carregar_grupos_excel()
    if len(df_g) == 0:
        return []
    todos_grupos = sorted(df_g["PROPRIETARIO"].dropna().unique())
    # Excluir o balde "Other (sem mapeamento)" / "Other" — não é um grupo
    # econômico real, é o sumidouro de usinas sem cadastro.
    todos_grupos = [
        g for g in todos_grupos
        if not str(g).strip().lower().startswith("other")
    ]
    prio = [g for g in _GRUPOS_PRIORIZADOS if g in todos_grupos]
    restante = sorted(g for g in todos_grupos if g not in prio)
    return prio + restante


# =============================================================================
# Period controls forked do tab_curtailment._render_period_controls_curt.
# Diferenças:
# - Labels "MWm"/"GWh" no toggle (vs "%"/"GWh" da Curtailment)
# - Estado "mwm"/"gwh" (vs "pct"/"gwh")
# Resto idêntico: presets ativo amarelo (type="primary"), expansão sob
# demanda via callback, clamp em min_d, layout cols.
# =============================================================================


def _render_period_controls_gen(
    *,
    presets: List[Tuple[str, Optional[Callable[[date], date]], bool]],
    session_key_ini: str,
    session_key_fim: str,
    key_prefix: str,
    min_d: date,
    max_d: date,
    cache_data_ini_atual: Optional[date] = None,
    hard_min: Optional[date] = None,
    on_expansion_request: Optional[Callable[[str], None]] = None,
    unit_toggle_key: Optional[str] = None,
):
    """N botões de preset + toggle MWm/GWh + 2 date_inputs em 1 linha."""
    data_ini_atual = st.session_state[session_key_ini]
    data_fim_atual = st.session_state[session_key_fim]

    # Detecta preset ativo: data_fim ancorada em max_d e data_ini bate com
    # data_ini_target (pós-clamp).
    preset_atual = None
    if data_fim_atual == max_d:
        for label, data_ini_fn, is_max in presets:
            if is_max:
                if data_ini_atual == min_d:
                    preset_atual = label
                    break
            else:
                data_ini_target = max(min_d, data_ini_fn(max_d))
                if data_ini_atual == data_ini_target:
                    preset_atual = label
                    break

    n = len(presets)
    if unit_toggle_key is not None:
        if unit_toggle_key not in st.session_state:
            st.session_state[unit_toggle_key] = "mwm"
        # Layout: presets + spacer + MWm + GWh + spacer + 2 date_inputs.
        # Toggle 0.9/0.9 (vs 0.7/0.7 da Curtailment): "MWm" + setinha do
        # button precisam de mais largura que "%" da Curtailment, senão
        # quebram em 2 linhas em viewport ~100%.
        cols = st.columns(
            [1] * n + [0.3, 0.9, 0.9, 0.3, 1.4, 1.4]
        )
        idx_data_ini = n + 4
        idx_data_fim = n + 5
    else:
        cols = st.columns([1] * n + [0.3, 1.4, 1.4])
        idx_data_ini = n + 1
        idx_data_fim = n + 2

    for i, (label, data_ini_fn, is_max) in enumerate(presets):
        with cols[i]:
            tipo = "primary" if label == preset_atual else "secondary"

            _floor = hard_min if hard_min is not None else min_d
            if is_max:
                target_real = _floor
            else:
                target_real = data_ini_fn(max_d)

            cache_cobre = (
                cache_data_ini_atual is None
                or target_real >= cache_data_ini_atual
            )

            if label == "24M":
                help_text = (
                    "24 meses (em cache)" if cache_cobre
                    else "24 meses (~3 min na 1ª vez)"
                )
            elif is_max:
                help_text = (
                    f"Máximo — desde {_floor.strftime('%d/%m/%Y')}"
                    if cache_cobre
                    else "Histórico completo (~5-7 min na 1ª vez)"
                )
            else:
                help_text = None

            if st.button(
                label, use_container_width=True,
                key=f"{key_prefix}{label}", type=tipo, help=help_text,
            ):
                if (
                    not cache_cobre
                    and on_expansion_request is not None
                ):
                    on_expansion_request(label)
                    return

                # Clamp em min_d como defesa em profundidade (decisão 5.27)
                st.session_state[session_key_ini] = max(min_d, target_real)
                st.session_state[session_key_fim] = max_d
                st.rerun()

    if unit_toggle_key is not None:
        unidade_atual = st.session_state[unit_toggle_key]
        with cols[n + 1]:
            if st.button(
                "MWm", use_container_width=True,
                key=f"{key_prefix}unit_mwm",
                type="primary" if unidade_atual == "mwm" else "secondary",
                help="Mostrar gráfico em MWm (potência média)",
            ):
                st.session_state[unit_toggle_key] = "mwm"
                st.rerun()
        with cols[n + 2]:
            if st.button(
                "GWh", use_container_width=True,
                key=f"{key_prefix}unit_gwh",
                type="primary" if unidade_atual == "gwh" else "secondary",
                help="Mostrar gráfico em GWh (energia)",
            ):
                st.session_state[unit_toggle_key] = "gwh"
                st.rerun()

    with cols[idx_data_ini]:
        st.date_input(
            "Data inicial", min_value=min_d, max_value=max_d,
            key=session_key_ini,
            format="DD/MM/YYYY",
        )
    with cols[idx_data_fim]:
        st.date_input(
            "Data final", min_value=min_d, max_value=max_d,
            key=session_key_fim,
            format="DD/MM/YYYY",
        )


# =============================================================================
# Agregação por grupo
#
# Recebe df_rateado_amplo (concat Eólica+Solar pós-rateio), filtra pelo
# grupo + janela de datas, aplica adicionar_chave_periodo e pivota
# Eólica/Solar como colunas.
#
# Output: DataFrame com colunas
#   PERIODO_LABEL | PERIODO_INICIO | PERIODO_FIM | EOLICA_MWH | SOLAR_MWH
#
# Cache 6h (alinhado com upstream). Args escalares + 1 df com underscore.
# =============================================================================


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def _agregar_geracao_por_grupo(
    data_ini: date,
    data_fim: date,
    granularidade: str,
    grupo: str,
    _df_rateado_amplo: pd.DataFrame,
) -> pd.DataFrame:
    df = _df_rateado_amplo
    if df is None or len(df) == 0:
        return pd.DataFrame(
            columns=[
                "PERIODO_LABEL", "PERIODO_INICIO", "PERIODO_FIM",
                "EOLICA_MWH", "SOLAR_MWH",
            ]
        )

    # df["DATA"] vem como dtype object (valores datetime.date), NÃO
    # datetime64 — Curtailment preserva esse dtype upstream. Comparar
    # date >= date funciona; pd.Timestamp(date) >= date levanta TypeError.
    mask = (
        (df["DATA"] >= data_ini)
        & (df["DATA"] <= data_fim)
        & (df["PROPRIETARIO"] == grupo)
    )
    df_f = df.loc[mask, ["DATA", "FONTE", "OUTPUT_MWH"]]
    if len(df_f) == 0:
        return pd.DataFrame(
            columns=[
                "PERIODO_LABEL", "PERIODO_INICIO", "PERIODO_FIM",
                "EOLICA_MWH", "SOLAR_MWH",
            ]
        )

    df_p = adicionar_chave_periodo(df_f, granularidade)

    grouped = (
        df_p.groupby(
            ["PERIODO_CHAVE", "PERIODO_LABEL", "PERIODO_INICIO",
             "PERIODO_FIM", "FONTE"],
            observed=True,
        )["OUTPUT_MWH"]
        .sum()
        .reset_index()
    )

    pivot = grouped.pivot_table(
        index=["PERIODO_CHAVE", "PERIODO_LABEL", "PERIODO_INICIO",
               "PERIODO_FIM"],
        columns="FONTE",
        values="OUTPUT_MWH",
        aggfunc="sum",
        fill_value=0.0,
    ).reset_index()

    # Garante colunas EOLICA / SOLAR mesmo se grupo só tem 1 fonte
    if "EOLICA" not in pivot.columns:
        pivot["EOLICA"] = 0.0
    if "SOLAR" not in pivot.columns:
        pivot["SOLAR"] = 0.0

    pivot = pivot.rename(
        columns={"EOLICA": "EOLICA_MWH", "SOLAR": "SOLAR_MWH"}
    )
    pivot = pivot.sort_values("PERIODO_INICIO").reset_index(drop=True)

    return pivot[
        ["PERIODO_LABEL", "PERIODO_INICIO", "PERIODO_FIM",
         "EOLICA_MWH", "SOLAR_MWH"]
    ]


# =============================================================================
# Render do gráfico (colunas agrupadas)
# =============================================================================


def _render_grafico_grupo(
    df_agg: pd.DataFrame,
    grupo_label: str,
    unidade_modo: str,                  # "mwm" ou "gwh"
    granularidade_ui: str,              # "Diária" / "Mensal" / "Trimestral"
    granularidade_slug: str,            # "diario" / "mensal" / "trimestral"
    data_ini: date,
    data_fim: date,
):
    if len(df_agg) == 0:
        st.warning(
            f"O grupo {grupo_label} não tem geração registrada nesse período."
        )
        return

    # ------------------------------------------------------------------
    # Conversão MWh -> MWm/GWh por período.
    # HORAS_PERIODO = ((PERIODO_FIM - PERIODO_INICIO).days + 1) * 24
    # MWm = MWh / HORAS_PERIODO
    # GWh = MWh / 1000
    #
    # ATENÇÃO ao MWm em períodos parciais (ex: trimestre corrente):
    # PERIODO_FIM vem como último dia do bucket completo (30/jun pra T2),
    # NÃO como min(data_fim, último dia do bucket). Resultado: MWm do
    # trimestre/mês corrente fica diluído por horas que ainda não
    # passaram, aparecendo artificialmente baixo. Comportamento idêntico
    # ao da Curtailment com toggle GWh. Aceitável — usuário vê a tag
    # de granularidade no título e entende o contexto. Se virar dor
    # no futuro, trocar pra MIN(PERIODO_FIM, data_fim) aqui.
    # ------------------------------------------------------------------
    df = df_agg.copy()
    horas = (
        (
            pd.to_datetime(df["PERIODO_FIM"])
            - pd.to_datetime(df["PERIODO_INICIO"])
        ).dt.days + 1
    ) * 24

    if unidade_modo == "gwh":
        df["EOLICA_Y"] = df["EOLICA_MWH"] / 1000.0
        df["SOLAR_Y"]  = df["SOLAR_MWH"] / 1000.0
        unidade_label = "GWh"
        y_fmt = "%{y:,.2f} GWh"
        ticksuffix = " GWh"
        tickformat = ",.0f"
    else:
        df["EOLICA_Y"] = df["EOLICA_MWH"] / horas
        df["SOLAR_Y"]  = df["SOLAR_MWH"] / horas
        unidade_label = "MWm"
        y_fmt = "%{y:,.1f} MWm"
        ticksuffix = " MWm"
        tickformat = ",.0f"

    df["TOTAL_Y"] = df["EOLICA_Y"] + df["SOLAR_Y"]

    # ------------------------------------------------------------------
    # Título Bauhaus (2 linhas) + período à direita.
    # ------------------------------------------------------------------
    periodo_str = (
        f"{data_ini.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}"
    )
    st.markdown(
        f'<div style="display:flex; justify-content:space-between; '
        f'align-items:baseline; '
        f"font-family:'Bebas Neue', sans-serif; "
        f'font-size:1.1rem; letter-spacing:0.08em; color:#1A1A1A; '
        f'margin: 2.6rem 0 0.3rem 0; padding-bottom:3px; '
        f'border-bottom: 2px solid #1A1A1A;">'
        f'<span>GERAÇÃO EÓLICA/SOLAR · {grupo_label.upper()}</span>'
        f'<span>{periodo_str}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.9rem; color:#1A1A1A; font-weight:500; '
        f'letter-spacing:0.04em; margin:0 0 0.5rem 0;">'
        f'{granularidade_ui} · {unidade_label}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ------------------------------------------------------------------
    # Gráfico: colunas agrupadas (barmode="group")
    # ------------------------------------------------------------------
    fig = go.Figure()

    # Padded labels pra alinhamento monospace no hover unified.
    # "Eólica" tem 6 chars, "Solar" 5 — ljust(8) alinha os 2 com
    # 2-3 espaços de respiro à direita. "Total (E+S)" tem 11 chars,
    # precisa ljust(12) próprio pra preservar alinhamento.
    label_eol_fix   = "Eólica".ljust(8).replace(" ", "&nbsp;")
    label_sol_fix   = "Solar".ljust(8).replace(" ", "&nbsp;")
    label_total_fix = "Total (E+S)".ljust(12).replace(" ", "&nbsp;")

    fig.add_trace(go.Bar(
        x=df["PERIODO_LABEL"],
        y=df["EOLICA_Y"],
        name="Eólica",
        marker=dict(color=COR_FONTE_EOLICA),
        hovertemplate=(
            f'<span style="color:{COR_FONTE_EOLICA}; font-weight:700;">'
            f'{label_eol_fix}</span>&nbsp;&nbsp;'
            f'<span style="color:#1A1A1A;">{y_fmt}</span>'
            '<extra></extra>'
        ),
    ))
    fig.add_trace(go.Bar(
        x=df["PERIODO_LABEL"],
        y=df["SOLAR_Y"],
        name="Solar",
        marker=dict(color=COR_FONTE_SOLAR),
        hovertemplate=(
            f'<span style="color:{COR_FONTE_SOLAR}; font-weight:700;">'
            f'{label_sol_fix}</span>&nbsp;&nbsp;'
            f'<span style="color:#1A1A1A;">{y_fmt}</span>'
            '<extra></extra>'
        ),
    ))
    # Trace invisível Total — adiciona 3ª linha no hover unified
    fig.add_trace(go.Scatter(
        x=df["PERIODO_LABEL"],
        y=df["TOTAL_Y"],
        mode="markers",
        marker=dict(size=0, opacity=0),
        showlegend=False,
        hovertemplate=(
            '<span style="color:#1A1A1A; font-weight:700;">'
            f'{label_total_fix}</span>&nbsp;&nbsp;'
            f'<span style="color:#1A1A1A;">{y_fmt}</span>'
            '<extra></extra>'
        ),
    ))

    fig.update_layout(
        barmode="stack",
        height=450,
        margin=dict(l=20, r=20, t=40, b=20),
        paper_bgcolor=BAUHAUS_CREAM,
        plot_bgcolor=BAUHAUS_CREAM,
        separators=",.",
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
            traceorder="normal",
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
                size=13, color=BAUHAUS_BLACK,
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
                size=13, color=BAUHAUS_BLACK,
            ),
            zeroline=False,
            ticksuffix=ticksuffix,
            tickformat=tickformat,
        ),
        font=dict(family="Inter, sans-serif", size=12),
    )

    st.plotly_chart(
        fig, use_container_width=True, config={"displaylogo": False},
    )

    # ------------------------------------------------------------------
    # Caption explicativa pós-gráfico (Inter italic cinza).
    # Posição abaixo do gráfico é deliberada: contexto da fonte de
    # dados é mais útil ao leitor APÓS ver os números do que antes.
    # Margens: 1.2rem acima (respira do gráfico) / 0.8rem abaixo (cola
    # mais perto do bloco de download).
    # ------------------------------------------------------------------
    st.markdown(
        '<div style="font-family:\'Inter\', sans-serif; '
        'font-size:0.85rem; color:#6B6B6B; font-style:italic; '
        'margin: 1.2rem 0 0.8rem 0;">'
        'Geração eólica e solar verificada por grupo econômico. '
        'Cobertura: usinas Tipo I, II-B e II-C apuradas no '
        'constrained-off (não inclui Tipo III nem geração SMF/CCEE '
        'de referência). Pode divergir de releases corporativos que '
        'usam Sistema de Medição para Faturamento. Dados ONS via '
        'base de constrained-off.'
        '</div>',
        unsafe_allow_html=True,
    )

    # ------------------------------------------------------------------
    # Download CSV
    # ------------------------------------------------------------------
    df_export = df[
        ["PERIODO_LABEL", "PERIODO_INICIO", "PERIODO_FIM",
         "EOLICA_MWH", "SOLAR_MWH", "EOLICA_Y", "SOLAR_Y", "TOTAL_Y"]
    ].copy()
    df_export = df_export.rename(columns={
        "PERIODO_LABEL":  "Período",
        "PERIODO_INICIO": "Início",
        "PERIODO_FIM":    "Fim",
        "EOLICA_MWH":     "Eólica (MWh)",
        "SOLAR_MWH":      "Solar (MWh)",
        "EOLICA_Y":       f"Eólica ({unidade_label})",
        "SOLAR_Y":        f"Solar ({unidade_label})",
        "TOTAL_Y":        f"Total ({unidade_label})",
    })
    csv = df_export.to_csv(
        index=False, sep=";", decimal=",",
    ).encode("utf-8-sig")

    grupo_slug = (
        grupo_label.lower()
        .replace(" ", "_")
        .replace("ó", "o").replace("á", "a").replace("é", "e")
        .replace("í", "i").replace("ú", "u").replace("ã", "a")
        .replace("õ", "o").replace("ç", "c")
    )
    filename = (
        f"geracao_grupo_{grupo_slug}_{granularidade_slug}_"
        f"{data_ini.strftime('%Y%m%d')}_{data_fim.strftime('%Y%m%d')}.csv"
    )

    col_dl_l, col_dl_r = st.columns([3, 1])
    with col_dl_r:
        st.download_button(
            "Baixar CSV",
            data=csv,
            file_name=filename,
            mime="text/csv",
            use_container_width=True,
        )


# =============================================================================
# Função principal — wrapper defensivo + impl
# =============================================================================


def render_aba_geracao_grupo() -> None:
    """Wrapper defensivo. Captura crash e exibe stack trace na tela em vez
    de propagar pra Streamlit (que mostraria 'Oh no' no lugar)."""
    try:
        _render_aba_geracao_grupo_impl()
    except Exception:
        import traceback
        st.error("⚠️ Erro ao carregar sub-aba Geração por Grupo (debug ativo)")
        st.code(traceback.format_exc(), language="python")
        st.caption(
            "Este erro foi capturado para investigação. "
            "Por favor, copie o stack trace acima e reporte."
        )


def _render_aba_geracao_grupo_impl() -> None:
    # Título h1 + linha separadora Bauhaus
    st.markdown("# GERAÇÃO POR GRUPO")
    st.markdown(
        '<div style="border-bottom: 2px solid #1A1A1A; '
        'margin: 0 0 -1.5rem 0;"></div>',
        unsafe_allow_html=True,
    )

    # ------------------------------------------------------------------
    # Mapeamento de proprietários (Excel + aliases) — ~1s
    # ------------------------------------------------------------------
    with st.spinner("Carregando mapeamento de proprietários..."):
        df_grupos = carregar_grupos_excel()
        aliases = carregar_aliases()

    opcoes_grupos = _construir_opcoes_grupos()
    if len(opcoes_grupos) == 0:
        st.warning(
            "Excel de proprietários vazio — sub-aba indisponível."
        )
        return

    # ------------------------------------------------------------------
    # Descobrir último dia disponível (ancora max_d)
    # ------------------------------------------------------------------
    with st.spinner("Verificando última data disponível no ONS..."):
        try:
            ultimo_dia = descobrir_ultimo_dia_disponivel("eolica")
        except Exception:
            ultimo_dia = None
        if ultimo_dia is None:
            ultimo_dia = date.today()

    min_d_hard = date(2022, 1, 1)
    max_d = ultimo_dia

    # ------------------------------------------------------------------
    # Controles em 1 linha: [Grupo] [Granularidade] (ajuste A do plano —
    # Grupo à esquerda porque é a variável trocada com mais frequência).
    # Proporções [0.8, 0.7, 1.5]: Grupo um pouco mais largo (strings
    # "Equatorial"/"Neoenergia" são longas), spacer à direita.
    # ------------------------------------------------------------------
    ctrl_cols = st.columns([0.8, 0.7, 1.5])
    with ctrl_cols[0]:
        # Reset defensivo (decisão 5.12): se grupo selecionado não está
        # mais nas opções (Excel mudou), volta pra opcoes_grupos[0].
        atual_grupo = st.session_state.get(
            "geracao_grupo_selecionado", opcoes_grupos[0]
        )
        if atual_grupo not in opcoes_grupos:
            st.session_state["geracao_grupo_selecionado"] = opcoes_grupos[0]
        grupo_selecionado = st.selectbox(
            "Grupo",
            opcoes_grupos,
            key="geracao_grupo_selecionado",
        )
    with ctrl_cols[1]:
        granularidade_ui = st.selectbox(
            "Granularidade",
            list(GRANS_UI.keys()),
            index=1,  # default Mensal
            key="geracao_grupo_granularidade",
        )
    granularidade = GRANS_UI[granularidade_ui]

    # Spacer: CSS global de app.py:353 aplica margin-top:-1.5rem em
    # .stDateInput. Sem este spacer, labels dos date_inputs sobrepõem
    # os selectboxes acima. NÃO REMOVER sem testar visualmente.
    st.markdown(
        '<div style="height:1.5rem"></div>', unsafe_allow_html=True,
    )

    # ------------------------------------------------------------------
    # Reset de janela ao trocar granularidade
    # ------------------------------------------------------------------
    prev_gran = st.session_state.get("geracao_grupo_gran_anterior")
    trocou_gran = prev_gran is not None and prev_gran != granularidade

    def _aplicar_default_periodo(gran_key, mn, mx):
        cfg = PRESETS_BY_GRAN[gran_key]
        default_label = cfg["default"]
        for label, data_ini_fn, is_max in cfg["presets"]:
            if label == default_label:
                if is_max:
                    st.session_state["geracao_grupo_data_ini"] = mn
                else:
                    st.session_state["geracao_grupo_data_ini"] = max(
                        mn, data_ini_fn(mx)
                    )
                st.session_state["geracao_grupo_data_fim"] = mx
                return

    # Janela ampla compartilhada com Curtailment via curt_janela_modo.
    # Key prefix "curt_" é intencional — expansão numa sub-aba propaga
    # pra outra automaticamente (mesmo cache disco, baixar 24M na Curt
    # disponibiliza pra Geração-Grupo sem novo download). NÃO renomear
    # pra "gen_grupo_janela_modo" sem migrar o cache.
    modo_janela_atual = st.session_state.get("curt_janela_modo", "default")
    data_ini_ampla_ui = _data_ini_ampla_efetiva(max_d, modo_janela_atual)

    if "geracao_grupo_data_ini" not in st.session_state or trocou_gran:
        _aplicar_default_periodo(granularidade, data_ini_ampla_ui, max_d)
    if "geracao_grupo_data_fim" not in st.session_state:
        st.session_state["geracao_grupo_data_fim"] = max_d
    st.session_state["geracao_grupo_gran_anterior"] = granularidade

    def _on_expansion_request(label: str):
        # Reusa _curt_pending_modal pra compartilhar o modal de
        # confirmação com a Curtailment (mesma key intencional).
        if label == "24M":
            st.session_state["_curt_pending_modal"] = "24m"
        else:
            st.session_state["_curt_pending_modal"] = "max"
        st.rerun()

    _render_period_controls_gen(
        presets=PRESETS_BY_GRAN[granularidade]["presets"],
        session_key_ini="geracao_grupo_data_ini",
        session_key_fim="geracao_grupo_data_fim",
        key_prefix="btn_gen_grupo_",
        min_d=data_ini_ampla_ui,
        max_d=max_d,
        cache_data_ini_atual=data_ini_ampla_ui,
        hard_min=min_d_hard,
        on_expansion_request=_on_expansion_request,
        unit_toggle_key="geracao_grupo_unidade",
    )

    # Modal de expansão (reusa o da Curtailment — decisão 5.12)
    modo_pendente = st.session_state.pop("_curt_pending_modal", None)
    if modo_pendente:
        _confirmar_expansao_curt(modo_pendente)

    data_ini = st.session_state["geracao_grupo_data_ini"]
    data_fim = st.session_state["geracao_grupo_data_fim"]
    if data_ini > data_fim:
        st.error("Data inicial maior que data final.")
        st.stop()

    unidade_modo = st.session_state.get("geracao_grupo_unidade", "mwm")

    # ------------------------------------------------------------------
    # Carregar janela ampla compartilhada (cache hit se Curtailment já
    # carregou na sessão).
    # ------------------------------------------------------------------
    modo_janela = st.session_state.get("curt_janela_modo", "default")
    data_ini_ampla = _data_ini_ampla_efetiva(max_d, modo_janela)

    ja_carregou_curt = st.session_state.get("_curt_ja_carregou", False)

    if not ja_carregou_curt:
        with st.spinner(
            "Carregando 15 meses de dados ONS — primeira carga da sessão "
            "(pode levar 40-60s)..."
        ):
            df_curt_raw_amplo = _carregar_curtailment_janela_ampla(
                data_ini_ampla=data_ini_ampla,
                data_fim_ampla=max_d,
                fontes=("eolica", "solar"),
            )
    else:
        df_curt_raw_amplo = _carregar_curtailment_janela_ampla(
            data_ini_ampla=data_ini_ampla,
            data_fim_ampla=max_d,
            fontes=("eolica", "solar"),
        )

    if df_curt_raw_amplo is None or len(df_curt_raw_amplo) == 0:
        st.error(
            "Não foi possível carregar dados para esta janela. "
            "Tente outro período ou verifique a conexão com o ONS."
        )
        return

    st.session_state["_curt_ja_carregou"] = True

    # ------------------------------------------------------------------
    # Aplicar rateio nas 2 fontes + concat
    # _aplicar_rateio_cached é cacheado por (janela, fonte), então as
    # 2 chamadas têm entries próprias no cache — trocar de grupo é
    # cache hit em ambas.
    # ------------------------------------------------------------------
    df_eol = _aplicar_rateio_cached(
        data_ini_ampla, max_d, "Eólica",
        df_curt_raw_amplo, df_grupos, aliases,
    )
    df_sol = _aplicar_rateio_cached(
        data_ini_ampla, max_d, "Solar",
        df_curt_raw_amplo, df_grupos, aliases,
    )
    df_rateado_amplo = pd.concat([df_eol, df_sol], ignore_index=True)

    # ------------------------------------------------------------------
    # Agregar pelo grupo selecionado + render
    # ------------------------------------------------------------------
    df_agg = _agregar_geracao_por_grupo(
        data_ini, data_fim, granularidade, grupo_selecionado,
        df_rateado_amplo,
    )

    _render_grafico_grupo(
        df_agg,
        grupo_label=grupo_selecionado,
        unidade_modo=unidade_modo,
        granularidade_ui=granularidade_ui,
        granularidade_slug=granularidade.lower(),  # diario/mensal/trimestral
        data_ini=data_ini,
        data_fim=data_fim,
    )
