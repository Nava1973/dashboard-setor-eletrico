# Dashboard do Setor Elétrico Brasileiro

Aplicação web para visualização de dados públicos do setor elétrico (CCEE, ONS, ANEEL).

**MVP atual:** PLD médio diário por submercado, com filtro de período, atalhos temporais e comparação com a média Brasil.

---

## Arquitetura

- **Frontend + backend**: Streamlit (Python)
- **Fonte de dados**: [CCEE Portal Dados Abertos](https://dadosabertos.ccee.org.br/dataset/pld_media_diaria) — CSVs anuais, licença CC-BY-4.0
- **Autenticação**: `streamlit-authenticator` com senhas bcrypt
- **Cache**: `@st.cache_data` com TTL de 12h + botão de refresh manual
- **Atualização automática**: GitHub Action diário que pinga o app

```
pld-dashboard/
├── app.py                  # App principal (UI e gráficos)
├── auth.py                 # Gestão de login
├── data_loader.py          # Ingestão CCEE + cache
├── config.yaml             # Usuários e cookie (NÃO commitar)
├── gen_password.py         # Utilitário para criar hashes de senha
├── requirements.txt
├── .streamlit/config.toml  # Tema
└── .github/workflows/update_data.yml
```

---

## Setup local (Windows — passo a passo)

> Instruções voltadas pra quem está começando. Abra o **Prompt de Comando** (cmd) ou **PowerShell** na pasta onde quer guardar o projeto.

### 1. Clonar o repositório

```cmd
git clone https://github.com/Nava1973/dashboard-setor-eletrico.git
cd dashboard-setor-eletrico
```

### 2. Criar o ambiente virtual (venv) e instalar dependências

```cmd
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Você deve ver `(venv)` no começo do prompt, indicando que o ambiente está ativo.

### 3. Criar o `config.yaml` a partir do template

O arquivo `config.yaml` (com seu usuário/senha) **não vem no repositório por segurança**. Você precisa criá-lo localmente:

```cmd
copy config.yaml.example config.yaml
```

Agora abra o `config.yaml` no editor (VS Code, Notepad++, etc.) e preencha:

**a) Gerar o hash da sua senha:**

```cmd
python gen_password.py
```

Digite a senha desejada e copie o hash gerado (começa com `$2b$12$...`). Cole no campo `password:` do `config.yaml`.

**b) Gerar uma chave secreta para o cookie:**

```cmd
python -c "import secrets; print(secrets.token_hex(32))"
```

Copie a saída (64 caracteres hexadecimais) e cole no campo `cookie.key:` do `config.yaml`.

**c) Trocar `seu_usuario`, `seu_email@example.com` e `Seu Nome`** pelos seus dados.

### 4. Rodar o app

**Opção A — atalho `.bat` (mais fácil):** dê duplo-clique em `abrir_dashboard.bat`. Ele ativa o `venv` e sobe o Streamlit automaticamente.

**Opção B — manualmente no terminal:**

```cmd
venv\Scripts\activate
streamlit run app.py
```

Abre em `http://localhost:8501`. Faça login com o usuário/senha que você configurou.

---

## Deploy em produção (Streamlit Community Cloud — grátis)

É a opção mais simples. Sua app fica em `https://seu-app.streamlit.app` com HTTPS.

### Passo a passo

1. **Crie um repositório GitHub** com todo o código (exceto `config.yaml`, que tem segredos).

2. **Acesse** [share.streamlit.io](https://share.streamlit.io) e faça login com sua conta GitHub.

3. **Clique em "New app"** e aponte para o repositório, branch `main`, arquivo `app.py`.

4. **Configure os secrets**: na página do app, vá em `Settings > Secrets` e cole:

   ```toml
   [auth_config]
   yaml_content = """
   credentials:
     usernames:
       nava:
         name: Nava
         email: nava@example.com
         password: $2b$12$SEU_HASH_BCRYPT_AQUI
         failed_login_attempts: 0
         logged_in: false
         roles:
           - admin
   cookie:
     key: SEU_SECRET_ALEATORIO_LONGO
     name: seb_dashboard_session
     expiry_days: 7
   pre-authorized:
     emails: []
   """
   ```

   E ajuste `auth.py` para ler daí em produção (detalhe abaixo).

5. **Deploy**. Em ~2 minutos está no ar.

### Lendo secrets em produção

Para que `auth.py` use secrets do Streamlit em produção em vez do `config.yaml` local, substitua `_load_config()`:

```python
def _load_config() -> dict:
    # Em produção (Streamlit Cloud), carrega de st.secrets
    if "auth_config" in st.secrets:
        return yaml.load(st.secrets["auth_config"]["yaml_content"], Loader=SafeLoader)
    # Local: carrega do arquivo
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.load(f, Loader=SafeLoader)
```

---

## Deploy alternativo (Railway / Render / Fly.io)

Se quiser mais controle ou precisar rodar além do plano gratuito do Streamlit Cloud, qualquer serviço que rode Python serve. Exemplo com Railway:

1. `railway init` na pasta do projeto.
2. Adicionar um `Procfile` com:
   ```
   web: streamlit run app.py --server.port $PORT --server.address 0.0.0.0
   ```
3. Configurar variáveis de ambiente no painel (equivalente aos secrets).
4. `railway up`.

---

## Atualização automática de dados

Os CSVs da CCEE são atualizados diariamente. O app usa cache de 12h, então a primeira visita após o cache expirar dispara o download automático.

Para garantir que alguém "aqueça" o cache antes de você acessar de manhã (e para manter o app vivo no Streamlit Cloud, que hiberna apps ociosos):

1. No repo GitHub: `Settings > Secrets and variables > Actions > New repository secret`.
2. Adicione `STREAMLIT_APP_URL` = `https://seu-app.streamlit.app`.
3. O workflow em `.github/workflows/update_data.yml` vai pingar o app todo dia às 04h BRT.

---

## Roadmap de próximas abas

Este MVP foi desenhado para evoluir. Próximos candidatos:

1. **Reservatórios** (ONS) — nível de reservatórios equivalentes por subsistema.
2. **Spread entre submercados** (CCEE) — diferencial SE–NE, SE–S etc. e heatmap.
3. **ENA / ENAA** (ONS) — energia natural afluente vs MLT.
4. **Carga e geração por fonte** (ONS) — stacked area hidro/térmica/eólica/solar.
5. **Tarifas de distribuição** (ANEEL) — componentes Parcela A/B, CAIMI.

Cada aba é um novo item em `st.radio` na sidebar + um bloco novo em `app.py`. A arquitetura de cache isolado por loader (como `load_pld_media_diaria`) permite adicionar `load_reservatorios`, `load_ena` etc. sem tocar nas demais.

---

## Segurança

- **Nunca commitar `config.yaml` em produção** — ele tem credenciais.
- **Cookie secret** precisa ser único por deploy e longo (32+ bytes hex).
- **Sempre rode o app atrás de HTTPS** — Streamlit Cloud já faz isso. Em Railway/Render, ative TLS.
- Pra múltiplos usuários, considere trocar `streamlit-authenticator` por Auth0 ou Clerk com SSO.

---

## Licença dos dados

Os dados de PLD são da CCEE sob [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/). Atribua a fonte ao usar.
