"""
validar_gsf_calculado_vs_mre.py — utilitario de validacao (NAO e executado pelo app).

Roda a formula do loader oficial (`data_loaders/ccee_gsf.load_gsf_mensal()`)
contra os 15 pontos oficiais de GSF (9 do Power BI publico CCEE + 6 do
InfoPLD) coletados durante a Fase 0 do Sprint GSF (§5.77 do CLAUDE.md).

Util como REGRESSAO contra:
  - Mudancas silenciosas no dataset CCEE (colunas renomeadas, novas
    convencoes de MES_REFERENCIA, recontabilizacoes pos-publicacao).
  - Quebras introduzidas no loader (`_agregar_mensal`, `_carregar_ano_horario`).
  - Drift no calculo do GSF que escape do compile-check (tipos batem,
    mas semantica muda).

Diferenca pra `validacao_final_gsf.py` (sibling): aquele baixa do CKAN
direto e roda a formula manual — foi a prova de Fase 0 que estabeleceu
a formula. ESTE valida o LOADER do projeto, que e o que de fato roda
em producao. Os dois sao complementares.

Criterio de aceitacao:
  - Pontos dentro do range coberto pelo loader (nov/2023+): diff <0.5pp
    contra oficial = HIT. Diff 0.5-1.0pp = WARN (aceitavel, investigar).
    Diff >1.0pp = FAIL (script retorna exit code 1).
  - Pontos fora do range (~3 dos 15): SKIP, nao contam contra hits.

Como rodar (da raiz do projeto):
  venv/Scripts/python.exe scripts/validar_gsf_calculado_vs_mre.py

Flags opcionais:
  --fresh   Limpa cache (RAM + disk) antes de carregar — forca re-download
            do CKAN. Util pra checar dataset realmente atual. Caro (~25s).
            Sem a flag, usa cache existente (~60ms warm-disk).

Exit codes:
  0 = todos os pontos cobertos passaram (<0.5pp).
  1 = pelo menos 1 FAIL (>1.0pp diff vs oficial).
  2 = erro inesperado durante execucao.
"""
from __future__ import annotations

import os
import sys
import traceback

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from data_loaders.ccee_gsf import load_gsf_mensal, clear_gsf_cache  # noqa: E402


# 15 pontos oficiais coletados na Fase 0 do Sprint GSF (§5.77).
# Valores em PERCENTUAL (multiplicar gsf decimal do loader por 100 pra
# comparar). Fonte:
#   - 9 do Power BI publico CCEE (Painel GSF)
#   - 6 do InfoPLD (boletim semanal CCEE)
# Mantido sincronizado com `validacao_final_gsf.py` (a verdade dos 2 e a
# mesma — esses sao os dados oficiais que validam a formula).
GSF_OFICIAL_PCT = {
    "2023-03": 101.564,  # SKIP esperado: arquivo de 2023 do CCEE comeca em nov/2023
    "2023-07":  77.957,  # SKIP esperado: mesma razao
    "2024-03":  95.041,  # OK: arquivo de 2024 tem o mes inteiro
    "2024-07":  84.975,
    "2025-01": 113.213,
    "2025-02": 110.957,
    "2025-06":  87.700,
    "2025-07":  69.330,
    "2025-08":  62.600,
    "2025-09":  63.000,
    "2025-10":  63.100,
    "2025-11":  65.700,
    "2025-12":  73.600,
    "2026-01":  81.207,
    "2026-02": 100.318,
}

TOLERANCIA_HIT_PP = 0.5   # <0.5pp = HIT
TOLERANCIA_WARN_PP = 1.0  # 0.5-1.0pp = WARN, >1.0pp = FAIL


