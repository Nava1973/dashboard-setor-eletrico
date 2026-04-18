"""
auth.py
Autenticação simples baseada em streamlit-authenticator.

Em desenvolvimento (local): lê credenciais de config.yaml.
Em produção (Streamlit Cloud): lê de st.secrets["auth_config"]["yaml_content"].

Para adicionar/remover usuários localmente, edite config.yaml.
Para produção, edite Settings > Secrets no painel do Streamlit Cloud.
"""

from pathlib import Path
import yaml
import streamlit as st
import streamlit_authenticator as stauth
from yaml.loader import SafeLoader

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def _load_config() -> dict:
    """
    Prioridade:
    1. st.secrets["auth_config"]["yaml_content"] (produção)
    2. config.yaml local (desenvolvimento)
    """
    # Produção: Streamlit Cloud
    try:
        if "auth_config" in st.secrets:
            yaml_text = st.secrets["auth_config"]["yaml_content"]
            return yaml.load(yaml_text, Loader=SafeLoader)
    except Exception:
        pass

    # Desenvolvimento: arquivo local
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.load(f, Loader=SafeLoader)

    raise RuntimeError(
        "Configuração de autenticação não encontrada. "
        "Em desenvolvimento, crie config.yaml. "
        "Em produção, defina st.secrets['auth_config']['yaml_content']."
    )


def require_login() -> str | None:
    """
    Exibe tela de login. Retorna o username se autenticado, None caso contrário.
    Chame st.stop() no caller se retornar None.
    """
    config = _load_config()

    authenticator = stauth.Authenticate(
        config["credentials"],
        config["cookie"]["name"],
        config["cookie"]["key"],
        config["cookie"]["expiry_days"],
    )

    try:
        authenticator.login(location="main", key="login_form")
    except Exception as e:
        st.error(f"Erro no login: {e}")
        return None

    auth_status = st.session_state.get("authentication_status")
    name = st.session_state.get("name")
    username = st.session_state.get("username")

    if auth_status is False:
        st.error("Usuário ou senha incorretos.")
        return None
    if auth_status is None:
        st.info("Entre com suas credenciais para acessar o dashboard.")
        return None

    # Autenticado — botão de logout na sidebar
    with st.sidebar:
        authenticator.logout("Sair", "sidebar")

    return name or username

