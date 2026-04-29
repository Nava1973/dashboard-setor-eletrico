"""
utils_periodos.py
=================

Módulo de agrupamento temporal para o dashboard.

Suporta as granularidades:
    - DIARIO     : por dia
    - SEMANAL    : segunda a domingo (ISO 8601)
    - MENSAL     : por mês calendário (YYYY-MM)
    - TRIMESTRAL : 1T/2T/3T/4T calendário (Q-DEC, padrão fiscal BR)
    - ROLLING_12M: janela móvel de 365 dias terminando em cada ponto

Regras de período parcial:
    O período corrente (que ainda não fechou) é detectado e marcado
    com flag `parcial=True`. Útil para visualizações que precisam
    sinalizar que o último ponto não é diretamente comparável.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Tuple, Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Tipos
# ---------------------------------------------------------------------------

GRANULARIDADES = ("DIARIO", "SEMANAL", "MENSAL", "TRIMESTRAL", "ROLLING_12M")


@dataclass
class Periodo:
    """Representação canônica de um período."""
    chave: str          # chave de agrupamento (ex.: '2026-Q1', '2026-04', '2026-W17')
    label: str          # label de exibição (ex.: '1T26', 'Abr/26', 'Sem 17/26')
    inicio: date        # primeiro dia do período (inclusive)
    fim: date           # último dia do período (inclusive)
    parcial: bool       # True se o período ainda não fechou


# ---------------------------------------------------------------------------
# Funções de fronteira de período
# ---------------------------------------------------------------------------


def _semana_iso_bounds(d: date) -> Tuple[date, date]:
    """Retorna (segunda, domingo) da semana ISO contendo d."""
    inicio = d - timedelta(days=d.weekday())  # segunda
    fim = inicio + timedelta(days=6)          # domingo
    return inicio, fim


def _mes_bounds(ano: int, mes: int) -> Tuple[date, date]:
    inicio = date(ano, mes, 1)
    if mes == 12:
        fim = date(ano, 12, 31)
    else:
        fim = date(ano, mes + 1, 1) - timedelta(days=1)
    return inicio, fim


def _trimestre_bounds(ano: int, trimestre: int) -> Tuple[date, date]:
    """Trimestre calendário: 1T=jan-mar, 2T=abr-jun, 3T=jul-set, 4T=out-dez."""
    mes_ini = (trimestre - 1) * 3 + 1
    mes_fim = mes_ini + 2
    return _mes_bounds(ano, mes_ini)[0], _mes_bounds(ano, mes_fim)[1]


# ---------------------------------------------------------------------------
# Adicionar coluna de chave de período no DataFrame
# ---------------------------------------------------------------------------


def adicionar_chave_periodo(
    df: pd.DataFrame,
    granularidade: str,
    col_data: str = "DATA",
) -> pd.DataFrame:
    """
    Adiciona ao DataFrame as colunas:
        PERIODO_CHAVE  - string de agrupamento
        PERIODO_LABEL  - string de exibição
        PERIODO_INICIO - date de início
        PERIODO_FIM    - date de fim
    """
    if granularidade not in GRANULARIDADES:
        raise ValueError(
            f"Granularidade '{granularidade}' inválida. Use: {GRANULARIDADES}"
        )

    df = df.copy()
    s = pd.to_datetime(df[col_data])

    if granularidade == "DIARIO":
        df["PERIODO_CHAVE"] = s.dt.strftime("%Y-%m-%d")
        df["PERIODO_LABEL"] = s.dt.strftime("%d/%m/%Y")
        df["PERIODO_INICIO"] = s.dt.date
        df["PERIODO_FIM"] = s.dt.date

    elif granularidade == "SEMANAL":
        # ISO: segunda como início da semana
        ano_iso = s.dt.isocalendar().year
        sem_iso = s.dt.isocalendar().week
        df["PERIODO_CHAVE"] = (
            ano_iso.astype(str) + "-W" + sem_iso.astype(str).str.zfill(2)
        )
        df["PERIODO_LABEL"] = (
            "Sem " + sem_iso.astype(str).str.zfill(2)
            + "/" + ano_iso.astype(str).str[-2:]
        )
        # Fronteiras: segunda e domingo
        seg = s - pd.to_timedelta(s.dt.weekday, unit="D")
        df["PERIODO_INICIO"] = seg.dt.date
        df["PERIODO_FIM"] = (seg + pd.Timedelta(days=6)).dt.date

    elif granularidade == "MENSAL":
        df["PERIODO_CHAVE"] = s.dt.strftime("%Y-%m")
        meses_pt = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
                    "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
        df["PERIODO_LABEL"] = (
            s.dt.month.apply(lambda m: meses_pt[m - 1])
            + "/" + s.dt.year.astype(str).str[-2:]
        )
        df["PERIODO_INICIO"] = s.dt.to_period("M").dt.start_time.dt.date
        df["PERIODO_FIM"] = s.dt.to_period("M").dt.end_time.dt.date

    elif granularidade == "TRIMESTRAL":
        # Q-DEC = trimestre calendário (jan-mar, abr-jun, ...)
        per = s.dt.to_period("Q-DEC")
        df["PERIODO_CHAVE"] = per.astype(str)  # ex.: '2026Q1'
        df["PERIODO_LABEL"] = (
            per.dt.quarter.astype(str) + "T"
            + per.dt.year.astype(str).str[-2:]
        )
        df["PERIODO_INICIO"] = per.dt.start_time.dt.date
        df["PERIODO_FIM"] = per.dt.end_time.dt.date

    elif granularidade == "ROLLING_12M":
        # Para rolling 12m, o "período" para cada linha é o dia + (dia - 365)
        df["PERIODO_CHAVE"] = s.dt.strftime("%Y-%m-%d")
        df["PERIODO_LABEL"] = s.dt.strftime("%d/%m/%Y") + " (12m)"
        df["PERIODO_FIM"] = s.dt.date
        df["PERIODO_INICIO"] = (s - pd.Timedelta(days=364)).dt.date

    return df


# ---------------------------------------------------------------------------
# Listar períodos contidos em um intervalo (para definir colunas de tabela)
# ---------------------------------------------------------------------------


def listar_periodos(
    data_inicio: date,
    data_fim: date,
    granularidade: str,
    ultimo_dia_disponivel: Optional[date] = None,
    limite: Optional[int] = None,
) -> list[Periodo]:
    """
    Lista os períodos que cobrem o intervalo [data_inicio, data_fim].

    ultimo_dia_disponivel: se informado, marca como `parcial=True` os períodos
                           cujo fim é posterior a este dia.
    limite: se informado, retorna apenas os N períodos mais recentes.
    """
    if ultimo_dia_disponivel is None:
        ultimo_dia_disponivel = date.today()

    periodos: list[Periodo] = []

    if granularidade == "DIARIO":
        d = data_inicio
        while d <= data_fim:
            periodos.append(Periodo(
                chave=d.strftime("%Y-%m-%d"),
                label=d.strftime("%d/%m/%Y"),
                inicio=d,
                fim=d,
                parcial=(d > ultimo_dia_disponivel),
            ))
            d += timedelta(days=1)

    elif granularidade == "SEMANAL":
        ini, _ = _semana_iso_bounds(data_inicio)
        d = ini
        while d <= data_fim:
            seg, dom = _semana_iso_bounds(d)
            iso = d.isocalendar()
            periodos.append(Periodo(
                chave=f"{iso[0]}-W{iso[1]:02d}",
                label=f"Sem {iso[1]:02d}/{str(iso[0])[-2:]}",
                inicio=seg,
                fim=dom,
                parcial=(dom > ultimo_dia_disponivel),
            ))
            d += timedelta(days=7)

    elif granularidade == "MENSAL":
        ano, mes = data_inicio.year, data_inicio.month
        meses_pt = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
                    "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
        while date(ano, mes, 1) <= data_fim:
            ini, fim = _mes_bounds(ano, mes)
            periodos.append(Periodo(
                chave=f"{ano}-{mes:02d}",
                label=f"{meses_pt[mes - 1]}/{str(ano)[-2:]}",
                inicio=ini,
                fim=fim,
                parcial=(fim > ultimo_dia_disponivel),
            ))
            mes += 1
            if mes > 12:
                mes = 1
                ano += 1

    elif granularidade == "TRIMESTRAL":
        ano = data_inicio.year
        trim = (data_inicio.month - 1) // 3 + 1
        while True:
            ini, fim = _trimestre_bounds(ano, trim)
            if ini > data_fim:
                break
            periodos.append(Periodo(
                chave=f"{ano}Q{trim}",
                label=f"{trim}T{str(ano)[-2:]}",
                inicio=ini,
                fim=fim,
                parcial=(fim > ultimo_dia_disponivel),
            ))
            trim += 1
            if trim > 4:
                trim = 1
                ano += 1

    elif granularidade == "ROLLING_12M":
        # Para rolling 12m, "período" = data_fim do intervalo
        periodos.append(Periodo(
            chave=data_fim.strftime("%Y-%m-%d"),
            label=f"{data_fim.strftime('%d/%m/%Y')} (12m)",
            inicio=data_fim - timedelta(days=364),
            fim=data_fim,
            parcial=(data_fim > ultimo_dia_disponivel),
        ))

    if limite is not None and limite > 0:
        return periodos[-limite:]
    return periodos


# ---------------------------------------------------------------------------
# Helpers para a aba de curtailment
# ---------------------------------------------------------------------------


def calcular_periodo_corrente(granularidade: str, hoje: Optional[date] = None) -> Periodo:
    """Retorna o período corrente conforme a granularidade."""
    if hoje is None:
        hoje = date.today()

    if granularidade == "DIARIO":
        return Periodo(
            chave=hoje.strftime("%Y-%m-%d"),
            label=hoje.strftime("%d/%m/%Y"),
            inicio=hoje, fim=hoje, parcial=False,
        )
    if granularidade == "SEMANAL":
        seg, dom = _semana_iso_bounds(hoje)
        iso = hoje.isocalendar()
        return Periodo(
            chave=f"{iso[0]}-W{iso[1]:02d}",
            label=f"Sem {iso[1]:02d}/{str(iso[0])[-2:]}",
            inicio=seg, fim=dom, parcial=(dom > hoje),
        )
    if granularidade == "MENSAL":
        ini, fim = _mes_bounds(hoje.year, hoje.month)
        meses_pt = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
                    "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
        return Periodo(
            chave=f"{hoje.year}-{hoje.month:02d}",
            label=f"{meses_pt[hoje.month - 1]}/{str(hoje.year)[-2:]}",
            inicio=ini, fim=fim, parcial=(fim > hoje),
        )
    if granularidade == "TRIMESTRAL":
        trim = (hoje.month - 1) // 3 + 1
        ini, fim = _trimestre_bounds(hoje.year, trim)
        return Periodo(
            chave=f"{hoje.year}Q{trim}",
            label=f"{trim}T{str(hoje.year)[-2:]}",
            inicio=ini, fim=fim, parcial=(fim > hoje),
        )
    # ROLLING_12M
    return Periodo(
        chave=hoje.strftime("%Y-%m-%d"),
        label=f"{hoje.strftime('%d/%m/%Y')} (12m)",
        inicio=hoje - timedelta(days=364),
        fim=hoje, parcial=False,
    )