def main() -> int:
    print("=" * 75)
    print("  VALIDAR GSF CALCULADO (loader) vs OFICIAL (CCEE Power BI + InfoPLD)")
    print("=" * 75)

    fresh = "--fresh" in sys.argv
    if fresh:
        print("\n  Flag --fresh: limpando cache (RAM + disk parquets)...")
        try:
            clear_gsf_cache()
            print("  Cache limpo. Proxima chamada vai re-baixar do CKAN (~25s).")
        except Exception as e:
            print(f"  [WARN] Falha ao limpar cache: {e}")

    print("\n  Chamando load_gsf_mensal()...")
    try:
        df = load_gsf_mensal()
    except Exception:
        print("  [FATAL] Erro carregando GSF:")
        traceback.print_exc()
        return 2

    if df.empty:
        print("  [FATAL] load_gsf_mensal() retornou DataFrame vazio.")
        return 2

    print(f"  shape       : {df.shape}")
    print(f"  colunas     : {list(df.columns)}")
    print(f"  range       : {df.index.min().date()} a {df.index.max().date()}")
    print(f"  fonte_dado  : {sorted(df['fonte_dado'].unique())}")

    # Mapeia "YYYY-MM" -> primeiro dia do mes pra lookup no index do loader
    def _mes_key_to_ts(k: str) -> pd.Timestamp:
        ano, mes = k.split("-")
        return pd.Timestamp(int(ano), int(mes), 1)

    print("\n" + "-" * 75)
    print(f"  {'mes':>8}  {'oficial':>9}  {'loader':>9}  {'diff_pp':>9}  status")
    print("-" * 75)

    hits = 0
    warns = 0
    fails = 0
    skips = 0
    diffs = []
    fails_list: list[tuple[str, float, float, float]] = []

    for mes_key, oficial_pct in GSF_OFICIAL_PCT.items():
        ts = _mes_key_to_ts(mes_key)
        if ts not in df.index:
            print(f"  {mes_key}  {oficial_pct:>8.3f}%  n/d        n/d         "
                  "SKIP (fora do range coberto pelo loader)")
            skips += 1
            continue

        # Loader retorna gsf em DECIMAL (ex: 0.8497) — converter pra pct.
        gsf_loader_pct = float(df.loc[ts, "gsf"]) * 100.0
        diff = gsf_loader_pct - oficial_pct
        diffs.append(diff)

        if abs(diff) < TOLERANCIA_HIT_PP:
            status = "[OK]"
            hits += 1
        elif abs(diff) < TOLERANCIA_WARN_PP:
            status = "[WARN]"
            warns += 1
        else:
            status = "[FAIL]"
            fails += 1
            fails_list.append((mes_key, oficial_pct, gsf_loader_pct, diff))

        print(f"  {mes_key}  {oficial_pct:>8.3f}%  {gsf_loader_pct:>8.3f}%  "
              f"{diff:>+8.4f}  {status}")

    print("-" * 75)
    avaliados = hits + warns + fails
    print(f"\n  RESUMO:")
    print(f"    Pontos avaliados:   {avaliados}/{len(GSF_OFICIAL_PCT)} "
          f"(skipados: {skips})")
    print(f"    HITS  (<0.5pp):     {hits}")
    print(f"    WARNS (0.5-1.0pp):  {warns}")
    print(f"    FAILS (>1.0pp):     {fails}")

    if diffs:
        mean_abs = sum(abs(d) for d in diffs) / len(diffs)
        max_abs = max(abs(d) for d in diffs)
        mean_signed = sum(diffs) / len(diffs)
        print(f"    Mean abs diff:      {mean_abs:.4f} pp")
        print(f"    Max  abs diff:      {max_abs:.4f} pp")
        print(f"    Mean signed diff:   {mean_signed:+.4f} pp")

    if fails_list:
        print(f"\n  FAILS detalhados:")
        for mes_key, of, lo, d in fails_list:
            print(f"    {mes_key}: oficial={of:.3f}%  loader={lo:.3f}%  "
                  f"diff={d:+.3f}pp")

    print()
    if fails > 0:
        print(f"  STATUS: [FAIL] {fails} ponto(s) fora da tolerancia de "
              f"{TOLERANCIA_WARN_PP}pp. Investigar antes de prosseguir.")
        return 1
    elif warns > 0:
        print(f"  STATUS: [OK com WARN] {hits} hits + {warns} warns "
              f"(<{TOLERANCIA_WARN_PP}pp). Aceitavel mas vale revisar.")
        return 0
    else:
        print(f"  STATUS: [OK] {hits}/{avaliados} hits dentro de "
              f"{TOLERANCIA_HIT_PP}pp. Formula do loader bate com o oficial.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
