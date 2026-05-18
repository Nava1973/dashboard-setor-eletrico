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
# Paleta — migração 2026-05-15 (Bauhaus → Bradesco).
# Single source of truth em utils/paleta_bradesco.py.
# =============================================================================

from utils.paleta_bradesco import (
    COR_FUNDO,
    COR_TEXTO,
    COR_TEXTO_SECUND,
    COR_GRID,
    COR_DESTAQUE,
)

# Compat aliases — migração 2026-05-15. TODO: rename to COR_* nos consumidores.
BAUHAUS_BLACK = COR_TEXTO     # era #1A1A1A → #313131
BAUHAUS_CREAM = COR_FUNDO     # era #F5F1E8 → #FFFFFF
BAUHAUS_LIGHT = COR_GRID      # era #E8E3D4 → #E0E0E0
BAUHAUS_RED   = COR_DESTAQUE  # era #D62828 → #CC092F (vermelho Bradesco)


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

# Usuários com permissão de editar a Estimativa BBI (baseline oficial visto
# por todos). Demais usuários veem o baseline como ponto de partida e podem
# montar cenários pessoais em cima — sem afetar o BBI.
ADMIN_USERS = {"Nava", "Fagundes", "Caruso"}

# Key especial no JSON pra Estimativa BBI. Prefixo `_` separa de usernames
# reais (que nunca começam com `_`).
_BBI_KEY = "_bbi"

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
    """Cascata em 3 camadas: code defaults → Estimativa BBI (baseline
    oficial) → premissas pessoais do user. Cada camada sobrescreve a
    anterior campo a campo (None = não sobrescreve).
    Dados de schema antigo (sem `_versao` atual) são ignorados."""
    base = _premissas_default()
    try:
        if _PREMISSAS_PATH.exists():
            todas = json.loads(_PREMISSAS_PATH.read_text(encoding="utf-8"))
            if todas.get("_versao") != _PREMISSAS_VERSAO:
                return base  # schema antigo → ignora, usa defaults
            # Camada 1: Estimativa BBI; Camada 2: cenário pessoal do user
            for fonte in (todas.get(_BBI_KEY, {}), todas.get(user, {})):
                for emp in EMPRESAS:
                    for tri in TRIMESTRES:
                        cell = fonte.get(emp, {}).get(tri, {})
                        for k in _CAMPOS_CELULA:
                            if cell.get(k) is not None:
                                base[emp][tri][k] = float(cell[k])
    except Exception:
        pass
    return base


def _carregar_baseline_bbi() -> dict | None:
    """Retorna a Estimativa BBI (baseline oficial) ou None se não existir.
    Usado pra detectar se o usuário está vendo o baseline ou um cenário."""
    try:
        if not _PREMISSAS_PATH.exists():
            return None
        todas = json.loads(_PREMISSAS_PATH.read_text(encoding="utf-8"))
        if todas.get("_versao") != _PREMISSAS_VERSAO:
            return None
        return todas.get(_BBI_KEY)
    except Exception:
        return None


def _salvar_premissas(user: str, premissas: dict) -> bool:
    """Grava as premissas pessoais do user no JSON compartilhado (best-effort).

    No Streamlit Cloud o disco é efêmero (apagado em restart do container)
    — persiste localmente sempre, no Cloud só entre reinícios.
    """
    return _gravar_secao(user, premissas)


def _salvar_baseline_bbi(premissas: dict) -> bool:
    """Grava a Estimativa BBI (baseline oficial). Só admins devem chamar —
    a checagem de permissão fica na UI, esta função apenas escreve."""
    return _gravar_secao(_BBI_KEY, premissas)


