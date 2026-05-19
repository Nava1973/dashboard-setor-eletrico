"""
data_loader_receita_eneva.py
============================

Calcula a receita estimada (R$) das 5 usinas Parnaíba da Eneva
(Parnaíba I, II, III+VI, IV, V), em base horária, com agregação mensal
e trimestral. Backend do gráfico "Receita Estimada" na sub-view Eneva
da aba Despacho Térmico.

Fórmulas por hora (decodificadas do backtesting Excel fornecido pelo user
em ``geracao_eneva_2023_2026_completo_v4.xlsx``, colunas J/K/L/M):

    ACR_h    = (Mérito_h + UnitCommit_h) × CVU_semana × %ACR × (1 - Perdas)
    SPOT_h   = ((Mérito_h + UnitCommit_h) × %Spot + GSUB_h + Inflex_h)
               × PLD_Norte_h × (1 - Perdas)
    EXPORT_h = Exportação_h × 400 × (1 - Perdas)
    TOTAL_h  = ACR_h + SPOT_h + EXPORT_h

Onde:
    - Mérito_h, UnitCommit_h, Exportação_h, GSUB_h, Inflex_h vêm do dataset
      ONS ``geracao_termica_despacho_2_ho`` (já carregado por
      ``data_loader_termico.py`` mês a mês). Mantém-se a substituição
      ``val_verifinflexibilidade ← val_verifinflexpura`` quando aplicável
      (decisão Fase A.1 do termico).
    - CVU_semana vem do dataset ONS ``cvu-usitermica`` (S3 path
      ``cvu_usitermica_se/CVU_USINA_TERMICA_{ano}.parquet``), tomando a
      última revisão (``num_revisao = max`` por (semana, usina)).
    - PLD_Norte_h vem do loader CCEE ``load_pld_horaria()`` filtrando
      submercado N.
    - %ACR, %Spot, Perdas são parâmetros por usina (ver ``PARAMS_PARNAIBA``).

Regra sazonal Parnaíba II:
    Em janeiro e em agosto-dezembro, contratos ACR e Spot estão
    suspensos — ACR_h = SPOT_h = 0 nesses meses. Apenas EXPORT_h
    permanece. (Origem: fórmulas IF(OR(MONTH=1, MONTH>=8), 0, ...) das
    células J/K na planilha Parnaíba II.)

Schema de saída de ``calcular_receita_horaria()`` (long-form por hora):
    data_hora (datetime64[ns]), usina_eneva (str),
    receita_acr (float, R$), receita_spot (float, R$),
    receita_export (float, R$), receita_total (float, R$).

Agregação:
    ``agregar_receita_mensal(df_h, ate_data)`` → DF
        (periodo: Period[M], receita_acr_mn, receita_spot_mn,
         receita_export_mn, receita_total_mn, eh_parcial: bool,
         ate_dia: int|None)  [valores em R$ milhões]
    ``agregar_receita_trimestral(df_h, ate_data)`` → DF análogo com
        periodo: Period[Q].

Caching:
    - Reusa ``data_loader_termico._carregar_mes_com_cache`` (cascade
      disco + RAM já existente) pra geração horária.
    - Adiciona cache disco próprio em ``~/.cache/dashboard-setor-eletrico/
      cvu_v1/CVU_USINA_TERMICA_{ano}.parquet`` para CVU.
    - Top-level ``carregar_receita_eneva_horaria()`` com
      ``@st.cache_resource(ttl=6h)`` (mesmo padrão de carregar_termico).
"""

from __future__ import annotations

import functools
import gc
import io
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

try:
    from curl_cffi import requests as creq
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    import requests as creq  # type: ignore

# Reusa pipeline disco+RAM e normalização já estabelecidos no termico —
# importar privados é aceitável dentro do mesmo pacote ``data_loaders``.
from data_loaders.data_loader_termico import (
    _carregar_mes_com_cache,
    _normalizar_motivos,
)


# ---------------------------------------------------------------------------
# Constantes — parâmetros das 5 usinas Parnaíba
# ---------------------------------------------------------------------------

# Lista canônica das 5 usinas em ordem cronológica de entrada em operação.
PARNAIBAS: list[str] = [
    "PARNAÍBA I",
    "PARNAÍBA II",
    "PARNAÍBA III+VI",
    "PARNAÍBA IV",
    "PARNAÍBA V",
]

