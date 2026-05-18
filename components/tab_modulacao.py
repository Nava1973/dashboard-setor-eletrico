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
from utils.cores_fontes import (
    COR_FONTE_HIDRO,
    COR_FONTE_EOLICA,
    COR_FONTE_SOLAR,
)


# =============================================================================
# Paleta — migração 2026-05-15 (Bauhaus → Bradesco).
# Single source of truth em utils/paleta_bradesco.py. Aliases locais ficam
# por compat com ~26 usos no resto do arquivo.
# =============================================================================

from utils.paleta_bradesco import (
    COR_FUNDO,
    COR_TEXTO,
    COR_TEXTO_SECUND,
    COR_GRID,
)

# Compat aliases — migração 2026-05-15. TODO: rename to COR_* nos consumidores.
BAUHAUS_BLACK  = COR_TEXTO   # era #1A1A1A → #313131
BAUHAUS_CREAM  = COR_FUNDO   # era #F5F1E8 → #FFFFFF
BAUHAUS_LIGHT  = COR_GRID    # era #E8E3D4 → #E0E0E0

# Cores canônicas de fontes de geração — agora importadas de
# utils/cores_fontes.py (decisão 5.33 RESOLVIDA). Os nomes locais
# COR_FONTE_HIDRO/EOLICA/SOLAR continuam disponíveis via import,
# então CORES_FONTE_MOD abaixo + todas as referências subsequentes
# seguem funcionando inalteradas — só a fonte da constante mudou.

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
        ("Máx", None),
    ],
    "semanal": [
        ("1M", 4),
        ("3M", 13),
        ("Máx", None),
    ],
}

DEFAULT_PRESET_POR_GRANULARIDADE = {
    "mensal":     "12M",
    "trimestral": "12M",
    "semanal":    "3M",
}


# =============================================================================
# Mês PT-BR (sem depender de locale do sistema — Cloud usa Linux)
# =============================================================================

MESES_PT = {
    1: "jan", 2: "fev", 3: "mar", 4: "abr", 5: "mai", 6: "jun",
    7: "jul", 8: "ago", 9: "set", 10: "out", 11: "nov", 12: "dez",
}


def _fmt_periodo(ts, granularidade: str, longo: bool = False) -> str:
    """Formata um Timestamp de início de período conforme granularidade.

    mensal     → 'mai/26'
    trimestral → '2T26'
    semanal    → '06/01'  (DD/MM do 1º dia da semana); longo=True → '06/01/26'

    `longo` só afeta o semanal — adiciona o ano de 2 dígitos. Usado no
    título e no hover (que têm espaço e se beneficiam do ano sem
    ambiguidade); o eixo X usa a forma curta DD/MM pra caber mais barras.
    Mensal e trimestral já carregam o ano nos dois modos.
    """
    ts = pd.Timestamp(ts)
    if granularidade == "mensal":
        return f"{MESES_PT[ts.month]}/{ts.year % 100:02d}"
    if granularidade == "trimestral":
        q = (ts.month - 1) // 3 + 1
        return f"{q}T{ts.year % 100:02d}"
    if granularidade == "semanal":
        # Data do 1º dia da semana (freq W → segunda-feira). Mais legível
        # que a numeração ISO de semana, que exige contar semanas de cabeça.
        return ts.strftime("%d/%m/%y") if longo else ts.strftime("%d/%m")
    raise ValueError(f"Granularidade desconhecida: {granularidade!r}")


# =============================================================================
# Disk cache — 6 parquets, TTL 24h: variante "recente" (default, ~2 anos de
# PLD horário — caminho rápido da Frente 3) + variante "completo" (desde 2022),
# uma de cada por granularidade.
#
# Schema v2: coluna periodo_inicio (em vez de ano_mes do v1).
# Nome canônico da variante completa preservado (modulacao_spread_v2_{g}) —
# não invalida parquets já no disco; a recente ganha sufixo descritivo.
# Espelha o split recente/completo do PLD horário (CLAUDE.md §5.71, Frente 3).
# Reusa fábrica do data_loader.py (decisão 5.15).
# =============================================================================

_GRANULARIDADES = ("mensal", "trimestral", "semanal")