def _apagar_premissas_usuario(user: str) -> bool:
    """Remove a seção pessoal do user (usado pelo Reset → BBI).
    Após isso, o user passa a ver a Estimativa BBI ao recarregar."""
    try:
        if not _PREMISSAS_PATH.exists():
            return True
        todas = json.loads(_PREMISSAS_PATH.read_text(encoding="utf-8"))
        if user in todas:
            del todas[user]
            _PREMISSAS_PATH.write_text(
                json.dumps(todas, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return True
    except Exception:
        return False


def _gravar_secao(chave: str, premissas: dict) -> bool:
    """Grava uma seção qualquer no JSON (user ou _bbi), preservando o resto."""
    try:
        _PREMISSAS_PATH.parent.mkdir(parents=True, exist_ok=True)
        todas = {}
        if _PREMISSAS_PATH.exists():
            try:
                existente = json.loads(
                    _PREMISSAS_PATH.read_text(encoding="utf-8"))
                if existente.get("_versao") == _PREMISSAS_VERSAO:
                    todas = existente  # preserva outras seções
            except Exception:
                pass
        todas["_versao"] = _PREMISSAS_VERSAO
        todas[chave] = premissas
        _PREMISSAS_PATH.write_text(
            json.dumps(todas, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True
    except Exception:
        return False


def _premissas_iguais(a: dict, b: dict | None) -> bool:
    """Compara dois dicts de premissas com tolerância pequena pra floats.
    Usado pra detectar se o usuário está com o baseline BBI puro ou se já
    divergiu (cenário pessoal)."""
    if b is None:
        return False
    for emp in EMPRESAS:
        for tri in TRIMESTRES:
            ac = a.get(emp, {}).get(tri, {})
            bc = b.get(emp, {}).get(tri, {})
            for k in _CAMPOS_CELULA:
                av, bv = ac.get(k), bc.get(k)
                if av is None and bv is None:
                    continue
                if av is None or bv is None:
                    return False
                if abs(float(av) - float(bv)) > 1e-6:
                    return False
    return True


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
    (R$mn — podem ser negativas), n_horas, data_label, acl_mwmed, spot_mwmed,
    total_mwmed, spread_aplicado (R$/MWh — médio total já ponderado por
    submercado e fontes; trimestres reais usam regra ACL, futuros o assumido)."""
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
                # Spread "exibido" = mesmo valor da coluna Spread da Tabela 1
                # (ponderado regra ACL — coerente com o que o usuário vê).
                spread_aplicado = ws_acl
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
                spread_aplicado = float(spread_assumido)

            linhas.append({
                "empresa": emp, "trimestre": tri, "tipo": tipo,
                "receita_realizada": receita_td,
                "receita_estimada": receita_est,
                "n_horas": n_horas, "data_label": data_label,
                "acl_mwmed": acl, "spot_mwmed": spot,
                "total_mwmed": acl + spot,
                "spread_aplicado": spread_aplicado,
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
        f'font-size:1rem; letter-spacing:0.08em; color:{COR_TEXTO}; '
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
        hide_index=True, width="stretch",
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
        f'<div style="font-family:\'Inter\', sans-serif; font-size:1rem; '
        f'font-weight:600; letter-spacing:0.05em; color:{COR_TEXTO}; '
        f'margin:1.8rem 0 0.4rem 0; padding-bottom:3px; '
        f'border-bottom:2px solid {COR_TEXTO};">'
        f'Premissas — Vendas ACL e Spot (MWmed) e Spread de modulação (R$/MWh)'
        f'</div>',
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
                    hide_index=True, width="stretch",
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
        f'<div style="font-family:\'Inter\', sans-serif; font-size:1rem; '
        f'font-weight:600; letter-spacing:0.05em; color:{COR_TEXTO}; '
        f'margin:1.4rem 0 0.4rem 0; padding-bottom:3px; '
        f'border-bottom:2px solid {COR_TEXTO};">'
        f'Alocação entre fontes da capacidade firme total (%)'
        f'</div>',
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
                    hide_index=True, width="stretch",
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
    dfe = dfe.sort_values("_ord").reset_index(drop=True)

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

    # customdata: [spread, acl, spot, total] — só a trace de linha consome
    # esse customdata. As barras usam hoverinfo="skip" porque o R$mn já está
    # impresso DENTRO da barra (redundante repetir no hover) e o spread é
    # único por trimestre (mesmo valor pra realizado e estimado), então não
    # faz sentido separar a contribuição de cada um.
    customdata = dfe[
        ["spread_aplicado", "acl_mwmed", "spot_mwmed", "total_mwmed"]
    ].to_numpy()

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
        hoverinfo="skip",
    ))
    fig.add_trace(go.Bar(
        name="Estimativa",
        x=x_labels, y=estimativa_inc,
        marker=dict(color=COR_ESTIMATIVA),
        hoverinfo="skip",
    ))

    # --- Label única por barra (= total estimado, altura cheia da barra) ---
    # Como o hover unificou Realizado/Estimativa num único bloco (spread é
    # o mesmo nas duas categorias), a label também precisa ser única —
    # quebrar em dois números (parcial + incremento) só polui o visual.
    # Posicionamento: FORA do tip da barra (acima se positivo, abaixo se
    # negativo), texto escuro contra o fundo creme — funciona pra trimestre
    # fechado, corrente parcial e futuro sem mexer em cor de fonte por trace.
    total_vals = dfe["receita_estimada"].tolist()
    total_text = _txt(total_vals)
    total_textpos = [
        "top center" if v >= 0 else "bottom center" for v in total_vals
    ]
    fig.add_trace(go.Scatter(
        x=x_labels, y=total_vals,
        mode="text",
        text=total_text,
        textposition=total_textpos,
        textfont=dict(family="Inter, sans-serif", size=14,
                      color=BAUHAUS_BLACK),
        hoverinfo="skip", showlegend=False, cliponaxis=False,
    ))

    # --- Linha de Spread aplicado (eixo Y secundário) ---------------------
    # Cor neutra escura, fina; vértices marcados pra ancorar cada trimestre.
    # Tracejada nos trim. futuros (premissa, não realizado) e contínua nos
    # reais. Pra ter dash misto, uso 2 traces que compartilham o ponto de
    # transição (último real = primeiro futuro), mantendo a linha visualmente
    # contínua mas com estilos distintos por segmento.
    COR_SPREAD = "#3A3A3A"
    spreads = dfe["spread_aplicado"].tolist()
    tipos = dfe["tipo"].tolist()

    def _segmento(condicao):
        """Y do segmento — None nos pontos fora do segmento (Plotly não
        desenha None, mantendo o eixo X intacto)."""
        return [s if condicao(t, i) else None
                for i, (t, s) in enumerate(zip(tipos, spreads))]

    # Índice do último trimestre real (pra fazer a ponte com o tracejado).
    idx_ultimo_real = max(
        (i for i, t in enumerate(tipos) if t != "futuro"), default=-1,
    )

    y_real = _segmento(lambda t, i: t != "futuro")
    # Futuro: APENAS pontos futuros (sem o ponto de transição). Antes eu
    # incluía o ponto de transição em ambas as traces pra ter visual contínuo,
    # mas isso causava hover DUPLICADO no trimestre de transição (2T26 no
    # caso EQTL — vide bug reportado). Agora a continuidade visual vem da
    # trace "ponte" abaixo.
    y_futuro = [s if t == "futuro" else None
                for t, s in zip(tipos, spreads)]
    # Ponte: 2 pontos só (último real → primeiro futuro), tracejada, SEM
    # markers e SEM hover — só une visualmente os dois segmentos.
    y_bridge = [None] * len(spreads)
    if (idx_ultimo_real >= 0 and idx_ultimo_real + 1 < len(spreads)
            and tipos[idx_ultimo_real + 1] == "futuro"):
        y_bridge[idx_ultimo_real] = spreads[idx_ultimo_real]
        y_bridge[idx_ultimo_real + 1] = spreads[idx_ultimo_real + 1]

    # Hover da linha = ÚNICA fonte de info no tooltip. Spread em 2 decimais
    # (R$/MWh — granularidade fina importa); ACL/Spot/Total sem decimais
    # (MWmed — número arredondado é mais legível).
    # Prefixo "─●─" colorido na linha de Spread = marcador inline que deixa
    # claro qual item é o da linha. Plotly em "x unified" centraliza o
    # símbolo da trace verticalmente no bloco inteiro, então com 4 linhas
    # ele cai no meio (em "Venda ACL"); este prefixo resolve sem refactor.
    hover_line = (
        f"<span style='color:{COR_SPREAD}'>─●─</span> "
        "Spread modulação: R$/MWh %{customdata[0]:,.2f}<br>"
        "Venda ACL: %{customdata[1]:,.0f} MWmed<br>"
        "Venda Spot: %{customdata[2]:,.0f} MWmed<br>"
        "<b>Total: %{customdata[3]:,.0f} MWmed</b>"
        "<extra></extra>"
    )

    fig.add_trace(go.Scatter(
        name="Spread aplicado",
        x=x_labels, y=y_real,
        mode="lines+markers",
        line=dict(color=COR_SPREAD, width=1.6, shape="linear"),
        marker=dict(size=9, color=COR_SPREAD,
                    line=dict(width=1.2, color=BAUHAUS_CREAM)),
        yaxis="y2",
        customdata=customdata,
        hovertemplate=hover_line,
        legendgroup="spread",
        connectgaps=False,
    ))
    # Ponte tracejada (sem markers, sem hover) — só une visualmente os dois
    # segmentos. Como o hover é skip, não duplica o tooltip no trimestre de
    # transição (que continua tendo hover só pela trace real).
    if any(v is not None for v in y_bridge):
        fig.add_trace(go.Scatter(
            x=x_labels, y=y_bridge,
            mode="lines",
            line=dict(color=COR_SPREAD, width=1.6, dash="dash"),
            yaxis="y2",
            hoverinfo="skip",
            showlegend=False,
            connectgaps=False,
        ))
    # Segmento futuro — tracejado. showlegend=False pra não duplicar na legenda.
    if any(v is not None for v in y_futuro):
        fig.add_trace(go.Scatter(
            name="Spread aplicado",
            x=x_labels, y=y_futuro,
            mode="lines+markers",
            line=dict(color=COR_SPREAD, width=1.6, dash="dash"),
            marker=dict(size=9, color=COR_SPREAD,
                        line=dict(width=1.2, color=BAUHAUS_CREAM)),
            yaxis="y2",
            customdata=customdata,
            hovertemplate=hover_line,
            legendgroup="spread",
            showlegend=False,
            connectgaps=False,
        ))

    # --- Range Y1 + Y2: zona reservada pra linha de spread no topo ---
    # Problema anterior: em barras pequenas (tip perto de 0), o label da barra
    # (posicionado FORA do tip) caía na mesma faixa vertical do vértice da
    # linha de spread (puxada pro topo via Y2), gerando overlap visual.
    # Solução: estender Y1 com ~40% de headroom acima da maior barra; mapear
    # Y2 pra que os vértices da linha caiam EXATAMENTE nessa headroom.
    # Resultado: bars vivem na parte inferior, linha vive na parte superior,
    # sempre fisicamente separadas — independente do tamanho da barra.
    all_bar_vals = [v for v in realizado if v is not None]
    all_bar_vals.extend(
        v for v in dfe["receita_estimada"].tolist() if v is not None
    )
    all_bar_vals.append(0)  # garante que 0 sempre está no range
    b_min = min(all_bar_vals)
    b_max = max(all_bar_vals)
    bar_amp = max(b_max - b_min, 1.0)
    HEADROOM_TOP = 0.40  # 40% extra acima do bar_max = zona da linha
    BOTTOM_PAD = 0.05
    y1_top = b_max + HEADROOM_TOP * bar_amp
    y1_bot = b_min - BOTTOM_PAD * bar_amp
    y1_range = [y1_bot, y1_top]
    y1_height = y1_top - y1_bot

    # Y2: mapeia spread_min/max pra zona "logo acima das barras" → "quase no topo"
    spreads_clean = [s for s in spreads if s is not None]
    yaxis2_range = None
    if spreads_clean:
        s_min = min(spreads_clean)
        s_max = max(spreads_clean)
        s_diff = s_max - s_min
        if s_diff < 0.5:  # spreads quase iguais — synthesize range pra evitar
            pad = max(abs(s_max), 1.0) * 0.1
            s_min -= pad
            s_max += pad
            s_diff = s_max - s_min
        # Faixa visual reservada (em unidades Y1): de "logo acima do bar_max
        # com margem" até "quase no topo do Y1 com pequeno respiro".
        v_low = b_max + 0.12 * bar_amp
        v_high = y1_top - 0.05 * y1_height
        # Resolve y2_min/y2_max tal que s_min → v_low e s_max → v_high
        # quando projetados na mesma faixa visual do Y1.
        f_low = (v_low - y1_bot) / y1_height
        f_high = (v_high - y1_bot) / y1_height
        dy2 = s_diff / (f_high - f_low)
        y2_min = s_min - f_low * dy2
        y2_max = y2_min + dy2
        yaxis2_range = [y2_min, y2_max]

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
            # Range explícito com headroom no topo pra acomodar a linha de
            # spread numa "zona reservada" — evita overlap com label das barras.
            range=y1_range,
        ),
        # Eixo Y2 (spread): invisível por pedido do usuário — só serve pra
        # escalar a linha sem competir com o eixo das barras. O range é
        # forçado (não-autoscale) pra manter a linha no top ~25% do gráfico
        # e evitar overlap com as barras quando spread e receita têm o mesmo
        # sinal/magnitude (caso EQTL).
        yaxis2=dict(
            overlaying="y", side="right",
            showgrid=False, showline=False, zeroline=False,
            showticklabels=False, ticks="",
            title=None,
            range=yaxis2_range,
        ),
        font=dict(family="Inter, sans-serif", size=12),
    )
    st.plotly_chart(fig, width="stretch",
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
    # Título + linha preta separadora (padrão final calibrado: -0.2rem top
    # compensa gap do Streamlit; 1.2rem bottom dá respiro pros controles;
    # 12px left alinha com padding-left do h1 global → gap entre barra
    # vermelha e linha horizontal em vez do "L colado").
    st.markdown("# RECEITA DE MODULAÇÃO")
    st.markdown(
        f'<div style="border-bottom: 2px solid {BAUHAUS_BLACK}; '
        f'margin: -0.2rem 0 1.2rem 12px;"></div>',
        unsafe_allow_html=True,
    )
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

    # Permissão: admin pode gravar na Estimativa BBI; demais só na própria
    # seção. Baseline BBI carregado direto do disco pra detectar se o que
    # o user está vendo agora é o BBI puro ou se já divergiu pro cenário dele.
    is_admin = user in ADMIN_USERS
    bbi_baseline = _carregar_baseline_bbi()

    chart_box = st.container()      # gráfico no topo (renderizado depois)
    modo_box = st.container()       # rótulo "Estimativa BBI" / "Cenário pessoal"

    st.markdown(
        f'<div style="font-family:\'Inter\', sans-serif; '
        f'font-size:0.85rem; color:{COR_TEXTO_SECUND}; font-style:italic; '
        f'margin:0.2rem 0 1rem 0;">'
        f'Cálculo aproximado: receita ≈ (Vendas ACL + Vendas líquidas no spot, '
        f'em MWmed convertidas a MWh) × spread de modulação ponderado pelo mix '
        f'de fontes da empresa (hidro/eólica/solar). Pode ser negativa (empresa '
        f'muito exposta a solar → spread negativo). Trimestre corrente é '
        f'pró-rata até a última data com dado; trimestres futuros usam, por '
        f'default, o spread ponderado corrente (editável na tabela).'
        f'</div>',
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

    # --- Rótulo "modo" + botões adaptativos por permissão ---
    # IMPORTANTE: comparar contra `payload` (versão normalizada, com spreads
    # futuros = None quando coincidem com o auto), não contra `premissas_atual`
    # (versão materializada com spreads já calculados). Sem isso, o spread
    # auto-calculado em RAM vs o `None` salvo no BBI causam falso "divergiu".
    payload = _para_salvar(premissas_atual, spreads_auto, tris_futuros)

    # Modo preview do admin: lê do session_state ANTES de renderizar botões
    # (o widget checkbox em si fica DEPOIS dos botões — menos churn visual
    # quando o admin toggle). Default False na primeira visita.
    # Banner amarelo de aviso vai DEPOIS do checkbox (renderizado lá embaixo).
    preview_user = (
        is_admin and st.session_state.get("receita_preview_user", False)
    )
    is_admin_efetivo = is_admin and not preview_user

    viewing_bbi = _premissas_iguais(payload, bbi_baseline)
    with modo_box:
        if viewing_bbi:
            st.markdown(
                f'<div style="font-family:\'Bebas Neue\', sans-serif; '
                f'font-size:1rem; letter-spacing:0.08em; color:{BAUHAUS_BLACK}; '
                f'background:{BAUHAUS_LIGHT}; padding:0.4rem 0.8rem; '
                f'border-left:4px solid {BAUHAUS_RED}; margin:0.5rem 0;">'
                f'📊 ESTIMATIVA BBI'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div style="font-family:\'Inter\', sans-serif; '
                f'font-size:0.9rem; color:{COR_TEXTO_SECUND}; '
                f'background:{BAUHAUS_LIGHT}; padding:0.4rem 0.8rem; '
                f'border-left:4px solid {COR_TEXTO_SECUND}; margin:0.5rem 0; '
                f'font-style:italic;">'
                f'Cenário pessoal — diferente da Estimativa BBI'
                f'</div>',
                unsafe_allow_html=True,
            )

    if is_admin_efetivo:
        col_a, col_b, _ = st.columns([1.3, 1.3, 2.4])
        with col_a:
            salvar_bbi = st.button(
                "Salvar como Estimativa BBI", width="stretch",
                type="primary",
                help="Atualiza o baseline oficial visto por todos os usuários.",
            )
        with col_b:
            salvar = st.button(
                "Salvar minhas premissas", width="stretch",
                help="Salva apenas no seu cenário pessoal (não afeta o BBI).",
            )
        if salvar_bbi:
            if _salvar_baseline_bbi(payload):
                st.toast("Estimativa BBI atualizada.", icon="✅")
                st.rerun()  # rerun pra atualizar o rótulo "modo"
            else:
                st.toast(
                    "Não foi possível salvar (disco somente leitura?).",
                    icon="⚠️",
                )
        if salvar:
            if _salvar_premissas(user, payload):
                st.toast("Premissas pessoais salvas.", icon="✅")
            else:
                st.toast(
                    "Não foi possível salvar (disco somente leitura?).",
                    icon="⚠️",
                )
    else:
        col_a, col_b, _ = st.columns([1.3, 1.6, 2.1])
        with col_a:
            salvar = st.button(
                "Salvar minhas premissas", width="stretch",
                type="primary",
                help="Salva o cenário pessoal só pra você.",
            )
        with col_b:
            reset_bbi = st.button(
                "Resetar para Estimativa BBI", width="stretch",
                help="Apaga suas premissas e volta a ver o baseline oficial.",
            )
        if salvar:
            if _salvar_premissas(user, payload):
                st.toast("Premissas pessoais salvas.", icon="✅")
            else:
                st.toast(
                    "Não foi possível salvar (disco somente leitura?).",
                    icon="⚠️",
                )
        if reset_bbi:
            if _apagar_premissas_usuario(user):
                # Limpa session_state pra forçar recarregar do BBI.
                st.session_state.pop("receita_premissas_base_v2", None)
                st.toast("Premissas resetadas para a Estimativa BBI.",
                         icon="✅")
                st.rerun()
            else:
                st.toast("Não foi possível resetar.", icon="⚠️")

    # Checkbox de preview (admin-only) — posicionado ABAIXO dos botões pra
    # minimizar churn visual no toggle. O valor é lido lá em cima via
    # st.session_state antes da renderização dos botões; o widget aqui apenas
    # registra/atualiza o estado quando o admin clica. O banner amarelo de
    # aviso (quando preview está on) fica logo abaixo do checkbox, associado
    # visualmente ao controle que ativou ele.
    if is_admin:
        st.markdown(
            '<div style="margin-top:0.4rem;"></div>', unsafe_allow_html=True,
        )
        st.checkbox(
            "👁️ Admin: Ver como usuário comum (preview)",
            key="receita_preview_user",
            help="Mostra a tela igual a um usuário sem permissão de admin "
                 "veria — botões e contexto não-admin. Útil pra validar a UX.",
        )
        if preview_user:
            st.markdown(
                '<div style="background:#FFF3CD; border-left:4px solid #FFC107; '
                'padding:0.4rem 0.8rem; margin:0.3rem 0 0.6rem 0; '
                'font-family:Inter, sans-serif; font-size:0.85rem; '
                'color:#856404;">'
                '<b>MODO PREVIEW</b> — você está vendo a tela como um usuário '
                'comum (não-admin) veria. Os botões acima executam ações de '
                'verdade na sua conta — saving/reset afeta seu cenário pessoal.'
                '</div>',
                unsafe_allow_html=True,
            )

    # Cálculo + gráfico (no container do topo).
    df_receita = _calcular_receita(premissas_atual, spread_tri, tris_reais)
    with chart_box:
        # Spacer reduzido pra zero — o margin-bottom: 1.2rem da linha preta
        # já dá o respiro padrão. Spacer extra aqui empurrava os botões pra
        # baixo desnecessariamente.
        st.session_state.setdefault("receita_empresa", EMPRESAS[0])
        cols_emp = st.columns([1, 1, 1, 1, 1, 1, 3])
        for _i, _emp in enumerate(EMPRESAS):
            with cols_emp[_i]:
                _ativo = st.session_state["receita_empresa"] == _emp
                if st.button(
                    _emp, key=f"btn_receita_emp_{_emp}",
                    type="primary" if _ativo else "secondary",
                    width="stretch",
                ):
                    st.session_state["receita_empresa"] = _emp
                    st.rerun()
        empresa = st.session_state["receita_empresa"]
        # Spacer entre a linha de botões (Auren/Axia/etc) e o título do
        # gráfico — sem isso o título cola visualmente nos botões.
        st.markdown(
            '<div style="margin-top:1.8rem;"></div>', unsafe_allow_html=True,
        )
        _titulo_grafico(empresa)
        _render_grafico(df_receita, empresa)
