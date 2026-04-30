"""
data_loader_curtailment.py
==========================

Carrega dados de curtailment (constrained-off) de usinas EÓLICAS e SOLARES
do portal de dados abertos do ONS.

Fontes oficiais:
    - dados.ons.org.br/dataset/restricao_coff_eolica_usi
    - dados.ons.org.br/dataset/restricao_coff_fotovoltaica

Schema oficial (Dicionário ONS versão 1.4 / 26-09-2025):
    id_subsistema, nom_subsistema, id_estado, nom_estado,
    nom_usina, id_ons, ceg, din_instante,
    val_geracao, val_geracaolimitada, val_disponibilidade,
    val_geracaoreferencia, val_geracaoreferenciafinal,
    cod_razaorestricao    -> REL / CNF / ENE / PAR
    cod_origemrestricao   -> LOC / SIS
    dsc_restricao

Estratégia de ingestão (cascata de 2 estratégias):
    1. URL S3 direto - Parquet (preferido, menor)
    2. URL S3 direto - CSV (fallback)

Saída padronizada:
    DataFrame com colunas em UPPER_SNAKE_CASE, datas em datetime,
    submercados normalizados (SE/S/NE/N), com FRUSTRADO_MW pré-calculado.
"""

from __future__ import annotations

import concurrent.futures
import functools
import io
import tempfile
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
    "Accept": "*/*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": "https://dados.ons.org.br/",
}

URL_BASE_EOLICA = (
    "https://ons-aws-prod-opendata.s3.amazonaws.com/"
    "dataset/restricao_coff_eolica_tm/RESTRICAO_COFF_EOLICA_{ano}_{mes:02d}.{ext}"
)
URL_BASE_SOLAR = (
    "https://ons-aws-prod-opendata.s3.amazonaws.com/"
    "dataset/restricao_coff_fotovoltaica_tm/RESTRICAO_COFF_FOTOVOLTAICA_{ano}_{mes:02d}.{ext}"
)

SUBMERCADO_ALIASES = {
    "SE": "SE", "SECO": "SE", "SE/CO": "SE", "SUDESTE": "SE",
    "SUDESTE/CENTRO-OESTE": "SE", "SUDESTE_CO": "SE", "SUDESTE_COBR": "SE",
    "S": "S", "SUL": "S",
    "NE": "NE", "NORDESTE": "NE",
    "N": "N", "NORTE": "N",
}
SUBMERCADOS_VALIDOS = {"SE", "S", "NE", "N"}
RAZOES_VALIDAS = {"REL", "CNF", "ENE", "PAR"}

# Cache local (parquet consolidado por mês) - acelera reload.
# Path versionado: bump quando schema do parquet mudar (coluna nova,
# tipo diferente, mudança no cálculo derivado em _padronizar).
# Ver decisão 5.34 do CLAUDE.md.
#
# Path com cascade (replica decisão 5.15 do data_loader.py raiz):
#   Path.home()/.cache/dashboard-setor-eletrico/curtailment_v3/  (primário)
#   tempfile.gettempdir()/dashboard-setor-eletrico/curtailment_v3/  (fallback)
#   None  (modo no-cache se ambos read-only — IO vira no-op)
# Detecção real de FS read-only via mkdir + touch + unlink: mkdir(exist_ok=True)
# pode passar mesmo em FS read-only se o diretório já existe; touch+unlink
# confirma escrita real.
_CACHE_VERSION = "curtailment_v3"
_CACHE_BASE_NAME = "dashboard-setor-eletrico"


@functools.lru_cache(maxsize=1)
def _get_cache_dir() -> Optional[Path]:
    """Resolve diretório writable pro cache. None se ambos candidatos falharem."""
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


# ---------------------------------------------------------------------------
# Helpers de I/O e parsing
# ---------------------------------------------------------------------------


def _registrar_erro(msg: str) -> None:
    """Padrão do projeto: erros vão para st.session_state['_debug_erros']."""
    try:
        if "_debug_erros" not in st.session_state:
            st.session_state["_debug_erros"] = []
        st.session_state["_debug_erros"].append(
            f"[{datetime.now().strftime('%H:%M:%S')}] [curtailment] {msg}"
        )
    except Exception:
        print(f"[curtailment] {msg}")


