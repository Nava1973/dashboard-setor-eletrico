"""
auth.py
Autenticação simples baseada em streamlit-authenticator.

Em desenvolvimento (local): lê credenciais de config.yaml.
Em produção (Streamlit Cloud): lê de st.secrets["auth_config"]["yaml_content"].
"""

from pathlib import Path
import yaml
import streamlit as st
import streamlit_authenticator as stauth
from yaml.loader import SafeLoader

CONFIG_PATH = Path(__file__).parent / "config.yaml"

# Paleta — importada pro CSS de login (fica consistente com app.py)
_RED = "#D62828"
_YELLOW = "#F6BD16"
_BLUE = "#3D5AFE"
_BLACK = "#1A1A1A"
_CREAM = "#F5F1E8"


def _load_config() -> dict:
    """
    Prioridade:
    1. st.secrets["auth_config"]["yaml_content"] (produção)
    2. config.yaml local (desenvolvimento)
    """
    try:
        if "auth_config" in st.secrets:
            yaml_text = st.secrets["auth_config"]["yaml_content"]
            return yaml.load(yaml_text, Loader=SafeLoader)
    except Exception:
        pass

    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.load(f, Loader=SafeLoader)

    raise RuntimeError(
        "Configuração de autenticação não encontrada. "
        "Em desenvolvimento, crie config.yaml. "
        "Em produção, defina st.secrets['auth_config']['yaml_content']."
    )


def _inject_login_css():
    """CSS Bauhaus específico da tela de login."""
    st.markdown(
        f"""
        <style>
        /* Form de login — estilização Bauhaus coesa */
        [data-testid="stForm"] {{
            background: {_CREAM} !important;
            border: 3px solid {_BLACK} !important;
            border-radius: 0 !important;
            padding: 2rem !important;
            max-width: 480px;
            margin: 0 auto;
        }}

        /* Inputs (username, password) */
        [data-testid="stForm"] input {{
            border-radius: 0 !important;
            border: 2px solid {_BLACK} !important;
            background: #FFFFFF !important;
            color: {_BLACK} !important;
            font-family: 'Inter', sans-serif !important;
            padding: 10px 12px !important;
        }}

        /* Labels dos inputs */
        [data-testid="stForm"] label,
        [data-testid="stForm"] label *,
        [data-testid="stForm"] label p {{
            color: {_BLACK} !important;
            font-family: 'Inter', sans-serif !important;
            font-weight: 600 !important;
            font-size: 0.85rem !important;
            text-transform: uppercase !important;
            letter-spacing: 0.08em !important;
        }}

        /* Botão de login */
        [data-testid="stForm"] button[kind="primary"],
        [data-testid="stForm"] button {{
            background: {_YELLOW} !important;
            color: {_BLACK} !important;
            border: 2px solid {_BLACK} !important;
            border-radius: 0 !important;
            font-family: 'Bebas Neue', sans-serif !important;
            letter-spacing: 0.1em !important;
            font-size: 1.1rem !important;
            padding: 10px 20px !important;
            width: auto !important;
        }}
        [data-testid="stForm"] button:hover {{
            background: {_RED} !important;
            color: {_CREAM} !important;
        }}

        /* Alerta de instrução — substituir st.info azul por caixa Bauhaus */
        .login-info {{
            background: {_YELLOW} !important;
            border: 2px solid {_BLACK};
            color: {_BLACK};
            font-family: 'Inter', sans-serif;
            font-weight: 600;
            font-size: 0.95rem;
            padding: 12px 16px;
            max-width: 480px;
            margin: 0 auto 1rem auto;
            text-align: center;
        }}

        /* Alerta de erro — caixa vermelha Bauhaus */
        .login-error {{
            background: {_RED} !important;
            border: 2px solid {_BLACK};
            color: {_CREAM};
            font-family: 'Inter', sans-serif;
            font-weight: 600;
            font-size: 0.95rem;
            padding: 12px 16px;
            max-width: 480px;
            margin: 0 auto 1rem auto;
            text-align: center;
        }}

        /* Esconder os st.info e st.error padrão na tela de login */
        [data-testid="stAlert"] {{
            display: none !important;
        }}

        /* Título da tela de login */
        .login-title {{
            font-family: 'Bebas Neue', sans-serif;
            font-size: 3rem;
            letter-spacing: 0.02em;
            color: {_BLACK};
            text-align: center;
            border-left: 10px solid {_RED};
            padding-left: 16px;
            max-width: 480px;
            margin: 2rem auto 1.5rem auto;
        }}

        .login-subtitle {{
            text-align: center;
            max-width: 480px;
            margin: 0 auto 1.5rem auto;
            color: #4A4A4A;
            font-family: 'Inter', sans-serif;
            font-size: 0.95rem;
            text-transform: uppercase;
            letter-spacing: 0.1em;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def require_login() -> str | None:
    """
    Exibe tela de login. Retorna o username se autenticado, None caso contrário.
    """
    config = _load_config()

    authenticator = stauth.Authenticate(
        config["credentials"],
        config["cookie"]["name"],
        config["cookie"]["key"],
        config["cookie"]["expiry_days"],
    )

    auth_status = st.session_state.get("authentication_status")

    # Se não está logado, injetar CSS e título da tela de login
    if auth_status is not True:
        _inject_login_css()
        st.markdown(
            '<div class="login-title">Dashboard Setor Elétrico</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="login-subtitle">Acesso restrito a usuários autorizados</div>',
            unsafe_allow_html=True,
        )

    # Renderizar o form nativo do streamlit-authenticator (com CSS customizado aplicado)
    try:
        authenticator.login(location="main", key="login_form")
    except Exception as e:
        st.error(f"Erro no login: {e}")
        return None

    auth_status = st.session_state.get("authentication_status")
    name = st.session_state.get("name")
    username = st.session_state.get("username")

    if auth_status is False:
        st.markdown(
            '<div class="login-error">Usuário ou senha incorretos.</div>',
            unsafe_allow_html=True,
        )
        return None
    if auth_status is None:
        st.markdown(
            '<div class="login-info">Entre com suas credenciais para acessar</div>',
            unsafe_allow_html=True,
        )
        return None

    # Autenticado — botão de logout na sidebar
    with st.sidebar:
        authenticator.logout("Sair", "sidebar")

    return name or username

