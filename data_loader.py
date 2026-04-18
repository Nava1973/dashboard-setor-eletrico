"""
data_loader.py
Ingestão dos dados de PLD médio diário da CCEE.

Estratégia de carregamento (em ordem de preferência):
1. API CKAN datastore_search (paginada, mais estável)
2. Dump direto (/datastore/dump/{id}?bom=True)
3. URL pda-download (link marcado como "Baixar")

Se todas falharem e DEMO_MODE=True, usa dados sintéticos para não quebrar o app.

Schema oficial do dataset PLD_MEDIA_DIARIA:
    MES_REFERENCIA  (AAAAMM)
    SUBMERCADO      (SE, S, NE, N ou siglas completas)
    DIA             (DD/MM/AAAA)
    PLD_MEDIA_DIA   (numeric R$/MWh)
"""

from __future__ import annotations

import io
import os
from datetime import datetime, timedelta

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

RESOURCE_IDS = {
    2021: "9e152b60-f75c-4219-bcee-6033d287e0ab",
    2022: "6ccbf348-66ca-4bb1-a329-f607761fdf11",
    2023: "f28d0cb3-1afa-4b55-bf90-71c68b28272a",
    2024: "ed66d3dd-1987-4460-9164-20e169ad36fc",
    2025: "8b81daa1-8155-4fe1-9ee3-e01beb42fcc8",
    2026: "3ca83769-de89-4dc5-84a7-0128167b594d",
}

def _dump_url(resource_id: str) -> str:
    return f"https://dadosabertos.ccee.org.br/datastore/dump/{resource_id}?bom=True"

PDA_DOWNLOAD_URLS = {
    2021: "https://pda-download.ccee.org.br/s2aV2TfuTb2EQmKKY2Qg-w/content",
    2022: "https://pda-download.ccee.org.br/toeEwFnrRdi2lT7_ppiRfw/content",
    2023: "https://pda-download.ccee.org.br/WYOTpvY0QrmRKXx0bVT_ng/content",
    2024: "https://pda-download.ccee.org.br/jJSRhSl3SuGfKkCHVcQHxA/content",
    2025: "https://pda-download.ccee.org.br/by-H-ms8SLCvO0rerYBWTQ/content",
    2026: "https://pda-download.ccee.org.br/T09SGpnfRN-2ZaeWfHgrMw/content",
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


def _download_year(ano: int) -> tuple[pd.DataFrame | None, str]:
    """Tenta 3 estratégias em ordem. Retorna (df, fonte_usada)."""
    resource_id = RESOURCE_IDS[ano]

    df = _try_ckan_api(resource_id)
    if df is not None and not df.empty:
        return df, "api"

    df = _try_dump(resource_id)
    if df is not None and not df.empty:
        return df, "dump"

    if ano in PDA_DOWNLOAD_URLS:
        df = _try_pda_download(PDA_DOWNLOAD_URLS[ano])
        if df is not None and not df.empty:
            return df, "pda"

    return None, "falhou"


# =============================================================================
# NORMALIZAÇÃO
# =============================================================================


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza para schema: data, submercado, pld."""
    df.columns = [str(c).upper().strip() for c in df.columns]

    for c in ["_ID", "_FULL_TEXT", "RANK"]:
        if c in df.columns:
            df = df.drop(columns=[c])

    # Identifica colunas por palavra-chave
    col_data = next(
        (c for c in df.columns if c in ("DIA", "DIN_INSTANTE", "DATA", "DT_REFERENCIA")),
        None,
    ) or next((c for c in df.columns if "DIA" in c or "DATA" in c or "INSTANTE" in c), None)

    col_sub = next(
        (c for c in df.columns if c in ("SUBMERCADO", "ID_SUBSISTEMA", "SUBSISTEMA", "NOM_SUBMERCADO")),
        None,
    ) or next((c for c in df.columns if "SUB" in c or "MERCADO" in c), None)

    col_pld = next(
        (c for c in df.columns if c in ("PLD_MEDIA_DIA", "VAL_PLD", "PLD", "VALOR")),
        None,
    ) or next((c for c in df.columns if "PLD" in c or "VAL" in c), None)

    if not all([col_data, col_sub, col_pld]):
        raise ValueError(
            f"Colunas não identificadas. Disponíveis: {list(df.columns)}"
        )

    # Parse data: tenta DD/MM/YYYY primeiro, depois ISO
    data_series = df[col_data].astype(str)
    parsed = pd.to_datetime(data_series, format="%d/%m/%Y", errors="coerce")
    if parsed.isna().mean() > 0.5:
        parsed = pd.to_datetime(data_series, errors="coerce")

    # PLD: string "123,45" ou "123.45" ou numérico
    pld_series = df[col_pld]
    if pld_series.dtype == object:
        pld_series = (
            pld_series.astype(str)
            .str.replace(".", "", regex=False)
            .str.replace(",", ".", regex=False)
        )
    pld = pd.to_numeric(pld_series, errors="coerce")

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


# =============================================================================
# DEMO (fallback)
# =============================================================================


def _generate_demo_data() -> pd.DataFrame:
    """Série sintética realista para exibir o dashboard se a CCEE falhar."""
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
# ENTRY POINT
# =============================================================================


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def load_pld_media_diaria() -> pd.DataFrame:
    """Baixa e consolida todos os anos. Retorna DataFrame: data, submercado, pld."""
    # Reset debug
    st.session_state["_debug_erros"] = []

    frames = []
    fontes_por_ano = {}
    erros = []

    for ano in RESOURCE_IDS.keys():
        df, fonte = _download_year(ano)
        fontes_por_ano[ano] = fonte
        if df is None:
            erros.append(str(ano))
            continue
        try:
            frames.append(_normalize(df))
        except Exception as e:
            erros.append(f"{ano} (parse: {e})")

    st.session_state["_fontes_por_ano"] = fontes_por_ano

    if not frames:
        if DEMO_MODE:
            st.session_state["_demo_mode"] = True
            return _generate_demo_data()
        raise RuntimeError(
            "Não foi possível baixar dados da CCEE em nenhuma das estratégias "
            f"(API, dump, pda-download). Anos com falha: {', '.join(erros)}. "
            "Para ver o dashboard com dados sintéticos de demonstração, "
            "defina a variável de ambiente DEMO_MODE=1 e reinicie o app."
        )

    st.session_state["_demo_mode"] = False
    st.session_state["_erros_carga"] = erros

    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=["data", "submercado"], keep="last")
    df = df.sort_values(["data", "submercado"]).reset_index(drop=True)
    return df


def clear_cache() -> None:
    """Força reload no próximo acesso."""
    load_pld_media_diaria.clear()
