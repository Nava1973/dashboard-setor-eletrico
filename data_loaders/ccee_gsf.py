"""
ccee_gsf.py
===========

Carrega o GSF (Fator de Ajuste do MRE - Generation Scaling Factor)
realizado mensal do SIN a partir do dataset CCEE GERACAO_HORARIA_SUBMERCADO.

Formula validada empiricamente na Fase 0 (12/12 hits +/-0.5pp contra
15 pontos oficiais Power BI CCEE + InfoPLD):

    GSF_mes = sum(GERACAO_MRE) / sum(GARANTIA_FISICA_MRE)

Somando 4 submercados x todos os periodos de comercializacao do mes.

Cobertura: nov/2023 ate ~M-2 (dataset publicado com defasagem MS+2 meses).
Volume: ~35k linhas/ano horarias x 4 anos = ~140k linhas. Trivial.

Documentacao completa: docs/SPEC_gsf_v1.md
Resource IDs: scripts/_resource_ids_gsf.json (origem deste mapeamento)

Estrategia de ingestao (cascade):
    1. CKAN datastore_search paginado (1000 linhas/request)
    2. Dump endpoint /datastore/dump/{id}?bom=True

Cache 2-layer:
    - @st.cache_data na funcao publica (TTL 6h)
    - Disk parquet por ano em ~/.cache/dashboard-setor-eletrico/gsf_v1/
    - TTL diferenciado por ano:
        - Anos fechados (< ano_atual - 1): 30 dias
        - Ano atual e anterior: 24h (recontabilizacao possivel)

Padronizacao do retorno:
    DataFrame indexado por mes_ref (datetime64, primeiro dia do mes),
    colunas: sum_geracao_mre_mwh, sum_gf_mre_mwh, gsf (decimal), fonte_dado.

V2 (extensao historica pre-nov/2023): load_gsf_historico_pre2023()
le data/raw/gsf_historico_pre2023.csv se existir; senao retorna df vazio.
"""
from __future__ import annotations

import functools
import io
import json
import tempfile
import time
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Tuple

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
    "Accept": "application/json,*/*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": "https://dadosabertos.ccee.org.br/",
}

CKAN_BASE = "https://dadosabertos.ccee.org.br/api/3/action"
DUMP_URL_TEMPLATE = (
    "https://dadosabertos.ccee.org.br/datastore/dump/{rid}?bom=True"
)

# Dataset GERACAO_HORARIA_SUBMERCADO (Fase 0 confirmou)
DATASET_NAME = "geracao_horaria_submercado"
DATASET_ID = "27fd4abf-9508-4c16-9885-289524b2d529"

# Resource IDs por ano — origem em scripts/_resource_ids_gsf.json
# Mantemos inline aqui pra evitar I/O no import e dependencia de path
# relativo em runtime (Streamlit Cloud pode rodar de cwd inesperado).
# Para atualizar: rodar scripts/validacao_final_gsf.py (regenera o JSON)
# e copiar o dict aqui.
RESOURCE_IDS_BY_YEAR: dict[int, str] = {
    2023: "18c785e6-ecb3-465c-af55-77dc9a374f95",
    2024: "9d619679-62fc-4afd-b725-ee63c5d511d8",
    2025: "eeafc24a-97de-4e34-805b-bf5fc8146be2",
    2026: "4ff8ad16-93fa-4bf2-a7f3-03f23132fb38",
}

# Versao do cache. Bump ao mudar schema do parquet, formula ou conjunto
# de colunas extraidas (decisao 5.34 do CLAUDE.md).
_CACHE_VERSION = "gsf_v1"
_CACHE_BASE_NAME = "dashboard-setor-eletrico"

# TTL diferenciado por idade do ano (decisao §4.1 do SPEC)
_TTL_ANO_FECHADO_SEC = 60 * 60 * 24 * 30   # 30 dias
_TTL_ANO_RECENTE_SEC = 60 * 60 * 24        # 24 horas

