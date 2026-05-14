"""
tab_receita_modulacao.py
========================

Sub-aba "Receita por Empresa" da aba Modulação.

Receita de modulação por empresa ≈ volume vendido (Vendas ACL + Vendas
líquidas no spot, MWmed → MWh) × spread de modulação PONDERADO pelo mix de
fontes da empresa (hidro/eólica/solar), por trimestre. Resultado em R$mn.

Modelo:
  - Spread por (trimestre, submercado, fonte) vem do _calcular_spread da
    aba Modulação (granularidade trimestral).
  - Cada empresa tem submercado(s) — ver EMPRESAS_SUBMERCADO (Axia é caso
    especial: ACL = média N+NE+SE+S, Spot = média N+NE) — e uma alocação %
    entre hidro/eólica/solar por trimestre (2ª tabela, editável).
  - Spread ponderado da empresa = Σ_fonte (aloc%_fonte × spread_fonte).
    Pode ser NEGATIVO (ex.: empresa muito solar → spread negativo → perda).
  - Trimestre fechado: receita do trimestre cheio.
  - Trimestre corrente (parcial): receita "até a data" (pró-rata via
    n_horas) + estimativa do trimestre cheio.
  - Trimestres futuros: estimativa usando um spread assumido (editável na
    tabela 1; default = spread ponderado corrente).
  - ACL/Spot, spread assumido dos futuros e a alocação % são premissas
    editáveis (st.data_editor), salvas por usuário num JSON.
"""

from __future__ import annotations

import json
import traceback
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.tab_modulacao import _calcular_spread


# =============================================================================
# Paleta Bauhaus
# =============================================================================

BAUHAUS_BLACK = "#1A1A1A"
BAUHAUS_CREAM = "#F5F1E8"
BAUHAUS_LIGHT = "#E8E3D4"
BAUHAUS_RED   = "#D62828"   # cor única dos gráficos (padrão das outras abas)