def _http_get(url: str, timeout: int = 90) -> Optional[bytes]:
    """GET com curl_cffi (impersonate=chrome) - bypassa Akamai/TLS fingerprint."""
    try:
        if HAS_CURL_CFFI:
            r = creq.get(
                url,
                impersonate="chrome",
                headers=BROWSER_HEADERS,
                timeout=timeout,
            )
        else:
            r = creq.get(url, headers=BROWSER_HEADERS, timeout=timeout)

        if r.status_code == 200 and len(r.content) > 0:
            return r.content
        if r.status_code == 404:
            return None  # mês não publicado, silencioso
        _registrar_erro(f"HTTP {r.status_code} em {url[-50:]}")
        return None
    except Exception as e:
        _registrar_erro(f"Falha GET {url[-50:]}: {type(e).__name__}: {e}")
        return None


def _normalizar_colunas(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().upper() for c in df.columns]
    return df


def _identificar_coluna(df: pd.DataFrame, *keywords: str) -> Optional[str]:
    """Match por keyword (mais robusto que match exato)."""
    for kw in keywords:
        kw_upper = kw.upper()
        for col in df.columns:
            if kw_upper in col.upper():
                return col
    return None


def _normalizar_submercado(valor) -> Optional[str]:
    if pd.isna(valor):
        return None
    s = str(valor).strip().upper()
    if s in SUBMERCADO_ALIASES:
        return SUBMERCADO_ALIASES[s]
    if s in SUBMERCADOS_VALIDOS:
        return s
    return None


def _parse_data(serie: pd.Series) -> pd.Series:
    """Parse robusto: tenta ISO primeiro, depois BR (dayfirst)."""
    out = pd.to_datetime(serie, errors="coerce", format="ISO8601")
    if out.isna().mean() > 0.5:
        out = pd.to_datetime(serie, errors="coerce", dayfirst=True)
    return out


def _to_float_br(serie: pd.Series) -> pd.Series:
    """Converte para float, lidando com vírgula decimal BR."""
    if serie.dtype.kind in "fiu":
        return serie.astype(float)
    s = serie.astype(str).str.strip()
    has_comma = s.str.contains(r",\d{1,3}", regex=True, na=False).any()
    if has_comma:
        s = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce")


def _ler_parquet_bytes(content: bytes) -> Optional[pd.DataFrame]:
    try:
        return pd.read_parquet(io.BytesIO(content))
    except Exception as e:
        _registrar_erro(f"Erro lendo parquet: {e}")
        return None


def _ler_csv_bytes(content: bytes) -> Optional[pd.DataFrame]:
    """Lê CSV com cascata de separadores e encodings."""
    for sep in [";", ","]:
        for enc in ["utf-8", "latin-1", "utf-8-sig"]:
            try:
                df = pd.read_csv(
                    io.BytesIO(content),
                    sep=sep,
                    encoding=enc,
                    low_memory=False,
                )
                if len(df.columns) >= 5:
                    return df
            except Exception:
                continue
    _registrar_erro("Falha lendo CSV com todos os separadores/encodings")
    return None


# ---------------------------------------------------------------------------
# Padronização (normalização do schema)
# ---------------------------------------------------------------------------