# V2: arquivo de historico pre-nov/2023
_HISTORICO_PRE2023_PATH = (
    Path(__file__).resolve().parent.parent
    / "data" / "raw" / "gsf_historico_pre2023.csv"
)


# ---------------------------------------------------------------------------
# Helpers de cache disco (cascade de paths writable)
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def _get_cache_dir() -> Optional[Path]:
    """Resolve diretorio writable pro cache. None se ambos candidatos falharem.

    Padrao replicado de data_loaders/data_loader_curtailment.py:
    Path.home() primario, tempfile.gettempdir() fallback, None se ambos
    read-only (Cloud com FS restrito).
    """
    candidates = [
        Path.home() / ".cache" / _CACHE_BASE_NAME / _CACHE_VERSION,
        Path(tempfile.gettempdir()) / _CACHE_BASE_NAME / _CACHE_VERSION,
    ]
    for d in candidates:
        try:
            d.mkdir(parents=True, exist_ok=True)
            test = d / ".write_test"
            test.touch()
            test.unlink()
            return d
        except Exception:
            continue
    return None


def _cache_path_for_year(ano: int) -> Optional[Path]:
    cache_dir = _get_cache_dir()
    if cache_dir is None:
        return None
    return cache_dir / f"gsf_horaria_{ano}.parquet"


def _ttl_for_year(ano: int) -> int:
    """TTL diferenciado: anos fechados longos, recentes curtos.

    Considera ano corrente E ano anterior como "recentes" (24h) porque
    a CCEE pode publicar recontabilizacoes ate ~6 meses apos o fechamento.
    """
    hoje = date.today()
    if ano >= hoje.year - 1:
        return _TTL_ANO_RECENTE_SEC
    return _TTL_ANO_FECHADO_SEC


def _is_cache_fresh(parquet_path: Path, ttl_sec: int) -> bool:
    if not parquet_path.exists():
        return False
    try:
        idade = time.time() - parquet_path.stat().st_mtime
        return idade < ttl_sec
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Helpers de erro + HTTP
# ---------------------------------------------------------------------------


def _registrar_erro(msg: str) -> None:
    """Erros vao pra st.session_state['_debug_erros'] (padrao do projeto)."""
    try:
        if "_debug_erros" not in st.session_state:
            st.session_state["_debug_erros"] = []
        st.session_state["_debug_erros"].append(
            f"[{datetime.now().strftime('%H:%M:%S')}] [ccee_gsf] {msg}"
        )
    except Exception:
        print(f"[ccee_gsf] {msg}")


def _http_get(url: str, params: dict | None = None,
              timeout: int = 60) -> Optional[bytes]:
    """GET com curl_cffi (impersonate=chrome) - bypassa Akamai/TLS fingerprint."""
    try:
        if HAS_CURL_CFFI:
            r = creq.get(
                url, params=params or {}, headers=BROWSER_HEADERS,
                impersonate="chrome", timeout=timeout,
            )
        else:
            r = creq.get(
                url, params=params or {}, headers=BROWSER_HEADERS,
                timeout=timeout,
            )
        if r.status_code == 200 and len(r.content) > 0:
            return r.content
        _registrar_erro(f"HTTP {r.status_code} em {url[-60:]}")
        return None
    except Exception as e:
        _registrar_erro(f"Falha GET {url[-60:]}: {type(e).__name__}: {e}")
        return None


# ---------------------------------------------------------------------------
# 3-strategy cascade
# ---------------------------------------------------------------------------


def _try_ckan_api(resource_id: str) -> Optional[pd.DataFrame]:
    """CKAN datastore_search paginado (1000 linhas/request)."""
    base = f"{CKAN_BASE}/datastore_search"
    all_rows = []
    offset = 0
    limit = 1000
    while True:
        params = {"resource_id": resource_id, "limit": limit, "offset": offset}
        content = _http_get(base, params=params, timeout=120)
        if content is None:
            if all_rows:
                # devolve parcial em vez de perder tudo
                return pd.DataFrame(all_rows)
            return None
        try:
            payload = json.loads(content)
        except Exception as e:
            _registrar_erro(f"CKAN payload parse: {type(e).__name__}: {e}")
            return None
        if not payload.get("success"):
            _registrar_erro(f"CKAN success=false rid={resource_id[:8]}")
            return None
        recs = payload.get("result", {}).get("records", [])
        if not recs:
            break
        all_rows.extend(recs)
        if len(recs) < limit:
            break
        offset += limit
        time.sleep(0.05)
    if not all_rows:
        return None
    return pd.DataFrame(all_rows)


