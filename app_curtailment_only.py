"""
App MÍNIMO pra debug de OOM no Cloud — só renderiza aba Curtailment.

Criado na sessão emergencial 2026-04-30 pra isolar se OOM no Cloud
é causado pela aba Curtailment isoladamente OU pela carga combinada
de todas as abas + import de data_loader.py monolítico (1818 linhas
com 16+ decoradores @st.cache_data).

Diferenças vs app.py:
- SEM import de data_loader (monolito não é importado)
- SEM CSS global de 440+ linhas (linhas 92-533 do app.py)
- SEM constantes BAUHAUS_*/COR_FONTE_* (Curtailment usa internas)
- SEM components.html script de ícones
- SEM sidebar com radio de abas
- SEM dispatch das outras 5 abas (PLD, Reservatórios, ENA, Geração, Carga)
- SEM logout_button

Mantido:
- st.set_page_config (page_title diferente pra distinguir)
- require_login (mesmo auth do app principal)
- render_aba_curtailment (componente em components/tab_curtailment.py)

Quando termina o teste:
- Se app sobe e Curtailment funciona → OOM era carga combinada,
  precisamos otimizar imports / lazy loading no app principal
- Se app crasha igual ao principal → bug específico no Curtailment,
  investigamos com mais profundidade

Esse arquivo é DESCARTÁVEL após o diagnóstico. Removê-lo da próxima
sessão de limpeza junto com funções órfãs do mapa choropleth.
"""
from __future__ import annotations

import streamlit as st

from auth import require_login
from components.tab_curtailment import render_aba_curtailment


st.set_page_config(
    page_title="Curtailment Debug",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Login obrigatório (mesmo auth do app principal)
user = require_login()
if user is None:
    st.stop()

# Aviso visual pra distinguir do app principal
st.warning(
    "⚠️ APP DEBUG — só renderiza aba Curtailment isoladamente. "
    "Para uso normal, acesse o app principal."
)

# Renderiza Curtailment direto, sem outras abas
render_aba_curtailment()
