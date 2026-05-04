"""
validar_cache_janela_ampla.py
=============================

Prova de não-regressão pro Caminho 1 (Variante A, janela 15M):
o wrapper _carregar_curtailment_janela_ampla carrega 15M consolidado
com Categorical e Visão Geral filtra slice em memória pros presets curtos.

Compara bit-a-bit, pra cada janela curta representativa × fonte:

    Path A (antigo): carregar_curtailment(janela_curta)
                     → filter por fonte → aplicar_rateio
    Path B (novo):   carregar_curtailment(janela_15M) → Categorical
                     → filter por fonte → aplicar_rateio (em 15M)
                     → filter DATA in [janela_curta_ini, janela_curta_fim]

Asserts:
    1. len(df_a) == len(df_b)
    2. sum(FRUSTRADO_MWH) idêntico (diff < 1e-6)
    3. sum(OUTPUT_MWH) idêntico (diff < 1e-6)
    4. df.equals bit-a-bit (após sort + reset_index, comparando
       Categorical pelo VALOR — não pelo dtype, já que Path B
       usa Categorical e Path A object).
    5. Cobertura especial: as 18 usinas em rateio múltiplo
       (Serra do Mel et al.) — groupby('USINA').size() idêntico.

Janelas testadas (ancoradas em max_d): 30D, 3M, 6M, 12M.
Fontes: Solar + Eólica.

Roda fora do Streamlit (warning de "no script run context" é esperado e
inofensivo — funções @st.cache_data viram no-op).

Uso:
    venv\\Scripts\\python.exe scripts/validar_cache_janela_ampla.py
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

import pandas as pd

from data_loaders.data_loader_curtailment import (
    carregar_curtailment, descobrir_ultimo_dia_disponivel,
)
from data_loaders.data_loader_grupos_excel import (
    carregar_grupos_excel, carregar_aliases, aplicar_rateio,
)


# ---------------------------------------------------------------------------
# Helpers locais (recriados pra evitar importar tab_curtailment, que carregaria
# Streamlit + dependências de UI).
# ---------------------------------------------------------------------------


def _inicio_trimestre(d: date) -> date:
    mes_inicio = ((d.month - 1) // 3) * 3 + 1
    return date(d.year, mes_inicio, 1)


def _inicio_mes_anterior(d: date, n: int) -> date:
    ano = d.year
    mes = d.month - n
    while mes <= 0:
        mes += 12
        ano -= 1
    return date(ano, mes, 1)


def _inicio_trimestre_anterior(d: date, n: int) -> date:
    inicio_q_atual = _inicio_trimestre(d)
    return _inicio_mes_anterior(inicio_q_atual, n * 3)


def _aplicar_categorical(df: pd.DataFrame) -> pd.DataFrame:
    """Replica o que _carregar_curtailment_janela_ampla faz no wrapper."""
    if len(df) == 0:
        return df
    df = df.copy()
    for col in ("USINA", "RAZAO", "FONTE", "SUBMERCADO", "UF"):
        if col in df.columns:
            df[col] = df[col].astype("category")
    return df


# ---------------------------------------------------------------------------
# Comparação por janela
# ---------------------------------------------------------------------------


def _executar_path_a(
    janela_ini: date, janela_fim: date,
    df_grupos, aliases, fonte_label: str,
) -> pd.DataFrame:
    """Path A (antigo): carrega janela curta → filter por fonte → rateio."""
    fonte_code = "SOLAR" if fonte_label == "Solar" else "EOLICA"
    df_curt_curto = carregar_curtailment(
        data_inicio=janela_ini, data_fim=janela_fim,
        fontes=("eolica", "solar"),
    )
    df_filtrado_fonte = df_curt_curto[df_curt_curto["FONTE"] == fonte_code]
    return aplicar_rateio(df_filtrado_fonte, df_grupos, aliases)


def _executar_path_b(
    df_amplo: pd.DataFrame,
    janela_ini: date, janela_fim: date,
    df_grupos, aliases, fonte_label: str,
) -> pd.DataFrame:
    """Path B (novo): df_amplo c/ Categorical → filter fonte → rateio → filter DATA."""
    fonte_code = "SOLAR" if fonte_label == "Solar" else "EOLICA"
    df_filtrado_fonte = df_amplo[df_amplo["FONTE"] == fonte_code]
    df_pos_rateio = aplicar_rateio(df_filtrado_fonte, df_grupos, aliases)
    return df_pos_rateio[
        (df_pos_rateio["DATA"] >= janela_ini)
        & (df_pos_rateio["DATA"] <= janela_fim)
    ]


def _normalizar_pra_comparacao(df: pd.DataFrame) -> pd.DataFrame:
    """Converte Categorical → object (.astype('object')) pra que .equals
    compare por VALOR, não por dtype. Sort + reset_index pra ordem
    determinística."""
    df = df.copy()
    for col in df.columns:
        if isinstance(df[col].dtype, pd.CategoricalDtype):
            df[col] = df[col].astype("object")
    sort_cols = [
        c for c in
        ["USINA", "DATA", "RAZAO", "NOME_USINA_DASH", "PROPRIETARIO"]
        if c in df.columns
    ]
    cols_ordenadas = sorted(df.columns)
    return df[cols_ordenadas].sort_values(sort_cols).reset_index(drop=True)


def _comparar_paths_para_janela(
    janela_label: str,
    janela_ini: date, janela_fim: date,
    df_amplo: pd.DataFrame,
    df_grupos, aliases,
    fonte_label: str,
) -> bool:
    fonte_code = "SOLAR" if fonte_label == "Solar" else "EOLICA"
    print(f"\n  -- {janela_label} | {fonte_label} ({fonte_code}) "
          f"[{janela_ini} → {janela_fim}] --")

    df_a = _executar_path_a(janela_ini, janela_fim, df_grupos, aliases, fonte_label)
    df_b = _executar_path_b(df_amplo, janela_ini, janela_fim,
                            df_grupos, aliases, fonte_label)

    print(f"     Path A: {len(df_a):,} linhas | Path B: {len(df_b):,} linhas")

    ok = True

    # 1. Cardinalidade
    if len(df_a) != len(df_b):
        print(f"     ✗ FAIL: len difere ({len(df_a)} vs {len(df_b)})")
        ok = False
    else:
        print(f"     ✓ len iguais: {len(df_a):,}")

    # 2. Soma FRUSTRADO_MWH
    sum_fr_a = float(df_a["FRUSTRADO_MWH"].sum())
    sum_fr_b = float(df_b["FRUSTRADO_MWH"].sum())
    diff_fr = abs(sum_fr_a - sum_fr_b)
    if diff_fr > 1e-6:
        print(
            f"     ✗ FAIL: sum FRUSTRADO_MWH difere "
            f"(A={sum_fr_a:.6f}, B={sum_fr_b:.6f}, diff={diff_fr:.2e})"
        )
        ok = False
    else:
        print(
            f"     ✓ sum FRUSTRADO_MWH idêntico: {sum_fr_a:,.4f} "
            f"(diff={diff_fr:.2e})"
        )

    # 3. Soma OUTPUT_MWH
    sum_ot_a = float(df_a["OUTPUT_MWH"].sum())
    sum_ot_b = float(df_b["OUTPUT_MWH"].sum())
    diff_ot = abs(sum_ot_a - sum_ot_b)
    if diff_ot > 1e-6:
        print(
            f"     ✗ FAIL: sum OUTPUT_MWH difere "
            f"(A={sum_ot_a:.6f}, B={sum_ot_b:.6f}, diff={diff_ot:.2e})"
        )
        ok = False
    else:
        print(
            f"     ✓ sum OUTPUT_MWH idêntico: {sum_ot_a:,.4f} "
            f"(diff={diff_ot:.2e})"
        )

    # 4. df.equals bit-a-bit (Categorical normalizado pra object)
    df_a_norm = _normalizar_pra_comparacao(df_a)
    df_b_norm = _normalizar_pra_comparacao(df_b)
    if df_a_norm.equals(df_b_norm):
        print(f"     ✓ df.equals bit-a-bit (após sort + Categorical→object)")
    else:
        print(f"     ✗ FAIL: df.equals divergiu")
        # Diagnóstico por coluna
        for col in df_a_norm.columns:
            try:
                if not df_a_norm[col].equals(df_b_norm[col]):
                    print(f"         coluna {col!r} difere")
                    if df_a_norm[col].dtype.kind in "fiu":
                        diff_max = (df_a_norm[col] - df_b_norm[col]).abs().max()
                        print(f"             diff max numérico: {diff_max:.2e}")
            except Exception as e:
                print(f"         erro comparando {col!r}: {e}")
        ok = False

    # 5. Cobertura especial: 18 usinas em rateio múltiplo
    if "USINA" in df_a.columns:
        cnt_a = df_a.groupby("USINA", observed=True).size().sort_index()
        cnt_b = df_b.groupby("USINA", observed=True).size().sort_index()
        if cnt_a.equals(cnt_b):
            print(
                f"     ✓ groupby('USINA').size() idêntico "
                f"({len(cnt_a)} usinas)"
            )
        else:
            usinas_diff = (cnt_a != cnt_b)
            n_diff = int(usinas_diff.sum())
            print(f"     ✗ FAIL: contagem por USINA difere em {n_diff} usinas")
            ok = False

    return ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print("=" * 70)
    print("VALIDAÇÃO CAMINHO 1: cache de janela ampla 15M com Categorical")
    print("=" * 70)

    # 1. Anchor em max_d real do ONS
    print("\n[1/4] Descobrindo última data disponível no ONS...")
    try:
        max_d = descobrir_ultimo_dia_disponivel("eolica") or date.today()
    except Exception:
        max_d = date.today()
    min_d_dataset = date(2022, 1, 1)
    print(f"  max_d = {max_d}")

    # 2. Janela ampla (mesma fórmula do wrapper em produção)
    janela_ampla_ini = max(
        min_d_dataset, _inicio_trimestre_anterior(max_d, 4)
    )
    print(f"  janela_ampla = {janela_ampla_ini} → {max_d} "
          f"(~{(max_d - janela_ampla_ini).days} dias)")

    # 3. Carregar df_amplo + dependências do rateio (1×)
    print("\n[2/4] Carregando df_amplo (15M) + Categorical, df_grupos, aliases...")
    df_amplo_raw = carregar_curtailment(
        data_inicio=janela_ampla_ini, data_fim=max_d,
        fontes=("eolica", "solar"),
    )
    if df_amplo_raw is None or len(df_amplo_raw) == 0:
        print("✗ FAIL: df_amplo vazio. Verifique conexão / cache.")
        sys.exit(1)
    df_amplo = _aplicar_categorical(df_amplo_raw)
    df_grupos = carregar_grupos_excel()
    aliases = carregar_aliases()
    print(
        f"  df_amplo: {len(df_amplo):,} linhas "
        f"({df_amplo.memory_usage(deep=True).sum() / 1024**2:.1f} MB) | "
        f"df_grupos: {len(df_grupos):,} | aliases: {len(aliases)}"
    )

    # 4. Janelas curtas a testar
    print("\n[3/4] Definindo janelas curtas a testar...")
    janelas_curtas = [
        ("30D",  max_d - timedelta(days=30),       max_d),
        ("3M",   _inicio_mes_anterior(max_d, 2),   max_d),
        ("6M",   _inicio_mes_anterior(max_d, 5),   max_d),
        ("12M",  _inicio_mes_anterior(max_d, 11),  max_d),
    ]
    for label, ini, fim in janelas_curtas:
        print(f"  {label}: {ini} → {fim}")

    # 5. Comparar Path A vs Path B em cada janela × fonte
    print("\n[4/4] Comparando Path A (antigo) vs Path B (novo)...")
    resultados = []
    for label, ini, fim in janelas_curtas:
        print(f"\n  ========== Janela {label} ==========")
        for fonte_label in ("Solar", "Eólica"):
            ok = _comparar_paths_para_janela(
                label, ini, fim, df_amplo, df_grupos, aliases, fonte_label,
            )
            resultados.append((label, fonte_label, ok))

    # Resumo
    print(f"\n{'=' * 70}")
    print("RESUMO")
    print(f"{'=' * 70}")
    n_ok = sum(1 for _, _, ok in resultados if ok)
    n_total = len(resultados)
    for label, fonte, ok in resultados:
        marker = "✓" if ok else "✗"
        print(f"  {marker}  {label:5s}  {fonte}")

    print()
    if n_ok == n_total:
        print(
            f"✓ OK: paths matematicamente idênticos pra Solar e Eólica em "
            f"todas as {n_total} janelas testadas."
        )
        print("  Caminho 1 (cache de janela ampla 15M) é seguro pra aplicar.")
        sys.exit(0)
    else:
        print(f"✗ FAIL: {n_total - n_ok}/{n_total} comparações divergiram.")
        print("  NÃO promover o refator pra produção.")
        sys.exit(2)


if __name__ == "__main__":
    main()