def _blend(hex_a: str, hex_b: str, t: float) -> str:
    """Mistura duas cores hex (t=0 → hex_a, t=1 → hex_b)."""
    a = [int(hex_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(hex_b[i:i + 2], 16) for i in (1, 3, 5)]
    c = [round(a[k] * (1 - t) + b[k] * t) for k in range(3)]
    return f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"


COR_REALIZADO = BAUHAUS_RED
COR_ESTIMATIVA = _blend(BAUHAUS_RED, BAUHAUS_CREAM, 0.62)  # vermelho esmaecido


# =============================================================================
# Empresas — submercados usados pro spread de ACL e de Spot
# =============================================================================
# Pro spread, faz-se a média do spread dos submercados listados. As demais
# empresas têm 1 submercado só; Axia é o caso especial (geração em todos).

EMPRESAS_SUBMERCADO = {
    "Auren": {"acl": ["SE"],                 "spot": ["SE"]},
    "Axia":  {"acl": ["N", "NE", "SE", "S"], "spot": ["N", "NE"]},
    "Cemig": {"acl": ["SE"],                 "spot": ["SE"]},
    "Copel": {"acl": ["S"],                  "spot": ["S"]},
    "Engie": {"acl": ["S"],                  "spot": ["S"]},
    "EQTL":  {"acl": ["NE"],                 "spot": ["NE"]},
}
EMPRESAS = sorted(EMPRESAS_SUBMERCADO, key=str.lower)

# Fontes de geração — usadas na 2ª tabela (alocação) e no spread ponderado.
FONTES = ["hidro", "eolica", "solar"]
LABELS_FONTE = {"hidro": "Hidro", "eolica": "Eólica", "solar": "Solar"}


def _label_regiao(empresa: str) -> str:
    """Rótulo compacto de região/submercado pra coluna da tabela.
    Axia → 'Todos *' (regra detalhada na nota de rodapé)."""
    if empresa == "Axia":
        return "Todos *"
    return EMPRESAS_SUBMERCADO[empresa]["acl"][0]


# =============================================================================
# Trimestres do ano corrente
# =============================================================================

ANO = datetime.now().year
_AA = ANO % 100
TRIMESTRES = [f"{q}T{_AA:02d}" for q in (1, 2, 3, 4)]

MESES_PT = {
    1: "jan", 2: "fev", 3: "mar", 4: "abr", 5: "mai", 6: "jun",
    7: "jul", 8: "ago", 9: "set", 10: "out", 11: "nov", 12: "dez",
}


def _trimestre_label(periodo_inicio) -> str:
    ts = pd.Timestamp(periodo_inicio)
    q = (ts.month - 1) // 3 + 1
    return f"{q}T{ts.year % 100:02d}"


def _horas_trimestre_cheio(label: str) -> int:
    q = int(label[0])
    ano = 2000 + int(label[2:])
    inicio = pd.Timestamp(ano, (q - 1) * 3 + 1, 1)
    fim = inicio + pd.offsets.QuarterEnd(0)
    return ((fim.normalize() - inicio.normalize()).days + 1) * 24


def _data_parcial_label(label: str, n_horas: int) -> str:
    q = int(label[0])
    ano = 2000 + int(label[2:])
    inicio = pd.Timestamp(ano, (q - 1) * 3 + 1, 1)
    ultima = inicio + pd.Timedelta(hours=max(n_horas - 1, 0))
    return f"até {ultima.day:02d}/{MESES_PT[ultima.month]}"


# =============================================================================
# Premissas — defaults + persistência por usuário
# =============================================================================
# PLACEHOLDER: ACL/Spot ilustrativos; alocação default 100% hidro (mantém o
# resultado idêntico ao modelo hidro-puro anterior até o usuário preencher).

_DEFAULT_ACL = 200.0
_DEFAULT_SPOT = 50.0
_DEFAULT_ALOC = {"hidro": 100.0, "eolica": 0.0, "solar": 0.0}

_PREMISSAS_PATH = (
    Path(__file__).resolve().parent.parent
    / "data" / "premissas_receita_modulacao.json"
)

# Versão do schema das premissas. Bump quando a semântica muda — dados
# salvos com versão anterior são ignorados (voltam pros defaults). v2:
# introduziu alocação por fonte + spread futuro com semântica "None = auto".
_PREMISSAS_VERSAO = 2

_CAMPOS_CELULA = (
    "acl", "spot", "spread", "aloc_hidro", "aloc_eolica", "aloc_solar",
)


def _premissas_default() -> dict:
    return {
        emp: {
            tri: {
                "acl": _DEFAULT_ACL, "spot": _DEFAULT_SPOT, "spread": None,
                "aloc_hidro": _DEFAULT_ALOC["hidro"],
                "aloc_eolica": _DEFAULT_ALOC["eolica"],
                "aloc_solar": _DEFAULT_ALOC["solar"],
            }
            for tri in TRIMESTRES
        }
        for emp in EMPRESAS
    }


def _carregar_premissas(user: str) -> dict:
    """Premissas salvas do usuário; cai pros defaults onde não houver/erro.
    Dados de schema antigo (sem `_versao` atual) são ignorados."""
    base = _premissas_default()
    try:
        if _PREMISSAS_PATH.exists():
            todas = json.loads(_PREMISSAS_PATH.read_text(encoding="utf-8"))
            if todas.get("_versao") != _PREMISSAS_VERSAO:
                return base  # schema antigo → ignora, usa defaults
            salvas = todas.get(user, {})
            for emp in EMPRESAS:
                for tri in TRIMESTRES:
                    cell = salvas.get(emp, {}).get(tri, {})
                    for k in _CAMPOS_CELULA:
                        if cell.get(k) is not None:
                            base[emp][tri][k] = float(cell[k])
    except Exception:
        pass
    return base


def _salvar_premissas(user: str, premissas: dict) -> bool:
    """Grava as premissas do usuário no JSON compartilhado (best-effort).

    No Streamlit Cloud o disco é efêmero (apagado em restart do container)
    — persiste localmente sempre, no Cloud só entre reinícios.
    """
    try:
        _PREMISSAS_PATH.parent.mkdir(parents=True, exist_ok=True)
        todas = {}
        if _PREMISSAS_PATH.exists():
            try:
                existente = json.loads(
                    _PREMISSAS_PATH.read_text(encoding="utf-8"))
                if existente.get("_versao") == _PREMISSAS_VERSAO:
                    todas = existente  # preserva outros usuários
            except Exception:
                pass
        todas["_versao"] = _PREMISSAS_VERSAO
        todas[user] = premissas
        _PREMISSAS_PATH.write_text(
            json.dumps(todas, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True
    except Exception:
        return False


# =============================================================================
# Spread trimestral por (trimestre, submercado, fonte)
# =============================================================================

def _spread_trimestral() -> dict:
    """{trimestre: {submercado: {fonte: {'spread': float, 'n_horas': int}}}}.
    Só inclui trimestres com dado (fechados + corrente parcial)."""
    df = _calcular_spread("trimestral", incluir_historico_completo=False)
    if df is None or df.empty:
        return {}
    df = df[df["periodo_inicio"].dt.year == ANO]
    out: dict = {}
    for _, row in df.iterrows():
        tri = _trimestre_label(row["periodo_inicio"])
        sub_d = out.setdefault(tri, {}).setdefault(row["submercado"], {})
        sub_d[row["fonte"]] = {
            "spread": float(row["spread_rs_mwh"]),
            "n_horas": int(row["n_horas"]),
        }
    return out


def _spread_fonte_rule(empresa, tri, fonte, rule, spread_tri):
    """Spread de uma fonte pra uma empresa num trimestre, pela regra
    (rule ∈ {'acl','spot'}): média sobre os submercados da regra."""
    subs = EMPRESAS_SUBMERCADO[empresa][rule]
    subs_tri = spread_tri.get(tri, {})
    vals = [
        subs_tri[s][fonte]["spread"]
        for s in subs
        if s in subs_tri and fonte in subs_tri[s]
    ]
    return sum(vals) / len(vals) if vals else None


def _spread_ponderado(empresa, tri, rule, aloc, spread_tri):
    """Spread ponderado pelo mix de fontes: Σ_fonte (aloc%_fonte × spread_fonte).
    aloc = {'hidro':%, 'eolica':%, 'solar':%}. None se faltar dado do trimestre."""
    total = 0.0
    achou = False
    for fonte in FONTES:
        sf = _spread_fonte_rule(empresa, tri, fonte, rule, spread_tri)
        if sf is None:
            continue
        achou = True
        total += (aloc.get(fonte, 0.0) / 100.0) * sf
    return total if achou else None


def _n_horas_tri(tri, spread_tri) -> int:
    """n_horas representativo de um trimestre real (média entre submercado×fonte)."""
    vals = [
        d["n_horas"]
        for fontes in spread_tri.get(tri, {}).values()
        for d in fontes.values()
    ]
    return int(sum(vals) / len(vals)) if vals else 0


def _aloc_de(premissas, emp, tri) -> dict:
    """Extrai {'hidro','eolica','solar'} (%) das premissas de uma célula."""
    return {
        "hidro": float(premissas[emp][tri].get("aloc_hidro") or 0.0),
        "eolica": float(premissas[emp][tri].get("aloc_eolica") or 0.0),
        "solar": float(premissas[emp][tri].get("aloc_solar") or 0.0),
    }


def _spreads_auto(aloc_atual, spread_tri, tris_reais) -> dict:
    """Spread ponderado "corrente" (último trimestre real, regra ACL) por
    empresa — é o default dos trimestres futuros que o usuário não editou.
    Recalculado a cada render → SEGUE mudanças na alocação de fontes."""
    if not tris_reais:
        return {e: None for e in EMPRESAS}
    ult = tris_reais[-1]
    out = {}
    for emp in EMPRESAS:
        ws = _spread_ponderado(emp, ult, "acl", aloc_atual[emp][ult], spread_tri)
        out[emp] = round(ws, 1) if ws is not None else None
    return out


def _para_salvar(premissas_atual, spreads_auto, tris_futuros) -> dict:
    """Versão das premissas pra persistir. No spread dos trimestres futuros:
    se o valor bate com o "auto" (spread ponderado corrente), salva None —
    assim, no reload, ele volta a SEGUIR a alocação. Só spread futuro
    editado MANUALMENTE pelo usuário é salvo com valor (override)."""
    out = {}
    for emp in EMPRESAS:
        out[emp] = {}
        for tri in TRIMESTRES:
            cell = dict(premissas_atual[emp][tri])
            if tri in tris_futuros:
                sp, auto = cell.get("spread"), spreads_auto.get(emp)
                if (sp is None or auto is None
                        or abs(sp - auto) <= 0.05):
                    cell["spread"] = None
            out[emp][tri] = cell
    return out


def _spread_display(empresa, tri, aloc, spread_tri):
    """Spread ponderado (regra ACL) a exibir read-only num trimestre real."""
    ws = _spread_ponderado(empresa, tri, "acl", aloc, spread_tri)
    return round(ws, 1) if ws is not None else None


# =============================================================================
# Cálculo da receita por (empresa, trimestre)
# =============================================================================

def _calcular_receita(premissas: dict, spread_tri: dict, tris_reais) -> pd.DataFrame:
    """DataFrame: empresa, trimestre, tipo, receita_realizada, receita_estimada
    (R$mn — podem ser negativas), n_horas, data_label."""
    linhas = []
    for emp in EMPRESAS:
        for tri in TRIMESTRES:
            acl = float(premissas[emp][tri].get("acl") or 0.0)
            spot = float(premissas[emp][tri].get("spot") or 0.0)
            horas_cheio = _horas_trimestre_cheio(tri)
            aloc = _aloc_de(premissas, emp, tri)

            if tri in tris_reais:
                ws_acl = _spread_ponderado(emp, tri, "acl", aloc, spread_tri)
                ws_spot = _spread_ponderado(emp, tri, "spot", aloc, spread_tri)
                if ws_acl is None or ws_spot is None:
                    continue
                n_horas = _n_horas_tri(tri, spread_tri)
                base = acl * ws_acl + spot * ws_spot
                receita_td = base * n_horas / 1e6
                if n_horas < horas_cheio - 48:  # trimestre corrente parcial
                    receita_est = base * horas_cheio / 1e6
                    tipo = "corrente"
                    data_label = _data_parcial_label(tri, n_horas)
                else:
                    receita_est = receita_td
                    tipo = "fechado"
                    data_label = "trimestre fechado"
            else:
                spread_assumido = premissas[emp][tri].get("spread")
                if spread_assumido is None:
                    continue
                receita_td = 0.0
                receita_est = (
                    (acl + spot) * float(spread_assumido) * horas_cheio / 1e6
                )
                tipo = "futuro"
                n_horas = 0
                data_label = "estimativa"

            linhas.append({
                "empresa": emp, "trimestre": tri, "tipo": tipo,
                "receita_realizada": receita_td,
                "receita_estimada": receita_est,
                "n_horas": n_horas, "data_label": data_label,
            })
    return pd.DataFrame(linhas)


# =============================================================================
# Tabelas editáveis em blocos lado a lado (st.data_editor)
# =============================================================================
# st.data_editor não suporta cabeçalho de 2 níveis; a tabela é dividida em
# blocos (1 de rótulos + 1 por trimestre), com o título de cada bloco
# fazendo o papel de cabeçalho de grupo e um gap pequeno separando-os.

# Altura fixa (px) dos blocos — mesma em todos pra alinharem topo E base.
# Cobre as 6 empresas + cabeçalho.
_ALTURA_BLOCO = 248

# CSS escopado aos wrappers das duas tabelas: gap mínimo entre blocos +
# cantos quadrados (o dashboard não usa cantos arredondados).
_CSS_TABELAS = """
<style>
.st-key-receita_tab_wrap [data-testid="stHorizontalBlock"],
.st-key-receita_aloc_wrap [data-testid="stHorizontalBlock"] {
    gap: 0.35rem !important;
}
.st-key-receita_tab_wrap, .st-key-receita_tab_wrap *,
.st-key-receita_aloc_wrap, .st-key-receita_aloc_wrap * {
    border-radius: 0 !important;
}
</style>
"""


def _titulo_bloco(texto: str) -> str:
    """HTML do título de um bloco (cabeçalho de grupo do trimestre)."""
    return (
        f'<div style="font-family:\'Bebas Neue\', sans-serif; '
        f'font-size:1rem; letter-spacing:0.08em; color:#1A1A1A; '
        f'text-align:center; margin:0 0 0.15rem 0; height:1.3rem; '
        f'line-height:1.3rem;">{texto}</div>'
    )


def _df_labels() -> pd.DataFrame:
    """Bloco de rótulos Empresa / Região (igual nas duas tabelas)."""
    return pd.DataFrame(
        {"Empresa": list(EMPRESAS),
         "Região": [_label_regiao(e) for e in EMPRESAS]},
        index=EMPRESAS,
    )


def _editor_labels(key: str) -> None:
    st.markdown(_titulo_bloco("&nbsp;"), unsafe_allow_html=True)
    st.data_editor(
        _df_labels(),
        column_config={
            "Empresa": st.column_config.TextColumn("Empresa", width="small"),
            "Região": st.column_config.TextColumn("Região", width="small"),
        },
        disabled=["Empresa", "Região"],
        hide_index=True, use_container_width=True,
        height=_ALTURA_BLOCO, key=key,
    )


def _num_cell(df, emp, col):
    v = df.loc[emp, col]
    return float(v) if v is not None and not pd.isna(v) else None


# --- Tabela 1: Vendas ACL/Spot + Spread -------------------------------------

def _render_tabela_premissas(premissas_base, aloc_atual, spreads_auto,
                             spread_tri, tris_reais) -> dict:
    """Tabela 1 (ACL/Spot/Spread). O Spread dos trimestres reais é o spread
    PONDERADO pelo mix de fontes (read-only); dos futuros é editável e o
    default segue o spread ponderado corrente (spreads_auto).

    Retorna {emp: {tri: {'acl','spot','spread'}}} — spread futuro = valor
    efetivo (pro cálculo).
    """
    st.markdown(
        '<div style="font-family:\'Inter\', sans-serif; font-size:1rem; '
        'font-weight:600; letter-spacing:0.05em; color:#1A1A1A; '
        'margin:1.8rem 0 0.4rem 0; padding-bottom:3px; '
        'border-bottom:2px solid #1A1A1A;">'
        'Premissas — Vendas ACL e Spot (MWmed) e Spread de modulação (R$/MWh)'
        '</div>',
        unsafe_allow_html=True,
    )

    out = {e: {} for e in EMPRESAS}
    with st.container(key="receita_tab_wrap"):
        cols = st.columns([1.15, 1.55, 1.55, 1.55, 1.55], gap="small")
        with cols[0]:
            _editor_labels("receita_ed_labels")

        for i, tri in enumerate(TRIMESTRES):
            eh_real = tri in tris_reais
            with cols[i + 1]:
                st.markdown(_titulo_bloco(tri), unsafe_allow_html=True)
                # Coluna Spread:
                #  - trimestres reais: read-only, spread ponderado apurado;
                #  - trimestres futuros: EDITÁVEL. Default = spread ponderado
                #    corrente (spreads_auto, recalculado a cada render → SEGUE
                #    a alocação). Se o usuário tiver salvo um override, ele
                #    tem precedência (premissas_base não-None).
                if eh_real:
                    spread_col = [
                        _spread_display(e, tri, aloc_atual[e][tri], spread_tri)
                        for e in EMPRESAS
                    ]
                else:
                    spread_col = [
                        premissas_base[e][tri].get("spread")
                        if premissas_base[e][tri].get("spread") is not None
                        else spreads_auto[e]
                        for e in EMPRESAS
                    ]
                df_q = pd.DataFrame(
                    {
                        "ACL":  [premissas_base[e][tri].get("acl") for e in EMPRESAS],
                        "Spot": [premissas_base[e][tri].get("spot") for e in EMPRESAS],
                        "Spread": spread_col,
                    },
                    index=EMPRESAS,
                )
                edited = st.data_editor(
                    df_q,
                    column_config={
                        "ACL": st.column_config.NumberColumn(
                            "ACL", help="Vendas no ACL (MWmed)",
                            format="%.0f", width="small"),
                        "Spot": st.column_config.NumberColumn(
                            "Spot", help="Vendas líquidas no spot (MWmed)",
                            format="%.0f", width="small"),
                        "Spread": st.column_config.NumberColumn(
                            "Spread",
                            help=("Spread ponderado apurado (R$/MWh)" if eh_real
                                  else "Spread ponderado corrente — default "
                                       "segue a alocação; editável (R$/MWh)"),
                            format="%.1f", width="small"),
                    },
                    disabled=(["Spread"] if eh_real else []),
                    hide_index=True, use_container_width=True,
                    height=_ALTURA_BLOCO, key=f"receita_ed_{tri}",
                )
                for emp in EMPRESAS:
                    out[emp][tri] = {
                        "acl": _num_cell(edited, emp, "ACL"),
                        "spot": _num_cell(edited, emp, "Spot"),
                        "spread": (None if eh_real
                                   else _num_cell(edited, emp, "Spread")),
                    }
    return out


# --- Tabela 2: Alocação entre fontes (%) ------------------------------------

def _render_tabela_alocacao(premissas_base) -> dict:
    """Tabela 2 (alocação % por fonte). Hidro/Eólica/Solar editáveis; cada
    linha deve somar 100% (validado com aviso — o st.data_editor não força).

    Retorna {emp: {tri: {'hidro','eolica','solar'}}}.
    """
    st.markdown(
        '<div style="font-family:\'Inter\', sans-serif; font-size:1rem; '
        'font-weight:600; letter-spacing:0.05em; color:#1A1A1A; '
        'margin:1.4rem 0 0.4rem 0; padding-bottom:3px; '
        'border-bottom:2px solid #1A1A1A;">'
        'Alocação entre fontes da capacidade firme total (%)'
        '</div>',
        unsafe_allow_html=True,
    )

    out = {e: {} for e in EMPRESAS}
    with st.container(key="receita_aloc_wrap"):
        cols = st.columns([1.15, 1.55, 1.55, 1.55, 1.55], gap="small")
        with cols[0]:
            _editor_labels("receita_aloc_labels")

        for i, tri in enumerate(TRIMESTRES):
            with cols[i + 1]:
                st.markdown(_titulo_bloco(tri), unsafe_allow_html=True)
                df_q = pd.DataFrame(
                    {
                        "Hidro":  [premissas_base[e][tri].get("aloc_hidro") for e in EMPRESAS],
                        "Eólica": [premissas_base[e][tri].get("aloc_eolica") for e in EMPRESAS],
                        "Solar":  [premissas_base[e][tri].get("aloc_solar") for e in EMPRESAS],
                    },
                    index=EMPRESAS,
                )
                cfg = {
                    f: st.column_config.NumberColumn(
                        f, help=f"% da capacidade firme em {f}",
                        format="%.0f", width="small", min_value=0.0,
                    )
                    for f in ("Hidro", "Eólica", "Solar")
                }
                edited = st.data_editor(
                    df_q, column_config=cfg,
                    hide_index=True, use_container_width=True,
                    height=_ALTURA_BLOCO, key=f"receita_ed_aloc_{tri}",
                )
                for emp in EMPRESAS:
                    out[emp][tri] = {
                        "hidro": _num_cell(edited, emp, "Hidro") or 0.0,
                        "eolica": _num_cell(edited, emp, "Eólica") or 0.0,
                        "solar": _num_cell(edited, emp, "Solar") or 0.0,
                    }

    # Validação: cada linha (empresa × trimestre) deve somar 100%.
    fora = []
    for emp in EMPRESAS:
        for tri in TRIMESTRES:
            a = out[emp][tri]
            soma = a["hidro"] + a["eolica"] + a["solar"]
            if abs(soma - 100.0) > 0.5:
                fora.append(f"{emp} {tri} ({soma:.0f}%)")
    if fora:
        st.warning(
            "Alocação deve somar 100% por empresa/trimestre. Fora: "
            + ", ".join(fora)
        )
    return out


# =============================================================================
# Render do gráfico (uma empresa)
# =============================================================================

def _render_grafico(df_receita: pd.DataFrame, empresa: str) -> None:
    dfe = df_receita[df_receita["empresa"] == empresa].copy()
    if dfe.empty:
        st.warning("Sem dados de receita pra esta empresa.")
        return
    ordem = {t: i for i, t in enumerate(TRIMESTRES)}
    dfe["_ord"] = dfe["trimestre"].map(ordem)
    dfe = dfe.sort_values("_ord")

    # Rótulos do eixo X — trimestre corrente ganha o "até DD/mmm".
    x_labels = [
        f"{r['trimestre']} · {r['data_label']}" if r["tipo"] == "corrente"
        else r["trimestre"]
        for _, r in dfe.iterrows()
    ]

    realizado = dfe["receita_realizada"].tolist()
    # Sem clip — receita pode ser negativa (empresa muito solar → perda).
    estimativa_inc = (
        dfe["receita_estimada"] - dfe["receita_realizada"]
    ).tolist()

    # Texto DENTRO de cada bloco — cada número vive na sua própria trace,
    # então some/volta junto quando o usuário liga/desliga a trace na legenda.
    def _txt(vals):
        return [
            f"{v:,.0f}".replace(",", ".") if abs(v) > 0.05 else ""
            for v in vals
        ]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Realizado",
        x=x_labels, y=realizado,
        marker=dict(color=COR_REALIZADO),
        text=_txt(realizado), textposition="inside",
        insidetextanchor="middle",
        textfont=dict(family="Inter, sans-serif", size=14, color="#FFFFFF"),
        hovertemplate="Realizado: R$mn %{y:.0f}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        name="Estimativa",
        x=x_labels, y=estimativa_inc,
        marker=dict(color=COR_ESTIMATIVA),
        text=_txt(estimativa_inc), textposition="inside",
        insidetextanchor="middle",
        textfont=dict(family="Inter, sans-serif", size=14,
                      color=BAUHAUS_BLACK),
        hovertemplate="Estimativa: R$mn %{y:.0f}<extra></extra>",
    ))

    fig.update_layout(
        barmode="relative",  # empilha respeitando sinal (suporta negativos)
        height=360,
        margin=dict(l=20, r=20, t=46, b=20),
        paper_bgcolor=BAUHAUS_CREAM,
        plot_bgcolor=BAUHAUS_CREAM,
        separators=",.",
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=BAUHAUS_CREAM, bordercolor=BAUHAUS_BLACK,
            font=dict(family="'IBM Plex Mono', 'Courier New', monospace",
                      size=12, color=BAUHAUS_BLACK),
        ),
        showlegend=True,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.06,
            xanchor="left", x=0, bgcolor="rgba(0,0,0,0)",
            font=dict(family="Bebas Neue, sans-serif", size=18,
                      color=BAUHAUS_BLACK),
        ),
        xaxis=dict(
            title=None, showgrid=False, showline=True,
            linewidth=2, linecolor=BAUHAUS_BLACK,
            ticks="outside", tickcolor=BAUHAUS_BLACK,
            tickfont=dict(family="Inter, sans-serif", size=14,
                          color=BAUHAUS_BLACK),
            type="category",
        ),
        yaxis=dict(
            title=None, showgrid=True, gridcolor=BAUHAUS_LIGHT, gridwidth=1,
            showline=True, linewidth=2, linecolor=BAUHAUS_BLACK,
            ticks="outside", tickcolor=BAUHAUS_BLACK,
            tickfont=dict(family="Inter, sans-serif", size=12,
                          color=BAUHAUS_BLACK),
            zeroline=True, zerolinecolor=BAUHAUS_BLACK, zerolinewidth=1.5,
            tickformat=",.0f",
        ),
        font=dict(family="Inter, sans-serif", size=12),
    )
    st.plotly_chart(fig, use_container_width=True,
                    config={"displaylogo": False})


