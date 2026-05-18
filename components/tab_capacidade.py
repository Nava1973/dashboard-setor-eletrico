"""
tab_capacidade.py
=================

Aba CAPACIDADE INSTALADA do dashboard — visão ANUAL.

Mostra evolução anual da capacidade instalada do Brasil em GW, decomposta
por fonte (6 categorias empilhadas):
- Hidro, Térmica, Nuclear, Eólica, Solar — SIGA centralizado (ANEEL)
- MMGD — anchor points anuais EPE PDGD (a partir de dez/2022)

Decisões arquiteturais (Sub-sessão A da branch ``feat/capacidade-instalada``)
----------------------------------------------------------------------------
- Granularidade ANUAL. Dataset MMGD ANEEL não suporta série mensal sem
  reconstrução viesada (campo ``DataConexao`` removido na migração
  SISGD→MMGD set/2025).
- MMGD pré-2022: marcado como NaN (Plotly omite do hover unified;
  reflete ausência real do regime regulatório pré-Lei 14.300/2022).
- Janela default: últimos 10 anos (controles: 2 ``date_input``, sem botões).
- Filtro por ANO (date_input só delimita janela de anos visíveis).

Fontes
------
- ``data_loaders.data_loader_aneel_siga.load_siga_anual()`` —
  DataFrame anual dez/AAAA + linha parcial do ano corrente (``IS_PARTIAL``).
- ``data_loaders.data_loader_aneel_mmgd.load_mmgd_anual()`` —
  Series com 4 anchor points (dez/2022 a dez/2025).

Visualização
------------
- Stacked bars anuais (6 categorias) com último x= parcial em opacidade 0.7.
- Eixo X categórico ("2014", "2015", ..., "2025", "2026 abr").
- Hover JetBrains Mono "x unified".
- Tabela Bauhaus (``.bauhaus-table``) — últimos 10 anos em ordem decrescente.
- CSV anual com 6 fontes + TOTAL, separador ; decimal , (formato BR).
"""

from __future__ import annotations

import traceback
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_loaders.data_loader_aneel_siga import load_siga_anual
from data_loaders.data_loader_aneel_mmgd_sql import (
    load_mmgd_anual,
    load_mmgd_mensal,
)
from utils.cores_fontes import (
    COR_FONTE_HIDRO,
    COR_FONTE_TERMICA,
    COR_FONTE_NUCLEAR,
    COR_FONTE_EOLICA,
    COR_FONTE_SOLAR,
    COR_FONTE_MMGD,
)


# =============================================================================
# Paleta estrutural — migração 2026-05-15 (Bauhaus → Bradesco).
# Single source of truth em utils/paleta_bradesco.py.
# =============================================================================

from utils.paleta_bradesco import (
    COR_FUNDO,
    COR_TEXTO,
    COR_TEXTO_SECUND,
    COR_GRID,
)

# Compat aliases — migração 2026-05-15. TODO: rename to COR_* nos consumidores.
# NOTA: BAUHAUS_GRAY aqui = COR_TEXTO_SECUND (#6B6B6B), diferente dos outros
# módulos onde mapeia pra COR_SIN (#4A4A4A) — preserva o tom original do
# arquivo (divergência §5.33 do CLAUDE.md, padronizada nesta migração).
BAUHAUS_BLACK = COR_TEXTO          # era #1A1A1A → #313131
BAUHAUS_CREAM = COR_FUNDO          # era #F5F1E8 → #FFFFFF
BAUHAUS_LIGHT = COR_GRID           # era #E8E3D4 → #E0E0E0
BAUHAUS_GRAY  = COR_TEXTO_SECUND   # era #6B6B6B (preservado, fix da divergência)

# Configuração das fontes plotadas. Ordem importa pro empilhamento:
# 1ª trace adicionada fica na base do stack (Hidro embaixo, MMGD em cima).
_FONTES_CONFIG = [
    ("CAP_HIDRO_MW",   "Hidro",   COR_FONTE_HIDRO),
    ("CAP_TERMICA_MW", "Térmica", COR_FONTE_TERMICA),
    ("CAP_NUCLEAR_MW", "Nuclear", COR_FONTE_NUCLEAR),
    ("CAP_EOLICA_MW",  "Eólica",  COR_FONTE_EOLICA),
    ("CAP_SOLAR_MW",   "Solar",   COR_FONTE_SOLAR),
    ("CAP_MMGD_MW",    "MMGD",    COR_FONTE_MMGD),
]

_MESES_PT = {
    1: "jan", 2: "fev", 3: "mar", 4: "abr", 5: "mai", 6: "jun",
    7: "jul", 8: "ago", 9: "set", 10: "out", 11: "nov", 12: "dez",
}


# =============================================================================
# CSS scoped (.bauhaus-table — preservado da versão anterior)
# =============================================================================

