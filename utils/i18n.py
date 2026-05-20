"""
utils/i18n.py — internacionalização PT/EN do dashboard.
=======================================================

Mecânica
--------
- O idioma corrente vive em ``st.session_state["idioma"]`` ("pt" | "en"),
  default "pt".
- ``t(texto_pt)`` devolve o texto no idioma atual:
    - idioma "pt" → devolve o próprio argumento;
    - idioma "en" → busca em ``TRADUCOES_EN``; se não achar, devolve o
      texto PT (fallback). O fallback é proposital: durante a migração
      incremental (feita por fases), strings ainda não traduzidas
      simplesmente aparecem em português — nada quebra.
- A CHAVE do dicionário é a própria string em português. Assim não é
  preciso inventar nomes de chave: basta envolver ``"texto"`` →
  ``t("texto")`` e adicionar a entrada PT→EN aqui.

Acrônimos do setor elétrico (PLD, ENA, MLT, GSF, CVU, SIN, MWmed, GWh…)
são mantidos como estão — NÃO entram no dicionário; o fallback devolve
o próprio acrônimo.

Fases de tradução
-----------------
- Fase 1 (esta): a "casca" — sidebar (menu, sub-views, toggle, rótulos).
- Fases seguintes: uma aba por vez (controles, captions, gráficos).
"""

from __future__ import annotations

import streamlit as st

IDIOMA_DEFAULT = "pt"
IDIOMAS = ("pt", "en")


# ---------------------------------------------------------------------------
# Dicionário de traduções PT → EN
# ---------------------------------------------------------------------------
# Organizado por seção pra facilitar manutenção. Acrescentar entradas
# conforme cada fase avança.
TRADUCOES_EN: dict[str, str] = {
    # --- Sidebar — identidade ---
    "Setor Elétrico · Brasil": "Power Sector · Brazil",

    # --- Sidebar — menu principal (abas) ---
    # "PLD", "Curtailment", "Admin" são mantidos (acrônimo / já em inglês).
    "Modulação": "Modulation",
    "Reservatórios": "Reservoirs",
    "ENA/Chuva": "ENA/Rainfall",
    "Despacho Térmico": "Thermal Dispatch",
    "Geração": "Generation",
    "Carga": "Load",
    "Capacidade": "Capacity",

    # --- Sidebar — sub-views ---
    # "Eneva", "SIN", "GSF" mantidos.
    "Eólica/Solar por Grupo": "Wind/Solar by Group",
    "Por Submercado/Fonte": "By Submarket/Source",
    "Receita por Empresa": "Revenue by Company",
    "Visão Geral": "Overview",
    "Crescimento": "Growth",

    # --- Sidebar — controles e rodapé ---
    "Idioma": "Language",
    "Navegação": "Navigation",
    "Atualizar": "Refresh",
    "Sair": "Sign out",
    "Dados atualizados automaticamente 1x ao dia.":
        "Data updated automatically once a day.",
}


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


def idioma_atual() -> str:
    """Retorna o idioma corrente ('pt' | 'en'). Default 'pt'."""
    return st.session_state.get("idioma", IDIOMA_DEFAULT)


def t(texto_pt: str) -> str:
    """Traduz ``texto_pt`` pro idioma corrente.

    Em "pt" devolve o próprio argumento. Em "en" busca em TRADUCOES_EN
    e, se não houver entrada, devolve o texto PT (fallback seguro pra
    migração incremental).
    """
    if idioma_atual() == "en":
        return TRADUCOES_EN.get(texto_pt, texto_pt)
    return texto_pt