# Mapeamento Parnaíba → aliases ONS no dataset GERAÇÃO TÉRMICA DESPACHO 2.
# (Subset de ENEVA_USINAS em data_loader_termico — mantido aqui pra evitar
# acoplamento e permitir aliases extras pro CVU sem mexer no termico.)
PARNAIBAS_ALIASES_ONS_GEN: dict[str, list[str]] = {
    "PARNAÍBA I":       ["Maranhão 4", "Maranhão 5", "Maranhão IV", "Maranhão V"],
    "PARNAÍBA II":      ["Maranhão III"],
    "PARNAÍBA III+VI":  ["Nova Venécia 2"],
    "PARNAÍBA IV":      ["Parnaíba 4", "Parnaíba IV"],
    "PARNAÍBA V":       ["Parnaíba V"],
}

# Mapeamento Parnaíba → nom_usina do dataset CVU. Nomes truncados (10 chars).
# Validado em scripts/discover/test contra parquet CVU_USINA_TERMICA_2026 do ONS.
# MARANHAOIV e MARANHAO V têm CVU idêntico por semana (mesma usina física,
# 2 unidades geradoras) — qualquer um serve; escolhemos MARANHAOIV pra ser
# determinístico. PARNA_IV_F é variante de regime restrito de Parnaíba IV —
# considerada outlier e excluída (Excel do user usa só PARNAIB_IV).
PARNAIBAS_ALIASES_CVU: dict[str, list[str]] = {
    "PARNAÍBA I":       ["MARANHAOIV"],
    "PARNAÍBA II":      ["MARANHAO3"],
    "PARNAÍBA III+VI":  ["N.VENECIA2"],
    "PARNAÍBA IV":      ["PARNAIB_IV"],
    "PARNAÍBA V":       ["PARNAIBA_V"],
}

# Parâmetros por usina extraídos das células R2/R3/R6 das sheets do Excel
# de backtesting (decodificadas via openpyxl data_only=False).
#   pct_acr   = participação do contrato ACR no merit + unit commitment
#   pct_spot  = participação Spot (complemento até 100%)
#   perdas    = fator multiplicativo (1 - perdas) aplicado a TODAS as receitas
#               (valor 0.045 = 4,5% para todas as 5 usinas)
#
# Decisão (Excel): pct_acr + pct_spot pode somar < 1 (resíduo "non-merchant"
# nas usinas com contratos parcialmente alocados). Mantemos os 2 separados
# em vez de derivar um do outro — exato igual ao Excel.
PARAMS_PARNAIBA: dict[str, dict[str, float]] = {
    "PARNAÍBA I":       {"pct_acr": 0.7377, "pct_spot": 0.2623, "perdas": 0.045},
    "PARNAÍBA II":      {"pct_acr": 0.9184, "pct_spot": 0.0816, "perdas": 0.045},
    "PARNAÍBA III+VI":  {"pct_acr": 0.7424, "pct_spot": 0.2576, "perdas": 0.045},
    "PARNAÍBA IV":      {"pct_acr": 0.0000, "pct_spot": 1.0000, "perdas": 0.045},
    "PARNAÍBA V":       {"pct_acr": 0.9400, "pct_spot": 0.0600, "perdas": 0.045},
}

# Receita de exportação: preço fixo R$/MWh aplicado a Exportação_h × (1 - perdas).
# Valor 400 confirmado nas células L de TODAS as 5 sheets do Excel.
PRECO_EXPORTACAO_BRL_MWH: float = 400.0

# Regra sazonal Parnaíba II: meses em que ACR/SPOT = 0.
# Origem: IF(OR(MONTH(A)=1, MONTH(A)>=8), 0, ...) nas células J/K da sheet Parnaíba II.
MESES_PARNAIBA_II_OFFSEASON: set[int] = {1, 8, 9, 10, 11, 12}

# Janela de receita: começa em 2023-01-01 (1T23, conforme spec do user).
ANO_INI_RECEITA: int = 2023

# ---------------------------------------------------------------------------
# Cache local — CVU ANUAL
# ---------------------------------------------------------------------------

