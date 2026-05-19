"""
profile_memory.py — mede RAM consumida por cada loader principal do app.

Util pra identificar os top culpados de OOM no Streamlit Cloud (limite
~1GB no free tier). Roda cada loader em sequencia, mede o delta de RSS
via psutil, e reporta uma tabela ordenada do maior pro menor.

Como rodar (da raiz do projeto):
  venv/Scripts/python.exe scripts/profile_memory.py

Saida: tabela com loader | linhas | shape | delta_MB | total_MB.

NAO modifica nada — read-only. Pode rodar a qualquer momento.
"""
from __future__ import annotations

import gc
import os
import sys
import time
import traceback
from datetime import date

import psutil

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _ram_mb() -> float:
    """RSS em MB do processo atual."""
    return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024


def _df_info(df) -> tuple[int, str]:
    """Retorna (n_linhas, shape_str). Aceita DataFrame ou Series."""
    if df is None:
        return 0, "None"
    try:
        if hasattr(df, "shape"):
            shape = "x".join(str(s) for s in df.shape)
            n = df.shape[0] if df.shape else 0
            return int(n), shape
    except Exception:
        pass
    return 0, "?"


# Cada entrada: (label, callable, args_dict). Ordenado por categoria.
# Lambdas pra import lazy — evita importar tudo no boot se um loader quebrar.

LOADERS = [
    # PLD
    ("load_pld_media_diaria",
     lambda: __import__("data_loader", fromlist=["load_pld_media_diaria"]).load_pld_media_diaria(),
     {}),
    ("load_pld_media_semanal",
     lambda: __import__("data_loader", fromlist=["load_pld_media_semanal"]).load_pld_media_semanal(),
     {}),
    ("load_pld_media_mensal",
     lambda: __import__("data_loader", fromlist=["load_pld_media_mensal"]).load_pld_media_mensal(),
     {}),
    ("load_pld_horaria (recente 2a)",
     lambda: __import__("data_loader", fromlist=["load_pld_horaria"]).load_pld_horaria(False),
     {}),
    ("load_pld_horaria (COMPLETO 6a)",
     lambda: __import__("data_loader", fromlist=["load_pld_horaria"]).load_pld_horaria(True),
     {}),
    # ONS — balancos pesados
    ("load_balanco_subsistema (15a)",
     lambda: __import__("data_loader", fromlist=["load_balanco_subsistema"]).load_balanco_subsistema(False),
     {}),
    ("load_balanco_subsistema (COMPLETO 27a)",
     lambda: __import__("data_loader", fromlist=["load_balanco_subsistema"]).load_balanco_subsistema(True),
     {}),
    # ONS — outros
    ("load_reservatorios",
     lambda: __import__("data_loader", fromlist=["load_reservatorios"]).load_reservatorios(),
     {}),
    ("load_ena",
     lambda: __import__("data_loader", fromlist=["load_ena"]).load_ena(),
     {}),
    ("load_gd_ons",
     lambda: __import__("data_loader", fromlist=["load_gd_ons"]).load_gd_ons(),
     {}),
    # GSF
    ("load_gsf_mensal",
     lambda: __import__("data_loaders.ccee_gsf", fromlist=["load_gsf_mensal"]).load_gsf_mensal(),
     {}),
    # MMGD / SIGA
    ("load_mmgd_mensal (SQL)",
     lambda: __import__("data_loaders.data_loader_aneel_mmgd_sql", fromlist=["load_mmgd_mensal"]).load_mmgd_mensal(),
     {}),
    ("load_siga",
     lambda: __import__("data_loaders.data_loader_aneel_siga", fromlist=["load_siga"]).load_siga(),
     {}),
    # Curtailment + Termico (pesados)
    ("carregar_curtailment (default)",
     lambda: __import__("data_loaders.data_loader_curtailment", fromlist=["carregar_curtailment"]).carregar_curtailment(),
     {}),
    ("carregar_termico (default)",
     lambda: __import__("data_loaders.data_loader_termico", fromlist=["carregar_termico"]).carregar_termico(),
     {}),
]


def main() -> int:
    print("=" * 90)
    print("  PROFILE MEMORY — RAM consumida por loader (RSS via psutil)")
    print("=" * 90)
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  RAM inicial: {_ram_mb():,.1f} MB")
    print()

    resultados = []
    ram_anterior = _ram_mb()

    for label, fn, _ in LOADERS:
        gc.collect()
        ram_pre = _ram_mb()
        t_inicio = time.time()
        n_linhas, shape = 0, "?"
        erro = None
        try:
            df = fn()
            n_linhas, shape = _df_info(df)
            # Mantem df vivo (forca permanecer na RAM ate proxima iteracao)
        except Exception as e:
            erro = f"{type(e).__name__}: {e}"
            traceback.print_exc()

        dt = time.time() - t_inicio
        ram_pos = _ram_mb()
        delta = ram_pos - ram_pre

        resultados.append({
            "loader": label,
            "n_linhas": n_linhas,
            "shape": shape,
            "delta_MB": delta,
            "ram_pos_MB": ram_pos,
            "tempo_s": dt,
            "erro": erro,
        })

        marker = "[ERRO]" if erro else "[OK]"
        print(f"  {marker} {label:<45} delta={delta:>+7.1f}MB  "
              f"shape={shape:<15}  t={dt:>5.1f}s  total={ram_pos:.0f}MB")
        if erro:
            print(f"           -> {erro[:80]}")

    print()
    print("=" * 90)
    print("  TOP 5 LOADERS POR CONSUMO (ordenado por delta_MB):")
    print("=" * 90)
    top5 = sorted(
        [r for r in resultados if r["erro"] is None],
        key=lambda r: r["delta_MB"], reverse=True,
    )[:5]
    print(f"  {'rank':<5}{'loader':<45}{'delta_MB':>12}{'shape':>20}")
    print(f"  {'-'*5}{'-'*45}{'-'*12}{'-'*20}")
    for i, r in enumerate(top5, 1):
        print(f"  {i:<5}{r['loader']:<45}{r['delta_MB']:>+10.1f}MB"
              f"{r['shape']:>20}")

    ram_final = _ram_mb()
    print()
    print(f"  RAM final: {ram_final:,.1f} MB  (cresceu "
          f"{ram_final - ram_anterior:+.1f}MB no total)")
    print()

    # Tabela completa em CSV (ranking + investigacao posterior)
    import csv
    out = "scripts/_profile_memory_result.csv"
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(resultados[0].keys()))
        w.writeheader()
        w.writerows(resultados)
    print(f"  Resultados completos em: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
