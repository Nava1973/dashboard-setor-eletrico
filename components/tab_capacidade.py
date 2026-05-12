"""
tab_capacidade.py
=================

Aba CAPACIDADE INSTALADA do dashboard (versão preliminar — apenas SIGA,
agora decomposta por fonte de geração).

Estado preliminar (faltam pra v3 completa):
- MMGD ainda não integrada (próxima sessão) — entrará como nova
  categoria empilhada acima das 5 fontes existentes.
- Cross-checks ONS e EPE pendentes.
- KPIs (Cap. Total / % MMGD) ainda não entram — chegam com MMGD.

Fonte (atual): SIGA — Sistema de Informações de Geração da ANEEL
    via data_loaders.data_loader_aneel_siga.load_siga()

Schema esperado do DataFrame retornado pelo loader:
    Indexado por ANO_MES (Timestamp 1º dia do mês), com 7 colunas em
    MW (estoque acumulado por fonte):
        CAP_HIDRO_MW    (UHE + PCH + CGH)
        CAP_TERMICA_MW  (UTE)
        CAP_NUCLEAR_MW  (UTN)
        CAP_EOLICA_MW   (EOL)
        CAP_SOLAR_MW    (UFV)
        CAP_OUTRAS_MW   (defensivo, 0 no schema atual)
        CAP_TOTAL_MW    (soma das 6 anteriores)

Visualização (preliminar):
- Controles de período: 3M / 12M / Tudo + 2 date_inputs
- Gráfico de COLUNAS EMPILHADAS por fonte (5 séries plotadas;
  OUTRAS no DataFrame mas omitida do plot por ser 0).
- Eixo Y em GW. Hover monospace JetBrains Mono alinhado.
- Tabela últimos meses do período selecionado (.bauhaus-table)
  com 7 colunas (MÊS + 5 fontes + TOTAL — OUTRAS omitida).
- Botão CSV completo (8 colunas — INCLUI Outras pra transparência).

Janela histórica do gráfico: a partir de 2023-01 (SPEC §3.1, marco
Lei 14.300/2022). O cumsum interno do loader cobre desde 1900 — o
recorte 2023-01 acontece aqui na UI.
"""

from __future__ import annotations

import traceback
from dateutil.relativedelta import relativedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_loaders.data_loader_aneel_siga import load_siga
from utils.cores_fontes import (
    COR_FONTE_HIDRO,
    COR_FONTE_TERMICA,
    COR_FONTE_NUCLEAR,
    COR_FONTE_EOLICA,
    COR_FONTE_SOLAR,
)


# =============================================================================
# Paleta Bauhaus estrutural (cores de UI — bordas, fundos, texto)
# =============================================================================

BAUHAUS_BLACK = "#1A1A1A"
BAUHAUS_CREAM = "#F5F1E8"
BAUHAUS_LIGHT = "#E8E3D4"
BAUHAUS_GRAY = "#6B6B6B"

# Cores canônicas de fontes de geração — importadas de utils/cores_fontes.py
# (decisão 5.33 RESOLVIDA). Paleta consistente com todas as outras abas
# do dashboard que mostram fontes de geração (Geração, Carga, Curtailment,
# Modulação, Capacidade).

# Configuração das fontes plotadas. Ordem importa pro empilhamento:
# 1ª trace adicionada fica na base do stack (Hidro embaixo, Solar em cima).
# OUTRAS NÃO entra aqui — fica no DataFrame mas não é plotada (0 no
# schema atual; se aparecer no futuro, vai aparecer no CSV mas não no plot).
_FONTES_CONFIG = [
    ("CAP_HIDRO_MW",   "Hidro",   COR_FONTE_HIDRO),
    ("CAP_TERMICA_MW", "Térmica", COR_FONTE_TERMICA),
    ("CAP_NUCLEAR_MW", "Nuclear", COR_FONTE_NUCLEAR),
    ("CAP_EOLICA_MW",  "Eólica",  COR_FONTE_EOLICA),
    ("CAP_SOLAR_MW",   "Solar",   COR_FONTE_SOLAR),
]

# Janela inicial do gráfico (SPEC §3.1 — marco Lei 14.300/2022)
JANELA_INICIO = pd.Timestamp("2023-01-01")


