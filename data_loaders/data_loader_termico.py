"""
data_loader_termico.py
======================

Carrega dados do dataset ONS `geracao_termica_despacho_2_ho` (despacho térmico
verificado, granularidade horária, 2022-presente). Backend da aba "Despacho
Térmico" — sub-views Sistema (térmico Brasil) + Eneva (portfólio 11 usinas).

Fonte oficial:
    https://dados.ons.org.br/dataset/geracao_termica_despacho_2_ho

URL pattern S3 público:
    https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/
        geracao_termica_despacho_2_ho/GERACAO_TERMICA_DESPACHO-2_{ano}_{mes:02d}.parquet

Schema final de carregar_termico (wide-form, 13 colunas, granularidade DIÁRIA):
    data, id_subsistema, nom_subsistema, nom_usina, usina_eneva,
    val_verifgeracao, val_verifinflexibilidade, val_verifordemmerito,
    val_verifunitcommitment, val_verifexportacao, val_verifgsub,
    val_verifrazaoeletrica, val_verifgarantiaenergetica.

Para granularidade HORÁRIA (modo Horario single-day + drill-down Horario),
ver carregar_termico_horario_dia(dia) — schema 14 colunas com 'hora'.

Cache em 2 camadas (espelha decisão 5.15 do CLAUDE.md):
    1. Disco: ~/.cache/dashboard-setor-eletrico/termico_v1/{ano}_{mes:02d}.parquet
       (cascade pra tempfile se home read-only)
    2. RAM: @st.cache_data(ttl=30d) por mês fechado em _download_mes_historico
    3. Top-level: @st.cache_data(ttl=6h) em carregar_termico(ano_ini, ano_fim)

Premissas (validadas nas Fases A, A.1, A.2):
    - Schema estável de 2022-01 até hoje (decisão Fase A.1)
    - val_verifinflexpura populated retroativamente desde 2022-01 — substituir
      val_verifinflexibilidade por val_verifinflexpura quando sum > 0 fecha o
      balanço com val_verifgeracao (decisão Fase A.1)
    - 7 motivos do legado são suficientes — sem bucket "Outros" (decisão A.1)
    - 3 usinas entraram em operação pós-2022 (PARNAÍBA V, POVOAÇÃO, LINHARES) —
      ver USINAS_COBERTURA (decisão Fase A.2)
"""

from __future__ import annotations

import functools
import gc
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

URL_PATTERN = (
    "https://ons-aws-prod-opendata.s3.amazonaws.com/"
    "dataset/geracao_termica_despacho_2_ho/"
    "GERACAO_TERMICA_DESPACHO-2_{ano}_{mes:02d}.parquet"
)

# 7 motivos de despacho do legado. Mantém-se exatamente — soma fecha com
# val_verifgeracao após substituição inflexpura (decisão Fase A.1).
MOTIVOS: list[Tuple[str, str]] = [
    ("val_verifinflexibilidade",    "Inflexibilidade"),
    ("val_verifordemmerito",        "Ordem de mérito"),
    ("val_verifunitcommitment",     "Unit commitment"),
    ("val_verifexportacao",         "Exportação"),
    ("val_verifgsub",               "Substituição (GSUB)"),
    ("val_verifrazaoeletrica",      "Razão elétrica"),
    ("val_verifgarantiaenergetica", "Garantia energética"),
]
MOTIVOS_COLS: list[str] = [c for c, _ in MOTIVOS]