_CSS_CAPACIDADE = f"""
<style>
/* ===== Tabela Bauhaus (referência pra projeto) ===== */
.bauhaus-table {{
    width: 100%;
    border-collapse: collapse;
    font-family: 'Inter', sans-serif;
    font-size: 0.9rem;
    margin-top: 0.5rem;
}}
.bauhaus-table thead th {{
    font-family: 'Bebas Neue', sans-serif;
    font-size: 1rem;
    letter-spacing: 0.08em;
    color: {COR_TEXTO};
    background: {COR_GRID};
    padding: 8px 12px;
    border-bottom: 2px solid {COR_TEXTO};
    text-align: left;
    font-weight: 400;
}}
.bauhaus-table tbody td {{
    padding: 6px 12px;
    border-bottom: 1px solid {COR_GRID};
    color: {COR_TEXTO};
}}
.bauhaus-table tbody tr:hover {{
    background: {COR_FUNDO};
}}
.bauhaus-table td.num {{
    text-align: right;
    font-variant-numeric: tabular-nums;
}}
.bauhaus-table th.num {{
    text-align: right;
}}
</style>
"""


# =============================================================================
# Helpers
# =============================================================================


def _montar_df_consolidado() -> pd.DataFrame:
    """Carrega SIGA anual + MMGD anchor points e consolida em 1 DataFrame.

    Schema retornado
    ----------------
    Index ``ANO_MES`` (``DatetimeIndex``)
    Colunas:
        - ``CAP_HIDRO_MW``, ``CAP_TERMICA_MW``, ``CAP_NUCLEAR_MW``,
          ``CAP_EOLICA_MW``, ``CAP_SOLAR_MW``
        - ``CAP_MMGD_MW`` (``NaN`` pre-dez/2022)
        - ``CAP_TOTAL_MW`` (soma — MMGD entra com 0 quando ``NaN``)
        - ``IS_PARTIAL`` (``bool``)
    """
    df_siga = load_siga_anual()
    if df_siga is None or df_siga.empty:
        return pd.DataFrame()

    serie_mmgd = load_mmgd_anual()  # 4 pontos: dez/2022 a dez/2025

    df = df_siga.copy()
    # Merge MMGD: anos pré-2022 ficam NaN (Plotly omite do hover unified).
    df["CAP_MMGD_MW"] = df.index.map(serie_mmgd).astype(float)

    # Propaga origem do MMGD (sql_live | fallback_anchors | unavailable)
    df.attrs["mmgd_source"] = serie_mmgd.attrs.get("source", "unknown")

    # Recalcular total incluindo MMGD (NaN tratado como 0 no total).
    df["CAP_TOTAL_MW"] = (
        df["CAP_HIDRO_MW"]
        + df["CAP_TERMICA_MW"]
        + df["CAP_NUCLEAR_MW"]
        + df["CAP_EOLICA_MW"]
        + df["CAP_SOLAR_MW"]
        + df["CAP_MMGD_MW"].fillna(0.0)
    )

    # Remover CAP_OUTRAS_MW se existir (sempre 0 no SIGA atual; visão anual
    # não plota nem inclui no CSV).
    if "CAP_OUTRAS_MW" in df.columns:
        df = df.drop(columns=["CAP_OUTRAS_MW"])

    return df


def _formatar_label_anual(timestamp: pd.Timestamp, is_partial: bool) -> str:
    """Formata label do eixo X.

    - Ano fechado (dez/AAAA): ``"2024"``
    - Ano parcial: ``"2026 abr"``
    """
    if is_partial:
        return f"{timestamp.year} {_MESES_PT[timestamp.month]}"
    return str(timestamp.year)


def _fmt_num_br(num: float, casas: int = 2) -> str:
    """Formata número no padrão BR (separador milhar ``.``, decimal ``,``)
    com suporte a ``NaN`` (retorna ``"—"``)."""
    if pd.isna(num):
        return "—"
    fmt = f"{num:,.{casas}f}"
    return fmt.replace(",", "X").replace(".", ",").replace("X", ".")


def _gerar_csv_capacidade(df_filtrado: pd.DataFrame) -> bytes:
    """Gera CSV bytes UTF-8 BOM, padrão BR, granularidade anual.

    Schema:
        Rótulo | Hidro (GW) | Térmica (GW) | Nuclear (GW) |
        Eólica (GW) | Solar (GW) | MMGD (GW) | Total (GW) | Parcial
    """
    df_csv = pd.DataFrame({
        "Rótulo": [
            _formatar_label_anual(ts, bool(p))
            for ts, p in zip(df_filtrado.index, df_filtrado["IS_PARTIAL"])
        ],
        "Hidro (GW)":   (df_filtrado["CAP_HIDRO_MW"]   / 1000.0).round(3).values,
        "Térmica (GW)": (df_filtrado["CAP_TERMICA_MW"] / 1000.0).round(3).values,
        "Nuclear (GW)": (df_filtrado["CAP_NUCLEAR_MW"] / 1000.0).round(3).values,
        "Eólica (GW)":  (df_filtrado["CAP_EOLICA_MW"]  / 1000.0).round(3).values,
        "Solar (GW)":   (df_filtrado["CAP_SOLAR_MW"]   / 1000.0).round(3).values,
        "MMGD (GW)":    (df_filtrado["CAP_MMGD_MW"]    / 1000.0).round(3).values,
        "Total (GW)":   (df_filtrado["CAP_TOTAL_MW"]   / 1000.0).round(3).values,
        "Parcial":      df_filtrado["IS_PARTIAL"].values,
    })
    return df_csv.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")


