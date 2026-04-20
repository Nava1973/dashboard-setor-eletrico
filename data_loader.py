"""
data_loader.py
Ingestão de dados pro dashboard. Duas fontes consolidadas neste módulo:

  1) CCEE — PLD em 4 granularidades (diária, horária, semanal, mensal).
     Infraestrutura própria: cascade CKAN→dump→PDA com curl_cffi.
  2) ONS — EAR (Energia Armazenada) diária por subsistema, mais SIN agregado.
     Baixado direto do S3 público do ONS em parquet.

Ambas compartilham _http_get + BROWSER_HEADERS + padrão de cache/erro.
Seção ONS fica no final do arquivo (ver "RESERVATÓRIOS (ONS)").

Estratégia de carregamento por ano (em ordem de preferência):
1. API CKAN datastore_search (paginada, mais estável)
2. Dump direto (/datastore/dump/{id}?bom=True)
3. URL pda-download (APENAS para dataset "diaria" — outros datasets não
   expõem essa URL; se os 2 primeiros falharem, retorna erro)

Se todas falharem e DEMO_MODE=True:
  - dataset "diaria": cai em dados sintéticos (_generate_demo_data)
  - demais datasets: retorna DataFrame vazio (sem demo implementado)

Schemas oficiais por dataset (após _normalize_*):
  diaria   → (data=day,       submercado, pld)
  horaria  → (data=datetime,  submercado, pld)
  semanal  → (data=ini-semana, submercado, pld)
             NOTA: a CCEE publica apenas a data de início da semana
             (coluna SEMANA), não o fim. Se o consumidor precisar do
             intervalo completo (ex: hover "13/04 a 19/04"), calcule
             data + timedelta(days=6) no ponto de render. Não
             armazenamos data_fim no DataFrame pra não guardar coluna
             derivada que desincronizaria se a lógica mudasse.
  mensal   → (data=1º dia do mês, submercado, pld)

Schema diário (original, já consolidado em produção):
    MES_REFERENCIA  (AAAAMM)
    SUBMERCADO      (SE, S, NE, N ou siglas completas)
    DIA             (DD/MM/AAAA)
    PLD_MEDIA_DIA   (numeric R$/MWh)

Para atualizar resource_ids quando a CCEE publicar um novo ano, rodar:
    venv/Scripts/python.exe scripts/discover_ccee_ids.py
"""

from __future__ import annotations

import io
import os
from datetime import datetime, timedelta
from typing import Callable

import numpy as np
import pandas as pd
import streamlit as st

# curl_cffi imita o fingerprint TLS do Chrome — muito mais difícil de bloquear
# que o requests padrão. Akamai e Cloudflare costumam cair nessa.
try:
    from curl_cffi import requests as http
    _CURL_CFFI_AVAILABLE = True
except ImportError:
    # Fallback para requests padrão se curl_cffi não estiver instalado
    import requests as http
    _CURL_CFFI_AVAILABLE = False


def _http_get(url: str, **kwargs):
    """
    Faz uma requisição GET usando curl_cffi (com impersonate=chrome) se disponível,
    ou requests normal como fallback.
    """
    if _CURL_CFFI_AVAILABLE:
        # impersonate="chrome" faz a requisição parecer exatamente um Chrome real
        return http.get(url, impersonate="chrome", **kwargs)
    return http.get(url, **kwargs)

# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

# Resource IDs CKAN da CCEE por (dataset, ano).
# IMPORTANTE:
#   - Para "semanal" e "mensal", a chave 2001 aponta para o CSV consolidado
#     2001-2020 ("pld_media_semanal_2001_2020" / "pld_media_mensal_2001_2020").
#     Não é o ano 2001 isolado — é todo o histórico pré-2021 em um arquivo.
#     O normalizer extrai as linhas pelas datas reais; concat+dedup resolve.
#   - Para "horaria" não há histórico pré-2021: PLD horário só existe
#     a partir de 2021 (antes era só semanal). Ignoramos o recurso
#     "pld_historico_semanal_2001_2020" que a CCEE anexa ao pacote
#     PLD_HORARIO, porque seu conteúdo é semanal e quebraria o normalizer.
RESOURCE_IDS_BY_DATASET: dict[str, dict[int, str]] = {
    "diaria": {
        2021: "9e152b60-f75c-4219-bcee-6033d287e0ab",
        2022: "6ccbf348-66ca-4bb1-a329-f607761fdf11",
        2023: "f28d0cb3-1afa-4b55-bf90-71c68b28272a",
        2024: "ed66d3dd-1987-4460-9164-20e169ad36fc",
        2025: "8b81daa1-8155-4fe1-9ee3-e01beb42fcc8",
        2026: "3ca83769-de89-4dc5-84a7-0128167b594d",
    },
    "horaria": {
        2021: "51922462-16b4-4c64-8327-4e14d6ee8c6c",
        2022: "723cf7e6-6c29-4da6-aa39-e4c8804baf65",
        2023: "5fc317af-7191-4f8a-94e7-f77c56c747b3",
        2024: "1b5b6946-8036-4622-a7a3-b21f33fc52b7",
        2025: "2a180a6b-f092-43eb-9f82-a48798b803dc",
        2026: "3f279d6b-1069-42f7-9b0a-217b084729c4",
    },
    "semanal": {
        2001: "9e5dc4aa-9a77-4a14-965e-30bcf13b21c9",  # consolidado 2001-2020
        2021: "b6961e51-22d9-4345-9662-0e64dc9530c6",
        2022: "37cb2711-f7fd-4539-86c0-672e89b5a3ce",
        2023: "a135b355-1d31-4847-8396-232ee88faeeb",
        2024: "cddc565c-6c06-4ee8-8a44-6d79c6bc69a6",
        2025: "b1a35c4b-a3ad-4572-9927-4dc5724578bd",
        2026: "e34f98e8-68df-4a22-972f-02cb621ec978",
    },
    "mensal": {
        2001: "a6ac9621-6c2f-48b7-9d72-c4564abfd7c2",  # consolidado 2001-2020
        2021: "cca2e61a-1621-4ff9-984d-78241c486b1e",
        2022: "12cd1ea2-e998-4098-9dac-fe8c2bcaf01f",
        2023: "bafe8615-e5f6-4d25-9a18-19b668c97cec",
        2024: "65b8a3e4-f5e9-4ea5-9566-1a7b38c70001",
        2025: "9b9a4ae6-3db4-48f8-8130-ffa229835f7a",
        2026: "e3a256cd-3580-49ae-a843-5a0c3d4eabb9",
    },
}