_CACHE_VERSION_CVU = "cvu_v1"
_CACHE_BASE_NAME = "dashboard-setor-eletrico"

URL_PATTERN_CVU = (
    "https://ons-aws-prod-opendata.s3.amazonaws.com/"
    "dataset/cvu_usitermica_se/CVU_USINA_TERMICA_{ano}.parquet"
)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": "https://dados.ons.org.br/",
}


@functools.lru_cache(maxsize=1)
def _get_cache_dir_cvu() -> Optional[Path]:
    """Diretório writable pra cache CVU. None se tudo falhar (no-op silencioso)."""
    candidates = [
        Path.home() / ".cache" / _CACHE_BASE_NAME / _CACHE_VERSION_CVU,
        Path(tempfile.gettempdir()) / _CACHE_BASE_NAME / _CACHE_VERSION_CVU,
    ]
    for d in candidates:
        try:
            d.mkdir(parents=True, exist_ok=True)
            t = d / ".write_test"
            t.touch()
            t.unlink()
            return d
        except Exception:
            continue
    return None


def _registrar_erro(msg: str) -> None:
    """Acumula em st.session_state['_debug_erros'] (padrão do projeto)."""
    try:
        if "_debug_erros" not in st.session_state:
            st.session_state["_debug_erros"] = []
        st.session_state["_debug_erros"].append(
            f"[{datetime.now().strftime('%H:%M:%S')}] [receita_eneva] {msg}"
        )
    except Exception:
        print(f"[receita_eneva] {msg}")


def _http_get(url: str, timeout: int = 180) -> Optional[bytes]:
    """GET com curl_cffi (impersonate=chrome). None em 404 ou erro."""
    try:
        if HAS_CURL_CFFI:
            r = creq.get(
                url, impersonate="chrome", headers=BROWSER_HEADERS, timeout=timeout,
            )
        else:
            r = creq.get(url, headers=BROWSER_HEADERS, timeout=timeout)
        if r.status_code == 200 and len(r.content) > 0:
            return r.content
        if r.status_code == 404:
            return None
        _registrar_erro(f"HTTP {r.status_code} em {url[-80:]}")
        return None
    except Exception as e:
        _registrar_erro(f"Falha GET {url[-80:]}: {type(e).__name__}: {e}")
        return None


def _eh_cache_valido_cvu(ano: int) -> bool:
    """Cache vale pra anos fechados. Ano corrente sempre re-baixa
    (CVU tem revisões semanais constantes)."""
    return ano < date.today().year


def _baixar_cvu_ano(ano: int) -> pd.DataFrame:
    """Baixa parquet anual + cacheia em disco. DF vazio em qualquer falha."""
    cache_file: Optional[Path] = None
    cache_dir = _get_cache_dir_cvu()
    if cache_dir is not None:
        cache_file = cache_dir / f"CVU_USINA_TERMICA_{ano}.parquet"

    if (
        cache_file is not None
        and cache_file.exists()
        and _eh_cache_valido_cvu(ano)
    ):
        try:
            return pd.read_parquet(cache_file)
        except Exception as e:
            _registrar_erro(f"Cache CVU {ano} corrompido: {e}")

    url = URL_PATTERN_CVU.format(ano=ano)
    content = _http_get(url)
    if content is None:
        return pd.DataFrame()
    try:
        df = pd.read_parquet(io.BytesIO(content))
    except Exception as e:
        _registrar_erro(f"Falha parse parquet CVU {ano}: {type(e).__name__}: {e}")
        return pd.DataFrame()

    if cache_file is not None:
        try:
            df.to_parquet(cache_file, index=False)
        except Exception as e:
            _registrar_erro(f"Erro salvando cache CVU {ano}: {e}")
    return df


# ---------------------------------------------------------------------------
# API pública — CVU
# ---------------------------------------------------------------------------


