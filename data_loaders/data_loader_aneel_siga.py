"""
data_loader_aneel_siga.py
=========================

Loader do SIGA — Sistema de Informações de Geração da ANEEL.
Fonte PRINCIPAL de capacidade centralizada Brasil pra aba
"Capacidade Instalada (Brasil + MMGD)" (SPEC v3).

Fonte
-----
- Dataset CKAN ANEEL:
  https://dadosabertos.aneel.gov.br/dataset/siga-sistema-de-informacoes-de-geracao-da-aneel
- Resource ID: ``11ec447d-698d-4ab8-977f-b424d5deee6a``
- Endpoint base: ``https://dadosabertos.aneel.gov.br/api/3/action``
- Atualização: mensal
- Escopo: todo o parque gerador nacional com outorga ANEEL
  (SIN + sistemas isolados)
- Granularidade nativa: 1 linha por empreendimento (~25k linhas)

Estratégia de ingestão (cascata 3-tier, padrão do projeto)
----------------------------------------------------------
1. CKAN ``datastore_search`` paginado (``limit=32000``, ``offset`` incremental)
2. CKAN ``datastore_dump`` (CSV via endpoint de dump)
3. URL CSV fixa direta (último fallback)

Todos usam ``curl_cffi`` com ``impersonate="chrome"`` quando disponível
(decisão arquitetural do projeto contra Akamai/Cloudflare).

Cache (2 camadas)
-----------------
- **Disco**: ``~/.cache/dashboard-setor-eletrico/siga_v1.parquet``
  via fábrica ``_make_disk_cache_helpers`` de ``data_loader.py``
  (decisão 5.15 do CLAUDE.md). TTL 30 dias. Cascade Path.home() →
  tempfile.gettempdir() pra ambientes FS read-only.
- **RAM**: ``@st.cache_data(ttl=30 dias)`` na função pública.
- Schema do parquet: snapshot BRUTO (~25k linhas, leve) — SPEC §4.3.
  Padronização roda toda vez (custo trivial em 25k linhas).

Schema de saída (função pública ``load_siga``)
---------------------------------------------
``pd.DataFrame`` indexado por ``ANO_MES`` (Timestamp 1º dia do mês),
com 7 colunas (todos os valores em **MW**, estoque acumulado via cumsum
por fonte):

    CAP_HIDRO_MW    - UHE + PCH + CGH
    CAP_TERMICA_MW  - UTE
    CAP_NUCLEAR_MW  - UTN
    CAP_EOLICA_MW   - EOL
    CAP_SOLAR_MW    - UFV
    CAP_OUTRAS_MW   - siglas não mapeadas (defensivo, 0 no schema atual)
    CAP_TOTAL_MW    - soma das 6 anteriores

Decomposição via mapeamento ``_MAPA_FONTES`` da coluna ``SigTipoGeracao``
do schema bruto SIGA.

Filtros e premissas
-------------------
- Apenas linhas com ``SitFase`` ≈ "Operação" (case-insensitive, com
  fallback pra "OPERACAO" sem acento) — descarta construção e
  empreendimentos revogados.
- Campo de capacidade: tenta ``MdaPotenciaOutorgadaKw`` (preferencial),
  fallback automático pra ``MdaPotenciaFiscalizadaKw`` se ausente.
  Conversão kW → MW (÷ 1000).

Limitação conhecida (SPEC §2.1, §3.3)
-------------------------------------
Empreendimentos descomissionados saem da fase "Operação" no snapshot
atual. Como o filtro é aplicado APÓS o download, a série representa
**capacidade viva hoje, retroprojetada por data de entrada**.
Subestima levemente histórico. Mitigação: cross-check silencioso vs
ONS Capacidade (a ser implementado em ``data_loader_ons_capacidade.py``,
SPEC §3.5) — sinaliza divergências relevantes via ``st.warning``.

DEMO_MODE
---------
Quando ``DEMO_MODE=1`` no ambiente E todas as 3 estratégias de download
falharem, retorna série sintética 2023-01 → mês atual (base 200.000 MW
crescendo ~0,3% a.m.). NÃO é modo primário — apenas fallback (padrão
do projeto, ver ``data_loader.py:190``).

Campos relevantes do schema bruto
---------------------------------
- ``DatEntradaOperacao``        — data de início da operação (string ANEEL)
- ``SitFase``                   — fase operativa (filtrada por "Operação")
- ``MdaPotenciaOutorgadaKw``    — potência outorgada em kW (preferencial)
- ``MdaPotenciaFiscalizadaKw``  — potência fiscalizada em kW (fallback)
"""