def _try_dump(resource_id: str) -> Optional[pd.DataFrame]:
    """Fallback: CSV completo via /datastore/dump/{id}?bom=True."""
    url = DUMP_URL_TEMPLATE.format(rid=resource_id)
    content = _http_get(url, timeout=120)
    if content is None:
        return None
    for sep in [",", ";"]:
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                df = pd.read_csv(io.BytesIO(content), sep=sep, encoding=enc)
                if df.shape[1] >= 5:
                    return df
            except Exception:
                continue
    _registrar_erro(f"DUMP {resource_id[:8]}: falha lendo CSV")
    return None


def _download_year(ano: int) -> Tuple[Optional[pd.DataFrame], str]:
    """Cascade CKAN -> dump. Retorna (df, fonte)."""
    rid = RESOURCE_IDS_BY_YEAR.get(ano)
    if not rid:
        _registrar_erro(f"resource_id ausente pro ano {ano}")
        return None, "sem_resource_id"
    df = _try_ckan_api(rid)
    if df is not None and not df.empty:
        return df, "ckan_api"
    df = _try_dump(rid)
    if df is not None and not df.empty:
        return df, "dump"
    return None, "falhou"


# ---------------------------------------------------------------------------
# Cache por ano (combina cascade + parquet disco com TTL diferenciado)
# ---------------------------------------------------------------------------


def _carregar_ano_horario(ano: int) -> pd.DataFrame:
    """Baixa horario do ano (cache disco com TTL por idade). Retorna 5 colunas:
    MES_REFERENCIA, SUBMERCADO, PERIODO_COMERCIALIZACAO, GERACAO_MRE,
    GARANTIA_FISICA_MRE.
    """
    parquet_path = _cache_path_for_year(ano)
    ttl = _ttl_for_year(ano)

    # 1. Tenta disk cache
    if parquet_path is not None and _is_cache_fresh(parquet_path, ttl):
        try:
            return pd.read_parquet(parquet_path)
        except Exception as e:
            _registrar_erro(
                f"cache disco corrompido {parquet_path.name}: {e}"
            )

    # 2. Cascade download
    df, fonte = _download_year(ano)
    if df is None or df.empty:
        return pd.DataFrame(
            columns=[
                "MES_REFERENCIA", "SUBMERCADO", "PERIODO_COMERCIALIZACAO",
                "GERACAO_MRE", "GARANTIA_FISICA_MRE",
            ]
        )

    # 3. Normalizar e enxugar colunas (so o necessario pro GSF)
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    cols_necessarias = [
        "MES_REFERENCIA", "SUBMERCADO", "PERIODO_COMERCIALIZACAO",
        "GERACAO_MRE", "GARANTIA_FISICA_MRE",
    ]
    cols_faltando = [c for c in cols_necessarias if c not in df.columns]
    if cols_faltando:
        _registrar_erro(
            f"ano {ano}: colunas ausentes {cols_faltando}. "
            f"Schema retornado: {list(df.columns)}"
        )
        return pd.DataFrame(columns=cols_necessarias)

    df = df[cols_necessarias].copy()
    df["MES_REFERENCIA"] = df["MES_REFERENCIA"].astype(str)
    df["SUBMERCADO"] = df["SUBMERCADO"].astype(str)
    df["PERIODO_COMERCIALIZACAO"] = pd.to_numeric(
        df["PERIODO_COMERCIALIZACAO"], errors="coerce"
    )
    df["GERACAO_MRE"] = pd.to_numeric(df["GERACAO_MRE"], errors="coerce")
    df["GARANTIA_FISICA_MRE"] = pd.to_numeric(
        df["GARANTIA_FISICA_MRE"], errors="coerce"
    )

    # 4. Persistir no disco
    if parquet_path is not None:
        try:
            df.to_parquet(parquet_path, index=False)
        except Exception as e:
            _registrar_erro(f"erro salvando cache {parquet_path.name}: {e}")

    return df


