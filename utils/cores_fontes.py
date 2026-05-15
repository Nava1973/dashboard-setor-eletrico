"""
utils/cores_fontes.py
=====================

**Fachada** — re-exporta as cores de fontes de geração de
``utils.paleta_bradesco`` desde 2026-05-15 (migração Bauhaus →
Bradesco). Mantido para compat de imports legados:

    from utils.cores_fontes import COR_FONTE_HIDRO  # continua funcionando

Histórico original (preservado pra contexto)
--------------------------------------------
Paleta canônica de cores das **fontes de geração de energia** (dados em
gráficos). Resolveu a decisão 5.33 do CLAUDE.md — fim da duplicação de
constantes ``COR_FONTE_*`` em 4+ arquivos (``app.py``,
``components/tab_curtailment.py``, ``components/tab_geracao_grupo.py``,
``components/tab_modulacao.py``, ``components/tab_capacidade.py``).

Pós-migração Bradesco, o canônico das fontes vive em
``utils.paleta_bradesco`` (junto com o resto da paleta). Este módulo
fica como **fachada** que re-exporta as mesmas constantes — assim os
imports históricos (``from utils.cores_fontes import COR_FONTE_*``)
continuam funcionando sem mudança nos callers.

Quem é novo: importe direto de ``utils.paleta_bradesco``.

Distinção entre paleta de **dados** e paleta **estrutural**
-----------------------------------------------------------
**Esta paleta é pra DADOS** (séries em gráficos de geração/capacidade).
NÃO confundir com a **paleta estrutural** (``COR_FUNDO``, ``COR_TEXTO``,
``COR_BORDA``, ``COR_SIDEBAR_*``) — essa rege **UI** (bordas, eixos,
texto, fundos) e vive em ``utils.paleta_bradesco`` seções 1-2.
"""

from utils.paleta_bradesco import (
    COR_FONTE_HIDRO,
    COR_FONTE_TERMICA,
    COR_FONTE_NUCLEAR,
    COR_FONTE_EOLICA,
    COR_FONTE_SOLAR,
    COR_FONTE_MMGD,
    CORES_FONTE_DICT,
)

__all__ = [
    "COR_FONTE_HIDRO",
    "COR_FONTE_TERMICA",
    "COR_FONTE_NUCLEAR",
    "COR_FONTE_EOLICA",
    "COR_FONTE_SOLAR",
    "COR_FONTE_MMGD",
    "CORES_FONTE_DICT",
]
