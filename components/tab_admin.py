"""
components/tab_admin.py
=======================

Aba "Admin" do dashboard — visível só pra usuários em ADMIN_EMAILS.

Sub-views (Fase C+D §5.93):
  1. Clientes (Fase C) — form de cadastro, tabela de clientes
     cadastrados, botão "Regenerar senha" por linha.
  2. Log de Acesso (Fase D) — tabela + gráfico de usuários únicos/dia.

Fluxo de cadastro:
  - Admin preenche código + nome + sobrenome + empresa + email.
  - App gera senha aleatória de 12 chars (letras + dígitos).
  - App computa bcrypt hash, grava na sheet via `adicionar_cliente`.
  - App MOSTRA a senha plana UMA vez (st.code) pro admin copiar e enviar
    ao cliente por email. Senha plana NUNCA é gravada/persistida.

Fluxo de reset:
  - Admin clica "Regenerar senha" na linha do cliente.
  - App gera nova senha, atualiza hash via `atualizar_senha_hash`.
  - Mostra nova senha plana UMA vez.

Pattern aderente: usa `eh_admin()` pra autorização (centralizado em
`utils/admin.py`). Mesmo padrão visual das outras abas (h1 + linha preta).
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, date

import bcrypt
import pandas as pd
import streamlit as st

from utils.admin import eh_admin
from utils.google_sheets import (
    COLUNAS_CLIENTES,
    adicionar_cliente,
    atualizar_cliente,
    atualizar_senha_hash,
    buscar_cliente_por_email,
    listar_clientes,
    listar_log_acesso,
)


# Caracteres usados pra gerar senhas aleatórias. Excluí confusos
# (0/O/o/1/l/I) pra reduzir erro de digitação humana ao colar do email.
_SENHA_CHARS = "".join(
    c for c in (string.ascii_letters + string.digits)
    if c not in "0Oo1lI"
)

# Tamanho default da senha gerada — decisão UX do usuário (§5.93):
# clientes copiam/colam do email, 6 chars é mais amigável que 12.
# Tradeoff: 6 chars × ~50 chars/alfabeto = ~15bi combinações.
# Streamlit Cloud sem rate limiting nativo → ataque de força bruta em
# escala demoraria meses. Aceitável pro contexto interno BBI (100
# clientes conhecidos). Se virar produto público, repensar.
_SENHA_TAMANHO_DEFAULT = 6


def _gerar_senha_aleatoria(n: int = _SENHA_TAMANHO_DEFAULT) -> str:
    """Gera senha aleatória de N chars usando `secrets` (CSPRNG)."""
    return "".join(secrets.choice(_SENHA_CHARS) for _ in range(n))


def _hash_bcrypt(senha_plana: str) -> str:
    """Retorna bcrypt hash UTF-8 da senha plana."""
    return bcrypt.hashpw(
        senha_plana.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")


# ============================================================================
# Renderer principal (chamado pelo app.py quando aba == "Admin")
# ============================================================================

def render_aba_admin(user: str | None = None) -> None:
    """Entry point da aba Admin."""
    if not eh_admin(user):
        st.error(
            "🔒 Acesso restrito a administradores. "
            "Se você acredita que isso é um erro, contate o time."
        )
        return

    st.markdown("# ADMIN")
    st.markdown(
        '<div style="border-bottom: 2px solid #313131; '
        'margin: -0.2rem 0 1.2rem 12px;"></div>',
        unsafe_allow_html=True,
    )

    # Sub-views: dois botões no topo do conteúdo (não na sidebar — pra
    # não poluir o menu principal). Padrão diferente das outras abas
    # porque Admin é uso ocasional.
    if "admin_subview" not in st.session_state:
        st.session_state["admin_subview"] = "Clientes"

    col_btn1, col_btn2, _ = st.columns([1, 1, 4])
    with col_btn1:
        if st.button(
            "👤 Clientes",
            type="primary" if st.session_state["admin_subview"] == "Clientes" else "secondary",
            width="stretch",
        ):
            st.session_state["admin_subview"] = "Clientes"
            st.rerun()
    with col_btn2:
        if st.button(
            "📊 Log de Acesso",
            type="primary" if st.session_state["admin_subview"] == "Log" else "secondary",
            width="stretch",
        ):
            st.session_state["admin_subview"] = "Log"
            st.rerun()

    st.divider()

    subview = st.session_state["admin_subview"]
    if subview == "Clientes":
        _render_sub_clientes()
    elif subview == "Log":
        _render_sub_log()
    else:
        _render_sub_clientes()


# ============================================================================
# Sub-view: Clientes (Fase C)
# ============================================================================

def _render_sub_clientes() -> None:
    """Form de cadastro + tabela + reset de senha."""
    # ----- Form de cadastro -----
    st.subheader("Cadastrar novo cliente")
    with st.form("admin_form_cadastro", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            codigo = st.text_input("Código do cliente", key="admin_form_codigo")
            nome = st.text_input("Nome", key="admin_form_nome")
            empresa = st.text_input("Empresa", key="admin_form_empresa")
        with col2:
            sobrenome = st.text_input("Sobrenome", key="admin_form_sobrenome")
            email = st.text_input("Email (será o usuário de login)", key="admin_form_email")

        submitted = st.form_submit_button(
            "Gerar senha + Cadastrar", type="primary", width="stretch",
        )

    if submitted:
        # Validações básicas
        erros = []
        if not codigo.strip():
            erros.append("código vazio")
        if not nome.strip():
            erros.append("nome vazio")
        if not sobrenome.strip():
            erros.append("sobrenome vazio")
        if not empresa.strip():
            erros.append("empresa vazia")
        if not email.strip() or "@" not in email:
            erros.append("email inválido")
        if erros:
            st.error(f"Erros no formulário: {', '.join(erros)}")
        else:
            # Checa email duplicado
            existente = buscar_cliente_por_email(email)
            if existente is not None:
                st.error(
                    f"❌ Email **{email}** já cadastrado "
                    f"(código `{existente.get('codigo')}`). "
                    "Use o botão 'Regenerar senha' na tabela abaixo "
                    "se quer apenas redefinir a senha."
                )
            else:
                # Gera senha + hash + grava
                senha_plana = _gerar_senha_aleatoria()
                senha_hash = _hash_bcrypt(senha_plana)
                try:
                    adicionar_cliente(
                        codigo=codigo.strip(),
                        nome=nome.strip(),
                        sobrenome=sobrenome.strip(),
                        empresa=empresa.strip(),
                        email=email.strip(),
                        senha_hash=senha_hash,
                    )
                    st.success(
                        f"✅ Cliente **{nome} {sobrenome}** "
                        f"(`{email}`) cadastrado com sucesso!"
                    )
                    _mostrar_senha_gerada(email.strip(), senha_plana)
                except Exception as e:
                    st.error(f"❌ Erro ao gravar na planilha: {e}")

    st.divider()

    # ----- Tabela + reset de senha -----
    st.subheader("Clientes cadastrados")
    df = listar_clientes()

    if df.empty:
        st.info("Nenhum cliente cadastrado ainda. Use o formulário acima.")
        return

    # Esconde senha_hash da visualização (segurança UX — admin não precisa
    # ver, e não cabe na tela com tanto char).
    cols_visiveis = [c for c in COLUNAS_CLIENTES if c != "senha_hash"]
    df_display = df[cols_visiveis].copy()
    st.dataframe(df_display, width="stretch", hide_index=True)

    # ----- Reset de senha por email -----
    # ----- Editar dados do cliente -----
    with st.expander("✏️ Editar dados de um cliente (código/nome/sobrenome/empresa)"):
        emails_edit = ["—"] + sorted(df["email"].astype(str).tolist())
        email_edit = st.selectbox(
            "Selecione o email do cliente:",
            options=emails_edit,
            key="admin_edit_email_select",
        )

        if email_edit and email_edit != "—":
            # Carrega dados atuais pra preencher o form
            cliente_atual = buscar_cliente_por_email(email_edit)
            if cliente_atual is None:
                st.error("Cliente não encontrado (recarregue a página).")
            else:
                st.caption(
                    f"Editando: **{email_edit}** "
                    f"(email não pode ser alterado — use Cadastrar+Excluir se precisar)"
                )
                with st.form("admin_form_editar", clear_on_submit=False):
                    col_e1, col_e2 = st.columns(2)
                    with col_e1:
                        novo_codigo = st.text_input(
                            "Código",
                            value=str(cliente_atual.get("codigo", "")),
                            key="admin_edit_codigo",
                        )
                        novo_nome = st.text_input(
                            "Nome",
                            value=str(cliente_atual.get("nome", "")),
                            key="admin_edit_nome",
                        )
                    with col_e2:
                        novo_sobrenome = st.text_input(
                            "Sobrenome",
                            value=str(cliente_atual.get("sobrenome", "")),
                            key="admin_edit_sobrenome",
                        )
                        nova_empresa = st.text_input(
                            "Empresa",
                            value=str(cliente_atual.get("empresa", "")),
                            key="admin_edit_empresa",
                        )

                    salvou = st.form_submit_button(
                        "Salvar alterações", type="primary", width="stretch",
                    )

                if salvou:
                    # Compara com atual pra evitar update desnecessário
                    mudou = (
                        str(cliente_atual.get("codigo", "")) != novo_codigo
                        or str(cliente_atual.get("nome", "")) != novo_nome
                        or str(cliente_atual.get("sobrenome", "")) != novo_sobrenome
                        or str(cliente_atual.get("empresa", "")) != nova_empresa
                    )
                    if not mudou:
                        st.info("Nenhuma alteração detectada.")
                    else:
                        try:
                            ok = atualizar_cliente(
                                email_edit,
                                codigo=novo_codigo.strip(),
                                nome=novo_nome.strip(),
                                sobrenome=novo_sobrenome.strip(),
                                empresa=nova_empresa.strip(),
                            )
                            if ok:
                                st.success(
                                    f"✅ Dados de **{email_edit}** atualizados!"
                                )
                                st.rerun()
                            else:
                                st.error("❌ Cliente não encontrado.")
                        except Exception as e:
                            st.error(f"❌ Erro ao atualizar: {e}")

    st.markdown("**Resetar senha de um cliente:**")
    col_reset1, col_reset2 = st.columns([3, 1])
    with col_reset1:
        emails_opcoes = ["—"] + sorted(df["email"].astype(str).tolist())
        email_reset = st.selectbox(
            "Selecione o email:",
            options=emails_opcoes,
            key="admin_reset_email_select",
            label_visibility="collapsed",
        )
    with col_reset2:
        clicou = st.button(
            "Regenerar senha",
            type="primary",
            width="stretch",
            disabled=(email_reset == "—"),
        )

    if clicou and email_reset != "—":
        nova_senha = _gerar_senha_aleatoria()
        novo_hash = _hash_bcrypt(nova_senha)
        try:
            ok = atualizar_senha_hash(email_reset, novo_hash)
            if ok:
                st.success(f"✅ Senha de **{email_reset}** regenerada!")
                _mostrar_senha_gerada(email_reset, nova_senha)
            else:
                st.error(f"❌ Cliente `{email_reset}` não encontrado na planilha.")
        except Exception as e:
            st.error(f"❌ Erro ao atualizar senha: {e}")


def _mostrar_senha_gerada(email: str, senha: str) -> None:
    """Mostra a senha plana com aviso forte 'copie agora'.

    A senha NÃO é persistida — só aparece UMA vez nesta tela após
    cadastrar/resetar. Se admin não copiar agora, precisará regenerar.
    """
    st.warning(
        "⚠️ **Anote ou copie a senha agora.** Ela não será mostrada "
        "novamente — se perder, use 'Regenerar senha' (cria uma nova)."
    )
    st.code(
        f"Login: {email}\nSenha: {senha}",
        language="text",
    )


# ============================================================================
# Sub-view: Log de Acesso (Fase D — placeholder, será expandido)
# ============================================================================

def _render_sub_log() -> None:
    """Visão do log de acesso: gráfico + tabela.

    Granularidade: 1 linha por (email, dia). Login múltiplo do mesmo
    usuário no mesmo dia conta 1 vez (decisão do usuário §5.93).

    Métricas:
      - Gráfico: usuários únicos por dia (últimos 30 dias)
      - Tabela: raw log (filtrável por email e período)
    """
    import plotly.graph_objects as go

    st.subheader("Log de Acesso")
    df = listar_log_acesso()
    if df.empty:
        st.info(
            "Nenhum acesso registrado ainda. Os registros aparecerão aqui "
            "após o primeiro login de qualquer usuário."
        )
        return

    # Normaliza tipo de data — gspread retorna strings, convertemos.
    df["data_dt"] = pd.to_datetime(df["data"], errors="coerce")
    df = df.dropna(subset=["data_dt"]).copy()

    # ----- Métricas resumo (3 cards) -----
    total_logins = len(df)
    usuarios_unicos = df["email"].nunique()
    hoje = pd.Timestamp(date.today())
    df_30d = df[df["data_dt"] >= hoje - pd.Timedelta(days=30)]
    usuarios_30d = df_30d["email"].nunique() if not df_30d.empty else 0

    col1, col2, col3 = st.columns(3)
    col1.metric("Total de acessos", f"{total_logins:,}".replace(",", "."))
    col2.metric("Usuários únicos (total)", usuarios_unicos)
    col3.metric("Usuários únicos (30d)", usuarios_30d)

    st.markdown("")

    # ----- Gráfico: usuários únicos por dia (últimos 30 dias) -----
    st.markdown("##### Usuários únicos por dia (últimos 30 dias)")
    if df_30d.empty:
        st.caption("Sem acessos nos últimos 30 dias.")
    else:
        grupo_dia = (
            df_30d.groupby("data_dt")["email"]
            .nunique()
            .reset_index()
            .rename(columns={"email": "usuarios_unicos"})
        )
        # Preenche dias faltantes com 0 pra eixo X contínuo
        idx_completo = pd.date_range(
            start=hoje - pd.Timedelta(days=29), end=hoje, freq="D",
        )
        grupo_dia = (
            grupo_dia.set_index("data_dt")
            .reindex(idx_completo, fill_value=0)
            .reset_index()
            .rename(columns={"index": "data_dt"})
        )

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=grupo_dia["data_dt"],
            y=grupo_dia["usuarios_unicos"],
            marker=dict(color="#CC092F"),
            hovertemplate="<b>%{x|%d/%m/%Y}</b><br>%{y} usuários únicos<extra></extra>",
        ))
        fig.update_layout(
            height=280,
            margin=dict(l=20, r=20, t=10, b=20),
            paper_bgcolor="#FFFFFF",
            plot_bgcolor="#FFFFFF",
            showlegend=False,
            xaxis=dict(
                title=None,
                tickformat="%d/%m",
                dtick=86400000 * 3,  # tick a cada 3 dias
                tickangle=0,
            ),
            yaxis=dict(
                title="Usuários únicos",
                tickformat="d",
                gridcolor="#E0E0E0",
            ),
        )
        st.plotly_chart(fig, width="stretch", config={"displaylogo": False})

    st.divider()

    # ----- Tabela completa -----
    st.markdown("##### Registros detalhados")
    col_f1, col_f2 = st.columns([2, 1])
    with col_f1:
        emails_disponiveis = ["(todos)"] + sorted(df["email"].astype(str).unique().tolist())
        filtro_email = st.selectbox(
            "Filtrar por email:", options=emails_disponiveis,
            key="admin_log_filtro_email",
        )
    with col_f2:
        dias_filtro = st.selectbox(
            "Período:",
            options=["Últimos 7 dias", "Últimos 30 dias", "Últimos 90 dias", "Tudo"],
            index=1, key="admin_log_filtro_periodo",
        )

    df_filtrado = df.copy()
    if filtro_email != "(todos)":
        df_filtrado = df_filtrado[df_filtrado["email"] == filtro_email]
    dias_map = {"Últimos 7 dias": 7, "Últimos 30 dias": 30, "Últimos 90 dias": 90}
    if dias_filtro in dias_map:
        n_dias = dias_map[dias_filtro]
        corte = hoje - pd.Timedelta(days=n_dias)
        df_filtrado = df_filtrado[df_filtrado["data_dt"] >= corte]

    # Colunas no schema denormalizado (§5.93): codigo | nome | sobrenome
    # | empresa | email | data | hora_acesso. Tudo já gravado na sheet
    # — não precisa JOIN com a aba Clientes.
    cols_visiveis = [
        "codigo", "nome", "sobrenome", "empresa",
        "email", "data", "hora_acesso",
    ]
    cols_existentes = [c for c in cols_visiveis if c in df_filtrado.columns]
    df_display = df_filtrado.sort_values("data_dt", ascending=False)[
        cols_existentes
    ]
    st.dataframe(df_display, width="stretch", hide_index=True)
    st.caption(f"{len(df_filtrado)} registros após filtros.")
