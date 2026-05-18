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

from pathlib import Path

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


# =============================================================================
# Estimativa CCEE — projeção mensal de GSF pra meses sem dado oficial
# =============================================================================
# Admin-only: usuários comuns só veem o gráfico (com tracejado pra estimativas);
# admins podem editar via st.data_editor. Pattern análogo ao Estimativa BBI
# da Receita por Empresa (§5.78), mas SEM cenário pessoal — única fonte de
# verdade pras projeções é o que admin grava como Estimativa CCEE oficial.
# Quando a CCEE publica o valor final do mês, o mês migra automaticamente
# pra linha sólida (lógica de "tem dado oficial? → sólido, senão → tracejado").

ADMIN_USERS = {"Nava", "Fagundes", "Caruso"}

_GSF_PROJECAO_PATH = (
    Path(__file__).resolve().parent.parent
    / "data" / "gsf_projecao_ccee.json"
)
_GSF_PROJECAO_VERSAO = 1

# Horizonte do editor: cobre até dezembro do ano N+1. CCEE costuma publicar
# estimativas só pra o ano corrente, mas o editor abre 2 anos pra suportar
# planejamentos de longo prazo. Meses em branco = não aparecem no gráfico.
_GSF_HORIZONTE_ANO_FINAL = 2027


def _carregar_estimativas_ccee() -> dict:
    """Retorna {YYYY-MM: gsf_pct_float} com as estimativas CCEE salvas.
    Dict vazio se arquivo não existe ou tem schema antigo."""
    import json
    try:
        if not _GSF_PROJECAO_PATH.exists():
            return {}
        todas = json.loads(_GSF_PROJECAO_PATH.read_text(encoding="utf-8"))
        if todas.get("_versao") != _GSF_PROJECAO_VERSAO:
            return {}
        return {
            k: float(v)
            for k, v in todas.get("estimativas", {}).items()
            if v is not None
        }
    except Exception:
        return {}


def _salvar_estimativas_ccee(estimativas: dict) -> bool:
    """Grava as estimativas no JSON (best-effort).
    `estimativas`: {YYYY-MM: float (% gsf, ex: 85.5)}. None/NaN são filtrados.

    No Streamlit Cloud o disco é efêmero — persiste localmente, no Cloud só
    entre restarts do container (mesma ressalva do disk-cache)."""
    import json
    try:
        _GSF_PROJECAO_PATH.parent.mkdir(parents=True, exist_ok=True)
        clean = {
            k: float(v) for k, v in estimativas.items()
            if v is not None and pd.notna(v)
        }
        payload = {
            "_versao": _GSF_PROJECAO_VERSAO,
            "estimativas": clean,
        }
        _GSF_PROJECAO_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return True
    except Exception:
        return False


def _merge_estimativas_no_df(
    df_mensal: pd.DataFrame, estimativas: dict,
) -> pd.DataFrame:
    """Retorna cópia do df mensal com:
      (a) coluna nova 'is_estimativa' (False pros oficiais, True pras
          estimativas adicionadas);
      (b) novas linhas pros meses que estão no `estimativas` mas NÃO no df
          oficial. Mês que tem AMBOS (oficial + estimativa) → oficial vence,
          estimativa é ignorada (sinaliza que CCEE publicou o valor final).

    O GSF das linhas de estimativa é setado em decimal (ex: 0.855 pra 85.5%)
    pra ficar consistente com a coluna `gsf` do df oficial. As colunas
    `sum_geracao_mre_mwh` e `sum_gf_mre_mwh` ficam NaN nas linhas estimadas
    (não temos como decompor o GSF estimado em geração e GF separadamente —
    é uma % publicada pela CCEE, não calculada por nós)."""
    out = df_mensal.copy()
    out["is_estimativa"] = False
    if not estimativas:
        return out
    # Identifica meses oficiais já no df (set de Timestamps start-of-month).
    oficiais_set = set(out.index)
    novas_linhas = []
    for ym, gsf_pct in estimativas.items():
        try:
            ts = pd.Timestamp(f"{ym}-01")
        except Exception:
            continue
        if ts in oficiais_set:
            # CCEE já publicou oficial → estimativa expira (ignorada).
            continue
        novas_linhas.append({
            "_idx": ts,
            "sum_geracao_mre_mwh": float("nan"),
            "sum_gf_mre_mwh": float("nan"),
            "gsf": float(gsf_pct) / 100.0,
            "fonte_dado": "estimativa_ccee",
            "is_estimativa": True,
        })
    if not novas_linhas:
        return out
    df_novas = pd.DataFrame(novas_linhas).set_index("_idx")
    df_novas.index.name = out.index.name
    # Garante mesmas colunas (preenche faltantes com NaN).
    for col in out.columns:
        if col not in df_novas.columns:
            df_novas[col] = float("nan") if col != "is_estimativa" else False
    df_novas = df_novas[out.columns]
    merged = pd.concat([out, df_novas]).sort_index()
    return merged


