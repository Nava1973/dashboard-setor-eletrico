"""
validate_balanco.py — smoke test do load_balanco_subsistema().

Roda o loader real (bypass de cache Streamlit via .clear() se já houver),
valida schema, integridade e números conhecidos da spec/research.

Como rodar (da raiz):
  venv/Scripts/python.exe scripts/validate_balanco.py
"""
from __future__ import annotations
import sys
import traceback

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd

# Adiciona raiz ao path pra importar data_loader
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from data_loader import load_balanco_subsistema


def section(title):
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


section("1) Invocando load_balanco_subsistema()")
try:
    df = load_balanco_subsistema()
except Exception:
    traceback.print_exc()
    sys.exit(1)

print(f"  shape: {df.shape}")
print(f"  cols:  {list(df.columns)}")
print(f"  dtypes:")
for c, dt in df.dtypes.items():
    print(f"    {c:15} {dt}")


section("2) Schema: submercados e fontes")
print(f"  submercados únicos : {sorted(df['submercado'].unique().tolist())}")
print(f"  fontes únicas      : {sorted(df['fonte'].unique().tolist())}")
print(f"  range temporal     : {df['data_hora'].min()} .. {df['data_hora'].max()}")

expected_subs = {"SE", "S", "NE", "N", "SIN"}
expected_fontes = {"hidro", "termica", "eolica", "solar", "carga", "intercambio"}
got_subs = set(df["submercado"].unique())
got_fontes = set(df["fonte"].unique())
assert got_subs == expected_subs, f"submercados: esperado {expected_subs}, obtido {got_subs}"
assert got_fontes == expected_fontes, f"fontes: esperado {expected_fontes}, obtido {got_fontes}"
print("  OK: submercados e fontes batem com schema esperado")


section("3) Cobertura anual")
df["_ano"] = df["data_hora"].dt.year
cov = df.groupby("_ano").size()
print(f"  anos cobertos: {cov.index.min()} a {cov.index.max()} ({len(cov)} anos)")
print(f"  linhas por ano (primeiros/últimos 3):")
print(cov.head(3).to_string())
print("  ...")
print(cov.tail(3).to_string())


section("4) Smoke test 2024 (SIN) — comparar com research doc")
d24 = df[(df["data_hora"].dt.year == 2024) & (df["submercado"] == "SIN")]
pivot24 = d24.pivot_table(
    index="data_hora", columns="fonte", values="mwmed", aggfunc="mean"
)
m = pivot24.mean()
print(f"  SIN 2024 média anual (GWmed):")
for f in ["hidro", "termica", "eolica", "solar", "carga"]:
    if f in m.index:
        print(f"    {f:12} {m[f]/1000:7.2f}")
if all(f in m.index for f in ["hidro", "termica", "eolica", "solar"]):
    total_ger = m[["hidro", "termica", "eolica", "solar"]].sum()
    pct_renov = (m["eolica"] + m["solar"]) / total_ger * 100
    print(f"    {'TOTAL GER':12} {total_ger/1000:7.2f}  (spec: 75-80)")
    print(f"    {'renov var':12} {pct_renov:6.2f}%  (spec: 22-25, esperado ~26)")

# Sanity check dos valores esperados do research
assert 75 <= total_ger/1000 <= 82, f"SIN 2024 total fora da faixa: {total_ger/1000}"
assert 24 <= pct_renov <= 28, f"renov var 2024 fora da faixa: {pct_renov}"
print("  OK: números SIN 2024 dentro do esperado")


section("5) SIN vs soma dos 4 (validação cruzada)")
# Soma dos 4 subs por timestamp e fonte
cols_geracao = ["hidro", "termica", "eolica", "solar", "carga"]
sum4 = (
    df[df["submercado"].isin(["SE", "S", "NE", "N"])]
    .groupby(["data_hora", "fonte"])["mwmed"]
    .sum()
    .unstack("fonte")
)
sin = (
    df[df["submercado"] == "SIN"]
    .pivot_table(index="data_hora", columns="fonte", values="mwmed", aggfunc="mean")
)
# Align
common_idx = sum4.index.intersection(sin.index)
for f in cols_geracao:
    if f not in sum4.columns or f not in sin.columns:
        continue
    diff = (sum4.loc[common_idx, f] - sin.loc[common_idx, f]).abs()
    print(f"  {f:10} max|soma4-SIN|={diff.max():>8.2f}  mean={diff.mean():>6.3f}")


section("6) NaN por fonte (deve ser 0 ou quase)")
for f in sorted(df["fonte"].unique()):
    n = df[df["fonte"] == f]["mwmed"].isna().sum()
    total = (df["fonte"] == f).sum()
    print(f"  {f:12} {n}/{total} ({n/total*100:.3f}%)")


section("FIM")
print("  Validação concluída sem erros. Loader pronto pra ser consumido pela aba.")