# =============================================================================
# CSS scoped (.bauhaus-table — referência reusável pra próximas tabelas)
# =============================================================================

_CSS_CAPACIDADE = """
<style>
/* ===== Tabela Bauhaus (referência pra projeto) ===== */
.bauhaus-table {
    width: 100%;
    border-collapse: collapse;
    font-family: 'Inter', sans-serif;
    font-size: 0.9rem;
    margin-top: 0.5rem;
}
.bauhaus-table thead th {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 1rem;
    letter-spacing: 0.08em;
    color: #1A1A1A;
    background: #E8E3D4;
    padding: 8px 12px;
    border-bottom: 2px solid #1A1A1A;
    text-align: left;
    font-weight: 400;
}
.bauhaus-table tbody td {
    padding: 6px 12px;
    border-bottom: 1px solid #E8E3D4;
    color: #1A1A1A;
}
.bauhaus-table tbody tr:hover {
    background: #F5F1E8;
}
.bauhaus-table td.num {
    text-align: right;
    font-variant-numeric: tabular-nums;
}
.bauhaus-table th.num {
    text-align: right;
}
</style>
"""


# =============================================================================
# Helper: controles de período (inline — pattern decisão 5.12)
# =============================================================================


def _render_period_controls_cap(df: pd.DataFrame):
    """Renderiza 3 atalhos (3M / 12M / Tudo) + 2 date_inputs.

    Estado em ``session_state['cap_data_ini'/'cap_data_fim']``.
    Retorna ``(data_ini, data_fim)`` como ``datetime.date``.

    Limita a janela visível ao período pós-2023-01 (SPEC §3.1).
    """
    # Recorte 2023-01 → max do DataFrame
    max_d = df.index.max().date()
    df_visivel = df[df.index >= JANELA_INICIO]
    if df_visivel.empty:
        min_d = max_d
    else:
        min_d = df_visivel.index.min().date()

    # Init defensivo (1ª render) — default 12M
    if "cap_data_ini" not in st.session_state:
        default_ini = max(min_d, max_d - relativedelta(months=11))
        st.session_state["cap_data_ini"] = default_ini
    if "cap_data_fim" not in st.session_state:
        st.session_state["cap_data_fim"] = max_d

    presets = [
        ("3M", 2, False),    # 2 meses atrás + atual = 3 meses
        ("12M", 11, False),  # 11 meses atrás + atual = 12 meses
        ("Tudo", None, True),
    ]

    # Detecta preset ativo (data_fim == max_d AND data_ini bate com target)
    data_ini_atual = st.session_state["cap_data_ini"]
    data_fim_atual = st.session_state["cap_data_fim"]
    preset_atual = None
    if data_fim_atual == max_d:
        for label, n_meses_atras, is_tudo in presets:
            if is_tudo:
                if data_ini_atual == min_d:
                    preset_atual = label
                    break
            else:
                target = max(
                    min_d, max_d - relativedelta(months=n_meses_atras)
                )
                if data_ini_atual == target:
                    preset_atual = label
                    break

    # Layout: 3 botões + spacer + 2 date_inputs
    cols = st.columns([1, 1, 1, 0.3, 1.4, 1.4])

    for i, (label, n_meses_atras, is_tudo) in enumerate(presets):
        with cols[i]:
            tipo = "primary" if label == preset_atual else "secondary"
            if st.button(
                label,
                use_container_width=True,
                key=f"btn_cap_{label}",
                type=tipo,
            ):
                if is_tudo:
                    st.session_state["cap_data_ini"] = min_d
                else:
                    st.session_state["cap_data_ini"] = max(
                        min_d, max_d - relativedelta(months=n_meses_atras)
                    )
                st.session_state["cap_data_fim"] = max_d
                st.rerun()

    with cols[4]:
        st.date_input(
            "Data inicial",
            min_value=min_d,
            max_value=max_d,
            key="cap_data_ini",
            format="DD/MM/YYYY",
        )
    with cols[5]:
        st.date_input(
            "Data final",
            min_value=min_d,
            max_value=max_d,
            key="cap_data_fim",
            format="DD/MM/YYYY",
        )

    return (
        st.session_state["cap_data_ini"],
        st.session_state["cap_data_fim"],
    )


# =============================================================================
# Helper: filtrar DataFrame por janela
# =============================================================================


