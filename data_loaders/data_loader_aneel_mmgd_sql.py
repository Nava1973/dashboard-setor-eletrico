"""
data_loader_aneel_mmgd_sql.py
==============================

Loader de capacidade MMGD via ANEEL CKAN datastore_search_sql (workaround §4.11).

ARQUITETURA:
- Queries SUM agregadas paralelas via concurrent.futures.ThreadPoolExecutor
- Cache 2-camadas: @st.cache_data (RAM 30d) + parquet disk persistente
- Fallback automático pros anchor points hardcoded (data_loader_aneel_mmgd.py)
  se >50% das queries SQL falharem

API pública:
- load_mmgd_anual() -> pd.Series  (5 cutoffs: dez/22, dez/23, dez/24, dez/25, hoje)
- load_mmgd_mensal() -> pd.Series  (12 cutoffs: fim de mês dos últimos 12)

Ambas retornam Series com:
- Index: DatetimeIndex name='ANO_MES'
- Values: float (MW)
- Name: 'CAP_MMGD_MW'
- attrs['source']: 'sql_live' (dados reais ANEEL) OU 'fallback_anchors' (estimativa)

Decisão arquitetural ver CLAUDE.md §5.66 + §4.11.
"""
from __future__ import annotations

import datetime
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st
from curl_cffi import requests as curl_requests

from data_loaders.data_loader_aneel_mmgd import (
    MMGD_ANCHORS,
    load_mmgd_anual as load_mmgd_anual_fallback,
)

# Constantes do workaround SQL (CLAUDE.md §4.11)
SQL_URL = "https://dadosabertos.aneel.gov.br/api/3/action/datastore_search_sql"
RESOURCE_ID = "b1bd71e7-d0ad-4214-9053-cbd58e9564a7"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": "https://dadosabertos.aneel.gov.br/",
}

# Cache disk
_CACHE_DIR = Path("./cache/mmgd_sql")
_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 dias

# Tunáveis
_MAX_WORKERS = 12       # Paralelismo (1 thread por cutoff mensal max)
_QUERY_TIMEOUT = 60     # Por query (em s)
_MAX_FALHA_PCT = 0.5    # >50% falhas → fallback


def _query_sum_cutoff(cutoff_iso: str) -> Optional[float]:
    """Executa SUMIF server-side pra um único cutoff. Retorna MW ou None se falha."""
    sql = (
        f'SELECT SUM(replace("MdaPotenciaInstaladaKW", \',\', \'.\')::float) AS total_kw '
        f'FROM "{RESOURCE_ID}" '
        f'WHERE "DthAtualizaCadastralEmpreend" <= \'{cutoff_iso}\''
    )
    try:
        r = curl_requests.get(
            SQL_URL,
            params={"sql": sql},
            impersonate="chrome",
            headers=BROWSER_HEADERS,
            timeout=_QUERY_TIMEOUT,
        )
        if r.status_code != 200:
            print(f"[QUERY_FAIL] cutoff={cutoff_iso} HTTP={r.status_code} body={r.text[:100]}", file=sys.stderr)
            return None
        data = r.json()
        if not data.get("success"):
            print(f"[QUERY_FAIL] cutoff={cutoff_iso} success=False error={data.get('error', {})}", file=sys.stderr)
            return None
        records = data["result"]["records"]
        if not records or records[0]["total_kw"] is None:
            print(f"[QUERY_FAIL] cutoff={cutoff_iso} empty records or null total_kw", file=sys.stderr)
            return None
        return float(records[0]["total_kw"]) / 1000.0  # kW → MW
    except Exception as e:
        print(f"[QUERY_FAIL] cutoff={cutoff_iso} EXCEPTION {type(e).__name__}: {e}", file=sys.stderr)
        return None


def _query_series_paralela(cutoffs: list[pd.Timestamp]) -> Optional[pd.Series]:
    """Executa N queries paralelas (1 por cutoff). Retorna Series ou None se >50% falhas."""
    resultados: dict[pd.Timestamp, Optional[float]] = {}

    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(cutoffs))) as executor:
        futures = {
            executor.submit(_query_sum_cutoff, cutoff.strftime("%Y-%m-%d")): cutoff
            for cutoff in cutoffs
        }
        for future in as_completed(futures):
            cutoff = futures[future]
            try:
                resultados[cutoff] = future.result()
            except Exception:
                resultados[cutoff] = None

    falhas = sum(1 for v in resultados.values() if v is None)
    if falhas / len(cutoffs) > _MAX_FALHA_PCT:
        return None  # Sinaliza fallback necessário

    # Build series com cutoffs ordenados; substitui None por NaN (raro caso parcial)
    series_dict = {cutoff: resultados.get(cutoff, None) for cutoff in sorted(cutoffs)}
    series = pd.Series(series_dict, name="CAP_MMGD_MW", dtype=float)
    series.index.name = "ANO_MES"
    return series


def _carregar_de_cache_disk(filename: str) -> Optional[pd.Series]:
    """Tenta carregar parquet do disk se válido (mtime < TTL)."""
    cache_path = _CACHE_DIR / filename
    if not cache_path.exists():
        return None
    age_seconds = time.time() - cache_path.stat().st_mtime
    if age_seconds > _CACHE_TTL_SECONDS:
        return None
    try:
        df = pd.read_parquet(cache_path)
        series = df["CAP_MMGD_MW"]
        series.attrs["source"] = "sql_live"
        return series
    except Exception:
        return None


