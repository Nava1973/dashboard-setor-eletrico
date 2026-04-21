"""
validate_ena.py — utilitário de validação (NÃO é executado pelo app).

Rodar sempre que suspeitar de mudança no dataset ONS ena-diario-por-subsistema:
  - Após ONS publicar um novo ano (janeiro/ano seguinte)
  - Se o loader começar a retornar shape inesperado
  - Pra auditar integridade do cálculo SIN (soma simples)
  - Após upgrade de pandas/openpyxl que possa afetar leitura xlsx

Checa:
  - Shape esperado (~27 anos × 365 × 5 subsistemas)
  - Todos os 5 códigos presentes (N, NE, S, SE, SIN)
  - SIN calculado bate com N+NE+S+SE (amostras aleatórias)
  - Range histórico (2000-hoje)
  - Valores extremos (seco máximo, cheia máxima)

Como rodar (da raiz do projeto):
  venv/Scripts/python.exe scripts/validate_ena.py
"""
from __future__ import annotations
import sys
import traceback

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_loader import load_ena  # noqa: E402


def main():
    print("=" * 70)
    print("  LOAD ENA")
    print("=" * 70)
    try:
        df = load_ena()
    except Exception:
        print("FALHOU — traceback completo:")
        traceback.print_exc()
        return

    print(f"\n  shape       : {df.shape}")
    print(f"  colunas     : {list(df.columns)}")
    print(f"  dtypes:")
    for c, dt in df.dtypes.items():
        print(f"    {c:25} {dt}")

    print(f"\n  data min    : {df['data'].min()}")
    print(f"  data max    : {df['data'].max()}")

    print(f"\n  Por subsistema:")
    grouped = df.groupby("subsistema_code").agg(
        n=("data", "count"),
        data_min=("data", "min"),
        data_max=("data", "max"),
        mwmed_min=("ena_mwmed", "min"),
        mwmed_mean=("ena_mwmed", "mean"),
        mwmed_max=("ena_mwmed", "max"),
        mlt_mean=("ena_mlt_pct", "mean"),
    )
    print(grouped.to_string())

    # Sanity: todos os 5 códigos presentes
    codes = sorted(df["subsistema_code"].unique().tolist())
    print(f"\n  códigos únicos: {codes}")
    expected = ["N", "NE", "S", "SE", "SIN"]
    missing = set(expected) - set(codes)
    if missing:
        print(f"  [WARN] faltando: {missing}")
    else:
        print("  [OK] todos os 5 presentes")

    # Sanity SIN: amostras de datas, confirmar SIN == soma(4 subs)
    print(f"\n  Amostra de 3 datas (SIN vs soma dos 4 subsistemas):")
    datas_amostra = df[df["subsistema_code"] == "SIN"]["data"].sample(
        n=3, random_state=42
    )
    for d in datas_amostra:
        linhas = df[df["data"] == d].sort_values("subsistema_code")
        subs = linhas[linhas["subsistema_code"].isin(["N", "NE", "S", "SE"])]
        sin_row = linhas[linhas["subsistema_code"] == "SIN"]
        soma = subs["ena_mwmed"].sum()
        sin_val = sin_row["ena_mwmed"].iloc[0] if not sin_row.empty else float("nan")
        diff = abs(soma - sin_val)
        ok = "OK" if diff < 0.01 else "MISMATCH"
        print(f"\n    data: {d.date()}  [{ok}]")
        for _, r in linhas.iterrows():
            print(
                f"      {r['subsistema_code']:4} "
                f"({r['subsistema_nome']:10}) "
                f"ena_mwmed={r['ena_mwmed']:10.2f}  "
                f"mlt_pct={r['ena_mlt_pct']:6.2f}"
            )
        print(f"      --> soma dos 4 = {soma:.2f}  |  SIN = {sin_val:.2f}  |  diff = {diff:.4f}")

    # Sanity SIN em % MLT: recalcular pela fórmula de reversão da MLT absoluta
    # e conferir contra o valor publicado pelo loader.
    #
    # Fórmula canônica:
    #   mlt_abs_sub(data) = ena_mwmed_sub(data) / (pct_mlt_sub(data) / 100)
    #   SIN_mlt_pct(data) = sum(ena_mwmed_sub) / sum(mlt_abs_sub) × 100
    print(f"\n  Amostra de 3 datas — SIN em % MLT (fórmula de reversão):")
    datas_pct = df[df["subsistema_code"] == "SIN"]["data"].sample(
        n=3, random_state=7
    )
    for d in datas_pct:
        linhas = df[df["data"] == d]
        subs = linhas[linhas["subsistema_code"].isin(["N", "NE", "S", "SE"])]
        sin_row = linhas[linhas["subsistema_code"] == "SIN"]
        if sin_row.empty or subs.empty:
            continue
        pct = subs["ena_mlt_pct"]
        valid = pct > 0
        num = subs.loc[valid, "ena_mwmed"].sum()
        den = (subs.loc[valid, "ena_mwmed"] / (pct[valid] / 100.0)).sum()
        pct_calc = num / den * 100 if den > 0 else float("nan")
        pct_sin = sin_row["ena_mlt_pct"].iloc[0]
        diff = abs(pct_calc - pct_sin)
        ok = "OK" if diff < 0.01 else "MISMATCH"
        print(
            f"    {d.date()}  SIN.mlt_pct={pct_sin:7.3f}%  "
            f"recalc={pct_calc:7.3f}%  diff={diff:.4f}  [{ok}]"
        )

    # Valores extremos históricos por subsistema
    print(f"\n  Valores extremos históricos (ena_mwmed):")
    print(f"    {'code':4} {'seco_min_mwmed':>15} {'data_seco':>12} "
          f"{'cheia_max_mwmed':>15} {'data_cheia':>12}")
    for code in ["SIN", "SE", "S", "NE", "N"]:
        sub = df[df["subsistema_code"] == code]
        if sub.empty:
            continue
        row_min = sub.loc[sub["ena_mwmed"].idxmin()]
        row_max = sub.loc[sub["ena_mwmed"].idxmax()]
        print(
            f"    {code:4} "
            f"{row_min['ena_mwmed']:15.1f} "
            f"{str(row_min['data'].date()):>12} "
            f"{row_max['ena_mwmed']:15.1f} "
            f"{str(row_max['data'].date()):>12}"
        )

    # Primeiras e últimas linhas
    print(f"\n  primeiras 3:")
    print(df.head(3).to_string(index=False))
    print(f"\n  últimas 3:")
    print(df.tail(3).to_string(index=False))


if __name__ == "__main__":
    main()
