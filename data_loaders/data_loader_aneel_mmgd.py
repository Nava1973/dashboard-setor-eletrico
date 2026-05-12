"""
data_loader_aneel_mmgd.py
=========================

Loader de capacidade instalada MMGD (Mini e Microgeração Distribuída).

ARQUITETURA: Anchor points anuais hardcoded (EPE PDGD release abr/2026).

Decisão arquitetural (registrada na SPEC v4 — próxima atualização):
1. Dataset ANEEL CKAN bruto (resource b1bd71e7-...) NÃO contém campo
   ``DataConexao`` após migração SISGD→MMGD de set/2025. Única coluna
   temporal (``DthAtualizaCadastralEmpreend``) é "data de última
   atualização cadastral", não "data de conexão" — inadequada como
   proxy temporal (viés desconhecido).

2. EPE PDGD e ONS POE — fontes oficiais — publicam apenas snapshots
   ANUAIS de capacidade MMGD, não série mensal.

3. Pra equity research macro, anchor points anuais oficiais EPE PDGD
   são mais defensáveis que série mensal reconstruída com viés
   desconhecido.

FONTE OFICIAL: EPE PDGD (Painel de Dados de Micro e Minigeração Distribuída)
  https://dashboard.epe.gov.br/apps/pdgd/

RELEASE DO PDGD: abril/2026 (publicação consolidada dos dados de 2025)

ÚLTIMA ATUALIZAÇÃO DESTE LOADER: 2026-05 (Nava)
PRÓXIMA REVISÃO ESPERADA: 2027-04 (quando EPE publicar PDGD com dados de 2026)
"""

import pandas as pd

# ========================================================================
# Anchor points oficiais EPE PDGD (valores em MW)
# ========================================================================
#
# IMPORTANTE: revisar anualmente quando EPE publicar update do PDGD (release
# tipicamente em abril, consolidando dados do ano anterior).
#
# Procedência dos valores:
# - dez/2022: ~20.000 MW (INFERIDO por subtração: 28000 - 8000 [expansão 2022])
# - dez/2023: ~28.000 MW (INFERIDO por subtração: 36200 - 8300 [expansão 2023])
# - dez/2024:  36.200 MW (CONFIRMADO via release oficial EPE abril/2026)
# - dez/2025:  45.000 MW (CONFIRMADO via release oficial EPE abril/2026)
# - abr/2026:  45.000 MW (CARRY-FORWARD do dez/2025; não há dado oficial
#   posterior ao último release EPE PDGD abril/2026. Decisão pós-screenshot:
#   preferir leitura honesta do último valor confirmado a extrapolação γ.
#   Substituir por valor PDGD em ~abr/2027.)
#
# Investigação B.5 empírica (mai/2026) tentou reconstruir série temporal
# via DthAtualizaCadastralEmpreend; endpoint datastore/dump trunca em 28%
# e datastore_search paginado timeout em ~46% (servidor instável).
# Decisão arquitetural: manter anchor manual EPE PDGD como fonte oficial,
# adicionar 1 anchor carry-forward pra ano corrente.
#
# Os valores INFERIDOS para 2022 e 2023 têm margem estimada de ±1 GW e
# devem ser substituídos por leituras diretas do PDGD na próxima sessão
# de manutenção (pendência registrada).
#
MMGD_ANCHORS = {
    "2022-12-01": 20000.0,   # INFERIDO
    "2023-12-01": 28000.0,   # INFERIDO
    "2024-12-01": 36200.0,   # CONFIRMADO (EPE PDGD abr/2026)
    "2025-12-01": 45000.0,   # CONFIRMADO (EPE PDGD abr/2026)
    "2026-04-01": 45000.0,   # CARRY-FORWARD (último oficial dez/2025; sem release PDGD posterior)
}


def load_mmgd_anual() -> pd.Series:
    """Retorna Series com anchor points anuais MMGD (snapshot dez/AAAA).

    Schema
    ------
    - Index: ``pd.DatetimeIndex``, name=``'ANO_MES'``
    - Values: ``float`` (MW)
    - Name: ``'CAP_MMGD_MW'``

    Cobertura inicial: dez/2022 a abr/2026 (5 pontos).

    Janela inicial em dez/2022 reflete Lei 14.300/2022 (marco legal
    pós-sanção jan/2022 — dez/2022 é o primeiro fim-de-ano sob novo regime).
    Último anchor (abr/2026) é carry-forward do último valor oficial
    confirmado (dez/2025) — ANEEL não publica série mensal oficial de MMGD.

    USO:
        >>> serie = load_mmgd_anual()
        >>> serie["2024-12-01"]  # → 36200.0
    """
    serie = pd.Series(MMGD_ANCHORS, name="CAP_MMGD_MW")
    serie.index = pd.to_datetime(serie.index)
    serie.index.name = "ANO_MES"
    return serie