def _salvar_no_cache_disk(series: pd.Series, filename: str) -> None:
    """Salva Series como parquet no cache disk."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _CACHE_DIR / filename
    try:
        series.to_frame().to_parquet(cache_path, compression="snappy")
    except Exception:
        pass  # Cache disk é best-effort


@st.cache_resource(ttl=_CACHE_TTL_SECONDS, show_spinner=False)
def load_mmgd_anual() -> pd.Series:
    """Versão SQL-backed do load_mmgd_anual (substitui anchor hardcoded como default).

    5 cutoffs: dez/2022, dez/2023, dez/2024, dez/2025, último mês fechado.
    Convenção de index: 1º do mês (igual SIGA), para permitir df.index.map(series) limpo.
    Cutoffs de query usam fim de mês (pra capturar todos cadastros).
    Último ponto é o ÚLTIMO MÊS FECHADO (não today()) — evita misalignment com SIGA.
    Fallback automático pra anchor hardcoded se SQL falhar em >50% das queries.
    """
    # 1ª tentativa: cache disk
    cached = _carregar_de_cache_disk("anual.parquet")
    if cached is not None:
        return cached

    # 2ª tentativa: queries paralelas SQL
    # IMPORTANTE: cutoffs de query usam FIM do mês (pra capturar todos os registros
    # cadastrados naquele mês), mas o INDEX retornado normaliza pra 1º do mês
    # — convenção idêntica ao SIGA pra permitir merge limpo via df.index.map().
    hoje = pd.Timestamp(datetime.date.today())
    mes_corrente_inicio = hoje.replace(day=1)
    ultimo_mes_fechado_inicio = mes_corrente_inicio - pd.DateOffset(months=1)
    ultimo_mes_fechado_fim = mes_corrente_inicio - pd.DateOffset(days=1)

    pares = [
        (pd.Timestamp("2022-12-31"), pd.Timestamp("2022-12-01")),
        (pd.Timestamp("2023-12-31"), pd.Timestamp("2023-12-01")),
        (pd.Timestamp("2024-12-31"), pd.Timestamp("2024-12-01")),
        (pd.Timestamp("2025-12-31"), pd.Timestamp("2025-12-01")),
        (ultimo_mes_fechado_fim, ultimo_mes_fechado_inicio),
    ]
    cutoffs_query = [p[0] for p in pares]
    cutoffs_index = [p[1] for p in pares]

    series_raw = _query_series_paralela(cutoffs_query)

    if series_raw is not None:
        # Re-indexar com convenção SIGA (1º do mês) — IMPORTANTE: usar .loc[cutoff_q]
        # porque _query_series_paralela retorna Series com index ORDENADO (sorted),
        # garantindo lookup correto independente da ordem original dos cutoffs.
        series = pd.Series(
            [series_raw.loc[cutoff_q] for cutoff_q in cutoffs_query],
            index=cutoffs_index,
            name="CAP_MMGD_MW",
        )
        series.index.name = "ANO_MES"
        series.attrs["source"] = "sql_live"
        _salvar_no_cache_disk(series, "anual.parquet")
        return series

    # 3ª tentativa: fallback pros anchors hardcoded
    fallback = load_mmgd_anual_fallback()
    fallback.attrs["source"] = "fallback_anchors"
    return fallback


@st.cache_resource(ttl=_CACHE_TTL_SECONDS, show_spinner=False)
def load_mmgd_mensal() -> pd.Series:
    """Carrega capacidade MMGD acumulada por mês (últimos 12 MESES FECHADOS).

    Útil pra modo Mensal da aba Capacidade. 12 queries paralelas (~5-15s 1º load).

    Convenção de index: 1º do mês (igual SIGA), pra permitir df.index.map(series).
    Cutoffs de query usam FIM do mês (pra capturar todos cadastros).
    EXCLUI mês corrente parcial — só meses fechados.

    Fallback: Series vazia com attrs['source']='unavailable' se SQL falhar
    (modo Mensal não tem anchor hardcoded pra cair).
    """
    cached = _carregar_de_cache_disk("mensal.parquet")
    if cached is not None:
        return cached

    # Últimos 12 MESES FECHADOS (exclui mês corrente parcial).
    # IMPORTANTE: cutoffs de query usam FIM do mês (pra capturar todos cadastros),
    # mas o INDEX retornado normaliza pra 1º do mês — convenção idêntica ao SIGA
    # pra permitir merge limpo via df.index.map() (mesmo padrão do load_mmgd_anual).
    hoje = pd.Timestamp(datetime.date.today())
    mes_corrente_inicio = hoje.replace(day=1)
    ultimo_mes_fechado_inicio = mes_corrente_inicio - pd.DateOffset(months=1)

    # Gerar 12 1º-do-mês terminando no último mês fechado
    inicios_mes = pd.date_range(
        end=ultimo_mes_fechado_inicio,
        periods=12,
        freq="MS",  # MonthStart: 01/AAAA-MM
    ).tolist()

    pares = [
        (inicio + pd.offsets.MonthEnd(0), inicio)
        for inicio in inicios_mes
    ]
    cutoffs_query = [p[0] for p in pares]
    cutoffs_index = [p[1] for p in pares]

    series_raw = _query_series_paralela(cutoffs_query)

    if series_raw is not None:
        # Re-indexar com convenção SIGA (1º do mês) — mesmo padrão do load_mmgd_anual.
        series = pd.Series(
            [series_raw.loc[cutoff_q] for cutoff_q in cutoffs_query],
            index=cutoffs_index,
            name="CAP_MMGD_MW",
        )
        series.index.name = "ANO_MES"
        series.attrs["source"] = "sql_live"
        _salvar_no_cache_disk(series, "mensal.parquet")
        return series

    # Modo Mensal não tem anchor hardcoded — retorna Series vazia + flag
    empty = pd.Series(dtype=float, name="CAP_MMGD_MW")
    empty.index.name = "ANO_MES"
    empty.attrs["source"] = "unavailable"
    return empty
