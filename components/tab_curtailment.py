"""
tab_curtailment.py
==================

Aba CURTAILMENT do dashboard do setor elétrico.

Estrutura (sub-abas internas):
    1. Visão geral       - KPIs + série temporal por tipo de restrição
    2. Por estado        - Heatmap UF × tipo                 (em construção)
    3. Por usina         - Matriz usinas × períodos          (em construção)
    4. Por grupo         - Por grupo econômico               (em construção)
    5. Debug mapeamento  - Cobertura Excel ↔ ONS             (em construção)

Granularidades: Diária, Mensal, Trimestral.
Presets de período: 30D, 90D, 6M, 12M, Máx.

Mapeamento de proprietário:
    Fonte primária: data/curtailment/unidades_geradoras.xlsx
    Aliases manuais: data/curtailment/aliases_curtailment.csv
    Rateio proporcional aplicado.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, List, Optional, Tuple

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from data_loaders.data_loader_curtailment import (
    carregar_curtailment, descobrir_ultimo_dia_disponivel,
)
from data_loaders.data_loader_grupos_excel import (
    carregar_grupos_excel, carregar_aliases, aplicar_rateio,
    EXCEL_DEFAULT_PATH,
)
from utils.utils_periodos import adicionar_chave_periodo
from utils.utils_curtailment import (
    serie_temporal,
    calcular_periodos_curtailment, pct_no_periodo,
    _inicio_trimestre, _inicio_trimestre_anterior, _inicio_mes_anterior,
)


# =============================================================================
# Paleta Bauhaus (duplicada do app.py:61-76 — manter sincronizada).
# Não é importável do app.py por evitar circular import (app importa este).
# Refator futuro: mover pra utils/bauhaus_palette.py compartilhado.
# =============================================================================

BAUHAUS_RED    = "#D62828"
BAUHAUS_YELLOW = "#F6BD16"
BAUHAUS_BLUE   = "#2A6F97"
BAUHAUS_BLACK  = "#1A1A1A"
BAUHAUS_CREAM  = "#F5F1E8"
BAUHAUS_GRAY   = "#4A4A4A"
BAUHAUS_LIGHT  = "#E8E3D4"

# Cores canônicas de fontes de geração (decisão 5.33 do CLAUDE.md)
COR_FONTE_SOLAR  = "#F6BD16"
COR_FONTE_EOLICA = "#8FA31E"


# =============================================================================
# Mapeamento razão → cor + labels (briefing §2.1)
# =============================================================================

CORES_RAZAO = {
    "ENE": BAUHAUS_RED,     # energético (sobreoferta) — ~98% do total histórico
    "CNF": BAUHAUS_YELLOW,  # confiabilidade
    "REL": BAUHAUS_BLUE,    # elétrico (indisponibilidade externa)
    "PAR": BAUHAUS_BLACK,   # parecer de acesso (raramente usado, opt-in)
}

LABELS_RAZAO = {
    "ENE": "Energético",
    "CNF": "Confiabilidade",
    "REL": "Elétrico",
    "PAR": "Parecer Acesso",
}

# Granularidade UI → chave interna do utils_periodos
GRANS_UI = {
    "Diária":     "DIARIO",
    "Mensal":     "MENSAL",
    "Trimestral": "TRIMESTRAL",
}

# =============================================================================
# Modos de janela ampla (Caminho 1 + expansão sob demanda).
# Default = ~13M (4 trimestres atrás). 24M e Máx exigem download adicional
# (~3min e ~5-7min respectivamente, medidos empiricamente). State sticky
# em curt_janela_modo, resetado por clear_cache (data_loader.py).
# Padrão análogo à decisão 5.17 (Geração: gen_historico_completo).
# =============================================================================

_CURT_MODOS_JANELA = {
    "default": lambda mx: _inicio_trimestre_anterior(mx, 4),
    "24m":     lambda mx: _inicio_trimestre_anterior(mx, 7),
    "max":     lambda mx: date(2022, 1, 1),
}


def _data_ini_ampla_efetiva(max_d: date, modo: str) -> date:
    """data_ini_ampla calculada conforme modo (default/24m/max)."""
    fn = _CURT_MODOS_JANELA.get(modo, _CURT_MODOS_JANELA["default"])
    return max(date(2022, 1, 1), fn(max_d))


# =============================================================================
# Presets de período por granularidade.
# - Diária: presets em dias contados pra trás (sem encaixe).
# - Mensal: encaixe em fronteira de mês (1M = mês atual desde dia 1).
# - Trimestral: encaixe em fronteira de trimestre (6M = 2 trimestres).
# Cada tuple: (label, data_ini_fn, is_max). data_ini_fn é Callable[[date], date]
# que recebe max_d e retorna data_ini esperada do preset. Pra "Máx" passa None
# (helper resolve usando min_d).
# =============================================================================

PRESETS_BY_GRAN = {
    "DIARIO": {
        "default": "30D",
        "presets": [
            ("30D",  lambda mx: mx - timedelta(days=30),  False),
            ("90D",  lambda mx: mx - timedelta(days=90),  False),
            ("6M",   lambda mx: mx - timedelta(days=180), False),
            ("12M",  lambda mx: mx - timedelta(days=365), False),
            ("Máx",  None, True),
        ],
    },
    "MENSAL": {
        "default": "12M",
        "presets": [
            ("1M",   lambda mx: _inicio_mes_anterior(mx, 0),  False),
            ("3M",   lambda mx: _inicio_mes_anterior(mx, 2),  False),
            ("6M",   lambda mx: _inicio_mes_anterior(mx, 5),  False),
            ("12M",  lambda mx: _inicio_mes_anterior(mx, 11), False),
            ("Máx",  None, True),
        ],
    },
    "TRIMESTRAL": {
        "default": "12M",
        "presets": [
            ("6M",   lambda mx: _inicio_trimestre_anterior(mx, 1),  False),
            ("12M",  lambda mx: _inicio_trimestre_anterior(mx, 3),  False),
            ("24M",  lambda mx: _inicio_trimestre_anterior(mx, 7),  False),
            ("Máx",  None, True),
        ],
    },
}


# =============================================================================
# Helpers de formatação BR
# =============================================================================


def _fmt_br_curt(v, casas: int = 0) -> str:
    """Número BR: 1.234,56 (milhar ponto, decimal vírgula)."""
    if v is None or pd.isna(v):
        return "—"
    fmt = f"{{:,.{casas}f}}"
    return fmt.format(v).replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_pct_curt(x, casas: int = 2) -> str:
    """Pct BR: '5,32%' (recebe valor 0-1, multiplica por 100)."""
    if x is None or pd.isna(x):
        return "—"
    return _fmt_br_curt(x * 100, casas) + "%"


# =============================================================================
# Helpers de fronteira temporal (mês/trimestre)
# Usados pelos presets adaptativos por granularidade — Mensal e Trimestral
# encaixam em fronteira de mês/trimestre, Diária não encaixa.
# =============================================================================


# _inicio_trimestre, _inicio_trimestre_anterior e _inicio_mes_anterior
# movidos pra utils/utils_curtailment.py (G.5 + G.7) — importados no
# topo. Mesma família de helpers temporais que _inicio_mes (já em
# utils desde antes). Scripts em scripts/ ainda têm cópias locais —
# TODO sessão futura: importar de utils.


# =============================================================================
# CSS dos KPIs custom + helper (decisão 5.21 — Bebas Neue é all-caps por
# design, então "MWmed"/"MWh" precisa de unidade em Inter mixed-case
# separada do número em Bebas)
# =============================================================================

_CSS_KPI_CURT = """
<style>
.curt-kpi-card {
    background: #F5F1E8;
    border: 2px solid #1A1A1A;
    padding: 8px 12px;
    border-radius: 0;
    text-align: center;
    width: 100%;
    box-sizing: border-box;
    min-height: 6rem;
    display: flex;
    flex-direction: column;
    justify-content: center;
}
.curt-kpi-label {
    font-family: 'Inter', sans-serif;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #1A1A1A;
    font-weight: 700;
    line-height: 1.2;
    word-break: keep-all;
    overflow-wrap: normal;
    hyphens: none;
}
.curt-kpi-value {
    display: flex;
    align-items: baseline;
    justify-content: center;
    margin-top: 0.5rem;
}
.curt-kpi-value-num {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 1.45rem;
    color: #1A1A1A;
    letter-spacing: 0.02em;
    line-height: 1.1;
}
.curt-kpi-value-unit {
    font-family: 'Inter', sans-serif;
    font-size: 0.85rem;
    color: #1A1A1A;
    font-weight: 600;
    margin-left: 0.4rem;
}

/* Variantes de cor pra cards KPI (sub-aba "Por estado").
   Default (sem modifier class) mantém preto BAUHAUS_BLACK. */