@st.cache_resource(ttl=60 * 60 * 6, show_spinner=False)
def carregar_cvu_parnaibas(
    ano_ini: int = ANO_INI_RECEITA,
    ano_fim: Optional[int] = None,
) -> pd.DataFrame:
    """Retorna CVU semanal das 5 Parnaíba — última revisão por (semana, usina).

    Args:
        ano_ini: ano inicial (default 2023).
        ano_fim: ano final inclusive (default ano corrente).

    Returns:
        DataFrame com colunas:
            dat_iniciosemana (datetime64[ns]): início da semana operativa
            dat_fimsemana    (datetime64[ns]): fim
            usina_eneva      (str): canônica (5 valores possíveis)
            val_cvu          (float, R$/MWh): última revisão (num_revisao max)

        Vazio se não conseguir baixar nenhum ano.
    """
    if ano_fim is None:
        ano_fim = date.today().year

    dfs: list[pd.DataFrame] = []
    nomes_cvu_to_canonica = {
        nome: canonica
        for canonica, lst in PARNAIBAS_ALIASES_CVU.items()
        for nome in lst
    }
    nomes_alvo = list(nomes_cvu_to_canonica.keys())

    for ano in range(ano_ini, ano_fim + 1):
        try:
            df_ano = _baixar_cvu_ano(ano)
            if df_ano.empty:
                continue

            # Filtrar pras 5+ usinas alvo
            sub = df_ano[df_ano["nom_usina"].isin(nomes_alvo)].copy()
            if sub.empty:
                continue

            # Última revisão por (dat_iniciosemana, nom_usina)
            sub = sub.sort_values(["dat_iniciosemana", "nom_usina", "num_revisao"])
            sub = sub.drop_duplicates(
                subset=["dat_iniciosemana", "nom_usina"], keep="last"
            )

            sub["dat_iniciosemana"] = pd.to_datetime(sub["dat_iniciosemana"])
            sub["dat_fimsemana"] = pd.to_datetime(sub["dat_fimsemana"])
            sub["val_cvu"] = pd.to_numeric(sub["val_cvu"], errors="coerce").fillna(0.0)
            sub["usina_eneva"] = sub["nom_usina"].map(nomes_cvu_to_canonica)

            dfs.append(
                sub[["dat_iniciosemana", "dat_fimsemana", "usina_eneva", "val_cvu"]]
            )
        except Exception as e:
            _registrar_erro(f"Erro CVU {ano}: {type(e).__name__}: {e}")

    if not dfs:
        return pd.DataFrame(
            columns=["dat_iniciosemana", "dat_fimsemana", "usina_eneva", "val_cvu"]
        )

    out = pd.concat(dfs, ignore_index=True)
    out = out.sort_values(["usina_eneva", "dat_iniciosemana"]).reset_index(drop=True)
    del dfs
    gc.collect()
    return out


# ---------------------------------------------------------------------------
# API pública — Geração horária Parnaíba
# ---------------------------------------------------------------------------


def _filtrar_parnaibas_e_tagear(df: pd.DataFrame) -> pd.DataFrame:
    """Filtra df_mes_raw (do ONS termico) pras 5 Parnaíba + tag usina_eneva.

    Replica a lógica de ``_mapear_eneva`` do termico mas só pras 5 usinas,
    e DELETA todas as outras linhas (in-place) pra reduzir RAM antes do concat.
    """
    if "nom_usina" not in df.columns:
        return df.iloc[0:0].copy()  # vazio com mesmas cols

    nom = df["nom_usina"].astype(str)
    df = df.copy()
    df["usina_eneva"] = pd.Series([None] * len(df), index=df.index, dtype="object")
    mask_qualquer = pd.Series(False, index=df.index)

    for canonica, aliases in PARNAIBAS_ALIASES_ONS_GEN.items():
        mask_u = pd.Series(False, index=df.index)
        for alias in aliases:
            mask_u |= nom.str.contains(alias, case=False, na=False)
        df.loc[mask_u, "usina_eneva"] = canonica
        mask_qualquer |= mask_u

    return df[mask_qualquer].copy()