def _filtrar_periodo(
    df: pd.DataFrame,
    data_ini,
    data_fim,
) -> pd.DataFrame:
    """Recorta o DataFrame por janela (datas inclusive)."""
    ini_ts = pd.Timestamp(data_ini)
    fim_ts = pd.Timestamp(data_fim)
    mask = (df.index >= ini_ts) & (df.index <= fim_ts)
    return df[mask]


def _fmt_num_br(num: float, casas: int = 2) -> str:
    """Formata número no padrão BR (separador milhar `.`, decimal `,`)."""
    fmt = f"{num:,.{casas}f}"
    return fmt.replace(",", "X").replace(".", ",").replace("X", ".")


# =============================================================================
# Helper: gerar CSV (8 colunas — inclui OUTRAS pra transparência)
# =============================================================================


def _gerar_csv_capacidade(df_filtrado: pd.DataFrame) -> bytes:
    """Gera CSV bytes UTF-8 BOM, padrão BR.

    Schema: Data | Hidro (MW) | Térmica (MW) | Nuclear (MW) |
            Eólica (MW) | Solar (MW) | Outras (MW) | Total (MW)

    OUTRAS é incluída pra transparência total dos dados, mesmo
    que seja 0 no schema atual. ``sep=';'``, ``decimal=','``,
    encoding ``utf-8-sig``, datas em ``DD/MM/YYYY``.
    """
    df_csv = df_filtrado.reset_index().copy()
    df_csv["Data"] = df_csv["ANO_MES"].dt.strftime("%d/%m/%Y")
    cols_order = [
        "Data",
        "CAP_HIDRO_MW",
        "CAP_TERMICA_MW",
        "CAP_NUCLEAR_MW",
        "CAP_EOLICA_MW",
        "CAP_SOLAR_MW",
        "CAP_OUTRAS_MW",
        "CAP_TOTAL_MW",
    ]
    df_csv = df_csv[cols_order].rename(columns={
        "CAP_HIDRO_MW":   "Hidro (MW)",
        "CAP_TERMICA_MW": "Térmica (MW)",
        "CAP_NUCLEAR_MW": "Nuclear (MW)",
        "CAP_EOLICA_MW":  "Eólica (MW)",
        "CAP_SOLAR_MW":   "Solar (MW)",
        "CAP_OUTRAS_MW":  "Outras (MW)",
        "CAP_TOTAL_MW":   "Total (MW)",
    })
    return df_csv.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")


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
    """Renderiza a aba Capacidade (versão preliminar — só SIGA, decomposto)."""

    # ---- Injeta CSS scoped (1x por render) ----
    st.markdown(_CSS_CAPACIDADE, unsafe_allow_html=True)

    # ---- Título h1 (padrão das outras abas) ----
    st.markdown("# CAPACIDADE INSTALADA · BRASIL")

    # ---- Footnote preliminar (Inter italic cinza) ----
    st.markdown(
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.85rem; color:{BAUHAUS_GRAY}; font-style:italic; '
        f'margin:0 0 0.8rem 0;">'
        f'Versão preliminar — MMGD será adicionada na próxima sessão '
        f'como nova categoria empilhada. Fonte atual: SIGA (ANEEL), '
        f'geração centralizada Brasil em fase de Operação.'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ---- Carrega dados ----
    with st.spinner("Carregando capacidade instalada (SIGA / ANEEL)…"):
        df_completo = load_siga()

    if df_completo is None or df_completo.empty:
        st.warning(
            "Não foi possível carregar dados de capacidade do SIGA. "
            "Verifique logs em st.session_state['_debug_erros']."
        )
        return

    # Recorte a partir de 2023-01 (SPEC §3.1)
    df_visivel = df_completo[df_completo.index >= JANELA_INICIO]
    if df_visivel.empty:
        st.warning("Sem dados pós-2023-01 disponíveis.")
        return

    # ---- Controles de período ----
    data_ini, data_fim = _render_period_controls_cap(df_completo)

    if data_ini > data_fim:
        st.error("Data inicial não pode ser maior que data final.")
        st.stop()

    df_filtrado = _filtrar_periodo(df_completo, data_ini, data_fim)

    # ---- Título Bauhaus do gráfico (padrão decisão 5.22) ----
    if len(df_filtrado) > 0:
        periodo_str = (
            f"{df_filtrado.index.min().strftime('%m/%Y')} a "
            f"{df_filtrado.index.max().strftime('%m/%Y')}"
        )
    else:
        periodo_str = "—"

    st.markdown(
        f'<div style="display:flex; justify-content:space-between; '
        f'align-items:baseline; '
        f"font-family:'Bebas Neue', sans-serif; "
        f'font-size:1.1rem; letter-spacing:0.08em; color:{BAUHAUS_BLACK}; '
        f'margin: 2.6rem 0 0.3rem 0; padding-bottom:3px; '
        f'border-bottom: 2px solid {BAUHAUS_BLACK};">'
        f'<span>CAPACIDADE INSTALADA POR FONTE · ESTOQUE ACUMULADO</span>'
        f'<span>{periodo_str}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ---- Subtítulo Inter (padrão decisão 5.22) ----
    st.markdown(
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.9rem; color:{BAUHAUS_BLACK}; font-weight:500; '
        f'letter-spacing:0.04em; margin:0 0 0.5rem 0;">'
        f'Evolução mensal · GW'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ---- Gráfico de COLUNAS EMPILHADAS (Plotly) ----
    if len(df_filtrado) > 0:
        fig = go.Figure()

        # 5 traces, uma por fonte (na ordem de _FONTES_CONFIG).
        # Hidro embaixo (1ª adicionada), Solar em cima (última).
        for col, label, cor in _FONTES_CONFIG:
            val_mw = df_filtrado[col].values
            val_gw = val_mw / 1000.0

            # Customdata: GW formatado BR pra hover monospace
            customdata = [
                f"{v / 1000.0:.2f} GW".replace(".", ",")
                if pd.notna(v) else "—"
                for v in val_mw
            ]

            # Padded label (8 chars) pra alinhamento monospace no hover
            label_fix = label.ljust(8).replace(" ", "&nbsp;")

            fig.add_trace(
                go.Bar(
                    x=df_filtrado.index,
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
            use_container_width=True,
            config={"displaylogo": False},
        )
    else:
        st.info("Sem dados no período selecionado.")

    # ---- Tabela últimos 12 meses do PERÍODO FILTRADO (.bauhaus-table) ----
    st.markdown(
        f'<div style="font-family:\'Bebas Neue\', sans-serif; '
        f'font-size:1rem; letter-spacing:0.08em; color:{BAUHAUS_BLACK}; '
        f'margin: 2rem 0 0.3rem 0;">'
        f'CAPACIDADE · PERÍODO SELECIONADO (ATÉ 12 MESES)'
        f'</div>',
        unsafe_allow_html=True,
    )

    ultimos_12 = (
        df_filtrado.tail(12) if len(df_filtrado) >= 12 else df_filtrado
    )
    if len(ultimos_12) > 0:
        # 7 colunas: MÊS + 5 fontes + TOTAL (OUTRAS omitido visualmente)
        cols_tabela = [
            ("CAP_HIDRO_MW",   "HIDRO"),
            ("CAP_TERMICA_MW", "TÉRMICA"),
            ("CAP_NUCLEAR_MW", "NUCLEAR"),
            ("CAP_EOLICA_MW",  "EÓLICA"),
            ("CAP_SOLAR_MW",   "SOLAR"),
            ("CAP_TOTAL_MW",   "TOTAL"),
        ]
        linhas_html = []
        for ts, row in ultimos_12.iterrows():
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
    else:
        st.caption("(sem dados)")

    # ---- Botão CSV (8 colunas — inclui OUTRAS pra transparência) ----
    st.markdown(
        '<div style="margin-top: 1rem;"></div>',
        unsafe_allow_html=True,
    )
    csv_bytes = _gerar_csv_capacidade(df_filtrado)
    filename = (
        f"capacidade_brasil_"
        f"{pd.Timestamp(data_ini).strftime('%Y-%m')}_"
        f"{pd.Timestamp(data_fim).strftime('%Y-%m')}.csv"
    )
    st.download_button(
        label="Baixar dados filtrados (CSV)",
        data=csv_bytes,
        file_name=filename,
        mime="text/csv",
        use_container_width=False,
        key="btn_cap_csv",
    )