from __future__ import annotations

import io
import os
from datetime import datetime
from typing import Optional

import pandas as pd
import streamlit as st

try:
    from curl_cffi import requests as creq
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    import requests as creq  # type: ignore

# Reuso da fábrica disk-cache de data_loader.py (decisão 5.15 do CLAUDE.md).
# Path do parquet: ~/.cache/dashboard-setor-eletrico/siga_v1.parquet
# TTL 30 dias (estoque histórico é estável; refresh raro).
from data_loader import _make_disk_cache_helpers  # type: ignore


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

ANEEL_CKAN_BASE = "https://dadosabertos.aneel.gov.br/api/3/action"
RESOURCE_ID_SIGA = "11ec447d-698d-4ab8-977f-b424d5deee6a"
DATASET_ID_SIGA = "siga-sistema-de-informacoes-de-geracao-da-aneel"

# URLs por estratégia
URL_CKAN_SEARCH_TEMPLATE = (
    f"{ANEEL_CKAN_BASE}/datastore_search"
    f"?resource_id={RESOURCE_ID_SIGA}&limit={{limit}}&offset={{offset}}"
)
URL_DATASTORE_DUMP = (
    f"https://dadosabertos.aneel.gov.br/datastore/dump/{RESOURCE_ID_SIGA}"
)
URL_CSV_DIRETO = (
    "https://dadosabertos.aneel.gov.br/dataset/"
    f"{DATASET_ID_SIGA}/resource/{RESOURCE_ID_SIGA}/download/"
    "siga-sistema-de-informacoes-de-geracao-da-aneel.csv"
)

DEMO_MODE = os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes")

# Mapeamento das siglas do SIGA pra categorias finais do DataFrame.
# Schema observado empiricamente em 2026-05-12: 7 siglas, todas mapeadas
# diretamente. "OUTRAS" fica como defesa contra siglas futuras (ex: BIO,
# WAV, HIB) — log defensivo registra qualquer sigla nova encontrada.
_MAPA_FONTES = {
    "UHE": "HIDRO",  "PCH": "HIDRO",  "CGH": "HIDRO",
    "UTE": "TERMICA",
    "UTN": "NUCLEAR",
    "EOL": "EOLICA",
    "UFV": "SOLAR",
}

# Categorias finais (ordem importa pro layout do gráfico stacked).
_CATEGORIAS = ["HIDRO", "TERMICA", "NUCLEAR", "EOLICA", "SOLAR", "OUTRAS"]

# Schema final do DataFrame retornado por load_siga().
_COLUNAS_FINAIS = [f"CAP_{c}_MW" for c in _CATEGORIAS] + ["CAP_TOTAL_MW"]


def _empty_df_siga() -> pd.DataFrame:
    """DataFrame vazio com as 7 colunas declaradas (evita KeyError na UI)."""
    df = pd.DataFrame(columns=_COLUNAS_FINAIS)
    df.index.name = "ANO_MES"
    return df


# Disk cache via fábrica padronizada (decisão 5.15). 4 closures:
# get_path, is_fresh, try_read, try_write — cada com fallback silencioso
# pra FS read-only.
(
    _get_siga_cache_path,
    _is_siga_cache_fresh,
    _try_read_siga,
    _try_write_siga,
) = _make_disk_cache_helpers("siga_v1", ttl_sec=60 * 60 * 24 * 30)


# ---------------------------------------------------------------------------
# Helpers privados
# ---------------------------------------------------------------------------


def _registrar_erro(msg: str) -> None:
    """Log de erro/info pra debug — vai pra ``st.session_state['_debug_erros']``.

    Wrapper try/except pra suportar uso fora do runtime Streamlit
    (scripts standalone como ``test_siga_loader.py``). Nesses casos
    cai em ``print()`` direto.
    """
    try:
        if "_debug_erros" not in st.session_state:
            st.session_state["_debug_erros"] = []
        st.session_state["_debug_erros"].append(
            f"[{datetime.now().strftime('%H:%M:%S')}] [siga] {msg}"
        )
    except Exception:
        print(f"[siga] {msg}")