@st.cache_resource(ttl=60 * 60 * 6, show_spinner=False)
def carregar_geracao_horaria_parnaibas(
    ano_ini: int = ANO_INI_RECEITA,
    ano_fim: Optional[int] = None,
) -> pd.DataFrame:
    """Geração HORÁRIA das 5 Parnaíba (din_instante preservado).

    Estratégia memory-efficient: pra cada mês, baixa parquet via
    ``_carregar_mes_com_cache`` (reusa cache disco do termico),
    filtra IMEDIATAMENTE pras 5 usinas (5/250 ≈ 2% do volume),
    normaliza motivos, agrega por (din_instante, usina_eneva).

    Args:
        ano_ini, ano_fim: janela. Default = 2023 → ano corrente.

    Returns:
        DataFrame (granularidade HORÁRIA, long-form por usina) com cols:
            data_hora                       (datetime64[ns])
            usina_eneva                     (str)
            val_verifordemmerito            (float, MWh)
            val_verifunitcommitment         (float, MWh)
            val_verifexportacao             (float, MWh)
            val_verifgsub                   (float, MWh)
            val_verifinflexibilidade        (float, MWh — c/ substituição inflexpura)

        Vazio se nenhum mês carregar.
    """
    if ano_fim is None:
        ano_fim = date.today().year

    hoje = date.today()
    dfs: list[pd.DataFrame] = []

    for ano in range(ano_ini, ano_fim + 1):
        mes_max = hoje.month if ano == hoje.year else 12
        for mes in range(1, mes_max + 1):
            try:
                df_raw = _carregar_mes_com_cache(ano, mes)
                if df_raw.empty:
                    continue

                # Filtra Parnaíba ANTES do normalize pra reduzir RAM
                df_p = _filtrar_parnaibas_e_tagear(df_raw)
                if df_p.empty:
                    del df_raw
                    continue
                del df_raw

                # Aplica substituição inflexpura globalmente (mesma lógica
                # _normalizar_motivos — mas precisa rodar APÓS filtro pra
                # economizar memória, e a substituição é por linha então
                # nao tem perda de qualidade)
                df_p = _normalizar_motivos(df_p)

                # Cria data_hora a partir de din_instante
                if "din_instante" not in df_p.columns:
                    _registrar_erro(f"din_instante ausente em {ano}-{mes:02d}")
                    continue
                df_p["data_hora"] = pd.to_datetime(
                    df_p["din_instante"], errors="coerce"
                )

                # Agrega por (data_hora, usina_eneva) — soma os 2 sub-units de
                # PARNAÍBA I (Maranhão 4 + Maranhão 5), 3 de PARNAÍBA III+VI
                # eventualmente, etc. Mantém granularidade horária.
                cols_soma = [
                    "val_verifordemmerito",
                    "val_verifunitcommitment",
                    "val_verifexportacao",
                    "val_verifgsub",
                    "val_verifinflexibilidade",
                ]
                cols_soma_existentes = [c for c in cols_soma if c in df_p.columns]
                df_agg = (
                    df_p.groupby(
                        ["data_hora", "usina_eneva"], dropna=False, as_index=False,
                    )[cols_soma_existentes]
                    .sum()
                )

                dfs.append(df_agg)
                del df_p, df_agg
                gc.collect()
            except Exception as e:
                _registrar_erro(
                    f"Erro mensal {ano}-{mes:02d}: {type(e).__name__}: {e}"
                )

    if not dfs:
        return pd.DataFrame(
            columns=[
                "data_hora", "usina_eneva",
                "val_verifordemmerito", "val_verifunitcommitment",
                "val_verifexportacao", "val_verifgsub",
                "val_verifinflexibilidade",
            ]
        )

    out = pd.concat(dfs, ignore_index=True)
    out = out.sort_values(["data_hora", "usina_eneva"]).reset_index(drop=True)
    del dfs
    gc.collect()
    return out


# ---------------------------------------------------------------------------
# API pública — PLD Norte horário (wrapper)
# ---------------------------------------------------------------------------


@st.cache_resource(ttl=60 * 60 * 6, show_spinner=False)
def carregar_pld_norte_horaria() -> pd.DataFrame:
    """Wrapper sobre load_pld_horaria com histórico completo + filtro submercado N.

    Necessário pra receita Eneva porque o default (incluir_historico_completo=False)
    só traz 2 anos — temos backtesting desde 1T23, então precisamos do range
    2021+ (PLD horário só existe a partir de 2021 mesmo).

    Returns:
        DataFrame com cols (data: datetime com hora, submercado='N', pld).
    """
    # Import dentro da função pra evitar circular import no nível do módulo.
    from data_loader import load_pld_horaria

    df = load_pld_horaria(incluir_historico_completo=True)
    if df.empty:
        return df
    return df[df["submercado"] == "N"].copy()