# Mapeamento Eneva → ONS (substring case-insensitive). ONS desagrega por
# patamar/combustível em algumas usinas (Maranhão 4 P0/P1/P2, Luiz O R Melo
# GNL/PCS) — o filtro substring agrega automaticamente.
ENEVA_USINAS: dict[str, list[str]] = {
    "ITAQUI":           ["Porto do Itaqui"],
    "PECÉM II":         ["Porto do Pecém II"],
    "PARNAÍBA I":       ["Maranhão 4", "Maranhão 5", "Maranhão IV", "Maranhão V"],
    "PARNAÍBA II":      ["Maranhão III"],
    "PARNAÍBA III+VI":  ["Nova Venécia 2"],
    "PARNAÍBA IV":      ["Parnaíba 4", "Parnaíba IV"],
    "PARNAÍBA V":       ["Parnaíba V"],
    "PORTO DE SERGIPE": ["Porto de Sergipe I"],
    "VIANA":            ["Viana", "Viana 1"],
    "POVOAÇÃO":         ["Povoação 1"],
    "LINHARES (LORM)":  ["Luiz O R Melo"],
}

# Cobertura por usina (mapeada empiricamente em scripts/inspect_termico_cobertura.py
# em 48 meses de 2022-01 até 2025-12). 3 usinas entraram em operação pós-2022.
# Sem lacunas no meio em nenhuma das 11.
USINAS_COBERTURA: dict[str, dict] = {
    "ITAQUI":             {"inicio": "2022-01", "fim": None, "lacunas": []},
    "PECÉM II":           {"inicio": "2022-01", "fim": None, "lacunas": []},
    "PARNAÍBA I":         {"inicio": "2022-01", "fim": None, "lacunas": []},
    "PARNAÍBA II":        {"inicio": "2022-01", "fim": None, "lacunas": []},
    "PARNAÍBA III+VI":    {"inicio": "2022-01", "fim": None, "lacunas": []},
    "PARNAÍBA IV":        {"inicio": "2022-01", "fim": None, "lacunas": []},
    "PARNAÍBA V":         {"inicio": "2022-11", "fim": None, "lacunas": []},
    "PORTO DE SERGIPE":   {"inicio": "2022-01", "fim": None, "lacunas": []},
    "VIANA":              {"inicio": "2022-01", "fim": None, "lacunas": []},
    "POVOAÇÃO":           {"inicio": "2022-07", "fim": None, "lacunas": []},
    "LINHARES (LORM)":    {"inicio": "2022-07", "fim": None, "lacunas": [("2026-02", "2026-04")]},
}

# Cache versionado (decisão 5.34). Bump quando o schema do parquet cacheado
# mudar (coluna nova, normalização diferente, mudança de _normalizar_motivos).
_CACHE_VERSION = "termico_v2"
# v2 (2026-05-04): dedup defensivo em _baixar_mes_raw após detectar
# parquet bruto ONS de abril/2026 com 2x linhas duplicadas. Cache v1
# pode conter parquets contaminados — bump invalida tudo.
_CACHE_BASE_NAME = "dashboard-setor-eletrico"