def _titulo_grafico(empresa: str) -> None:
    """Título Bauhaus do gráfico (padrão das outras abas)."""
    st.markdown(
        f'<div style="display:flex; justify-content:space-between; '
        f'align-items:baseline; '
        f"font-family:'Bebas Neue', sans-serif; "
        f'font-size:1.1rem; letter-spacing:0.08em; color:{BAUHAUS_BLACK}; '
        f'margin: 0.6rem 0 0.3rem 0; padding-bottom:3px; '
        f'border-bottom: 2px solid {BAUHAUS_BLACK};">'
        f'<span>RECEITA DE MODULAÇÃO ACL + SPOT · {empresa.upper()}</span>'
        f'<span>Trimestral acumulada · (R$mn)</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


# =============================================================================
# Wrapper principal
# =============================================================================

def render_aba_receita_modulacao(user: str) -> None:
    """Wrapper defensivo — captura crash e mostra stack trace na tela."""
    try:
        _render_impl(user)
    except Exception:
        st.error("⚠️ Erro ao carregar Receita por Empresa (debug ativo)")
        st.code(traceback.format_exc(), language="python")
        st.caption(
            "Este erro foi capturado para investigação. "
            "Por favor, copie o stack trace acima e reporte."
        )


def _render_impl(user: str) -> None:
    st.markdown("# RECEITA DE MODULAÇÃO")
    st.markdown(_CSS_TABELAS, unsafe_allow_html=True)

    spread_tri = _spread_trimestral()
    if not spread_tri:
        st.warning("Sem dados de spread de modulação disponíveis no momento.")
        return

    tris_reais = [t for t in TRIMESTRES if t in spread_tri]
    tris_futuros = [t for t in TRIMESTRES if t not in spread_tri]

    # Premissas base (carregadas 1×; o st.data_editor guarda os edits da sessão).
    # Chave de sessão versionada — bump força recarregar quando o schema
    # das premissas muda (ignora dados de sessão do schema antigo).
    if "receita_premissas_base_v2" not in st.session_state:
        st.session_state["receita_premissas_base_v2"] = _carregar_premissas(user)
    premissas_base = st.session_state["receita_premissas_base_v2"]

    chart_box = st.container()      # gráfico no topo (renderizado depois)

    st.markdown(
        '<div style="font-family:\'Inter\', sans-serif; '
        'font-size:0.85rem; color:#6B6B6B; font-style:italic; '
        'margin:0.2rem 0 1rem 0;">'
        'Cálculo aproximado: receita ≈ (Vendas ACL + Vendas líquidas no spot, '
        'em MWmed convertidas a MWh) × spread de modulação ponderado pelo mix '
        'de fontes da empresa (hidro/eólica/solar). Pode ser negativa (empresa '
        'muito exposta a solar → spread negativo). Trimestre corrente é '
        'pró-rata até a última data com dado; trimestres futuros usam, por '
        'default, o spread ponderado corrente (editável na tabela).'
        '</div>',
        unsafe_allow_html=True,
    )

    tab1_box = st.container()       # tabela 1 (posicionada acima da tabela 2)

    # Tabela 2 (alocação) — renderizada aqui no código (precisa vir antes da
    # tabela 1, que usa a alocação pra calcular o spread ponderado), mas
    # posicionada visualmente DEPOIS via o container tab1_box.
    aloc_atual = _render_tabela_alocacao(premissas_base)

    # Spread ponderado "corrente" por empresa — default dos trimestres
    # futuros não-editados; recalculado de aloc_atual → segue a alocação.
    spreads_auto = _spreads_auto(aloc_atual, spread_tri, tris_reais)

    # Tabela 1 (no container reservado acima da tabela 2).
    with tab1_box:
        premissas_acl = _render_tabela_premissas(
            premissas_base, aloc_atual, spreads_auto, spread_tri, tris_reais)

    # Nota da Axia (vale pras duas tabelas — "Todos *").
    st.markdown(
        '<div style="font-family:\'Inter\', sans-serif; font-size:0.8rem; '
        'color:#5A5A5A; font-style:italic; margin:0.35rem 0 0.6rem 0;">'
        '(*) Axia: ACL = média do spread de todos os submercados; '
        'Spot = média de N e NE.'
        '</div>',
        unsafe_allow_html=True,
    )

    # Premissas atuais = ACL/Spot/Spread (tabela 1) + alocação (tabela 2).
    premissas_atual = {}
    for emp in EMPRESAS:
        premissas_atual[emp] = {}
        for tri in TRIMESTRES:
            premissas_atual[emp][tri] = {
                **premissas_acl[emp][tri],
                "aloc_hidro": aloc_atual[emp][tri]["hidro"],
                "aloc_eolica": aloc_atual[emp][tri]["eolica"],
                "aloc_solar": aloc_atual[emp][tri]["solar"],
            }

    col_btn, _ = st.columns([1, 4])
    with col_btn:
        salvar = st.button("Salvar premissas", use_container_width=True)
    if salvar:
        # st.toast: notificação transitória (aparece e some sozinha) — evita
        # que o usuário ache que o salvamento é automático.
        ok = _salvar_premissas(
            user, _para_salvar(premissas_atual, spreads_auto, tris_futuros))
        if ok:
            st.toast("Premissas salvas.", icon="✅")
        else:
            st.toast(
                "Não foi possível salvar (disco somente leitura?).",
                icon="⚠️",
            )

    # Cálculo + gráfico (no container do topo).
    df_receita = _calcular_receita(premissas_atual, spread_tri, tris_reais)
    with chart_box:
        st.markdown(
            '<div style="margin-top:0.7rem;"></div>', unsafe_allow_html=True,
        )
        st.session_state.setdefault("receita_empresa", EMPRESAS[0])
        cols_emp = st.columns([1, 1, 1, 1, 1, 1, 3])
        for _i, _emp in enumerate(EMPRESAS):
            with cols_emp[_i]:
                _ativo = st.session_state["receita_empresa"] == _emp
                if st.button(
                    _emp, key=f"btn_receita_emp_{_emp}",
                    type="primary" if _ativo else "secondary",
                    use_container_width=True,
                ):
                    st.session_state["receita_empresa"] = _emp
                    st.rerun()
        empresa = st.session_state["receita_empresa"]
        _titulo_grafico(empresa)
        _render_grafico(df_receita, empresa)
