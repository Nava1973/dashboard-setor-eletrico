"""
auth.py
Autenticação simples baseada em streamlit-authenticator.

Em desenvolvimento (local): lê credenciais de config.yaml.
Em produção (Streamlit Cloud): lê de st.secrets["auth_config"]["yaml_content"].
"""

import base64
from pathlib import Path
import yaml
import streamlit as st
import streamlit_authenticator as stauth
from yaml.loader import SafeLoader

CONFIG_PATH = Path(__file__).parent / "config.yaml"

# Paleta — importada pro CSS de login (fica consistente com app.py)
from utils.paleta_bradesco import (
    COR_FUNDO,
    COR_TEXTO,
    COR_TEXTO_SECUND,
    COR_DESTAQUE,
    COR_ACCENT,
)

# Compat aliases — migração 2026-05-15 (Bauhaus → Bradesco).
# TODO: rename to COR_* nos consumidores e remover estes aliases.
_RED    = COR_DESTAQUE   # era #D62828 (vermelho Bauhaus) → #CC092F (Bradesco)
_YELLOW = COR_DESTAQUE   # era #F6BD16 (amarelo Bauhaus); todos os 3 usos eram destaque → vira vermelho
_BLUE   = COR_ACCENT     # era #2A6F97 (azul petróleo Bauhaus) → #0078B7 (azul Bradesco)
_BLACK  = COR_TEXTO      # era #1A1A1A → #313131
_CREAM  = COR_FUNDO      # era #F5F1E8 (creme) → #FFFFFF (branco)

# Logo BBI vermelho horizontal — lido 1x no nível do módulo
_LOGO_RED_PATH = Path(__file__).parent / "assets" / "logos" / "bbi_horizontal_red.png"
try:
    _LOGO_RED_B64 = base64.b64encode(_LOGO_RED_PATH.read_bytes()).decode()
except Exception:
    _LOGO_RED_B64 = ""


def _load_config() -> dict:
    """
    Carrega config de autenticação (formato streamlit-authenticator).

    Prioridade (decisão 5.93 — backend Google Sheets):
      1. Google Sheets (aba "Clientes" via gspread) — fonte de verdade
         única pra ~100 clientes externos + 3 admins. Atualizações via
         painel Admin no app, sem precisar mexer em config/secrets.
      2. st.secrets["auth_config"]["yaml_content"] (fallback produção
         antiga — preserva login no Cloud durante migração caso o
         gspread falhe por qualquer motivo).
      3. config.yaml local (fallback desenvolvimento sem internet ou
         sem credencial gspread configurada).

    Cookie config sempre vem do YAML (Sheets só guarda credenciais de
    usuários, não config de cookie/preauth). Quando a 1ª prioridade
    bate, fundimos credentials da Sheet com cookie/preauth do YAML.
    """
    # 1) Carrega ambas as fontes
    sheet_creds = _carregar_credenciais_da_sheet()  # dict ou None
    yaml_cfg = _carregar_yaml_config()              # dict completo ou None

    if yaml_cfg is None and sheet_creds is None:
        raise RuntimeError(
            "Configuração de autenticação não encontrada. "
            "Configure st.secrets['gcp_service_account'] + planilha Clientes, "
            "OU st.secrets['auth_config']['yaml_content'], "
            "OU config.yaml local."
        )

    # 2) Merge: YAML é a base (preserva admins, cookie, pre-authorized);
    # credenciais da Sheet ADICIONAM/SOBRESCREVEM por chave (email).
    #
    # Decisão (§5.93 fix mid-sessão): durante a transição admins-no-YAML
    # → admins-na-Sheet (Fase E), AMBAS as fontes precisam coexistir pra
    # ninguém ficar fora do login. Substituição pura quebrava admins
    # ainda não migrados pra Sheet.
    #
    # Após Fase E (admins na Sheet), o YAML pode ser deprecado, mas
    # mantemos o merge defensivamente — Sheet sempre ganha em conflito
    # (mais "fresca" / sob admin control via painel).
    base_usernames = {}
    base_cookie = {"name": "auth_session", "key": "fallback", "expiry_days": 1}
    base_preauth = {"emails": []}

    if yaml_cfg is not None:
        base_usernames = dict(
            yaml_cfg.get("credentials", {}).get("usernames", {})
        )
        base_cookie = yaml_cfg.get("cookie", base_cookie)
        base_preauth = yaml_cfg.get(
            "pre-authorized",
            yaml_cfg.get("preauthorized", base_preauth),
        )

    if sheet_creds is not None:
        # Sheet ganha em chaves coincidentes (admin que migrou pra Sheet
        # vai usar a Sheet em vez do YAML).
        base_usernames.update(sheet_creds)

    return {
        "credentials": {"usernames": base_usernames},
        "cookie": base_cookie,
        "pre-authorized": base_preauth,
    }