# ---------------------------------------------------------------------------
# API pública — Cálculo de receita
# ---------------------------------------------------------------------------


def _join_cvu_horario(
    df_gen_h: pd.DataFrame, df_cvu: pd.DataFrame,
) -> pd.DataFrame:
    """Adiciona coluna val_cvu (R$/MWh) ao df de geração horária via merge_asof.

    Estratégia: pra cada usina, alinhar cada hora à semana que a contém
    via merge_asof por dat_iniciosemana (backward). Equivale a SQL:
        cvu_h = cvu_semanal WHERE dat_iniciosemana ≤ data_hora < proxima_semana
                            AND usina = usina

    Horas fora da janela de cobertura CVU ficam com val_cvu = NaN → 0.0
    no consumidor (cálculo de receita).
    """
    if df_gen_h.empty:
        df_gen_h = df_gen_h.copy()
        df_gen_h["val_cvu"] = 0.0
        return df_gen_h
    if df_cvu.empty:
        df_gen_h = df_gen_h.copy()
        df_gen_h["val_cvu"] = 0.0
        _registrar_erro("CVU vazio — receita ACR sairá 0 em todas as horas")
        return df_gen_h

    pieces: list[pd.DataFrame] = []
    for usina in PARNAIBAS:
        gen_u = df_gen_h[df_gen_h["usina_eneva"] == usina].copy()
        if gen_u.empty:
            continue
        cvu_u = df_cvu[df_cvu["usina_eneva"] == usina].copy()
        if cvu_u.empty:
            gen_u["val_cvu"] = 0.0
            pieces.append(gen_u)
            continue

        gen_u = gen_u.sort_values("data_hora").reset_index(drop=True)
        cvu_u = cvu_u.sort_values("dat_iniciosemana").reset_index(drop=True)

        merged = pd.merge_asof(
            gen_u,
            cvu_u[["dat_iniciosemana", "val_cvu"]],
            left_on="data_hora",
            right_on="dat_iniciosemana",
            direction="backward",
        )
        merged["val_cvu"] = merged["val_cvu"].fillna(0.0)
        merged = merged.drop(columns=["dat_iniciosemana"], errors="ignore")
        pieces.append(merged)

    if not pieces:
        df_gen_h = df_gen_h.copy()
        df_gen_h["val_cvu"] = 0.0
        return df_gen_h
    return pd.concat(pieces, ignore_index=True)


def _join_pld_horario(
    df_gen_h: pd.DataFrame, df_pld_n_h: pd.DataFrame,
) -> pd.DataFrame:
    """Adiciona val_pld (R$/MWh) — PLD Norte horário — ao df de geração horária.

    df_pld_n_h: DataFrame com cols (data: datetime com hora, submercado='N', pld).
    Join direto por data_hora == data. Horas faltantes → pld = 0.
    """
    if df_pld_n_h.empty:
        out = df_gen_h.copy()
        out["val_pld"] = 0.0
        _registrar_erro("PLD Norte vazio — receita SPOT sairá 0")
        return out

    pld_slim = df_pld_n_h[["data", "pld"]].copy()
    pld_slim = pld_slim.rename(columns={"data": "data_hora", "pld": "val_pld"})
    pld_slim["val_pld"] = pd.to_numeric(pld_slim["val_pld"], errors="coerce").fillna(0.0)

    out = df_gen_h.merge(pld_slim, on="data_hora", how="left")
    out["val_pld"] = out["val_pld"].fillna(0.0)
    return out


