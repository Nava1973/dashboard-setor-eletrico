"""
utils/admin.py
==============

Verificação centralizada de quem é admin do dashboard.

Histórico: até §5.91, `ADMIN_USERS = {"Nava", "Fagundes", "Caruso"}` era
verificado contra o `name` (display name) retornado pelo `auth.py`.
Funcionava porque o YAML cadastrava admins com `name` capitalizado.

A partir do backend Google Sheets (§5.93), admins serão cadastrados
junto com clientes externos, com `name = "{nome} {sobrenome}"`
(ex: "Francisco Navarrete"). A checagem antiga quebraria.

**Decisão:** checar primariamente por **email** (chave estável que não
muda com cadastro). `ADMIN_USERS` legacy continua suportado como
fallback durante migração.
"""
from __future__ import annotations

import streamlit as st


# Fonte de verdade pra quem é admin. Editar aqui pra adicionar/remover.
# Mantém alinhamento com auth do projeto (emails BBI dos 3 sócios do dash).
ADMIN_EMAILS: set[str] = {
    "francisco.navarrete@bradescobbi.com.br",
    "joao.fagundes@bradescobbi.com.br",
    "matheus.caruso@bradescobbi.com.br",
}

# Compat legacy — `name` capitalizado, conferido contra o retorno do
# `require_login()` quando email não está disponível por algum motivo
# (raríssimo, mas defensivo).
ADMIN_USERS: set[str] = {"Nava", "Fagundes", "Caruso"}


def eh_admin(user_display: str | None = None) -> bool:
    """Retorna True se o usuário atual é admin do dashboard.

    Args:
        user_display: o `name` (display) retornado pelo `require_login()`.
            Aceito como fallback se o email não estiver acessível.

    Lógica:
      1. Tenta `st.session_state["username"]` (que streamlit-authenticator
         seta com o username == email no nosso schema). Compara contra
         ADMIN_EMAILS case-insensitive.
      2. Fallback: compara `user_display` contra ADMIN_USERS legacy.
    """
    # Checagem primária via email (chave estável)
    try:
        email = st.session_state.get("username")
    except Exception:
        email = None

    if email:
        email_lower = str(email).strip().lower()
        if email_lower in {e.lower() for e in ADMIN_EMAILS}:
            return True

    # Fallback legacy via name
    if user_display and user_display in ADMIN_USERS:
        return True

    return False