def _carregar_credenciais_da_sheet() -> dict | None:
    """Lê linhas da aba Clientes e retorna dict no formato
    streamlit-authenticator. None se gspread/sheet indisponível.

    Schema de retorno:
        {email: {name, email, password, failed_login_attempts,
                 logged_in, roles}}

    Onde:
      - 'password' é o hash bcrypt da coluna senha_hash.
      - 'name' é montado como "{nome} {sobrenome}".
      - 'roles' default ["user"]; admin é controlado pelo `ADMIN_USERS`
        set hardcoded em components/tab_*.py (não vive na planilha).
    """
    try:
        from utils.google_sheets import listar_clientes
    except ImportError:
        return None

    try:
        df = listar_clientes()
    except Exception:
        # Sem credencial, sem internet, ou planilha inacessível —
        # cai pro fallback silenciosamente.
        return None

    if df is None or df.empty:
        return None

    usernames = {}
    for _, row in df.iterrows():
        email = str(row.get("email", "")).strip()
        senha_hash = str(row.get("senha_hash", "")).strip()
        if not email or not senha_hash:
            continue  # linha incompleta, pula
        nome = str(row.get("nome", "")).strip()
        sobrenome = str(row.get("sobrenome", "")).strip()
        nome_display = f"{nome} {sobrenome}".strip() or email
        usernames[email] = {
            "email": email,
            "name": nome_display,
            "password": senha_hash,
            "failed_login_attempts": 0,
            "logged_in": False,
            "roles": ["user"],
        }
    return usernames if usernames else None


def _carregar_yaml_config() -> dict | None:
    """Lê config YAML de st.secrets["auth_config"]["yaml_content"] ou
    config.yaml local. None se nada disponível."""
    try:
        if "auth_config" in st.secrets:
            yaml_text = st.secrets["auth_config"]["yaml_content"]
            return yaml.load(yaml_text, Loader=SafeLoader)
    except Exception:
        pass

    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.load(f, Loader=SafeLoader)

    return None


