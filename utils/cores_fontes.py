"""
utils/cores_fontes.py
=====================

Paleta canônica de cores das **fontes de geração de energia** (dados em
gráficos). Resolve a decisão 5.33 do CLAUDE.md — fim da duplicação de
constantes ``COR_FONTE_*`` em 4+ arquivos (``app.py``,
``components/tab_curtailment.py``, ``components/tab_geracao_grupo.py``,
``components/tab_modulacao.py``, ``components/tab_capacidade.py``).

Distinção importante
--------------------
**Esta paleta é pra DADOS** (séries em gráficos de geração/capacidade).
NÃO confundir com a **paleta Bauhaus estrutural** (``BAUHAUS_BLACK``,
``BAUHAUS_CREAM``, ``BAUHAUS_LIGHT``, ``BAUHAUS_GRAY``, etc.) — essas
regem **UI** (bordas, eixos, texto, fundos) e continuam em
``app.py:75-78``.

Mapeamento canônico (5 fontes)
------------------------------
- ``COR_FONTE_HIDRO``   = ``#4A6FA5`` (azul-hidro)
- ``COR_FONTE_TERMICA`` = ``#A04B2E`` (terracota)
- ``COR_FONTE_NUCLEAR`` = ``#4A4A4A`` (cinza escuro = BAUHAUS_GRAY)
  → **categoria nova** introduzida pela aba Capacidade. Antes do refactor
  desta paleta, NUCLEAR não existia no canônico porque nenhuma aba
  isolava UTN visualmente (todas agregavam sob "Térmica"). A aba
  Capacidade plotará Angra 1+2 (~2 GW) como linha distinta no stack.
- ``COR_FONTE_EOLICA``  = ``#8FA31E`` (oliva)
- ``COR_FONTE_SOLAR``   = ``#F6BD16`` (amarelo Bauhaus)

Uso típico
----------
::

    from utils.cores_fontes import (
        COR_FONTE_HIDRO,
        COR_FONTE_TERMICA,
        COR_FONTE_NUCLEAR,
        COR_FONTE_EOLICA,
        COR_FONTE_SOLAR,
    )

    # OU via dict pra mapeamento dinâmico por chave do schema:
    from utils.cores_fontes import CORES_FONTE_DICT
    cor = CORES_FONTE_DICT["hidro"]  # → "#4A6FA5"

Arquivo puramente declarativo (zero imports do projeto) — ``utils/`` é
folha do grafo de imports, sem risco de ciclo.
"""

COR_FONTE_HIDRO   = "#4A6FA5"
COR_FONTE_TERMICA = "#A04B2E"
COR_FONTE_NUCLEAR = "#4A4A4A"
COR_FONTE_EOLICA  = "#8FA31E"
COR_FONTE_SOLAR   = "#F6BD16"

# Dict de conveniência pra mapeamento por chave do schema
# (ex: ``CORES_FONTE_DICT[df["fonte"]]`` em loops sobre DataFrames).
CORES_FONTE_DICT = {
    "hidro":   COR_FONTE_HIDRO,
    "termica": COR_FONTE_TERMICA,
    "nuclear": COR_FONTE_NUCLEAR,
    "eolica":  COR_FONTE_EOLICA,
    "solar":   COR_FONTE_SOLAR,
}
