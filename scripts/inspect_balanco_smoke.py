"""
inspect_balanco_smoke.py — só a parte 5 do inspect, com colunas corrigidas
(val_gersolar, não fotovoltaica) + range numérico real após coerção.
"""
from __future__ import annotations
import sys
import io
import traceback

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from curl_cffi import requests as http
    CURL_OK = True
except ImportError:
    import requests as http
    CURL_OK = False

import pandas as pd


def _get(url, **kwargs):
    if CURL_OK:
        return http.get(url, impersonate="chrome", timeout=120, **kwargs)
    return http.get(url, timeout=120, **kwargs)


PARQUET_URL = "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/balanco_energia_subsistema_ho/BALANCO_ENERGIA_SUBSISTEMA_{ano}.parquet"

# -------------------------------------------------------------------------
# Range numérico real de 2016 após coerção
# -------------------------------------------------------------------------
print("=" * 72)
print("  Range numérico real (2016) após pd.to_numeric")
print("=" * 72)

r = _get(PARQUET_URL.format(ano=2016))
df16 = pd.read_parquet(io.BytesIO(r.content))

num_cols = ["val_gerhidraulica", "val_gertermica", "val_gereolica", "val_gersolar",
            "val_carga", "val_intercambio"]
for c in num_cols:
    df16[c] = pd.to_numeric(df16[c], errors="coerce")

# Range por subsistema
print(f"\n  por submercado (id_subsistema):")
for sub in ["SIN", "SE", "S", "NE", "N"]:
    d = df16[df16["id_subsistema"] == sub]
    if d.empty:
        continue
    print(f"\n    {sub}:")
    for c in num_cols:
        s = d[c]
        print(f"      {c:25} min={s.min():>10.1f}  max={s.max():>10.1f}  mean={s.mean():>10.1f}")

# Validar que SIN é igual à soma dos 4
print(f"\n  SIN pré-calculado vs soma dos 4 submercados (validação):")
by_time = df16.groupby(["din_instante", "id_subsistema"])[
    ["val_gerhidraulica", "val_gertermica", "val_gereolica", "val_gersolar", "val_carga"]
].sum().reset_index()

pivot = by_time.pivot_table(
    index="din_instante",
    columns="id_subsistema",
    values=["val_gerhidraulica", "val_gertermica", "val_gereolica", "val_gersolar", "val_carga"],
)

for metric in ["val_gerhidraulica", "val_gertermica", "val_gereolica", "val_carga"]:
    soma_4 = pivot[metric][["SE", "S", "NE", "N"]].sum(axis=1)
    sin = pivot[metric]["SIN"]
    diff_abs = (soma_4 - sin).abs()
    diff_rel = (diff_abs / sin.abs().replace(0, pd.NA)).dropna()
    print(f"    {metric:25} max_diff_abs={diff_abs.max():>8.2f}  max_diff_rel={diff_rel.max()*100:>6.3f}%")


# -------------------------------------------------------------------------
# Smoke test 2024 com col_solar correta
# -------------------------------------------------------------------------
print()
print("=" * 72)
print("  Smoke test 2024 (val_gersolar)")
print("=" * 72)

r = _get(PARQUET_URL.format(ano=2024))
df24 = pd.read_parquet(io.BytesIO(r.content))
for c in num_cols:
    if c in df24.columns:
        df24[c] = pd.to_numeric(df24[c], errors="coerce")

# SIN já vem pronto — usa a linha direto
sin24 = df24[df24["id_subsistema"] == "SIN"].copy()
print(f"\n  registros SIN 2024: {len(sin24)}  (esperado: {366*24})")

# Média anual
m = sin24[["val_gerhidraulica", "val_gertermica", "val_gereolica", "val_gersolar", "val_carga"]].mean()
total = m["val_gerhidraulica"] + m["val_gertermica"] + m["val_gereolica"] + m["val_gersolar"]
print(f"\n  SIN 2024 (média anual de todas as horas):")
print(f"    hidráulica     : {m['val_gerhidraulica']/1000:7.2f} GWmed")
print(f"    térmica        : {m['val_gertermica']/1000:7.2f} GWmed")
print(f"    eólica         : {m['val_gereolica']/1000:7.2f} GWmed")
print(f"    solar          : {m['val_gersolar']/1000:7.2f} GWmed")
print(f"    geração total  : {total/1000:7.2f} GWmed   (spec: ~75-80)")
print(f"    carga          : {m['val_carga']/1000:7.2f} GWmed   (spec: ~75-80)")
pct_renov_var = (m['val_gereolica'] + m['val_gersolar']) / total * 100
print(f"    %(eol+sol)     : {pct_renov_var:5.2f}%   (spec: ~22-25)")

# NE 2024
ne24 = df24[df24["id_subsistema"] == "NE"].copy()
m_ne = ne24[["val_gerhidraulica", "val_gertermica", "val_gereolica", "val_gersolar"]].mean()
total_ne = m_ne.sum()
print(f"\n  NE 2024 (média anual):")
print(f"    total          : {total_ne/1000:7.2f} GWmed")
print(f"    %(eol+sol)     : {(m_ne['val_gereolica']+m_ne['val_gersolar'])/total_ne*100:5.2f}%   (spec: ~80% picos)")

# NE meses de pico — olhar alguns meses onde eolica+solar supera tudo
ne24["mes"] = ne24["din_instante"].dt.month
m_ne_mes = ne24.groupby("mes")[
    ["val_gerhidraulica", "val_gertermica", "val_gereolica", "val_gersolar"]
].mean()
m_ne_mes["total"] = m_ne_mes.sum(axis=1)
m_ne_mes["pct_renov"] = (m_ne_mes["val_gereolica"] + m_ne_mes["val_gersolar"]) / m_ne_mes["total"] * 100
print(f"\n  NE 2024 por mês (% renov variável):")
for mes, row in m_ne_mes.iterrows():
    print(f"    mês {mes:2}: {row['pct_renov']:5.2f}%")

# Sul 2024
s24 = df24[df24["id_subsistema"] == "S"].copy()
m_s = s24[["val_gerhidraulica", "val_gertermica", "val_gereolica", "val_gersolar"]].mean()
total_s = m_s.sum()
pct_term_s = m_s["val_gertermica"] / total_s * 100
pct_term_sin = m["val_gertermica"] / total * 100
print(f"\n  Sul 2024:")
print(f"    total          : {total_s/1000:7.2f} GWmed")
print(f"    %térmica       : {pct_term_s:5.2f}%   (SIN: {pct_term_sin:.2f}% — spec: Sul > SIN)")

# Range de datas em 2025/2026 (pra saber o "hoje" do dataset)
print()
print("=" * 72)
print("  Última data disponível (2026)")
print("=" * 72)
r26 = _get(PARQUET_URL.format(ano=2026))
df26 = pd.read_parquet(io.BytesIO(r26.content))
print(f"  shape 2026: {df26.shape}")
print(f"  din_instante min: {df26['din_instante'].min()}")
print(f"  din_instante max: {df26['din_instante'].max()}")

print()
print("FIM")