def _inject_login_css():
    """CSS Bauhaus específico da tela de login."""
    st.markdown(
        f"""
        <style>
        /* Form de login — estilização Bauhaus coesa.
           Bloco centralizado horizontalmente na tela. Largura escolhida
           pra casar visualmente com a largura natural do título+barra. */
        [data-testid="stForm"] {{
            background: {_CREAM} !important;
            border: 3px solid {_BLACK} !important;
            border-radius: 0 !important;
            padding: 2rem !important;
            max-width: 600px;
            margin: 0 auto;
        }}

        /* Inputs (username, password) — garantir largura completa e sem espaço branco */
        [data-testid="stForm"] input {{
            border-radius: 0 !important;
            border: 2px solid {_BLACK} !important;
            background: #FFFFFF !important;
            color: {_BLACK} !important;
            font-family: 'Inter', sans-serif !important;
            padding: 10px 12px !important;
            width: 100% !important;
            box-sizing: border-box !important;
        }}

        /* Campo de senha — container flex com botão de olho colado no final.
           Remove QUALQUER espaço em branco à direita. */
        [data-testid="stForm"] [data-testid="stTextInputRootElement"],
        [data-testid="stForm"] div[data-baseweb="input"] {{
            background: #FFFFFF !important;
            border: 2px solid {_BLACK} !important;
            border-radius: 0 !important;
            display: flex !important;
            align-items: stretch !important;
            width: 100% !important;
            padding: 0 !important;
            overflow: hidden !important;
        }}
        [data-testid="stForm"] div[data-baseweb="input"] > div {{
            flex: 1 !important;
            display: flex !important;
        }}
        [data-testid="stForm"] div[data-baseweb="input"] input {{
            border: none !important;
            flex: 1 !important;
            width: 100% !important;
        }}
        /* Botão de olho — vermelho Bradesco com glifo branco, colado no final. */
        [data-testid="stForm"] button[aria-label*="Show password"],
        [data-testid="stForm"] button[aria-label*="Hide password"],
        [data-testid="stForm"] button[kind="iconButton"] {{
            background: {_RED} !important;
            border: none !important;
            border-left: 2px solid {_BLACK} !important;
            color: {_CREAM} !important;
            padding: 0 12px !important;
            margin: 0 !important;
            border-radius: 0 !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            min-width: 44px !important;
            height: auto !important;
            align-self: stretch !important;
        }}
        [data-testid="stForm"] button[aria-label*="Show password"]:hover,
        [data-testid="stForm"] button[aria-label*="Hide password"]:hover {{
            background: {_BLACK} !important;
            color: {_CREAM} !important;
        }}
        /* Garante que o glifo SVG pegue a cor herdada (branco / branco no hover).
           `fill="none"` (paths em outline) preservado pra não pintar áreas vazias. */
        [data-testid="stForm"] button[aria-label*="Show password"] svg path:not([fill="none"]),
        [data-testid="stForm"] button[aria-label*="Hide password"] svg path:not([fill="none"]),
        [data-testid="stForm"] button[kind="iconButton"] svg path:not([fill="none"]),
        [data-testid="stForm"] button[aria-label*="Show password"] svg,
        [data-testid="stForm"] button[aria-label*="Hide password"] svg,
        [data-testid="stForm"] button[kind="iconButton"] svg {{
            fill: currentColor !important;
            color: {_CREAM} !important;
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

        /* Botão de login — vermelho Bradesco com texto branco. */
        [data-testid="stForm"] button[kind="primary"],
        [data-testid="stForm"] button {{
            background: {_RED} !important;
            color: {_CREAM} !important;
            border: 2px solid {_BLACK} !important;
            border-radius: 0 !important;
            font-family: 'Bebas Neue', sans-serif !important;
            letter-spacing: 0.1em !important;
            font-size: 1.1rem !important;
            padding: 10px 20px !important;
            width: auto !important;
        }}
        /* Força texto branco em qualquer filho do botão (p, span, div) — vence
           a herança padrão do Streamlit que repinta o label do botão. */
        [data-testid="stForm"] button[kind="primary"] *,
        [data-testid="stForm"] button * {{
            color: {_CREAM} !important;
        }}
        [data-testid="stForm"] button:hover {{
            background: {_BLACK} !important;
            color: {_CREAM} !important;
        }}
        [data-testid="stForm"] button:hover * {{
            color: {_CREAM} !important;
        }}

        /* Alerta de instrução — caixa neutra (cinza claro + borda preta).
           Bauhaus usava amarelo aqui; pós-migração Bradesco passa pra
           cinza neutro pra não competir com .login-error (vermelho). */
        .login-info {{
            background: #F5F5F5 !important;
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

        /* Logo BBI horizontal vermelho — topo da tela de login.
           Centralizado horizontalmente na tela. */
        .login-logo {{
            display: block;
            width: 380px;
            max-width: 60%;
            height: auto;
            margin: 2.5rem auto 1.5rem auto;
        }}

        /* Título da tela de login.
           !important nas props abaixo é necessário pra vencer a regra
           global `h1 { ... }` injetada pelo app.py (border-left vermelho
           padrão Bauhaus 7px, padding-left 12px, font-size 2rem). Aqui
           preservamos a barra vermelha mas com 10px (mais robusta pra
           tela de login) e padding 16px — assinatura Bauhaus do projeto.
           `width: fit-content` faz o bloco ocupar só a largura do texto+
           barra+padding; combinado com `margin: 0 auto`, centraliza o
           bloco inteiro horizontalmente na tela mantendo barra à esquerda. */
        .login-title {{
            font-family: 'Bebas Neue', sans-serif !important;
            font-size: 2.5rem !important;
            letter-spacing: 0.02em !important;
            color: {_BLACK} !important;
            text-align: left !important;
            border-left: 10px solid {_RED} !important;
            padding-left: 16px !important;
            padding-right: 0 !important;
            width: fit-content !important;
            max-width: 90% !important;
            margin: 0 auto 0.6rem auto !important;
            line-height: 1.1 !important;
        }}
        /* Em desktop com folga, garante 1 linha; em telas estreitas
           deixa quebrar naturalmente pra evitar scroll horizontal. */
        @media (min-width: 700px) {{
            .login-title {{
                white-space: nowrap !important;
            }}
        }}

        /* Autores — abaixo do título, antes do form.
           Centralizados horizontalmente na tela. */
        .login-authors {{
            font-family: 'Inter', sans-serif;
            font-size: 1.15rem;
            color: {_BLACK};
            text-align: center;
            letter-spacing: 0.06em;
            max-width: 600px;
            margin: 0 auto 2rem auto;
        }}

        .login-subtitle {{
            text-align: center;
            max-width: 600px;
            margin: 0 auto 1.5rem auto;
            color: {COR_TEXTO_SECUND};
            font-family: 'Inter', sans-serif;
            font-size: 0.95rem;
            text-transform: uppercase;
            letter-spacing: 0.1em;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _get_authenticator():
    """Cria o Authenticate UMA VEZ por sessão e reutiliza nos reruns.

    Recriar a cada rerun churna o `extra_streamlit_components.CookieManager`
    por baixo (`CookieModel.__init__` instancia um novo a cada vez), o que é
    fonte conhecida de instabilidade do cookie de re-autenticação.
    """
    auth = st.session_state.get("_authenticator")
    if auth is not None:
        return auth
    config = _load_config()
    auth = stauth.Authenticate(
        config["credentials"],
        config["cookie"]["name"],
        config["cookie"]["key"],
        config["cookie"]["expiry_days"],
    )
    st.session_state["_authenticator"] = auth
    return auth


def require_login() -> str | None:
    """
    Exibe tela de login. Retorna o username se autenticado, None caso contrário.
    """
    authenticator = _get_authenticator()

    # Captura o status ANTES de chamar login() — pra detectar a transição
    # "acabou de logar" e disparar um rerun (vide nota mais abaixo).
    auth_status_before = st.session_state.get("authentication_status")

    # Se não está logado, injetar CSS e cabeçalho (logo + título + autores)
    if auth_status_before is not True:
        _inject_login_css()
        if _LOGO_RED_B64:
            st.markdown(
                f'<img src="data:image/png;base64,{_LOGO_RED_B64}" '
                f'class="login-logo" alt="Bradesco BBI" />',
                unsafe_allow_html=True,
            )
        st.markdown(
            '<h1 class="login-title">Dashboard Setor Elétrico — Brasil</h1>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="login-authors">Navarrete | Fagundes | Caruso</div>',
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

    # Transição "acabou de logar agora": força um st.rerun() pra dar um ciclo
    # limpo de render ao CookieManager flushar o cookie no navegador antes
    # do app prosseguir. A streamlit-authenticator 0.4.2 só faz esse rerun
    # interno quando `Authenticate(...)` recebe um caminho de config (path),
    # o que não é o caso aqui (passamos o dict de credenciais). Sem este
    # rerun, o cookie pode não ser persistido de forma confiável → na
    # próxima reconexão/refresh o usuário "desloga".
    if auth_status is True and auth_status_before is not True:
        # Registra acesso no log antes do rerun (Fase D §5.93). Best-effort:
        # se gspread falhar, login continua OK — log é instrumentação, não
        # gating. Idempotente por (email, hoje) — múltiplos logins/dia
        # contam 1 só (decisão do usuário).
        try:
            from utils.google_sheets import registrar_acesso
            registrar_acesso(username)
        except Exception:
            pass
        st.rerun()

    if auth_status is False:
        st.markdown(
            '<div class="login-error">Usuário ou senha incorretos.</div>',
            unsafe_allow_html=True,
        )
        return None
    if auth_status is None:
        # Sem mensagem extra — o form nativo já é autoexplicativo
        return None

    # Autenticado — logout fica na barra superior (gerenciado pelo app.py)
    return name or username


def logout_button(
    location: str = "main",
    key: str = "logout_main",
    label: str = "Sair",
) -> None:
    """
    Renderiza o botão de logout. Pode ser chamado de qualquer lugar do app.
    location: "main" (topo do app) ou "sidebar"
    label: texto do botão (o caller passa t("Sair") pra i18n PT/EN).
    """
    auth = st.session_state.get("_authenticator")
    if auth is None:
        return
    try:
        auth.logout(label, location, key=key)
    except TypeError:
        # Versões antigas não aceitam 'key'
        auth.logout(label, location)
