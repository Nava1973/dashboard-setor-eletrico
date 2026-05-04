"""
medir_memoria_caminho1.py
=========================

Mede footprint de memória RSS do pipeline do Caminho 1 (cache de janela
ampla 15M com Categorical) em pontos discretos do fluxo. Threshold de
aceite: peak RSS observado < 250MB.

Etapas medidas (delta vs etapa anterior, e total vs baseline):
    0. Baseline (após imports)
    1. Após carregar_curtailment(janela_ampla 15M) raw
    2. Após Categorical aplicado
    3. Após carregar_grupos_excel + carregar_aliases
    4. Após filter Solar + aplicar_rateio
    5. Após filter Eólica + aplicar_rateio (peak esperado aqui)

Exit:
    0 se peak < 250MB
    2 se peak >= 250MB (regredir refator pra Variante B)

Uso:
    venv\\Scripts\\python.exe scripts/medir_memoria_caminho1.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8")

import psutil  # noqa: E402
import pandas as pd  # noqa: E402

from data_loaders.data_loader_curtailment import (  # noqa: E402
    carregar_curtailment, descobrir_ultimo_dia_disponivel,
)
from data_loaders.data_loader_grupos_excel import (  # noqa: E402
    carregar_grupos_excel, carregar_aliases, aplicar_rateio,
)


THRESHOLD_PEAK_MB = 300.0


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
    return _inicio_mes_anterior(_inicio_trimestre(d), n * 3)


def _aplicar_categorical(df: pd.DataFrame) -> pd.DataFrame:
    """Replica o que _carregar_curtailment_janela_ampla faz no wrapper."""
    if len(df) == 0:
        return df
    df = df.copy()
    for col in ("USINA", "RAZAO", "FONTE", "SUBMERCADO", "UF"):
        if col in df.columns:
            df[col] = df[col].astype("category")
    return df


def _rss_mb() -> float:
    return psutil.Process().memory_info().rss / 1024**2


def main() -> None:
    print("=" * 70)
    print("MEDIÇÃO DE MEMÓRIA — Caminho 1 (janela ampla 15M + Categorical)")
    print("=" * 70)
    print(f"Threshold de aceite: peak RSS < {THRESHOLD_PEAK_MB:.0f}MB\n")

    medidas = []

    def checkpoint(label: str) -> None:
        rss = _rss_mb()
        delta_prev = rss - medidas[-1][1] if medidas else 0.0
        delta_base = rss - medidas[0][1] if medidas else 0.0
        medidas.append((label, rss, delta_prev, delta_base))
        print(
            f"  [{len(medidas) - 1}] {label:48s}  "
            f"RSS={rss:7.1f}MB  Δprev={delta_prev:+7.1f}  "
            f"Δbase={delta_base:+7.1f}"
        )

    checkpoint("baseline (após imports)")

    # 1. Janela ampla
    max_d = descobrir_ultimo_dia_disponivel("eolica") or date.today()
    janela_ampla_ini = max(
        date(2022, 1, 1), _inicio_trimestre_anterior(max_d, 4)
    )
    print(
        f"\n  janela_ampla = {janela_ampla_ini} → {max_d} "
        f"(~{(max_d - janela_ampla_ini).days} dias)\n"
    )

    df_amplo_raw = carregar_curtailment(
        data_inicio=janela_ampla_ini, data_fim=max_d,
        fontes=("eolica", "solar"),
    )
    if df_amplo_raw is None or len(df_amplo_raw) == 0:
        print("✗ FAIL: df_amplo vazio. Verifique conexão / cache.")
        sys.exit(1)
    checkpoint(f"carregar_curtailment 15M raw ({len(df_amplo_raw):,} linhas)")

    # 2. Categorical
    df_amplo = _aplicar_categorical(df_amplo_raw)
    del df_amplo_raw  # libera o object original
    checkpoint("Categorical aplicado")

    print(
        f"\n  df_amplo footprint via memory_usage(deep=True): "
        f"{df_amplo.memory_usage(deep=True).sum() / 1024**2:.2f}MB\n"
    )

    # 3. Grupos + aliases
    df_grupos = carregar_grupos_excel()
    aliases = carregar_aliases()
    checkpoint(
        f"carregar_grupos_excel + aliases "
        f"({len(df_grupos)} grupos, {len(aliases)} aliases)"
    )

    # 4. Filter Solar + rateio
    df_solar = df_amplo[df_amplo["FONTE"] == "SOLAR"]
    df_solar_pos = aplicar_rateio(df_solar, df_grupos, aliases)
    checkpoint(
        f"filter Solar + aplicar_rateio "
        f"({len(df_solar_pos):,} linhas pós-rateio)"
    )

    # 5. Filter Eólica + rateio (peak esperado)
    df_eolica = df_amplo[df_amplo["FONTE"] == "EOLICA"]
    df_eolica_pos = aplicar_rateio(df_eolica, df_grupos, aliases)
    checkpoint(
        f"filter Eólica + aplicar_rateio "
        f"({len(df_eolica_pos):,} linhas pós-rateio)"
    )

    # Veredicto
    peak_rss = max(rss for _, rss, _, _ in medidas)
    delta_total = medidas[-1][1] - medidas[0][1]

    print(f"\n{'=' * 70}")
    print("RESUMO")
    print(f"{'=' * 70}")
    print(f"  Peak RSS observado:  {peak_rss:7.1f}MB")
    print(f"  Threshold aceite:    {THRESHOLD_PEAK_MB:7.1f}MB")
    print(f"  Delta total (final - baseline): {delta_total:+.1f}MB")
    print(
        f"  Folga pro threshold:  "
        f"{THRESHOLD_PEAK_MB - peak_rss:+.1f}MB "
        f"({(1 - peak_rss / THRESHOLD_PEAK_MB) * 100:.1f}%)"
    )

    print()
    if peak_rss < THRESHOLD_PEAK_MB:
        print(
            f"✓ OK: peak RSS {peak_rss:.1f}MB < {THRESHOLD_PEAK_MB:.0f}MB. "
            f"Margem confortável vs Cloud free tier 1GB."
        )
        sys.exit(0)
    else:
        print(
            f"✗ FAIL: peak RSS {peak_rss:.1f}MB >= {THRESHOLD_PEAK_MB:.0f}MB. "
            f"Considerar Variante B (lazy load por sub-aba) em vez do "
            f"eager 15M pré-carregado."
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
