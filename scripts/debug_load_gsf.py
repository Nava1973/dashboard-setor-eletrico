"""
debug_load_gsf.py — smoke test standalone do data_loaders/ccee_gsf.py.

Valida que load_gsf_mensal() retorna DataFrame nao-vazio com schema
correto e GSF batendo nos pontos oficiais.

Como rodar (da raiz do projeto):
    venv\\Scripts\\python.exe scripts\\debug_load_gsf.py

Saida esperada:
    - Schema validado
    - >= 25 meses cobertos
    - GSF nos 5 meses-amostra batendo com tolerancia oficial (Fase 0)
    - Estatisticas de cache
    - Output bem formatado
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# Permitir rodar de qualquer cwd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# Subset dos 15 pontos oficiais (5 representativos: surplus, deficit
# profundo, deficit moderado, neutro, recente)
PONTOS_AMOSTRA = {
    "2024-07": 0.84975,
    "2025-01": 1.13213,
    "2025-07": 0.69330,
    "2025-12": 0.73600,
    "2026-02": 1.00318,
}


def main():
    print("=" * 75)
    print("DEBUG load_gsf_mensal — smoke test Fase 1")
    print("=" * 75)

    from data_loaders.ccee_gsf import (
        load_gsf_mensal,
        load_gsf_historico_pre2023,
        clear_gsf_cache,
        is_gsf_cache_fresh,
        RESOURCE_IDS_BY_YEAR,
        _get_cache_dir,
    )

    print(f"\n[Setup]")
    print(f"  Cache dir: {_get_cache_dir()}")
    print(f"  Resource IDs mapeados: {len(RESOURCE_IDS_BY_YEAR)} anos "
          f"({sorted(RESOURCE_IDS_BY_YEAR.keys())})")

    cache_fresh_pre = is_gsf_cache_fresh()
    print(f"  Cache fresh (todos os anos)? {cache_fresh_pre}")

    # ---- 1. Carregar (com ou sem cache) ----
    print(f"\n[1] Chamando load_gsf_mensal()...")
    t0 = time.time()
    df = load_gsf_mensal()
    elapsed = time.time() - t0
    print(f"  -> retornou em {elapsed:.2f}s")

    # ---- 2. Validar schema ----
    print(f"\n[2] Validacao de schema:")
    cols_esperadas = {"sum_geracao_mre_mwh", "sum_gf_mre_mwh",
                      "gsf", "fonte_dado"}
    cols_recebidas = set(df.columns)
    assert cols_esperadas == cols_recebidas, (
        f"colunas divergem!\n  esperadas: {sorted(cols_esperadas)}\n"
        f"  recebidas: {sorted(cols_recebidas)}"
    )
    print(f"  Colunas OK: {sorted(df.columns)}")

    assert df.index.name == "mes_ref", \
        f"index.name esperado 'mes_ref', recebido {df.index.name!r}"
    assert str(df.index.dtype).startswith("datetime64"), \
        f"index dtype esperado datetime64, recebido {df.index.dtype}"
    print(f"  Index OK: name='mes_ref', dtype={df.index.dtype}")

    assert df.index.is_monotonic_increasing, \
        "index nao esta em ordem ASC"
    assert not df.index.duplicated().any(), "index tem duplicatas"
    print(f"  Index ASC sem duplicatas: OK")

    assert not df.empty, "DataFrame vazio!"
    print(f"  Linhas: {len(df)} (esperado >= 25)")
    assert len(df) >= 25, f"poucos meses: {len(df)}"

    # ---- 3. Range temporal ----
    print(f"\n[3] Cobertura temporal:")
    print(f"  Primeiro mes: {df.index.min().strftime('%Y-%m')}")
    print(f"  Ultimo mes:   {df.index.max().strftime('%Y-%m')}")
    print(f"  Total meses:  {len(df)}")

    # ---- 4. Tipos das colunas ----
    print(f"\n[4] Dtypes das colunas:")
    for c in df.columns:
        print(f"    {c:>22}  {df[c].dtype}")

    # ---- 5. Sample head e tail ----
    print(f"\n[5] Head(3):")
    print(df.head(3).to_string())
    print(f"\n  Tail(3):")
    print(df.tail(3).to_string())

    # ---- 6. fonte_dado distribuicao ----
    print(f"\n[6] Distribuicao fonte_dado:")
    print(df["fonte_dado"].value_counts().to_string())

    # ---- 7. Validar GSF em pontos amostra ----
    print(f"\n[7] Validacao contra pontos oficiais (Fase 0):")
    print(f"  {'mes_ref':>9}  {'oficial':>9}  {'calc':>9}  {'diff_pp':>9}  status")
    hits = 0
    fails = []
    for mes_str, oficial in PONTOS_AMOSTRA.items():
        ts = pd.Timestamp(mes_str + "-01")
        if ts not in df.index:
            print(f"  {mes_str}  {oficial*100:>8.3f}%  AUSENTE no df")
            fails.append((mes_str, "ausente"))
            continue
        calc = df.loc[ts, "gsf"]
        diff_pp = (calc - oficial) * 100
        if abs(diff_pp) < 0.5:
            status = "HIT(0.5)"
            hits += 1
        elif abs(diff_pp) < 1.0:
            status = "hit(1.0)"
        else:
            status = "FAIL"
            fails.append((mes_str, f"diff={diff_pp:+.3f}"))
        print(f"  {mes_str}  {oficial*100:>8.3f}%  {calc*100:>8.3f}%  "
              f"{diff_pp:>+8.4f}  {status}")
    print(f"\n  Hits +/-0.5pp: {hits}/{len(PONTOS_AMOSTRA)}")
    if fails:
        print(f"  Fails: {fails}")

    # ---- 8. Cache pos-load ----
    cache_fresh_post = is_gsf_cache_fresh()
    print(f"\n[8] Cache fresh apos load: {cache_fresh_post}")

    # ---- 9. Re-load (deve ser instantaneo via @st.cache_data) ----
    print(f"\n[9] Re-load (cache RAM hit esperado)...")
    t0 = time.time()
    df2 = load_gsf_mensal()
    elapsed2 = time.time() - t0
    print(f"  -> {elapsed2:.3f}s")
    assert df2.equals(df), "re-load retornou DataFrame diferente!"
    print(f"  Bate com 1a chamada: OK")

    # ---- 10. V2 — historico pre-2023 (deve retornar vazio sem arquivo) ----
    print(f"\n[10] V2 — load_gsf_historico_pre2023():")
    df_v2 = load_gsf_historico_pre2023()
    print(f"  Linhas: {len(df_v2)}  (esperado: 0 se arquivo nao existe)")
    if df_v2.empty:
        print(f"  Schema retornado: {list(df_v2.columns)}  OK (vazio)")
    else:
        print(f"  ATENCAO: arquivo encontrado e parseado!")
        print(df_v2.head(3).to_string())

    # ---- 11. V1 + V2 integrado ----
    print(f"\n[11] load_gsf_mensal(incluir_historico_pre2023=True):")
    df_full = load_gsf_mensal(incluir_historico_pre2023=True)
    print(f"  Linhas: {len(df_full)} (esperado >= V1 sem V2)")
    fontes = df_full["fonte_dado"].value_counts().to_dict()
    print(f"  Fontes: {fontes}")

    # ---- 12. Estatisticas finais ----
    print(f"\n[12] Estatisticas finais do GSF V1:")
    gsf_pct = df["gsf"] * 100
    print(f"  min   = {gsf_pct.min():.2f}%")
    print(f"  max   = {gsf_pct.max():.2f}%")
    print(f"  mean  = {gsf_pct.mean():.2f}%")
    print(f"  median= {gsf_pct.median():.2f}%")
    n_secundaria = (gsf_pct > 100).sum()
    print(f"  meses com Energia Secundaria (GSF>100%): {n_secundaria}")

    print(f"\n[FIM] Smoke test concluido sem erro.")
    if hits == len(PONTOS_AMOSTRA):
        print(f"  Status: TODOS os {hits} pontos-amostra dentro de +/-0.5pp")
    elif hits >= len(PONTOS_AMOSTRA) - 1:
        print(f"  Status: {hits}/{len(PONTOS_AMOSTRA)} amostras OK")
    else:
        print(f"  Status: {hits}/{len(PONTOS_AMOSTRA)} — INVESTIGAR!")


if __name__ == "__main__":
    # Garantir import pd no escopo (usado nas asserts via pd.Timestamp)
    import pandas as pd  # noqa: F401 — usado no main()
    globals()["pd"] = pd
    main()