def _agregar_mensal(df_horario: pd.DataFrame) -> pd.DataFrame:
    """Agrega horario -> mensal aplicando a formula GSF validada.

    Soma GERACAO_MRE e GARANTIA_FISICA_MRE por MES_REFERENCIA (4 submercados
    x todos os periodos colapsam no sum). Computa gsf = sum_ger/sum_gf.

    Retorna DataFrame indexado por mes_ref (datetime64), colunas:
        sum_geracao_mre_mwh, sum_gf_mre_mwh, gsf, fonte_dado
    """
    if df_horario is None or df_horario.empty:
        return pd.DataFrame(
            columns=["sum_geracao_mre_mwh", "sum_gf_mre_mwh",
                     "gsf", "fonte_dado"]
        )

    agg = df_horario.groupby("MES_REFERENCIA").agg(
        sum_geracao_mre_mwh=("GERACAO_MRE", "sum"),
        sum_gf_mre_mwh=("GARANTIA_FISICA_MRE", "sum"),
    )
    # GSF como fracao decimal (mult por 100 pra %)
    agg["gsf"] = agg["sum_geracao_mre_mwh"] / agg["sum_gf_mre_mwh"]
    agg["fonte_dado"] = "ccee_horaria"

    # Indexar por datetime (primeiro dia do mes)
    agg.index = pd.to_datetime(agg.index, format="%Y%m")
    agg.index.name = "mes_ref"
    agg = agg.sort_index()

    return agg


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------


@st.cache_resource(ttl=60 * 60 * 6, show_spinner=False)
def load_gsf_mensal(
    incluir_historico_pre2023: bool = False,
) -> pd.DataFrame:
    """Carrega GSF mensal SIN (V1 = ccee_horaria; V2 opcional via flag).

    Args:
        incluir_historico_pre2023: se True, concatena
            load_gsf_historico_pre2023() na frente da serie V1.

    Returns:
        DataFrame indexado por mes_ref (datetime64 ASC, sem duplicatas).
        Colunas:
            sum_geracao_mre_mwh (float, NaN para fonte historico)
            sum_gf_mre_mwh      (float, NaN para fonte historico)
            gsf                 (float decimal, ex: 0.8497)
            fonte_dado          (str: 'ccee_horaria' | 'historico_legado')
    """
    # 1. V1: somar anos disponiveis
    dfs_anos = []
    for ano in sorted(RESOURCE_IDS_BY_YEAR.keys()):
        df_ano = _carregar_ano_horario(ano)
        if not df_ano.empty:
            dfs_anos.append(df_ano)

    if not dfs_anos:
        _registrar_erro("nenhum ano carregado — retornando df vazio")
        return pd.DataFrame(
            columns=["sum_geracao_mre_mwh", "sum_gf_mre_mwh",
                     "gsf", "fonte_dado"]
        )

    df_horario = pd.concat(dfs_anos, ignore_index=True)
    df_v1 = _agregar_mensal(df_horario)

    # 2. V2: opcional, prefixar historico legado
    if incluir_historico_pre2023:
        df_v2 = load_gsf_historico_pre2023()
        if not df_v2.empty:
            # remove sobreposicao: V1 tem prioridade onde ambos cobrem
            df_v2 = df_v2[~df_v2.index.isin(df_v1.index)]
            df_out = pd.concat([df_v2, df_v1]).sort_index()
            return df_out

    return df_v1