def _padronizar(df: pd.DataFrame, fonte: str) -> pd.DataFrame:
    """Normaliza schema bruto do ONS para padrão do dashboard."""
    df = _normalizar_colunas(df)

    col_subm     = _identificar_coluna(df, "ID_SUBSISTEMA")
    col_subm_nm  = _identificar_coluna(df, "NOM_SUBSISTEMA")
    col_estado   = _identificar_coluna(df, "ID_ESTADO")
    col_est_nm   = _identificar_coluna(df, "NOM_ESTADO")
    col_usina    = _identificar_coluna(df, "NOM_USINA")
    col_id_ons   = _identificar_coluna(df, "ID_ONS")
    col_ceg      = _identificar_coluna(df, "CEG")
    col_data     = _identificar_coluna(df, "DIN_INSTANTE", "INSTANTE", "DATA_HORA")
    col_geracao  = _identificar_coluna(df, "VAL_GERACAO")
    col_ger_lim  = _identificar_coluna(df, "VAL_GERACAOLIMITADA", "GERACAOLIMITADA")
    col_disp     = _identificar_coluna(df, "VAL_DISPONIBILIDADE", "DISPONIBILIDADE")
    col_ref_fin  = _identificar_coluna(df, "VAL_GERACAOREFERENCIAFINAL", "REFERENCIAFINAL")
    col_ref_orig = _identificar_coluna(df, "VAL_GERACAOREFERENCIA")
    col_razao    = _identificar_coluna(df, "COD_RAZAORESTRICAO", "RAZAORESTRICAO")
    col_origem   = _identificar_coluna(df, "COD_ORIGEMRESTRICAO", "ORIGEMRESTRICAO")
    col_dsc      = _identificar_coluna(df, "DSC_RESTRICAO")

    # Validação mínima
    minimas = [col_data, col_geracao, col_ref_fin, col_razao]
    if not all(minimas):
        _registrar_erro(
            f"Colunas mínimas faltando ({fonte}). "
            f"Encontradas: {list(df.columns)[:15]}"
        )
        return pd.DataFrame()

    out = pd.DataFrame()
    out["DATA_HORA"] = _parse_data(df[col_data])
    out["DATA"] = out["DATA_HORA"].dt.date
    out["FONTE"] = "EOLICA" if fonte == "eolica" else "SOLAR"

    # Submercado (prioriza ID, fallback para nome)
    if col_subm:
        out["SUBMERCADO"] = df[col_subm].apply(_normalizar_submercado)
    elif col_subm_nm:
        out["SUBMERCADO"] = df[col_subm_nm].apply(_normalizar_submercado)
    else:
        out["SUBMERCADO"] = None

    out["UF"] = (
        df[col_estado].astype(str).str.strip().str.upper()
        if col_estado else None
    )
    out["ESTADO_NOME"] = (
        df[col_est_nm].astype(str).str.strip()
        if col_est_nm else None
    )

    out["USINA"] = df[col_usina].astype(str).str.strip() if col_usina else None
    out["ID_ONS"] = df[col_id_ons].astype(str).str.strip() if col_id_ons else None
    out["CEG"] = df[col_ceg].astype(str).str.strip() if col_ceg else None

    try:
        # Métricas (MWmed)
        out["GERACAO_MW"] = _to_float_br(df[col_geracao])
        if col_ger_lim:
            out["GERACAO_LIMITADA_MW"] = _to_float_br(df[col_ger_lim])
        if col_disp:
            # CRÍTICO: val_disponibilidade é OBRIGATÓRIO pra fórmula de curtailment.
            # MIN(disponibilidade, geracao_referencia) - geracao = energia frustrada.
            # Se este loader rodar contra dados sem essa coluna, o cálculo cai em
            # fallback baseado em val_geracaolimitada (que é diferente conceitualmente)
            # e o curtailment fica subestimado em ~10x.
            out["VAL_DISPONIBILIDADE_MW"] = _to_float_br(df[col_disp])
        if col_ref_orig:
            out["GERACAO_REF_MW"] = _to_float_br(df[col_ref_orig])
        out["GERACAO_REF_FINAL_MW"] = _to_float_br(df[col_ref_fin])

        # Razão (REL/CNF/ENE/PAR)
        out["RAZAO"] = df[col_razao].astype(str).str.strip().str.upper()
        out.loc[~out["RAZAO"].isin(RAZOES_VALIDAS), "RAZAO"] = None

        if col_origem:
            out["ORIGEM"] = df[col_origem].astype(str).str.strip().str.upper()
        if col_dsc:
            out["DSC_RESTRICAO"] = df[col_dsc].astype(str).str.strip()

        # =========================================================================
        # Cálculo correto do curtailment - alinhado ao template do mercado.
        #
        # ONS publica em PASSO SEMI-HORÁRIO (30min). Valores em MWmed.
        # Conversão para MWh do passo: × 0.5 (meia hora).
        #
        # Fórmula da coluna Q do template:
        #   curtailment_mwh = IF(razao_vazio, 0,
        #                        MAX(MIN(disponibilidade, geracao_referencia)
        #                            - geracao, 0)) * 0.5
        #
        # Diferenças vs versão anterior (errada):
        #   - Usa MIN(disp, ref), não geracao_ref_final
        #   - Multiplica por 0.5 (passo semi-horário)
        #   - Só conta se há razão de restrição (cod_razaorestricao não vazio)
        #
        # Output (denominador, coluna U do template):
        #   output_mwh = geracao * 0.5  (geração realizada no passo)
        # =========================================================================
        PASSO_HORAS = 0.5  # passo semi-horário do dataset ONS

        # Curtailment frustrado em MWh do passo
        if "GERACAO_REF_MW" in out.columns:
            ref_para_min = out["GERACAO_REF_MW"]
        else:
            # Se ref original não veio, fallback para a final (degrada graceful)
            ref_para_min = out["GERACAO_REF_FINAL_MW"]

        if "GERACAO_LIMITADA_MW" in out.columns:
            # val_disponibilidade no template é a disponibilidade da usina;
            # no parquet do ONS isso aparece como val_disponibilidade
            # (capturada em col_disp se presente; vide _detectar_colunas)
            disp = out.get("VAL_DISPONIBILIDADE_MW", out["GERACAO_LIMITADA_MW"])
        else:
            disp = ref_para_min  # fallback inócuo (MIN(x,x) = x)

        if "VAL_DISPONIBILIDADE_MW" in out.columns:
            disp = out["VAL_DISPONIBILIDADE_MW"]

        min_disp_ref = pd.concat([disp, ref_para_min], axis=1).min(axis=1)
        frustrado_mwmed = (min_disp_ref - out["GERACAO_MW"]).clip(lower=0)

        # Só conta se há razão de restrição (RAZAO não None)
        com_razao = out["RAZAO"].notna() & (out["RAZAO"] != "")
        out["FRUSTRADO_MWH"] = (frustrado_mwmed * PASSO_HORAS).where(com_razao, 0.0)

        # Output (geração realizada em MWh) - DENOMINADOR
        out["OUTPUT_MWH"] = out["GERACAO_MW"] * PASSO_HORAS

        # Mantém FRUSTRADO_MW para compat retrô (mesmo cálculo, sem × 0.5)
        out["FRUSTRADO_MW"] = frustrado_mwmed.where(com_razao, 0.0)

        # Limpeza final
        out = out.dropna(subset=["DATA_HORA", "GERACAO_MW"])
        return out
    except Exception as e:
        _registrar_erro(
            f"Erro em _padronizar ({fonte}): {type(e).__name__}: {e}"
        )
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Download por mês com cascata
# ---------------------------------------------------------------------------