def _http_get_json(url: str, timeout: int = 60) -> Optional[dict]:
    """GET com curl_cffi (``impersonate=chrome``) se disponível. Retorna
    JSON parseado ou ``None`` em erro."""
    try:
        if HAS_CURL_CFFI:
            r = creq.get(url, impersonate="chrome",
                         headers=BROWSER_HEADERS, timeout=timeout)
        else:
            r = creq.get(url, headers=BROWSER_HEADERS, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        _registrar_erro(f"HTTP {r.status_code} em {url[-80:]}")
        return None
    except Exception as e:
        _registrar_erro(f"Falha JSON GET: {type(e).__name__}: {e}")
        return None


def _http_get_bytes(url: str, timeout: int = 120) -> Optional[bytes]:
    """GET pra binário (CSV). Timeout maior porque dumps podem ser pesados."""
    try:
        if HAS_CURL_CFFI:
            r = creq.get(url, impersonate="chrome",
                         headers=BROWSER_HEADERS, timeout=timeout)
        else:
            r = creq.get(url, headers=BROWSER_HEADERS, timeout=timeout)
        if r.status_code == 200 and len(r.content) > 0:
            return r.content
        _registrar_erro(f"HTTP {r.status_code} em {url[-80:]}")
        return None
    except Exception as e:
        _registrar_erro(f"Falha bytes GET: {type(e).__name__}: {e}")
        return None


def _identificar_coluna(df: pd.DataFrame, *keywords: str) -> Optional[str]:
    """Match case-insensitive nas colunas do DataFrame.

    Tenta cada keyword na ordem; primeira que dá match (substring no
    nome da coluna após UPPER) é retornada. Defensivo contra variações
    de capitalização entre versões do schema ANEEL.
    """
    for kw in keywords:
        kw_upper = kw.upper()
        for col in df.columns:
            if kw_upper in str(col).upper():
                return col
    return None


# ---------------------------------------------------------------------------
# Estratégias de download (cascata 3-tier)
# ---------------------------------------------------------------------------


def _baixar_siga_via_ckan_paginado() -> Optional[pd.DataFrame]:
    """Estratégia 1: ``datastore_search`` paginado.

    SIGA tem ~25k linhas — 1 página de 32000 normalmente basta. Loop
    incremental por segurança caso o dataset cresça ou a ANEEL imponha
    page-size menor. Safety break em 200k registros.
    """
    todos = []
    offset = 0
    limit = 32000

    while True:
        url = URL_CKAN_SEARCH_TEMPLATE.format(limit=limit, offset=offset)
        data = _http_get_json(url)
        if not data or not data.get("success"):
            if offset == 0:
                _registrar_erro("CKAN datastore_search falhou na 1ª página")
                return None
            break  # paginação parou; retorna parcial

        records = data.get("result", {}).get("records", [])
        if not records:
            break
        todos.extend(records)
        if len(records) < limit:
            break  # última página
        offset += limit

        # Safety: SIGA não deve passar de ~50k mesmo em cenários extremos
        if offset > 200_000:
            _registrar_erro("Safety break em paginação CKAN (>200k registros)")
            break

    if not todos:
        return None
    return pd.DataFrame(todos)


def _baixar_siga_via_datastore_dump() -> Optional[pd.DataFrame]:
    """Estratégia 2: endpoint ``/datastore/dump/{id}`` (CSV completo)."""
    content = _http_get_bytes(URL_DATASTORE_DUMP, timeout=120)
    if not content:
        return None
    # Tenta combinações de separador × encoding (ANEEL inconsistente)
    for sep in [",", ";"]:
        for enc in ["utf-8-sig", "utf-8", "latin-1"]:
            try:
                df = pd.read_csv(io.BytesIO(content), sep=sep,
                                 encoding=enc, low_memory=False)
                if len(df.columns) >= 3:
                    return df
            except Exception:
                continue
    _registrar_erro("Falha lendo CSV de datastore_dump (sep/encoding)")
    return None


def _baixar_siga_via_url_fixa() -> Optional[pd.DataFrame]:
    """Estratégia 3: URL CSV fixa (último fallback)."""
    content = _http_get_bytes(URL_CSV_DIRETO, timeout=120)
    if not content:
        return None
    for sep in [";", ","]:
        for enc in ["utf-8-sig", "utf-8", "latin-1"]:
            try:
                df = pd.read_csv(io.BytesIO(content), sep=sep,
                                 encoding=enc, low_memory=False)
                if len(df.columns) >= 3:
                    return df
            except Exception:
                continue
    _registrar_erro("Falha lendo CSV de URL fixa (sep/encoding)")
    return None


def _baixar_siga() -> tuple[Optional[pd.DataFrame], str]:
    """Orquestra a cascata 3-tier. Retorna ``(df, estrategia_usada)``.

    Estrategia_usada: ``"ckan_paginado"`` | ``"datastore_dump"`` |
    ``"url_fixa"`` | ``"falhou"``.
    """
    df = _baixar_siga_via_ckan_paginado()
    if df is not None and len(df) > 0:
        return df, "ckan_paginado"

    df = _baixar_siga_via_datastore_dump()
    if df is not None and len(df) > 0:
        return df, "datastore_dump"

    df = _baixar_siga_via_url_fixa()
    if df is not None and len(df) > 0:
        return df, "url_fixa"

    return None, "falhou"


# ---------------------------------------------------------------------------
# Padronização (SPEC §4.4)
# ---------------------------------------------------------------------------


def _padronizar_siga(df: pd.DataFrame) -> pd.DataFrame:
    """Filtra fase, decompõe por sigla de geração, agrega mensalmente,
    retorna DataFrame com cumsum por fonte + total.

    Retorna ``pd.DataFrame`` indexado por ``ANO_MES`` (Timestamp 1º dia
    do mês), com 7 colunas (em MW, estoque acumulado por fonte):

        CAP_HIDRO_MW, CAP_TERMICA_MW, CAP_NUCLEAR_MW,
        CAP_EOLICA_MW, CAP_SOLAR_MW, CAP_OUTRAS_MW, CAP_TOTAL_MW

    DataFrame vazio (mesmas 7 colunas, sem linhas) se schema inválido.

    Tratamentos defensivos
    ----------------------
    - **Coluna de fase case-insensitive** (resolve pendência §9.2 da
      SPEC): keyword principal ``DscFaseUsina`` (nome atual confirmado
      empiricamente no schema ANEEL); fallbacks defensivos pra
      ``SitFase``/``FaseUsina``. Compara contra ``"OPERAÇÃO"`` E
      ``"OPERACAO"`` (com e sem acento).
    - **Coluna de tipo de geração case-insensitive**: keyword
      ``SigTipoGeracao``, fallback ``TipoGeracao``.
    - **Campo capacidade com fallback** (resolve pendência §9.1):
      tenta ``MdaPotenciaOutorgadaKw``; se ausente, usa
      ``MdaPotenciaFiscalizadaKw``.
    - **Mapeamento de siglas**: ``_MAPA_FONTES`` cobre as 7 siglas
      observadas (UHE/PCH/CGH/UTE/UTN/EOL/UFV). Siglas não mapeadas
      caem em ``OUTRAS`` com log defensivo no ``_debug_erros`` —
      detecta schema drift sem quebrar processamento.
    - **Datas inválidas** viram NaT e são descartadas via ``dropna``.
    - **Vírgula decimal BR** em capacidade tratada via ``str.replace``.
    """
    col_fase = _identificar_coluna(
        df, "DscFaseUsina", "SitFase", "FaseUsina"
    )
    col_data = _identificar_coluna(df, "DatEntradaOperacao")
    col_tipo = _identificar_coluna(df, "SigTipoGeracao", "TipoGeracao")
    col_cap_outorgada = _identificar_coluna(df, "MdaPotenciaOutorgadaKw")
    col_cap_fiscalizada = _identificar_coluna(df, "MdaPotenciaFiscalizadaKw")

    if not col_fase or not col_data or not col_tipo:
        _registrar_erro(
            f"Colunas mínimas ausentes. fase={col_fase}, "
            f"data={col_data}, tipo={col_tipo}. "
            f"Disponíveis: {list(df.columns)[:15]}"
        )
        return _empty_df_siga()

    # Pendência §9.1: campo de capacidade com fallback automático
    if col_cap_outorgada is not None:
        col_cap = col_cap_outorgada
        _registrar_erro(f"Capacidade: usando {col_cap_outorgada}")
    elif col_cap_fiscalizada is not None:
        col_cap = col_cap_fiscalizada
        _registrar_erro(
            f"MdaPotenciaOutorgadaKw ausente — fallback pra "
            f"{col_cap_fiscalizada}"
        )
    else:
        _registrar_erro(
            "Nenhum campo de capacidade (Outorgada/Fiscalizada) "
            f"encontrado. Disponíveis: {list(df.columns)[:15]}"
        )
        return _empty_df_siga()

    df = df.copy()

    # Pendência §9.2: filtro case-insensitive na coluna de fase
    fase_norm = df[col_fase].astype(str).str.strip().str.upper()
    mask_operacao = fase_norm.isin({"OPERAÇÃO", "OPERACAO"})
    if mask_operacao.sum() == 0:
        _registrar_erro(
            f"Nenhuma linha em fase='Operação' (coluna {col_fase}). "
            f"Valores únicos (top 10): "
            f"{sorted(fase_norm.unique())[:10]}"
        )
        return _empty_df_siga()
    df = df[mask_operacao].copy()

    # Parse de data
    df["DATA"] = pd.to_datetime(df[col_data], errors="coerce")
    df = df.dropna(subset=["DATA"])

    # ANO_MES = 1º dia do mês (Timestamp)
    df["ANO_MES"] = df["DATA"].dt.to_period("M").dt.to_timestamp()

    # Capacidade kW → MW, tratando vírgula decimal BR
    cap_str = df[col_cap].astype(str).str.replace(",", ".", regex=False)
    df["CAP_MW"] = pd.to_numeric(cap_str, errors="coerce") / 1000.0
    df = df.dropna(subset=["CAP_MW"])

    # Mapeamento sigla → categoria (fallback "OUTRAS" pra siglas novas)
    df["SIGLA"] = df[col_tipo].astype(str).str.strip().str.upper()
    df["CATEGORIA"] = df["SIGLA"].map(_MAPA_FONTES).fillna("OUTRAS")

    # Log defensivo: registra siglas não mapeadas (schema drift)
    nao_mapeadas = df[df["CATEGORIA"] == "OUTRAS"]
    if len(nao_mapeadas) > 0:
        siglas_novas = nao_mapeadas["SIGLA"].value_counts()
        for sigla, count in siglas_novas.items():
            _registrar_erro(
                f"Sigla nova encontrada (mapeada como OUTRAS): "
                f"{sigla} ({count} linhas)"
            )

    # Agrega por (ANO_MES, CATEGORIA) → pivot wide
    agg = (
        df.groupby(["ANO_MES", "CATEGORIA"])["CAP_MW"]
        .sum()
        .reset_index()
    )
    pivot = (
        agg.pivot(index="ANO_MES", columns="CATEGORIA", values="CAP_MW")
        .sort_index()
    )

    # Garante todas as 6 categorias presentes (0 onde ausente)
    pivot = pivot.reindex(columns=_CATEGORIAS, fill_value=0.0)
    pivot = pivot.fillna(0.0)

    # Cumsum por categoria (estoque acumulado por fonte)
    cumsum = pivot.cumsum()

    # Total = soma das 6 categorias (inclui OUTRAS)
    cumsum["TOTAL"] = cumsum.sum(axis=1)

    # Renomeia colunas pra padrão CAP_<X>_MW e ordena explicitamente
    cumsum = cumsum.rename(columns={c: f"CAP_{c}_MW" for c in cumsum.columns})
    cumsum = cumsum[_COLUNAS_FINAIS]
    cumsum.index.name = "ANO_MES"
    return cumsum


# ---------------------------------------------------------------------------
# Fallback DEMO (SPEC §6)
# ---------------------------------------------------------------------------


def _carregar_siga_demo() -> pd.DataFrame:
    """DataFrame sintético: 2023-01 → mês atual.

    Base 200.000 MW total decomposto em 5 fontes + outras (proporções
    aproximadas do parque Brasil 2024-2025):

        HIDRO    50%
        TERMICA  22%
        EOLICA   15%
        SOLAR    11%
        NUCLEAR   1%
        OUTRAS    1%

    Crescimento total ~0,3% a.m. (cumulativo, aplicado a cada fonte
    proporcionalmente — sem variação setorial, é apenas placeholder).

    Usado APENAS como fallback quando ``DEMO_MODE=1`` E todas as 3
    estratégias de download falharam (padrão do projeto, não é modo
    primário).
    """
    fim = pd.Timestamp.today().to_period("M").to_timestamp()
    datas = pd.date_range(start="2023-01-01", end=fim, freq="MS")
    base = 200_000.0  # 200 GW iniciais
    valores_total = [base * (1.003 ** i) for i in range(len(datas))]

    shares = {
        "HIDRO":   0.50,
        "TERMICA": 0.22,
        "NUCLEAR": 0.01,
        "EOLICA":  0.15,
        "SOLAR":   0.11,
        "OUTRAS":  0.01,
    }

    df = pd.DataFrame(index=datas)
    df.index.name = "ANO_MES"
    for cat in _CATEGORIAS:  # ordem canônica
        df[f"CAP_{cat}_MW"] = [v * shares[cat] for v in valores_total]
    df["CAP_TOTAL_MW"] = df[[f"CAP_{c}_MW" for c in _CATEGORIAS]].sum(axis=1)
    df = df[_COLUNAS_FINAIS]
    return df


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


@st.cache_data(ttl=60 * 60 * 24 * 30, show_spinner=False)
def load_siga() -> pd.DataFrame:
    """Carrega capacidade centralizada Brasil decomposta por fonte
    (SIGA/ANEEL) — fonte principal.

    Retorna ``pd.DataFrame`` indexado por ``ANO_MES`` (Timestamp 1º dia
    do mês), com 7 colunas em MW (estoque acumulado mês-a-mês por fonte):

        CAP_HIDRO_MW    - UHE + PCH + CGH
        CAP_TERMICA_MW  - UTE
        CAP_NUCLEAR_MW  - UTN
        CAP_EOLICA_MW   - EOL
        CAP_SOLAR_MW    - UFV
        CAP_OUTRAS_MW   - siglas não mapeadas (defensivo, 0 hoje)
        CAP_TOTAL_MW    - soma das 6 anteriores

    Cobertura: empreendimentos com outorga ANEEL em fase de "Operação"
    (SIN + sistemas isolados). Série é "viva hoje, retroprojetada por
    data de entrada" (SPEC §2.1).

    Ordem de tentativas
    -------------------
    1. **Cache disco** (TTL 30 dias) — leitura direta de
       ``~/.cache/dashboard-setor-eletrico/siga_v1.parquet``.
       Padronização ainda roda (custo trivial em ~25k linhas).
    2. **Download fresh** via cascata 3-tier (CKAN paginado →
       datastore_dump → URL fixa). Em sucesso, persiste snapshot
       BRUTO no disco antes de retornar.
    3. **Fallback DEMO** (apenas se ``DEMO_MODE=1`` e download
       totalmente falhar) — DataFrame sintético.
    4. **Falha total** — retorna DataFrame VAZIO com as 7 colunas
       declaradas (consumidores devem checar ``.empty``).
    """
    # Tentativa 1: cache disco
    df_disk = _try_read_siga()
    if df_disk is not None and not df_disk.empty:
        return _padronizar_siga(df_disk)

    # Tentativa 2: download fresh
    df_raw, estrategia = _baixar_siga()
    if df_raw is not None and len(df_raw) > 0:
        _registrar_erro(
            f"Download OK via {estrategia}: {len(df_raw)} linhas brutas"
        )
        # Persiste snapshot bruto (SPEC §4.3)
        _try_write_siga(df_raw)
        return _padronizar_siga(df_raw)

    # Tentativa 3: DEMO fallback
    if DEMO_MODE:
        _registrar_erro("Download falhou; DEMO_MODE=1 → DataFrame sintético")
        return _carregar_siga_demo()

    # Tentativa 4: falha total → DataFrame vazio com schema declarado
    _registrar_erro(
        "Download falhou e DEMO_MODE desabilitado — DataFrame vazio"
    )
    return _empty_df_siga()
