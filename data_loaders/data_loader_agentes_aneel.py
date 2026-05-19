"""
data_loader_agentes_aneel.py
============================

Carrega o dataset "Agentes de Geração de Energia Elétrica" da ANEEL,
que relaciona CEG <-> agente operador <-> CNPJ <-> % de participação.

Fonte:
    https://dadosabertos.aneel.gov.br/dataset/agentes-de-geracao-de-energia-eletrica

Resource ID conhecido (verificado): 20ef769f-a072-489d-9df4-c834529f8a78

Estratégia:
    1. CKAN datastore_search paginado (limit=32000, offset incremental)
    2. URL direta do recurso CSV como fallback

Saída:
    DataFrame com colunas padronizadas em UPPER_SNAKE_CASE,
    incluindo CNPJ_RAIZ (8 primeiros dígitos) para agregação por grupo.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
import io

import pandas as pd
import streamlit as st

try:
    from curl_cffi import requests as creq
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    import requests as creq  # type: ignore


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": "https://dadosabertos.aneel.gov.br/",
}

# CKAN endpoints
ANEEL_CKAN_BASE = "https://dadosabertos.aneel.gov.br/api/3/action"
RESOURCE_ID_AGENTES = "20ef769f-a072-489d-9df4-c834529f8a78"
DATASET_ID_AGENTES = "agentes-de-geracao-de-energia-eletrica"

# URLs alternativas
URL_DUMP = (
    f"{ANEEL_CKAN_BASE}/datastore_search?resource_id={RESOURCE_ID_AGENTES}"
    "&limit=32000&offset={offset}"
)
URL_CSV_DIRETO = (
    "https://dadosabertos.aneel.gov.br/dataset/"
    f"{DATASET_ID_AGENTES}/resource/{RESOURCE_ID_AGENTES}/download/"
    "agentes-de-geracao-de-energia-eletrica.csv"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _registrar_erro(msg: str) -> None:
    try:
        if "_debug_erros" not in st.session_state:
            st.session_state["_debug_erros"] = []
        st.session_state["_debug_erros"].append(
            f"[{datetime.now().strftime('%H:%M:%S')}] [agentes_aneel] {msg}"
        )
    except Exception:
        print(f"[agentes_aneel] {msg}")


def _http_get_json(url: str, timeout: int = 60) -> Optional[dict]:
    try:
        if HAS_CURL_CFFI:
            r = creq.get(url, impersonate="chrome",
                         headers=BROWSER_HEADERS, timeout=timeout)
        else:
            r = creq.get(url, headers=BROWSER_HEADERS, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        _registrar_erro(f"HTTP {r.status_code} em {url[-60:]}")
        return None
    except Exception as e:
        _registrar_erro(f"Falha JSON GET: {type(e).__name__}: {e}")
        return None


def _http_get_bytes(url: str, timeout: int = 90) -> Optional[bytes]:
    try:
        if HAS_CURL_CFFI:
            r = creq.get(url, impersonate="chrome",
                         headers=BROWSER_HEADERS, timeout=timeout)
        else:
            r = creq.get(url, headers=BROWSER_HEADERS, timeout=timeout)
        if r.status_code == 200 and len(r.content) > 0:
            return r.content
        _registrar_erro(f"HTTP {r.status_code} em {url[-60:]}")
        return None
    except Exception as e:
        _registrar_erro(f"Falha bytes GET: {type(e).__name__}: {e}")
        return None


def _normalizar_colunas(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().upper() for c in df.columns]
    return df


def _identificar_coluna(df: pd.DataFrame, *keywords: str) -> Optional[str]:
    for kw in keywords:
        kw_upper = kw.upper()
        for col in df.columns:
            if kw_upper in col.upper():
                return col
    return None


def _limpar_cnpj(serie: pd.Series) -> pd.Series:
    """Remove pontuação e normaliza CNPJ para 14 dígitos string."""
    return (
        serie.astype(str)
        .str.replace(r"[^0-9]", "", regex=True)
        .str.zfill(14)
    )


# ---------------------------------------------------------------------------
# Estratégias de download
# ---------------------------------------------------------------------------


def _baixar_via_ckan() -> Optional[pd.DataFrame]:
    """Estratégia 1: CKAN datastore_search paginado."""
    todos = []
    offset = 0
    limite = 32000

    while True:
        url = URL_DUMP.format(offset=offset)
        data = _http_get_json(url)
        if not data or not data.get("success"):
            if offset == 0:
                _registrar_erro("CKAN datastore_search falhou na primeira página")
                return None
            break  # paginação parou - dados parciais já carregados

        records = data.get("result", {}).get("records", [])
        if not records:
            break
        todos.extend(records)
        if len(records) < limite:
            break  # última página
        offset += limite

        # Limite de segurança
        if offset > 500_000:
            _registrar_erro("Limite de paginação atingido (>500k registros)")
            break

    if not todos:
        return None
    return pd.DataFrame(todos)


def _baixar_csv_direto() -> Optional[pd.DataFrame]:
    """Estratégia 2: download direto do CSV."""
    content = _http_get_bytes(URL_CSV_DIRETO)
    if not content:
        return None
    for sep in [";", ","]:
        for enc in ["utf-8", "latin-1", "utf-8-sig"]:
            try:
                df = pd.read_csv(
                    io.BytesIO(content),
                    sep=sep,
                    encoding=enc,
                    low_memory=False,
                )
                if len(df.columns) >= 3:
                    return df
            except Exception:
                continue
    _registrar_erro("Falha lendo CSV direto da ANEEL")
    return None


# ---------------------------------------------------------------------------
# Padronização
# ---------------------------------------------------------------------------


def _padronizar(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza schema do dataset de agentes para o padrão do dashboard."""
    df = _normalizar_colunas(df)

    col_ceg     = _identificar_coluna(df, "CEG")
    col_usina   = _identificar_coluna(df, "NOMEMPREENDIMENTO", "DSCEMPREENDIMENTO",
                                       "NOMUSINA", "NOM_USINA", "EMPREENDIMENTO")
    col_agente  = _identificar_coluna(df, "NOMAGENTE", "DSCAGENTE", "AGENTE",
                                       "RAZAOSOCIAL", "RAZAO_SOCIAL")
    col_cnpj    = _identificar_coluna(df, "NUMCPFCNPJ", "CPFCNPJ", "CNPJ")
    col_part    = _identificar_coluna(df, "PERCENTUAL", "PARTICIPACAO", "PERC")
    col_regime  = _identificar_coluna(df, "REGIME", "EXPLORACAO")
    col_fase    = _identificar_coluna(df, "FASE", "SITUACAO")

    if not col_ceg or not col_agente:
        _registrar_erro(
            f"Colunas mínimas (CEG, agente) não encontradas. "
            f"Disponíveis: {list(df.columns)[:15]}"
        )
        return pd.DataFrame()

    out = pd.DataFrame()
    out["CEG"] = df[col_ceg].astype(str).str.strip()
    out["AGENTE"] = df[col_agente].astype(str).str.strip()

    if col_usina:
        out["USINA_ANEEL"] = df[col_usina].astype(str).str.strip()
    if col_cnpj:
        out["CNPJ"] = _limpar_cnpj(df[col_cnpj])
        # CNPJ raiz = 8 primeiros dígitos (matriz/grupo societário)
        out["CNPJ_RAIZ"] = out["CNPJ"].str[:8]
    if col_part:
        out["PCT_PARTICIPACAO"] = pd.to_numeric(
            df[col_part].astype(str)
            .str.replace(",", ".", regex=False)
            .str.replace("%", "", regex=False),
            errors="coerce",
        )
    if col_regime:
        out["REGIME"] = df[col_regime].astype(str).str.strip()
    if col_fase:
        out["FASE"] = df[col_fase].astype(str).str.strip()

    # Filtra linhas com CEG válido
    out = out[out["CEG"].notna() & (out["CEG"] != "") & (out["CEG"] != "nan")]
    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


