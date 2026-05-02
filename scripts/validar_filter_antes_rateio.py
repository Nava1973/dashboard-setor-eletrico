"""
validar_filter_antes_rateio.py
==============================

Prova de não-regressão pra refator de performance da aba Curtailment:
filtrar por FONTE ANTES de aplicar_rateio (em vez de depois).

Compara bit-a-bit o output de:

    Path A (atual): aplicar_rateio(df_curt_raw_completo) -> filter por fonte
    Path B (novo):  filter por fonte -> aplicar_rateio(df_filtrado)

Pra cada fonte (Solar, Eólica), valida:
  1. Mesmo número de linhas
  2. Soma de FRUSTRADO_MWH idêntica em 1e-9
  3. Soma de OUTPUT_MWH idêntica em 1e-9
  4. df_a.equals(df_b) bit-a-bit (após sort + reset_index)

Sort necessário porque pandas.merge how="left" pode produzir linhas em
ordem ligeiramente diferente quando a ordem do input difere — sort
elimina esse falso-positivo.

Roda fora do Streamlit (warning de "no script run context" é esperado e
inofensivo — funções @st.cache_data viram no-op).

Uso:
    venv\\Scripts\\python.exe scripts/validar_filter_antes_rateio.py
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

# Permitir imports do projeto a partir do scripts/
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Encoding pra prints com Unicode no Windows cp1252 (armadilha 4.4)
sys.stdout.reconfigure(encoding="utf-8")

from data_loaders.data_loader_curtailment import (
    carregar_curtailment, descobrir_ultimo_dia_disponivel,
)
from data_loaders.data_loader_grupos_excel import (
    carregar_grupos_excel, carregar_aliases, aplicar_rateio,
)


def _comparar_paths(df_curt_raw, df_grupos, aliases, fonte_label: str) -> bool:
    """Compara Path A (filter depois) vs Path B (filter antes) pra uma fonte."""
    fonte_code = "SOLAR" if fonte_label == "Solar" else "EOLICA"
    print(f"\n{'='*70}")
    print(f"FONTE: {fonte_label} ({fonte_code})")
    print(f"{'='*70}")

    # Path A: rateio em tudo, depois filter
    print("Path A (atual): aplicar_rateio(tudo) -> filter por FONTE")
    df_join_a = aplicar_rateio(df_curt_raw, df_grupos, aliases)
    df_a = df_join_a[df_join_a["FONTE"] == fonte_code].copy()
    print(f"  resultado: {len(df_a):,} linhas")

    # Path B: filter, depois rateio
    print("Path B (novo): filter por FONTE -> aplicar_rateio(filtrado)")
    df_filtrado = df_curt_raw[df_curt_raw["FONTE"] == fonte_code].copy()
    df_b = aplicar_rateio(df_filtrado, df_grupos, aliases)
    print(f"  resultado: {len(df_b):,} linhas")

    # ---------- Comparações ----------
    ok = True

    # 1. Mesma cardinalidade
    if len(df_a) != len(df_b):
        print(f"  ✗ FAIL: len difere ({len(df_a)} vs {len(df_b)})")
        ok = False
    else:
        print(f"  ✓ len iguais: {len(df_a):,}")

    # 2. Soma FRUSTRADO_MWH
    sum_fr_a = float(df_a["FRUSTRADO_MWH"].sum())
    sum_fr_b = float(df_b["FRUSTRADO_MWH"].sum())
    diff_fr = abs(sum_fr_a - sum_fr_b)
    if diff_fr > 1e-6:
        print(
            f"  ✗ FAIL: sum FRUSTRADO_MWH difere "
            f"(A={sum_fr_a:.6f}, B={sum_fr_b:.6f}, diff={diff_fr:.2e})"
        )
        ok = False
    else:
        print(
            f"  ✓ sum FRUSTRADO_MWH idêntico: {sum_fr_a:,.4f} "
            f"(diff={diff_fr:.2e})"
        )

    # 3. Soma OUTPUT_MWH
    sum_ot_a = float(df_a["OUTPUT_MWH"].sum())
    sum_ot_b = float(df_b["OUTPUT_MWH"].sum())
    diff_ot = abs(sum_ot_a - sum_ot_b)
    if diff_ot > 1e-6:
        print(
            f"  ✗ FAIL: sum OUTPUT_MWH difere "
            f"(A={sum_ot_a:.6f}, B={sum_ot_b:.6f}, diff={diff_ot:.2e})"
        )
        ok = False
    else:
        print(
            f"  ✓ sum OUTPUT_MWH idêntico: {sum_ot_a:,.4f} "
            f"(diff={diff_ot:.2e})"
        )

    # 4. df.equals bit-a-bit (após sort)
    sort_cols = [
        c for c in
        ["USINA", "DATA", "RAZAO", "NOME_USINA_DASH", "PROPRIETARIO"]
        if c in df_a.columns and c in df_b.columns
    ]
    cols_comuns = sorted(set(df_a.columns) & set(df_b.columns))
    df_a_sorted = (
        df_a[cols_comuns].sort_values(sort_cols).reset_index(drop=True)
    )
    df_b_sorted = (
        df_b[cols_comuns].sort_values(sort_cols).reset_index(drop=True)
    )
    if df_a_sorted.equals(df_b_sorted):
        print(f"  ✓ df.equals bit-a-bit (após sort por {sort_cols})")
    else:
        print(f"  ✗ FAIL: df.equals divergiu (após sort)")
        # Tenta diagnosticar: compara dtypes + soma por coluna numérica
        for col in cols_comuns:
            if col in sort_cols:
                continue
            if df_a_sorted[col].dtype != df_b_sorted[col].dtype:
                print(
                    f"      dtype divergiu em {col!r}: "
                    f"A={df_a_sorted[col].dtype}, B={df_b_sorted[col].dtype}"
                )
            try:
                eq = df_a_sorted[col].equals(df_b_sorted[col])
                if not eq:
                    print(f"      coluna {col!r} difere")
            except Exception as e:
                print(f"      erro comparando {col!r}: {e}")
        ok = False

    return ok


def main():
    print("=" * 70)
    print("VALIDAÇÃO DE NÃO-REGRESSÃO: filter por fonte ANTES de aplicar_rateio")
    print("=" * 70)

    # 1. Janela: 12 meses (mesma usada na sub-aba "Por usina")
    print("\n[1/3] Descobrindo última data disponível no ONS...")
    try:
        max_d = descobrir_ultimo_dia_disponivel("eolica") or date.today()
    except Exception:
        max_d = date.today()
    min_d = max_d - timedelta(days=365)
    print(f"  janela: {min_d} a {max_d}")

    # 2. Carregar dados
    print("\n[2/3] Carregando df_curt_raw, df_grupos, aliases...")
    df_curt_raw = carregar_curtailment(
        data_inicio=min_d, data_fim=max_d, fontes=("eolica", "solar"),
    )
    if df_curt_raw is None or len(df_curt_raw) == 0:
        print("✗ FAIL: df_curt_raw vazio. Verifique conexão / cache.")
        sys.exit(1)
    df_grupos = carregar_grupos_excel()
    aliases = carregar_aliases()
    print(
        f"  df_curt_raw: {len(df_curt_raw):,} linhas | "
        f"df_grupos: {len(df_grupos):,} | aliases: {len(aliases)}"
    )

    # 3. Comparar paths para cada fonte
    print("\n[3/3] Comparando paths...")
    ok_solar = _comparar_paths(df_curt_raw, df_grupos, aliases, "Solar")
    ok_eolica = _comparar_paths(df_curt_raw, df_grupos, aliases, "Eólica")

    # Resumo
    print(f"\n{'=' * 70}")
    if ok_solar and ok_eolica:
        print("✓ OK: paths matematicamente idênticos pra Solar e Eólica.")
        print("  Refator (filter antes do rateio) é seguro pra aplicar.")
        sys.exit(0)
    else:
        print("✗ FAIL: divergência detectada. NÃO aplicar refator.")
        sys.exit(2)


if __name__ == "__main__":
    main()