_CACHE_PREFIXO_POR_MODO = {
    "completo": "modulacao_spread_v2_",
    "recente":  "modulacao_spread_v2_recente_",
}

_DISK_CACHE_HELPERS = {
    (modo, g): _make_disk_cache_helpers(
        f"{prefixo}{g}", ttl_sec=60 * 60 * 24,
    )
    for modo, prefixo in _CACHE_PREFIXO_POR_MODO.items()
    for g in _GRANULARIDADES
}


# =============================================================================
# Cálculo principal — cache 2-layer (RAM 30d + disk 24h)
# =============================================================================

@st.cache_data(
    ttl=60 * 60 * 24 * 30,
    show_spinner="Calculando spread de modulação...",
)
def _calcular_spread(
    granularidade: str, incluir_historico_completo: bool = False,
) -> pd.DataFrame:
    """Calcula spread por (periodo_inicio, submercado, fonte).

    granularidade ∈ {'mensal', 'trimestral', 'semanal'}.

    incluir_historico_completo: se False (default), usa só o PLD horário
        recente (~2 anos — caminho rápido da Frente 3, CLAUDE.md §5.71).
        Cobre os presets default de Mensal (12M) e Semanal (3M); Trimestral
        24M fica parcial até o usuário carregar o histórico completo. Se
        True, usa o histórico PLD completo (desde 2021), pago sob demanda
        via modal de confirmação na UI.

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

    modo = "completo" if incluir_historico_completo else "recente"
    _, _, try_read, try_write = _DISK_CACHE_HELPERS[(modo, granularidade)]
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
    # O modo (recente ~2 anos / completo desde 2021) é repassado pro loader:
    # recente é o caminho rápido (Frente 3) e cobre os presets default; o
    # completo é pago sob demanda via modal na UI da aba.
    df_pld = load_pld_horaria(
        incluir_historico_completo=incluir_historico_completo
    )
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

    # Drop períodos parciais — EXCETO o último (período corrente): ele é
    # exibido com a média parcial acumulada até a última hora disponível
    # (ex.: mensal = média de 01/mai até o último dia com dado). Os demais
    # períodos parciais (gaps históricos, raros — dados são horário-estrito)
    # continuam dropados pra não exibir spread ruidoso no meio da série.
    min_horas = GRANULARIDADE_MIN_HORAS[granularidade]
    ultimo_periodo = g["periodo_inicio"].max()
    g = g[
        (g["n_horas"] >= min_horas)
        | (g["periodo_inicio"] == ultimo_periodo)
    ].copy()

    out = g[
        ["periodo_inicio", "submercado", "fonte", "spread_rs_mwh",
         "mwmed_medio", "n_horas"]
    ].sort_values(
        ["periodo_inicio", "submercado", "fonte"]
    ).reset_index(drop=True)

    try_write(out)
    return out


# =============================================================================
# Shadow state — protege widget keys contra cleanup cross-tab
# =============================================================================
# Problema: ao navegar pra outra aba, Streamlit faz cleanup das widget keys
# nao renderizadas (mod_granularidade, mod_data_ini, mod_data_fim). Keys
# nao-widget (mod_datas_custom, mod_granularidade_anterior) sobrevivem,
# criando estado inconsistente que pode resetar a UI pro default ao voltar.
#
# Solucao: espelhar as widget keys em keys "shadow" (prefixo mod_shadow_*),
# que NAO sao widget keys e sobrevivem ao cleanup. Restaurar a partir do
# shadow no INICIO do render se as widget keys sumiram.
#
# Pattern alinhado com CLAUDE.md §5.18 (backup paralelo) e replicado de
# components/tab_gsf.py (§5.77 Fase 2D++). Pendencia §9.2 do CLAUDE.md.

_SHADOW_MAP_MOD = {
    "mod_granularidade": "mod_shadow_granularidade",
    "mod_data_ini":      "mod_shadow_data_ini",
    "mod_data_fim":      "mod_shadow_data_fim",
}


def _shadow_restore_mod() -> None:
    """Detecta widget cleanup (key ausente mas shadow presente) e restaura.

    Roda no INICIO do render, ANTES de qualquer setdefault — assim o
    setdefault nao sobrescreve a restauracao com defaults.

    Edge case 1a render absoluta: nem widget keys nem shadows existem;
    restore eh no-op; init defaults rola normal.
    """
    for src, dst in _SHADOW_MAP_MOD.items():
        if src not in st.session_state and dst in st.session_state:
            st.session_state[src] = st.session_state[dst]


def _shadow_sync_mod() -> None:
    """Espelha widget keys → shadow keys.

    Chamada no FIM do render (apos todas as mutacoes programaticas) e
    sempre que o codigo muda widget keys (init, troca de granularidade,
    clamp defensivo). on_change dos widgets NAO precisa chamar — o
    proximo render acaba sincronizando aqui.
    """
    for src, dst in _SHADOW_MAP_MOD.items():
        if src in st.session_state:
            st.session_state[dst] = st.session_state[src]


def clear_modulacao_disk_cache() -> None:
    """Limpa o cache da aba Modulação: RAM (`_calcular_spread`) + os 6
    parquets de disk-cache (recente + completo × 3 granularidades) + a
    preferência `mod_historico_completo` em session_state.

    Chamado pelo botão "Atualizar" da sidebar (app.py), junto com o
    `clear_cache()` do data_loader — mantém a promessa "Atualizar =
    começar do zero" também pra esta aba, e devolve o usuário ao modo
    recente (rápido) por default.
    """
    _calcular_spread.clear()
    for get_path, _, _, _ in _DISK_CACHE_HELPERS.values():
        try:
            p = get_path()
            if p is not None and p.exists():
                p.unlink()
        except Exception:
            pass
    for k in (
        "mod_historico_completo", "mod_data_ini", "mod_data_fim",
        "mod_periodo_preset", "_mod_pending_modal", "_mod_pending_max",
        "mod_datas_custom", "mod_granularidade_anterior",
        # Shadows também — senão "Atualizar" só limpa widget keys e o
        # shadow restauraria o estado antigo no próximo render.
        *_SHADOW_MAP_MOD.values(),
    ):
        st.session_state.pop(k, None)


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


def _preset_ativo(df_spread: pd.DataFrame, granularidade: str,
                  data_ini, data_fim):
    """Qual preset (se algum) corresponde exatamente à janela (data_ini,
    data_fim) atual — usado pra destacar o botão como "primary".

    Retorna None quando o usuário escolheu uma janela custom pelos
    date_inputs (nenhum preset bate). data_ini/data_fim são datetime.date.
    """
    for label, _ in PRESETS_POR_GRANULARIDADE[granularidade]:
        di, dfim = _resolver_janela(df_spread, label, granularidade)
        if pd.isna(di) or pd.isna(dfim):
            continue
        if (pd.Timestamp(di).date() == data_ini
                and pd.Timestamp(dfim).date() == data_fim):
            return label
    return None


def _marcar_datas_custom() -> None:
    """on_change dos date_inputs: marca que o usuário mexeu manualmente
    nas datas.

    Enquanto `mod_datas_custom` é False, trocar de granularidade re-deriva
    a janela pro preset default da nova granularidade — assim cada
    granularidade sempre abre mostrando até o último período disponível.
    Quando True, a janela custom do usuário persiste entre granularidades.
    """
    st.session_state["mod_datas_custom"] = True


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
    # longo=True: no semanal o título mostra DD/MM/AA (tem espaço e o ano
    # evita ambiguidade); mensal/trimestral já trazem o ano.
    periodo_min = _fmt_periodo(
        df_periodo["periodo_inicio"].min(), granularidade, longo=True,
    )
    periodo_max = _fmt_periodo(
        df_periodo["periodo_inicio"].max(), granularidade, longo=True,
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
        f'{gran_label} · (R$/MWh)'
        f'</div>',
        unsafe_allow_html=True,
    )

    # X labels pré-formatados (categorial — preserva ordem cronológica).
    df_periodo["x_label"] = df_periodo["periodo_inicio"].apply(
        lambda ts: _fmt_periodo(ts, granularidade)
    )

    fig = go.Figure()

    # Hover semanal: trace fantasma com a data + ano (DD/MM/AA). O eixo X
    # usa DD/MM (compacto); esta linha extra no hover unified mostra a
    # semana com ano, sem ambiguidade. Pattern do PLD semanal (§5.68):
    # go.Scatter invisível com customdata 2D pré-computada. Adicionado
    # antes das barras → aparece como 1ª linha do hover.
    if granularidade == "semanal":
        periodos = (
            df_periodo[["periodo_inicio", "x_label"]]
            .drop_duplicates()
            .sort_values("periodo_inicio")
        )
        fig.add_trace(go.Scatter(
            x=periodos["x_label"],
            y=[0] * len(periodos),
            mode="markers",
            marker=dict(opacity=0),
            showlegend=False,
            hovertemplate="Semana de %{customdata[0]}<extra></extra>",
            customdata=[
                [_fmt_periodo(ts, "semanal", longo=True)]
                for ts in periodos["periodo_inicio"]
            ],
        ))

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
        fig, width="stretch", config={"displaylogo": False},
    )


# =============================================================================
# Modal de confirmação — lazy loading do histórico completo (Frente 3)
# =============================================================================

@st.dialog("Carregar histórico completo (desde 2022)?")
def _confirmar_historico_completo_modulacao() -> None:
    """Modal disparado pelo botão "Máx" em modo recente. Confirma a troca
    pro histórico de spread completo (desde 2022) antes de pagar o load
    pesado do PLD horário completo. Espelha
    `_confirmar_historico_completo_pld_horario` do app.py (CLAUDE.md §5.71).
    """
    st.markdown(
        "Calcular o spread sobre o **histórico completo** (desde 2022)?  \n"
        "Pode levar 1 a 2 minutos na primeira vez (segundos nas próximas)."
    )
    st.caption(
        "Para uso típico (análise recente), o default de ~2 anos é mais "
        "rápido e cobre os períodos padrão de Mensal e Semanal."
    )
    col1, col2 = st.columns(2)
    if col1.button("Cancelar", width="stretch"):
        st.rerun()
    if col2.button("Carregar", type="primary", width="stretch"):
        st.session_state["mod_historico_completo"] = True
        # Consumida no próximo render: aplica a janela "Máx" sobre o
        # dataset completo recém-carregado.
        st.session_state["_mod_pending_max"] = True
        st.rerun()


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
    """Renderiza a aba Modulação: numa linha só, o selectbox de
    granularidade + botões de preset + date_inputs início/fim (à direita,
    padrão das outras abas); abaixo, 4 gráficos empilhados (SE/S/NE/N).

    As datas (`mod_data_ini`/`mod_data_fim` em session_state) são a fonte
    de verdade do recorte; os presets são atalhos que as setam. O destaque
    "primary" do botão é derivado das datas (None = janela custom)."""
    # FIRST: restaura widget keys do shadow se Streamlit fez cleanup
    # ao sair da aba (cross-tab navigation). Tem que vir ANTES de
    # qualquer setdefault — senão o setdefault sobrescreveria a
    # restauração com defaults. Pendência §9.2 do CLAUDE.md.
    _shadow_restore_mod()

    # Título h1 + linha preta separadora (padrão final calibrado: -0.2rem
    # top compensa gap do Streamlit; 1.2rem bottom dá respiro pros controles;
    # 12px left alinha com padding-left do h1 global → gap entre barra
    # vermelha vertical e linha horizontal em vez do "L colado").
    st.markdown("# MODULAÇÃO")
    st.markdown(
        f'<div style="border-bottom: 2px solid {BAUHAUS_BLACK}; '
        f'margin: -0.2rem 0 1.2rem 12px;"></div>',
        unsafe_allow_html=True,
    )
    # NOTA: o caption explicativo (definição de spread de modulação) foi
    # MOVIDO pra depois do último gráfico — fica como rodapé didático no
    # final da página, sem competir com o título no topo.

    # --- Frente 3 (lazy loading): modo recente (default) vs completo ---
    # `mod_historico_completo` persiste a escolha em session_state; só volta
    # a False via "Atualizar" (clear_modulacao_disk_cache). Antes de tudo,
    # consome a flag intermediária e abre o modal de confirmação se pendente.
    historico_completo = st.session_state.setdefault(
        "mod_historico_completo", False
    )
    if st.session_state.pop("_mod_pending_modal", False):
        _confirmar_historico_completo_modulacao()

    # --- Controles numa linha: granularidade | presets | datas início/fim ---
    # Layout FIXO de 7 colunas (independe da granularidade): dropdown | 3
    # slots de preset | spacer | data inicial | data final. Datas ancoradas
    # à direita (padrão das outras abas). Granularidades com 2 presets
    # deixam o 3º slot vazio — a largura total (13.2) e o espaçamento
    # visual ficam idênticos pros casos de 2 e 3 presets.
    #
    # Layout fixo é proposital: NÃO há mais st.rerun() na troca de
    # granularidade. Um rerun explícito ali interrompia o script antes dos
    # date_inputs renderizarem, e o Streamlit limpava as keys de widget não
    # renderizado (mod_data_ini/mod_data_fim). Sem rerun, os date_inputs
    # renderizam todo run e as keys sobrevivem.
    #
    # Comportamento das datas na troca de granularidade:
    #   - datas NÃO custom (mod_datas_custom=False) → re-derivam pro preset
    #     default da nova granularidade (sempre mostra até o último período
    #     disponível — vide bloco mais abaixo);
    #   - datas custom (usuário mexeu nos date_inputs) → persistem; o clamp
    #     em [min_d, max_d] cobre as diferenças de range entre granularidades.
    st.session_state.setdefault("mod_granularidade", "mensal")
    st.session_state.setdefault("mod_datas_custom", False)
    gran_opts = ["mensal", "trimestral", "semanal"]
    cols = st.columns([2, 1, 1, 1, 5.2, 1.5, 1.5])

    with cols[0]:
        granularidade = st.selectbox(
            "Granularidade",
            options=gran_opts,
            format_func=lambda g: LABELS_GRANULARIDADE[g],
            key="mod_granularidade",
            label_visibility="collapsed",
        )

    presets = PRESETS_POR_GRANULARIDADE[granularidade]

    # --- Cálculo do spread (cache 2-layer) — necessário já aqui pra resolver
    #     os presets em datas e definir os limites dos date_inputs. ---
    df_spread = _calcular_spread(granularidade, historico_completo)
    if df_spread.empty:
        st.warning("Sem dados de spread disponíveis no momento.")
        return

    min_d = pd.Timestamp(df_spread["periodo_inicio"].min()).date()
    max_d = pd.Timestamp(df_spread["periodo_inicio"].max()).date()

    # Inicializa as datas (1ª carga ou pós-"Atualizar") com a janela do
    # preset default da granularidade.
    if ("mod_data_ini" not in st.session_state
            or "mod_data_fim" not in st.session_state):
        di, dfim = _resolver_janela(
            df_spread, DEFAULT_PRESET_POR_GRANULARIDADE[granularidade],
            granularidade,
        )
        st.session_state["mod_data_ini"] = pd.Timestamp(di).date()
        st.session_state["mod_data_fim"] = pd.Timestamp(dfim).date()

    # Troca de granularidade SEM datas custom → re-deriva a janela pro
    # preset default da nova granularidade. Sem isso, o clamp entre
    # granularidades (que têm max_d diferentes: mensal 01/mai, trimestral
    # 01/abr, semanal a última segunda) "prendia" data_fim no menor max_d
    # já visto e a aba abria sem o período corrente. Re-derivar garante
    # que cada granularidade abre mostrando até o último período disponível.
    _gran_anterior = st.session_state.get("mod_granularidade_anterior")
    if (_gran_anterior is not None and _gran_anterior != granularidade
            and not st.session_state["mod_datas_custom"]):
        di, dfim = _resolver_janela(
            df_spread, DEFAULT_PRESET_POR_GRANULARIDADE[granularidade],
            granularidade,
        )
        st.session_state["mod_data_ini"] = pd.Timestamp(di).date()
        st.session_state["mod_data_fim"] = pd.Timestamp(dfim).date()
    st.session_state["mod_granularidade_anterior"] = granularidade

    # Pós-modal de confirmação: aplica a janela "Máx" sobre o dataset
    # completo recém-carregado (flag setada no modal, consumida aqui).
    if st.session_state.pop("_mod_pending_max", False):
        st.session_state["mod_data_ini"] = min_d
        st.session_state["mod_data_fim"] = max_d
        st.session_state["mod_datas_custom"] = False

    # Clamp defensivo: se o dataset encolheu (ex.: completo → recente via
    # "Atualizar"), datas fora do range novo dariam StreamlitAPIException
    # ao re-instanciar o date_input.
    st.session_state["mod_data_ini"] = min(
        max(st.session_state["mod_data_ini"], min_d), max_d
    )
    st.session_state["mod_data_fim"] = min(
        max(st.session_state["mod_data_fim"], min_d), max_d
    )

    # Sincroniza shadow após todas as mutações programáticas (init,
    # troca de granularidade, clamp). Garante que cross-tab navegando
    # depois disto restaura tudo corretamente. Pendência §9.2.
    _shadow_sync_mod()

    # Preset ativo (destaque "primary") derivado das datas atuais — None
    # quando o usuário escolheu uma janela custom pelos date_inputs.
    preset_atual = _preset_ativo(
        df_spread, granularidade,
        st.session_state["mod_data_ini"], st.session_state["mod_data_fim"],
    )

    # --- Botões de preset (cols 1..3; 3º slot fica vazio se só há 2) ---
    # Frente 3: "Máx" em modo recente não filtra direto — abre o modal de
    # confirmação antes de pagar o load do histórico completo. Em modo
    # completo, "Máx" é filtro puro (janela inteira do dataset).
    for i, (label, _) in enumerate(presets):
        with cols[i + 1]:
            tipo = "primary" if label == preset_atual else "secondary"
            eh_max_lazy = label == "Máx" and not historico_completo
            if st.button(
                label, key=f"btn_mod_{label}",
                type=tipo, width="stretch",
                help=(
                    "Carregar histórico completo (desde 2022) — "
                    "1 a 2 min na 1ª vez"
                    if eh_max_lazy else None
                ),
            ):
                if eh_max_lazy:
                    st.session_state["_mod_pending_modal"] = True
                else:
                    di, dfim = _resolver_janela(
                        df_spread, label, granularidade,
                    )
                    st.session_state["mod_data_ini"] = pd.Timestamp(di).date()
                    st.session_state["mod_data_fim"] = pd.Timestamp(dfim).date()
                    # Clique de preset = seleção "gerida", não custom —
                    # trocar de granularidade depois volta a re-derivar.
                    st.session_state["mod_datas_custom"] = False
                st.rerun()

    # --- Date inputs início/fim (cols 5 e 6, à direita — índices fixos) ---
    with cols[5]:
        st.date_input(
            "Data inicial", min_value=min_d, max_value=max_d,
            key="mod_data_ini", format="DD/MM/YYYY",
            on_change=_marcar_datas_custom,
        )
    with cols[6]:
        st.date_input(
            "Data final", min_value=min_d, max_value=max_d,
            key="mod_data_fim", format="DD/MM/YYYY",
            on_change=_marcar_datas_custom,
        )

    data_ini = st.session_state["mod_data_ini"]
    data_fim = st.session_state["mod_data_fim"]
    if data_ini > data_fim:
        st.warning("Data inicial posterior à data final.")
        return

    df_filtrado = df_spread[
        (df_spread["periodo_inicio"] >= pd.Timestamp(data_ini))
        & (df_spread["periodo_inicio"] <= pd.Timestamp(data_fim))
    ]
    if df_filtrado.empty:
        st.warning("Sem dados no período selecionado.")
        return

    for sub in ORDEM_SUBMERCADOS:
        df_sub = df_filtrado[df_filtrado["submercado"] == sub]
        if df_sub.empty:
            continue
        _render_grafico_submercado(df_sub, sub, granularidade)

    # Caption explicativa (movida de cima do h1 pra rodapé didático no final
    # da página — fica como nota de pé pro último gráfico, sem competir com
    # o título no topo).
    st.markdown(
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.85rem; color:{COR_TEXTO_SECUND}; font-style:italic; '
        f'margin:0.6rem 0 0 0;">'
        'Spread de modulação (R$/MWh) = PLD médio ponderado pela geração '
        '<strong>menos</strong> PLD médio flat. Positivo = fonte gera mais nas '
        'horas caras. Negativo = gera mais nas horas baratas.'
        '</div>',
        unsafe_allow_html=True,
    )