@st.cache_resource(ttl=86400 * 7, show_spinner=False)  # cache de 7 dias
def carregar_agentes_aneel() -> pd.DataFrame:
    """
    Carrega o dataset de agentes de geração da ANEEL.

    Retorna DataFrame com schema:
        CEG, AGENTE, USINA_ANEEL, CNPJ, CNPJ_RAIZ,
        PCT_PARTICIPACAO, REGIME, FASE
    """
    # Estratégia 1: CKAN paginado
    df = _baixar_via_ckan()
    if df is not None and len(df) > 0:
        return _padronizar(df)

    # Estratégia 2: CSV direto
    df = _baixar_csv_direto()
    if df is not None and len(df) > 0:
        return _padronizar(df)

    _registrar_erro("Falha em todas as estratégias de download de agentes ANEEL")
    return pd.DataFrame()


def construir_mapa_ceg_agente(
    df_agentes: pd.DataFrame,
    estrategia: str = "maior_participacao",
) -> pd.DataFrame:
    """
    A partir do dataset (que pode ter múltiplos sócios por CEG),
    constrói um mapa CEG -> 1 agente principal.

    Estratégias:
        'maior_participacao' (default): pega o sócio com maior % de participação
        'primeiro': pega a primeira ocorrência
    """
    if len(df_agentes) == 0:
        return pd.DataFrame(columns=["CEG", "AGENTE", "CNPJ", "CNPJ_RAIZ"])

    df = df_agentes.copy()

    if estrategia == "maior_participacao" and "PCT_PARTICIPACAO" in df.columns:
        df = df.sort_values(
            ["CEG", "PCT_PARTICIPACAO"],
            ascending=[True, False],
            na_position="last",
        )

    cols_keep = ["CEG", "AGENTE"]
    for col in ["CNPJ", "CNPJ_RAIZ", "PCT_PARTICIPACAO"]:
        if col in df.columns:
            cols_keep.append(col)

    return df.drop_duplicates("CEG", keep="first")[cols_keep].reset_index(drop=True)