# =============================================================================
# Helper: modo Mensal (12M) — 5 fontes SIGA + MMGD condicional via ANEEL CKAN
# =============================================================================


def _render_modo_mensal(df_mensal: pd.DataFrame) -> None:
    """Renderiza modo Mensal (12M) da aba Capacidade.

    Estética Bauhaus 100% preservada (CSS ``.bauhaus-table``, paleta SIGA,
    Plotly CREAM/JetBrains/Bebas). 5 fontes SIGA empilhadas + MMGD condicional
    via ANEEL CKAN (SUM agregado por cutoffs mensais — G.5 da branch
    ``feat/capacidade-instalada``).

    Fallback ``unavailable``: se SQL falhar em >50% das 12 queries OU se
    merge SIGA × MMGD produzir NaN em qualquer linha, o gráfico renderiza
    apenas as 5 fontes SIGA (sem 6ª trace) e a mini-nota indica fonte
    indisponível.

    Args:
        df_mensal: DataFrame com últimos 12 meses do ``load_siga()``
                   (7 colunas ``CAP_*_MW`` + ``CAP_TOTAL_MW``,
                   indexado por ``ANO_MES``). Será mutado in-place
                   pra adicionar ``CAP_MMGD_MW`` e recalcular
                   ``CAP_TOTAL_MW`` (se ``_tem_mmgd``).
    """
    # Carregar MMGD mensal (SQL ou unavailable se ANEEL fora)
    serie_mmgd_m = load_mmgd_mensal()
    _mmgd_source = serie_mmgd_m.attrs.get("source", "unknown")

    # Merge: adicionar CAP_MMGD_MW ao df_mensal (NaN se index não bate)
    df_mensal["CAP_MMGD_MW"] = df_mensal.index.map(serie_mmgd_m).astype(float)

    # Recalcular TOTAL incluindo MMGD (só se source=sql_live com valores válidos)
    _tem_mmgd = (
        _mmgd_source == "sql_live"
        and df_mensal["CAP_MMGD_MW"].notna().all()
    )
    if _tem_mmgd:
        df_mensal["CAP_TOTAL_MW"] = (
            df_mensal["CAP_HIDRO_MW"]
            + df_mensal["CAP_TERMICA_MW"]
            + df_mensal["CAP_NUCLEAR_MW"]
            + df_mensal["CAP_EOLICA_MW"]
            + df_mensal["CAP_SOLAR_MW"]
            + df_mensal["CAP_MMGD_MW"]
        )

    # ---- Título Bauhaus do gráfico ----
    periodo_str = (
        f"{df_mensal.index.min().strftime('%m/%Y')} a "
        f"{df_mensal.index.max().strftime('%m/%Y')}"
    )
    st.markdown(
        f'<div style="display:flex; justify-content:space-between; '
        f'align-items:baseline; '
        f"font-family:'Bebas Neue', sans-serif; "
        f'font-size:1.1rem; letter-spacing:0.08em; color:{BAUHAUS_BLACK}; '
        f'margin: 2.6rem 0 0.3rem 0; padding-bottom:3px; '
        f'border-bottom: 2px solid {BAUHAUS_BLACK};">'
        f'<span>CAPACIDADE INSTALADA POR FONTE · ÚLTIMOS 12 MESES</span>'
        f'<span>{periodo_str}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ---- Subtítulo Inter ----
    _subtitulo_text = (
        "Evolução mensal · GW (incluindo MMGD via ANEEL CKAN)"
        if _tem_mmgd
        else "Evolução mensal · GW (MMGD mensal indisponível via ANEEL)"
    )
    st.markdown(
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.9rem; color:{BAUHAUS_BLACK}; font-weight:500; '
        f'letter-spacing:0.04em; margin:0 0 0.5rem 0;">'
        f'{_subtitulo_text}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ---- Gráfico Plotly stacked bars (5 fontes SIGA, sem MMGD) ----
    labels_x = df_mensal.index.strftime("%m/%Y").tolist()
    fig = go.Figure()

    # _FONTES_CONFIG[:5] = 5 SIGA; _FONTES_CONFIG = 5 SIGA + MMGD (se disponível).
    _fontes_iter = _FONTES_CONFIG if _tem_mmgd else _FONTES_CONFIG[:5]
    for col, label, cor in _fontes_iter:
        val_gw = df_mensal[col].values / 1000.0
        customdata = [
            f"{v:.2f} GW".replace(".", ",") for v in val_gw
        ]
        label_fix = label.ljust(8).replace(" ", "&nbsp;")
        fig.add_trace(
            go.Bar(
                x=labels_x,
                y=val_gw,
                name=label,
                marker=dict(color=cor),
                customdata=customdata,
                hovertemplate=(
                    f'<span style="color:{cor}; font-weight:700;">'
                    f'{label_fix}</span>'
                    '&nbsp;&nbsp;'
                    f'<span style="color:{BAUHAUS_BLACK};">'
                    '%{customdata}</span>'
                    '<extra></extra>'
                ),
            )
        )

    # ---- Trace invisível pra "Total" no hover unified (G.6.5) ----
    totais_gw = df_mensal["CAP_TOTAL_MW"].values / 1000.0
    total_customdata = [
        f"{v:.2f} GW".replace(".", ",") for v in totais_gw
    ]
    fig.add_trace(
        go.Scatter(
            x=labels_x,
            y=[0] * len(labels_x),
            mode="markers",
            marker=dict(opacity=0),
            showlegend=False,
            customdata=total_customdata,
            hovertemplate=(
                f'<span style="color:{BAUHAUS_BLACK}; font-weight:700;">'
                f'{"TOTAL".ljust(8).replace(" ", "&nbsp;")}</span>'
                '&nbsp;&nbsp;'
                f'<span style="color:{BAUHAUS_BLACK};">'
                '%{customdata}</span>'
                '<extra></extra>'
            ),
        )
    )

    fig.update_layout(
        barmode="stack",
        height=460,
        margin=dict(l=20, r=20, t=20, b=20),
        paper_bgcolor=BAUHAUS_CREAM,
        plot_bgcolor=BAUHAUS_CREAM,
        separators=",.",
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=BAUHAUS_CREAM,
            bordercolor=BAUHAUS_BLACK,
            font=dict(
                family="'JetBrains Mono', 'Courier New', monospace",
                size=12,
                color=BAUHAUS_BLACK,
            ),
        ),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            bgcolor="rgba(0,0,0,0)",
            font=dict(
                family="Bebas Neue, sans-serif",
                size=18,
                color=BAUHAUS_BLACK,
            ),
        ),
        xaxis=dict(
            title=None,
            type="category",
            showgrid=False,
            showline=True,
            linewidth=2,
            linecolor=BAUHAUS_BLACK,
            ticks="outside",
            tickcolor=BAUHAUS_BLACK,
            tickfont=dict(
                family="Inter, sans-serif",
                size=12,
                color=BAUHAUS_BLACK,
            ),
        ),
        yaxis=dict(
            title=None,
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
                size=12,
                color=BAUHAUS_BLACK,
            ),
            zeroline=False,
            tickformat=",.0f",
            ticksuffix=" GW",
        ),
        font=dict(family="Inter, sans-serif", size=12),
    )

    st.plotly_chart(
        fig,
        width="stretch",
        config={"displaylogo": False},
    )

    # ---- Nota descritiva (movida de cima do gráfico pra baixo) ----
    st.markdown(
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.85rem; color:{BAUHAUS_GRAY}; font-style:italic; '
        f'margin:0.6rem 0 0 0;">'
        f'Evolução da capacidade instalada no SIN, por fonte, incluindo MMGD.'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ---- Mini-nota de origem do MMGD ----
    if _tem_mmgd:
        _src_text = "Fonte MMGD: ANEEL CKAN (live)"
        _src_color = BAUHAUS_BLACK
    else:
        _src_text = (
            "Fonte MMGD: indisponível via ANEEL — "
            "modo Mensal exibido sem MMGD"
        )
        _src_color = BAUHAUS_GRAY
    st.markdown(
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.7rem; color:{_src_color}; font-style:italic; '
        f'margin: 0.3rem 0 0 0;">'
        f'{_src_text}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ---- Tabela Bauhaus — 12 meses ordem decrescente ----
    st.markdown(
        f'<div style="font-family:\'Bebas Neue\', sans-serif; '
        f'font-size:1rem; letter-spacing:0.08em; color:{BAUHAUS_BLACK}; '
        f'margin: 2rem 0 0.3rem 0;">'
        f'CAPACIDADE · ÚLTIMOS 12 MESES'
        f'</div>',
        unsafe_allow_html=True,
    )

    df_tab = df_mensal.iloc[::-1].copy()  # mais recente no topo
    cols_tabela = [
        ("CAP_HIDRO_MW",   "HIDRO"),
        ("CAP_TERMICA_MW", "TÉRMICA"),
        ("CAP_NUCLEAR_MW", "NUCLEAR"),
        ("CAP_EOLICA_MW",  "EÓLICA"),
        ("CAP_SOLAR_MW",   "SOLAR"),
    ]
    if _tem_mmgd:
        cols_tabela.append(("CAP_MMGD_MW", "MMGD"))
    cols_tabela.append(("CAP_TOTAL_MW", "TOTAL"))
    linhas_html = []
    for ts, row in df_tab.iterrows():
        mes_fmt = ts.strftime("%m/%Y")
        cells = [f'<td>{mes_fmt}</td>']
        for col_name, _ in cols_tabela:
            val_gw = row[col_name] / 1000.0
            cells.append(
                f'<td class="num">{_fmt_num_br(val_gw, casas=2)}</td>'
            )
        linhas_html.append(f'<tr>{"".join(cells)}</tr>')

    thead_cells = ['<th>MÊS</th>'] + [
        f'<th class="num">{label} (GW)</th>' for _, label in cols_tabela
    ]
    tabela_html = (
        '<table class="bauhaus-table">'
        f'<thead><tr>{"".join(thead_cells)}</tr></thead>'
        f'<tbody>{"".join(linhas_html)}</tbody>'
        '</table>'
    )
    st.markdown(tabela_html, unsafe_allow_html=True)

    # ---- Botão CSV (12 meses, formato BR) ----
    st.markdown(
        '<div style="margin-top: 1rem;"></div>',
        unsafe_allow_html=True,
    )
    csv_dict = {
        "Mês":          df_mensal.index.strftime("%m/%Y").values,
        "Hidro (GW)":   (df_mensal["CAP_HIDRO_MW"]   / 1000.0).round(3).values,
        "Térmica (GW)": (df_mensal["CAP_TERMICA_MW"] / 1000.0).round(3).values,
        "Nuclear (GW)": (df_mensal["CAP_NUCLEAR_MW"] / 1000.0).round(3).values,
        "Eólica (GW)":  (df_mensal["CAP_EOLICA_MW"]  / 1000.0).round(3).values,
        "Solar (GW)":   (df_mensal["CAP_SOLAR_MW"]   / 1000.0).round(3).values,
    }
    if _tem_mmgd:
        csv_dict["MMGD (GW)"] = (df_mensal["CAP_MMGD_MW"] / 1000.0).round(3).values
    csv_dict["Total (GW)"] = (df_mensal["CAP_TOTAL_MW"] / 1000.0).round(3).values
    df_csv = pd.DataFrame(csv_dict)
    csv_bytes = df_csv.to_csv(
        index=False, sep=";", decimal=","
    ).encode("utf-8-sig")
    ini = df_mensal.index.min().strftime("%Y-%m")
    fim = df_mensal.index.max().strftime("%Y-%m")
    filename = f"capacidade_brasil_mensal_{ini}_{fim}.csv"
    st.download_button(
        label="Baixar dados mensais (CSV)",
        data=csv_bytes,
        file_name=filename,
        mime="text/csv",
        width="content",
        key="btn_cap_csv_mensal",
    )

    # ---- Bloco "Fonte" no rodapé (condicional MMGD) ----
    if _tem_mmgd:
        _fonte_rodape = (
            "<strong>Fontes:</strong> SIGA/ANEEL (geração centralizada em fase de Operação) + "
            "ANEEL CKAN (MMGD via SUM agregado server-side com cutoffs mensais). "
            "<br/>"
            "<strong>Cobertura MMGD:</strong> último mês fechado disponível "
            "(cadastros podem ter lag de até 60 dias)."
        )
    else:
        _fonte_rodape = (
            "<strong>Fonte:</strong> SIGA/ANEEL (geração centralizada em fase de Operação). "
            "MMGD não exibida (endpoint ANEEL CKAN indisponível no momento)."
        )
    st.markdown(
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.75rem; color:{BAUHAUS_GRAY}; font-style:italic; '
        f'margin: 2rem 0 0 0; padding-top: 1rem; '
        f'border-top: 1px solid {BAUHAUS_LIGHT};">'
        f'{_fonte_rodape}'
        f'</div>',
        unsafe_allow_html=True,
    )


# =============================================================================
# Wrappers principais
# =============================================================================


def render_aba_capacidade() -> None:
    """Wrapper defensivo. Captura crash e exibe stack trace na tela em vez
    de propagar pra Streamlit (que mostraria 'Oh no' no lugar)."""
    try:
        _render_aba_capacidade_impl()
    except Exception:
        st.error("⚠ Erro ao carregar aba Capacidade (debug ativo)")
        st.code(traceback.format_exc(), language="python")
        st.caption(
            "Este erro foi capturado para investigação. "
            "Por favor, copie o stack trace acima e reporte."
        )


def _render_aba_capacidade_impl() -> None:
    """Renderiza a aba Capacidade — visão ANUAL com 6 fontes empilhadas."""

    # ---- Injeta CSS scoped (1x por render) ----
    st.markdown(_CSS_CAPACIDADE, unsafe_allow_html=True)

    # ---- Título h1 + linha preta separadora (padrão tab_gsf.py:517-522) ----
    # Nota descritiva ("Evolução da capacidade instalada no SIN, por fonte,
    # incluindo MMGD") foi MOVIDA pra DEPOIS do gráfico (annual + mensal) —
    # contexto de fonte cabe melhor como rodapé do gráfico, não como preâmbulo.
    # margin-left: 12px alinha o início da linha com o padding-left do h1
    # global (app.py:170) → cria um pequeno gap visual entre a barra vermelha
    # vertical e a linha preta horizontal (em vez de fazer um "L" colado).
    st.markdown("# CAPACIDADE INSTALADA · BRASIL + MMGD")
    st.markdown(
        f'<div style="border-bottom: 2px solid {BAUHAUS_BLACK}; '
        f'margin: 0 0 1rem 12px;"></div>',
        unsafe_allow_html=True,
    )

    # ---- Init defensivo do selectbox de granularidade (ANTES do widget) ----
    if "cap_granularidade" not in st.session_state:
        st.session_state["cap_granularidade"] = "Anual"

    # ---- Controles: selectbox de granularidade + (date_inputs no modo Anual) ----
    col_gran, col_ini, col_fim, _ = st.columns(
        [1.2, 1.4, 1.4, 4],
        vertical_alignment="bottom",
    )
    with col_gran:
        granularidade = st.selectbox(
            "Granularidade",
            options=["Anual", "Mensal (12M)"],
            key="cap_granularidade",
        )

    # ============================================================
    # BRANCH MENSAL: carrega SIGA mensal, recorta 12 meses, delega ao helper
    # ============================================================
    if granularidade == "Mensal (12M)":
        from data_loaders.data_loader_aneel_siga import load_siga
        with st.spinner("Carregando capacidade mensal (SIGA / últimos 12 meses)…"):
            df_mensal = load_siga()
        if df_mensal is None or df_mensal.empty:
            st.warning("Dados mensais indisponíveis.")
            return
        df_mensal = df_mensal.tail(12).copy()
        _render_modo_mensal(df_mensal)
        return

    # ============================================================
    # BRANCH ANUAL (default): consolida SIGA anual + MMGD anchors
    # ============================================================
    with st.spinner("Carregando capacidade instalada (SIGA + MMGD)…"):
        df_completo = _montar_df_consolidado()

    if df_completo is None or df_completo.empty:
        st.warning(
            "Não foi possível carregar dados de capacidade. "
            "Verifique logs em st.session_state['_debug_erros']."
        )
        return

    # ---- Controles de período (date_inputs, anos cobertos) ----
    min_disponivel = df_completo.index.min().date()
    max_disponivel = df_completo.index.max().date()

    # Default últimos 10 anos (recortado pelo min disponível se for o caso).
    hoje = date.today()
    default_ini_candidato = date(hoje.year - 10, 1, 1)
    default_ini = max(min_disponivel, default_ini_candidato)

    if "cap_data_ini" not in st.session_state:
        st.session_state["cap_data_ini"] = default_ini
    if "cap_data_fim" not in st.session_state:
        st.session_state["cap_data_fim"] = max_disponivel

    with col_ini:
        st.date_input(
            "Data inicial",
            min_value=min_disponivel,
            max_value=max_disponivel,
            key="cap_data_ini",
            format="DD/MM/YYYY",
        )
    with col_fim:
        st.date_input(
            "Data final",
            min_value=min_disponivel,
            max_value=max_disponivel,
            key="cap_data_fim",
            format="DD/MM/YYYY",
        )

    data_ini = st.session_state["cap_data_ini"]
    data_fim = st.session_state["cap_data_fim"]
    if data_ini > data_fim:
        st.error("Data inicial não pode ser maior que data final.")
        st.stop()

    # Filtro por ANO (date_input só delimita janela de anos visíveis)
    ano_ini = data_ini.year
    ano_fim = data_fim.year
    df_filtrado = df_completo[
        (df_completo.index.year >= ano_ini)
        & (df_completo.index.year <= ano_fim)
    ].copy()

    if df_filtrado.empty:
        st.info("Nenhum dado no período selecionado.")
        return

    # ---- Título Bauhaus do gráfico (período adapta pra rótulos anuais) ----
    primeiro_label = _formatar_label_anual(
        df_filtrado.index.min(),
        bool(df_filtrado["IS_PARTIAL"].iloc[0]),
    )
    ultimo_label = _formatar_label_anual(
        df_filtrado.index.max(),
        bool(df_filtrado["IS_PARTIAL"].iloc[-1]),
    )
    if primeiro_label == ultimo_label:
        periodo_str = primeiro_label
    else:
        periodo_str = f"{primeiro_label} a {ultimo_label}"

    st.markdown(
        f'<div style="display:flex; justify-content:space-between; '
        f'align-items:baseline; '
        f"font-family:'Bebas Neue', sans-serif; "
        f'font-size:1.1rem; letter-spacing:0.08em; color:{BAUHAUS_BLACK}; '
        f'margin: 2.6rem 0 0.3rem 0; padding-bottom:3px; '
        f'border-bottom: 2px solid {BAUHAUS_BLACK};">'
        f'<span>CAPACIDADE INSTALADA POR FONTE</span>'
        f'<span>{periodo_str}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ---- Subtítulo Inter ----
    st.markdown(
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.9rem; color:{BAUHAUS_BLACK}; font-weight:500; '
        f'letter-spacing:0.04em; margin:0 0 0.5rem 0;">'
        f'Evolução anual · GW'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ---- Gráfico stacked bar Plotly ----
    # Labels categóricos pro eixo X (tipo "category" preserva ordem)
    labels_x = [
        _formatar_label_anual(ts, bool(p))
        for ts, p in zip(df_filtrado.index, df_filtrado["IS_PARTIAL"])
    ]

    # Opacidades: 1.0 pra fechados, 0.7 pra parcial (lista por ponto)
    opacidades = [
        0.7 if bool(p) else 1.0
        for p in df_filtrado["IS_PARTIAL"]
    ]

    fig = go.Figure()

    for col, label, cor in _FONTES_CONFIG:
        val_mw = df_filtrado[col].values  # pode ter NaN em MMGD pre-2022
        val_gw = val_mw / 1000.0

        # Customdata: GW formatado BR pra hover monospace. NaN → None
        # (Plotly omite trace+customdata=None do hover unified).
        customdata = [
            f"{v / 1000.0:.2f} GW".replace(".", ",")
            if pd.notna(v) else None
            for v in val_mw
        ]

        # Padded label (8 chars) pra alinhamento monospace no hover
        label_fix = label.ljust(8).replace(" ", "&nbsp;")

        fig.add_trace(
            go.Bar(
                x=labels_x,
                y=val_gw,
                name=label,
                marker=dict(color=cor, opacity=opacidades),
                customdata=customdata,
                hovertemplate=(
                    f'<span style="color:{cor}; font-weight:700;">'
                    f'{label_fix}</span>'
                    '&nbsp;&nbsp;'
                    f'<span style="color:{BAUHAUS_BLACK};">'
                    '%{customdata}</span>'
                    '<extra></extra>'
                ),
            )
        )

    # ---- Trace invisível pra "Total" no hover unified (G.6.5) ----
    totais_gw = df_filtrado["CAP_TOTAL_MW"].values / 1000.0
    total_customdata = [
        f"{v:.2f} GW".replace(".", ",") for v in totais_gw
    ]
    fig.add_trace(
        go.Scatter(
            x=labels_x,
            y=[0] * len(labels_x),
            mode="markers",
            marker=dict(opacity=0),
            showlegend=False,
            customdata=total_customdata,
            hovertemplate=(
                f'<span style="color:{BAUHAUS_BLACK}; font-weight:700;">'
                f'{"TOTAL".ljust(8).replace(" ", "&nbsp;")}</span>'
                '&nbsp;&nbsp;'
                f'<span style="color:{BAUHAUS_BLACK};">'
                '%{customdata}</span>'
                '<extra></extra>'
            ),
        )
    )

    fig.update_layout(
        barmode="stack",
        height=460,
        margin=dict(l=20, r=20, t=20, b=20),
        paper_bgcolor=BAUHAUS_CREAM,
        plot_bgcolor=BAUHAUS_CREAM,
        separators=",.",
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=BAUHAUS_CREAM,
            bordercolor=BAUHAUS_BLACK,
            font=dict(
                family="'JetBrains Mono', 'Courier New', monospace",
                size=12,
                color=BAUHAUS_BLACK,
            ),
        ),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            bgcolor="rgba(0,0,0,0)",
            font=dict(
                family="Bebas Neue, sans-serif",
                size=18,
                color=BAUHAUS_BLACK,
            ),
        ),
        xaxis=dict(
            title=None,
            type="category",
            showgrid=False,
            showline=True,
            linewidth=2,
            linecolor=BAUHAUS_BLACK,
            ticks="outside",
            tickcolor=BAUHAUS_BLACK,
            tickfont=dict(
                family="Inter, sans-serif",
                size=12,
                color=BAUHAUS_BLACK,
            ),
        ),
        yaxis=dict(
            title=None,
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
                size=12,
                color=BAUHAUS_BLACK,
            ),
            zeroline=False,
            tickformat=",.0f",
            ticksuffix=" GW",
        ),
        font=dict(family="Inter, sans-serif", size=12),
    )

    st.plotly_chart(
        fig,
        width="stretch",
        config={"displaylogo": False},
    )

    # ---- Nota descritiva (movida de cima do gráfico pra baixo) ----
    st.markdown(
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.85rem; color:{BAUHAUS_GRAY}; font-style:italic; '
        f'margin:0.6rem 0 0 0;">'
        f'Evolução da capacidade instalada no SIN, por fonte, incluindo MMGD.'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ---- Mini-nota de origem do MMGD (G.3 — feedback visual de fallback) ----
    _mmgd_source = df_filtrado.attrs.get("mmgd_source", "unknown")
    if _mmgd_source == "sql_live":
        _src_text = "Fonte MMGD: ANEEL CKAN (live)"
        _src_color = BAUHAUS_BLACK
    elif _mmgd_source == "fallback_anchors":
        _src_text = "Fonte MMGD: anchors hardcoded (ANEEL indisponível)"
        _src_color = BAUHAUS_GRAY
    else:
        _src_text = f"Fonte MMGD: {_mmgd_source}"
        _src_color = BAUHAUS_GRAY
    st.markdown(
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.7rem; color:{_src_color}; font-style:italic; '
        f'margin: 0.3rem 0 0 0;">'
        f'{_src_text}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ---- Tabela Bauhaus — últimos 10 ANOS do recorte, ordem decrescente ----
    st.markdown(
        f'<div style="font-family:\'Bebas Neue\', sans-serif; '
        f'font-size:1rem; letter-spacing:0.08em; color:{BAUHAUS_BLACK}; '
        f'margin: 2rem 0 0.3rem 0;">'
        f'CAPACIDADE · ÚLTIMOS 10 ANOS DO PERÍODO'
        f'</div>',
        unsafe_allow_html=True,
    )

    # tail(10): últimos 10 do recorte; iloc[::-1]: ordem decrescente (mais
    # recente no topo).
    ultimos_10 = df_filtrado.tail(10).iloc[::-1].copy()
    if len(ultimos_10) > 0:
        # 8 colunas: ANO + 6 fontes + TOTAL
        cols_tabela = [
            ("CAP_HIDRO_MW",   "HIDRO"),
            ("CAP_TERMICA_MW", "TÉRMICA"),
            ("CAP_NUCLEAR_MW", "NUCLEAR"),
            ("CAP_EOLICA_MW",  "EÓLICA"),
            ("CAP_SOLAR_MW",   "SOLAR"),
            ("CAP_MMGD_MW",    "MMGD"),
            ("CAP_TOTAL_MW",   "TOTAL"),
        ]
        linhas_html = []
        for ts, row in ultimos_10.iterrows():
            rotulo = _formatar_label_anual(ts, bool(row["IS_PARTIAL"]))
            cells = [f'<td>{rotulo}</td>']
            for col_name, _ in cols_tabela:
                val_mw = row[col_name]
                if pd.isna(val_mw):
                    cells.append('<td class="num">—</td>')
                else:
                    val_gw = val_mw / 1000.0
                    cells.append(
                        f'<td class="num">{_fmt_num_br(val_gw, casas=2)}</td>'
                    )
            linhas_html.append(f'<tr>{"".join(cells)}</tr>')

        thead_cells = ['<th>ANO</th>'] + [
            f'<th class="num">{label} (GW)</th>' for _, label in cols_tabela
        ]
        tabela_html = (
            '<table class="bauhaus-table">'
            f'<thead><tr>{"".join(thead_cells)}</tr></thead>'
            f'<tbody>{"".join(linhas_html)}</tbody>'
            '</table>'
        )
        st.markdown(tabela_html, unsafe_allow_html=True)
    else:
        st.caption("(sem dados)")

    # ---- Botão CSV (mesmo recorte do gráfico) ----
    st.markdown(
        '<div style="margin-top: 1rem;"></div>',
        unsafe_allow_html=True,
    )
    csv_bytes = _gerar_csv_capacidade(df_filtrado)
    filename = f"capacidade_brasil_anual_{ano_ini}-{ano_fim}.csv"
    st.download_button(
        label="Baixar dados anuais (CSV)",
        data=csv_bytes,
        file_name=filename,
        mime="text/csv",
        width="content",
        key="btn_cap_csv",
    )

    # ---- Bloco "Fonte" no rodapé ----
    st.markdown(
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.75rem; color:{BAUHAUS_GRAY}; font-style:italic; '
        f'margin: 2rem 0 0 0; padding-top: 1rem; '
        f'border-top: 1px solid {BAUHAUS_LIGHT};">'
        f'<strong>Fontes:</strong> SIGA/ANEEL (geração centralizada em fase de Operação) + '
        f'EPE PDGD (Mini e Microgeração Distribuída, anchor points anuais '
        f'a partir de dez/2022, marco Lei 14.300). '
        f'<br/>'
        f'<strong>MMGD em abr/2026:</strong> último dado oficial dez/2025 (EPE PDGD) carregado '
        f'para frente. Próxima revisão esperada com release PDGD ~abr/2027.'
        f'</div>',
        unsafe_allow_html=True,
    )
