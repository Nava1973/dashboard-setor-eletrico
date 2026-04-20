"""
validate_reservatorios.py — utilitário de validação (NÃO é executado pelo app).

Rodar sempre que suspeitar de mudança no dataset ONS ear-diario-por-subsistema:
  - Após ONS publicar um novo ano (janeiro/ano seguinte)
  - Se o loader começar a retornar shape inesperado
  - Pra auditar integridade do cálculo SIN
  - Após upgrade de pandas/pyarrow que possa afetar leitura parquet

Checa:
  - Shape esperado (anos × 365 × 5 subsistemas aproximadamente)
  - Todos os 5 códigos presentes (N, NE, S, SE, SIN)
  - SIN calculado bate com expectativa (peso do SE domina)
  - Range histórico (2000-hoje)

Como rodar (da raiz do projeto):
  venv/Scripts/python.exe scripts/validate_reservatorios.py
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
from data_loader import load_reservatorios  # noqa: E402


def main():
    print("=" * 70)
    print("  LOAD RESERVATÓRIOS")
    print("=" * 70)
    try:
        df = load_reservatorios()
    except Exception:
        print("FALHOU — traceback completo:")
        traceback.print_exc()
        return

    print(f"\n  shape       : {df.shape}")
    print(f"  colunas     : {list(df.columns)}")
    print(f"  dtypes:")
    for c, dt in df.dtypes.items():
        print(f"    {c:18} {dt}")

    print(f"\n  data min    : {df['data'].min()}")
    print(f"  data max    : {df['data'].max()}")

    print(f"\n  Por subsistema:")
    grouped = df.groupby("subsistema_code").agg(
        n=("data", "count"),
        data_min=("data", "min"),
        data_max=("data", "max"),
        pct_min=("ear_pct", "min"),
        pct_mean=("ear_pct", "mean"),
        pct_max=("ear_pct", "max"),
    )
    print(grouped.to_string())

    # Sanity: todos os 5 códigos presentes
    codes = sorted(df["subsistema_code"].unique().tolist())
    print(f"\n  códigos únicos: {codes}")
    expected = ["N", "NE", "S", "SE", "SIN"]
    missing = set(expected) - set(codes)
    if missing:
        print(f"  ⚠ faltando: {missing}")
    else:
        print("  ✓ todos os 5 presentes")

    # Sanity SIN: algumas datas amostra, confirmar valor SIN bate
    # com soma dos 4 subsistemas / soma ear_max
    print(f"\n  Amostra de 3 datas (SIN vs subsistemas):")
    datas_amostra = df[df["subsistema_code"] == "SIN"]["data"].sample(
        n=3, random_state=42
    )
    for d in datas_amostra:
        linhas = df[df["data"] == d].sort_values("subsistema_code")
        print(f"\n    data: {d.date()}")
        for _, r in linhas.iterrows():
            print(
                f"      {r['subsistema_code']:4} "
                f"({r['subsistema_nome']:10}) "
                f"ear_pct={r['ear_pct']:.2f}%"
            )

    # Primeiras e últimas linhas
    print(f"\n  primeiras 3:")
    print(df.head(3).to_string(index=False))
    print(f"\n  últimas 3:")
    print(df.tail(3).to_string(index=False))


if __name__ == "__main__":
    main()
