"""
validar_filtro_razoes.py
========================

Prova de não-regressão pra G.6 (filtro por razão na sub-aba "Por usina").

Valida que `_calcular_linhas_unidade(df, ("CNF", "ENE", "REL"))` (path
NOVO com filtro de razão "todas marcadas") produz o MESMO resultado que
`_calcular_linhas_unidade(df, ())` (path SEM filtro, equivalente ao
comportamento pré-G.6).

Razão da equivalência:
    - Path NOVO com TODAS as razões operativas marcadas: zera FRUSTRADO_MWH
      apenas em RAZAO=PAR (que NÃO está em ("CNF","ENE","REL")) e em
      RAZAO=NaN não modifica (mask checa notna()).
    - PAR já é excluído downstream por `pct_no_periodo` (que chama
      `calcular_pct_curtailment` com default `RAZOES_OPERATIVAS`).
    - Linhas RAZAO=NaN preservam OUTPUT_MWH em ambos paths (mask de
      G.6 usa notna(), e o helper interno não considera RAZAO=NaN como
      razão).
    - Resultado: ambos paths calculam o MESMO numerador e denominador.

Asserts (pra cada fonte Solar e Eólica):
    1. len(linhas_a) == len(linhas_b)
    2. cada linha tem mesmo `unidade` e `proprietario`
    3. cada linha tem mesmos 7 valores de % (3 meses + 4 trimestres),
       comparação bit-a-bit (None == None, float == float exato)

Roda fora do Streamlit (warning de "no script run context" é esperado e
inofensivo — funções @st.cache_data viram no-op).

Uso:
    venv\\Scripts\\python.exe scripts/validar_filtro_razoes.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd  # noqa: E402

from data_loaders.data_loader_curtailment import (  # noqa: E402
    carregar_curtailment, descobrir_ultimo_dia_disponivel,
)
from data_loaders.data_loader_grupos_excel import (  # noqa: E402
    carregar_grupos_excel, carregar_aliases, aplicar_rateio,
)
from utils.utils_curtailment import _inicio_trimestre_anterior  # noqa: E402

# Import do helper que está sendo validado.
# tab_curtailment.py puxa Streamlit, mas só `_calcular_linhas_unidade`
# é chamado — @st.cache_data fica no-op fora de runtime, sem impacto.
from components.tab_curtailment import _calcular_linhas_unidade  # noqa: E402


def _aplicar_categorical(df: pd.DataFrame) -> pd.DataFrame:
    """Replica o que _carregar_curtailment_janela_ampla faz no wrapper."""
    if len(df) == 0:
        return df
    df = df.copy()
    for col in ("USINA", "RAZAO", "FONTE", "SUBMERCADO", "UF"):
        if col in df.columns:
            df[col] = df[col].astype("category")
    return df


def _comparar_paths(df_filtrado: pd.DataFrame, fonte_label: str) -> bool:
    print(f"\n{'=' * 70}")
    print(f"FONTE: {fonte_label}")
    print(f"{'=' * 70}")

    # Path A (NOVO): com filtro de razão = todas operativas marcadas
    print("Path A (NOVO): _calcular_linhas_unidade(df, ('CNF', 'ENE', 'REL'))")
    linhas_a = _calcular_linhas_unidade(
        df_filtrado, razoes_marcadas=("CNF", "ENE", "REL")
    )
    print(f"  resultado: {len(linhas_a):,} linhas")

    # Path B (BYPASS): tupla vazia → não aplica filter, equivale ao pré-G.6
    print("Path B (BYPASS): _calcular_linhas_unidade(df, ())")
    linhas_b = _calcular_linhas_unidade(df_filtrado, razoes_marcadas=())
    print(f"  resultado: {len(linhas_b):,} linhas")

    ok = True

    # 1. Cardinalidade
    if len(linhas_a) != len(linhas_b):
        print(f"  ✗ FAIL: len difere ({len(linhas_a)} vs {len(linhas_b)})")
        return False
    print(f"  ✓ len iguais: {len(linhas_a):,}")

    # 2. Identidade de unidade/proprietario por linha + 7 valores
    cols_pcts = (
        "mes_corrente", "mes_anterior", "penultimo",
        "tri_corrente", "tri_anterior_1", "tri_anterior_2", "tri_anterior_3",
        "ultimos_12m",  # G.7
    )
    n_diff_unidade = 0
    n_diff_prop = 0
    n_diff_pct = 0
    primeiros_diffs = []

    for ra, rb in zip(linhas_a, linhas_b):
        if ra["unidade"] != rb["unidade"]:
            n_diff_unidade += 1
            if len(primeiros_diffs) < 5:
                primeiros_diffs.append(
                    f"unidade: A={ra['unidade']!r} vs B={rb['unidade']!r}"
                )
            continue  # ordem divergiu, comparações por linha não fazem sentido
        if ra["proprietario"] != rb["proprietario"]:
            # Aceita None == NaN como igual (pandas/numpy)
            if not (
                pd.isna(ra["proprietario"]) and pd.isna(rb["proprietario"])
            ):
                n_diff_prop += 1
                if len(primeiros_diffs) < 5:
                    primeiros_diffs.append(
                        f"prop em {ra['unidade']!r}: "
                        f"A={ra['proprietario']!r} vs B={rb['proprietario']!r}"
                    )
        for k in cols_pcts:
            va, vb = ra[k], rb[k]
            if va is None and vb is None:
                continue
            if va is None or vb is None:
                n_diff_pct += 1
                if len(primeiros_diffs) < 5:
                    primeiros_diffs.append(
                        f"pct {k} em {ra['unidade']!r}: A={va} vs B={vb}"
                    )
                continue
            # Comparação bit-a-bit (mesmas operações em ambos paths →
            # mesmos floats; sem tolerância)
            if va != vb:
                n_diff_pct += 1
                if len(primeiros_diffs) < 5:
                    primeiros_diffs.append(
                        f"pct {k} em {ra['unidade']!r}: "
                        f"A={va!r} vs B={vb!r} (diff={abs(va-vb):.2e})"
                    )

    if n_diff_unidade > 0:
        print(f"  ✗ FAIL: ordem de unidades diferente ({n_diff_unidade} divergentes)")
        ok = False
    if n_diff_prop > 0:
        print(f"  ✗ FAIL: proprietário diferente em {n_diff_prop} linhas")
        ok = False
    if n_diff_pct > 0:
        print(f"  ✗ FAIL: % diferente em {n_diff_pct} células")
        ok = False
    if primeiros_diffs:
        print("  Primeiros diffs:")
        for d in primeiros_diffs:
            print(f"    - {d}")

    if ok:
        print(f"  ✓ Bit-a-bit: ordem, proprietário e 8 % por linha idênticos")

    return ok


def main() -> None:
    print("=" * 70)
    print("VALIDAÇÃO G.6: filtro de razão (todas marcadas) == sem filtro")
    print("=" * 70)

    # 1. Anchor
    print("\n[1/4] Descobrindo última data disponível no ONS...")
    try:
        max_d = descobrir_ultimo_dia_disponivel("eolica") or date.today()
    except Exception:
        max_d = date.today()
    janela_ampla_ini = max(
        date(2022, 1, 1), _inicio_trimestre_anterior(max_d, 4)
    )
    print(f"  janela_ampla = {janela_ampla_ini} → {max_d}")

    # 2. Carrega df_amplo + dependências
    print("\n[2/4] Carregando df_amplo + Categorical, df_grupos, aliases...")
    df_amplo = _aplicar_categorical(carregar_curtailment(
        data_inicio=janela_ampla_ini, data_fim=max_d,
        fontes=("eolica", "solar"),
    ))
    if len(df_amplo) == 0:
        print("✗ FAIL: df_amplo vazio.")
        sys.exit(1)
    df_grupos = carregar_grupos_excel()
    aliases = carregar_aliases()
    print(f"  df_amplo: {len(df_amplo):,} linhas")

    # 3. Aplica rateio por fonte
    print("\n[3/4] Aplicando rateio por fonte...")
    df_solar = aplicar_rateio(
        df_amplo[df_amplo["FONTE"] == "SOLAR"], df_grupos, aliases,
    )
    df_eolica = aplicar_rateio(
        df_amplo[df_amplo["FONTE"] == "EOLICA"], df_grupos, aliases,
    )
    print(f"  Solar:  {len(df_solar):,} linhas pós-rateio")
    print(f"  Eólica: {len(df_eolica):,} linhas pós-rateio")

    # 4. Comparar paths
    print("\n[4/4] Comparando Path A (NOVO) vs Path B (BYPASS)...")
    ok_solar = _comparar_paths(df_solar, "Solar")
    ok_eolica = _comparar_paths(df_eolica, "Eólica")

    # Resumo
    print(f"\n{'=' * 70}")
    print("RESUMO")
    print(f"{'=' * 70}")
    print(f"  Solar:  {'✓' if ok_solar else '✗'}")
    print(f"  Eólica: {'✓' if ok_eolica else '✗'}")
    print()
    if ok_solar and ok_eolica:
        print(
            "✓ OK: filtro G.6 com TODAS razões marcadas é "
            "matematicamente idêntico ao comportamento pré-G.6."
        )
        print("  Refator G.6 é seguro pra promover.")
        sys.exit(0)
    else:
        print("✗ FAIL: divergência detectada. NÃO promover refator.")
        sys.exit(2)


if __name__ == "__main__":
    main()