# Alias de compatibilidade — código antigo pode referenciar RESOURCE_IDS.
# Aponta pro diário (comportamento original).
RESOURCE_IDS = RESOURCE_IDS_BY_DATASET["diaria"]


def _dump_url(resource_id: str) -> str:
    return f"https://dadosabertos.ccee.org.br/datastore/dump/{resource_id}?bom=True"


# PDA fallback URLs: apenas o dataset "diaria" tem essas URLs mapeadas.
# Para os demais datasets, se CKAN API e dump falharem, o download retorna erro
# (sem 3º tier). Se algum dia for necessário, descobrir as URLs e popular aqui.
PDA_DOWNLOAD_URLS_BY_DATASET: dict[str, dict[int, str]] = {
    "diaria": {
        2021: "https://pda-download.ccee.org.br/s2aV2TfuTb2EQmKKY2Qg-w/content",
        2022: "https://pda-download.ccee.org.br/toeEwFnrRdi2lT7_ppiRfw/content",
        2023: "https://pda-download.ccee.org.br/WYOTpvY0QrmRKXx0bVT_ng/content",
        2024: "https://pda-download.ccee.org.br/jJSRhSl3SuGfKkCHVcQHxA/content",
        2025: "https://pda-download.ccee.org.br/by-H-ms8SLCvO0rerYBWTQ/content",
        2026: "https://pda-download.ccee.org.br/T09SGpnfRN-2ZaeWfHgrMw/content",
    },
}

# Alias de compatibilidade.
PDA_DOWNLOAD_URLS = PDA_DOWNLOAD_URLS_BY_DATASET["diaria"]


# Anos disponíveis por dataset (derivado de RESOURCE_IDS_BY_DATASET).
# Usado pelo _load_dataset para iterar.
DATASET_YEARS_AVAILABLE: dict[str, list[int]] = {
    ds: sorted(ids.keys()) for ds, ids in RESOURCE_IDS_BY_DATASET.items()
}


BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/json,*/*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": "https://dadosabertos.ccee.org.br/",
}

SUBMERCADO_MAP = {
    "SE/CO": "SE",
    "SE": "SE",
    "SUDESTE": "SE",
    "SUDESTE/CENTRO-OESTE": "SE",
    "SUL": "S",
    "S": "S",
    "NORDESTE": "NE",
    "NE": "NE",
    "NORTE": "N",
    "N": "N",
}

DEMO_MODE = os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes")


# =============================================================================
# DOWNLOAD
# =============================================================================


def _try_ckan_api(resource_id: str) -> pd.DataFrame | None:
    """
    API CKAN datastore_search — paginada.
    Alguns servidores CKAN (caso da CCEE) retornam 403 para limit alto.
    Usamos limit=1000 que é seguro em praticamente todos os deploys.
    """
    import time

    base = "https://dadosabertos.ccee.org.br/api/3/action/datastore_search"
    all_records = []
    offset = 0
    limit = 1000  # seguro para o rate/size limit da CCEE

    while True:
        params = {"resource_id": resource_id, "limit": limit, "offset": offset}
        try:
            r = _http_get(base, params=params, headers=BROWSER_HEADERS, timeout=60)
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            errs = st.session_state.setdefault("_debug_erros", [])
            errs.append(
                f"CKAN {resource_id[:8]}... offset={offset}: "
                f"{type(e).__name__}: {e}"
            )
            # Se já baixamos algo, devolve parcial em vez de perder tudo
            if all_records:
                return pd.DataFrame(all_records)
            return None

        if not payload.get("success"):
            errs = st.session_state.setdefault("_debug_erros", [])
            errs.append(f"CKAN {resource_id[:8]}...: success=false")
            return None

        records = payload.get("result", {}).get("records", [])
        if not records:
            break
        all_records.extend(records)
        if len(records) < limit:
            break
        offset += limit
        # Pequeno delay para não parecer bot agressivo
        time.sleep(0.1)

    if not all_records:
        return None
    return pd.DataFrame(all_records)


def _try_dump(resource_id: str) -> pd.DataFrame | None:
    """Dump CSV completo via /datastore/dump/{id}?bom=True."""
    url = _dump_url(resource_id)
    try:
        r = _http_get(url, headers=BROWSER_HEADERS, timeout=60)
        r.raise_for_status()
    except Exception as e:
        errs = st.session_state.setdefault("_debug_erros", [])
        errs.append(f"DUMP {resource_id[:8]}...: {type(e).__name__}: {e}")
        return None

    for sep in [",", ";"]:
        try:
            df = pd.read_csv(io.BytesIO(r.content), sep=sep, encoding="utf-8-sig")
            if df.shape[1] >= 3:
                return df
        except Exception:
            continue
    return None


def _try_pda_download(url: str) -> pd.DataFrame | None:
    """Último recurso — URL pda-download."""
    try:
        r = _http_get(url, headers=BROWSER_HEADERS, timeout=60, allow_redirects=True)
        r.raise_for_status()
    except Exception as e:
        errs = st.session_state.setdefault("_debug_erros", [])
        errs.append(f"PDA {url[-30:]}: {type(e).__name__}: {e}")
        return None

    for sep in [";", ","]:
        for enc in ["utf-8-sig", "utf-8", "latin-1"]:
            try:
                df = pd.read_csv(
                    io.BytesIO(r.content), sep=sep, decimal=",", encoding=enc
                )
                if df.shape[1] >= 3:
                    return df
            except Exception:
                continue
    return None


def _download_year(ano: int, dataset: str = "diaria") -> tuple[pd.DataFrame | None, str]:
    """
    Tenta 3 estratégias em ordem (CKAN API → dump → PDA).
    Retorna (df, fonte_usada).

    Para datasets sem PDA fallback mapeado (horaria/semanal/mensal),
    o tier 3 é simplesmente pulado.
    """
    resource_id = RESOURCE_IDS_BY_DATASET[dataset][ano]

    df = _try_ckan_api(resource_id)
    if df is not None and not df.empty:
        return df, "api"

    df = _try_dump(resource_id)
    if df is not None and not df.empty:
        return df, "dump"

    pda_urls = PDA_DOWNLOAD_URLS_BY_DATASET.get(dataset, {})
    if ano in pda_urls:
        df = _try_pda_download(pda_urls[ano])
        if df is not None and not df.empty:
            return df, "pda"

    return None, "falhou"


# =============================================================================
# NORMALIZAÇÃO
# =============================================================================


def _identify_column(df: pd.DataFrame, exact: tuple[str, ...],
                     keywords: tuple[str, ...]) -> str | None:
    """Acha coluna com match exato primeiro; fallback pra substring."""
    for c in df.columns:
        if c in exact:
            return c
    for c in df.columns:
        if any(k in c for k in keywords):
            return c
    return None


def _parse_pld_series(series: pd.Series) -> pd.Series:
    """Converte série de PLD pra numérico lidando com vírgula decimal BR."""
    if series.dtype == object:
        series = (
            series.astype(str)
            .str.replace(".", "", regex=False)
            .str.replace(",", ".", regex=False)
        )
    return pd.to_numeric(series, errors="coerce")


def _parse_date_series(series: pd.Series) -> pd.Series:
    """Parse BR (DD/MM/YYYY) primeiro; se maioria falhar, cai pra ISO."""
    s = series.astype(str)
    parsed = pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")
    if parsed.isna().mean() > 0.5:
        parsed = pd.to_datetime(s, errors="coerce")
    return parsed


def _parse_datetime_series(series: pd.Series) -> pd.Series:
    """
    Parse datetime com hora. Tenta formatos BR (DD/MM/YYYY HH:MM) primeiro,
    depois ISO. Usado pra granularidade horária.
    """
    s = series.astype(str)
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        parsed = pd.to_datetime(s, format=fmt, errors="coerce")
        if parsed.isna().mean() < 0.5:
            return parsed
    return pd.to_datetime(s, errors="coerce")


def _normalize_diaria(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza PLD diário para schema: data, submercado, pld."""
    df.columns = [str(c).upper().strip() for c in df.columns]

    for c in ["_ID", "_FULL_TEXT", "RANK"]:
        if c in df.columns:
            df = df.drop(columns=[c])

    # Identifica colunas por palavra-chave
    col_data = _identify_column(
        df,
        exact=("DIA", "DIN_INSTANTE", "DATA", "DT_REFERENCIA"),
        keywords=("DIA", "DATA", "INSTANTE"),
    )
    col_sub = _identify_column(
        df,
        exact=("SUBMERCADO", "ID_SUBSISTEMA", "SUBSISTEMA", "NOM_SUBMERCADO"),
        keywords=("SUB", "MERCADO"),
    )
    col_pld = _identify_column(
        df,
        exact=("PLD_MEDIA_DIA", "VAL_PLD", "PLD", "VALOR"),
        keywords=("PLD", "VAL"),
    )

    if not all([col_data, col_sub, col_pld]):
        raise ValueError(
            f"Colunas não identificadas (diaria). Disponíveis: {list(df.columns)}"
        )

    parsed = _parse_date_series(df[col_data])
    pld = _parse_pld_series(df[col_pld])

    out = pd.DataFrame(
        {
            "data": parsed,
            "submercado": df[col_sub].astype(str).str.upper().str.strip(),
            "pld": pld,
        }
    )
    out["submercado"] = out["submercado"].map(SUBMERCADO_MAP).fillna(out["submercado"])
    out = out.dropna(subset=["data", "submercado", "pld"])
    out = out[out["submercado"].isin(["SE", "S", "NE", "N"])]
    return out


def _normalize_horaria(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normaliza PLD horário para schema: data (datetime com hora), submercado, pld.

    Schema real da CCEE (observado no dataset PLD_HORARIO em 2026):
        MES_REFERENCIA   ('202604')          ← AAAAMM
        SUBMERCADO       ('NORDESTE')
        DIA              ('20')              ← APENAS O DIA DO MÊS, não data completa
        HORA             (0 a 23, int)
        PLD_HORA         (float)

    Por isso NÃO existe coluna de data completa; montamos o datetime
    combinando MES_REFERENCIA + DIA + HORA.

    Mantemos fallbacks (DIN_INSTANTE / DATA completa) caso a CCEE publique
    um recurso em formato antigo — não custa, e protege contra regressão.
    """
    df.columns = [str(c).upper().strip() for c in df.columns]

    for c in ["_ID", "_FULL_TEXT", "RANK"]:
        if c in df.columns:
            df = df.drop(columns=[c])

    col_sub = _identify_column(
        df,
        exact=("SUBMERCADO", "ID_SUBSISTEMA", "SUBSISTEMA", "NOM_SUBMERCADO"),
        keywords=("SUB", "MERCADO"),
    )
    col_pld = _identify_column(
        df,
        exact=("PLD_HORA", "PLD_HORARIO", "VAL_PLD", "PLD", "VALOR"),
        keywords=("PLD", "VAL"),
    )

    # Fallback 1: timestamp completo em uma coluna (DIN_INSTANTE etc.)
    col_instante = _identify_column(
        df,
        exact=("DIN_INSTANTE", "DATA_REFERENCIA", "DT_REFERENCIA"),
        keywords=("INSTANTE", "TIMESTAMP"),
    )

    parsed = None
    if col_instante:
        parsed = _parse_datetime_series(df[col_instante])
        if parsed.isna().mean() > 0.5:
            parsed = None  # fallback pra tentativa MES_REF + DIA + HORA

    col_hora = _identify_column(
        df,
        exact=("HORA", "HORA_INICIO", "HORA_REFERENCIA", "HR", "NUM_HORA"),
        keywords=("HORA", "HR_"),
    )

    if parsed is None and col_hora:
        # Formato atual CCEE: MES_REFERENCIA (AAAAMM) + DIA (dia do mês) + HORA
        col_mref = _identify_column(
            df, exact=("MES_REFERENCIA", "MES_REF"), keywords=("MES_REF", "ANOMES"),
        )
        col_dia = _identify_column(df, exact=("DIA",), keywords=("DIA",))
        if col_mref and col_dia:
            s_mref = df[col_mref].astype(str).str.strip().str.replace(
                r"[-/]", "", regex=True
            )
            ano = pd.to_numeric(s_mref.str[:4], errors="coerce")
            mes = pd.to_numeric(s_mref.str[4:6], errors="coerce")
            dia = pd.to_numeric(df[col_dia], errors="coerce")
            hora_num = pd.to_numeric(
                df[col_hora].astype(str).str.extract(r"(\d+)", expand=False),
                errors="coerce",
            ).fillna(0).astype(int).clip(0, 23)
            base = pd.to_datetime(
                dict(year=ano, month=mes, day=dia), errors="coerce",
            )
            parsed = base + pd.to_timedelta(hora_num, unit="h")
        else:
            # Último fallback: DIA completo (DD/MM/YYYY) + HORA
            col_data_full = _identify_column(
                df, exact=("DATA",), keywords=("DATA",),
            )
            if col_data_full:
                dia_parsed = _parse_date_series(df[col_data_full])
                hora_num = pd.to_numeric(
                    df[col_hora].astype(str).str.extract(r"(\d+)", expand=False),
                    errors="coerce",
                ).fillna(0).astype(int).clip(0, 23)
                parsed = dia_parsed + pd.to_timedelta(hora_num, unit="h")

    if parsed is None:
        raise ValueError(
            f"Colunas de timestamp não identificadas (horaria). "
            f"Disponíveis: {list(df.columns)}"
        )

    if not all([col_sub, col_pld]):
        raise ValueError(
            f"Colunas sub/pld não identificadas (horaria). "
            f"Disponíveis: {list(df.columns)}"
        )

    pld = _parse_pld_series(df[col_pld])

    out = pd.DataFrame(
        {
            "data": parsed,
            "submercado": df[col_sub].astype(str).str.upper().str.strip(),
            "pld": pld,
        }
    )
    out["submercado"] = out["submercado"].map(SUBMERCADO_MAP).fillna(out["submercado"])
    out = out.dropna(subset=["data", "submercado", "pld"])
    out = out[out["submercado"].isin(["SE", "S", "NE", "N"])]
    return out


def _normalize_semanal(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normaliza PLD semanal para schema: (data=ini-semana, submercado, pld).

    Schema real da CCEE (observado no dataset PLD_MEDIA_SEMANAL):
        MES_REFERENCIA       ('202604')
        SUBMERCADO           ('NORDESTE')
        SEMANA               ('11/04/2026')  ← APENAS data de início da semana
        PLD_MEDIA_SEMANA     (float)

    IMPORTANTE: a CCEE publica SÓ a data de início da semana, não o fim.
    Não computamos data_fim aqui pra evitar guardar coluna derivada. Se o
    consumidor precisar do intervalo pra exibir (ex: hover "13/04 a 19/04"),
    calcula no ponto de render com data + timedelta(days=6).
    """
    df.columns = [str(c).upper().strip() for c in df.columns]

    for c in ["_ID", "_FULL_TEXT", "RANK"]:
        if c in df.columns:
            df = df.drop(columns=[c])

    col_sub = _identify_column(
        df,
        exact=("SUBMERCADO", "ID_SUBSISTEMA", "SUBSISTEMA", "NOM_SUBMERCADO"),
        keywords=("SUB", "MERCADO"),
    )
    col_pld = _identify_column(
        df,
        exact=("PLD_MEDIA_SEMANA", "PLD_MEDIA_SEMANAL", "PLD_SEMANAL",
               "VAL_PLD", "PLD", "VALOR"),
        keywords=("PLD", "VAL"),
    )
    col_data = _identify_column(
        df,
        exact=("SEMANA", "DIM_SEMANA", "DAT_INI_SEMANA", "DIN_INI_SEMANA",
               "DATA_INICIO", "DATA"),
        keywords=("SEMANA", "INI", "DATA"),
    )

    if not all([col_sub, col_pld, col_data]):
        raise ValueError(
            f"Colunas não identificadas (semanal). "
            f"Disponíveis: {list(df.columns)}"
        )

    # A coluna SEMANA pode ter formato "DD/MM/YYYY" OU "DD/MM/YYYY a DD/MM/YYYY"
    # (se algum dia mudarem). Pegamos a PRIMEIRA data encontrada = início.
    s = df[col_data].astype(str)
    extracted = s.str.extract(r"(\d{2}/\d{2}/\d{4})", expand=False)
    # Se a extração falhar (ex: formato ISO), cai pro parser genérico.
    if extracted.isna().mean() > 0.5:
        parsed = _parse_date_series(s)
    else:
        parsed = _parse_date_series(extracted)

    pld = _parse_pld_series(df[col_pld])

    out = pd.DataFrame(
        {
            "data": parsed,
            "submercado": df[col_sub].astype(str).str.upper().str.strip(),
            "pld": pld,
        }
    )
    out["submercado"] = out["submercado"].map(SUBMERCADO_MAP).fillna(out["submercado"])
    out = out.dropna(subset=["data", "submercado", "pld"])
    out = out[out["submercado"].isin(["SE", "S", "NE", "N"])]
    return out


def _normalize_mensal(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normaliza PLD mensal para schema: (data=1º dia do mês, submercado, pld).

    Tenta MES_REFERENCIA (formato AAAAMM inteiro) primeiro; cai em
    colunas separadas MES + ANO; por último, parser flexível.
    """
    df.columns = [str(c).upper().strip() for c in df.columns]

    for c in ["_ID", "_FULL_TEXT", "RANK"]:
        if c in df.columns:
            df = df.drop(columns=[c])

    col_sub = _identify_column(
        df,
        exact=("SUBMERCADO", "ID_SUBSISTEMA", "SUBSISTEMA", "NOM_SUBMERCADO"),
        keywords=("SUB", "MERCADO"),
    )
    col_pld = _identify_column(
        df,
        exact=("PLD_MEDIA_MENSAL", "PLD_MENSAL", "VAL_PLD", "PLD", "VALOR"),
        keywords=("PLD", "VAL"),
    )

    parsed = None
    # Caso 1: MES_REFERENCIA no formato AAAAMM
    col_mref = _identify_column(
        df,
        exact=("MES_REFERENCIA", "MES_REF", "ANO_MES"),
        keywords=("MES_REF", "ANOMES"),
    )
    if col_mref:
        s = df[col_mref].astype(str).str.strip()
        # Aceita "202101", "2021-01", "2021/01"
        s = s.str.replace(r"[-/]", "", regex=True)
        ano = pd.to_numeric(s.str[:4], errors="coerce")
        mes = pd.to_numeric(s.str[4:6], errors="coerce")
        parsed = pd.to_datetime(
            dict(year=ano, month=mes, day=1), errors="coerce"
        )

    # Caso 2: ANO + MES separados
    if parsed is None or parsed.isna().mean() > 0.5:
        col_ano = _identify_column(df, exact=("ANO",), keywords=("ANO",))
        col_mes = _identify_column(df, exact=("MES",), keywords=("MES",))
        if col_ano and col_mes:
            ano = pd.to_numeric(df[col_ano], errors="coerce")
            mes = pd.to_numeric(df[col_mes], errors="coerce")
            parsed = pd.to_datetime(
                dict(year=ano, month=mes, day=1), errors="coerce"
            )

    # Caso 3: fallback pra parser de data normal (campo tipo "01/01/2021")
    if parsed is None or parsed.isna().mean() > 0.5:
        col_data = _identify_column(
            df, exact=("DATA", "DIA"), keywords=("DATA", "DIA"),
        )
        if col_data:
            d = _parse_date_series(df[col_data])
            # Normaliza pro primeiro dia do mês
            parsed = d.dt.to_period("M").dt.to_timestamp()

    if parsed is None:
        raise ValueError(
            f"Colunas de mês não identificadas (mensal). "
            f"Disponíveis: {list(df.columns)}"
        )

    if not all([col_sub, col_pld]):
        raise ValueError(
            f"Colunas sub/pld não identificadas (mensal). "
            f"Disponíveis: {list(df.columns)}"
        )

    pld = _parse_pld_series(df[col_pld])

    out = pd.DataFrame(
        {
            "data": parsed,
            "submercado": df[col_sub].astype(str).str.upper().str.strip(),
            "pld": pld,
        }
    )
    out["submercado"] = out["submercado"].map(SUBMERCADO_MAP).fillna(out["submercado"])
    out = out.dropna(subset=["data", "submercado", "pld"])
    out = out[out["submercado"].isin(["SE", "S", "NE", "N"])]
    return out


# Alias backward-compat: código antigo pode chamar _normalize diretamente
_normalize = _normalize_diaria


# =============================================================================
# DEMO (fallback)
# =============================================================================


def _generate_demo_data() -> pd.DataFrame:
    """Série sintética realista para exibir o dashboard se a CCEE falhar.

    Implementado apenas para granularidade diária. As demais granularidades
    retornam DataFrame vazio em DEMO_MODE quando o download real falha.
    """
    rng = np.random.default_rng(42)
    fim = datetime.now().date()
    ini = fim - timedelta(days=365 * 2)
    datas = pd.date_range(ini, fim, freq="D")

    base = {"SE": 180, "S": 170, "NE": 150, "N": 140}
    amp = {"SE": 80, "S": 75, "NE": 90, "N": 85}

    rows = []
    for i, d in enumerate(datas):
        sazonal = np.sin(2 * np.pi * (d.dayofyear - 120) / 365) * 0.5 + 0.5
        for sub in ["SE", "S", "NE", "N"]:
            valor = base[sub] + amp[sub] * sazonal + rng.normal(0, 20)
            valor = float(np.clip(valor, 50, 600))
            rows.append({"data": d, "submercado": sub, "pld": round(valor, 2)})

    return pd.DataFrame(rows)


# =============================================================================
# LOADER GENÉRICO
# =============================================================================


def _load_dataset(
    dataset: str,
    normalizer: Callable[[pd.DataFrame], pd.DataFrame],
    dedup_keys: tuple[str, ...] = ("data", "submercado"),
) -> pd.DataFrame:
    """
    Download + normalização + concat para um dataset inteiro.

    O dataset "diaria" escreve em `_fontes_por_ano`, `_erros_carga`,
    `_demo_mode` (chaves consumidas pelo app.py hoje).
    Os demais datasets escrevem em chaves namespaced
    (`_fontes_por_ano_{dataset}`, `_erros_carga_{dataset}`) pra não
    colidir com o estado do diário.
    """
    # Reset debug a cada chamada (comportamento original do diário)
    st.session_state["_debug_erros"] = []

    years = DATASET_YEARS_AVAILABLE[dataset]
    frames = []
    fontes_por_ano = {}
    erros = []

    for ano in years:
        df, fonte = _download_year(ano, dataset)
        fontes_por_ano[ano] = fonte
        if df is None:
            erros.append(str(ano))
            continue
        try:
            frames.append(normalizer(df))
        except Exception as e:
            erros.append(f"{ano} (parse: {e})")

    # Session state — diário usa chaves "curtas" (compat app.py).
    if dataset == "diaria":
        st.session_state["_fontes_por_ano"] = fontes_por_ano
        st.session_state["_erros_carga"] = erros
    else:
        st.session_state[f"_fontes_por_ano_{dataset}"] = fontes_por_ano
        st.session_state[f"_erros_carga_{dataset}"] = erros

    if not frames:
        if DEMO_MODE and dataset == "diaria":
            st.session_state["_demo_mode"] = True
            return _generate_demo_data()
        if DEMO_MODE:
            # Demo não implementado pras 3 novas granularidades — retorna vazio
            return pd.DataFrame(columns=list(dedup_keys) + ["pld"])
        raise RuntimeError(
            f"Não foi possível baixar dados da CCEE (dataset={dataset}) em "
            f"nenhuma das estratégias (API, dump, pda-download). "
            f"Anos com falha: {', '.join(erros)}. "
            f"Para ver o dashboard com dados sintéticos de demonstração "
            f"(apenas diário), defina a variável de ambiente DEMO_MODE=1 e "
            f"reinicie o app."
        )

    if dataset == "diaria":
        st.session_state["_demo_mode"] = False

    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=list(dedup_keys), keep="last")
    df = df.sort_values(list(dedup_keys)).reset_index(drop=True)
    return df


# =============================================================================
# ENTRY POINTS (cached)
# =============================================================================


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def load_pld_media_diaria() -> pd.DataFrame:
    """Baixa e consolida PLD diário de todos os anos.

    Retorna DataFrame: (data, submercado, pld).
    """
    return _load_dataset("diaria", _normalize_diaria)


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def load_pld_horaria() -> pd.DataFrame:
    """Baixa e consolida PLD horário de todos os anos (2021+).

    Retorna DataFrame: (data=datetime, submercado, pld).
    """
    return _load_dataset("horaria", _normalize_horaria)


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def load_pld_media_semanal() -> pd.DataFrame:
    """Baixa e consolida PLD semanal (histórico 2001+).

    Retorna DataFrame: (data=ini-semana, data_fim=fim-semana, submercado, pld).
    """
    return _load_dataset(
        "semanal", _normalize_semanal, dedup_keys=("data", "submercado"),
    )


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def load_pld_media_mensal() -> pd.DataFrame:
    """Baixa e consolida PLD mensal (histórico 2001+).

    Retorna DataFrame: (data=1º dia do mês, submercado, pld).
    """
    return _load_dataset("mensal", _normalize_mensal)


# =============================================================================
# RESERVATÓRIOS (ONS)
# =============================================================================
# Dataset: ear-diario-por-subsistema (CKAN ONS, só pra metadata).
# Origem real dos arquivos: AWS S3 público, virtual-hosted style.
# URL pattern:
#   https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/ear_subsistema_di/
#     EAR_DIARIO_SUBSISTEMA_{YYYY}.parquet
#
# Schema do parquet ONS (validado na Fase A, ver docs/reservatorios_research.md):
#   id_subsistema                    (str) 'N','NE','S','SE'
#   nom_subsistema                   (str) 'NORTE','NORDESTE','SUL','SUDESTE'
#   ear_data                         (str) 'YYYY-MM-DD'
#   ear_max_subsistema               (float, MWmês)
#   ear_verif_subsistema_mwmes       (float, MWmês)
#   ear_verif_subsistema_percentual  (float, %)  ← métrica principal
#
# Schema de saída (long-form):
#   data (datetime), subsistema_code (str), subsistema_nome (str), ear_pct (float)
#
# SIN é CALCULADO (dataset só tem os 4 subsistemas — não tem linha SIN):
#   SIN_pct(data) = sum(ear_verif_mwmes) / sum(ear_max) × 100
# =============================================================================

ONS_EAR_SUBSISTEMA_URL = (
    "https://ons-aws-prod-opendata.s3.amazonaws.com/"
    "dataset/ear_subsistema_di/EAR_DIARIO_SUBSISTEMA_{ano}.parquet"
)

# Mapa ONS id → nome completo usado na renderização.
# ONS usa "SUDESTE" (não "SUDESTE/CENTRO-OESTE") — aderimos à convenção oficial.
SUBSISTEMA_NOMES = {
    "SE":  "SUDESTE",
    "S":   "SUL",
    "NE":  "NORDESTE",
    "N":   "NORTE",
    "SIN": "SIN",
}

# Anos disponíveis (confirmado Fase A: 2000-2026). Rever anualmente.
# Se ONS publicar 2027, acrescentar ao range ou usar descoberta dinâmica.
RESERVATORIOS_YEARS_AVAILABLE = list(range(2000, 2027))


def _download_reservatorio_parquet_raw(ano: int) -> pd.DataFrame | None:
    """Baixa 1 ano de EAR por subsistema em parquet do S3 ONS. Sem cache."""
    url = ONS_EAR_SUBSISTEMA_URL.format(ano=ano)
    try:
        r = _http_get(url, headers=BROWSER_HEADERS, timeout=60)
        r.raise_for_status()
    except Exception as e:
        errs = st.session_state.setdefault("_debug_erros", [])
        errs.append(f"ONS EAR {ano} (download): {type(e).__name__}: {e}")
        return None

    try:
        return pd.read_parquet(io.BytesIO(r.content))
    except Exception as e:
        errs = st.session_state.setdefault("_debug_erros", [])
        errs.append(f"ONS EAR {ano} (parse parquet): {type(e).__name__}: {e}")
        return None


# Cache longo (30 dias) pra anos FECHADOS. ONS não altera histórico publicado.
# Separado do ano corrente pra não re-baixar 26 anos quando só o ano atual mudou.
@st.cache_data(ttl=60 * 60 * 24 * 30, show_spinner=False)
def _download_reservatorio_parquet_historico(ano: int) -> pd.DataFrame | None:
    """Ano fechado — cache de 30 dias. Invalidar manualmente via clear_cache
    só se suspeitar de reedição do ONS (raro)."""
    return _download_reservatorio_parquet_raw(ano)


def _normalize_reservatorios(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza schema ONS pra long-form (data, code, nome, ear_pct)."""
    df.columns = [str(c).strip() for c in df.columns]

    col_code = "id_subsistema"
    col_nome = "nom_subsistema"
    col_data = "ear_data"
    col_pct  = "ear_verif_subsistema_percentual"

    missing = [c for c in (col_code, col_nome, col_data, col_pct)
               if c not in df.columns]
    if missing:
        raise ValueError(
            f"Colunas ONS faltando: {missing}. Presentes: {list(df.columns)}"
        )

    out = pd.DataFrame({
        "data": pd.to_datetime(df[col_data], errors="coerce"),
        "subsistema_code": df[col_code].astype(str).str.strip().str.upper(),
        "subsistema_nome": df[col_nome].astype(str).str.strip().str.upper(),
        "ear_pct": pd.to_numeric(df[col_pct], errors="coerce"),
    })
    out = out.dropna(subset=["data", "subsistema_code", "ear_pct"])
    out = out[out["subsistema_code"].isin(["SE", "S", "NE", "N"])]
    return out


def _compute_sin_aggregate(raw_frames: list[pd.DataFrame]) -> pd.DataFrame:
    """
    Calcula série SIN a partir dos frames brutos (preserva ear_max +
    ear_verif_mwmes antes do normalize que descartaria essas colunas).

    SIN_pct(data) = sum(ear_verif_mwmes) / sum(ear_max) × 100

    Retorna mesmo schema de saída: (data, code='SIN', nome='SIN', ear_pct).
    """
    if not raw_frames:
        return pd.DataFrame(
            columns=["data", "subsistema_code", "subsistema_nome", "ear_pct"]
        )

    full = pd.concat(raw_frames, ignore_index=True)
    full["ear_data"] = pd.to_datetime(full["ear_data"], errors="coerce")
    full["ear_max_subsistema"] = pd.to_numeric(
        full["ear_max_subsistema"], errors="coerce"
    )
    full["ear_verif_subsistema_mwmes"] = pd.to_numeric(
        full["ear_verif_subsistema_mwmes"], errors="coerce"
    )
    full = full[full["id_subsistema"].isin(["SE", "S", "NE", "N"])]

    agg = (
        full.groupby("ear_data", as_index=False)[
            ["ear_max_subsistema", "ear_verif_subsistema_mwmes"]
        ]
        .sum()
    )
    # Divisão por zero extremamente improvável (EARmax nunca zera), mas proteger
    agg["ear_pct"] = np.where(
        agg["ear_max_subsistema"] > 0,
        agg["ear_verif_subsistema_mwmes"] / agg["ear_max_subsistema"] * 100.0,
        np.nan,
    )

    out = pd.DataFrame({
        "data": agg["ear_data"],
        "subsistema_code": "SIN",
        "subsistema_nome": "SIN",
        "ear_pct": agg["ear_pct"],
    })
    return out.dropna(subset=["data", "ear_pct"])


@st.cache_data(ttl=60 * 60 * 2, show_spinner=False)
def load_reservatorios() -> pd.DataFrame:
    """
    Baixa e consolida EAR por subsistema do ONS + calcula linha SIN agregada.

    Retorna DataFrame long-form:
      data             datetime64
      subsistema_code  str    'SE'|'S'|'NE'|'N'|'SIN'
      subsistema_nome  str    'SUDESTE'|'SUL'|'NORDESTE'|'NORTE'|'SIN'
      ear_pct          float  0-100

    Fonte: S3 público ONS, 27 anos de parquet (~900KB total).

    Cache em 2 camadas:
      - Externo (esta função): TTL 2h. Captura atualização diária do ONS.
      - Interno: _download_reservatorio_parquet_historico(ano) com TTL 30d
        pra anos fechados (não mudam) → evita re-baixar 26 anos toda vez.
        Ano corrente é baixado direto (sem cache interno) — refresh a cada 2h.

    clear_cache() limpa só o cache externo. Historic interno sobrevive.
    Resultado: 'Atualizar' invalida só o ano corrente (histórico preservado).
    """
    st.session_state["_debug_erros"] = []

    ano_corrente = datetime.now().year

    raw_frames = []
    erros = []
    for ano in RESERVATORIOS_YEARS_AVAILABLE:
        if ano < ano_corrente:
            df_raw = _download_reservatorio_parquet_historico(ano)
        else:
            # Ano corrente (ou futuro, se alguém colocar): sempre fresh
            df_raw = _download_reservatorio_parquet_raw(ano)
        if df_raw is None or df_raw.empty:
            erros.append(str(ano))
            continue
        raw_frames.append(df_raw)

    st.session_state["_erros_carga_reservatorios"] = erros

    if not raw_frames:
        raise RuntimeError(
            "Não foi possível baixar dados do ONS "
            "(ear-diario-por-subsistema) em nenhum ano. "
            f"Anos com falha: {', '.join(erros)}."
        )

    subsistema_frames = []
    for df_raw in raw_frames:
        try:
            subsistema_frames.append(_normalize_reservatorios(df_raw))
        except Exception as e:
            erros.append(f"parse: {e}")

    sin_df = _compute_sin_aggregate(raw_frames)

    if not subsistema_frames and sin_df.empty:
        raise RuntimeError("Nenhum frame ONS normalizado com sucesso.")

    df = pd.concat(subsistema_frames + [sin_df], ignore_index=True)
    df = df.drop_duplicates(subset=["data", "subsistema_code"], keep="last")
    df = df.sort_values(["subsistema_code", "data"]).reset_index(drop=True)
    return df


def clear_cache() -> None:
    """Força reload no próximo acesso — limpa cache de PLD (4 granularidades)
    e de reservatórios (ONS)."""
    load_pld_media_diaria.clear()
    load_pld_horaria.clear()
    load_pld_media_semanal.clear()
    load_pld_media_mensal.clear()
    load_reservatorios.clear()