def calcular_receita_horaria(
    df_gen_h: pd.DataFrame,
    df_cvu: pd.DataFrame,
    df_pld_n_h: pd.DataFrame,
) -> pd.DataFrame:
    """Aplica as fórmulas ACR/SPOT/EXPORT/TOTAL hora a hora.

    Args:
        df_gen_h: saída de carregar_geracao_horaria_parnaibas (horário, long).
        df_cvu: saída de carregar_cvu_parnaibas (semanal por usina).
        df_pld_n_h: PLD Norte horário (cols: data com hora, submercado, pld).
            O caller é responsável por filtrar submercado='N' antes.

    Returns:
        DataFrame com mesmas linhas de df_gen_h + 4 cols de receita (R$):
            receita_acr, receita_spot, receita_export, receita_total
        Plus colunas auxiliares val_cvu e val_pld preservadas pra debug.
    """
    if df_gen_h.empty:
        return pd.DataFrame(
            columns=[
                "data_hora", "usina_eneva",
                "receita_acr", "receita_spot", "receita_export", "receita_total",
            ]
        )

    # Joins
    df = _join_cvu_horario(df_gen_h, df_cvu)
    df = _join_pld_horario(df, df_pld_n_h)

    # Garantir cols de geração presentes
    for c in [
        "val_verifordemmerito", "val_verifunitcommitment",
        "val_verifexportacao", "val_verifgsub", "val_verifinflexibilidade",
    ]:
        if c not in df.columns:
            df[c] = 0.0

    # Parâmetros via map por usina (vetorizado)
    df["_pct_acr"] = df["usina_eneva"].map(
        {u: PARAMS_PARNAIBA[u]["pct_acr"] for u in PARNAIBAS}
    ).fillna(0.0)
    df["_pct_spot"] = df["usina_eneva"].map(
        {u: PARAMS_PARNAIBA[u]["pct_spot"] for u in PARNAIBAS}
    ).fillna(0.0)
    df["_perdas"] = df["usina_eneva"].map(
        {u: PARAMS_PARNAIBA[u]["perdas"] for u in PARNAIBAS}
    ).fillna(0.045)
    df["_fator_perdas"] = 1.0 - df["_perdas"]

    merito_uc = df["val_verifordemmerito"] + df["val_verifunitcommitment"]

    # Fórmulas
    df["receita_acr"] = (
        merito_uc * df["val_cvu"] * df["_pct_acr"] * df["_fator_perdas"]
    )
    df["receita_spot"] = (
        (
            merito_uc * df["_pct_spot"]
            + df["val_verifgsub"]
            + df["val_verifinflexibilidade"]
        )
        * df["val_pld"]
        * df["_fator_perdas"]
    )
    df["receita_export"] = (
        df["val_verifexportacao"] * PRECO_EXPORTACAO_BRL_MWH * df["_fator_perdas"]
    )

    # Regra sazonal Parnaíba II: ACR=SPOT=0 em jan + ago-dez
    mask_p2 = df["usina_eneva"] == "PARNAÍBA II"
    if mask_p2.any():
        meses = df.loc[mask_p2, "data_hora"].dt.month
        mask_offseason = mask_p2 & df["data_hora"].dt.month.isin(
            MESES_PARNAIBA_II_OFFSEASON
        )
        df.loc[mask_offseason, "receita_acr"] = 0.0
        df.loc[mask_offseason, "receita_spot"] = 0.0

    df["receita_total"] = (
        df["receita_acr"] + df["receita_spot"] + df["receita_export"]
    )

    # Cleanup
    df = df.drop(columns=["_pct_acr", "_pct_spot", "_perdas", "_fator_perdas"])
    gc.collect()
    return df


# ---------------------------------------------------------------------------
# API pública — Agregação Mensal / Trimestral
# ---------------------------------------------------------------------------