@functools.lru_cache(maxsize=1)
def _get_cache_dir() -> Optional[Path]:
    """Resolve diretório writable pro cache. None se ambos candidatos falharem.

    Cascade replicado da decisão 5.15:
        1. Path.home()/.cache/dashboard-setor-eletrico/termico_v1/
        2. tempfile.gettempdir()/dashboard-setor-eletrico/termico_v1/
        3. None — IO vira no-op silencioso.

    Detecção real de FS read-only via mkdir + touch + unlink (mkdir(exist_ok=True)
    pode passar mesmo em FS read-only se o diretório já existe).
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


# ---------------------------------------------------------------------------
# Helpers privados
# ---------------------------------------------------------------------------


def _registrar_erro(msg: str) -> None:
    """Acumula erro em st.session_state['_debug_erros'] (padrão do projeto).

    Fora de runtime Streamlit (ex: scripts), faz fallback pra print.
    """
    try:
        if "_debug_erros" not in st.session_state:
            st.session_state["_debug_erros"] = []
        st.session_state["_debug_erros"].append(
            f"[{datetime.now().strftime('%H:%M:%S')}] [termico] {msg}"
        )
    except Exception:
        print(f"[termico] {msg}")


def _http_get(url: str, timeout: int = 180) -> Optional[bytes]:
    """GET com curl_cffi (impersonate=chrome). Fallback requests + BROWSER_HEADERS.

    Retorna r.content se 200, None se 404 (mês não publicado, silencioso) ou
    qualquer outro erro (registrado em _debug_erros).
    """
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
            return None
        _registrar_erro(f"HTTP {r.status_code} em {url[-60:]}")
        return None
    except Exception as e:
        _registrar_erro(f"Falha GET {url[-60:]}: {type(e).__name__}: {e}")
        return None


def _baixar_mes_raw(ano: int, mes: int) -> Optional[pd.DataFrame]:
    """HTTP-only: baixa o parquet bruto do ONS sem cache. None em qualquer falha.

    Aplica dedup defensivo em (din_instante, nom_usina) com keep='last'. ONS já foi
    flagrado publicando parquet com linhas duplicadas (abril/2026: 2x todas as linhas).
    Política: confiar na última versão como correção do ONS.
    """
    url = URL_PATTERN.format(ano=ano, mes=mes)
    content = _http_get(url)
    if content is None:
        return None
    try:
        df = pd.read_parquet(io.BytesIO(content))
    except Exception as e:
        _registrar_erro(f"Falha parse parquet {ano}-{mes:02d}: {type(e).__name__}: {e}")
        return None

    # Dedup defensivo — ONS publica parquets com linhas duplicadas ocasionalmente.
    if "din_instante" in df.columns and "nom_usina" in df.columns:
        n_antes = len(df)
        df = df.drop_duplicates(subset=["din_instante", "nom_usina"], keep="last").reset_index(drop=True)
        n_depois = len(df)
        if n_antes > n_depois:
            _registrar_erro(
                f"ONS publicou {ano}-{mes:02d} com {n_antes - n_depois:,} "
                f"linhas duplicadas em (din_instante, nom_usina) — "
                f"deduplicado automaticamente (de {n_antes:,} para {n_depois:,})"
            )

    return df


def _cache_path(ano: int, mes: int) -> Optional[Path]:
    cache_dir = _get_cache_dir()
    if cache_dir is None:
        return None
    return cache_dir / f"{ano}_{mes:02d}.parquet"


def _eh_cache_valido(ano: int, mes: int) -> bool:
    """Cache vale para meses fechados (não corrente nem em revisão pós-fechamento).

    Replica regra do data_loader_curtailment.py:
        - Mês corrente: SEMPRE re-baixa.
        - Mês imediatamente anterior nos primeiros 5 dias do mês corrente:
          ainda em revisão pelo ONS, re-baixa.
    """
    hoje = date.today()
    if ano == hoje.year and mes == hoje.month:
        return False
    eh_mes_anterior = (
        (ano == hoje.year and mes == hoje.month - 1)
        or (ano == hoje.year - 1 and hoje.month == 1 and mes == 12)
    )
    if eh_mes_anterior and hoje.day <= 5:
        return False
    return True


@st.cache_data(ttl=60 * 60 * 24 * 30, show_spinner=False)
def _download_mes_historico(ano: int, mes: int) -> Optional[pd.DataFrame]:
    """Mês fechado — cache de 30 dias em RAM. Delega pra _baixar_mes_raw.

    Cache RAM via @st.cache_data sobrevive lifetime do container Streamlit,
    eliminando re-download de meses fechados entre reruns sucessivos.
    """
    return _baixar_mes_raw(ano, mes)


def _carregar_mes_com_cache(ano: int, mes: int) -> pd.DataFrame:
    """Orquestra cache disco + RAM. Retorna DataFrame raw (não normalizado)."""
    cache_file = _cache_path(ano, mes)

    if cache_file is not None and cache_file.exists() and _eh_cache_valido(ano, mes):
        try:
            return pd.read_parquet(cache_file)
        except Exception as e:
            _registrar_erro(f"Cache {cache_file.name} corrompido: {e}")

    if _eh_cache_valido(ano, mes):
        df = _download_mes_historico(ano, mes)
    else:
        df = _baixar_mes_raw(ano, mes)
    if df is None or len(df) == 0:
        return pd.DataFrame()

    if cache_file is not None:
        try:
            df.to_parquet(cache_file, index=False)
        except Exception as e:
            _registrar_erro(f"Erro salvando cache {cache_file.name}: {e}")

    return df


def _normalizar_motivos(df_in: pd.DataFrame) -> pd.DataFrame:
    """Converte 7 motivos + val_verifgeracao pra numérico e aplica substituição
    val_verifinflexibilidade ← val_verifinflexpura quando soma > 0.

    Substituição é a chave do balanço fechar (decisão Fase A.1). val_verifinflexpura
    fica preservada no DataFrame (pode ser útil pra debug).
    """
    df = df_in.copy()
    for col in MOTIVOS_COLS + ["val_verifgeracao"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        else:
            df[col] = 0.0

    if "val_verifinflexpura" in df.columns:
        s_pura = pd.to_numeric(df["val_verifinflexpura"], errors="coerce").fillna(0)
        if s_pura.sum() > 0:
            df["val_verifinflexibilidade"] = s_pura

    del df_in
    gc.collect()
    return df


def _mapear_eneva(df_in: pd.DataFrame) -> pd.DataFrame:
    """Adiciona coluna 'usina_eneva' (string canônica ou None).

    Aplica filtro substring case-insensitive em nom_usina pra cada conjunto de
    aliases em ENEVA_USINAS. Usinas não-Eneva ficam com None.
    """
    df = df_in.copy()
    df["usina_eneva"] = pd.Series([None] * len(df), index=df.index, dtype="object")
    if "nom_usina" not in df.columns:
        del df_in
        gc.collect()
        return df
    nom = df["nom_usina"]
    for canonica, aliases in ENEVA_USINAS.items():
        mask = pd.Series(False, index=df.index)
        for alias in aliases:
            mask |= nom.str.contains(alias, case=False, na=False)
        df.loc[mask, "usina_eneva"] = canonica
    del df_in
    gc.collect()
    return df


def _agregar_diario_no_worker(df_in: pd.DataFrame) -> pd.DataFrame:
    """Agrega DataFrame horario pra granularidade DIARIA.

    Reduz cardinalidade ~24x mantendo informacao pra modos
    Mensal/Diario/Trimestral. Modo Horario usa loader separado
    (carregar_termico_horario_dia) — pra preservar granularidade
    nativa apenas pra single-day.

    Antes do groupby, coerce os 7 motivos + val_verifgeracao +
    val_verifinflexpura pra numeric (defesa contra parquets ONS com
    tipos object/string que produziriam string-concat em vez de sum).

    Cols groupby: data (normalizada 00:00:00), id_subsistema,
    nom_subsistema, nom_usina.
    (usina_eneva eh adicionada apos o concat, no DataFrame agregado.)
    Cols agregadas: 7 motivos + val_verifgeracao + val_verifinflexpura.
    val_verifinflexpura eh preservada pra que _normalizar_motivos
    post-concat possa decidir substituicao GLOBAL (decisao Fase A.1).
    """
    df = df_in.copy()

    # Coerce defensivo pra numeric (parquets ONS antigos podem ter
    # motivos como object/string — sem coerce, groupby.sum() gera
    # string-concat em vez de aritmetica):
    cols_pra_coercar = MOTIVOS_COLS + ["val_verifgeracao", "val_verifinflexpura"]
    for col in cols_pra_coercar:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Normalizar data pra 00:00:00 (remove componente hora):
    if "data" not in df.columns and "din_instante" in df.columns:
        df["data"] = pd.to_datetime(df["din_instante"], errors="coerce").dt.normalize()
    elif "data" in df.columns:
        df["data"] = pd.to_datetime(df["data"], errors="coerce").dt.normalize()

    cols_grupo = ["data", "id_subsistema", "nom_subsistema", "nom_usina"]
    cols_existentes_grupo = [c for c in cols_grupo if c in df.columns]

    cols_soma = MOTIVOS_COLS + ["val_verifgeracao", "val_verifinflexpura"]
    cols_existentes_soma = [c for c in cols_soma if c in df.columns]

    if not cols_existentes_grupo or not cols_existentes_soma:
        del df_in
        gc.collect()
        return df  # fallback: retorna sem agregar se cols criticas ausentes

    df_agg = df.groupby(cols_existentes_grupo, dropna=False, as_index=False)[
        cols_existentes_soma
    ].sum()

    del df, df_in
    gc.collect()
    return df_agg


def _gerar_meses(ano_ini: int, ano_fim: int) -> list[Tuple[int, int]]:
    """Lista (ano, mes) de (ano_ini, 1) até o mês corrente (se ano_fim == ano corrente)
    ou até dezembro do ano_fim caso contrário."""
    hoje = date.today()
    meses: list[Tuple[int, int]] = []
    for ano in range(ano_ini, ano_fim + 1):
        mes_max = hoje.month if ano == hoje.year else 12
        for mes in range(1, mes_max + 1):
            meses.append((ano, mes))
    return meses


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


@st.cache_data(ttl=60 * 60 * 6, show_spinner=False)
def carregar_termico(
    ano_ini: int = 2022,
    ano_fim: Optional[int] = None,
) -> pd.DataFrame:
    """Carrega dataset ONS de despacho térmico verificado, agregado pra DIÁRIO.

    Args:
        ano_ini: ano inicial (default 2022, limite do legado).
        ano_fim: ano final inclusive (default = ano corrente).

    Returns:
        DataFrame wide-form com 13 colunas (granularidade DIÁRIA):
            data (datetime64[ns]): instante normalizado pro dia
            id_subsistema (str): N / NE / S / SE
            nom_subsistema (str): NORTE / NORDESTE / SUL / SUDESTE
            nom_usina (str): nome ONS da usina
            usina_eneva (str|None): nome canônico Eneva ou None pra não-Eneva
            val_verifgeracao (float): MWh por (data, usina) — soma das 24h
            val_verifinflexibilidade (float): MWh — substituição inflexpura aplicada
            val_verifordemmerito (float): MWh
            val_verifunitcommitment (float): MWh
            val_verifexportacao (float): MWh
            val_verifgsub (float): MWh
            val_verifrazaoeletrica (float): MWh
            val_verifgarantiaenergetica (float): MWh

        Retorna DataFrame vazio se todos os meses falharem. Falhas individuais
        vão pra st.session_state['_debug_erros'] sem interromper o load.
    """
    if ano_fim is None:
        ano_fim = date.today().year
    if ano_ini > ano_fim:
        _registrar_erro(f"ano_ini > ano_fim: {ano_ini} > {ano_fim}")
        return pd.DataFrame()

    meses = _gerar_meses(ano_ini, ano_fim)
    dfs: list[pd.DataFrame] = []

    for ano, mes in meses:
        try:
            df_mes = _carregar_mes_com_cache(ano, mes)
            if len(df_mes) > 0:
                # Agregar pra DIARIA antes de adicionar (reduz RAM ~24x).
                # _normalizar_motivos + _mapear_eneva continuam apos
                # o concat pra preservar decisao GLOBAL da substituicao
                # inflexpura (decisao Fase A.1).
                df_mes = _agregar_diario_no_worker(df_mes)
                dfs.append(df_mes)
            del df_mes
            gc.collect()
        except Exception as e:
            _registrar_erro(
                f"Erro carregando {ano}-{mes:02d}: {type(e).__name__}: {e}"
            )

    if not dfs:
        _registrar_erro(f"Nenhum dado térmico carregado em {ano_ini}-{ano_fim}")
        return pd.DataFrame()

    try:
        df = pd.concat(dfs, ignore_index=True)
        del dfs
        gc.collect()
    except Exception as e:
        _registrar_erro(f"Erro consolidando termico: {type(e).__name__}: {e}")
        return pd.DataFrame()

    df = _normalizar_motivos(df)
    df = _mapear_eneva(df)

    # Conversao datetime + criacao de 'hora' REMOVIDAS (Fase 2 do
    # refactor dual-loader):
    # - 'data' ja foi criada por _agregar_diario_no_worker no for loop.
    # - 'din_instante' nao existe mais (descartada no groupby).
    # - 'hora' nao existe mais (granularidade horaria perdida
    #   intencionalmente; modo Horario usa loader separado em Fase 3).

    cols_finais = [
        "data",
        "id_subsistema", "nom_subsistema", "nom_usina", "usina_eneva",
        "val_verifgeracao",
        "val_verifinflexibilidade",
        "val_verifordemmerito",
        "val_verifunitcommitment",
        "val_verifexportacao",
        "val_verifgsub",
        "val_verifrazaoeletrica",
        "val_verifgarantiaenergetica",
    ]
    cols_existentes = [c for c in cols_finais if c in df.columns]
    df = df[cols_existentes].copy()

    try:
        df = df.sort_values(["data", "nom_usina"]).reset_index(drop=True)
    except Exception as e:
        _registrar_erro(f"Erro no sort final: {type(e).__name__}: {e}")

    return df


@st.cache_data(ttl=21600, show_spinner=False)
def carregar_termico_horario_dia(dia: date) -> pd.DataFrame:
    """Carrega dados HORARIOS de um unico dia (lazy load).

    Usado APENAS pelo modo Horario (single-day, decisao 5.46) e pelo
    drill-down Horario (3o grafico do drill, decisao 5.54). NAO usar
    pra ranges multi-dia — pra isso use carregar_termico (agregacao
    diaria).

    Carrega APENAS o parquet do mes que contem 'dia', aplica
    _normalizar_motivos + _mapear_eneva, filtra "data == dia",
    retorna ~1900 rows com schema HORARIO (incluindo coluna 'hora').

    Cache: TTL 6h por dia. Multiplos dias != entradas separadas no cache.

    Args:
        dia: data alvo (datetime.date).

    Returns:
        DataFrame com 14 cols (incluindo 'hora') filtrado pra
        df["data"].dt.date == dia. Pode estar vazio se dia eh
        anterior ao dataset ou se ONS nao publicou ainda.
    """
    if not isinstance(dia, date):
        _registrar_erro(f"carregar_termico_horario_dia: dia invalido {dia!r}")
        return pd.DataFrame()

    # Carregar APENAS o parquet do mes do dia:
    df_mes = _carregar_mes_com_cache(dia.year, dia.month)
    if df_mes.empty:
        return pd.DataFrame()

    # Aplicar normalize + mapear (mesma logica de carregar_termico, sem agregar):
    df_mes = _normalizar_motivos(df_mes)
    df_mes = _mapear_eneva(df_mes)

    # Criar 'data' e 'hora' a partir de din_instante:
    if "din_instante" not in df_mes.columns:
        _registrar_erro(f"din_instante ausente em {dia.year}-{dia.month:02d}")
        return pd.DataFrame()

    ts = pd.to_datetime(df_mes["din_instante"], errors="coerce")
    df_mes = df_mes.copy()
    df_mes["data"] = ts.dt.normalize()
    df_mes["hora"] = ts.dt.hour.astype("int8")

    # Filtrar pra 1 dia:
    mask_dia = df_mes["data"].dt.date == dia
    df_dia = df_mes[mask_dia].copy()
    del df_mes
    gc.collect()

    if df_dia.empty:
        return pd.DataFrame()

    # Schema final 14 cols:
    cols_finais = [
        "data", "hora",
        "id_subsistema", "nom_subsistema", "nom_usina", "usina_eneva",
        "val_verifgeracao",
        "val_verifinflexibilidade",
        "val_verifordemmerito",
        "val_verifunitcommitment",
        "val_verifexportacao",
        "val_verifgsub",
        "val_verifrazaoeletrica",
        "val_verifgarantiaenergetica",
    ]
    cols_existentes = [c for c in cols_finais if c in df_dia.columns]
    df_dia = df_dia[cols_existentes].copy()

    try:
        df_dia = df_dia.sort_values(["data", "hora", "nom_usina"]).reset_index(drop=True)
    except Exception as e:
        _registrar_erro(f"Erro no sort horario: {type(e).__name__}: {e}")

    gc.collect()
    return df_dia


def is_termico_cache_fresh(ano: int, mes: int) -> bool:
    """Retorna True se o parquet do mês existe em cache de disco e o mês não
    é o corrente / em revisão (vale o cache pra leitura direta)."""
    cache_file = _cache_path(ano, mes)
    if cache_file is None or not cache_file.exists():
        return False
    return _eh_cache_valido(ano, mes)


def clear_termico_cache() -> None:
    """Limpa cache em ambas as camadas: disco + @st.cache_data.

    Decisão 5.17 do CLAUDE.md: 'Atualizar = começar do zero'. Sem isso, o
    @st.cache_data fica fora de sincronia com o disco se o usuário deletar
    parquets manualmente — gera bug invisível. Best-effort em ambas — falhas
    isoladas vão pra _debug_erros sem interromper.
    """
    try:
        carregar_termico.clear()
    except Exception as e:
        _registrar_erro(f"Falha clear carregar_termico: {type(e).__name__}: {e}")
    try:
        carregar_termico_horario_dia.clear()
    except Exception as e:
        _registrar_erro(f"Falha clear carregar_termico_horario_dia: {type(e).__name__}: {e}")
    try:
        _download_mes_historico.clear()
    except Exception as e:
        _registrar_erro(f"Falha clear _download_mes_historico: {type(e).__name__}: {e}")

    cache_dir = _get_cache_dir()
    if cache_dir is None:
        return
    try:
        for f in cache_dir.glob("*.parquet"):
            try:
                f.unlink()
            except Exception as e:
                _registrar_erro(f"Falha unlink {f.name}: {type(e).__name__}: {e}")
    except Exception as e:
        _registrar_erro(f"Falha glob cache_dir: {type(e).__name__}: {e}")


def usina_em_operacao(usina_eneva: str, ano: int, mes: int) -> bool:
    """Consulta USINAS_COBERTURA pra determinar se a usina estava em operação.

    Útil pra UI (Fase C) decidir mostrar tooltip / guard de período fora da
    janela operacional.

    Args:
        usina_eneva: nome canônico (chave de USINAS_COBERTURA).
        ano, mes: período de checagem.

    Returns:
        True se a usina já estava em operação no mês E não está em lacuna.
        False se ainda não havia entrado em operação ou está em lacuna conhecida.
        True se a usina não está no dicionário (default permissivo — usina
        não-Eneva ou cadastro novo não-mapeado).
    """
    info = USINAS_COBERTURA.get(usina_eneva)
    if info is None:
        return True

    target = (ano, mes)

    inicio = info.get("inicio")
    if inicio:
        a, m = int(inicio[:4]), int(inicio[5:7])
        if target < (a, m):
            return False

    fim = info.get("fim")
    if fim:
        a, m = int(fim[:4]), int(fim[5:7])
        if target > (a, m):
            return False

    for ini_l, fim_l in info.get("lacunas") or []:
        a1, m1 = int(ini_l[:4]), int(ini_l[5:7])
        a2, m2 = int(fim_l[:4]), int(fim_l[5:7])
        if (a1, m1) <= target <= (a2, m2):
            return False

    return True