def load_gsf_historico_pre2023() -> pd.DataFrame:
    """V2: le data/raw/gsf_historico_pre2023.csv se existir.

    Schema minimo aceito no CSV:
        mes_ref (YYYY-MM ou YYYYMM)
        gsf     (decimal, ex: 0.823, ou percentual ex: 82.3)

    Retorna DataFrame com mesmo schema de load_gsf_mensal,
    com sum_geracao_mre_mwh e sum_gf_mre_mwh = NaN (nao reconstruivel),
    fonte_dado = 'historico_legado'.

    Se arquivo nao existir, retorna DataFrame vazio.
    """
    if not _HISTORICO_PRE2023_PATH.exists():
        return pd.DataFrame(
            columns=["sum_geracao_mre_mwh", "sum_gf_mre_mwh",
                     "gsf", "fonte_dado"]
        )

    try:
        df_raw = pd.read_csv(_HISTORICO_PRE2023_PATH)
    except Exception as e:
        _registrar_erro(
            f"erro lendo {_HISTORICO_PRE2023_PATH.name}: "
            f"{type(e).__name__}: {e}"
        )
        return pd.DataFrame(
            columns=["sum_geracao_mre_mwh", "sum_gf_mre_mwh",
                     "gsf", "fonte_dado"]
        )

    # Normalizar nomes de coluna pra lower
    df_raw.columns = [c.lower().strip() for c in df_raw.columns]
    if "mes_ref" not in df_raw.columns or "gsf" not in df_raw.columns:
        _registrar_erro(
            f"V2 schema invalido: colunas necessarias mes_ref + gsf; "
            f"recebido: {list(df_raw.columns)}"
        )
        return pd.DataFrame(
            columns=["sum_geracao_mre_mwh", "sum_gf_mre_mwh",
                     "gsf", "fonte_dado"]
        )

    # Parsear mes_ref aceitando YYYY-MM ou YYYYMM
    s = df_raw["mes_ref"].astype(str).str.replace("-", "", regex=False)
    idx = pd.to_datetime(s, format="%Y%m", errors="coerce")
    if idx.isna().any():
        _registrar_erro(f"V2: {idx.isna().sum()} linhas com mes_ref invalido")

    # Parsear gsf — se valores forem > 2.0 assume percentual (ex: 82.3 -> 0.823)
    gsf_vals = pd.to_numeric(df_raw["gsf"], errors="coerce")
    if gsf_vals.dropna().median() > 2.0:
        gsf_vals = gsf_vals / 100.0

    out = pd.DataFrame({
        "sum_geracao_mre_mwh": pd.NA,
        "sum_gf_mre_mwh": pd.NA,
        "gsf": gsf_vals.values,
        "fonte_dado": "historico_legado",
    }, index=idx)
    out.index.name = "mes_ref"
    out = out.dropna(subset=["gsf"])
    out = out[~out.index.isna()]
    out = out[~out.index.duplicated(keep="first")].sort_index()
    return out


def clear_gsf_cache() -> None:
    """Limpa cache RAM (st.cache_resource) + apaga parquets por ano."""
    try:
        load_gsf_mensal.clear()
    except Exception:
        pass
    cache_dir = _get_cache_dir()
    if cache_dir is None:
        return
    for ano in RESOURCE_IDS_BY_YEAR.keys():
        p = cache_dir / f"gsf_horaria_{ano}.parquet"
        try:
            if p.exists():
                p.unlink()
        except Exception as e:
            _registrar_erro(f"erro removendo {p.name}: {e}")

    # Força GC após liberar DataFrames grandes do cache. §5.92.
    import gc
    gc.collect()


def is_gsf_cache_fresh(ano: Optional[int] = None) -> bool:
    """True se cache disco do ano (ou de TODOS os anos) ainda esta fresh.

    Util pra UI escolher mensagem de spinner antes da chamada.
    """
    cache_dir = _get_cache_dir()
    if cache_dir is None:
        return False
    if ano is not None:
        p = _cache_path_for_year(ano)
        return p is not None and _is_cache_fresh(p, _ttl_for_year(ano))
    return all(
        _is_cache_fresh(
            cache_dir / f"gsf_horaria_{a}.parquet", _ttl_for_year(a)
        )
        for a in RESOURCE_IDS_BY_YEAR.keys()
    )
