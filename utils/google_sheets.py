"""
utils/google_sheets.py
======================

Helpers de leitura/escrita na planilha "Dashboard Setor Elétrico —
Clientes" via gspread + Service Account.

Planilha tem 2 abas:
  - Clientes: codigo | nome | sobrenome | empresa | email |
              senha_hash | data_cadastro
  - Log_Acesso: email | data | hora_primeiro_acesso (1 linha por
                email-dia, idempotente)

Credencial via st.secrets["gcp_service_account"] (dict do JSON da
Service Account). Localmente: arquivo .streamlit/secrets.toml; no
Cloud: cola via UI de Secrets.

Cache:
  - _get_client() via @st.cache_resource (1 conexão compartilhada).
  - listar_clientes() / listar_log_acesso() via @st.cache_data TTL
    5min (balance entre rate-limit Google e frescor de dados).
  - Operações de escrita invalidam o cache (.clear()) antes de retornar.

Rate limits da Google Sheets API pra Service Account: 60 leituras/min
+ 300 escritas/min por projeto. Com 100 users ativos:
  - Login: ~100 leituras + 100 escritas / dia. Trivial.
  - Painel admin: dezenas de chamadas / dia. Trivial.
Sem necessidade de rate limiter manual.

Decisão 5.93 (sessão 19/05/2026 — backend cadastro de clientes).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import pandas as pd
import streamlit as st


# ============================================================================
# Configuração
# ============================================================================

# ID da planilha Google Sheets (parte entre /d/ e /edit na URL).
# Fixo por design — uma única planilha pro app inteiro. Se mudar de
# planilha (ex: migração pra conta corporativa BBI), atualizar aqui +
# st.secrets["gcp_service_account"] (nova Service Account compartilhada
# com a planilha nova).
PLANILHA_ID = "13lWJhqWePlZ35edIjm4DIt4axS5W_zo3cX4266G98Y4"

ABA_CLIENTES = "Clientes"
ABA_LOG = "Log_Acesso"

# Scope mínimo necessário (apenas Sheets — não Drive). Restringir reduz
# superfície de risco caso a chave vaze.
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Schema das abas (ordem das colunas) — usado pra validar headers e
# pra append_row na ordem correta.
COLUNAS_CLIENTES = [
    "codigo", "nome", "sobrenome", "empresa",
    "email", "senha_hash", "data_cadastro",
]
COLUNAS_LOG = [
    "codigo", "nome", "sobrenome", "empresa",
    "email", "data", "hora_acesso",
]

# Coluna 1-indexed do "email" e "senha_hash" na aba Clientes (pra
# atualizações cell-level via update_cell).
_COL_EMAIL_IDX = COLUNAS_CLIENTES.index("email") + 1       # 5
_COL_SENHA_HASH_IDX = COLUNAS_CLIENTES.index("senha_hash") + 1  # 6


# ============================================================================
# Conexão
# ============================================================================

@st.cache_resource(show_spinner=False)
def _get_client():
    """Autentica via Service Account e retorna gspread.Client.

    Lê a credencial de st.secrets["gcp_service_account"] (dict). Cached
    como resource pra reutilizar a 1 conexão entre sessions concorrentes
    (pattern §5.92 — 100 users compartilham 1 client).
    """
    import gspread
    from google.oauth2.service_account import Credentials

    if "gcp_service_account" not in st.secrets:
        raise RuntimeError(
            "Credencial gspread ausente. Adicione "
            "[gcp_service_account] em .streamlit/secrets.toml (local) ou "
            "em st.secrets do Cloud."
        )

    # st.secrets retorna AttrDict; convertendo pra dict puro pra
    # Credentials.from_service_account_info aceitar.
    cred_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(cred_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def _get_aba(nome_aba: str):
    """Retorna gspread Worksheet pelo nome da aba."""
    client = _get_client()
    return client.open_by_key(PLANILHA_ID).worksheet(nome_aba)


# ============================================================================
# Clientes — leitura
# ============================================================================

@st.cache_data(ttl=300, show_spinner=False)
def listar_clientes() -> pd.DataFrame:
    """Retorna DataFrame com todos os clientes cadastrados.

    DataFrame vazio com colunas COLUNAS_CLIENTES se planilha vazia.
    Cache TTL 5min — admin que cadastrar via outro cliente vê em até 5min.
    Operações de escrita aqui chamam .clear() pra invalidar imediato.
    """
    ws = _get_aba(ABA_CLIENTES)
    records = ws.get_all_records()  # lista de dicts (1 por linha)
    df = pd.DataFrame(records)
    if df.empty:
        df = pd.DataFrame(columns=COLUNAS_CLIENTES)
    # Garante colunas na ordem canonica
    cols_existentes = [c for c in COLUNAS_CLIENTES if c in df.columns]
    df = df[cols_existentes]
    # codigo lido como int pelo gspread se for numerico — força str
    if "codigo" in df.columns:
        df["codigo"] = df["codigo"].astype(str)
    return df


def buscar_cliente_por_email(email: str) -> Optional[dict]:
    """Retorna dict com dados do cliente, ou None se não cadastrado.

    Busca case-insensitive (emails comparados em lowercase).
    """
    if not email:
        return None
    df = listar_clientes()
    if df.empty:
        return None
    email_lower = email.strip().lower()
    match = df[df["email"].str.strip().str.lower() == email_lower]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


# ============================================================================
# Clientes — escrita
# ============================================================================

def adicionar_cliente(
    *,
    codigo: str,
    nome: str,
    sobrenome: str,
    empresa: str,
    email: str,
    senha_hash: str,
) -> None:
    """Adiciona linha nova na aba Clientes.

    Args:
        codigo: código interno do cliente (string — pode ser numérico
            mas guardamos como str pra preservar zeros à esquerda).
        nome, sobrenome, empresa: dados pessoais.
        email: usado como username de login. Deve ser único.
        senha_hash: hash bcrypt da senha em texto plano. JAMAIS passar
            senha plana aqui — caller responsável pelo bcrypt.

    `data_cadastro` é gerada automaticamente (hoje, formato ISO YYYY-MM-DD).
    Invalida cache de leitura ao final.
    """
    ws = _get_aba(ABA_CLIENTES)
    nova_linha = [
        str(codigo), nome, sobrenome, empresa, email,
        senha_hash, date.today().isoformat(),
    ]
    ws.append_row(nova_linha, value_input_option="USER_ENTERED")
    listar_clientes.clear()


def atualizar_cliente(
    email: str,
    *,
    codigo: str | None = None,
    nome: str | None = None,
    sobrenome: str | None = None,
    empresa: str | None = None,
) -> bool:
    """Atualiza dados do cliente (mas NÃO email nem senha_hash).

    Args:
        email: chave de busca (case-insensitive).
        codigo, nome, sobrenome, empresa: novos valores. None = não altera
            (mantém valor atual).

    Email é a chave de identificação, não muda — pra trocar email,
    apagar + cadastrar de novo. Senha continua só via `atualizar_senha_hash`.

    Retorna True se atualizou, False se cliente não encontrado.
    """
    if not email:
        return False

    ws = _get_aba(ABA_CLIENTES)
    # Acha a linha do cliente pelo email
    emails_col = ws.col_values(_COL_EMAIL_IDX)
    email_lower = email.strip().lower()
    linha_idx = None
    for i, e in enumerate(emails_col, start=1):
        if e.strip().lower() == email_lower:
            linha_idx = i
            break
    if linha_idx is None:
        return False

    # Mapping coluna 1-indexed pra valor novo. Só atualiza colunas
    # que receberam valor (None = preserva atual).
    updates = []
    valores = {
        "codigo": codigo,
        "nome": nome,
        "sobrenome": sobrenome,
        "empresa": empresa,
    }
    for nome_col, valor_novo in valores.items():
        if valor_novo is None:
            continue
        col_idx_1based = COLUNAS_CLIENTES.index(nome_col) + 1
        updates.append((col_idx_1based, str(valor_novo)))

    if not updates:
        return False  # nada pra atualizar

    # Batch update em vez de N chamadas — economiza rate limit do Sheets
    for col_idx, valor in updates:
        ws.update_cell(linha_idx, col_idx, valor)

    listar_clientes.clear()
    return True


def deletar_cliente(email: str) -> bool:
    """Remove a linha do cliente da aba Clientes.

    Args:
        email: chave de busca (case-insensitive).

    Returns:
        True se deletou, False se cliente não encontrado.

    Atenção: ação destrutiva. UI deve sempre confirmar com o admin
    antes de chamar. O log de acesso histórico do cliente NÃO é
    afetado (audit trail preservado — schema denormalizado §5.93
    guarda snapshot dos dados no momento de cada acesso).
    """
    if not email:
        return False
    ws = _get_aba(ABA_CLIENTES)
    emails_col = ws.col_values(_COL_EMAIL_IDX)
    email_lower = email.strip().lower()
    linha_idx = None
    for i, e in enumerate(emails_col, start=1):
        if e.strip().lower() == email_lower:
            linha_idx = i
            break
    if linha_idx is None:
        return False
    ws.delete_rows(linha_idx)
    listar_clientes.clear()
    return True


def atualizar_senha_hash(email: str, novo_hash: str) -> bool:
    """Atualiza só a coluna senha_hash do cliente com email dado.

    Retorna True se atualizou, False se cliente não foi encontrado.
    Comparação de email case-insensitive (consistente com busca).
    """
    if not email or not novo_hash:
        return False
    ws = _get_aba(ABA_CLIENTES)
    # Lê coluna inteira de emails pra achar a linha
    emails_col = ws.col_values(_COL_EMAIL_IDX)
    email_lower = email.strip().lower()
    linha_idx = None
    for i, e in enumerate(emails_col, start=1):
        if e.strip().lower() == email_lower:
            linha_idx = i
            break
    if linha_idx is None:
        return False
    ws.update_cell(linha_idx, _COL_SENHA_HASH_IDX, novo_hash)
    listar_clientes.clear()
    return True


# ============================================================================
# Log de acesso
# ============================================================================

@st.cache_data(ttl=300, show_spinner=False)
def listar_log_acesso() -> pd.DataFrame:
    """Retorna DataFrame com todos os registros de acesso.

    Colunas: email | data (YYYY-MM-DD) | hora_primeiro_acesso (HH:MM:SS).
    """
    ws = _get_aba(ABA_LOG)
    records = ws.get_all_records()
    df = pd.DataFrame(records)
    if df.empty:
        df = pd.DataFrame(columns=COLUNAS_LOG)
    return df


def registrar_acesso(email: str) -> bool:
    """Registra 1 acesso do email na data de hoje. Idempotente.

    Schema denormalizado (decisão do usuário §5.93): o log guarda os
    dados do cliente direto (codigo, nome, sobrenome, empresa) em vez
    de só email — torna a planilha autocontida e preserva o "snapshot"
    do cliente no momento do acesso.

    Se já existe linha (email, hoje), não duplica — retorna False.
    Se não existe, busca o cliente em `listar_clientes()`, adiciona
    linha completa, retorna True.

    Cliente não encontrado (ex: admins ainda não migrados pra Sheet):
    grava o log assim mesmo com colunas extras em branco — após Fase E
    todos os usernames terão match.

    Decisão de design (5.93): granularidade dia, não session. Se cliente
    entra 10x em 24h, conta 1 vez (suficiente pra acompanhar engajamento
    sem overload da sheet).
    """
    if not email:
        return False
    email_strip = email.strip()
    hoje_str = date.today().isoformat()

    # Idempotência: já tem linha (email, hoje)?
    df_log = listar_log_acesso()
    if not df_log.empty and "email" in df_log.columns and "data" in df_log.columns:
        match = df_log[
            (df_log["email"].astype(str).str.strip() == email_strip)
            & (df_log["data"].astype(str) == hoje_str)
        ]
        if not match.empty:
            return False  # já registrado hoje

    # Busca dados do cliente pra preencher colunas extras (denormalização).
    cliente = buscar_cliente_por_email(email_strip)
    if cliente:
        codigo = str(cliente.get("codigo", ""))
        nome = str(cliente.get("nome", ""))
        sobrenome = str(cliente.get("sobrenome", ""))
        empresa = str(cliente.get("empresa", ""))
    else:
        # Sem match (ex: admin ainda não migrado pra Sheet) — colunas
        # extras vazias. Log ainda registra pra ter audit trail.
        codigo = nome = sobrenome = empresa = ""

    ws = _get_aba(ABA_LOG)
    agora = datetime.now().strftime("%H:%M:%S")
    ws.append_row(
        [codigo, nome, sobrenome, empresa, email_strip, hoje_str, agora],
        value_input_option="USER_ENTERED",
    )
    listar_log_acesso.clear()
    return True