def _baixar_mes(fonte: str, ano: int, mes: int) -> Optional[pd.DataFrame]:
    """Cascata: parquet -> csv. Retorna DataFrame normalizado ou vazio."""
    base = URL_BASE_EOLICA if fonte == "eolica" else URL_BASE_SOLAR

    # Estratégia 1: Parquet
    content = _http_get(base.format(ano=ano, mes=mes, ext="parquet"))
    if content:
        df = _ler_parquet_bytes(content)
        if df is not None and len(df) > 0:
            return _padronizar(df, fonte)

    # Estratégia 2: CSV
    content = _http_get(base.format(ano=ano, mes=mes, ext="csv"))
    if content:
        df = _ler_csv_bytes(content)
        if df is not None and len(df) > 0:
            return _padronizar(df, fonte)

    return None


# ---------------------------------------------------------------------------
# Cache local em parquet (para arquivos antigos que não mudam)
# ---------------------------------------------------------------------------


def _cache_path(fonte: str, ano: int, mes: int) -> Optional[Path]:
    cache_dir = _get_cache_dir()
    if cache_dir is None:
        return None
    return cache_dir / f"{fonte}_{ano}_{mes:02d}.parquet"


def _eh_cache_valido(fonte: str, ano: int, mes: int) -> bool:
    """Cache vale para meses fechados (não corrente nem em revisão pós-fechamento)."""
    hoje = date.today()
    # Mês corrente sempre re-baixa
    if ano == hoje.year and mes == hoje.month:
        return False
    # Mês imediatamente anterior pode estar em revisão nos primeiros 5 dias
    eh_mes_anterior = (
        (ano == hoje.year and mes == hoje.month - 1) or
        (ano == hoje.year - 1 and hoje.month == 1 and mes == 12)
    )
    if eh_mes_anterior and hoje.day <= 5:
        return False
    return True