.curt-kpi-card.variante-vermelho .curt-kpi-value-num { color: #D62828; }
.curt-kpi-card.variante-azul .curt-kpi-value-num { color: #2A6F97; }
.curt-kpi-card.variante-cinza .curt-kpi-value-num { color: #4A4A4A; }

/* Tabs internas (st.tabs) — fix de cor pra legibilidade.
   Nota: seletor .stTabs é global, mas como o CSS só muda COR DE TEXTO
   (não layout/tamanho/padding), o impacto em outras abas que usem
   st.tabs é benéfico (legibilidade) ou neutro. */
.stTabs [data-baseweb="tab"] p {
    color: #1A1A1A !important;
    font-weight: 500;
}
.stTabs [data-baseweb="tab"][aria-selected="true"] p {
    color: #D62828 !important;
    font-weight: 700;
}
</style>
"""


def _render_kpi_curt(
    label: str, num: str, unit: str = "", variante: str = "default",
) -> str:
    """Renderiza card KPI Bauhaus.

    variante: "default" (preto, padrão da visão geral), "vermelho", "azul",
    "cinza" — controla cor do número via CSS modifier class.
    """
    unit_html = (
        f'<span class="curt-kpi-value-unit">{unit}</span>' if unit else ""
    )
    classe = "curt-kpi-card"
    if variante != "default":
        classe += f" variante-{variante}"
    return (
        f'<div class="{classe}">'
        f'<div class="curt-kpi-label">{label}</div>'
        f'<div class="curt-kpi-value">'
        f'<span class="curt-kpi-value-num">{num}</span>{unit_html}'
        f'</div></div>'
    )


def _placeholder_em_construcao():
    """Placeholder elegante pras sub-abas vazias (Por estado / Por usina /
    Por grupo) — substitui st.info() por div Inter italic centralizado."""
    st.markdown(
        '<div style="font-family:\'Inter\', sans-serif; '
        'font-size:0.95rem; color:#6B6B6B; font-style:italic; '
        'padding: 2rem 0; text-align:center;">'
        'Sub-aba em construção — disponível em breve.'
        '</div>',
        unsafe_allow_html=True,
    )


# =============================================================================
# Helper de período (versão simplificada de app.py:638 — sem single-day mode).
# Decisão 5.6 documenta o helper original. Versão completa fica no app.py por
# enquanto pra evitar circular import. Refator pra módulo compartilhado é
# roadmap futuro.
# =============================================================================


def _render_period_controls_curt(
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
):
    """N botões de preset + 2 date_inputs em 1 linha. Botão primary
    (amarelo via CSS global do app.py) quando preset ativo.

    Cada tuple do preset: (label, data_ini_fn, is_max).
    - data_ini_fn(max_d) -> date: retorna data_ini esperada do preset.
    - is_max=True: data_ini = min_d (data_ini_fn pode ser None).

    Parâmetros relativos ao limite mínimo:
    - min_d: limite VISUAL dos date_inputs (clamp aplicado ao setar
      state). Tipicamente data_ini do cache atual.
    - hard_min: limite ABSOLUTO do dataset (ex: date(2022, 1, 1) pra
      curtailment ONS). Usado SÓ pra computar target_real do preset
      "Máx" sem clamp — necessário pra detectar pedido de expansão.
      Default min_d se None (sem expansão sob demanda).

    Expansão sob demanda (curtailment Visão Geral):
    - cache_data_ini_atual: data_ini do cache de janela ampla atual.
    - on_expansion_request(label): callback chamado quando preset clicado
      pede data_ini ANTERIOR ao cache atual (= precisa baixar mais ONS).
      Se não passado (ou cache_data_ini_atual=None), comportamento legado:
      clamp normal em min_d sem confirmação.
    """
    data_ini_atual = st.session_state[session_key_ini]
    data_fim_atual = st.session_state[session_key_fim]

    # Detecta preset ativo: data_fim ancorada em max_d e data_ini bate com
    # data_ini_target (pós-clamp). Clamp em min_d aplicado simetricamente
    # aqui e no clique pra que botão amarelo destaque mesmo após clamp.
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
    cols = st.columns([1] * n + [0.3, 1.4, 1.4])

    for i, (label, data_ini_fn, is_max) in enumerate(presets):
        with cols[i]:
            tipo = "primary" if label == preset_atual else "secondary"

            # Target REAL (sem clamp em min_d) — necessário pra detectar
            # pedido de expansão. Pra "Máx" usa hard_min (= limite absoluto
            # do dataset, ex 2022-01-01 pra curtailment); fallback min_d
            # mantém comportamento legado quando hard_min não é passado.
            _floor = hard_min if hard_min is not None else min_d
            if is_max:
                target_real = _floor
            else:
                target_real = data_ini_fn(max_d)

            cache_cobre = (
                cache_data_ini_atual is None
                or target_real >= cache_data_ini_atual
            )

            # Tooltip dinâmico: depende se cache atual cobre o target.
            # Hardcode dos labels "24M"/"Máx" porque são convenções do
            # projeto (e o helper já é específico do curtailment).
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
                # Expansão sob demanda: target_real ANTERIOR ao cache
                # atual → callback decide (modal ou outro). Helper
                # retorna SEM tocar em data_ini/data_fim — caller propaga.
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

    with cols[n + 1]:
        st.date_input(
            "Data inicial", min_value=min_d, max_value=max_d,
            key=session_key_ini,
            format="DD/MM/YYYY",
        )
    with cols[n + 2]:
        st.date_input(
            "Data final", min_value=min_d, max_value=max_d,
            key=session_key_fim,
            format="DD/MM/YYYY",
        )


# =============================================================================
# Dropdown "Entidade" (Visão geral) — Caminho 3:
# Grupos sempre todos do Excel (independente da fonte); unidades filtradas
# pela fonte. Lista vem do Excel (Fonte A), não do df pós-rateio (Fonte B):
# usuário precisa ver unidades cadastradas mesmo as sem curtailment na
# janela 15M.
# =============================================================================

_GRUPOS_PRIORIZADOS = (
    "Alupar", "Auren", "Copel", "CPFL",
    "Engie", "Eneva", "Equatorial", "Neoenergia",
)


@st.cache_data(show_spinner=False)
def _construir_opcoes_entidade(fonte_label: str) -> list:
    """Lista de itens do dropdown Entidade da Visão Geral.

    - "Brasil (SIN)" sempre primeiro.
    - Grupos: SEMPRE todos do Excel (Caminho 3), priorizadas no topo,
      restante alfabético. Ordem independente da fonte.
    - Unidades: filtradas pela fonte selecionada (só Solar OU só Eólica).
    - Display invertido: "Auren (Grupo)" / "Tacaratu (Unidade)" — nome em
      primeiro plano (decisão de design da sessão atual).
    """
    df_g = carregar_grupos_excel()
    if len(df_g) == 0:
        return ["Brasil (SIN)"]

    todos_grupos = sorted(df_g["PROPRIETARIO"].dropna().unique())
    prio = [g for g in _GRUPOS_PRIORIZADOS if g in todos_grupos]
    restante = sorted(g for g in todos_grupos if g not in prio)
    grupos_ordenados = prio + restante

    fonte_code = "SOLAR" if fonte_label == "Solar" else "EOLICA"
    unidades = sorted(
        df_g[df_g["FONTE"] == fonte_code]["NOME_USINA"].dropna().unique()
    )

    return (
        ["Brasil (SIN)"]
        + [f"{g} (Grupo)" for g in grupos_ordenados]
        + [f"{u} (Unidade)" for u in unidades]
    )


def _parse_entidade(entidade: str):
    """Retorna (filtro_grupo, filtro_unidade, titulo_contexto)."""
    if entidade == "Brasil (SIN)":
        return (None, None, "SIN")
    if entidade.endswith(" (Grupo)"):
        nome = entidade[: -len(" (Grupo)")]
        return (nome, None, nome.upper())
    if entidade.endswith(" (Unidade)"):
        nome = entidade[: -len(" (Unidade)")]
        return (None, nome, nome.upper())
    return (None, None, "SIN")  # fallback defensivo


# =============================================================================
# Modal de expansão da janela ampla — padrão @st.dialog (decisão 5.17).
# Disparado pelo helper de presets quando user clica 24M ou Máx e o cache
# atual não cobre. Confirmar marca curt_janela_modo, próximo render baixa
# meses extras (cache disco persiste pra sessões futuras).
# =============================================================================


@st.dialog("Carregar mais histórico de curtailment")
def _confirmar_expansao_curt(modo_alvo: str):
    """Modal de confirmação pra expandir janela ampla.

    modo_alvo: "24m" → 24 meses (~3 min)
               "max" → desde 01/01/2022 (~5-7 min)
    """
    if modo_alvo == "24m":
        titulo = "Carregar 24 meses de histórico?"
        custo = "~3 min na 1ª vez (instantâneo nas próximas)"
    else:  # "max"
        titulo = "Carregar histórico completo (desde 01/01/2022)?"
        custo = "~5-7 min na 1ª vez (instantâneo nas próximas)"

    st.markdown(f"**{titulo}**  \n{custo}")
    st.caption(
        "Os dados ficam em cache local — sessões futuras carregam do "
        "disco em ~1s, sem novo download."
    )
    col1, col2 = st.columns(2)
    if col1.button("Cancelar", use_container_width=True):
        st.rerun()
    if col2.button("Carregar", type="primary", use_container_width=True):
        st.session_state["curt_janela_modo"] = modo_alvo
        st.rerun()


# =============================================================================
# Sub-aba: Visão geral
# =============================================================================


def _render_visao_geral(
    df: pd.DataFrame,
    granularidade: str,
    granularidade_ui: str,
    fonte_label: str,
    data_ini: date,
    data_fim: date,
    *,
    filtro_unidade: Optional[str] = None,
    filtro_grupo: Optional[str] = None,
    titulo_contexto: Optional[str] = None,
):
    """KPIs + série temporal de % curtailment por tipo de restrição.

    df: DataFrame COM rateio aplicado e JÁ filtrado por janela e fonte
        conforme escolha do usuário nos controles globais.

    Filtros opcionais (modo drill-down — SPEC §8):
        filtro_unidade: se passado, filtra df por NOME_USINA_DASH == valor.
        filtro_grupo:   se passado, filtra df por PROPRIETARIO == valor.
        Apenas um dos dois pode ser não-nulo (ValueError se ambos).
        Quando ambos None, comportamento é 100% idêntico ao chamado original.

    titulo_contexto: rótulo do escopo no título Bauhaus do gráfico.
        "SIN" no padrão Brasil; nome do grupo/unidade.upper() em modo
        drill-down. Default "SIN" se None.
    """
    if filtro_unidade is not None and filtro_grupo is not None:
        raise ValueError(
            "filtro_unidade e filtro_grupo são mutuamente exclusivos — "
            "passar apenas um (ou nenhum)."
        )

    if filtro_unidade is not None:
        df = df[df["NOME_USINA_DASH"] == filtro_unidade]
    elif filtro_grupo is not None:
        df = df[df["PROPRIETARIO"] == filtro_grupo]

    # Guard de df vazio ANTES de renderizar título/tag — evita "header
    # órfão" tipo "CURTAILMENT · SOLAR · COPEL" seguido só de warning
    # (Copel só tem Eólica). Mensagem específica em modo drill-down.
    if len(df) == 0:
        if filtro_grupo is not None:
            st.warning(
                f"O grupo {filtro_grupo} não tem unidades em "
                f"{fonte_label} nesse período."
            )
        elif filtro_unidade is not None:
            st.warning(
                f"A unidade {filtro_unidade} não tem dados em "
                f"{fonte_label} nesse período."
            )
        else:
            st.warning("Sem dados de curtailment no período selecionado.")
        return

    # =========================================================================
    # Título Bauhaus do gráfico (mesmo padrão Carga/Geração)
    # =========================================================================
    periodo_str = (
        f"{data_ini.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}"
    )
    contexto_label = (titulo_contexto or "SIN").upper()
    st.markdown(
        f'<div style="display:flex; justify-content:space-between; '
        f'align-items:baseline; '
        f"font-family:'Bebas Neue', sans-serif; "
        f'font-size:1.1rem; letter-spacing:0.08em; color:#1A1A1A; '
        f'margin: 2.6rem 0 0.3rem 0; padding-bottom:3px; '
        f'border-bottom: 2px solid #1A1A1A;">'
        f'<span>CURTAILMENT POR TIPO DE RESTRIÇÃO · {fonte_label.upper()} · {contexto_label}</span>'
        f'<span>{periodo_str}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # =========================================================================
    # Tag de granularidade (decisão 5.22)
    # =========================================================================
    st.markdown(
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.9rem; color:#1A1A1A; font-weight:500; '
        f'letter-spacing:0.04em; margin:0 0 0.5rem 0;">'
        f'{granularidade_ui} · % curtailment'
        f'</div>',
        unsafe_allow_html=True,
    )

    # =========================================================================
    # Série temporal: barras empilhadas por razão (ENE / CNF / REL)
    # =========================================================================
    df_p = adicionar_chave_periodo(df, granularidade)
    s = serie_temporal(df_p)

    if len(s) == 0:
        # Caso patológico: df não-vazio (passou guard acima) mas série
        # temporal vazia. Improvável; manter como fallback defensivo.
        st.warning("Sem dados de curtailment no período selecionado.")
        return

    fig = go.Figure()
    razoes_ordem = ["ENE", "CNF", "REL"]
    for razao in razoes_ordem:
        col_pct = f"PCT_{razao}"
        if col_pct not in s.columns:
            continue
        cor = CORES_RAZAO[razao]
        label_razao = LABELS_RAZAO[razao]
        # Padded label pra alinhamento monospace no hover unified
        label_fix = label_razao.ljust(15).replace(" ", "&nbsp;")
        fig.add_trace(go.Bar(
            x=s["PERIODO_LABEL"],
            y=s[col_pct] * 100,
            name=label_razao,
            marker=dict(color=cor),
            hovertemplate=(
                f'<span style="color:{cor}; font-weight:700;">'
                f'{label_fix}</span>'
                '&nbsp;&nbsp;'
                '<span style="color:#1A1A1A;">%{y:.2f}%</span>'
                '<extra></extra>'
            ),
        ))

    # TODO(curtailment): xaxis.type="category" funciona bem em Mensal/
    # Trimestral (poucos pontos), mas vai ficar amontoado em
    # Diária + 12M (~365 labels). Resolver na próxima iteração com
    # detecção condicional: granularidade=="DIARIO" → datetime + hoverformat
    # como na Geração; senão → category. Issue conhecida documentada.
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
            type="category",  # PERIODO_LABEL é string ("Abr/25" etc.)
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
            ticksuffix="%",
            tickformat=",.1f",
        ),
        font=dict(family="Inter, sans-serif", size=12),
    )

    st.plotly_chart(
        fig, use_container_width=True, config={"displaylogo": False},
    )

    # =========================================================================
    # Expander glossário — perto do gráfico (UX: dúvida surge no contexto visual)
    # =========================================================================
    with st.expander("ⓘ Como é calculado"):
        st.markdown(
            "**Metodologia adotada**: definição pública do ONS, conforme "
            "dashboard oficial em https://www.ons.org.br/Paginas/faq_curtailment.aspx "
            "(Acompanhamento das Restrições de Geração UEE/UFV).\n\n"
            "**Numerador**: GNRa (Geração Não Realizada apurada) por razão "
            "ou total, em MWh.\n\n"
            "**Denominador**: geração potencial total (MWh) = "
            "`Geração Verificada + GNRa total` = `Output + (CNF + ENE + REL)`. "
            "Representa o que a usina poderia ter gerado se não houvesse restrição.\n\n"
            "**% Curtailment** = (CNF + ENE + REL) / (Output + CNF + ENE + REL)\n\n"
            "**Decomposição por razão**: cada razão é exibida com o **mesmo "
            "denominador**, então `% ENE + % CNF + % REL = % Curtailment` "
            "(matematicamente consistente).\n\n"
            "**Tipos de restrição**:\n"
            "- **ENE** (energético): sobreoferta de energia no sistema\n"
            "- **CNF** (confiabilidade): restrição por confiabilidade operativa\n"
            "- **REL** (elétrico/indisponibilidade externa): restrição em "
            "instalações externas (Rede Básica/DITs)\n"
            "- **PAR** (parecer de acesso): restrição contratual prévia "
            "(excluído por padrão)\n\n"
            "**Nota sobre ressarcimento (REN 1030/2022)**: o ressarcimento "
            "financeiro segue regras específicas da ANEEL conforme razão "
            "(REL ressarcível, ENE não-ressarcível, CNF parcialmente). "
            "Esse dashboard mostra volume físico de curtailment, não "
            "quantifica ressarcimento financeiro.\n\n"
            "**Comparação com Power BI público do ONS**: pequenas diferenças "
            "(~2-3%) podem ocorrer ao comparar com o Power BI público do ONS. "
            "O dashboard consome o dataset oficial de Constrained-off (ONS "
            "Dados Abertos, conforme REN 1030/2022), idêntico ao consultado "
            "pelo Power BI ONS. O gap residual é inerente a possíveis "
            "cruzamentos adicionais ou refinamentos na apresentação do "
            "Power BI ONS, e não pode ser eliminado apenas no dashboard."
        )

    # =========================================================================
    # Botão download CSV (alinhado à direita)
    # =========================================================================
    df_export = s.copy()
    # Multiplicar PCT_* por 100 pra exportar como % (ex: 5,32% em vez de 0,0532)
    for col in [c for c in df_export.columns if c.startswith("PCT_")]:
        df_export[col] = df_export[col] * 100

    rename_csv = {
        "PERIODO_LABEL":         "Período",
        "PERIODO_INICIO":        "Início",
        "PERIODO_FIM":           "Fim",
        "OUTPUT_MWH":            "Output (MWh)",
        "REF_FINAL_MWH":         "Ref Final (MWh)",
        "FRUSTRADO_TOTAL_MWH":   "Frustrado Total (MWh)",
        "FRUSTRADO_REL_MWH":     "Frustrado REL (MWh)",
        "FRUSTRADO_CNF_MWH":     "Frustrado CNF (MWh)",
        "FRUSTRADO_ENE_MWH":     "Frustrado ENE (MWh)",
        "PCT_TOTAL":             "% Curtailment",
        "PCT_REL":               "% Elétrico",
        "PCT_CNF":               "% Confiabilidade",
        "PCT_ENE":               "% Energético",
    }
    df_export = df_export.rename(columns=rename_csv)
    csv = df_export.to_csv(
        index=False, sep=";", decimal=",",
    ).encode("utf-8-sig")

    fonte_slug = (
        fonte_label.lower()
        .replace("ó", "o")
        .replace("â", "a")
    )
    filename = (
        f"curtailment_{granularidade.lower()}_{fonte_slug}_"
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
# Sub-aba: Por unidade — SPEC §6 (C.1: Total apenas, sem hover, sem click)
# =============================================================================

_CSS_TABELA_UNIDADES = """
<style>
.curt-tab-unid-wrap {
    max-height: 600px;
    overflow-y: auto;
    border: 2px solid #1A1A1A;
    background: #F5F1E8;
    margin: 0.5rem 0 1rem 0;
    /* Scrollbar Bauhaus (Firefox) */
    scrollbar-width: auto;
    scrollbar-color: #1A1A1A #F5F1E8;
}
/* Scrollbar Bauhaus (Chrome/Edge/Safari) — escopada, não vaza pra outros containers */
.curt-tab-unid-wrap::-webkit-scrollbar {
    width: 12px;
}
.curt-tab-unid-wrap::-webkit-scrollbar-track {
    background: #F5F1E8;
}
.curt-tab-unid-wrap::-webkit-scrollbar-thumb {
    background: #1A1A1A;
    border: 2px solid #F5F1E8;
}
.curt-tab-unid {
    width: 100%;
    border-collapse: collapse;
    /* Larguras fixas — header maior do mês corrente ("até XX/XX") não
       distorce as 3 colunas numéricas (decisão Smoke 2 da Sessão C.1). */
    table-layout: fixed;
    font-family: 'Inter', sans-serif;
    font-size: 0.85rem;
}
/* G.7 (10 colunas): 15% Unidade + 15% Grupo + 8.75% × 8 numéricas
   (3 meses + 4 trimestres + LTM) = 100%. Em viewport 1400px (G.4):
   col-num ≈ 122px, label cols ≈ 210px. */
.curt-tab-unid th:nth-child(1), .curt-tab-unid td:nth-child(1) { width: 15%; }
.curt-tab-unid th:nth-child(2), .curt-tab-unid td:nth-child(2) { width: 15%; }
.curt-tab-unid th.col-num, .curt-tab-unid td.col-num { width: 8.75%; }
/* Linha vertical sutil entre coluna do penúltimo mês (FEV) e trimestre
   corrente (2T 26) — separador conceitual mês↔trimestre. Cor #A8A8A8
   é cinza médio: contrasta o suficiente pra marcar a transição em fundo
   cream Bauhaus #F5F1E8 sem ficar poluída. Espessura 2px alinha com o
   padrão Bauhaus do app (bordas pretas 2px nos botões/cards) — cor
   sutil + espessura padrão = presente sem competir. Calibrada no smoke
   test do COMMIT 3 (1px era fino demais; #C8C8C8 era invisível). */
.curt-tab-unid th.col-divisor,
.curt-tab-unid td.col-divisor {
    /* !important pra vencer reset CSS global do Streamlit que aplica
       border: 0 em <td>/<th> com specificity igual ou superior. Sem
       !important a borda some apesar da regra estar válida. */
    border-left: 2px solid #A8A8A8 !important;
}
.curt-tab-unid thead th {
    position: sticky;
    top: 0;
    background: #1A1A1A;
    color: #F5F1E8;
    font-family: 'Inter', sans-serif;
    font-size: 0.85rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    text-align: left;
    padding: 10px 14px;
    border-bottom: 2px solid #1A1A1A;
    z-index: 10;
}
.curt-tab-unid thead th.col-num {
    text-align: right;
}
/* Sufixo "(até DD/MM)" do mês corrente em 2ª linha do header — menor,
   normal weight, não-uppercase pra contrastar com o "MAI/26" principal. */
.curt-tab-unid thead th .col-sufixo {
    display: block;
    font-size: 0.7rem;
    font-weight: 400;
    text-transform: none;
    letter-spacing: 0;
    margin-top: 2px;
    opacity: 0.85;
}
/* G.7: 2ª linha do header com MESMO peso visual do label principal
   (vs col-sufixo que é sutil). Usado pelo período LTM ("Últimos" +
   "12 meses") onde a 2ª linha é descrição ESSENCIAL da janela, não
   detalhe sufixado. font-size 0.85rem == thead th default → mesma
   hierarquia visual. line-height 1.05 compacta a altura pra não
   estourar o header. */
.curt-tab-unid thead th .col-sub-label {
    display: block;
    margin-top: 2px;
    font-family: 'Inter', sans-serif;
    font-weight: 700;
    font-size: 0.85rem;
    line-height: 1.05;
    letter-spacing: 0.06em;
    text-transform: uppercase;
}
.curt-tab-unid tbody td {
    padding: 10px 14px;
    border-bottom: 1px solid #E8E3D4;
    color: #1A1A1A;
    vertical-align: top;
    /* Trunca nomes muito longos com ellipsis em vez de quebrar (table-layout
       fixed obrigaria quebra automática feia). */
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.curt-tab-unid tbody td.col-num {
    font-family: 'JetBrains Mono', 'Courier New', monospace;
    text-align: right;
    white-space: nowrap;
}
.curt-tab-unid tbody td.col-prop-other {
    color: #6B6B6B;
    font-style: italic;
}
.curt-tab-unid tbody tr:last-child td {
    border-bottom: none;
}
</style>
"""

# Display do PROPRIETARIO "outros" (SPEC §6.6).
# 2 variantes coexistem na base atual: "Other" (do Excel — proprietário
# cadastrado como genérico) e "Other (sem mapeamento)" (gerado por
# aplicar_rateio quando linha do ONS não casa com nenhum nome do Excel).
# Match por prefixo cobre ambos + variantes futuras ("Other (excluído)",
# etc.) sem atualizar constante. Trade-off: se aparecer um proprietário
# legítimo cujo nome começa com "Other" (improvável; análise atual
# confirma que não ocorre), entraria no balde.
_PROP_OTHER_LABEL = "Outros"


# Razões de restrição expostas como filtro nas sub-abas "Por usina" e
# "Por grupo" (G.6). Ordem ENE→CNF→REL alinha com a ordem das cores
# Bauhaus do gráfico da Visão Geral (vermelho/amarelo/azul). PAR é
# excluído por convenção do projeto (vide RAZOES_OPERATIVAS em utils).
_RAZOES_FILTRO = (
    ("ENE", "Energético"),
    ("CNF", "Confiabilidade"),
    ("REL", "Elétrico"),
)


def _is_proprietario_outros(prop) -> bool:
    """True se o PROPRIETARIO deve cair no balde 'Outros / Não classificado'."""
    if prop is None or pd.isna(prop):
        return True
    return str(prop).strip().lower().startswith("other")


@st.cache_data(show_spinner=False)
def _calcular_linhas_unidade(
    df: pd.DataFrame,
    razoes_marcadas: tuple = ("CNF", "ENE", "REL"),
) -> list:
    """Calcula pct_total nos 7 períodos pra cada unidade do df.

    Decisões de produto:
    - Suprime unidades sem dado em NENHUM dos 7 períodos (todas pcts None).
    - Ordenação: decrescente por pct trimestre corrente (G.5); unidades sem
      dado no trimestre corrente vão pro fim em ordem alfabética.
    - PROPRIETARIO display fica pro caller (este helper retorna o valor cru).
    - razoes_marcadas (G.6): tuple SORTED de razões a contar. Default
      ("CNF", "ENE", "REL") preserva comportamento original (todas
      operativas marcadas). Tupla vazia equivale a "sem filtro de razão"
      (bypass) — usada SÓ em validação bit-a-bit (script
      validar_filtro_razoes.py); em produção o caller intercepta vazio
      e mostra mensagem "selecione pelo menos uma".

    Filter de razão (G.6): em vez de dropar linhas com RAZAO fora de
    razoes_marcadas (que removeria as linhas RAZAO=NaN onde mora o
    OUTPUT puro, subestimando o denominador), zera FRUSTRADO_MWH nas
    razões excluídas. Preserva OUTPUT íntegro, ajusta só o numerador.

    Cacheado: o cálculo é determinístico em (df, razoes_marcadas), e
    roda ~2160× pct_no_periodo (~270 unidades × 8 períodos pós-G.7:
    3 meses + 4 trimestres + 1 LTM). Cache evita repetir em reruns
    que não mudam (df_filtrado, razoes_marcadas).
    """
    if len(df) == 0 or df["DATA"].isna().all():
        return []

    # G.6: filter de razão por zerar FRUSTRADO_MWH (não dropar linhas)
    if razoes_marcadas:
        df = df.copy()
        mask_excluir = (
            df["RAZAO"].notna() & ~df["RAZAO"].isin(razoes_marcadas)
        )
        df.loc[mask_excluir, "FRUSTRADO_MWH"] = 0.0

    max_d = pd.Timestamp(df["DATA"].max()).date()
    periodos = calcular_periodos_curtailment(max_d)

    linhas = []
    for nome_usina, sub in df.groupby("NOME_USINA_DASH"):
        prop = sub["PROPRIETARIO"].iloc[0]
        pcts = {
            k: pct_no_periodo(sub, p["ini"], p["fim"])
            for k, p in periodos.items()
        }
        if all(v is None for v in pcts.values()):
            continue
        linhas.append({
            "unidade": nome_usina,
            "proprietario": prop,
            # 3 meses
            "mes_corrente":   pcts["mes_corrente"],
            "mes_anterior":   pcts["mes_anterior"],
            "penultimo":      pcts["penultimo"],
            # 4 trimestres (G.5)
            "tri_corrente":   pcts["tri_corrente"],
            "tri_anterior_1": pcts["tri_anterior_1"],
            "tri_anterior_2": pcts["tri_anterior_2"],
            "tri_anterior_3": pcts["tri_anterior_3"],
            # 1 LTM (G.7)
            "ultimos_12m":    pcts["ultimos_12m"],
        })

    # G.5: ordenação por trimestre corrente (não mais mês corrente).
    # Trimestre é métrica mais robusta pra ranking — 1 mês isolado pode
    # ter ruído pontual, trimestre suaviza. Edge: max_d cai no dia 1 do
    # trimestre (1/jan, 1/abr, 1/jul, 1/out) → tri_corrente vira 1 dia,
    # ordenação pode ficar ~aleatória nesse dia específico (aceito).
    linhas.sort(key=lambda r: (
        r["tri_corrente"] is None,
        -(r["tri_corrente"] or 0.0),
        r["unidade"],
    ))
    return linhas


def _montar_html_tabela_unidades(periodos: dict, linhas: list) -> str:
    """Monta string HTML da tabela. CSS em _CSS_TABELA_UNIDADES.

    Pós-G.7: 10 colunas (Unidade + Grupo + 3 meses + 4 trimestres + LTM).
    Classe `col-divisor` no PRIMEIRO trimestre (tri_corrente, 6ª coluna)
    marca a transição visual mês→trimestre via border-left no CSS.
    NÃO há separador entre 3T 25 e Últimos 12m — decisão G.7 pra evitar
    tabela "compartimentada demais".
    """
    rows_html = []
    for r in linhas:
        is_other = _is_proprietario_outros(r["proprietario"])
        prop_class = "col-prop-other" if is_other else ""
        prop_label = _PROP_OTHER_LABEL if is_other else r["proprietario"]
        rows_html.append(
            '<tr>'
            f'<td>{r["unidade"]}</td>'
            f'<td class="{prop_class}">{prop_label}</td>'
            f'<td class="col-num">{_fmt_pct_curt(r["mes_corrente"])}</td>'
            f'<td class="col-num">{_fmt_pct_curt(r["mes_anterior"])}</td>'
            f'<td class="col-num">{_fmt_pct_curt(r["penultimo"])}</td>'
            f'<td class="col-num col-divisor">{_fmt_pct_curt(r["tri_corrente"])}</td>'
            f'<td class="col-num">{_fmt_pct_curt(r["tri_anterior_1"])}</td>'
            f'<td class="col-num">{_fmt_pct_curt(r["tri_anterior_2"])}</td>'
            f'<td class="col-num">{_fmt_pct_curt(r["tri_anterior_3"])}</td>'
            f'<td class="col-num">{_fmt_pct_curt(r["ultimos_12m"])}</td>'
            '</tr>'
        )

    def _header_cell(p: dict, divisor: bool = False) -> str:
        # Mutex: segunda_linha (col-sub-label, mesmo peso) tem precedência
        # sobre sufixo_parcial (col-sufixo, sutil). Helper escolhe um dos
        # dois conforme presença no dict do período.
        extra_html = ""
        if p.get("segunda_linha"):
            extra_html = (
                f'<span class="col-sub-label">{p["segunda_linha"]}</span>'
            )
        elif p.get("sufixo_parcial"):
            extra_html = (
                f'<span class="col-sufixo">{p["sufixo_parcial"]}</span>'
            )
        classes = "col-num col-divisor" if divisor else "col-num"
        return f'<th class="{classes}">{p["label_curto"]}{extra_html}</th>'

    headers = (
        '<thead><tr>'
        '<th>Unidade</th>'
        '<th>Grupo</th>'
        f'{_header_cell(periodos["mes_corrente"])}'
        f'{_header_cell(periodos["mes_anterior"])}'
        f'{_header_cell(periodos["penultimo"])}'
        f'{_header_cell(periodos["tri_corrente"], divisor=True)}'
        f'{_header_cell(periodos["tri_anterior_1"])}'
        f'{_header_cell(periodos["tri_anterior_2"])}'
        f'{_header_cell(periodos["tri_anterior_3"])}'
        f'{_header_cell(periodos["ultimos_12m"])}'
        '</tr></thead>'
    )
    body = f'<tbody>{"".join(rows_html)}</tbody>'
    return (
        '<div class="curt-tab-unid-wrap">'
        '<table class="curt-tab-unid">'
        f'{headers}{body}'
        '</table></div>'
    )


def _render_por_unidade(
    df: pd.DataFrame,
    razoes_marcadas: tuple = ("CNF", "ENE", "REL"),
) -> None:
    """Sub-aba "Por usina" — tabela de unidades com curtailment nos
    8 períodos pós-G.7 (3 meses + 4 trimestres + 1 LTM).

    razoes_marcadas (G.6): tuple SORTED de razões a contar. Caller
    intercepta vazio antes de chamar — aqui assume tupla não vazia.

    C.1: só coluna Total, sem seletor de razão, sem hover, sem click.
    G.6: filtro de razão via checkboxes (ENE/CNF/REL).
    Próximas sub-fases: C.3 tooltip rico, C.4 click.
    """
    if len(df) == 0 or df["DATA"].isna().all():
        st.info("Sem dados pra esta combinação de filtros.")
        return

    max_d = pd.Timestamp(df["DATA"].max()).date()
    periodos = calcular_periodos_curtailment(max_d)
    linhas = _calcular_linhas_unidade(df, razoes_marcadas)

    if not linhas:
        st.info(
            "Nenhuma unidade com curtailment registrado nos 8 períodos analisados."
        )
        return

    st.markdown(
        '<div style="font-family:\'Inter\', sans-serif; '
        'font-size:0.85rem; color:#6B6B6B; font-style:italic; '
        'margin:0.6rem 0 0.5rem 0;">'
        'Cada linha é uma unidade geradora com algum corte registrado pelo '
        'ONS em pelo menos um dos 8 períodos (3 meses + 4 trimestres + LTM). '
        'Unidades sem ocorrências de curtailment não aparecem. % calculado '
        'sobre geração potencial da unidade no período. Ordenado por % do '
        'trimestre corrente.'
        '</div>',
        unsafe_allow_html=True,
    )

    st.markdown(_CSS_TABELA_UNIDADES, unsafe_allow_html=True)
    st.markdown(
        _montar_html_tabela_unidades(periodos, linhas),
        unsafe_allow_html=True,
    )


# =============================================================================
# Sub-aba: Por estado (mapa choropleth)
# =============================================================================


@st.cache_data
def _carregar_geojson_estados() -> dict:
    """Carrega GeoJSON simplificado dos 27 estados BR (data/curtailment/brazil_states.geojson).

    Cache por sessão Streamlit evita re-leitura/parse do arquivo a cada rerun.
    Chave de join: properties.sigla casa direto com df_post.UF (12/12 match).
    """
    import json
    from pathlib import Path
    return json.loads(
        Path("data/curtailment/brazil_states.geojson").read_text(encoding="utf-8")
    )


def _nome_estado(uf: str) -> str:
    """Retorna nome do estado em português (ex: 'BA' → 'Bahia').

    Usa GeoJSON cacheado via _carregar_geojson_estados.
    Fallback: retorna a própria UF se não encontrar.
    """
    gj = _carregar_geojson_estados()
    for f in gj["features"]:
        if f["properties"]["sigla"] == uf:
            return f["properties"]["name"]
    return uf


def _calcular_kpis_escopo(df: pd.DataFrame) -> dict:
    """Calcula % curtailment + decomposição por razão (fórmula ONS).

        % X = sum(FRUSTRADO_X) / (sum(FRUSTRADO_TOTAL) + sum(OUTPUT))

    Retorna ratios 0-1 (não percentuais 0-100) — compatível com
    _fmt_pct_curt que multiplica por 100 ao formatar.

    Garantia matemática: pct_ene + pct_cnf + pct_rel == pct_total.
    """
    fr_total = float(df["FRUSTRADO_MWH"].sum())
    ot_total = float(df["OUTPUT_MWH"].sum())
    denom = fr_total + ot_total
    if denom <= 0:
        return {"pct_total": 0.0, "pct_ene": 0.0, "pct_cnf": 0.0, "pct_rel": 0.0}
    fr_ene = float(df.loc[df["RAZAO"] == "ENE", "FRUSTRADO_MWH"].sum())
    fr_cnf = float(df.loc[df["RAZAO"] == "CNF", "FRUSTRADO_MWH"].sum())
    fr_rel = float(df.loc[df["RAZAO"] == "REL", "FRUSTRADO_MWH"].sum())
    return {
        "pct_total": fr_total / denom,
        "pct_ene":   fr_ene   / denom,
        "pct_cnf":   fr_cnf   / denom,
        "pct_rel":   fr_rel   / denom,
    }


def _render_kpis_por_estado(
    df_filtrado: pd.DataFrame,
    uf_selecionada: Optional[str],
    fonte_label: str,
) -> None:
    """Renderiza row de KPIs reativos por estado.

    - uf_selecionada=None  → 4 cards do Brasil agregado.
    - uf_selecionada='XX'  → 5 cards (4 do estado + 1 do Brasil pra comparação).

    Cores Bauhaus:
      - Card 1 (% Curtailment do escopo): vermelho — destaque principal
      - Cards 2/3/4 (ENE/CNF/REL): azul — decomposição secundária
      - Card 5 (% Brasil, só em modo estado): cinza — referência
    """
    kpis_br = _calcular_kpis_escopo(df_filtrado)

    if uf_selecionada is None:
        label_total = "Curtailment Brasil"
        cols = st.columns(4)
        valores = kpis_br
    else:
        df_estado = df_filtrado[df_filtrado["UF"] == uf_selecionada]
        valores = _calcular_kpis_escopo(df_estado)
        label_total = f"Curtailment {uf_selecionada}"
        cols = st.columns(5)

    with cols[0]:
        st.markdown(
            _render_kpi_curt(
                label_total, _fmt_pct_curt(valores["pct_total"]),
                variante="vermelho",
            ),
            unsafe_allow_html=True,
        )
    with cols[1]:
        st.markdown(
            _render_kpi_curt(
                "Energético<br>(ENE)", _fmt_pct_curt(valores["pct_ene"]),
                variante="azul",
            ),
            unsafe_allow_html=True,
        )
    with cols[2]:
        st.markdown(
            _render_kpi_curt(
                "Confiabilidade<br>(CNF)", _fmt_pct_curt(valores["pct_cnf"]),
                variante="azul",
            ),
            unsafe_allow_html=True,
        )
    with cols[3]:
        st.markdown(
            _render_kpi_curt(
                "Elétrico<br>(REL)", _fmt_pct_curt(valores["pct_rel"]),
                variante="azul",
            ),
            unsafe_allow_html=True,
        )

    if uf_selecionada is not None:
        with cols[4]:
            st.markdown(
                _render_kpi_curt(
                    "Curtailment Brasil",
                    _fmt_pct_curt(kpis_br["pct_total"]),
                    variante="cinza",
                ),
                unsafe_allow_html=True,
            )


def _render_mapa_estado(
    df_filtrado: pd.DataFrame,
    fonte_label: str,
) -> go.Figure:
    """Mapa choropleth do Brasil com % Curtailment por UF.

    - Estados COM dados: gradiente Bauhaus creme→amarelo→vermelho.
    - Estados SEM dados: cinza claro com tooltip "sem curtailment no período".
    - Hover rico no trace colorido: % Curtailment + Frustrado (MWh + MWmed).

    Função NÃO chama st.plotly_chart — retorna go.Figure pra integrador
    decidir layout (st.columns etc).

    Args:
        df_filtrado: DataFrame pós-aplicar_rateio + filtro fonte/janela.
                     Precisa colunas UF, FRUSTRADO_MWH, OUTPUT_MWH, DATA_HORA.
        fonte_label: "Solar" ou "Eólica" (futuro: usar em título).
    """
    gj = _carregar_geojson_estados()
    todas_siglas = [f["properties"]["sigla"] for f in gj["features"]]
    nomes_pt = {f["properties"]["sigla"]: f["properties"]["name"]
                for f in gj["features"]}

    # Agrega por UF (denominador = Output + Frustrado, fórmula ONS)
    agg = df_filtrado.groupby("UF", dropna=False).agg(
        FRUSTRADO_MWH=("FRUSTRADO_MWH", "sum"),
        OUTPUT_MWH=("OUTPUT_MWH", "sum"),
    ).reset_index()
    denom = agg["FRUSTRADO_MWH"] + agg["OUTPUT_MWH"]
    agg["PCT"] = (agg["FRUSTRADO_MWH"] / denom.replace(0, pd.NA) * 100).fillna(0)

    # Horas reais do período pra calcular MWmed (span de DATA_HORA)
    if "DATA_HORA" in df_filtrado.columns and len(df_filtrado) > 0:
        horas = max(
            (df_filtrado["DATA_HORA"].max() - df_filtrado["DATA_HORA"].min())
            .total_seconds() / 3600,
            0.5,
        )
    else:
        horas = 1.0
    agg["MWMED"] = agg["FRUSTRADO_MWH"] / horas
    agg["NOME_PT"] = agg["UF"].map(lambda u: nomes_pt.get(u, u))
    agg["FRUSTRADO_FMT"] = agg["FRUSTRADO_MWH"].apply(lambda v: _fmt_br_curt(v, 0))
    agg["MWMED_FMT"] = agg["MWMED"].apply(lambda v: _fmt_br_curt(v, 0))

    cd_colored = list(zip(
        agg["NOME_PT"], agg["FRUSTRADO_FMT"], agg["MWMED_FMT"],
    ))

    # Trace 1: estados sem dados (cinza, background)
    ufs_sem = [s for s in todas_siglas if s not in agg["UF"].values]
    trace_cinza = go.Choropleth(
        geojson=gj,
        featureidkey="properties.sigla",
        locations=ufs_sem,
        z=[0] * len(ufs_sem),
        colorscale=[[0, "#E5E5E5"], [1, "#E5E5E5"]],
        showscale=False,
        customdata=[[nomes_pt[u]] for u in ufs_sem],
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "sem curtailment no período<extra></extra>"
        ),
        marker=dict(line=dict(color=BAUHAUS_BLACK, width=0.5)),
        name="sem dados",
    )

    # Trace 2: estados com dados (gradiente Bauhaus, foreground)
    trace_colored = go.Choropleth(
        geojson=gj,
        featureidkey="properties.sigla",
        locations=agg["UF"].tolist(),
        z=agg["PCT"].tolist(),
        colorscale=[[0, BAUHAUS_CREAM], [0.5, BAUHAUS_YELLOW], [1, BAUHAUS_RED]],
        customdata=cd_colored,
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "% Curtailment: %{z:.2f}%<br>"
            "Frustrado: %{customdata[1]} MWh "
            "(%{customdata[2]} MWmed)<extra></extra>"
        ),
        marker=dict(line=dict(color=BAUHAUS_BLACK, width=0.5)),
        colorbar=dict(
            title=dict(
                text="% Curt.",
                font=dict(family="Inter, sans-serif", size=12,
                          color=BAUHAUS_BLACK),
            ),
            thickness=12, len=0.7,
            tickfont=dict(family="Inter, sans-serif", size=10,
                          color=BAUHAUS_BLACK),
            ticksuffix="%", tickformat=".1f",
        ),
        name="com dados",
    )

    fig = go.Figure(data=[trace_cinza, trace_colored])
    fig.update_geos(
        visible=False,
        fitbounds="locations",
        projection_type="mercator",
    )
    fig.update_layout(
        height=500,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor=BAUHAUS_CREAM,
        plot_bgcolor=BAUHAUS_CREAM,
        font=dict(family="Inter, sans-serif", size=12, color=BAUHAUS_BLACK),
        hoverlabel=dict(
            bgcolor=BAUHAUS_CREAM,
            bordercolor=BAUHAUS_BLACK,
            font=dict(family="Inter, sans-serif", size=12,
                      color=BAUHAUS_BLACK),
        ),
    )
    return fig


# =============================================================================
# Wrapper cacheado: filter por fonte + aplicar_rateio
#
# Performance crítica: aplicar_rateio em 3.6M linhas (Solar+Eólica) custava
# 17s por chamada. Filter por fonte ANTES do rateio reduz pra 1.1M (Solar)
# ou 2.5M (Eólica), e o cache evita re-execução em reruns sem mudança de
# (data_ini, data_fim, fonte_label).
#
# Decisões:
# - Args com prefix _ são ignorados pelo Streamlit no hashing (convenção
#   oficial docs) — chave de cache fica em (data_ini, data_fim, fonte_label),
#   3 escalares, hash trivial (~10ms vs ~1s pra hashear df 3.6M linhas).
# - TTL=6h alinha com carregar_curtailment upstream (data_loader_curtailment.
#   py:524) — wrapper não fica mais stale que loader.
# - Filter ANTES do rateio é matematicamente equivalente (validado em
#   scripts/validar_filter_antes_rateio.py): merge usa FONTE como chave,
#   cross-fonte = 0 por construção; rateio é multiplicação element-wise;
#   usinas em rateio múltiplo (18 casos, incl. 7 híbridos) preservam
#   exato número de linhas + volumes.
# =============================================================================


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def _aplicar_rateio_cached(
    data_ini: date,
    data_fim: date,
    fonte_label: str,
    _df_curt_raw: pd.DataFrame,
    _df_grupos: pd.DataFrame,
    _aliases: dict,
) -> pd.DataFrame:
    """Filter por FONTE + aplicar_rateio, cacheado por (janela, fonte)."""
    fonte_code = "SOLAR" if fonte_label == "Solar" else "EOLICA"
    df_curt_filtrado = _df_curt_raw[_df_curt_raw["FONTE"] == fonte_code]
    return aplicar_rateio(df_curt_filtrado, _df_grupos, _aliases)


# =============================================================================
# Wrapper top-level: janela ampla 15M com Categorical
#
# Caminho 1 (decisão de sessão 2026-05-04): cachear o df_curt_raw consolidado
# de uma janela ampla (~15M = 5 trimestres = 1 corrente parcial + 4 fechados,
# cobre comparação YoY pra qualquer trimestre). Visão Geral filtra slice em
# memória pros presets curtos; Por usina/Por grupo usam direto (15M cobre
# os 12M que pediam antes — calcular_periodos_curtailment usa 3 meses +
# 4 trimestres ancorados em max_d, voltando até T3 do ano anterior =
# ~10 meses atrás, ainda dentro dos 15M com folga de 1 trimestre).
#
# Categorical OBRIGATÓRIO em USINA/RAZAO/FONTE/SUBMERCADO/UF:
# - Sem Categorical: footprint estimado ~750MB → OOM no Cloud free tier 1GB
#   (mesmo motivo que removeu sub-aba Por estado em 2abd77b).
# - Com Categorical: footprint estimado ~180-220MB. Margem confortável.
# - USINA tem ~700 únicos, RAZAO 4, FONTE 2, SUBMERCADO 4, UF ~13 — todos
#   altíssimo grau de repetição em ~3.6M+ linhas, ganho típico 5-10×.
#
# Decisões de chave de cache:
# - 3 args escalares (date, date, tuple) — hash trivial.
# - TTL 6h alinha com carregar_curtailment upstream (não fica mais stale).
# - Sem hash_funcs custom (args primitivos imutáveis).
#
# Cold start estimado (Cloud free tier): 40-45s na 1ª chamada da sessão.
# Trocas subsequentes (preset, sub-aba): <1s (cache hit).
# Ganho colateral: _aplicar_rateio_cached agora é chamado com (janela_ampla,
# fonte) → cache hit em qualquer troca, não só Por usina ↔ Por grupo.
# =============================================================================


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def _carregar_curtailment_janela_ampla(
    data_ini_ampla: date,
    data_fim_ampla: date,
    fontes: tuple = ("eolica", "solar"),
) -> pd.DataFrame:
    """Carrega janela ampla 15M e converte strings pra Categorical."""
    df = carregar_curtailment(data_ini_ampla, data_fim_ampla, fontes)
    if len(df) == 0:
        return df
    for col in ("USINA", "RAZAO", "FONTE", "SUBMERCADO", "UF"):
        if col in df.columns:
            df[col] = df[col].astype("category")
    return df


# =============================================================================
# Função principal da aba
# =============================================================================


def render_aba_curtailment() -> None:
    """Wrapper defensivo. Captura crash e exibe stack trace na tela em vez
    de propagar pra Streamlit (que mostraria 'Oh no' no lugar)."""
    try:
        _render_aba_curtailment_impl()
    except Exception:
        import traceback
        st.error("⚠️ Erro ao carregar aba Curtailment (debug ativo)")
        st.code(traceback.format_exc(), language="python")
        st.caption(
            "Este erro foi capturado para investigação. "
            "Por favor, copie o stack trace acima e reporte."
        )
        # NOTA: sem re-raise para preservar st.error/st.code na tela.
        # O Streamlit capturaria a exception e mostraria "Oh no" no lugar.


def _render_aba_curtailment_impl() -> None:
    """Renderiza a aba completa de Curtailment."""

    # ---- Título h1 (padrão das outras abas: app.py:2192, 2785, 3741) ----
    st.markdown("# CURTAILMENT")

    # ---- Caption explicativa (Inter italic cinza, padrão Bauhaus) ----
    st.markdown(
        '<div style="font-family:\'Inter\', sans-serif; '
        'font-size:0.85rem; color:#6B6B6B; font-style:italic; '
        'margin:0 0 0.8rem 0;">'
        'Restrições de geração (constrained-off) em usinas eólicas e solares '
        'do SIN. Dados ONS desde 2022.'
        '</div>',
        unsafe_allow_html=True,
    )

    # =========================================================================
    # Mapeamento de proprietários (Excel + aliases) — rápido, ~1s
    # =========================================================================
    with st.spinner("Carregando mapeamento de proprietários…"):
        df_grupos = carregar_grupos_excel()
        aliases = carregar_aliases()

    if len(df_grupos) == 0:
        st.warning(
            f"Excel `{EXCEL_DEFAULT_PATH}` não carregado. Curtailment será "
            f"mostrado sem proprietários (todos como 'Other')."
        )

    # =========================================================================
    # Descobrir último dia disponível ANTES dos controles (ancora max_d).
    # Necessário pra que a presets ancorem corretamente sem baixar dataset
    # inteiro upfront. Usa cache do helper se disponível, senão fallback today.
    # =========================================================================
    with st.spinner("Verificando última data disponível no ONS…"):
        try:
            ultimo_dia = descobrir_ultimo_dia_disponivel("eolica")
        except Exception:
            ultimo_dia = None
        if ultimo_dia is None:
            ultimo_dia = date.today()

    # Range válido: dataset cobre desde 2022 (briefing). max_d = último dia
    # ONS publicado. Padrão Reservatórios/ENA/Carga: ancorar em data real do
    # dataset, não today.
    min_d_curt = date(2022, 1, 1)
    max_d_curt = ultimo_dia

    # ---- Registrar CSS dos KPIs (1× por render) ----
    st.markdown(_CSS_KPI_CURT, unsafe_allow_html=True)

    # =========================================================================
    # SUB-ABA selector — 3 st.button customizados em vez de st.segmented_control.
    # Razão: segmented_control não expõe atributo estável distinguindo ativo
    # de inativo (testado: aria-pressed/checked/selected todos vazios; classes
    # Emotion são instáveis — armadilha 4.3 do CLAUDE.md). 3 st.button +
    # type="primary"/"secondary" usam atributo HTML semântico (kind=) e
    # geram class .st-key-<key> no element-container (pattern já validado
    # no projeto, ver app.py:455-463 e decisão Sessão 4a).
    #
    # CSS: inverte hierarquia visual — ativo fica BRANCO com borda preta
    # (destaca sobre cream do app); inativos ficam pretos com texto cream.
    # Escopado via [class*="st-key-btn_curt_subaba_"] — não vaza pra outros
    # botões type="primary" da página (presets de período mantêm amarelo).
    # =========================================================================
    st.markdown("""
    <style>
    [class*="st-key-btn_curt_subaba_"] button[kind="primary"] {
        /* G.2 (Fase G): amarelo Bauhaus, alinha com presets de período. */
        background-color: #F6BD16 !important;  /* BAUHAUS_YELLOW */
        color: #1A1A1A !important;
        border: 2px solid #1A1A1A !important;
        border-radius: 0 !important;
        box-shadow: none !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 700 !important;
    }
    [class*="st-key-btn_curt_subaba_"] button[kind="secondary"] {
        background-color: #1A1A1A !important;
        color: #F5F1E8 !important;
        border: 2px solid #1A1A1A !important;
        border-radius: 0 !important;
        box-shadow: none !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 600 !important;
    }
    [class*="st-key-btn_curt_subaba_"] button:hover {
        opacity: 0.9;
    }
    </style>
    """, unsafe_allow_html=True)

    if "curt_sub_aba" not in st.session_state:
        st.session_state["curt_sub_aba"] = "Visão geral"

    opcoes_subaba = ["Visão geral", "Por usina", "Por grupo"]
    cols_subaba = st.columns(3)
    for i, nome in enumerate(opcoes_subaba):
        with cols_subaba[i]:
            ativo = st.session_state["curt_sub_aba"] == nome
            if st.button(
                nome,
                type="primary" if ativo else "secondary",
                key=f"btn_curt_subaba_{i}",
                use_container_width=True,
            ):
                st.session_state["curt_sub_aba"] = nome
                st.rerun()

    sub_aba = st.session_state["curt_sub_aba"]

    # =========================================================================
    # CONTROLES GLOBAIS — fonte sempre visível; granularidade + período só
    # na "Visão geral" (sub-abas "Por usina" e "Por grupo" usam períodos
    # fixos via calcular_periodos_curtailment — 3 meses + 4 trimestres
    # ancorados em max_d; controles não fazem nada nelas).
    # =========================================================================
    if sub_aba == "Visão geral":
        # Layout 0.7/0.7/1.6: Fonte e Granularidade são strings curtas;
        # Entidade pode ter strings longas tipo "Conjunto Dracena (Unidade)".
        ctrl_cols = st.columns([0.7, 0.7, 1.6])
        with ctrl_cols[0]:
            fonte_label = st.selectbox(
                "Fonte",
                ["Solar", "Eólica"],
                index=0,
                key="curt_fonte",
            )
        with ctrl_cols[1]:
            granularidade_ui = st.selectbox(
                "Granularidade",
                list(GRANS_UI.keys()),
                index=1,  # default: Mensal
                key="curt_granularidade",
            )
        with ctrl_cols[2]:
            # Reset defensivo ANTES de instanciar o widget (decisão 5.12):
            # se entidade selecionada não está mais nas opções (trocou Fonte
            # e era unidade da fonte anterior), volta pra "Brasil (SIN)".
            opcoes_entidade = _construir_opcoes_entidade(fonte_label)
            atual_entidade = st.session_state.get(
                "curt_entidade", "Brasil (SIN)"
            )
            if atual_entidade not in opcoes_entidade:
                st.session_state["curt_entidade"] = "Brasil (SIN)"
            entidade = st.selectbox(
                "Entidade",
                opcoes_entidade,
                key="curt_entidade",
            )
        granularidade = GRANS_UI[granularidade_ui]
        filtro_grupo, filtro_unidade, titulo_contexto = _parse_entidade(
            entidade
        )

        # Spacer: CSS global de app.py:353 aplica margin-top:-1.5rem em
        # .stDateInput. Sem este spacer, labels dos date_inputs sobrepõem
        # a Linha 1. NÃO REMOVER sem testar visualmente.
        st.markdown(
            '<div style="height:1.5rem"></div>', unsafe_allow_html=True,
        )

        # --- Reset de janela ao trocar granularidade ---
        prev_gran = st.session_state.get("curt_granularidade_anterior")
        trocou_gran = prev_gran is not None and prev_gran != granularidade

        def _aplicar_default_periodo_curt(gran_key, mn, mx):
            cfg = PRESETS_BY_GRAN[gran_key]
            default_label = cfg["default"]
            for label, data_ini_fn, is_max in cfg["presets"]:
                if label == default_label:
                    if is_max:
                        st.session_state["curt_data_ini"] = mn
                    else:
                        st.session_state["curt_data_ini"] = max(
                            mn, data_ini_fn(mx)
                        )
                    st.session_state["curt_data_fim"] = mx
                    return

        # Janela ampla efetiva: depende de curt_janela_modo (default/24m/max).
        # Necessária pra (a) min_d do helper, (b) tooltips dinâmicos, (c) detecção
        # de pedido de expansão, (d) clamp do default ao trocar granularidade.
        modo_janela_atual = st.session_state.get("curt_janela_modo", "default")
        data_ini_ampla_ui = _data_ini_ampla_efetiva(max_d_curt, modo_janela_atual)

        if "curt_data_ini" not in st.session_state or trocou_gran:
            _aplicar_default_periodo_curt(
                granularidade, data_ini_ampla_ui, max_d_curt
            )
        if "curt_data_fim" not in st.session_state:
            st.session_state["curt_data_fim"] = max_d_curt
        st.session_state["curt_granularidade_anterior"] = granularidade

        def _on_expansion_request_curt(label: str):
            """Callback do helper quando preset clicado pede mais histórico."""
            if label == "24M":
                st.session_state["_curt_pending_modal"] = "24m"
            else:  # is_max → "Máx"
                st.session_state["_curt_pending_modal"] = "max"
            st.rerun()

        _render_period_controls_curt(
            presets=PRESETS_BY_GRAN[granularidade]["presets"],
            session_key_ini="curt_data_ini",
            session_key_fim="curt_data_fim",
            key_prefix="btn_curt_",
            min_d=data_ini_ampla_ui,
            max_d=max_d_curt,
            cache_data_ini_atual=data_ini_ampla_ui,
            hard_min=date(2022, 1, 1),  # min_d_curt (limite absoluto ONS)
            on_expansion_request=_on_expansion_request_curt,
        )

        # Caption indicativa (lê data efetiva do cache atual). Padrão
        # Bauhaus de caption discreta — Inter italic cinza #6B6B6B
        # (st.caption renderiza em branco sobre cream, invisível).
        st.markdown(
            '<div style="font-family:\'Inter\', sans-serif; '
            'font-size:0.85rem; color:#6B6B6B; font-style:italic; '
            'margin:0.6rem 0 0.5rem 0;">'
            f'Histórico em cache: desde '
            f'{data_ini_ampla_ui.strftime("%d/%m/%Y")}. '
            f'Use 24M ou Máx pra carregar mais.'
            '</div>',
            unsafe_allow_html=True,
        )

        # Modal de expansão (decisão 5.12 — flag intermediário consumida com pop).
        modo_pendente = st.session_state.pop("_curt_pending_modal", None)
        if modo_pendente:
            _confirmar_expansao_curt(modo_pendente)

        data_ini = st.session_state["curt_data_ini"]
        data_fim = st.session_state["curt_data_fim"]
        if data_ini > data_fim:
            st.error("Data inicial maior que data final.")
            st.stop()
    else:
        # "Por usina" / "Por grupo": granularidade/preset ocultos.
        # Layout G.6: Fonte (~30%) + 3 checkboxes de razão (~70%) na
        # mesma linha. Razões padrão: todas marcadas (= comportamento
        # pré-G.6, validado bit-a-bit em validar_filtro_razoes.py).
        cols_filtros = st.columns([0.3, 0.7])
        with cols_filtros[0]:
            fonte_label = st.selectbox(
                "Fonte",
                ["Solar", "Eólica"],
                index=0,
                key="curt_fonte",
            )
        with cols_filtros[1]:
            # Spacer pra alinhar checkboxes com edge inferior do selectbox
            # "Fonte" — o label "Fonte" do selectbox ocupa ~20px acima do
            # widget. Mesmo padrão dos botões de preset de período.
            st.markdown(
                '<div style="font-size:0.875rem; color:transparent; '
                'user-select:none; margin-bottom:0.5rem;">.</div>',
                unsafe_allow_html=True,
            )
            cols_razoes = st.columns([1, 1, 1])
            razoes_marcadas_list = []
            # Pattern shadow key pra persistência entre sub-abas:
            # Streamlit DELETA widget keys do session_state em reruns que
            # não renderizam o widget (branch "Visão geral" não cria estes
            # checkboxes). Sem shadow, voltar pra "Por usina" recriaria os
            # widgets com default True, perdendo seleção.
            # Solução: shadow key (NÃO usada por widget) preserva estado
            # entre renderizações condicionais. Sufixo "_persisted" e
            # underscore inicial sinalizam intenção.
            for i, (sigla, nome) in enumerate(_RAZOES_FILTRO):
                shadow_key = f"_curt_razao_{sigla}_persisted"
                widget_key = f"curt_razao_{sigla}"

                # Inicializa shadow na 1ª render absoluta (default = marcado).
                if shadow_key not in st.session_state:
                    st.session_state[shadow_key] = True

                # Hidrata widget_key a partir do shadow ANTES de criar
                # o widget — sobrevive ao cleanup do Streamlit.
                if widget_key not in st.session_state:
                    st.session_state[widget_key] = st.session_state[shadow_key]

                with cols_razoes[i]:
                    marcada = st.checkbox(
                        f"{nome} ({sigla})",
                        key=widget_key,
                    )
                    if marcada:
                        razoes_marcadas_list.append(sigla)

                # Sincroniza shadow APÓS o render — captura o estado
                # atual do widget (ex: usuário acabou de marcar/desmarcar)
                # pra próxima renderização (mesmo se o widget for
                # descartado entre renders).
                st.session_state[shadow_key] = marcada

            # SORTED pra cache key canônica (("ENE", "REL") == ("REL", "ENE"))
            razoes_marcadas = tuple(sorted(razoes_marcadas_list))
        # TODO (Fase F polimento): data_ini/data_fim calculados aqui ficam
        # ÓRFÃOS pós-refator do Caminho 1 — Por usina/Por grupo passaram a
        # usar a janela ampla 15M direto via _carregar_curtailment_janela_ampla
        # (calcular_periodos_curtailment usa 3 meses + 4 trimestres ancorados
        # em max_d, sempre dentro dos 15M com folga). Aceitável agora pra
        # manter diff cirúrgico; limpar em sessão futura.
        data_fim = max_d_curt
        data_ini = max(min_d_curt, max_d_curt - timedelta(days=365))
        granularidade = None
        granularidade_ui = None

    # =========================================================================
    # Carregar curtailment via wrapper de janela ampla.
    # Janela varia por curt_janela_modo (default ~13M / 24m / max desde 2022).
    # Cache key inclui data_ini_ampla → entradas separadas por modo
    # automaticamente. Disk-cache v5 é por mês×fonte → meses extras
    # baixados ficam no disco, sessões futuras instantâneas.
    # Visão Geral filtra slice em memória pros presets curtos; Por usina/
    # Por grupo usam direto. Detalhes da decisão no cabeçalho do
    # _carregar_curtailment_janela_ampla.
    # =========================================================================
    modo_janela = st.session_state.get("curt_janela_modo", "default")
    data_ini_ampla = _data_ini_ampla_efetiva(max_d_curt, modo_janela)

    # G.3 (Fase G): mensagem informativa diferenciada.
    # 1ª carga da sessão: spinner com mensagem completa (40-60s esperados).
    # Cargas subsequentes: cache hit é instantâneo (<100ms); spinner que
    # pisca rápido demais polui visualmente — usar silêncio (sem with
    # st.spinner). Flag _curt_ja_carregou só vira True após sucesso —
    # próxima tentativa pós-erro mostra a mensagem completa de novo.
    ja_carregou_curt = st.session_state.get("_curt_ja_carregou", False)

    if not ja_carregou_curt:
        with st.spinner(
            "Carregando 15 meses de dados ONS — primeira carga da sessão "
            "(pode levar 40-60s)…"
        ):
            df_curt_raw_amplo = _carregar_curtailment_janela_ampla(
                data_ini_ampla=data_ini_ampla,
                data_fim_ampla=max_d_curt,
                fontes=("eolica", "solar"),
            )
    else:
        df_curt_raw_amplo = _carregar_curtailment_janela_ampla(
            data_ini_ampla=data_ini_ampla,
            data_fim_ampla=max_d_curt,
            fontes=("eolica", "solar"),
        )

    if df_curt_raw_amplo is None or len(df_curt_raw_amplo) == 0:
        st.error(
            "Não foi possível carregar dados de curtailment para esta janela. "
            "Tente outro período ou verifique a conexão com o ONS."
        )
        return

    st.session_state["_curt_ja_carregou"] = True

    # ---- Filter por fonte + Aplicar rateio (cacheado por janela_ampla+fonte) ----
    # Chamado SEMPRE com (data_ini_ampla, max_d_curt) — não com a janela curta
    # da Visão Geral. Razão: cache key fica (janela_ampla, fonte_label) = 2
    # entradas por sessão (Solar + Eólica). Cache hit em qualquer troca de
    # preset OU sub-aba, não só Por usina ↔ Por grupo. Equivalência matemática
    # validada em scripts/validar_cache_janela_ampla.py — rateio é
    # multiplicação element-wise, slice posterior por DATA é distributivo.
    df_filtrado_amplo = _aplicar_rateio_cached(
        data_ini_ampla, max_d_curt, fonte_label,
        df_curt_raw_amplo, df_grupos, aliases,
    )

    # Visão Geral: filter por DATA pra janela curta selecionada (ms).
    # Por usina/Por grupo: usam o df_filtrado_amplo direto (15M cobre os
    # 12M antigos; calcular_periodos_curtailment usa 3 meses + 4 trimestres
    # ancorados em max_d, sempre dentro dos 15M).
    if sub_aba == "Visão geral":
        df_filtrado = df_filtrado_amplo[
            (df_filtrado_amplo["DATA"] >= data_ini)
            & (df_filtrado_amplo["DATA"] <= data_fim)
        ]
    else:
        df_filtrado = df_filtrado_amplo

    if len(df_filtrado) == 0:
        st.warning("Sem dados pra esta combinação de filtros.")
        st.stop()

    # =========================================================================
    # DESPACHO — segmented_control acima escolheu sub_aba; render só da
    # escolhida. Sub-aba "Por estado" foi removida em commit 2abd77b
    # (OOM no Cloud free tier 1GB). Funções _render_mapa_estado,
    # _carregar_geojson_estados, _render_kpis_por_estado, _nome_estado
    # ficam órfãs (dead code) — remover em sessão futura.
    # data/curtailment/brazil_states.geojson permanece no repo.
    # =========================================================================
    if sub_aba == "Visão geral":
        _render_visao_geral(
            df_filtrado, granularidade, granularidade_ui, fonte_label,
            data_ini, data_fim,
            filtro_grupo=filtro_grupo,
            filtro_unidade=filtro_unidade,
            titulo_contexto=titulo_contexto,
        )
    elif sub_aba == "Por usina":
        # G.6: edge case "nenhum marcado" — caller mostra mensagem e
        # NÃO chama o helper. Não usa st.stop(): o resto da página
        # (controles do topo, sub-aba selector) continua interativo,
        # usuário pode re-marcar pelo menos uma razão.
        if len(razoes_marcadas) == 0:
            st.info(
                "Selecione pelo menos uma razão para visualizar a tabela."
            )
        else:
            _render_por_unidade(df_filtrado, razoes_marcadas)
    else:  # "Por grupo"
        _placeholder_em_construcao()