def _render_editor_estimativas_ccee(
    df_mensal_com_estimativas: pd.DataFrame, estimativas_atuais: dict,
) -> None:
    """Renderiza expander admin com data_editor pras estimativas CCEE.
    `df_mensal_com_estimativas`: df já mergeado (pra saber último mês oficial).
    `estimativas_atuais`: dict {YYYY-MM: float} carregado do JSON."""
    # Último mês com dado oficial CCEE (não-estimativa) determina o "ponto
    # de partida" do horizonte de projeção (admin edita só meses FUTUROS).
    df_oficiais = df_mensal_com_estimativas[
        ~df_mensal_com_estimativas["is_estimativa"]
    ]
    if df_oficiais.empty:
        ultimo_oficial = pd.Timestamp.today().normalize().replace(day=1)
    else:
        ultimo_oficial = pd.Timestamp(df_oficiais.index.max())

    # Horizonte: 1º mês após último oficial até Dez/_GSF_HORIZONTE_ANO_FINAL.
    primeiro_futuro = (ultimo_oficial + pd.DateOffset(months=1)).normalize()
    primeiro_futuro = primeiro_futuro.replace(day=1)
    ultimo_horizonte = pd.Timestamp(
        f"{_GSF_HORIZONTE_ANO_FINAL}-12-01"
    )
    if primeiro_futuro > ultimo_horizonte:
        # Já passamos do horizonte — nada a editar (caso edge).
        return

    meses = pd.date_range(
        primeiro_futuro, ultimo_horizonte, freq="MS",
    )

    n_est_atual = sum(
        1 for v in estimativas_atuais.values()
        if v is not None and pd.notna(v)
    )
    with st.expander(
        f"✏️ Admin: Editar Estimativa CCEE "
        f"({len(meses)} meses até Dez/{_GSF_HORIZONTE_ANO_FINAL})",
        expanded=False,
    ):
        # Badge "MODO ADMIN" — antes movido pro topo da aba; agora fica
        # AQUI (dentro do expander, antes da tabela) pra associar
        # visualmente com o controle de edição.
        st.markdown(
            f"<div style='background:#FFF3CD; border-left:4px solid #FFC107; "
            f"padding:0.4rem 0.8rem; margin:0 0 0.6rem 0; "
            f"font-family:Inter, sans-serif; font-size:0.85rem; "
            f"color:#856404;'>"
            f"<b>👤 MODO ADMIN</b> — você está editando a <b>Estimativa "
            f"CCEE oficial</b>. Mudanças aqui afetam o que todos os "
            f"usuários veem no gráfico. Atualmente {n_est_atual} "
            f"mês(es) com estimativa salva."
            f"</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div style='font-family:Inter,sans-serif; font-size:0.85rem; "
            f"color:{COR_TEXTO_SECUND}; font-style:italic; "
            f"margin:0 0 0.6rem 0;'>"
            "Valores em <b>% de GSF</b> (ex: 85,5 = 85,5%). Meses em "
            "branco não aparecem no gráfico. Quando a CCEE publica o valor "
            "oficial de um mês, a estimativa daquele mês expira "
            "automaticamente (oficial vence)."
            "</div>",
            unsafe_allow_html=True,
        )

        # CSS scoped pro editor: (a) centraliza valores na coluna "GSF
        # estimado (%)" — Streamlit alinha numéricos à direita por default,
        # fica ruim de ler; (b) força texto BRANCO no botão "Salvar" (o
        # CSS global de primary deveria já fazer isso, mas dentro de
        # expander tem cascata diferente, então reforço aqui).
        st.markdown(
            """
            <style>
            /* Centraliza valores na 2ª coluna do data_editor das estimativas.
               Glide Data Grid usa células com data-testid; cell numérico
               vai pra direita por default — sobrescreve. */
            [class*="st-key-gsf_editor_estimativas_ccee"]
            [data-testid="stDataFrameResizable"] [role="gridcell"]:nth-child(2),
            [class*="st-key-gsf_editor_estimativas_ccee"]
            div[role="gridcell"]:nth-child(2) {
                text-align: center !important;
                justify-content: center !important;
            }
            /* Botão "Salvar Estimativa CCEE": força texto branco. Necessário
               porque dentro de expander a cascata global de primary button
               às vezes perde pro estilo do p/span interno. */
            [class*="st-key-gsf_btn_salvar_estimativas"] button[kind="primary"],
            [class*="st-key-gsf_btn_salvar_estimativas"] button[kind="primary"] *,
            [class*="st-key-gsf_btn_salvar_estimativas"] button[kind="primary"] p,
            [class*="st-key-gsf_btn_salvar_estimativas"] button[kind="primary"] span,
            [class*="st-key-gsf_btn_salvar_estimativas"] button[kind="primary"] div {
                color: #FFFFFF !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        # Tabela editável: 1 linha por mês, coluna "GSF estimado (%)".
        df_editor = pd.DataFrame({
            "Mês": [_fmt_mes_pt(m) for m in meses],
            "GSF estimado (%)": [
                estimativas_atuais.get(m.strftime("%Y-%m"))
                for m in meses
            ],
        })
        edited = st.data_editor(
            df_editor,
            key="gsf_editor_estimativas_ccee",
            hide_index=True,
            disabled=["Mês"],
            column_config={
                "Mês": st.column_config.TextColumn("Mês", width="small"),
                "GSF estimado (%)": st.column_config.NumberColumn(
                    "GSF estimado (%)",
                    min_value=0.0, max_value=200.0,
                    step=0.1, format="%.1f",
                    help="Valor publicado pela CCEE (em %). Deixe vazio se "
                         "ainda não tem estimativa pro mês.",
                ),
            },
            use_container_width=True,
        )

        col_save, _ = st.columns([1.2, 4])
        with col_save:
            salvar = st.button(
                "Salvar Estimativa CCEE",
                key="gsf_btn_salvar_estimativas",
                use_container_width=True, type="primary",
                help="Grava as estimativas no arquivo data/"
                     "gsf_projecao_ccee.json (visível pra todos os usuários).",
            )
        if salvar:
            # Converte de volta pra dict {YYYY-MM: float}. None/NaN dropados.
            novas = {}
            for m, val in zip(meses, edited["GSF estimado (%)"]):
                if val is None or pd.isna(val):
                    continue
                novas[m.strftime("%Y-%m")] = float(val)
            if _salvar_estimativas_ccee(novas):
                st.toast("Estimativa CCEE atualizada.", icon="✅")
                st.rerun()
            else:
                st.toast(
                    "Não foi possível salvar (disco somente leitura?).",
                    icon="⚠️",
                )


def _marcar_datas_custom_gsf() -> None:
    """on_change dos date_inputs: marca que o usuario mexeu nas datas.

    Enquanto gsf_datas_custom eh False, trocar de granularidade re-deriva
    a janela pro default da nova granularidade (sempre mostra ate o
    ultimo periodo disponivel). Quando True, a janela custom persiste
    entre granularidades — soh muda a agregacao subjacente.
    """
    st.session_state["gsf_datas_custom"] = True


# =============================================================================
# Shadow state (Fase 2D++ bugfix — widget cleanup cross-tab)
# =============================================================================
# Problema: ao navegar pra outra aba, Streamlit faz cleanup das widget keys
# nao renderizadas (gsf_granularidade, gsf_data_ini, gsf_data_fim).
# Keys nao-widget (gsf_datas_custom, gsf_granularidade_anterior) sobrevivem,
# criando estado inconsistente que reseta a UI pro default ao voltar.
#
# Solucao: espelhar as widget keys em keys "shadow" (prefixo gsf_shadow_*),
# que NAO sao widget keys e sobrevivem ao cleanup. Restaurar a partir do
# shadow no INICIO do render se as widget keys sumiram.
#
# Pattern alinhado com CLAUDE.md §5.18 (backup paralelo de selectbox sujeito
# a cleanup).

_SHADOW_MAP_GSF = {
    "gsf_granularidade": "gsf_shadow_granularidade",
    "gsf_data_ini":      "gsf_shadow_data_ini",
    "gsf_data_fim":      "gsf_shadow_data_fim",
}


def _shadow_restore_gsf() -> None:
    """Detecta widget cleanup (key ausente mas shadow presente) e restaura.

    Roda no INICIO do render, ANTES de qualquer setdefault — assim o
    setdefault nao sobrescreve a restauracao com defaults.

    Edge case 1a render absoluta: nem widget keys nem shadows existem;
    restore eh no-op; init defaults rola normal.
    """
    for src, dst in _SHADOW_MAP_GSF.items():
        if src not in st.session_state and dst in st.session_state:
            st.session_state[src] = st.session_state[dst]


def _shadow_sync_gsf() -> None:
    """Espelha widget keys → shadow keys.

    Chamada no FIM do render (apos todas as mutacoes programaticas) e
    sempre que o codigo muda widget keys (init, re-derivacao por troca
    de granularidade). on_change dos selectbox NAO precisa chamar — o
    proximo render acaba sincronizando aqui.
    """
    for src, dst in _SHADOW_MAP_GSF.items():
        if src in st.session_state:
            st.session_state[dst] = st.session_state[src]


def _agregar_trimestral(df_mensal: pd.DataFrame) -> pd.DataFrame:
    """Agrega df mensal -> trimestral. Index = start-of-quarter.

    GSF recalculado do trimestre (sum / sum), NAO media de GSFs mensais
    — semantica contabil correta. EXCEÇÃO: trimestres com pelo menos um
    mês de estimativa CCEE (is_estimativa=True em algum mês) usam MÉDIA
    SIMPLES dos GSFs mensais, porque as estimativas vêm como % publicada
    pela CCEE (não temos como decompor em sum_geracao / sum_gf separados).

    Drop de trimestres incompletos NO INICIO (n_meses < 3) — exceto o
    ultimo, que pode ser parcial (trim em andamento).
    """
    # Defensivo: se df não tem coluna is_estimativa (caminho legacy), defaulta
    # tudo False — comportamento idêntico ao original.
    df_work = df_mensal.copy()
    if "is_estimativa" not in df_work.columns:
        df_work["is_estimativa"] = False

    # 'QS' = quarter start frequency. Index resultante eh start-of-quarter
    # (jan/abr/jul/out) — alinhado com convencao do projeto (1o dia do periodo).
    agg = df_work.groupby(pd.Grouper(freq="QS")).agg(
        sum_geracao_mre_mwh=("sum_geracao_mre_mwh", "sum"),
        sum_gf_mre_mwh=("sum_gf_mre_mwh", "sum"),
        fonte_dado=("fonte_dado", "first"),
        n_meses=("gsf", "count"),
        is_estimativa=("is_estimativa", "any"),
        mean_gsf=("gsf", "mean"),  # fallback usado em trimestres com estimativa
    )
    if agg.empty:
        agg["gsf"] = []
        return agg.drop(columns=["n_meses", "mean_gsf"])

    # Drop incompletos no INICIO; preserva o ultimo mesmo se parcial.
    max_idx = agg.index.max()
    mask = (agg["n_meses"] >= 3) | (agg.index == max_idx)
    agg = agg[mask].copy()

    # Trimestres só com dados oficiais → sum/sum (contábil correto).
    # Trimestres com ≥1 mês estimado → média simples dos GSFs mensais
    # (mistura oficial + estimativa do CCEE).
    agg["gsf"] = np.where(
        agg["is_estimativa"],
        agg["mean_gsf"],
        agg["sum_geracao_mre_mwh"] / agg["sum_gf_mre_mwh"],
    )
    agg = agg.drop(columns=["n_meses", "mean_gsf"])
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

    Janela default = Jan/(ano-corrente − 1) até Dez/ano-corrente — cobre
    2 anos cheios (histórico fechado + ano em curso, incluindo estimativas
    CCEE pros meses futuros do ano corrente). Clamp aos limites do df_agg
    quando dataset não cobre toda a faixa.
    """
    if df_agg.empty:
        hoje = pd.Timestamp.today().normalize()
        return hoje.date(), hoje.date()
    primeiro_ts = df_agg.index.min()
    ultimo_ts = df_agg.index.max()

    hoje = pd.Timestamp.today().normalize()
    data_ini_ts = pd.Timestamp(f"{hoje.year - 1}-01-01")
    data_fim_ts = pd.Timestamp(f"{hoje.year}-12-01")

    # Clamp aos limites reais do dataset (incluindo estimativas).
    if data_ini_ts < primeiro_ts:
        data_ini_ts = primeiro_ts
    if data_fim_ts > ultimo_ts:
        data_fim_ts = ultimo_ts

    # Pra trimestral, snap pro start-of-quarter (df_agg.index é start-of-Q).
    if granularidade == "trimestral":
        data_ini_ts = data_ini_ts.to_period("Q").start_time
        data_fim_ts = data_fim_ts.to_period("Q").start_time

    return data_ini_ts.date(), data_fim_ts.date()


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
    # showlegend=False: a área vermelha é auto-explicativa (cor já comunica
    # déficit), tirar do legend libera espaço pra GSF + Estimativa CCEE
    # caberem em 1 linha com fonte maior.
    fig.add_trace(go.Scatter(
        x=x, y=y_baixo,
        mode="lines",
        line=dict(color=_TRANSPARENT, width=0),
        fill="tonexty",
        fillcolor=_FILL_DEFICIT,
        name="Déficit",
        hoverinfo="skip",
        showlegend=False,
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
    # showlegend=False: idem trace de Déficit — área azul claro já comunica
    # "energia secundária" pelo contexto visual (acima da linha 100% =
    # paridade GF). Tirar libera espaço pra legend ficar em 1 linha.
    fig.add_trace(go.Scatter(
        x=x, y=y_alto,
        mode="lines",
        line=dict(color=_TRANSPARENT, width=0),
        fill="tonexty",
        fillcolor=_FILL_SECUNDARIA,
        name="Secundária",
        hoverinfo="skip",
        showlegend=False,
    ))

    # ---- Linha PRINCIPAL GSF (POR CIMA dos fills) ----
    # Quando df contém estimativas CCEE (coluna is_estimativa), quebra em 3
    # traces pra ter linha sólida nos meses oficiais + tracejada nos
    # estimados, com ponte invisível conectando os dois segmentos.
    # Hover dos estimados tem sufixo "(estimativa CCEE)".
    is_est = (
        df["is_estimativa"].values if "is_estimativa" in df.columns
        else np.zeros(len(df), dtype=bool)
    )
    has_estimativa = bool(is_est.any())

    if not has_estimativa:
        # Caminho legacy: linha única (comportamento original 100% preservado).
        fig.add_trace(go.Scatter(
            x=x, y=y_gsf_pct,
            mode="lines",
            line=dict(color=COR_TEXTO, width=2),
            name="GSF",
            hovertemplate="GSF: %{y:.2f}%<extra></extra>",
        ))
    else:
        # Com estimativa: 3 traces (real sólido / ponte tracejada sem hover /
        # estimativa tracejada). Idêntico ao pattern §5.78 (Receita Modulação).
        y_real = np.where(~is_est, y_gsf_pct, np.nan)
        y_est  = np.where(is_est,  y_gsf_pct, np.nan)
        # Ponte: último real + primeiro estimado (pra continuidade visual).
        y_bridge = np.full(len(df), np.nan)
        idx_real = np.where(~is_est)[0]
        idx_est  = np.where(is_est)[0]
        if len(idx_real) > 0 and len(idx_est) > 0:
            i_ult_real  = idx_real[-1]
            i_prim_est  = idx_est[0]
            # Só faz sentido conectar se um vem direto após o outro temporalmente.
            if i_prim_est == i_ult_real + 1:
                y_bridge[i_ult_real] = y_gsf_pct[i_ult_real]
                y_bridge[i_prim_est] = y_gsf_pct[i_prim_est]

        # Trace 1: parte REAL (sólida, com hover padrão).
        fig.add_trace(go.Scatter(
            x=x, y=y_real,
            mode="lines",
            line=dict(color=COR_TEXTO, width=2),
            name="GSF",
            hovertemplate="GSF: %{y:.2f}%<extra></extra>",
            connectgaps=False,
            legendgroup="gsf",
        ))
        # Trace 2: PONTE (tracejada, sem hover, sem markers — só conecta).
        if not np.all(np.isnan(y_bridge)):
            fig.add_trace(go.Scatter(
                x=x, y=y_bridge,
                mode="lines",
                line=dict(color=COR_TEXTO, width=2, dash="dash"),
                hoverinfo="skip",
                showlegend=False,
                connectgaps=False,
            ))
        # Trace 3: ESTIMATIVA CCEE (tracejada, com hover diferenciado).
        fig.add_trace(go.Scatter(
            x=x, y=y_est,
            mode="lines",
            line=dict(color=COR_TEXTO, width=2, dash="dash"),
            name="Estimativa CCEE",
            hovertemplate=(
                "<i>(estimativa CCEE)</i><br>"
                "GSF: %{y:.2f}%<extra></extra>"
            ),
            connectgaps=False,
            legendgroup="gsf",
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
    # Font size 14 + cor COR_TEXTO (#313131 preto Bradesco) — refino 2D+++
    # (legenda default em cinza pequena tinha legibilidade pior).
    # Legenda nativa do Plotly DESABILITADA — renderizamos uma legend HTML
    # custom abaixo do chart via st.markdown (controle total do layout
    # com display:flex, garante 1 linha sem brigar com auto-wrap do Plotly).
    layout["showlegend"] = False
    fig.update_layout(
        **layout,
        # Título removido — agora renderizado como markdown subtitle ANTES
        # do chart (padrão das outras abas: subtitle Bebas Neue com
        # border-bottom preto). Ver render_aba_gsf.
        # Altura 460 (original) — não precisa de margin.b extra porque a
        # legenda Plotly foi desabilitada. Legenda custom HTML é renderizada
        # FORA do chart (st.markdown abaixo do st.plotly_chart).
        height=460,
        margin=dict(b=50, t=30, l=50, r=30),
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
    - Linhas com Energia Secundaria (GSF > 1.0) destacadas em azul-céu
      (rgba(135, 206, 235, 0.3)) — MESMA cor da área Secundária no chart
      pra criar conexão visual entre tabela e gráfico
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
    /* .secundaria sobrepoe a alternancia (especificidade igual, vem depois).
       Cor MESMA da área Secundária no chart Plotly (_FILL_SECUNDARIA) →
       cria conexão visual: linha azul-claro na tabela = mês acima da
       paridade GF (100%) = energia secundária. */
    .gsf-tab-12m tbody tr.secundaria td {{ background: {_FILL_SECUNDARIA}; }}
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


def render_aba_gsf(user: str | None = None) -> None:
    """Entry point da sub-aba GSF (chamada de app.py)."""
    # FIRST: restaura widget keys do shadow se Streamlit fez cleanup
    # ao sair da aba. Tem que vir ANTES de setdefault — senao o
    # setdefault sobrescreveria a restauracao com defaults.
    _shadow_restore_gsf()

    # Header padrao do projeto. Margens calibradas pra alinhar a linha com o
    # fim da barra vermelha vertical + dar respiro pros labels dos controles:
    #   margin-top: -0.2rem → compensa o gap default do Streamlit entre blocos
    #     (sem isso a linha aparece abaixo do fim da barra vermelha)
    #   margin-bottom: 1.2rem → afasta os controles da linha (sem isso os
    #     labels tipo "Data inicial" colam visualmente na linha)
    #   margin-left: 12px → alinha o início da linha com o padding-left do
    #     h1 global (gap entre barra vermelha vertical e linha horizontal —
    #     em vez do "L colado")
    st.markdown("# GSF — FATOR DE AJUSTE DO MRE")
    st.markdown(
        '<div style="border-bottom: 2px solid #313131; '
        'margin: -0.2rem 0 1.2rem 12px;"></div>',
        unsafe_allow_html=True,
    )

    # Carregar dados
    with st.spinner("Carregando GSF (cold ~25s na 1ª vez; warm-disk ~0.06s)..."):
        df = load_gsf_mensal()

    if df.empty:
        st.error("load_gsf_mensal() retornou DataFrame vazio.")
        return

    # Mergeia estimativas CCEE (admin) no df oficial → meses futuros sem
    # dado oficial ganham linha is_estimativa=True. Mês que tem ambos
    # (oficial + estimativa) → oficial vence, estimativa é ignorada.
    is_admin = user in ADMIN_USERS
    # Preview mode (admin-only): permite ao admin ver a tela exatamente
    # como um usuário comum (sem badge, sem editor). Pattern espelhando
    # §5.78 (Receita Modulação). Lido AQUI, antes do merge/render.
    preview_user_gsf = (
        is_admin and st.session_state.get("gsf_preview_user", False)
    )
    is_admin_efetivo = is_admin and not preview_user_gsf
    estimativas_ccee = _carregar_estimativas_ccee()
    df = _merge_estimativas_no_df(df, estimativas_ccee)

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

    # Larguras: De/Ate alargadas (1.5 -> 2) pra caber "Mar/2025" sem
    # cortar. Spacer encolheu (5.2 -> 4.2). Soma total preservada (15.2).
    cols = st.columns([2, 1, 1, 1, 4.2, 2, 2])
    with cols[0]:
        # Label placeholder pra alinhar verticalmente com De/Ate. Os
        # selectbox De/Ate tem labels visiveis ("De", "Ate") que ocupam
        # ~16px acima do widget; sem o placeholder, a granularidade
        # ficaria mais alta. Padrao da decisao CLAUDE.md §5.15.
        st.markdown(
            '<div style="font-size:0.75rem; line-height:1.2; '
            'margin-bottom:2px; color:transparent; user-select:none;">·</div>',
            unsafe_allow_html=True,
        )
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

    # Sincroniza shadow apos todas as mutacoes programaticas
    # (init defaults, granularity-change re-derive/convert, snap).
    # Garante que cross-tab navegando depois disso restaura tudo.
    _shadow_sync_gsf()

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

    # ----- Subtítulo Bauhaus do gráfico (padrão das outras abas) -----
    # Bebas Neue uppercase com border-bottom preto → mesma assinatura
    # visual de Capacidade, Modulação, Receita Modulação, etc.
    st.markdown(
        f'<div style="display:flex; justify-content:space-between; '
        f'align-items:baseline; '
        f"font-family:'Bebas Neue', sans-serif; "
        f'font-size:1.1rem; letter-spacing:0.08em; color:{COR_TEXTO}; '
        f'margin: 0.6rem 0 0.3rem 0; padding-bottom:3px; '
        f'border-bottom: 2px solid {COR_TEXTO};">'
        f'<span>FATOR DE AJUSTE DO MRE (GSF) · SIN</span>'
        f'<span>{LABELS_GRANULARIDADE[granularidade]}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Gráfico principal (df_grafico filtrado + granularidade pro eixo X).
    fig = _construir_figura_gsf(df_grafico, granularidade)
    st.plotly_chart(fig, use_container_width=True)

    # Legenda HTML custom (centralizada, 1 linha garantida com display:flex)
    # — substitui a legenda nativa do Plotly que insistia em quebrar.
    # 4 itens: Déficit (área vermelha), Secundária (área azul-céu), GSF
    # (linha sólida), Estimativa CCEE (linha tracejada). Ordem: áreas
    # primeiro (esquerda), linhas depois (direita).
    st.markdown(
        f"""
        <div style="display:flex; justify-content:center; align-items:center;
                    gap:28px; font-family:'Inter', sans-serif; font-size:15px;
                    color:{COR_TEXTO}; margin:-0.5rem 0 0.5rem 0;
                    white-space:nowrap;">
            <span style="display:inline-flex; align-items:center; gap:8px;">
                <span style="display:inline-block; width:24px; height:14px;
                             background:{_FILL_DEFICIT};"></span>
                Déficit
            </span>
            <span style="display:inline-flex; align-items:center; gap:8px;">
                <span style="display:inline-block; width:24px; height:14px;
                             background:{_FILL_SECUNDARIA};"></span>
                Secundária
            </span>
            <span style="display:inline-flex; align-items:center; gap:8px;">
                <span style="display:inline-block; width:32px; height:2px;
                             background:{COR_TEXTO};"></span>
                GSF
            </span>
            <span style="display:inline-flex; align-items:center; gap:8px;">
                <span style="display:inline-block; width:32px; height:0;
                             border-top:2px dashed {COR_TEXTO};"></span>
                Estimativa CCEE
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Tabela "Detalhamento — Últimos 12 meses" (Fase 2C).
    # Decisao: SEMPRE fixa nos ultimos 12 meses, INDEPENDENTE dos period
    # controls do grafico. Tabela = "estado recente"; grafico = "evolucao".
    # Por isso usa `df` (completo), nao `df_grafico` (filtrado).
    st.markdown("### Detalhamento — Últimos 12 meses")
    st.markdown(_construir_tabela_12m(df), unsafe_allow_html=True)

    # Footnote com fórmula validada (R3 dos refinos 2B+) — vem ANTES do
    # botão de download (atribuição/contexto da tabela).
    st.caption(
        "**Fórmula** (Regras de Comercialização CCEE, módulo MRE, "
        "item MR.2.1): GSF = Σ(GERACAO_MRE) / Σ(GARANTIA_FISICA_MRE), "
        "agregando 4 submercados × todas as horas do mês. Fonte: dataset "
        "CCEE GERACAO_HORARIA_SUBMERCADO. Validado em 12/12 meses contra "
        "valores oficiais (Power BI CCEE + InfoPLD)."
    )

    # ----- Botão Baixar CSV (padrão Curtailment) -----
    # ABAIXO do footnote (decisão UX: footnote dá contexto/fonte da tabela
    # antes de oferecer o download). Exporta o df_grafico filtrado (=
    # janela visível no gráfico) em CSV PT-BR (separador ;, decimal
    # vírgula, UTF-8 BOM pra Excel abrir bem). Inclui flag "Fonte" pra
    # distinguir dado oficial CCEE de estimativa.
    df_csv = df_grafico.copy()
    df_csv["Mês"] = df_csv.index.strftime("%Y-%m")
    df_csv["GSF (%)"] = (df_csv["gsf"] * 100).round(2)
    df_csv["Geração MRE (TWh)"] = (
        df_csv["sum_geracao_mre_mwh"] / 1_000_000
    ).round(2)
    df_csv["GF MRE (TWh)"] = (df_csv["sum_gf_mre_mwh"] / 1_000_000).round(2)
    df_csv["Fonte"] = df_csv["fonte_dado"].apply(
        lambda v: "Estimativa CCEE" if v == "estimativa_ccee" else "Oficial"
    )
    df_csv = df_csv[
        ["Mês", "GSF (%)", "Geração MRE (TWh)", "GF MRE (TWh)", "Fonte"]
    ]
    csv_bytes = df_csv.to_csv(
        index=False, sep=";", decimal=",",
    ).encode("utf-8-sig")
    filename = (
        f"gsf_{granularidade}_"
        f"{data_ini.strftime('%Y%m%d')}_{data_fim.strftime('%Y%m%d')}.csv"
    )
    col_dl_l, col_dl_r = st.columns([3, 1])
    with col_dl_r:
        st.download_button(
            "Baixar CSV",
            data=csv_bytes,
            file_name=filename,
            mime="text/csv",
            use_container_width=True,
        )

    # ----- Bloco Admin: checkbox preview + editor expander -----
    # Ordem nova (decisão UX): checkbox ANTES do expander (entre footnote
    # e o expander). Assim, quando admin marca preview, o expander some
    # logo abaixo do próprio checkbox — fica claro que o toggle controla
    # a visibilidade do editor. Antes ficava confuso (checkbox embaixo do
    # expander, parecia desconexo).
    if is_admin:
        st.markdown(
            '<div style="margin-top:0.4rem;"></div>', unsafe_allow_html=True,
        )
        st.checkbox(
            "👁️ Admin: Ver como usuário comum (preview)",
            key="gsf_preview_user",
            help="Esconde o editor de Estimativa CCEE pra você ver a tela "
                 "como um usuário comum veria.",
        )
        if preview_user_gsf:
            st.markdown(
                '<div style="background:#FFF3CD; border-left:4px solid '
                '#FFC107; padding:0.4rem 0.8rem; margin:0.3rem 0 0.6rem 0; '
                'font-family:Inter, sans-serif; font-size:0.85rem; '
                'color:#856404;">'
                '<b>MODO PREVIEW</b> — você está vendo a aba GSF como um '
                'usuário comum (não-admin) veria. O editor de Estimativa '
                'CCEE abaixo está oculto. Desmarque o checkbox acima pra '
                'voltar pra visão de admin.'
                '</div>',
                unsafe_allow_html=True,
            )

    # Editor (aparece logo APÓS o checkbox; em preview mode fica oculto).
    if is_admin_efetivo:
        _render_editor_estimativas_ccee(df, estimativas_ccee)

    # Expander de Diagnóstico (Fase 2A) REMOVIDO — era debug de
    # desenvolvimento, sem valor pro usuário final. Se precisar inspecionar
    # o df no futuro, basta um `print(df.tail())` temporário no código.