def _carregar_mes_com_cache(fonte: str, ano: int, mes: int) -> pd.DataFrame:
    cache_file = _cache_path(fonte, ano, mes)

    if cache_file is not None and cache_file.exists() and _eh_cache_valido(fonte, ano, mes):
        try:
            return pd.read_parquet(cache_file)
        except Exception as e:
            _registrar_erro(f"Cache {cache_file.name} corrompido: {e}")

    df = _baixar_mes(fonte, ano, mes)
    if df is None or len(df) == 0:
        return pd.DataFrame()

    if cache_file is not None:
        try:
            df.to_parquet(cache_file, index=False)
        except Exception as e:
            _registrar_erro(f"Erro salvando cache {cache_file.name}: {e}")

    return df


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


def _gerar_meses(data_ini: date, data_fim: date) -> list[Tuple[int, int]]:
    """Lista (ano, mes) cobrindo o intervalo."""
    meses = []
    cur = date(data_ini.year, data_ini.month, 1)
    while cur <= data_fim:
        meses.append((cur.year, cur.month))
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)
    return meses


@st.cache_data(ttl=3600, show_spinner=False)
def carregar_curtailment(
    data_inicio: date,
    data_fim: date,
    fontes: tuple = ("eolica", "solar"),
) -> pd.DataFrame:
    """
    Carrega curtailment para o período solicitado.

    Args:
        data_inicio, data_fim: datas (inclusive)
        fontes: subset de ('eolica', 'solar')

    Returns:
        DataFrame com schema padronizado.
    """
    if data_inicio > data_fim:
        _registrar_erro(f"data_inicio > data_fim: {data_inicio} > {data_fim}")
        return pd.DataFrame()

    meses = _gerar_meses(data_inicio, data_fim)
    dfs = []

    # Paralelismo via ThreadPoolExecutor.
    # max_workers=8: paralelismo agressivo mas seguro. ONS S3 tolera bem,
    # 8 workers da ganho ~5x real. Container do Cloud (1GB RAM) suporta —
    # cada worker carrega parquet ~3MB, pico de memoria ~24MB extra.
    # Reduz cold start de ~60-120s pra ~12-25s no caso tipico (12 parquets).
    # Cada worker faz: _carregar_mes_com_cache (HTTP + cache local + parsing).
    # _http_get e _padronizar tem try/except próprios — exceptions ficam
    # contidas no worker. _registrar_erro pode falhar em thread workers
    # (st.session_state não-thread-safe) mas tem fallback pra print().
    tasks = [(fonte, ano, mes) for fonte in fontes for ano, mes in meses]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_to_task = {
            executor.submit(_carregar_mes_com_cache, fonte, ano, mes): (fonte, ano, mes)
            for fonte, ano, mes in tasks
        }
        for future in concurrent.futures.as_completed(future_to_task):
            try:
                df_mes = future.result()
                if len(df_mes) > 0:
                    dfs.append(df_mes)
            except Exception as e:
                fonte, ano, mes = future_to_task[future]
                _registrar_erro(
                    f"Erro paralelo em {fonte} {ano}-{mes:02d}: {type(e).__name__}: {e}"
                )

    if not dfs:
        _registrar_erro("Nenhum dado de curtailment carregado")
        return pd.DataFrame()

    try:
        df = pd.concat(dfs, ignore_index=True)
        df = df[(df["DATA"] >= data_inicio) & (df["DATA"] <= data_fim)]
        df = df.sort_values("DATA_HORA").reset_index(drop=True)
        return df
    except Exception as e:
        _registrar_erro(
            f"Erro consolidando curtailment: {type(e).__name__}: {e}"
        )
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def descobrir_ultimo_dia_disponivel(
    fonte: str = "eolica"
) -> Optional[date]:
    """
    Descobre a última data disponível baixando o mês mais recente publicado.
    Útil para definir 'hoje efetivo' no dashboard (período parcial).
    """
    hoje = date.today()
    base = URL_BASE_EOLICA if fonte == "eolica" else URL_BASE_SOLAR

    # Tenta os 3 meses mais recentes
    for offset in range(0, 3):
        ano = hoje.year
        mes = hoje.month - offset
        while mes <= 0:
            mes += 12
            ano -= 1

        df = _carregar_mes_com_cache(fonte, ano, mes)
        if len(df) > 0:
            return df["DATA"].max()

    return None