def _agregar_periodo(
    df_h: pd.DataFrame, freq: str, ate_data: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """Helper interno comum a mensal e trimestral.

    Soma todas as Parnaíba (sem breakdown) em R$ → converte pra R$ milhões.
    Marca o último período como parcial se max(data_hora) não cobrir o
    fim do período (Period.end_time).

    Args:
        df_h: saída de calcular_receita_horaria.
        freq: "M" (mensal) ou "Q" (trimestral) — usado como Period.
        ate_data: Timestamp do último ponto disponível (default: max do df).
            Necessário pra calcular "parcial até dia DD/MM" no último período.

    Returns:
        DataFrame com cols:
            periodo (Period[M|Q]): chave de agregação
            data_periodo (Timestamp): início do período (pra plot)
            label (str): "MAI/26" pra M ou "2T26" pra Q
            receita_acr_mn, receita_spot_mn, receita_export_mn, receita_total_mn
                (R$ milhões)
            eh_parcial (bool): True se max(data_hora) < periodo.end_time
            ate_dia (str|None): "DD/MM" se eh_parcial else None
    """
    cols_rec_brl = ["receita_acr", "receita_spot", "receita_export", "receita_total"]
    if df_h.empty:
        cols_out = (
            ["periodo", "data_periodo", "label"]
            + [c + "_mn" for c in cols_rec_brl]
            + ["eh_parcial", "ate_dia"]
        )
        return pd.DataFrame(columns=cols_out)

    df = df_h.copy()
    df["periodo"] = df["data_hora"].dt.to_period(freq)

    agg = (
        df.groupby("periodo", as_index=False)[cols_rec_brl]
        .sum()
        .sort_values("periodo")
        .reset_index(drop=True)
    )
    # R$ → R$ milhões
    for c in cols_rec_brl:
        agg[c + "_mn"] = agg[c] / 1_000_000.0
    agg = agg.drop(columns=cols_rec_brl)

    # data_periodo pra plot (start)
    agg["data_periodo"] = agg["periodo"].dt.start_time

    # Label PT-BR
    if freq == "M":
        meses_abrev_pt = {
            1: "JAN", 2: "FEV", 3: "MAR", 4: "ABR", 5: "MAI", 6: "JUN",
            7: "JUL", 8: "AGO", 9: "SET", 10: "OUT", 11: "NOV", 12: "DEZ",
        }
        agg["label"] = agg["periodo"].apply(
            lambda p: f"{meses_abrev_pt[p.month]}/{str(p.year)[-2:]}"
        )
    else:  # Q
        agg["label"] = agg["periodo"].apply(
            lambda p: f"{p.quarter}T{str(p.year)[-2:]}"
        )

    # Flag de parcial no último período — comparação no nível DIA (não hora).
    # Bug evitado: ate_data 2024-12-31 23:00 vs end_time 2024-12-31 23:59:59
    # marcaria 4T24 erroneamente como parcial. A regra correta é:
    # parcial ⇔ último dia coberto < último dia do período.
    if ate_data is None:
        ate_data = pd.Timestamp(df["data_hora"].max())
    agg["eh_parcial"] = False
    agg["ate_dia"] = None
    if len(agg) > 0:
        ultimo = agg.iloc[-1]["periodo"]
        ate_dia = pd.Timestamp(ate_data).normalize()
        fim_dia = pd.Timestamp(ultimo.end_time).normalize()
        if ate_dia < fim_dia:
            agg.loc[agg.index[-1], "eh_parcial"] = True
            agg.loc[agg.index[-1], "ate_dia"] = ate_dia.strftime("%d/%m")

    cols_finais = (
        ["periodo", "data_periodo", "label"]
        + [c + "_mn" for c in cols_rec_brl]
        + ["eh_parcial", "ate_dia"]
    )
    return agg[cols_finais]


def agregar_receita_mensal(
    df_h: pd.DataFrame, ate_data: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """Receita total Parnaíba consolidada por MÊS, em R$ milhões.

    Ver _agregar_periodo pra schema completo.
    """
    return _agregar_periodo(df_h, "M", ate_data)


def agregar_receita_trimestral(
    df_h: pd.DataFrame, ate_data: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """Receita total Parnaíba consolidada por TRIMESTRE, em R$ milhões.

    Ver _agregar_periodo pra schema completo.
    """
    return _agregar_periodo(df_h, "Q", ate_data)


# ---------------------------------------------------------------------------
# API pública — Cache management
# ---------------------------------------------------------------------------


def clear_receita_eneva_cache() -> None:
    """Limpa caches Streamlit + disco (CVU). Termico continua sob seu próprio
    clear_termico_cache. Best-effort em todas as camadas."""
    try:
        carregar_cvu_parnaibas.clear()
    except Exception as e:
        _registrar_erro(f"Falha clear cvu: {type(e).__name__}: {e}")
    try:
        carregar_geracao_horaria_parnaibas.clear()
    except Exception as e:
        _registrar_erro(f"Falha clear gen horária: {type(e).__name__}: {e}")

    cache_dir = _get_cache_dir_cvu()
    if cache_dir is None:
        return
    try:
        for f in cache_dir.glob("*.parquet"):
            try:
                f.unlink()
            except Exception as e:
                _registrar_erro(f"Falha unlink {f.name}: {type(e).__name__}: {e}")
    except Exception as e:
        _registrar_erro(f"Falha glob cvu cache_dir: {type(e).__name__}: {e}")
