"""Teste rápido dos helpers _compute_rampa_series + _compute_kpis_carga.

Não importa app.py (que executaria todo o Streamlit). Replica os helpers
inline pra rodar isolado e validar valores razoáveis pra SIN último mês.

Uso:
    venv\Scripts\python.exe scripts\test_kpis_carga.py

Esperado (ordem de grandeza, valores hoje):
    carga_total_media   ~ 70-85 GWmed
    carga_liquida_media ~ 50-70 GWmed
    rampa_max_1h        ~ 5-15 GW
    rampa_max_3h        ~ 10-25 GW
    pct_renov_var       ~ 15-30%
"""
import sys
from datetime import timedelta

import pandas as pd

# Windows cp1252 quebra com → e outros (CLAUDE.md §4.4).
sys.stdout.reconfigure(encoding="utf-8")

# Faz import do data_loader sem disparar app.py
sys.path.insert(0, ".")
from data_loader import load_balanco_subsistema  # noqa: E402


def _compute_rampa_series(df_long, code, data_ini, data_fim, janela_h):
    mask = (
        (df_long["submercado"] == code)
        & (df_long["data"] >= pd.Timestamp(data_ini))
        & (df_long["data"] <= pd.Timestamp(data_fim))
    )
    dff = df_long.loc[mask]
    if dff.empty:
        return pd.Series(dtype="float64")
    pivot = dff.pivot_table(
        index="data_hora", columns="fonte", values="mwmed", aggfunc="mean",
    ).sort_index()
    for col in ("carga", "eolica", "solar"):
        if col not in pivot.columns:
            pivot[col] = 0.0
    pivot[["carga", "eolica", "solar"]] = (
        pivot[["carga", "eolica", "solar"]].fillna(0)
    )
    liq = pivot["carga"] - pivot["eolica"] - pivot["solar"]
    return liq.shift(-janela_h) - liq


def _compute_kpis_carga(df_long, code, data_ini, data_fim):
    rampa_1h = _compute_rampa_series(df_long, code, data_ini, data_fim, 1)
    rampa_3h = _compute_rampa_series(df_long, code, data_ini, data_fim, 3)
    if rampa_1h.empty:
        return {
            "carga_total_media":   float("nan"),
            "carga_liquida_media": float("nan"),
            "rampa_max_1h":        float("nan"),
            "rampa_max_1h_ts":     None,
            "rampa_max_3h":        float("nan"),
            "rampa_max_3h_ts":     None,
            "pct_renov_var":       float("nan"),
        }
    mask = (
        (df_long["submercado"] == code)
        & (df_long["data"] >= pd.Timestamp(data_ini))
        & (df_long["data"] <= pd.Timestamp(data_fim))
    )
    pivot = df_long.loc[mask].pivot_table(
        index="data_hora", columns="fonte", values="mwmed", aggfunc="mean",
    ).sort_index()
    for col in ("carga", "eolica", "solar"):
        if col not in pivot.columns:
            pivot[col] = 0.0
    pivot[["carga", "eolica", "solar"]] = (
        pivot[["carga", "eolica", "solar"]].fillna(0)
    )
    carga_mean = pivot["carga"].mean()
    eolica_mean = pivot["eolica"].mean()
    solar_mean = pivot["solar"].mean()
    liq_mean = carga_mean - eolica_mean - solar_mean
    pct = (
        (eolica_mean + solar_mean) / carga_mean * 100
        if carga_mean and carga_mean > 0 else float("nan")
    )

    def _max_abs(s):
        s = s.dropna()
        if s.empty:
            return float("nan"), None
        a = s.abs()
        i = a.idxmax()
        return float(a.loc[i]), i

    r1, t1 = _max_abs(rampa_1h)
    r3, t3 = _max_abs(rampa_3h)
    return {
        "carga_total_media":   carga_mean,
        "carga_liquida_media": liq_mean,
        "rampa_max_1h":        r1,
        "rampa_max_1h_ts":     t1,
        "rampa_max_3h":        r3,
        "rampa_max_3h_ts":     t3,
        "pct_renov_var":       pct,
    }


def main():
    print("Carregando balanço (15a)...")
    df = load_balanco_subsistema(incluir_historico_completo=False)
    print(f"  rows: {len(df):,}")
    print(f"  range: {df['data_hora'].min()} → {df['data_hora'].max()}")

    max_d = df["data_hora"].max().date()
    ini = max_d - timedelta(days=30)
    print(f"\nJanela teste: {ini} → {max_d} (último mês)")

    for code in ("SIN", "SE", "NE"):
        print(f"\n--- {code} ---")
        k = _compute_kpis_carga(df, code, ini, max_d)
        print(f"  carga total média    : {k['carga_total_media']:>10,.0f} MWmed")
        print(f"  carga líquida média  : {k['carga_liquida_media']:>10,.0f} MWmed")
        print(f"  rampa máx 1h         : {k['rampa_max_1h']:>10,.0f} MW   @ {k['rampa_max_1h_ts']}")
        print(f"  rampa máx 3h         : {k['rampa_max_3h']:>10,.0f} MW   @ {k['rampa_max_3h_ts']}")
        print(f"  % renov variáveis    : {k['pct_renov_var']:>10.1f} %")


if __name__ == "__main__":
    main()
