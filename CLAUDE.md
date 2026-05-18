# Dashboard Setor Elétrico — Guia pro Claude Code

> ⚠️ **Leia este arquivo por inteiro antes de qualquer tarefa neste projeto.**
> Contém convenções, armadilhas e decisões arquiteturais acumuladas em múltiplas
> sessões. Ignorar leva a repetir discussões já resolvidas ou quebrar padrões
> estabelecidos.
>
> Se fizer mudança estrutural relevante (nova fonte, nova convenção, nova
> armadilha descoberta), atualize este arquivo **antes de fechar a sessão**.

---

## 1. Visão Geral

Aplicação Streamlit para visualização de dados públicos do setor elétrico
brasileiro (CCEE e ONS). Estilo **Bauhaus** (tipografia Bebas Neue + Inter,
paleta vermelho/amarelo/azul/preto sobre creme, geometria sóbria).

**2 abas atuais:**
- **PLD** (CCEE) — PLD com 4 granularidades (horário, diário, semanal, mensal)
  escolhidas via dropdown no título do gráfico. Filtros por período
  (1M/3M/6M/12M/Máx) e submercado (SE/S/NE/N + Média BR).
- **Reservatórios** (ONS) — EAR (% capacidade) por subsistema: 5 gráficos
  empilhados (SIN + SE + S + NE + N), filtros 1A/3A/5A/10A/Máx, faixas azuis
  de período úmido (1º nov – 30 abr).

Autenticação via `streamlit-authenticator` com senhas bcrypt em `config.yaml`
(não versionado) ou `st.secrets` em produção.

---

## 2. Stack Técnico

- **Streamlit 1.56** (não upgrade sem testar — seletores Emotion mudam)
- **Python** (ver `.python-version` / `venv`)
- **pandas, numpy, plotly** — data + visualização
- **curl_cffi** com `impersonate="chrome"` — obrigatório pra CCEE (Akamai)
- **openpyxl** — fallback pra XLSX (hoje preferimos parquet)
- **pyarrow** — parquet nativo do ONS
- **streamlit-authenticator + bcrypt + PyYAML** — auth
- Arquivo de deps: `requirements.txt`

---

## 3. Convenções do Projeto

### 3.1 Cores Bauhaus (`app.py` linhas 56-62)

```python
BAUHAUS_RED    = "#D62828"  # SE (PLD) / SUDESTE (Reservatórios)
BAUHAUS_YELLOW = "#F6BD16"  # NE / NORDESTE  (+ atalho ativo, hover sidebar)
BAUHAUS_BLUE   = "#2A6F97"  # S  / SUL
BAUHAUS_BLACK  = "#1A1A1A"  # N  / NORTE  (+ texto principal)
BAUHAUS_CREAM  = "#F5F1E8"  # fundo da página
BAUHAUS_GRAY   = "#4A4A4A"  # Média BR (PLD) / SIN (Reservatórios) / captions
BAUHAUS_LIGHT  = "#E8E3D4"  # elementos sutis (grids do Plotly)
```

Adicional Reservatórios: `#B3D4F1` = azul claro das faixas de período úmido.

### 3.2 Session State — prefixos e chaves

**PLD:** `data_ini`, `data_fim`, `_dataset_max`, `_dataset_min`, `granularidade`,
`granularidade_display` (legado), `selectbox_granularidade`.

**Reservatórios:** usa prefixo `res_` — `res_data_ini`, `res_data_fim`,
`_res_dataset_max`, `_res_dataset_min`.

**Globais:** `_debug_erros` (resetado a cada chamada de loader),
`_demo_mode`, `_fontes_por_ano`, `_erros_carga`, `_erros_carga_reservatorios`.

**Regra:** novas abas usam prefixo próprio pra evitar colisão
(ex: se criar aba "tarifas", prefixar `tar_`).

### 3.3 Data Loaders (`data_loader.py`)

**Arquivo único** (ver decisão 5.1). Entry points públicos e cacheados:

| Função | Dataset | TTL | Schema de saída |
|---|---|---|---|
| `load_pld_media_diaria()` | CCEE diária | 12h | `(data, submercado, pld)` |
| `load_pld_horaria()` | CCEE horária | 12h | `(data=datetime, submercado, pld)` |
| `load_pld_media_semanal()` | CCEE semanal | 12h | `(data=ini-semana, submercado, pld)` |
| `load_pld_media_mensal()` | CCEE mensal | 12h | `(data=1º dia mês, submercado, pld)` |
| `load_reservatorios()` | ONS EAR | 2h (+ 30d interno pros anos fechados) | `(data, subsistema_code, subsistema_nome, ear_pct)` |
| `load_ena()` | ONS ENA | 2h (+ 30d interno pros anos fechados) | `(data, subsistema_code, subsistema_nome, ena_mwmed, ena_armazenavel_mwmed, ena_mlt_pct)` |
| `clear_cache()` | — | — | Limpa as 6 |

**Padrões internos:**
- `_http_get()` usa curl_cffi se disponível, fallback requests.
- `_try_ckan_api` → `_try_dump` → `_try_pda_download` (cascade pra CCEE).
- `_normalize_*()` por dataset, usa `_identify_column()` tolerante a nomes.
- Erros vão pra `st.session_state["_debug_erros"]`, nunca silenciados.

### 3.4 Controles de Período — `_render_period_controls()` e variante

**`_render_period_controls`** — helper compartilhado em `app.py` (antes
do bloco SIDEBAR). Usado por PLD, Reservatórios, ENA e Geração
(Diária/Mensal). Assinatura:

```python
_render_period_controls(
    presets=[(label, delta_days_or_None, is_max), ...],
    session_key_ini="...", session_key_fim="...",
    key_prefix="btn_xxx_",
    min_d=..., max_d=...,
)
```

- Layout: N botões + spacer 0.3 + 2 date_inputs, proporções `[1]*N + [0.3, 1.4, 1.4]`.
- Preset ativo tem `type="primary"` (fundo amarelo via CSS global).
- Detecção automática: `delta_days` ou `is_max=True` + `data_ini == min_d`.

**`_render_period_controls_horaria`** — variante pro modo "data base +
janela" usado em Geração quando granularidade=Horária. 1 `date_input`
"Data base" + presets como **window de N dias terminando em data_base**
(não "últimos N dias ancorados em max_d"). Razão: em Horária, ver "1
dia específico" no PLD/Reservatórios exige setar `data_ini == data_fim`,
fricção desnecessária. Layout idêntico ao gêmeo (mesmas proporções de
coluna), com a 3ª coluna vazia preservada pra alinhar largura do campo
"Data base" com os date_inputs das outras abas. Ver decisão 5.9.

**`_format_periodo_br(data_ini, data_fim, granularidade)`** — string de
período em formato BR sob o título Bauhaus de cada gráfico. Formato
varia por granularidade: `abr/2026` (Mensal 1 mês) /
`mai/2025 a abr/2026` (Mensal ≥ 2) / `21/04/2026` (Horária 1D) /
`15/04/2026 a 21/04/2026` (Horária ≥ 2D ou Diária ≥ 2). Helper
top-level reusável.

### 3.5 Tipografia e Layout

- **Títulos Bauhaus:** Bebas Neue, 1.1rem, letter-spacing 0.08em,
  `border-bottom: 2px solid #1A1A1A`.
- **Corpo de texto:** Inter.
- **Captions:** Inter 0.85rem `#6B6B6B` italic.
- **Hover de gráficos:** IBM Plex Mono ou Courier (alinhamento com espaço fixo).
- Página limitada a `max-width: 1000px` no `.block-container`.
- Hovermode Plotly: `"x unified"` pro PLD, permite `hoverformat` por
  granularidade (`%d/%m/%Y %H:%M`, `%d/%m/%Y`, `%b %Y`).

---

## 4. Armadilhas Conhecidas

### 4.1 CSS & UI

- **NUNCA usar `:has()` em CSS.** Trava o app no Streamlit 1.56. Aprendizado
  histórico documentado em sessão anterior. Se precisar estilizar um pai com
  base em estado do filho, achar alternativa (ex: filter trick, ou atacar
  o input diretamente).
- **Filter CSS no pai afeta todos os children.** Parent filter sempre é
  aplicado após child filter no pipeline de render — child não pode "cancelar"
  um brightness(0) do pai. Exemplo: checkbox styling usa
  `filter: grayscale(1) brightness(0.6) contrast(5)` no span, e os valores
  foram escolhidos por aritmética pra que branco (1.0 → 0.6 → 1.0 após
  contrast) e pink (0.5 → 0.3 → 0 após clamp) resultem em tick branco sobre
  fundo preto.
- **Classes Emotion do Streamlit (`st-emotion-cache-XXXX`) são INSTÁVEIS** —
  geradas por build, mudam em updates. **Usar apenas** `data-testid="stX"`
  ou `data-baseweb="X"` (estáveis entre versões).
- **Streamlit checkbox: o `<input>` real tem `opacity:0`** — o `<span>` pai é
  quem desenha o quadradinho visível. Sem `:has()` não dá pra estilizar o pai
  baseado em `:checked` do filho. Solução aceita: `filter` no span (ver
  `data_loader.py` comentários do bloco checkbox em `app.py` linhas ~308-342).
- **Múltiplos blocos `<style>` via `st.markdown` espalhados** na página podem
  se sobrepor ou se anular. Prefira **um único bloco global** no topo
  (`app.py` linhas ~58-400). Estilos muito específicos de um componente
  podem ficar perto dele, mas documentar.

### 4.2 Download HTTP / CCEE / ONS

- **CCEE é bloqueado por Akamai.** Requests puros retornam 403.
  `curl_cffi` com `impersonate="chrome"` + `BROWSER_HEADERS` é
  **obrigatório**. Não é negociável.
- **ONS S3 público NÃO bloqueia** — hospedado em AWS S3 simples
  (`ons-aws-prod-opendata.s3.amazonaws.com`), funciona com requests puros.
  **Padrão do projeto: usar curl_cffi `impersonate="chrome"` em TODAS as
  fontes externas** por consistência e robustez futura (caso ONS troque
  pra CDN com fingerprinting).
- **Discovery de resource IDs CCEE:** `scripts/discover_ccee_ids.py`.
  Rodar quando CCEE publicar novo ano.
- **Descoberta ONS:** documentada em `docs/reservatorios_research.md`.

### 4.3 Streamlit widgets (quirks por versão)

- **`st.popover` em Streamlit 1.56 NÃO expõe `data-testid` estáveis** —
  só classes Emotion. Estilizar é frágil. **Preferir `st.selectbox`
  estilizado** com `[data-testid="stSelectbox"] [data-baseweb="select"] > div`
  (estáveis). Aceita visual default BaseWeb no menu aberto.
- **`st.radio` como atalho de período conflita com `date_input`** —
  aprendizado histórico documentado em sessão anterior (não revalidado nesta
  sessão). Usar `st.button` com `type="primary"` pra estado ativo (como no
  `_render_period_controls`).
- **`st.date_input` labels ficam ACIMA do campo** (default Streamlit). CSS
  existente deixa em Inter 0.75rem bold. Não tente esconder só em uma aba
  — uniformização global é regra.
- **`st.cache_data` fora de runtime** gera warnings mas não quebra — ok pra
  scripts de validação chamarem funções cacheadas.
- **Rerun automático.** Streamlit re-executa o script em toda interação
  (clique de button, mudança de selectbox). Evitar `st.rerun()` redundante,
  só usar se o estado precisar ser propagado DENTRO do mesmo render.
- **`on_change` callback do selectbox** dispara ANTES do main script rerun
  — usado pra unificar `granularidade_display` → `granularidade` sem rerun
  extra.

### 4.4 Ambiente local

**OneDrive + Git + Python = dor de cabeça real.** Evidência desta sessão:

- Projeto originalmente em
  `C:\Users\RENOMEAR\OneDrive\Desktop\dashboard-setor-eletrico`.
- `git init` nesse local causou problemas de lock/sync — recomendei mover.
- Migração pra `C:\Projetos\dashboard-setor-eletrico`.
- **Rename da pasta antiga no OneDrive FALHOU em todas as tentativas:**
  - `mv` via git bash ❌
  - `ren` via cmd.exe ❌
  - `Rename-Item` via PowerShell ❌
- Solução: **rename manual via Windows Explorer** (funcionou).
- **Causa:** OneDrive mantém file locks durante sincronização, impedindo
  rename programático. Mesmo com sync pausado, arquivos recém-alterados
  ficam em "placeholder" state.

**Regra:** sempre criar projetos novos em `C:\Projetos\...` ou outro
caminho fora do OneDrive. Venv especialmente.

**Outros itens Windows:**
- **venv local:** usar `venv\Scripts\python.exe` explicitamente. `python`
  puro pode pegar outra instalação do sistema.
- **Shell Windows cp1252:** scripts que fazem `print()` de Unicode (emojis,
  setas `→`, caracteres PT-BR raros) podem crashar. Usar
  `sys.stdout.reconfigure(encoding="utf-8")` no início do script.

### 4.5 Deploy Streamlit Cloud + `requirements.txt`

- **Upper bounds conservadores podem quebrar deploy no Cloud sem quebrar
  local.**

  Evidência (commits `87c8e72` → `80634b5`): `pyarrow>=15.0,<22.0` rodava
  normal no venv local (pip resolveu pyarrow 23.0.1 como dep transitiva do
  Streamlit 1.56 ANTES do constraint ser adicionado na Fase B dos
  Reservatórios). No Cloud, que faz `pip install -r requirements.txt` do
  zero, o resolver caiu numa pyarrow <22 sem wheel pra Python 3.13 →
  "Error installing requirements". Fix: `<24.0`.

  **Regra:** upper bound só se houver incompatibilidade CONHECIDA com versão
  mais nova. Caso contrário, deixar só lower bound (`>=X`). Se usar upper,
  manter sincronizado com a versão realmente instalada local.

- **Cache de pip local não re-resolve ao editar constraints.**

  Venv antigo continua rodando versões fora do constraint novo sem
  reclamar. Pra validar "de verdade", recriar o venv OU
  `pip install -r requirements.txt --upgrade --force-reinstall`.

  **Checkpoint antes de push que mexe em deps:** comparar
  `venv\Scripts\pip.exe show <lib>` com o constraint. Se local está fora
  do range declarado, Cloud vai falhar.

- **Streamlit 1.56 declara só `pyarrow>=7.0`** (verificado via
  `importlib.metadata.distribution('streamlit').requires`). Nossos upper
  bounds não estão resolvendo conflito real com Streamlit — são paranoia.
  Aumentar é barato, diminuir é que gera dor.

- **Como pegar log de deploy falho:** em `https://share.streamlit.io/`,
  clicar no app → botão **"Manage app"** no canto inferior direito → painel
  lateral abre com logs em tempo real. Procurar bloco "Building" /
  "Installing dependencies" com `ERROR:` do pip.

### 4.6 Windows PowerShell 5.1 + UTF-8 + BOM (encoding hell)

> **Nota de excecao**: esta armadilha contem glifos nao-ASCII
> (em-dash, smart quote, a-circunflexo, simbolo do Euro) usados
> para ilustrar o problema de encoding. Eh a UNICA secao do
> CLAUDE.md onde glifos nao-ASCII sao intencionais - todas as
> outras decisoes/armadilhas seguem ASCII puro nas adicoes da
> sessao 07/05/2026 em diante.

**`Set-Content -Encoding UTF8` em Windows PowerShell 5.1 escreve
UTF-8 COM BOM** (`EF BB BF` nos primeiros 3 bytes), nao UTF-8 puro.
Combinado com `Get-Content -Raw` que le com encoding default
cp1252 (mesmo se o arquivo eh UTF-8 sem BOM), gera double-encoding
silencioso e corrompe o arquivo.

**Cenario reproduzido nesta sessao** (commit `c5ecf15` cleanup):

1. Arquivo `.commit_msg.txt` criado pelo Write tool em UTF-8 puro
   (sem BOM), contendo 1 em-dash (`—`, U+2014, bytes `E2 80 94`).
2. PowerShell `Get-Content -Raw .commit_msg.txt` le os 3 bytes do
   em-dash interpretando como cp1252:
   - `0xE2` -> `â` (U+00E2)
   - `0x80` -> `€` (U+20AC, smart quote)
   - `0x94` -> `"` (U+201D, right double quote)
3. `-replace [char]0x2014, '-'` nao casa porque o texto ja nao
   contem U+2014, contem 3 chars cp1252.
4. `Set-Content -Encoding UTF8` escreve esses 3 chars como UTF-8
   COM BOM (`EF BB BF` no inicio + 3-9 bytes corrompidos no
   meio). Total: 4 chars nao-ASCII no arquivo final.

**Como detectar**: ler bytes brutos via
`[System.IO.File]::ReadAllBytes` + verificar `bytes[0..2]` pra BOM
e iterar bytes `> 127`:

```powershell
$bytes = [System.IO.File]::ReadAllBytes('arquivo.txt')
"First 4 hex: $([BitConverter]::ToString($bytes[0..3]))"
if ($bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
    "Has BOM"
}
```

**Solucao recomendada (uso do Claude Code)**: usar Write tool /
create_file pra escrever conteudo de arquivo. O Write tool escreve
UTF-8 sem BOM, sem ler-modificar-escrever, sem PowerShell no
caminho.

**Solucao em PowerShell puro** (se inevitavel):

```powershell
# Escreve UTF-8 sem BOM
[System.IO.File]::WriteAllText(
    'arquivo.txt', $conteudo,
    [System.Text.UTF8Encoding]::new($false)
)
```

O `$false` no construtor `UTF8Encoding` suprime o BOM. PowerShell
7+ tem `Set-Content -Encoding utf8NoBOM` mas nao funciona em 5.1.

**Outras armadilhas relacionadas** (nao reproduzidas nesta sessao
mas conhecidas):
- `Out-File` default: UTF-16 LE com BOM em PowerShell 5.1.
- `Get-Content` (sem `-Raw` e sem `-Encoding`) le com encoding
  default da console (varia por OS - cp1252 em Windows pt-BR).
- `>` redirect operator: usa o mesmo default do `Out-File`.

**Regra pratica**: nunca usar PowerShell 5.1 pra ler-modificar-
escrever arquivos UTF-8. Usar Python (`open(file, encoding='utf-
8')`), Write tool (Claude Code), ou Git Bash. Se precisar usar
PowerShell, usar `[System.IO.File]` direto.

### 4.7 Streamlit rodando do Python global em vez do venv

SINTOMA: graficos plotly_events renderizam invertidos (barras
horizontais em vez de verticais). Lib instalada no venv mas nao
acessivel em runtime.

CAUSA: comando `streamlit run app.py` direto pega `python` do PATH
do sistema (Python 3.14 global em
`C:\Users\RENOMEAR\AppData\Local\Python\pythoncore-3.14-64\`), nao
o do venv. Lib esta instalada no venv mas o Streamlit global nao
tem acesso a ela.

DIAGNOSTICO: console mostra `ModuleNotFoundError: No module named
'streamlit_plotly_events'` com path do Python global. Plotly da
versao global tambem pode ser diferente da do venv (ex: 6.x global
vs 5.x venv) — figuras serializadas com APIs incompativeis
renderizam invertidas.

SOLUCAO: SEMPRE rodar do venv local:

```powershell
# Recomendado (-m streamlit pra invocar via python explicito)
venv\Scripts\python -m streamlit run app.py

# Ou ativar venv antes
venv\Scripts\Activate.ps1
streamlit run app.py
```

NUNCA: `streamlit run app.py` direto sem ativacao — pega `streamlit`
do Python global do PATH.

Detectado em: sessao 07/05/2026 durante diagnostico de inversao do
grafico SIN. Fase Drill.2.C.1 — `streamlit-plotly-events` instalado
no venv, mas Streamlit rodando do global gerava sintomas que pareciam
bug da lib quando na verdade era ambiente errado.

### 4.8 OOM silencioso no Streamlit Cloud free tier

SINTOMA: aba quebra com "Oh no" no Cloud, mas funciona perfeitamente
local. Browser DevTools mostra:
- WebSocket onclose
- Cannot send rerun backMessage when disconnected from server
- GET /_stcore/health -> 503 Service Unavailable
- GET /_stcore/host-config -> 503 Service Unavailable

Logs do servidor (Manage app > Logs) mostram ZERO traceback Python -
apenas warnings de deprecation. App parece carregar normalmente,
depois conexao morre.

CAUSA: SIGKILL externo do Cloud por OOM (limite 1GB free tier).
Container morre instantaneamente sem propagar excecao Python - wrapper
nao captura SIGKILL. Browser ve apenas a conexao caindo.

DIAGNOSTICO PROGRESSIVO:
1. Local funciona, Cloud nao -> diferenca de ambiente.
2. Logs servidor sem traceback -> nao eh erro Python.
3. DevTools com 503 nos endpoints -> servidor crashou.
4. Hipotese OOM -> instrumentar com print de RAM.

INSTRUMENTACAO MINIMA:
```python
import sys
print(
    f"[DEBUG-RAM] df final: "
    f"{df.memory_usage(deep=True).sum()/1e6:.1f}MB, "
    f"{len(df):,} rows",
    file=sys.stderr, flush=True,
)
```

Rodar local pra ver tamanho REAL do dataset (idem entre ambientes -
RAM nao depende da maquina, depende dos dados).

GATE DE DECISAO:
- <150MB: H1 OOM descartado, problema eh outro vetor.
- 150-300MB: marginal, gc.collect() + del df pode bastar.
- >300MB: OOM confirmado fortissimo. Refactor estrutural obrigatorio
  (agregacao no worker pra reduzir cardinalidade).

PADROES DE FIX (ordem de complexidade):
1. gc.collect() + del df apos cada chamada (mirror Curtailment 35e4b97).
2. Agregacao DIARIA no worker antes do concat (mirror Curtailment 075a8d0).
3. Dual-loader: default agregado + lazy hourly pra modo single-day
   (decisao 5.57 desta sessao).

DETECTADO EM:
- Curtailment (sessao 30/04/2026, commits 35e4b97 + 075a8d0).
- Despacho Termico (sessao 08/05/2026, commit 0ec63e9 - decisao 5.57).

Padrao identico nos dois casos. Mantenedor: SEMPRE estimar RAM final
do dataset antes de assumir que loader generico vai funcionar no Cloud.

### 4.9 Parquets ONS publicam colunas numericas como object/string

SINTOMA: .sum() ou .mean() em coluna numerica do parquet ONS retorna
string concatenada gigante em vez de numero. Exemplo:

```python
df['val_geracao'].sum()
# Esperado: 12345.67
# Real:     '380.4374.87357.699345.133356.427...' (centenas de chars)
```

CAUSA: parquets ONS preservam dtypes do CSV original (todos string/
object). pandas `.sum()` em object dtype usa `__add__` que pra strings
significa concatenacao.

FIX OBRIGATORIO: coercao numerica explicita antes de agregar:

```python
pd.to_numeric(df[col], errors='coerce').fillna(0).sum()
```

- `errors='coerce'`: NaN se nao parsavel (defensivo)
- `.fillna(0)`: zera NaN antes de sum

CASOS CONHECIDOS:
- Termico: Fase 2 do refactor dual-loader em commit `0ec63e9` (sessao
  08/05/2026, manha) causou Mensal/Diario/Trimestral renderizarem
  zerados ate fix Opcao B (coerce defensivo no helper
  `_agregar_diario_no_worker` antes do groupby).
- Curtailment: descoberto durante investigacao Equatorial (sessao
  08/05/2026, tarde) ao rodar `.sum()` direto em script de inspecao
  manual; loader ja faz `_to_float_br()` em `_padronizar` corretamente,
  mas scripts de investigacao precisam aplicar o mesmo padrao.

REGRA: scripts de inspecao manual (`scripts/investigar_*.py` ou inline)
**sempre** aplicam `pd.to_numeric` antes de qualquer agregacao em
colunas de parquet bruto ONS. NUNCA assumir que `df[col].sum()` retorna
numero.

### 4.10 @st.cache_data nao detecta mudanca em arquivos lidos pelo loader

SINTOMA: edicao in-place de arquivo de dados (ex: Excel de
proprietarios) + Ctrl+R no browser nao reflete mudanca no app.
DataFrame em runtime mostra valores antigos do arquivo. Botao
"Atualizar" na sidebar pode nao resolver tambem.

CAUSA: `@st.cache_data` calcula cache key a partir dos ARGUMENTOS
da funcao decorada, nao do mtime/conteudo dos arquivos que a
funcao le internamente. Loader tipo:

```python
@st.cache_data(ttl=3600)
def carregar_grupos_excel(caminho: str = "...xlsx") -> pd.DataFrame:
    return pd.read_excel(caminho, ...)
```

cacheia o resultado por `(caminho,)`. Se o caminho nao muda,
cache HIT mesmo apos editar o Excel — Streamlit nao re-le.

Ctrl+R no browser tambem nao limpa: cache vive no PROCESSO do
servidor Streamlit, nao na sessao do navegador.

Botao "Atualizar" da sidebar (`clear_cache()` em
data_loader.py:1838) cobre PLD/Reservatorios/ENA/Geracao mas
NAO cobre Curtailment + Excel de grupos. Funcoes nao limpas
descobertas na sessao 08/05/2026:
- carregar_grupos_excel (data_loader_grupos_excel.py:127)
- carregar_aliases (data_loader_grupos_excel.py:202)
- _aplicar_rateio_cached (tab_curtailment.py:1429)
- _construir_opcoes_entidade (tab_curtailment.py:448)
- _calcular_linhas_unidade (tab_curtailment.py:962)
- _download_mes_historico (data_loader_curtailment.py:484)
- carregar_curtailment (data_loader_curtailment.py:534)
- descobrir_ultimo_dia_disponivel (data_loader_curtailment.py:595)

3 SOLUCOES (do mais simples ao mais permanente):

1. **Restart do servidor Streamlit** (recomendado pra dev):
   Ctrl+C no terminal + relancar via
   `venv\Scripts\python.exe -m streamlit run app.py`. Mata
   processo, mata cache, le arquivo novo.

2. **Aguardar TTL expirar** (passivo): TTLs variam — 1h pro
   Excel, 6h pra Curtailment, 30d pra parquets ONS fechados.
   Lento e imprevisivel pra dev local.

3. **Estender clear_cache()** (fix de longo prazo): adicionar
   `.clear()` nas funcoes Excel-dependentes. Decisao da sessao
   08/05/2026 foi NAO fazer agora — preserva `clear_cache()`
   focado nos loaders ONS centrais. Restart eh aceitavel pro
   caso raro de edicao do Excel. Reconsiderar se Excel virar
   editavel via UI no futuro.

CASO QUE MOTIVOU: sessao 08/05/2026 (commit `bce44f9`). Excel
unidades_geradoras.xlsx editado pra padronizar labels
"EQTL (Echo)" -> "Equatorial" em Solar. Local mostrou bug
"O grupo Equatorial nao tem unidades em Solar" mesmo apos
Ctrl+R. Diagnostico via debug `st.write` em
tab_curtailment.py:569 revelou df ainda tinha `EQTL (Echo)`
em PROPRIETARIO unicos pos-rateio. Restart full do Streamlit
resolveu.

REGRA: ao editar arquivo de dados lido por loader cacheado,
fazer restart full do servidor. Nao confiar em Ctrl+R nem em
"Atualizar". Cloud: redeploy ja faz container fresh, mas
reboot manual em share.streamlit.io eh garantido.

### 4.11 ANEEL CKAN tem endpoint SQL mas com whitelist de funcoes

SINTOMA: query SQL agregada (SUM, COUNT, etc) retorna HTTP 403 "Acesso negado: permissions: ['Not authorized to call function CAST']" em datastore_search_sql endpoint da ANEEL.

CAUSA: ANEEL aplica whitelist server-side de funcoes SQL permitidas. CAST(...) e to_number() estao na blacklist; tentativas via GET ou POST retornam 403. Operadores PostgreSQL nativos (::float) e funcoes basicas (SUM, COUNT, replace) sao permitidas.

WORKAROUND: para somar coluna text com virgula decimal BR (tipico em datasets ANEEL como MdaPotenciaInstaladaKW='5,94'), usar replace + cast operator em vez de funcao CAST:

```sql
SELECT SUM(replace("CampoTexto", ',', '.')::float) AS total
FROM "{resource_id}"
WHERE "ColunaDeData" <= '{cutoff}'
```

NOTA RELACIONADA: endpoint paginado datastore_search e endpoint /datastore/dump sao FRAGEIS pra ingestao completa de datasets grandes (truncamento server-side em ~28% via dump, timeout em ~46% via paginacao de 4.3M linhas). Preferir SQL agregado server-side sempre que possivel — retorna 1 linha em ~4-7s sem truncamento.

Investigacao completa: docs/B5_findings.md (Commit E 196a427).

### 4.12 Cache disk orfao sobrevive ao fix de convencao do loader

SINTOMA: apos fix de bug que muda CONVENCAO do retorno do loader (index, schema, formato de campo), proximo load ainda retorna dados buggados. Sanity test re-roda e reproduz o bug original — diagnostico inicial sugere que o fix nao funcionou, mas funcionou; esta sendo mascarado pelo cache.

CAUSA: loaders com cache disk (parquet local + mtime TTL) permanecem validos APOS o codigo do loader mudar. mtime ainda dentro do TTL, parquet ainda eh leitor valido. `@st.cache_data` em RAM tambem pode estar quente. Resultado: `load_X()` retorna cache antigo com schema/convencao antiga em vez de re-executar o fluxo corrigido.

CASO CONCRETO (Sub-sessao G fases G.4 e G.5.a): `load_mmgd_anual` original retornava index com fim de mes (2024-12-31). Fix re-indexa pra 1o do mes (2024-12-01) pra bater com convencao SIGA. Apos aplicar o fix, sanity test continuava mostrando 5/5 NaN no merge porque `cache/mmgd_sql/anual.parquet` ainda tinha o index antigo — `_carregar_de_cache_disk` retornava early com Series buggada antes do codigo novo executar.

WORKAROUND: `rm cache/<loader_name>/*.parquet` antes de re-testar pos-fix de convencao. Em cliente real, equivalentes: botao "Atualizar" da sidebar (se `clear_cache` cobrir o loader — decisao 4.10 lista as funcoes nao cobertas) OU redeploy do container Streamlit Cloud (sempre comeca com cache vazio).

SOLUCAO DE FUNDO: pattern decisao 5.34 (Cache versionado). Path do cache carrega sufixo de versao (`cache/mmgd_sql_v2/` em vez de `cache/mmgd_sql/`). Toda mudanca em schema ou convencao do retorno bump da versao. Cache antigo vira orfao no disco mas nao eh consumido. NAO implementado no `data_loader_aneel_mmgd_sql.py` hoje — manutencao manual eh a regra.

NOTA RELACIONADA: especifico a caches DISK persistentes. Cache so em RAM (`@st.cache_data` sem parquet overlay) some no restart do processo e o problema nao se manifesta — tradeoff de performance vs invalidacao automatica.

Detectado em: Sub-sessao G (Commit G 22403c5), fases G.4 e G.5.a. Mascarou validacao por 1 ciclo de teste em cada caso.

---

## 5. Decisões Arquiteturais

### 5.1 `data_loader.py` único vs subpastas

**Decisão:** arquivo único mesmo com 2 fontes (CCEE + ONS).

**Regra:** modulariza em subpasta `loaders/` **só com 3+ fontes distintas.**

**Razão:** ambas as fontes compartilham `_http_get`, `BROWSER_HEADERS`,
padrão de cache + erro. Separar agora duplicaria ~150 linhas sem benefício.

### 5.2 Cache split por ano (Reservatórios)

**Anos fechados** (pré-corrente): TTL 30 dias em cache interno por ano
(`_download_reservatorio_parquet_historico`). Dados imutáveis — ONS não
reemite histórico.

**Ano corrente:** sem cache interno — re-baixa a cada expiração do externo.

**Cache externo** `load_reservatorios()`: TTL 2h. Captura atualização
diária do ONS (geralmente publicada entre 10-14h BRT).

**`clear_cache()` limpa só o externo.** Histórico de 30d sobrevive. Efeito:
botão "Atualizar" re-baixa só ano corrente (26 anos de histórico cacheados
em disco do Streamlit). Eficiente.

### 5.3 SIN ponderado por EARmax, não média simples

ONS não publica linha SIN agregada no dataset `ear-diario-por-subsistema`
— só os 4 subsistemas.

**Cálculo correto:**
```
SIN_pct(data) = sum(ear_verif_mwmes) / sum(ear_max) × 100
```

Capacidades (MWmês): SE 204.615 | NE 51.691 | S 20.459 | N 15.302.
SE domina (70% do total). Média simples estaria ERRADA — daria peso igual
a subsistemas com capacidades ~13× diferentes.

### 5.4 ONS: dataset EAR agregado em vez do hidrológico

**Decisão inicial descartada:** usar `dados-hidrologicos-res` e calcular
EAR a partir de `val_volumeutilcon` por reservatório + tabela de EARmax.

**Problema:** 63k linhas/ano × reservatório × dia, sem EARmax nas colunas.

**Descoberta (Fase A Reservatórios):** existe `ear-diario-por-subsistema`
no CKAN ONS com EAR em % **PRONTO**, agregado por subsistema. Parquet
33KB/ano × 27 anos = ~900KB total.

Muito mais simples e preciso. Ver `docs/reservatorios_research.md` pra
contexto completo.

### 5.5 Selectbox estilizado no lugar de popover

Tentativa inicial com `st.popover` pro dropdown de granularidade no PLD
(Fase 2). Streamlit 1.56 não expõe `data-testid` estáveis no popover — só
classes Emotion dinâmicas (`e7msn5c*`).

**Migração pra `st.selectbox`** com seletores estáveis:
`[data-testid="stSelectbox"]` + `[data-baseweb="select"]`.

Aceita visual default BaseWeb no menu aberto como preço da robustez.
Agregado: seta ▾ via `::after`, `width: fit-content` pra encolher ao texto,
SVG chevron default escondido.

### 5.7 ENA: métrica é % MLT (normalizada), eixo Y compartilhado

**Decisão:** na aba ENA a métrica plotada é **`ena_mlt_pct`** (% da Média de
Longo Termo — ONS), não MWmed absoluto. Os 5 gráficos compartilham o mesmo
eixo Y **fixo em 0-250%**. Linha tracejada cinza em **100%** marca a média
histórica do mês. **Formato: zero casas decimais** (contraste com EAR que
usa 1 decimal — ENA varia mais bruscamente, decimal em % de MLT agrega
pouca informação vs. dígitos extras no display).

**Por que range fixo 0-250%:** ENA pode atingir ~1000% da MLT em eventos
hidrológicos excepcionais (enchentes regionais extremas). Um range
derivado-do-filtro seria esticado por esses picos raros, achatando a faixa
0-200% que é onde ~95% dos dados vivem. Range fixo preserva resolução
visual na faixa informativa. Picos acima de 250% **não são filtrados dos
dados** — ficam visualmente cortados no topo do gráfico e o hover continua
mostrando o valor real (ex: 487,3% MLT). A 3ª nota explicativa acima da
aba avisa o leitor.

**Razão:** % MLT é métrica **normalizada** — todos os subsistemas têm a
mesma dinâmica (em torno de 100%), comparação direta entre eles faz sentido
visualmente. Situação análoga ao EAR dos Reservatórios.

**Contraste com MWmed absoluto:** se a métrica fosse MWmed (variante que
consideramos antes), o gap de até 40× entre subsistemas (SE cheio ~110k
MWmed vs NE seco ~600) achataria N/NE em escala compartilhada. Nesse caso
o certo seria eixo independente por gráfico. A escolha de eixo segue a
natureza da métrica, não o dataset.

**Regra:** escala compartilhada **se** a unidade for intrinsecamente
comparável (%, fator, índice normalizado). Escala automática por gráfico
pra unidades absolutas (MW/MWh/MWmed) com gap grande entre séries.

**Exposição no DataFrame:** `ena_mwmed` e `ena_armazenavel_mwmed` continuam
no schema long-form retornado por `load_ena()` — podem ser expostos no
futuro via toggle se surgir demanda. Hoje a UI plota apenas `ena_mlt_pct`.

**Export CSV ENA:** colunas com nomes curtos (`SIN`, `SE`, `S`, `NE`, `N`)
sem sufixo de unidade. **Valores em % MLT** — unidade implícita no filename
`ena_*.csv` e na primeira nota explicativa acima da aba. Esse é um trade-off
deliberado pra manter consistência visual com o export dos Reservatórios.

### 5.6 Refatoração `_render_period_controls()`

PLD tinha atalhos inline com helpers locais (`_preset_ativo`, `_btn_atalho`,
CSS injetado no bloco). Reservatórios replicou o mesmo padrão.

**Extraído em função top-level** no módulo, recebe `presets`, `session_keys`,
`key_prefix`, `min_d/max_d`. CSS do botão `type="primary"` (amarelo) movido
pro bloco CSS global (disponível em todas as abas).

PLD encurtou ~70 linhas → 12 linhas. Reservatórios reutiliza a mesma
função com presets diferentes (1A/3A/5A/10A/Máx).

**Regra decorrente:** se uma aba nova precisar de controles de período,
reusar `_render_period_controls` com próprios presets e prefixos.

### 5.8 KPIs ENA ponderados (não média simples de %)

Cada gráfico da aba ENA/Chuva tem 4 KPIs acima: Último mês, Últimos
3 meses, Últimos 12 meses, Período úmido atual.

**Fórmula (helper `_compute_kpi_mlt_pct` em `app.py`):**
```
KPI(sub, janela) = sum(ena_mwmed[sub, janela]) / sum(mlt_abs[sub, janela]) × 100
```
`mlt_abs` é derivada linha a linha: `ena_mwmed / (ena_mlt_pct / 100)` —
ONS não publica MLT absoluta direto no dataset.

Pra `SIN`: agrega sobre os 4 subsistemas base (N+NE+S+SE). **Não usa** a
linha SIN pré-calculada nem média simples dos percentuais.

**Por que não média simples:** percentuais não somam/mediam linearmente.
Um subsistema em 200% e outro em 50% não cancela pra 125%, porque as MLTs
absolutas dos dois podem ser 10× diferentes. Ponderação pela MLT absoluta
é matematicamente consistente com a série temporal SIN já calculada em
`_compute_ena_sin_aggregate` (`data_loader.py`). Mesma lógica do SIN EAR
(decisão 5.3).

**Janelas ancoradas na ÚLTIMA DATA do dataset**, não no filtro de período.
Resultado: KPIs ficam estáveis quando o usuário mexe no range dos gráficos
— KPIs mostram "estado atual" do subsistema, gráfico mostra histórico
exploratório.

### 5.9 Modo "Data base + janela" na Horária (Geração)

**Decisão:** em Geração com granularidade=Horária, usar 1 `date_input`
"Data base" + presets de janela (1D/7D/30D/90D), em vez dos 2
`date_input` (data_ini, data_fim) usados nas outras granularidades.

**Razão:** em Horária, "ver 1 dia específico" exigia setar
`data_ini == data_fim` no modo range — fricção desnecessária. "Data
base + janela" é a operação natural do usuário ("ver as últimas N
horas terminando em X").

**Implementação:** helper `_render_period_controls_horaria` (gêmeo de
`_render_period_controls`). Keys session_state: `gen_data_base` (date)
+ `gen_horaria_window_dias` (int). Pós-helper, o caller deriva
`data_ini = data_base - (window-1) days` e `data_fim = data_base`,
espelhando em `gen_data_ini`/`gen_data_fim` pra preservar coerência ao
voltar pra Diária/Mensal.

### 5.10 Geração: gráfico único com dropdown vs. 5 gráficos empilhados

**Decisão:** aba Geração usa **1 gráfico único** com dropdown de
submercado (default SIN). KPIs e gráfico seguem o dropdown; export CSV
mantém os 5 subsistemas.

**Razão:** versão inicial usava 5 gráficos empilhados (padrão
Reservatórios/ENA). Em Horária/90D = 8.640 pontos × 5 stacks → render
muito lento. Reverter pra 1 gráfico reduz custo em ~5×. **Tela ≠ CSV
por design**: tela mostra o que o usuário está olhando, CSV mantém os
5 pra research/análise externa.

**Regra decorrente:** granularidades temporais densas
(horária/diária/mensal × anos) usam gráfico único com dropdown.
Granularidades agregadas leves (ex: "Dia Típico" = 24 pontos × 5
subsistemas = 120 pts total) podem usar 5 empilhados sem reintroduzir
lentidão (ver Sessão 2 do roadmap em `docs/sessao_geracao_status.md`).

### 5.11 Sentinela `_gen_dataset_max` (não `gen_data_ini`) como heurística de "1ª visita"

**Decisão:** em blocos que precisam saber "esse código já rodou pelo
menos 1× na sessão" (ex: reset de defaults), usar uma sentinela
**setada SÓ por aquele bloco** — não uma key gerenciada por widget ou
derivada.

**Bug que motivou:** o reset block da Geração usava
`"gen_data_ini" not in st.session_state` como sentinela. Mas em
Horária, `gen_data_ini` é DERIVADO pós-helper de
`gen_data_base`/`window`. No INÍCIO de cada render Horária, a key
ainda não existia → reset disparava → popava `gen_data_base` →
preset clicado revertia pra default. Bug invisível na análise estática,
descoberto via debug `st.write` em runtime.

**Fix:** trocar pra `"_gen_dataset_max" not in st.session_state`.
`_gen_dataset_max` é setada SÓ pelo próprio reset block, no MESMO
momento em que ele faz seu trabalho. Sentinela confiável.

**Regra:** uma sentinela boa atende a 3 critérios:
1. Setada SÓ pelo bloco que ela protege.
2. Setada na MESMA execução em que o resto do bloco roda (atomicidade).
3. Nome distinto (prefixo `_` ou similar) pra não colidir com keys de
   widget/usuário.

### 5.12 Flag intermediário pra modificar session_state de widget instanciado

**Decisão:** quando um botão (ou outro evento) precisa alterar a key
de um **widget já instanciado** no mesmo render (ex: trocar
`gen_granularidade` a partir do botão "Ver curva horária deste dia"),
usar **flag intermediário** consumido no início do próximo render —
nunca tentar setar a key direto.

**Bug que motivou:** o botão tentava `session_state["gen_granularidade"] = "Horária"`
direto. Streamlit lança `StreamlitAPIException`: "session_state.X
cannot be modified after the widget with key X is instantiated."

**Padrão correto:**

```python
# Topo do bloco da aba (ANTES do selectbox ser instanciado):
if st.session_state.pop("_gen_force_horaria", False):
    st.session_state["gen_granularidade"] = "Horária"

# selectbox renderizado depois — lê o valor já atualizado.
granularidade_gen = st.selectbox(..., key="gen_granularidade")

# ... bloco com botão (depois do selectbox):
if st.button("Ver curva horária"):
    st.session_state["_gen_force_horaria"] = True
    # Outras keys NÃO bound a widgets podem ser setadas direto:
    st.session_state["gen_data_base"] = data_fim_gen
    st.rerun()
```

`pop()` consome o flag de forma atômica (lê + remove). A key do flag
deve ter prefixo `_` pra distinguir de state "real".

### 5.13 Inits separados quando widget pode escrever `None` na key

**Decisão:** quando múltiplas keys são inicializadas juntas no mesmo
bloco (ex: `gen_data_base` e `gen_horaria_window_dias` no init de
Horária), separar em `if`s independentes — pra que reinicializar uma
não destrua o valor da outra.

**Bug que motivou:** `st.date_input` em Streamlit 1.56 pode escrever
`None` em `session_state[key]` durante alguns reruns. Quando o init
detectava `gen_data_base` ausente (ou `None` com `not get(...)`)
e RESETAVA AMBAS as keys juntas, o `gen_horaria_window_dias` recém
clicado (ex: 7) era zerado pra 1.

**Fix:**
```python
# Antes (errado — reinicializa ambos juntos):
if not st.session_state.get("gen_data_base"):
    st.session_state["gen_data_base"] = ...
    st.session_state["gen_horaria_window_dias"] = 1

# Depois (certo — checks independentes):
if not st.session_state.get("gen_data_base"):
    st.session_state["gen_data_base"] = ...
if "gen_horaria_window_dias" not in st.session_state:
    st.session_state["gen_horaria_window_dias"] = 1
```

Bonus: usar `not get()` (cobre ausência E `None`) na key que pode ser
escrita pelo widget; usar `"X" not in state` (só ausência) na key que
só é escrita por código nosso.

### 5.14 Auto-ajuste de período ao trocar pra granularidade incompatível ⚠ SUPERADA pela 5.20 + 5.24

> **Status:** histórico/superada. Cobertura distribuída em 2 decisões
> sucessoras:
> - **5.20** (defaults por granularidade via reset block unificado)
>   cobre TODAS as TRANSIÇÕES com defaults intencionais — Mensal
>   default 12M já evita o caso < 2 pontos sem workaround pontual.
> - **5.24** (st.stop educativo) cobre o caso de SELEÇÃO MANUAL
>   curta DENTRO do modo Mensal (date_inputs editados pra <60d),
>   que a 5.20 não pega — guard com warning + stop em vez de
>   auto-ajuste silencioso.
>
> Código antigo (auto-ajuste Mensal linhas 2243-2252) removido na
> Sessão 1.5b. Mantida aqui como referência da decisão original.

**Decisão original:** ao trocar pra uma granularidade onde o período
herdado geraria <2 pontos no resample, **auto-ajustar** o período pra
um default razoável da nova granularidade.

**Caso concreto:** trocar de Horária 1D pra Mensal mantém
`data_ini == data_fim` (1 dia). Mensal resample MS = 1 ponto → guard
`<2 pontos` dispara. UX ruim — usuário não entende por que Mensal
"não funciona".

**Implementação original** (substituída pela 5.20):
```python
if granularidade_gen == "Mensal" and (data_fim - data_ini).days < 60:
    st.session_state["gen_data_ini"] = max_d_gen - timedelta(days=90)
    st.session_state["gen_data_fim"] = max_d_gen
```

Aplicado **ANTES** do `_render_period_controls` ser chamado, pra
respeitar a regra 5.12 (não modificar key de widget instanciado).

### 5.15 Disk-cache de parquets ONS (Fix #3 da Sessão 1.5)

**Decisão:** datasets ONS pesados (>10MB consolidado) ganham camada
adicional de cache em disco entre `@st.cache_data` em-memória e o
download HTTP. Persiste o DataFrame pós-normalize/concat/sort em
parquet local.

**Caso concreto:** `load_balanco_subsistema` consolida 27 anos × 6,7M
linhas. Sem disk-cache, 1ª sessão de cada usuário paga ~60s pra
download + normalize. Com disk-cache hit: ~1-2s (leitura parquet
local). 11× redução em cold-starts subsequentes.

**Path com cascade + `lru_cache`:**

```python
@functools.lru_cache(maxsize=1)
def _get_balanco_disk_cache_path() -> Path | None:
    candidates = [
        Path.home() / ".cache" / "dashboard-setor-eletrico",
        Path(tempfile.gettempdir()) / "dashboard-setor-eletrico",
    ]
    for d in candidates:
        try:
            d.mkdir(parents=True, exist_ok=True)
            test = d / ".write_test"
            test.touch()
            test.unlink()  # Confirma escrita real (mkdir pode passar
                           # em FS read-only se path já existe)
            return d / "balanco.parquet"
        except Exception:
            continue
    return None  # Ambos read-only → disk-cache desabilitado
```

**Por que cascade:** `Path.home()/.cache/` é o ideal (segue convenção
XDG, persiste entre restarts do app). `tempfile.gettempdir()` é
fallback garantido em qualquer SO. No Streamlit Cloud, `Path.home()`
resolve em `/home/appuser/.cache/` — funciona durante lifetime do
container, some em re-deploy.

**Por que `lru_cache(maxsize=1)`:** o resolver roda em
`is_balanco_cache_fresh()`, leitura e escrita — sem cache, retentaria
mkdir+write_test em cada chamada. Como o path não muda no lifetime do
processo, cachear é seguro.

**TTL:** mtime do arquivo > (now - 6h). Alinhado com
`@st.cache_data(ttl=60*60*6)` externo — sem hash do conteúdo
(redundante).

**Degradação graciosa:** todas as operações em try/except amplo —
falhas vão pra `_debug_erros` mas não interrompem o load. Cobertura:

| Cenário | Comportamento |
|---|---|
| `home/.cache` writable | usa primário |
| `home/.cache` read-only | testa `/tmp`, usa se OK |
| Ambos read-only | retorna None, `is_balanco_cache_fresh()` sempre False, IO no-op silencioso. Load continua via download HTTP. |
| Parquet corrompido na leitura | exception capturada, refaz download |
| Disco cheio na escrita | exception capturada, df retornado normalmente |

**Helper público pra UI:** `is_balanco_cache_fresh() -> bool` exposto
de `data_loader`, permite a aba escolher mensagem de spinner antes do
load (Fix #4 — light vs pesado).

**`clear_cache()` estendido:** unlinks o parquet também — garante que
"Atualizar" sempre força download fresh, não só invalida cache em-memória.

**Quando aplicar a outros loaders:** se o tempo de cold-load passar
de ~10s e o dataset consolidado for >10MB, vale replicar o padrão.
Hoje só o balanço justifica (60s, 60MB consolidado). EAR (~900KB) e
ENA (~2MB) ficam só com `@st.cache_data` externo.

### 5.16 Sentinela de reset estendida com keys individuais

**Decisão:** quando o reset block usa uma sentinela do tipo
`_dataset_max` pra detectar "1ª visita / dataset mudou", **estender
a condição pra também disparar quando keys individuais críticas
estão ausentes**, não só quando a sentinela está.

**Bug que motivou:** `KeyError 'gen_data_ini'` no Cenário 3 da Sessão 1.5
(clicar Atualizar com sessão que tinha passado por Horária). Causa:
**widget-state cleanup do Streamlit (≥1.30)** — quando um widget com
`key="X"` não é instanciado em algum rerun (ex: usuário foi pra
Horária e o helper `_render_period_controls` não foi chamado), o
Streamlit pode descartar `st.session_state["X"]`. Sentinela
`_gen_dataset_max` ficou em state mas `gen_data_ini`/`gen_data_fim`
não — reset não disparava, leitura subsequente quebrava.

**Fix** (`app.py:2091-2103`):

```python
if (
    "_gen_dataset_max" not in st.session_state
    or st.session_state.get("_gen_dataset_max") != max_d_gen
    or st.session_state.get("_gen_dataset_min") != min_d_gen
    or "gen_data_ini" not in st.session_state   # widget cleanup
    or "gen_data_fim" not in st.session_state   # widget cleanup
):
    # ... seta tudo do zero ...
```

**Por que combinar com sentinela em vez de só checar keys individuais:**
em modo Horária, `gen_data_ini` é DERIVADO pós-helper de
`gen_data_base`/`window` — usar SÓ a key como sentinela faria o reset
disparar em todo render Horária e popar `gen_data_base` (regressão do
bug §3.2 da Sessão 1, decisão 5.11). A combinação `sentinela OR
key_ausente` cobre os dois casos: 1ª visita real (sentinela ausente)
+ widget cleanup (key específica ausente).

**Trade-off:** se Streamlit descartou widget-state, user perde
customização de período (volta pro default). Aceitável — a perda já
ocorreu, estamos só detectando.

**Quando aplicar em outros lugares:** qualquer aba que usa
`st.session_state["X"]` (brackets, sem `.get()` fallback) lendo de
key que é ALSO widget-state de `st.date_input`/`st.text_input` etc.
Se a aba alterna entre 2+ helpers que instanciam widgets diferentes
(ex: Geração com `_render_period_controls` vs
`_render_period_controls_horaria`), o cleanup pode ocorrer.

**Refinamento importante (decisão 5.19):** se a aba ALTERNA entre
modos onde widgets diferentes ocupam o mesmo papel (Diária/Mensal usa
`st.date_input` com keys X e Y; Horária usa outro layout sem essas
keys), a sentinela estendida precisa **EXCLUIR o modo onde o cleanup
é normal**. Sem isso, o reset dispara em todo rerun do modo
alternativo. Ver 5.19 abaixo.

**Extensão posterior (Sessão 1.6) — keys PRESENTES com valor inválido:**
A checagem de "ausência" da sentinela 5.16 cobre cleanup TOTAL
(ambas keys descartadas) ou PARCIAL (uma ou outra). Mas Streamlit
também tem um modo de falha mais sutil: descarta `gen_data_ini`,
mantém `gen_data_fim`, e quando o `st.date_input("Data inicial",
key="gen_data_ini")` é re-instanciado SEM `value=`, recria a key com
default clamped pra `max_value` (= `max_d_gen`). Resultado:
`gen_data_ini` reaparece no state com valor `== gen_data_fim`. As 2
keys ficam **PRESENTES**, mas o range é DEGENERADO. A 5.16 (que checa
só ausência) não pega.

**Diagnóstico em runtime (Sessão 1.6):** debug `st.write` injetado
em 3 pontos do flow comparando state antes/depois da navegação
mostrou: `gen_data_ini` mudava de `2026-01-23` (3M aplicado) pra
`2026-04-23` (max_d) ao voltar de outra aba; `gen_data_fim` ficava
estável em `2026-04-23`. Ambas presentes → reset não disparava →
guard `<2 pontos` (Diária) ou `<60d` (Mensal) ativava de novo.

**6º gatilho do reset block (`app.py:2261-2266`):**

```python
or (
    not em_horaria
    and "gen_data_ini" in st.session_state
    and "gen_data_fim" in st.session_state
    and st.session_state["gen_data_ini"]
        >= st.session_state["gen_data_fim"]
)
```

**Por que `>=` (não só `==`):** cobre `data_ini == data_fim` (caso
reportado) e `data_ini > data_fim` (defesa adicional, embora
improvável dado os widgets validarem).

**Por que mantém `not em_horaria`:** em Horária, `gen_data_ini ==
gen_data_fim` é LEGÍTIMO quando window=1 (data_base + 0 dias). Ver
5.19 — mesmo padrão de exclusão por modo.

**Refinamento (Fase E.12):** Defensivos `state.get(key, default)` nas
leituras de chave (em vez de `state[key]`) cobrem o caso de cleanup
mid-session sem regredir o bug E.5 (que motivou a remoção do `cond_a`
no `precisa_reset`). Aplicação: 4 leituras de
`termico_sistema_data_ini`/`_data_fim` (linhas 3388, 3389, 3460, 3461)
com defaults Mensal 12M. Escritas continuam com `[...]` direto
(não dão KeyError).

**Refinamento (Bug 2 / Despacho Termico - 07/05/2026, commit
`7b57925`):** o 6o gatilho da extensao Sessao 1.6 precisa de
ADAPTACAO quando o cleanup do Streamlit DELETA a key (em vez de
deixar valor stale).

- **Caso original (Geracao):** `gen_data_ini` reaparece no state com
  valor degenerado `== gen_data_fim`. As 2 keys ficam PRESENTES,
  mas o range eh zero. Gatilho original detecta via `data_ini >=
  data_fim`.
- **Caso novo (Despacho Termico, ao trocar sub-view Eneva <-> Sistema):**
  `termico_<sub>_data_ini` e/ou `_data_fim` sao DELETADAS, nao
  reaparecem stale. O gatilho original (`"X" in state AND state[X]
  >= state[Y]`) falha porque `"X" in state` retorna False.

Adaptacao - trocar AND por OR no gatilho, usando curto-circuito
pra proteger contra KeyError quando a key esta ausente:

```python
or (
    gran_atual not in ("Trimestral", "Horario")
    and (
        "termico_<sub>_data_ini" not in st.session_state
        or "termico_<sub>_data_fim" not in st.session_state
        or st.session_state["termico_<sub>_data_ini"]
            >= st.session_state["termico_<sub>_data_fim"]
    )
)
```

Aplicado em Sistema (`app.py:3322`) e Eneva (`app.py:4229`).
Trimestral excluido (datas informativas, filter usa anos+LTM).
Horario excluido (`data_ini == data_fim` eh design legitimo
single-day, decisao 5.46).

**Licao:** o cleanup do Streamlit pode se manifestar em 2 modos
distintos - keys deletadas (Despacho Termico, mais comum quando
widgets de uma sub-view nao instanciam por turnos consecutivos) ou
keys recriadas com valor clamped (Geracao, quando widget
re-instancia sem `value=` apos cleanup). Diagnosticar via debug
`st.write` em runtime eh essencial pra distinguir os 2 casos
antes de aplicar fix.

### 5.17 Dois eixos: range do dataset vs período visível

**Decisão:** quando o tamanho do dataset carregado é decisão própria
(ex: balanço da Geração, default 15a vs completo sob demanda), **separar
explicitamente em 2 eixos ortogonais** os controles de UI:

1. **Range do dataset** = "quanto histórico carregar". Controlado por
   estado *sticky* na sessão (ex: `gen_historico_completo: bool`),
   alterado via ação explícita do usuário (modal de confirmação).
   Default conservador (15 anos cobre 95% dos usos).
2. **Período visível** = "qual slice mostrar do que está carregado".
   Controlado pelos presets (1M, 3M, ..., Máx) + date inputs, dentro
   do range disponível.

**Não misturar.** O preset "Máx" navega ao mínimo *do range carregado*,
não força carregar mais. Quem quer expandir o range usa o botão
separado "Carregar histórico completo".

**Justificativa:**
- Performance: 99% dos usos não precisam dos 11 anos antigos. Carregar
  por padrão é ~25s vs ~15s — custo dobrado pra benefício raro.
- UX: clicar "Máx" é uma operação navegacional barata. Se ela
  silenciosamente disparasse "carregar mais 11 anos + esperar 25s",
  seria surpresa ruim.
- Modelo mental: "navegar dentro do que tenho" e "buscar mais dados"
  são ações conceitualmente distintas — refletir isso na UI é
  honesto.

**Implementação na Geração (Sessão 1.5b):**

```python
# Loader recebe a flag, @st.cache_data trata como key
@st.cache_data(...)
def load_balanco_subsistema(incluir_historico_completo: bool = False):
    ...

# Disk-caches separados por variante (via fábrica _make_disk_cache_helpers)
_make_disk_cache_helpers("balanco_15anos")
_make_disk_cache_helpers("balanco_completo")

# UI:
historico_completo_gen = st.session_state.get("gen_historico_completo", False)
df_gen = load_balanco_subsistema(incluir_historico_completo=historico_completo_gen)

# Botão de expansão é separado dos presets de período
if st.button("📈 Carregar histórico completo (2000-2010)"):
    _confirmar_historico_completo_gen()  # @st.dialog
```

**`clear_cache()` reseta `gen_historico_completo`:** "Atualizar"
semanticamente significa "começar do zero", não preservar escolhas
que forçariam re-download silencioso. Coerente com o eixo da decisão.

**Aplica a outros datasets pesados:** se Reservatórios/ENA crescerem
muito (improvável — são pequenos), o mesmo padrão se aplica. Hoje
ambos cabem em 15a-equivalente sem dor (dataset consolidado < 5MB).

### 5.18 Backup paralelo pra widgets selectbox sujeitos a cleanup

**Decisão:** keys de `st.selectbox` que precisam preservar valor entre
ciclos de rerun pesado (load >5s + clear_cache + navegação entre abas)
ganham um backup paralelo em key NÃO widget-state. Defesa preventiva
contra widget-state cleanup do Streamlit, mesmo padrão da 5.16 que
cobriu `st.date_input`.

**Bug que motivou (Sessão 1.5b):** após "Atualizar" na sidebar com
Geração+Mensal+histórico completo, dropdown visual mostrava "Mensal"
mas variável `granularidade_gen` lida pelo código vinha como "Diária".
Resultado: presets de Diária renderizam, gráfico Diária, mas user vê
"Mensal" no dropdown. Workaround manual era clicar no dropdown e
reselecionar o valor.

**Causa raiz:** Streamlit ≥1.30 descarta widget-state de keys cujo
widget não foi instanciado em algum rerun intermediário. No ciclo
pesado pós-"Atualizar" (clear_cache → rerun → load 15s → re-render),
há janela onde `gen_granularidade` pode sumir do state. Widget recria
com default (`index=1` → "Diária"). DOM do navegador pode mostrar o
valor antigo cached por 1+ frame até o re-render terminar, criando
divergência visual vs lógica.

**Padrão de fix:**

```python
# Antes do selectbox:
_BACKUP_KEY = "_<sufixo>_backup"
if (
    "<key_widget>" not in st.session_state
    and _BACKUP_KEY in st.session_state
):
    st.session_state["<key_widget>"] = st.session_state[_BACKUP_KEY]

# Selectbox normal:
valor = st.selectbox(..., key="<key_widget>")

# Pós-widget, atualiza backup:
st.session_state[_BACKUP_KEY] = valor
```

3 critérios da key de backup:
1. Prefixo `_` distingue de widget keys do user.
2. NÃO é widget-state — escrita só pelo nosso código → sobrevive cleanup.
3. Mantida sincronizada com o widget pós-render (sempre escrita ao final).

**Quando aplicar em outras abas:** preventivamente quando há sintoma
similar (dessincronia visual de selectbox após interação pesada). Não
necessariamente em TODOS os selectbox — só os que estão em ciclos
suscetíveis. Hoje aplicado em `gen_granularidade` e `gen_submercado`
da Geração, mas o radio `aba` da sidebar e os selectbox do PLD
(`selectbox_granularidade`) também são candidatos se o bug aparecer.

**Trade-off:** ~5 linhas extras por widget. Aceitável em troca de
robustez. Não é gratuito — em widgets de listas dinâmicas o backup
pode "lembrar" valor que não é mais opção válida; nesse caso, validar
antes de restaurar.

### 5.19 Sentinela do reset com EXCEÇÃO por modo (refinamento da 5.16)

**Decisão:** quando a sentinela do reset block (5.16) inclui keys
individuais ausentes E a aba tem modos onde essas keys NÃO são
widget-state (cleanup é normal/esperado naquele modo), **excluir o
modo do check** via `if mode == ... not em_modo_alternativo and ...`.

**Bug que motivou (Sessão 1.5b pós-implementação):** após aplicar a
5.16 estendendo a sentinela do reset com `gen_data_ini`/`gen_data_fim`
ausentes, descobrimos que botões 7D/30D/90D na Horária não respondiam.
Apenas 1D (default) funcionava. Causa: `gen_data_ini` e `gen_data_fim`
são widget-keys do `st.date_input` em `_render_period_controls`
(Diária/Mensal). Em Horária, esses widgets NÃO são instanciados —
helper Horária usa `_render_period_controls_horaria` com layout
diferente. Streamlit faz cleanup das keys → reset dispara em TODO
rerun Horária pós-cleanup → popa `gen_horaria_window_dias` → init
re-seta pra 1 → window do clique 7D é perdido.

**Fix** (`app.py:2170-2189`):

```python
em_horaria = (
    st.session_state.get("gen_granularidade") == "Horária"
)
if (
    "_gen_dataset_max" not in st.session_state
    or st.session_state.get("_gen_dataset_max") != max_d_gen
    or st.session_state.get("_gen_dataset_min") != min_d_gen
    or (
        not em_horaria
        and (
            "gen_data_ini" not in st.session_state
            or "gen_data_fim" not in st.session_state
        )
    )
):
    # ... reset ...
```

**Por que funciona:**
- Em Diária/Mensal: `em_horaria=False` → checa keys individuais →
  cobre o cenário do bug do Cenário 3 (Sessão 1.5).
- Em Horária: `em_horaria=True` → NÃO checa keys individuais → reset
  só dispara por mudança de dataset (`_gen_dataset_max/_min`) ou 1ª
  visita absoluta. Window preservada.
- Sentinela `_gen_dataset_max` continua autoritativa em ambos modos.

**Por que é seguro em Horária:**
- `gen_data_ini`/`gen_data_fim` em Horária são **derivadas** das
  linhas 2232-2233 (espelhadas a partir de `data_base`/`window`).
  Sempre re-escritas no fim do bloco Horária. Não há dependência de
  leitura — se sumirem, são re-criadas no rerun seguinte.
- Cenário "sessão antiga, sentinela presente, gen_data_ini perdida"
  em Horária deixa de auto-recuperar via reset, mas as próprias
  linhas de espelhamento recuperam.

**Lição aprendida:** sentinelas estendidas devem considerar TODOS os
modos da aba antes de assumir que "key ausente = sintoma de bug".
Nem sempre é — em modos alternativos pode ser comportamento normal.
Quando o reset tem efeitos colaterais (popa outras keys), uma falsa
detecção custa caro.

**Aplicação ao 6º gatilho (Sessão 1.6):** a checagem
`gen_data_ini >= gen_data_fim` (range degenerado, extensão da 5.16)
herda o mesmo padrão `not em_horaria` — em Horária com window=1,
`data_ini == data_fim` é estado válido derivado de `data_base + 0`,
não bug. Sem a exceção, o reset disparava em todo render Horária 1D
e popava `gen_horaria_window_dias` (mesma classe de regressão do bug
do Cenário 3 da Sessão 1.5).

**Padrão genérico aplicável:**

```python
em_modo_X = <condicao>  # ex: granularidade=="Horária"
if (
    sentinela_principal_invalida
    or (
        not em_modo_X
        and (key_widget_modo_diferente_ausente)
    )
):
    reset()
```

### 5.20 Defaults por granularidade + reset block unificado

**Decisão:** quando uma aba tem múltiplos modos (granularidades) com
controles de período distintos, **cada modo tem seu default próprio
de período**, aplicado por um reset block unificado que dispara nos 5
gatilhos abaixo. Substitui blocos espalhados de "ao sair do modo X" +
auto-ajuste pontual + reset de 1ª visita.

**Defaults na aba Geração:**

| Modo | Default | Comentário |
|---|---|---|
| Diária | 1M | Janela curta cobre análise recente; user expande sob demanda |
| Mensal | 12M | 12 pontos = 1 ano completo, mostra sazonalidade |
| Horária | 1D + data_base = max_d | "Como foi ontem" — uso casual mais comum |

**1ª entrada na aba (sentinela `_gen_dataset_max` ausente): default Horária.**
Pre-selectbox seta `state["gen_granularidade"] = "Horária"` antes do
widget ser instanciado (decisão 5.12). Razão UX: usuário casual
costuma querer ver "agora" não 12 meses de série.

**5 gatilhos do reset block unificado:**

```python
em_horaria = state.get("gen_granularidade") == "Horária"
prev_gran = state.get("_gen_last_gran")
em_transicao = (
    prev_gran is not None and prev_gran != granularidade_gen
)
force_reset = state.pop("_gen_force_reset", False)

if (
    force_reset                                      # 1. clear_cache disparou
    or "_gen_dataset_max" not in state               # 2. 1ª visita absoluta
    or state.get("_gen_dataset_max") != max_d_gen    # 3. dataset mudou (max)
    or state.get("_gen_dataset_min") != min_d_gen    # 4. dataset mudou (min)
    or em_transicao                                  # 5. transição de gran
    or (not em_horaria and (                         # 6. widget cleanup (5.16/5.19)
        "gen_data_ini" not in state
        or "gen_data_fim" not in state
    ))
):
    _aplica_default_periodo_gen(granularidade_gen, min_d_gen, max_d_gen)
    state["_gen_dataset_max"] = max_d_gen
    state["_gen_dataset_min"] = min_d_gen

state["_gen_last_gran"] = granularidade_gen
```

**Helper `_aplica_default_periodo_gen`** (top-level): aplica default
da granularidade passada + popa keys da granularidade alternativa.
Idempotente — chamadas redundantes não causam efeito colateral.

**Flag `_gen_force_reset`** setada por `clear_cache()` em
`data_loader.py`. Cobre o caso "Atualizar sem mudança de dataset"
(gen_historico_completo já era False, dataset não mudou). Consumida
com `pop` no início do reset.

**Detecção de transição via `_gen_last_gran`:**
- `prev_gran is not None` exclui 1ª visita (não é transição, é entrada).
- Atualizado SEMPRE no fim do bloco — independente de reset disparar.

**O que esta decisão SUBSTITUI/CONSOLIDA:**
- 5.14 (auto-ajuste Mensal < 60d) — superada. Default Mensal=12M já cobre.
- Bloco "ao sair de Horária" pop keys — absorvido (helper popa).
- Reset de 1ª visita com 12M-Diária fixo — vira reset com default da gran atual.

**Sem riscos de loop:**
- Reset é idempotente (set mesmo valor 2× → mesmo estado).
- Transição detectada UMA vez — ao final do reset, `_gen_last_gran` =
  atual → próximo render `em_transicao=False`.
- `force_reset` flag consumida com pop — só dispara 1×.

**Quando aplicar em outras abas:** quando uma aba tem 2+ modos com
controles de período diferentes. PLD tem 4 granularidades mas presets
similares (`_render_period_controls` em todas). Reservatórios e ENA
têm 1 modo só. Padrão fica reservado pra Geração por enquanto, mas
a estrutura é generalizável se aparecer caso similar.

**Refinamento (Fase E.5/E.9):** Padrão replicado em modo Trimestral
com edge case "tudo desmarcado" (anos vazios + LTM=False). Edge case
força default LTM=True como fallback (evita state inconsistente onde
nenhum filtro temporal está ativo). Validado em transições reversas
histórico → ano_completo.

### 5.21 KPIs em HTML custom quando o value tem letras mixed-case

**Decisão:** quando o value de um card de KPI precisa exibir uma
string com letras lowercase (ex: `MWmed`, `MWh`, `kWh`), **NÃO usar
`st.metric`** — refatorar pra HTML custom com 2 spans
(`.kpi-value-num` em Bebas Neue pro número, `.kpi-value-unit` em
Inter mixed-case pra unidade).

**Bug que motivou (Sessão 1.6 #4):** os 4 KPIs da aba Geração
(`st.metric("GERAÇÃO TOTAL", f"{...} MWmed")`) renderizavam "MWmed"
como "MWMED". Diagnóstico inicial errado: hipótese era
`text-transform: uppercase` global. Verificação no CSS (`app.py`
linhas 208-219) mostrou que `text-transform: uppercase` está SÓ no
LABEL do `st.metric`, não no VALUE. **Causa raiz:** o CSS Bauhaus
aplica `font-family: 'Bebas Neue'` no VALUE (linha 202), e Bebas
Neue é uma fonte **all-caps por design** — não tem glifos lowercase.
Letras lowercase renderizam como uppercase glyphs visualmente,
independente de qualquer override de `text-transform`.

**Padrão de implementação** (`app.py:2520-2566` na Geração; padrão
análogo já existia na ENA `app.py:1845-1873` por outro motivo):

```python
# CSS: 4 classes (card / label / value-flex / value-num / value-unit)
.gen-kpi-card { background: ...; border: 2px solid #1A1A1A; ... }
.gen-kpi-label { font-family: 'Inter'; uppercase; ... }
.gen-kpi-value { display: flex; align-items: baseline; ... }
.gen-kpi-value-num { font-family: 'Bebas Neue'; font-size: 1.45rem; ... }
.gen-kpi-value-unit {
    font-family: 'Inter';  /* mixed-case OK */
    margin-left: 0.4rem;
    ...
}

# Helper local pra evitar repetir HTML 4×:
def _render_kpi_gen(label, num, unit=""):
    unit_html = (
        f'<span class="gen-kpi-value-unit">{unit}</span>' if unit else ""
    )
    return (
        f'<div class="gen-kpi-card">'
        f'<div class="gen-kpi-label">{label}</div>'
        f'<div class="gen-kpi-value">'
        f'<span class="gen-kpi-value-num">{num}</span>{unit_html}'
        f'</div></div>'
    )

# Uso:
st.markdown(
    _render_kpi_gen("GERAÇÃO TOTAL", "67.890", "MWmed"),
    unsafe_allow_html=True,
)

# Caso especial: % colado no número (sem unit separada):
st.markdown(
    _render_kpi_gen("% RENOV VARIÁVEL", "18,5%"),
    unsafe_allow_html=True,
)
```

**Quando aplicar:**
- KPI com unidade contendo letras lowercase (`MWmed`, `kWh`, `MWh`)
  → HTML custom obrigatório.
- KPI com unidade só símbolo/número (`%`, `°C`, `R$`, números puros)
  → `st.metric` continua OK (Bebas all-caps preserva a aparência).

**Trade-off:** ~30 linhas extras por bloco de KPIs (CSS + helper) vs
`st.metric` puro de 1 linha por card. Aceitável quando há restrição
tipográfica genuína — não aplicar preventivamente em bloco que não
sofre o problema.

### 5.22 Tag compacta de granularidade entre título e gráfico

**Decisão:** quando uma aba tem múltiplos modos (granularidades) que
mudam o significado da unidade ("cada ponto representa X"), renderizar
uma **tag compacta** IMEDIATAMENTE entre o título Bauhaus do gráfico
e o `fig`/`st.plotly_chart`. **NÃO** no bloco geral de notas no topo
da aba.

**Razão:** princípio "informação que descreve o gráfico fica perto do
gráfico". O bloco geral de notas é pra contexto da aba toda
(atualização da fonte, decisões de cálculo, breakpoints históricos).
Texto que muda dinamicamente com a granularidade do gráfico
("Média mensal · MWmed" vs "Média diária · MWmed" vs "Valor horário ·
MWmed") interage visualmente com o gráfico, não com a aba.

**Padrão de implementação** (`app.py:2742-2749` na Geração):

```python
# Definição perto da escolha de granularidade:
tag_granularidade_gen = {
    "Mensal":  "Média mensal · MWmed",
    "Diária":  "Média diária · MWmed",
    "Horária": "Valor horário · MWmed",
}[granularidade_gen]

# Renderização ENTRE título Bauhaus e fig:
st.markdown(título_bauhaus, unsafe_allow_html=True)
st.markdown(
    f'<div style="font-family:\'Inter\', sans-serif; '
    f'font-size:0.85rem; color:#4A4A4A; '
    f'letter-spacing:0.04em; margin:0 0 0.5rem 0;">'
    f'{tag_granularidade_gen}'
    f'</div>',
    unsafe_allow_html=True,
)
fig_c = go.Figure()
```

**Estilo:**
- Inter 0.85rem cinza escuro `#4A4A4A` (BAUHAUS_GRAY).
- **Sem italic** (italic em corpo pequeno fica difícil de ler).
- Letter-spacing 0.04em (leve respiração).
- Texto compacto: `Sujeito · Unidade` (ex: "Média diária · MWmed"),
  não a frase longa "Cada ponto representa o valor X em UNIDADE".
- Margin: 0 acima (cola no título), 0.5rem abaixo (respira antes
  do gráfico).

**Quando aplicar:** abas com modo/granularidade variável que altera
a interpretação dos pontos. PLD (4 granularidades), Geração (3),
candidatos futuros. Reservatórios e ENA têm 1 modo só, não precisam.

### 5.23 Override Bauhaus de st.alert — container externo dita visual

**Decisão:** quando o tema do projeto for **dark**
(`textColor: "#f2f2f2"` em `.streamlit/config.toml`), o
`st.warning`/`st.info`/`st.error`/`st.success` ficam ilegíveis com
seus fundos coloridos default. Override CSS em estratégia
"**container externo dita o visual + descendentes transparentes**".

**Bug que motivou (Sessão 1.6 bonus):** warning de "Mensal precisa de
pelo menos 2 meses" tinha texto branco (do `textColor: #f2f2f2` do
tema) sobre fundo amarelo do warning Streamlit — quase ilegível.

**Padrão de implementação** (`app.py:225-256`):

```css
/* Container externo recebe TODO o visual + margins */
[data-testid="stAlert"] {
    margin-top: 0.8rem !important;
    margin-bottom: 0.4rem !important;
    background-color: #E8E3D4 !important;  /* BAUHAUS_LIGHT */
    border: 2px solid #1A1A1A !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    color: #1A1A1A !important;
}

/* Descendentes ficam TRANSPARENTES — deixam o cream do parent
   passar e matam border/shadow coloridos por tipo (warning amarelo,
   info azul, error vermelho) que vêm dos wrappers internos. */
[data-testid="stAlert"] div,
[data-testid="stAlert"] p,
[data-testid="stAlert"] span,
[data-testid="stAlert"] [data-baseweb="notification"],
[data-testid="stAlert"] [data-testid="stAlertContainer"] {
    background-color: transparent !important;
    border: none !important;
    box-shadow: none !important;
    color: #1A1A1A !important;
}
```

**Por que estratégia "externo + transparente":**
- Streamlit aninha alerts em wrappers internos
  (`[data-baseweb="notification"]`, `[data-testid="stAlertContainer"]`)
  e a borda/sombra colorida por tipo vem **desses** wrappers, não do
  `stAlert` externo. Ataque só ao externo deixa a borda interna
  visível.
- Atacar wrappers internos individualmente é frágil (estrutura DOM
  varia entre versões Streamlit).
- "Externo dita visual + internos transparentes" funciona INDEPENDENTE
  da estrutura — qualquer borda/sombra interna é zerada, qualquer
  fundo interno é transparente, deixando o cream do parent vazar.

**Cor `BAUHAUS_LIGHT` (não BAUHAUS_CREAM):**
- BAUHAUS_CREAM (`#F5F1E8`) é o fundo da página inteira → alert com
  o mesmo tom não destaca, fica "transparente" visualmente.
- BAUHAUS_LIGHT (`#E8E3D4`) é "elementos sutis" no sistema de cores
  do projeto (§3.1) — diferenciação visual sem agredir Bauhaus.

**SVGs/icons preservados:** seletor não inclui `svg`/`path`, então
o ícone do Streamlit (⚠️/ℹ️/❌/✅) mantém cor própria — única
diferenciação semântica que sobra entre tipos de alert.

**Trade-off:** todos os tipos de alert ficam visualmente uniformes.
Diferenciação semântica passa a depender SÓ do ícone. Aceitável
porque (a) alerts são raros no app, (b) consistência > sinalização
forte por cor (não é UI de produção crítica).

### 5.24 st.stop após guards que invalidam o gráfico

**Decisão:** quando um guard mostra `st.warning`/`st.info` em vez do
gráfico, **sempre** seguir com `st.stop()` pra bloquear KPIs e export
CSV junto. Coerência: gráfico inválido = KPIs/export também inválidos.

**Bug que motivou (Sessão 1.6 bonus):** guard `<2 pontos` em Diária
1 dia mostrava `st.info("Selecione pelo menos 2 pontos...")` no lugar
do gráfico, mas KPIs (calculados sobre `pivot_sel.mean()` com 1
ponto) e botão de export CSV continuavam aparecendo. Inconsistente
com o guard Mensal <60d (também na Sessão 1.6) que tem `st.stop()`.

**Razão semântica:** se o gráfico não faz sentido com a seleção
atual, KPIs calculados com a mesma seleção também não fazem.
Export CSV com 1 ponto é tecnicamente válido mas user-confuso —
download de 1 linha não é o uso esperado da aba.

**Padrão de implementação:**

```python
# Pattern: guard ANTES dos KPIs com st.stop() final.
if condicao_invalida:
    st.warning("...")  # ou st.info(...)
    # Opcionalmente: botões alternativos (ex: "Ver curva horária")
    if outro_caso:
        if st.button("..."):
            # ações + rerun (rerun bypassa o stop, OK)
            st.rerun()
    st.stop()  # impede KPIs / gráfico / export

# A partir daqui, render assume condição válida — pode acessar
# pivot_sel.mean() etc. sem checks defensivos.
```

**Onde colocar o guard:**
- ANTES do bloco dos KPIs (não depois). Ordem certa: pivots → guard
  → KPIs → gráfico → export.
- Botões alternativos (ex: "Ver curva horária deste dia" pra Diária
  1 dia) ficam DENTRO do branch do guard, ANTES do `st.stop()`. O
  `st.rerun()` do botão dispara antes do stop ser alcançado.

**Casos atuais com esse pattern (Geração):**
- Mensal `(data_fim - data_ini).days < 60`: warning + stop.
- Diária `len(pivot_sel) == 1`: info + botão "Ver curva horária" + stop.
- Sub sem dados (`pivot_sel is None`): warning + stop (já era assim
  antes da Sessão 1.6, decisão tornou padrão explícito).

**Quando NÃO aplicar:** guards informativos que NÃO invalidam o
gráfico (ex: caption "Granularidade horária com janela longa —
renderização pode levar alguns segundos" em Horária ≥30D). Esses
são avisos de UX, não bloqueios — não levam stop.

### 5.25 "Dia Típico" — granularidade não-temporal via reagregação por hora-do-dia

**Decisão:** quando uma aba precisa expor uma "granularidade" que NÃO
é uma agregação temporal canônica (D/MS/H), mas sim uma reagregação
por dimensão derivada (ex: hora-do-dia), **tratar como modo extra que
reusa a infraestrutura existente**, não como pipeline paralelo.

**Pattern (6 pontos):**

1. `freq_map` ganha entrada apontando pra `None` (mantém o pivot
   horário sem resample temporal).
2. Helper paralelo `_build_<modo>_submercado` que **chama**
   `_build_pivot_submercado` e aplica reagregação extra
   (`groupby(<dimensão>).mean()`).
3. Despacho elegante via variável local antes do loop:
   `_build_pivot = _build_<modo>_submercado if granularidade==X
   else _build_pivot_submercado` — 1 linha vs `if/else` espalhado.
4. Eixo X **categorial** (`xaxis.type="category"`) — preserva ordem
   natural do agrupamento, hovermode unified mostra a string direto
   sem precisar de `hoverformat`.
5. Reset block (5.20) ganha branch novo no `_aplica_default_periodo_gen`
   com default representativo do conceito.
6. Guard mínimo de período via `st.warning + st.stop` (padrão 5.24)
   — proteção contra "média de poucos pontos vira não-típica".

**Implementação Sessão 2 (Dia Típico):**

```python
# 1. freq_map
freq_map = {
    "Horária":    None,
    "Diária":     "D",
    "Mensal":     "MS",
    "Dia Típico": None,
}

# 2. Helper novo (5 linhas)
def _build_dia_tipico_submercado(code):
    pivot_horario = _build_pivot_submercado(code)  # reusa filter+pivot
    if pivot_horario is None or pivot_horario.empty:
        return None
    pivot = pivot_horario.groupby(pivot_horario.index.hour).mean()
    pivot.index = [f"{h:02d}:00" for h in pivot.index]
    pivot.index.name = "Hora"  # vira coluna no reset_index do export
    return pivot

# 3. Despacho elegante
_build_pivot = (
    _build_dia_tipico_submercado
    if granularidade_gen == "Dia Típico"
    else _build_pivot_submercado
)
for code in ORDEM_SUBSISTEMA_GEN:
    pv = _build_pivot(code)
    ...

# 4. Eixo X condicional
_xaxis_gen_dict = dict(title=None, ...)
if granularidade_gen == "Dia Típico":
    _xaxis_gen_dict["type"] = "category"
else:
    _xaxis_gen_dict["hoverformat"] = hover_fmt_gen

# 5. Default no reset block (5.20 estendida)
elif granularidade == "Dia Típico":
    st.session_state["gen_data_ini"] = max(min_d, max_d - timedelta(days=30))
    st.session_state["gen_data_fim"] = max_d
    # pop horária keys

# 6. Guard <7 dias
if (
    granularidade_gen == "Dia Típico"
    and (data_fim_gen - data_ini_efetivo_gen).days < 7
):
    st.warning("Dia típico precisa de pelo menos 7 dias...")
    st.stop()
```

**Default 30D — sweet spot UX:**
- 7D = mínimo defensivo (cobre weekday/weekend).
- **30D = sweet spot** — captura padrão semanal + dilui anomalias de
  1-2 dias específicos.
- 12M = perfil anual (mistura sazonalidade — média de verão+inverno).

**Presets sem "Máx":** descontinuidade estrutural pré-2010 da matriz
elétrica torna 25 anos sem sentido como "perfil típico" — eólica/solar
explodiram pós-2015. Lista: `7D, 30D, 90D, 6M, 12M, 5A`.

**Tag explicativa estendida:** `"Dia típico (média horária do período
selecionado) · MWmed"` — única das 4 tags da Geração que estende a
explicação, porque o conceito não é universal (Mensal/Diária/Horária
são óbvios; "Dia Típico" exige glossário inline).

**O que diverge do flow tradicional (apenas 3 pontos):**
- Eixo X categorial vs temporal.
- vline 29/04/2023 não aplicável (Timestamp não bate em eixo
  categorial — pulada via `if granularidade_gen != "Dia Típico"`).
- Export CSV usa coluna `"Hora"` (string `"00:00"..."23:00"`) em vez
  de `"Data"` (datetime), `gran_slug = "dia_tipico"` no filename.

**O que reusa (sem refator):**
- Filter+pivot+fillna otimizado da Sessão 1.5 (Fix #1, 50× speedup).
- Disk-cache de balanço da 1.5 (5.15) — sem cold-start dobrado.
- KPIs (`pivot_sel.mean()`), tag de granularidade, título Bauhaus,
  lado direito (`_format_periodo_br` cai no branch Diária por
  fallthrough), legenda Plotly, hover dos traces, estrutura geral.

**Trade-off conceitual:** KPIs em Dia Típico calculam média sobre 24
linhas (média da série já-mediada por hora). Conceito útil — "média do
dia típico" — mas user precisa entender que é average-of-averages. Na
prática, com default 30D, é a média típica de **30 dias × 24 horas =
720 valores subjacentes**, então o número converge pro mesmo resultado
de "média do período em Diária".

**Quando aplicar em outras abas:**
- Reservatórios/ENA: candidato natural seria "Mês típico" (12 valores,
  `groupby(index.month).mean()`). Sem demanda hoje.
- PLD: candidato seria "Hora típica do dia útil" vs "Hora típica do
  final de semana" (`groupby([dia_da_semana < 5, hour]).mean()`). Caso
  interessante mas fora de escopo.
- Pattern aplicável em geral: qualquer reagregação `groupby(<dimensão
  derivada>).mean()` sobre dados horários do mesmo dataset, com Plotly
  X categorial preservando ordem natural.

### 5.26 GD descartada via ONS após Fase A da Sessão 3

**Decisão:** a aba Geração mantém **4 fontes** (térmica, hidráulica,
eólica, solar centralizada). Não haverá 5ª faixa de GD/MMGD. A
existência de MMGD na carga pós-29/04/2023 já é comunicada pela vline
+ anotação visual no gráfico — solução suficiente.

**Achado da Fase A** (script `scripts/inspect_gd.py`, sondagem completa
do CKAN ONS — `package_list` 80 entries + `package_search` em "geração
distribuída", "MMGD", "micro minigeração", "fotovoltaica"):

1. **Não existe dataset standalone** de MMGD/GD por subsistema no ONS.
2. **`balanco-energia-subsistema`** (que já usamos) **não tem coluna de
   GD**. Schema 9 colunas em parquets 2024/2025/2026, nenhuma com
   keyword `gd`/`mmgd`/`distribuid`/`micro`/`mini`. `val_gersolar` é
   solar **centralizada** (UFV grande), não MMGD.
3. **MMGD vai embutida na carga** desde 29/04/2023 — confirmado nas
   notes do `carga-energia` (Diária) e `carga-mensal`. Ambas com schema
   minimalista (4 colunas), sem isolar MMGD como componente.
4. **Único dataset com MMGD isolada:** `carga-energia-verificada`
   (semi-horária, por **área de carga**, via API/Swagger). Mapping
   área→subsistema novo + paginação API + risco de cobertura temporal
   curta (não validada). Custo alto vs benefício de uma única série
   adicional no stacked.

**Razão da decisão:**
- A spec original (`docs/aba_geracao_spec.md` §4 antes da revisão) foi
  escrita sobre **hipótese não verificada** ("ONS publica MMGD mensal
  por subsistema"). Premissa errada — Fase A só descobriu ao tentar
  achar o dataset.
- Vline + anotação 29/04/2023 (`app.py:2898`) já comunica visualmente
  que carga pós-essa-data inclui MMGD. Cumpre o objetivo informativo
  sem requerer nova fonte.
- Plano B (carga-energia-verificada) traria custo de integração alto
  (API nova, mapping novo) por um único componente extra — assimetria
  custo/benefício ruim.

**Caminhos reservados pra futuro (NÃO continuação desta aba):**
- **Plano B (ONS `carga-energia-verificada`)**: viável tecnicamente
  mas exige Fase A.2 separada (cobertura temporal, schema, mapping)
  antes de comprometer escopo.
- **Plano C (ANEEL — cadastro MMGD)**: fonte oficial, mensal, por
  consumidor/UC. Mais coerente como **aba dedicada "GD Brasil"** do
  que como faixa do stacked atual. Esforço alto (mensalização +
  mapping estado→subsistema + estimativa de fator de capacidade).

**O que NÃO removemos do código:**
- Stub `load_gd_ons()` em `data_loader.py:1754` — fica como marcador
  histórico. Comentário acima dele descreve a decisão de descarte.
- `scripts/inspect_gd.py` — artefato de descoberta. Vale como
  referência pra futuros que queiram revisitar GD via outra fonte.
- Vline + anotação 29/04/2023 no gráfico — agora é a forma DEFINITIVA
  de comunicar MMGD na carga, não placeholder até "implementar GD".

**Lição aprendida:** specs que assumem existência de dataset externo
sem validar via discovery (Fase A) introduzem risco de retrabalho. O
padrão estabelecido (Reservatórios, ENA, Balanço — todos com Fase A
prévia documentada em `docs/*_research.md`) é o caminho certo.
Validar fonte ANTES de prometer feature.

### 5.27 Presets refletem dados disponíveis (sem preset que vira outro)

**Decisão:** botões de preset de período (1M / 3M / 6M / 12M / 5A /
10A / 15A / Máx) só são oferecidos se o range é REAL no dataset
corrente. **Preset que silenciosamente clamp-a pra outro não é
honesto** — usuário clica "15A" esperando 15 anos, recebe "Máx" sem
feedback visual de que o significado foi degradado. Solução: remover
o preset enganador, e oferecer **tooltip dinâmico no Máx** que
explicita a data inicial real do range disponível.

**Caso que motivou (Sessão 4a — Aba Carga, commit `be88e85`):** as
abas Geração e Carga oferecem 2 estados de range (15 anos default,
completo via `gen_historico_completo` / `carga_historico_completo`
— decisão 5.17). No estado default (~14 anos), o preset "15A" da
granularidade Mensal clampava pra `min_d` real (~01/01/2012) —
visualmente idêntico a clicar "Máx". Usuário ficou confuso.

**Implementação (3 partes):**

1. **Remoção do 15A** (`app.py:3044-3045` Geração; `app.py:3931`
   Carga) — lista Mensal nova nas duas abas: `3M / 6M / 12M / 5A /
   10A / Máx`. Reservatórios/ENA já topavam em 10A, PLD topa em
   12M — não tinham 15A, não foram afetados.

2. **Tooltip dinâmico no Máx** no helper compartilhado
   `_render_period_controls` (`app.py:687-694`):

   ```python
   help_text = (
       f"Máx — desde {min_d.strftime('%d/%m/%Y')}"
       if is_max else None
   )
   if st.button(label, ..., help=help_text):
       ...
   ```

   Aplicado nas 5 abas (PLD, Reservatórios, ENA, Geração, Carga).
   Outros presets (5A/10A) ficam sem tooltip — autoexplicativos.
   **Bug colateral fixado em `d6337ed`:** o `help=` envelopa o
   button num `<div data-testid="stTooltipHoverTarget">`, quebrando
   `.stButton > button` (combinator filho direto). Fix lateral:
   trocar pra `.stButton button[kind]` (descendente, com `[kind]`
   filtrando button interno do tooltip). Não é parte da 5.27, mas é
   consequência direta da introdução do `help=`.

3. **Clamp em `min_d` como defesa em profundidade**
   (`app.py:703-711`):

   ```python
   # Protege qualquer preset futuro contra StreamlitAPIException
   # quando date_input é re-instanciado com value < min_value,
   # mesmo após a remoção do 15A.
   st.session_state[session_key_ini] = max(
       min_d, max_d - timedelta(days=delta)
   )
   ```

   Não dispara em uso normal pós-5.27 (todos os presets cabem), mas
   previne regressão se um preset novo for adicionado e exceder o
   range em algum cenário.

**Trade-off aceito:** perda do "15A" como atalho rápido. Aceitável
porque (a) 15A degenerava pra Máx no dataset default de qualquer
jeito — o atalho era ilusório, (b) usuário que quer expandir pra
2000 tem botão dedicado "Estender histórico para 2000" (decisão
5.17), (c) Máx + tooltip dinâmico cumpre o papel de "ver o range
completo disponível" com transparência.

**Quando aplicar este padrão:**

- Ao adicionar preset novo: validar se o range cabe no dataset
  DEFAULT (não só no estendido). Se vai degenerar pra Máx em
  cenário comum, escolher: cortar o preset OU expandir o default.
- Tooltip dinâmico em qualquer preset cujo significado depende de
  estado runtime (range disponível, modo de granularidade, flag de
  histórico).

**Quando NÃO aplica:**

- Presets curtos que sempre cabem (1M / 3M / 6M / 12M cabem em
  qualquer dataset com >1 ano de histórico) — não precisam de
  tooltip nem cuidado especial.
- Presets com range fixo conhecido, independente de flags (ex:
  "Período úmido atual" da ENA — derivação calculada sobre dataset
  completo, sem variação por estado).

### 5.28 Preset "1D" em granularidade horária do PLD

**Decisão:** quando uma granularidade horária permite seleção de "1
dia específico" como caso de uso frequente (análise de spread
intradiário, perfil de pico/vale), o atalho fica como **preset** —
não como granularidade separada no dropdown. Os 5 presets do PLD
horário são: **1D / 1S / 1M / 3M / Máx**.

**Marcador de "modo single-day" é puro derivativo de runtime:**
`data_ini == data_fim`. Sem session_state dedicada, sem sentinela
extra. Inferência da UI por estado dos dados.

**Helper `_render_period_controls` ganhou parâmetro opcional**
`single_day_preset_label: str | None = None`. Quando passado:
- O preset com esse label é considerado ativo se `data_ini ==
  data_fim` (sobrescreve detecção por `delta_days`, que daria 0 =
  degenerado).
- Os 2 date_inputs ("Data inicial" / "Data final") são substituídos
  por **1 date_input "Dia"** + **1 botão "Último dia"** — mesmas
  larguras de coluna.

**Pattern de execução do botão "Último dia"** (lição da Sessão PLD
1D): o botão é renderizado VISUALMENTE à direita do date_input
(`with cols[n+2]:`), mas sua **chamada de código vem ANTES** do
`st.date_input`. Isso replica o pattern dos botões de preset (que
já estão validados): clique seta `state[session_key_ini] = max_d` +
`st.rerun()`, interrompendo o helper antes do widget date_input ser
instanciado nesse render. No próximo rerun, o widget é instanciado
pela primeira vez com o valor novo. **Sem flag intermediário**
(decisão 5.12 não é necessária aqui) e **sem one-rerun-behind**.

**Anteriormente considerado e descartado** (1ª iteração da Sessão
PLD 1D): granularidade `horario_1d` separada no dropdown. Foi
removida porque conceitualmente "1D" é período (1 dia), não
granularidade. Coerência com 1M/3M/etc.

**Trade-off vs decisão 5.9 (Geração):** lá criamos helper paralelo
`_render_period_controls_horaria` com `data_base + window`. Aqui o
caso é mais simples (sempre 1 dia, sem janela variável), então
parâmetro opcional no helper original é mais barato que duplicar.

**Defesa contra widget cleanup do `data_fim` em single-day mode:**
como o widget "Data final" não é instanciado no single-day, o
Streamlit pode descartar `state["data_fim"]`. Cleanup recovery no
caller PLD: se `data_fim` ausente em state, copia de `data_ini`
(consistente com single-day). Em granularidade não-horária, o
gatilho `range_degenerado_fora_horario` (data_ini == data_fim)
detecta o estado e dispara reset full pra default 90d.

**Sincronização `data_fim ← data_ini` no single-day:** callback
`on_change` do date_input "Dia" copia `state[session_key_ini]` em
`state[session_key_fim]`. Streamlit roda callbacks ANTES do main
rerun, então o filter no próximo render já vê ambas iguais (sem
flash de range de 2 dias).

### 5.29 KPI cards devem ser auto-suficientes e não-redundantes com o gráfico

**Decisão:** KPI cards devem mostrar apenas indicadores
**autocontidos do recorte ativo** (ex: PLD médio, máximo, mínimo,
spread). Comparações temporais (vs ontem, vs ano, vs média móvel)
ficam pra feature dedicada de "comparar com" no futuro — não
misturam no card individual.

**Caso que motivou (Sessão PLD 1D):** durante o design dos KPIs do
PLD horário 1D considerou-se um 5º card "VS MÉDIA DO MÊS" (delta %
entre PLD médio do dia e média do mês calendário). Removido porque:
1. **Denominador móvel:** a "média do mês" inclui o próprio dia
   selecionado, ruído conceitual.
2. **Pouca acionabilidade:** delta % isolado num card não substitui
   ver a curva inteira — o gráfico abaixo já mostra contexto
   temporal.
3. **Redundância visual:** o gráfico do PLD horário acima já
   permite "olhar pro lado" e ver outros dias do mês.

**Aplicação na Sessão PLD 1D:** os 4 cards finais são `PLD MÉDIO
DIA / MÁXIMO (com horário) / MÍNIMO (com horário) / SPREAD`. Todos
derivam SÓ da série de 24 valores do dia selecionado.

**Quando reconsiderar:** se uma feature dedicada "comparar com"
aparecer (ex: aba PLD com modo "comparação multi-dias"), aí faz
sentido ter cards de delta % — mas como produto inteiro daquela
feature, não enxertados num KPI bar de outro contexto.

**Quando NÃO aplica:** indicadores que JÁ SÃO comparações por
definição (ex: "ENA vs MLT" da aba ENA — `ena_mlt_pct`) são
autocontidos quando a comparação faz parte da definição da métrica.
Não são "delta entre 2 leituras independentes".

### 5.30 Display labels separados de variable names

**Decisão:** termos técnicos do setor elétrico brasileiro (SIN, PLD,
BAR, CAIMI, etc.) ficam exclusivamente na camada de UI; código
Python mantém nomes pragmáticos historicamente adotados (`media_br`,
`pld_horario`, etc.). **Camada de display traduz na fronteira do
rendering** — chaves de dict, colunas de DataFrame intermediário,
valores de comparação, variáveis Python NÃO acompanham renomeações
de UI.

**Caso que motivou (sessão pós-PLD 1D):** "Média BR" era termo
informal usado historicamente no app pra denominar a média dos 4
submercados (SE/S/NE/N). ANEEL/ONS/CCEE chamam isso de "SIN"
(Sistema Interligado Nacional) — pediu-se rename pra alinhar com
vocabulário do setor. Surgiu a pergunta: trocar tudo (data + UI)
pra "SIN", ou trocar só a UI?

**Decisão tomada — só UI:**

| Camada | Antes | Depois |
|---|---|---|
| Checkbox header | `"Média BR"` | `"SIN"` |
| Dropdown KPI (display) | `"Média BR"` | `"SIN"` (via `format_func`) |
| Legenda Plotly trace | `name=col` (=`"Média BR"`) | `name=("SIN" if col=="Média BR" else col)` |
| Hover sigla | `"BR"` | `"SIN"` |
| Pill do rodapé | `BR` | `SIN` |
| Mensagens (info/warning) | `"Média BR"` | `"SIN"` |
| Dict `CORES_SUBMERCADO` | `"Média BR"` | `"Média BR"` (mantém) |
| Coluna do pivot | `pivot["Média BR"]` | `pivot["Média BR"]` (mantém) |
| `series_plot.append(…)` | `"Média BR"` | `"Média BR"` (mantém) |
| Comparações `col == …` | `"Média BR"` | `"Média BR"` (mantém) |
| Variáveis Python | `media_br_ultimo`, `mostrar_media`, `is_media` | inalteradas |

**Razão pra não trocar o lado de dado:**

1. `"Média BR"` é chave INTERNA calculada no app — não vem de fonte
   externa (CCEE/ONS). Renomear seria seguro mecanicamente, mas
   força refator simultâneo de 9 ocorrências sem benefício prático.
2. **Histórico do código tem peso:** `media_br` aparece em
   variáveis, helper `_fmt_br()`, comentários antigos. Renomear
   faz código divergir de git blame, PRs antigos e do raciocínio
   sedimentado nas sessões anteriores.
3. **Camada de display é elástica:** se SIN virar outro termo
   amanhã (improvável, mas possível), só o ponto de tradução muda.
   Renomear data layer toda vez é custo recorrente.

**Trade-off aceito:** 9 ocorrências de `"Média BR"` no código
(`app.py:74, 1548, 1737, 1746, 1756, 1809, 1814, 1816, 1826`)
parecem inconsistência com a UI — não são. São camada de dado,
justificável e isolada por construção.

**3 padrões de implementação:**

- **Selectbox com `format_func`:** value interno mantém chave
  pragmática, display via lambda.
  ```python
  st.selectbox(
      ..., options=opcoes,
      format_func=lambda x: "SIN" if x == "Média BR" else x,
  )
  ```
- **Ternário inline** pra strings que vão direto pra Plotly/HTML:
  ```python
  name=("SIN" if col == "Média BR" else col)
  ```
- **Variável de display** quando string interna é interpolada em
  mensagem:
  ```python
  sub_kpis_display = "SIN" if sub_kpis == "Média BR" else sub_kpis
  st.warning(f"Sem dados pro submercado {sub_kpis_display}…")
  ```

**Quando aplicar este padrão:**

- Refactors de nomenclatura puramente visual (rename "amigável",
  padronização de vocabulário do setor).
- Termos técnicos brasileiros do setor (SIN, MWmed, MWmes, MLT,
  EARmax, ENA, MMGD, etc.) que entram no vocabulário do app via UI
  mas não mudam estrutura de dado interna.

**Quando NÃO aplica:**

- Mudanças motivadas por fonte externa (ex: nova versão do dataset
  CCEE muda nome de coluna) — aí o data layer muda pra acompanhar
  a fonte de verdade.
- Renomeação de variável Python motivada por ambiguidade REAL no
  escopo (ex: `df` → `df_carga` quando há 3 dataframes no escopo).
  Ambiguidade no código justifica refactor; aliança com vocabulário
  externo de UI não.

### 5.31 Viz 2 da Carga — ordem da carga líquida (stacked area)

**Decisão:** stacked area com 4 camadas na ordem **solar → eólica →
hidro → térmica** (de baixo pra cima), satisfazendo a equação de
balanço `hidro + termica + eolica + solar ≈ carga − intercambio`.
Renováveis variáveis (solar + eólica) embaixo "abatem" visualmente
da carga total — a altura cumulativa dessas duas camadas marca a
**carga líquida**, evidenciando o que as despacháveis (hidro +
térmica) acima precisam cobrir.

**Caso que motivou (Sessão 4a, Bloco 5):** o bloco original pediu
"decomposição com **ordem da carga líquida**" — termo técnico do
setor que distingue do empilhamento por ordem de despacho real.
Variante alternativa (Variante A no briefing — hidro → térmica →
eólica → solar → intercâmbio em ordem de despacho real) rejeitada
porque:

1. **Não casa com o nome do bloco** — "ordem da carga líquida" tem
   semântica específica.
2. **Redundância com dashboards genéricos do ONS** — empilhamento
   por despacho é o pattern padrão de qualquer painel de geração
   estatística.
3. **Viz 2 deve ser complementar à Viz 1, não redundante** — Viz 1
   já mostra carga total vs líquida como linhas; Viz 2 quebra a
   "área entre" em camadas que explicam o que cobre cada parte.

**Implementação (5 partes):**

1. **Ordem das camadas** (de baixo pra cima): solar → eólica →
   hidro → térmica. Intercâmbio NÃO entra como camada (ver 5.32).

2. **Linha de carga total sobreposta** (`mode="lines"`,
   `dash="dot"`, cor cinza-escuro fino) — evidencia o "fecho" do
   balanço. Em SIN, cola no topo do stack (intercâmbio
   internacional ~0). Em submercado, **gap** entre topo do stack e
   linha de carga = intercâmbio interno (vide 5.32).

3. **Paleta:**

   ```
   solar    = #F6BD16   (BAUHAUS_YELLOW)
   eólica   = #8FA31E   (oliva — coerente com Geração)
   hidro    = #4A6FA5   (azul-hidro)
   térmica  = #A04B2E   (terracota)
   ```

   *Nota: validar contraste do azul-hidro vs `BAUHAUS_BLUE` da Viz
   1 (linha "Carga Total") no render real — se confundir, ajustar
   matiz.*

4. **Dia Típico first-class** — Viz 2 funciona em
   `xaxis.type="category"` (mesmo padrão da Viz 1, decisão 5.25).
   Plotly stackgroup respeita eixo categorial. É onde a **duck
   curve** fica mais legível: ascensão solar das 6-12h, declive da
   térmica nas horas de pico solar, retomada noturna 18-22h.

5. **Vline 29/04/2023 (quebra MMGD)** — mantida por consistência
   com Viz 1 (decisão 5.26). Pulada em Dia Típico (decisão 5.25 —
   eixo categorial não casa com Timestamp).

**Display vs conceito:**

"Ordem da carga líquida" é o **conceito interno de empilhamento** —
a escolha arquitetural de colocar renováveis variáveis (solar+eólica)
embaixo abatendo da carga, e despacháveis (hidro+térmica) em cima
cobrindo o resto. Esse termo é vocabulário de design do projeto, não
jargão público do setor elétrico.

"Composição da carga total" é o **título visível pro usuário** —
linguagem clara em PT-BR coerente com o vocabulário do app.

Aplica o padrão da decisão 5.30 (display labels separados de variable
names): conceito interno mantém termo técnico de design; UI fala
português acessível.

**Trade-off aceito:** "ordem da carga líquida" não é o empilhamento
intuitivo pra quem nunca viu duck curve. Aceitável porque (a) o
glossário/KPIs já introduzem o conceito de carga líquida, (b) a
paleta + a linha de carga sobreposta tornam a leitura óbvia depois
de poucos segundos, (c) usuários técnicos do setor reconhecem o
pattern imediatamente.

**Quando aplicar este padrão:**

- Decomposições de fluxo de energia onde o usuário quer ler a
  **carga líquida diretamente do gráfico** (não como cálculo
  separado).
- Stacked areas onde a posição vertical das camadas conta uma
  narrativa específica (não é arbitrária).

**Quando NÃO aplica:**

- Decomposições por **ordem cronológica de despacho** (ex: curva
  de mérito) — usar Variante A nesse caso.
- Decomposições onde todas as componentes têm o mesmo "papel
  narrativo" (sem distinção variável vs despachável) — ordem
  alfabética ou por magnitude basta.

### 5.32 Intercâmbio: stack-aware híbrido por recorte

**Decisão:** intercâmbio recebe tratamento **condicional ao recorte
de submercado** na Viz 2 da Carga:

| Recorte | Tratamento | Motivo |
|---|---|---|
| **SIN** | Omitido (sem camada, sem linha) | Intercâmbio internacional ~0; mostrar polui sem informar |
| **Submercado individual (SE/S/NE/N)** | Trace `lines` sobreposto com sinal preservado, `dash="dashdot"`, cor `#9B9B9B` (cinza neutro) | Intercâmbio interno é relevante e pode ser positivo ou negativo |

Hover do trace de intercâmbio em submercado explicita o sinal:
`+exportação líquida` / `−importação líquida`.

**Caso que motivou (Sub-bloco 5.1):** Plotly `stackgroup` não suporta
valores negativos no mesmo trace — quebra o empilhamento visualmente
(camada inverte direção, sobrepõe outras). Submercados podem ser
**exportadores líquidos** em janelas específicas (S em períodos
úmidos, SE em meses de carga baixa) — nesses momentos
`intercambio > 0`.

**Estratégias rejeitadas:**

- **C1 — Split em `intercambio_pos` + `intercambio_neg` como camadas
  (ambos absolutizados):** "exportação" como camada empilhada não
  comunica saída do sistema — visualmente confuso, narrativa
  quebrada.
- **C2 — Linha sobreposta SEMPRE (inclusive no SIN):** poluiria o
  SIN com informação irrelevante (intercâmbio internacional ~0).
  Carga cognitiva sem benefício.
- **C3 — Valor absoluto + cor diferente:** perde o sinal — usuário
  não distingue importação de exportação.

**Implicação visual em submercados:** carga total + intercâmbio
sobreposto comunicam o balanço completo:

```
carga ≈ topo_do_stack - intercambio   (com sinal)
```

- `intercambio > 0` (exportação): linha de intercâmbio fica em y
  positivo (acima do eixo zero, abaixo do stack); gap entre topo do
  stack e linha de carga total fica negativo (carga total cola
  dentro do stack ou abaixo do topo) — exportação significa "sobrou
  geração".
- `intercambio < 0` (importação): linha de intercâmbio fica em y
  negativo (abaixo do eixo zero); gap entre topo do stack e linha
  de carga total fica positivo (carga total acima do topo) —
  importação significa "geração local não basta".

Documentar a convenção no glossário da aba.

**Trade-off aceito:** comportamento da Viz 2 muda quando user troca
SIN ↔ submercado. Aceitável porque (a) a mudança é semanticamente
justificada (intercâmbio internacional vs interno são fenômenos
diferentes), (b) o usuário típico da aba Carga é técnico do setor e
reconhece a distinção, (c) alternativa "uniforme" (C2) traria mais
ruído que clareza.

**Quando aplicar este padrão:**

- Decomposições de geração/carga onde o recorte muda a **semântica**
  de uma componente (interno ↔ externo, agregado ↔ desagregado).
- Vizs onde uma série pode ser positiva ou negativa e o **sinal**
  carrega significado (não é só magnitude).

**Quando NÃO aplica:**

- Decomposições onde todas as componentes têm semântica estável
  independente do recorte (ex: Viz 1 com carga total/líquida — ambas
  sempre positivas em qualquer submercado).
- Casos onde a magnitude da componente é ~zero em todos os recortes
  (não justifica trace separado).

**Convenção descoberta empiricamente:**

A convenção de sinal do `intercambio` no dataset ONS
`balanco_subsistema` foi descoberta empiricamente durante a validação
do Sub-bloco 5.5 da Sessão 4a. O sanity check inicial assumia
`carga ≈ stack + intercambio` (fórmula A) e disparou aviso de 27.62%
de desvio em SE × Dia Típico × 5A. Diagnóstico via comparação numérica
das 2 fórmulas candidatas (A: stack+interc, B: stack-interc) revelou
que a fórmula B fecha com ratio 0.00% — confirmando que o dataset usa
a convenção `positivo = saída/exportação`.

**Lição:** convenções de sinal de datasets externos não devem ser
inferidas a partir de nomes de coluna ou estereótipos do setor (ex:
"SE é exportador") — sempre validar numericamente quando o sinal
carrega significado direcional. Mesmo que o pipeline visual pareça
correto (Plotly plota o `y` literal sem interpretar sinal), texto de
hover e cálculos de balanço dependem da convenção certa.

### 5.33 Paleta canônica de fontes de geração

**Decisão:** as 4 fontes de geração elétrica (solar, eólica, hidro,
térmica) têm UMA cor canônica cada, definida em constantes únicas no
topo do `app.py` e aplicadas em todas as visualizações que mostram
fonte como dado:

| Fonte   | Cor       | Constante           |
|---------|-----------|---------------------|
| Solar   | `#F6BD16` | `COR_FONTE_SOLAR`   |
| Eólica  | `#8FA31E` | `COR_FONTE_EOLICA`  |
| Hidro   | `#4A6FA5` | `COR_FONTE_HIDRO`   |
| Térmica | `#A04B2E` | `COR_FONTE_TERMICA` |

**Caso que motivou:** durante validação visual da Viz 2 da Carga,
Nava notou que térmica preto (Geração) ficava como "buraco visual" e
hidráulica azul-Bauhaus (Geração) misturava papel estrutural com
dado. A Viz 2 já usava terracota e azul-hidro mais claro, mais
legíveis. Em vez de manter inconsistência entre abas, consolidou-se
paleta única.

**Razão das escolhas:**

1. **Térmica terracota (não preto):** preto é cor estrutural do
   design Bauhaus do projeto (bordas, eixos, texto principal). Usar
   preto pra dado mistura papéis. Terracota comunica combustão/queima
   — bate com termelétrica.
2. **Hidro `#4A6FA5` (não `BAUHAUS_BLUE` `#2A6F97`):** `BAUHAUS_BLUE`
   é cor estrutural — sidebar, eixos, alguns textos. Usar pra hidro
   confunde com a Viz 1 da Carga ("Carga Total" em azul) e com a
   sidebar. `#4A6FA5` é tom mais claro de azul, dedicado a
   "água/hidro".
3. **Solar e eólica:** já estavam consistentes entre abas, manter.

**Aplicação atual:**

- Aba Geração: 4 fontes.
- Aba Carga Viz 2: 4 fontes.
- Futuras vizs que mostrem fonte de geração: usar as mesmas
  constantes.

**Quando NÃO aplica:**

- Cores estruturais do design system (`BAUHAUS_BLACK`,
  `BAUHAUS_BLUE`, `BAUHAUS_CREAM`, `BAUHAUS_YELLOW`) — essas são pra
  UI, não pra dado.
- Cores de outras dimensões (linhas de carga, intercâmbio, vlines,
  marcadores) — têm critérios próprios.
- Cores de submercado (SE/S/NE/N/SIN) — outra dimensão, outra
  paleta.

**Trade-off aceito:** se um dia o ONS publicar paleta oficial das
fontes, adaptamos. Por enquanto, terracota+azul-hidro foram
calibrados visualmente no contexto do app, não vêm de standard
externo.

### 5.34 Cache versionado pra evitar armadilha de schema cacheado

**Decisão:** o path do cache local de parquets ONS no
`data_loader_curtailment.py` carrega um sufixo de versão
(`.cache/curtailment_v3/` em vez de `.cache/curtailment/`).
Toda mudança no schema do parquet cacheado — coluna nova,
coluna renomeada, mudança de tipo, mudança no cálculo de
campo derivado em `_padronizar()` — exige bump da versão.

**Caso que motivou:** durante a sessão de implementação da aba
Curtailment, ao corrigir o bug de `val_disponibilidade` ausente
(commit `0ff920b`), o cache de parquet existente continuava
retornando DataFrames sem a nova coluna `VAL_DISPONIBILIDADE_MW`.
O loader entrava silenciosamente em fallback baseado em
`val_geracaolimitada` e o cálculo do `FRUSTRADO_MWH` ficava
errado em ~10×, sem nenhum erro visível. Detectar isso custou
tempo. Versionar o path força re-fetch do ONS quando o schema
muda — caches antigos viram órfãos no disco mas não são
consumidos.

**Como aplicar:**

1. Bump `CACHE_DIR = Path(".cache/curtailment_vN")` em
   `data_loaders/data_loader_curtailment.py`.
2. Documentar o bump no commit message do schema-change
   (ex: "bump cache vN→vN+1: adiciona coluna X").
3. Caches antigos (`.cache/curtailment_v<N-1>/...`) ficam no
   disco do dev sem incomodar — limpeza opcional via
   `rm -rf .cache/curtailment_v*` quando convier.

**Quando NÃO aplica:** mudanças que NÃO afetam o conteúdo do
parquet cacheado — alteração só na UI, no `utils_curtailment`,
em CSS, etc. Se em dúvida, bump.

**Trade-off aceito:** primeiro `streamlit run` após bump demora
vários minutos pra re-popular o cache (download dos 12 meses de
parquet do ONS). Aceitável vs o custo de debugar schema stale
silencioso.

### 5.35 Métrica de curtailment alinhada com Power BI ONS público

**Decisão:** o cálculo de % curtailment usa a definição ONS pública
(`% = frustrado_total / (output + frustrado_total)`), não a definição
BBI Utilities (que excluía REL do numerador). A soma das 3 razões
(ENE + CNF + REL) bate exatamente com o total.

**Caso que motivou:** divergência observada entre o dashboard local e
o Power BI oficial do ONS
(https://www.ons.org.br/Paginas/faq_curtailment.aspx). Eólica 6M
(11/2025 a 04/2026): dashboard mostrava 14,85% (BBI), Power BI ONS
mostrava 17,5%. Diferença explicada pela exclusão de REL no numerador
BBI.

**Como aplicar:** `calcular_pct_curtailment` e `serie_temporal` em
`utils/utils_curtailment.py` somam todas as razões (CNF + ENE + REL)
no numerador. Decomposição por razão usa o mesmo denominador
(geração potencial), garantindo soma consistente.

**Quando NÃO aplica:** se análise específica exigir métrica financeira
de "perda não-ressarcível" (estilo BBI Utilities), calcular
separadamente — não substituir a métrica pública. REN 1030/2022 dá
tratamento detalhado de ressarcimento que não está implementado
neste dashboard.

**Trade-off aceito:** perda da semântica "perda financeira do gerador"
(BBI). Ganho de aderência à fonte oficial pública.

### 5.36 Default por granularidade no reset block (PLD)

**Decisão:** o reset block do PLD aplica default DIFERENTE conforme
granularidade ativa. Constante `_PLD_DEFAULTS_POR_GRANULARIDADE`
mapeia gran → (modo, valor):
- `"horario"` → `("single_day", None)` — `data_ini = data_fim = max_d`
  (modo 1D da decisão 5.28)
- `"diario"`  → `("dias", 90)`
- `"mensal"`  → `("dias", 90)`

Helper inline `_aplica_default_pld_inline(gran, min_d, max_d)` consome
a constante e seta `data_ini`/`data_fim`. Reset block tem **5 triggers**
e em qualquer um deles chama o helper passando a granularidade atual.

**Caso que motivou:** abrir PLD horário com período herdado (3M, 6M)
força render de até 230k pontos — lentidão e UX confusa pra um caso
de uso raro. Uso típico de "entrar em horário" é ver 1 dia específico
(decisão 5.28).

**Bug que validou a arquitetura (Cenário 3):** versão inicial usava
sentinela `_pld_granularidade_anterior` em bloco SEPARADO, APÓS o
reset block, detectando só TROCA real de gran. Mas voltar de outra
aba limpa `data_ini` (widget cleanup do `st.date_input("Dia",
key="data_ini")` em modo single-day — decisão 5.16). Reset GENÉRICO
de 90d disparava via `data_ini not in state`, e o bloco separado não
disparava (`gran_anterior == "horario"` na volta — não era troca).
Resultado: voltar pra PLD horário trazia 90d, não 1D.

Fix: integrar o default-por-gran no reset block (cobre TODOS os
triggers que aplicam default, não só troca interna).

**5 triggers do reset block** (`app.py:1448-1457`):

1. `data_ini` ausente do state — 1ª render OU widget cleanup ao
   voltar de outra aba.
2. `_dataset_max` mudou — refresh CCEE / Atualizar.
3. `_dataset_min` mudou.
4. `range_degenerado_fora_horario` (decisão 5.28) — vinha de horário
   1D pra diário/mensal, `data_ini == data_fim`.
5. `trocou_pra_horario` — `granularidade == "horario"` AND
   `gran_anterior != "horario"`. Cobre troca dropdown DENTRO da aba
   (data_ini AINDA em state, então trigger 1 não dispara).

```python
if (
    "data_ini" not in st.session_state
    or st.session_state.get("_dataset_max") != max_d
    or st.session_state.get("_dataset_min") != min_d
    or range_degenerado_fora_horario
    or trocou_pra_horario
):
    _aplica_default_pld_inline(granularidade, min_d, max_d)
    st.session_state["_dataset_max"] = max_d
    st.session_state["_dataset_min"] = min_d
```

**Comportamento emergente — trocar gran reseta período via trigger #3:**

Quando o usuário troca o dropdown de granularidade (ex: horário 1S
→ diário), `df = get_pld_df("diario")` carrega DataFrame diferente
e `min_d` re-computado pode divergir do `_dataset_min` herdado da
granularidade anterior. Trigger #3 dispara → reset aplica default
da gran nova (90d em diário/mensal).

**Diagnóstico empírico (Sessão PLD pós-Ajuste 2):** validado em
runtime via debug temporário. Em horário 1S → diário com dataset
CCEE atual (2026-04-29):
- `_dataset_min_state_pre = 2021-01-01` (horário)
- `min_d_atual = 2021-01-08` (diário)
- diferença: **7 dias**

A diferença é MÍNIMA mas suficiente pra ativar o trigger #3
(`!= ` é estrito).

**Comportamento de produto:** desejado e confirmado. Justificativa:
diário e mensal não têm preset "1S" no UI; deixar usuário em
diário com 7 dias herdados criaria estado "fantasma" não
recriável via botões. Forçar default da gran nova é mais
previsível: "trocar gran = vai pro default da gran nova".

**⚠️ Fragilidade reconhecida:** o reset ao trocar gran depende SÓ
da diferença em `_dataset_min` entre os datasets. Se um dia o
CCEE alinhar os históricos exatamente (ex: ambos começarem em
2021-01-01), `_dataset_min` ficaria igual entre granularidades e
trigger #3 não dispararia. Resultado: usuário começaria a HERDAR
o range entre granularidades — comportamento DIFERENTE do atual,
sem nenhuma mudança no nosso código.

**Decisão futura (não implementar agora):** se a fragilidade se
materializar (CCEE alinhar históricos OU bug de reset for
reportado), adicionar trigger #6 explícito ao reset block:

```python
trocou_de_gran = gran_anterior is not None and gran_anterior != granularidade
```

Padrão análogo ao trigger #5 (`trocou_pra_horario`) mas
generalizado pra qualquer troca. Mantemos código mínimo enquanto
o efeito colateral via trigger #3 funciona — não vale adicionar
defesa preventiva contra cenário hipotético.

**Sentinela `_pld_granularidade_anterior`:** atualizada SEMPRE (não
só quando reset dispara) — comportamento mais previsível. Não é
widget-state — sobrevive a cleanup. Condição única `gran_anterior !=
"horario"` cobre 2 casos:
- (a) **Troca real** entre granularidades:
  `gran_anterior in {"diario","mensal"}`.
- (b) **1ª render** da sessão já em horário: `gran_anterior is None`
  (`None != "horario"` é True). Pode acontecer se a aba PLD abre
  direto em horário via state restaurado (raro com defaults atuais,
  mas a condição cobre por defesa).

**Sem `st.rerun()` na troca:** o reset block roda ANTES da leitura
de `data_ini`/`data_fim` mais abaixo, então as mudanças em state
já valem no resto da render. Render mais rápido.

**O que NÃO é resetado:**
- Submercados (`sel_SE`, `sel_S`, `sel_NE`, `sel_N`, `sel_media`):
  preserva seleção do usuário (princípio de menor surpresa). Default
  "todos marcados" só vale na 1ª criação dos widgets via `value=True`.

**Quando aplicar este padrão em outras abas:** se uma aba ganhar
2+ granularidades com defaults distintos. Reservatórios e ENA têm 1
modo só. Geração já usa pattern análogo (decisão 5.20) com
`_gen_last_gran` + helper top-level `_aplica_default_periodo_gen` —
generalização que cobre defaults POR granularidade ativa, não só
"transição pra X". PLD usa forma mais simples (constante + helper
inline + 1 trigger de transição) porque só uma das 3 granularidades
precisa de default distinto. Migrar pra forma estilo Geração quando
PLD ganhar mais granularidades com defaults únicos.

### 5.37 Rebranding BBI (login + sidebar)

**Decisão:** dashboard adota identidade visual Bradesco BBI sem
abandonar o design system Bauhaus existente. Mudanças mínimas e
cirúrgicas em duas telas: login (vista 1× por sessão, cerimonial)
e sidebar (permanente durante navegação). Todas as outras telas
internas (abas PLD, Reservatórios, ENA, Geração, Carga, Curtailment)
ficam intactas.

**Decisões de produto:**

- Cores Bauhaus do projeto (`BAUHAUS_RED #D62828`, `BAUHAUS_BLUE
  #2A6F97`, `BAUHAUS_YELLOW #F6BD16`, `BAUHAUS_BLACK #1A1A1A`,
  `BAUHAUS_CREAM #F5F1E8`) são MANTIDAS. Não houve substituição
  por cores BBI — diferenças seriam imperceptíveis e custo de
  mudar (revisar gráficos, KPIs, prints) não compensa.
- Vermelho BBI `#CC092F` é usado APENAS no logo da tela de login
  (re-colorido a partir do logo branco da sidebar pra coerência
  visual). Não substitui o vermelho Bauhaus em nenhum outro lugar.
- Amarelo Bauhaus mantido apesar de a paleta BBI não ter amarelo.
  Justificativa: amarelo é central na identidade Bauhaus (botões
  ativos, submercado NE, cabeçalhos da sidebar) e seria caro de
  remover.

**Logos e geração:**

- Fontes originais: `BBI Logo 2.jpg` (vertical vermelho),
  `Bradesco_BBIS_RGB_BLACK (1).jpg` (horizontal preto). Originais
  preservados em `assets/source_logos/`.
- Pipeline de geração via Pillow (3 scripts em `scripts/`):
  - `gerar_logos_bbi.py`: remove fundo branco com tolerância de
    antialiasing, gera `bbi_horizontal_white.png` a partir do JPG
    preto (inverte preto pra branco, preserva alpha).
  - `gerar_logo_vermelho.py`: re-colore o branco pra vermelho BBI
    `#CC092F` preservando alpha. Gera `bbi_horizontal_red.png`.
    Garante que login e sidebar têm logos com mesma "geometria de
    bordas".
  - `crop_logo_white.py`: cropa margens transparentes herdadas do
    JPG original (5.5% laterais + 20.7% verticais). Aplicado
    APENAS no branco — vermelho mantém proporção original já
    calibrada com o título da tela de login.
- Previews descartáveis (`assets/logos/_preview_*.png`) ignorados
  via `.gitignore`.

**Tela de login (`auth.py`):**

- Logo BBI horizontal vermelho centralizado na tela.
- Título "Dashboard Setor Elétrico — Brasil" com barra vermelha
  Bauhaus (`border-left: 10px solid {_RED}`). `width: fit-content +
  margin: 0 auto` faz o bloco título+barra centralizar como UNIDADE
  mantendo `text-align: left` interno (técnica que evita brigar com
  `text-align: center vs left` no mesmo bloco).
- Autores "Navarrete | Fagundes | Caruso" centralizados em linha
  única, preto Bauhaus.
- Form com `max-width: 600px` (calibrado empiricamente pra borda
  direita coincidir com final do "l" de "Brasil").
- `!important` nas props de `.login-title` pra vencer regra global
  `h1` do `app.py` (border-left 7px Bauhaus padrão de seção).

**Sidebar (`app.py`):**

- Logo BBI horizontal branco no topo (alinhado à esquerda — precisou
  cropar PNG porque margem transparente do source desalinhava
  visualmente vs. o texto da sidebar).
- Título "DASHBOARD SETOR ELÉTRICO" Bebas Neue 1.25rem
  `letter-spacing: 0.20em` (calibrado pra abrir letras condensadas
  em font-size pequeno).
- Username "Nava" Inter 1rem cinza `#A0A0A0` (igual ao `st.caption`
  default em dark theme, `rgba(250,250,250,0.6)` renderizado),
  margin-top empurra pra baixo aproximando do Sair.
- Botão Sair com `margin-top: -0.5rem !important` (sobe dentro do
  `element_container` do Streamlit pra colar no username, sem
  alterar o container — alternativa a `:has()` que sabemos que
  trava o app, decisão 4.1).
- Seletor preciso `button[data-sair="true"]` usa o JS marker já
  existente.
- Seção "BBI UTILITIES TEAM:" no rodapé via `st.divider()` nativo
  + label Bebas Neue amarelo + 3 nomes Inter brancos alinhados à
  esquerda.

**Patterns reutilizáveis (registrados pra próximas mudanças
visuais):**

1. **Logos em base64 lidos 1× no nível do módulo** via `Path` +
   `try/except` defensivo. Se `assets/logos/` ausente, app não
   quebra — só não renderiza logo.
2. **Classes próprias** (`.sidebar-*`, `.login-*`) com seletor
   `[data-testid="stSidebar"] .classe` pra especificidade alta sem
   empilhar `!important` em cima de `!important`.
3. **Cropar margens transparentes de PNGs gerados a partir de JPGs**
   antes de usar em layouts críticos. Margens herdadas do JPG fonte
   (5-20% comum) desalinham visualmente o conteúdo.
4. **Cor cinza claro de `st.caption`** em dark theme do projeto =
   `~#A0A0A0` (rgba(250,250,250,0.6) renderizado). Útil pra replicar
   em classes próprias que substituem o caption preservando o look.
5. **Bebas Neue em font-size pequeno** (≤1.25rem): precisa
   `letter-spacing ≥ 0.20em` pra ficar legível. Inter pode ficar
   mais socada (default já funciona).
6. **`width: fit-content + margin: 0 auto`** centraliza um bloco
   block-level mantendo `text-align: left` interno — útil pra
   "barra vermelha + texto" que precisa centralizar como unidade
   sem perder a barra à esquerda.

**Quando aplicar este pattern em outras telas:**

- Mudanças visuais futuras que precisem inserir branding ou
  alterar visual de telas específicas (login, telas de erro, modais)
  sem refatorar o design system Bauhaus de gráficos/abas internas.
- Inserção de logos institucionais em qualquer ponto do app
  (preview de relatório, header de export PDF futuro).

**Quando NÃO aplica:**

- Mudanças de paleta global (gráficos, KPIs, abas internas) — exigem
  refator amplo das 5+ abas e dezenas de prints validados.
- Substituição de cores estruturais Bauhaus (`BAUHAUS_RED` etc.) —
  são identidade do projeto há múltiplas sessões e estão em
  centenas de pontos do código.

### 5.38 LTM trimestral = 4 trimestres móveis (offset 9 meses)

**Decisão**: Em modo Trimestral, "LTM" significa **trimestre corrente +
3 anteriores** = 4 barras. Nunca 12 meses corridos como em
granularidades menores.

**Caso que motivou**: Sessão Despacho Térmico (Fase E.8). Tooltip dizia
"Últimos 12 meses" mas o gráfico mostrava 4 barras (1 por trimestre),
criando dissonância visual. Correto em finanças: LTM trimestral =
4 trims (convenção de demonstrações financeiras).

**Implementação**: cálculo aritmético do `ltm_cutoff` sem
`relativedelta` (dependência adicional desnecessária):

```python
_mes_inicial_corrente = ((max_d.month - 1) // 3) * 3 + 1
_mes_cutoff_offset = _mes_inicial_corrente - 9
if _mes_cutoff_offset <= 0:
    _ano_ltm = max_d.year - 1
    _mes_ltm = _mes_cutoff_offset + 12
else:
    _ano_ltm = max_d.year
    _mes_ltm = _mes_cutoff_offset
ltm_cutoff = date(_ano_ltm, _mes_ltm, 1)
```

**Por quê 9 meses (e não 12)**: trimestre corrente + 3 anteriores
começam exatamente 9 meses antes do início do trimestre corrente.
Validação empírica em 4 cenários (1T/2T/3T/4T corrente).

**Quando aplicar**: qualquer dashboard com modo Trimestral que precise
de "LTM" semanticamente correto. Em modos não-Trimestral, manter
LTM = 365 dias (`max_d - timedelta(days=365)`).

### 5.39 State `int|None` → `list[int]` com rename pra forçar reset clean

**Decisão**: Quando uma chave de `st.session_state` muda de tipo
(ex: escalar pra lista), **renomear a chave** em vez de coexistir com
tipo antigo. State legado fica órfão e Streamlit garante que a nova
chave nasce limpa com o default novo.

**Caso que motivou**: Fase E.9 — `termico_sistema_trimestre_comparacao:
int|None` (single-select) virou `termico_sistema_trimestres_marcados:
list[int]` (multi-select). Manter a mesma chave faria leituras
downstream lerem state legado de tipos diferentes a depender da
última escrita.

**Implementação**: rename completo da chave + remoção de toda
referência à chave antiga.

**Por quê não migration in-place**: tentar
`if isinstance(state[key], int): state[key] = [state[key]]` é frágil:
- Não cobre `None` (precisa segundo `if`)
- Pode rodar múltiplas vezes (se schema mudar de novo)
- State legado de versões muito antigas pode ter outros tipos imprevisíveis

**Quando aplicar**: qualquer mudança de tipo em chave de
`session_state`. Renomear é mais barato que migrar.

**Trade-off**: usuários com sessão antiga "perdem" o estado da chave
(volta ao default). Aceitável pra estado de filtros (que o user vai
re-selecionar mesmo).

### 5.40 Interface temporal contextual (single↔multi-select com transições)

**Decisão**: Em filtros temporais com modos compostos (ex: ano/LTM/trim),
a UI muda comportamento conforme o modo ativo:
- Modo "ano completo" (sem trim): single-select dos anos+LTM
- Modo "histórico" (com trim): multi-select de tudo
- Transições explícitas entre modos:
  - "ano_completo → histórico" (1º click em trim): marca todos os anos
    automaticamente
  - "histórico → ano_completo" (último trim desmarcado): limpa anos,
    força LTM=True

**Caso que motivou**: Fase E.9. Usuário precisa de 2 análises distintas
no Trimestral:
- Comparar mesmo trim cross-anos (ex: "1T de 22, 23, 24, 25, 26")
- Ver série completa de um ano (ex: "todos os trims de 2024")

Sem transições explícitas, usuário precisaria desmarcar/marcar
manualmente vários botões a cada mudança de análise.

**Implementação**: handler de click de cada widget detecta `modo_trim`
(derivado de `if not trims_marcados: "ano_completo" else: "historico"`)
e aplica regra correspondente. Tooltips mudam por modo:
- "Comparar {label} cross-anos" (ano_completo)
- "Click pra desmarcar {label}" (historico ativo)
- "Adicionar {label} à comparação" (historico inativo)

**Quando aplicar**: filtros temporais com 2+ dimensões
(ano × período-do-ano) onde o usuário precisa de análises diferentes.
Não vale o overhead em filtros simples (só datas, só categorias).

**Refinamento (Fase H — Item 6):** Click no botão de ano deixou de
ser single-select em modo "ano_completo". Passou a ser **toggle
multi-select sempre**, com regra adicional: se `trims_marcados` está
vazio no momento de marcar um ano novo, marca automaticamente os 4
trims (`[1, 2, 3, 4]`) — comportamento default "ano cheio". O modo
ano_completo deixa de existir como operação distinta no botão de
ano. Aplicado em ENEVA + SIN.

Razão UX: single-select causava troca abrupta (clicar "2024" fazia
"2023" sumir mesmo se user queria ambos). Multi-select é mais
previsível — adiciona/remove sem perder seleção anterior. A regra
"1ª vez marca trims" preserva o atalho histórico de ver "ano cheio"
sem precisar marcar 4 trims manualmente.

**O que continua valendo da decisão 5.40 original:**
- Botão LTM: ainda usa lógica por modo (single-select em ano_completo
  / toggle em historico). Não foi alterado.
- Botão trim: ainda usa lógica por modo (transição ano_completo →
  historico marca TODOS os anos disponíveis ao clicar 1º trim).
- Help text dinâmico dos trims: ainda muda por modo
  ("Comparar cross-anos" / "Click pra desmarcar" / "Adicionar à
  comparação").
- Edge case "tudo desmarcado" (`anos=[] AND ltm=False`): ainda
  força `ltm=True` via `st.rerun()`.

**Variável `modo_trim`:** ainda calculada e usada por LTM e trims;
deixou de ser usada pelo botão de ano.

**Refinamento (Fase H.1 — Ajuste 3):** Click no botão de ano agora
**desliga LTM** automaticamente ao MARCAR ano. Reverte parcial o
"preserva LTM" do Refinamento Fase H — Item 6 acima. Aplicado em
ENEVA + SIN.

Razão UX validada após print: ao clicar "2024" com LTM ativo no
estado inicial, o user esperava ver "só 2024", não "2024 + LTM".
Mantendo LTM ligado dava resultado confuso (mais barras do que o
user pediu). Desligar LTM ao marcar ano alinha com a intenção de
"foco em ano específico".

**Implementação:** `st.session_state["..._ltm_marcado"] = False`
adicionado APÓS as escritas de `anos_comparacao`/`trims_marcados`
no branch "marcando" (`else` do `if ativo_ano:`). Sem efeito no
branch "desmarcando" (preserva LTM ao remover ano). Edge case
"tudo desmarcado" (`anos=[] AND ltm=False`) continua forçando
`ltm=True` via `st.rerun()` — garante saída do estado inválido se
user remove último ano com LTM já desligado.

### 5.41 `traceorder="normal"` pra Plotly stacked bar

**Decisão**: Em gráficos `barmode="stack"`, sempre setar
`legend.traceorder="normal"`. Default do Plotly é `"reversed"` quando
`barmode="stack"`, criando dissonância: a 1ª camada (base) aparece
**à direita** da legenda em vez da esquerda.

**Caso que motivou**: Fase E.7. Despacho Térmico SIN com 7 motivos
empilhados (Inflexibilidade na base, Garantia energética no topo).
Legenda mostrava "Garantia energética" à esquerda, "Inflexibilidade"
à direita. Usuários liam legenda da esquerda pra direita esperando
ordem visual idêntica.

**Implementação**:

```python
fig.update_layout(
    barmode="stack",
    legend=dict(
        traceorder="normal",
        orientation="h",
        ...
    ),
)
```

**Por quê não documentado pelo Plotly**: docs do Plotly mencionam
`traceorder` em `legend` mas não destacam que `barmode="stack"` muda
o default automaticamente. Pegadinha encontrada empíricamente.

**Quando aplicar**: qualquer `go.Bar` ou `go.Scatter(stackgroup=...)`
com 3+ traces empilhados.

### 5.42 Estilo inline sobrescreve CSS global sem `!important`

**Decisão**: Quando uma regra `<h3>`/`<h2>`/etc. global afeta uso
pontual de tag (ex: `border-bottom: 2px solid #1A1A1A` em todo h3
do projeto), **não usar `!important` no global**. Permite que estilos
inline (`<h3 style="border-bottom: none;">`) sobrescrevam pontualmente
sem precisar duplicar CSS scoped por aba.

**Caso que motivou**: Fase E.10 — caption interna do Despacho Térmico
(`### Despacho térmico nacional`) puxava linha horizontal do estilo
global. Era preciso remover só nessa caption, não em outras abas.
Solução: HTML inline
`<h3 style="border-bottom: none; padding-bottom: 0;">...</h3>`.

**Por quê funciona sem `!important`**: precedência CSS — estilo inline
(1000) > seletor de tag (1). Se global usar `!important` (10000),
inline precisa também usar `!important` pra ganhar (entra em "guerra
de !importants" desnecessária).

**Quando aplicar**: regras CSS de tags genéricas (h1-h6, p, table)
onde casos pontuais podem precisar override. CSS scoped via
`[class*="..."]` ainda usa `!important` quando necessário (Streamlit
aplica regras posteriores no DOM).

**Trade-off**: usuários ou outras abas podem acidentalmente
sobrescrever via inline. Aceitável (override é decisão consciente).

### 5.43 Spacer pra cancelar margin global Bauhaus em containers extras

**Decisão**: O título Bauhaus padrão
(`<div style="border-bottom: 2px solid #1A1A1A; margin: 0 0 -1.5rem 0;">`)
usa `margin-bottom: -1.5rem` pra puxar o conteúdo seguinte pra cima
e cancelar o `margin-top: -1.5rem` global dos `date_inputs`. Em abas
com conteúdo extra entre título e date_inputs (ex: pills de sub-view),
o cancelamento se quebra. Solução: adicionar
`<div style="margin-top: 1.5rem;"></div>` antes do bloco que tem
date_inputs.

**Caso que motivou**: Fase E.13 — Despacho Térmico Eneva com pills
(Eneva | SIN) entre título e helper `_render_period_controls`.
Date_inputs sobrepondo o pill SIN (overlap geométrico de 0.5rem).

**Cálculo**:
- Pills.base = 2.4rem
- Date_inputs Y = 1.9rem (= 3.4 - 1.5 do margin global)
- Overlap = 0.5rem
- Spacer 1.5rem cancela exatamente o `-1.5rem` global → date_inputs
  voltam a alinhar pela base com presets

**Quando aplicar**: qualquer aba com conteúdo entre título Bauhaus e
date_inputs/period_controls. Outras 5 abas (PLD, Reservatórios, ENA,
Geração, Carga) chamam helper direto e não precisam (cancelamento
natural via Bauhaus).

### 5.44 Dataset ONS horário nativo + `groupby(["data", "hora"])`

**Decisão**: Dataset `geracao_termica_despacho_2_ho` (ONS) é
**horário nativo**. Loader extrai coluna `hora` (int8, 0-23) via
`ts.dt.hour`, separada de `data` (normalizada pra 00:00:00).
Granularidades agregadas (Mensal/Diário/Trimestral) ignoram `hora`
no groupby. Granularidade Horário usa `groupby(["data", "hora"])` —
1 grupo por hora-do-dia.

**Caso que motivou**: Fase E.14. Pra adicionar granularidade Horário,
primeiro instinto seria buscar dataset diferente. Investigação revelou
que o dataset atual já é horário (sufixo `_ho` na URL ONS).

**Schema do DataFrame retornado por `carregar_termico()`**:

```python
data         datetime64[ns]   # normalizado pro dia (00:00:00)
hora         int8             # 0-23
id_subsistema, nom_subsistema  str
nom_usina, usina_eneva         str
val_verifgeracao               float (MWh por hora × usina)
7× val_verif{motivo}           float
```

**Reconstrução de instante completo**:
`data + pd.to_timedelta(hora, unit="h")`.

**Conversão pra MWm em modo Horário**: cada linha = 1 hora →
`sum(val) = MWh = MWm` (denominador implícito = 1h, sem divisão).
Em modos agregados, divide por horas_periodo (24 pra Diário, etc).

**Quando aplicar**: qualquer dataset com granularidade nativa fina +
necessidade de agregar opcionalmente. Padrão: separar `data` (dia)
de `hora` (int) no schema interno; consumidor escolhe granularidade.

### 5.45 "Checagem de órfãos" ao readicionar feature removida

**Decisão**: Quando uma feature/opção é removida do código,
**deixar comentário marcador** próximo à remoção, e ANTES de
readicionar a mesma feature em fase futura, fazer `grep` pelo nome
da feature em todo o codebase pra detectar **código órfão defensivo**
que pode interceptar silenciosamente.

**Caso que motivou**: Fase E.14. "Horário" foi removida do selectbox
na Fase E.1. Migração defensiva foi adicionada nas linhas 3149-3150
pra mapear state legado:
`if state["...granularidade"] == "Horário": state[...] = "Mensal"`.
Na Fase E.14, "Horário" foi readicionada ao selectbox, mas a migração
defensiva ficou. Resultado: usuário clicava "Horário", state escrevia
"Horário", próximo render o remap forçava de volta pra "Mensal".
Bug silencioso descoberto só com print do usuário.

**Trace do bug**:
1. User clica selectbox → state["granularidade"] = "Horário"
2. Streamlit rerun
3. Linha do remap: detecta "Horário" → REMAP pra "Mensal" ⚠
4. Selectbox renderiza "Mensal" selecionado
5. Gráfico Mensal renderiza com 12M

**Implementação**: ao remover feature, marcar com comentário tipo:

```python
# REMAP DEFENSIVO — feature "Horário" removida na Fase E.1.
# Se readicionar, REMOVER ESTE BLOCO antes ou bug silencioso.
```

**Quando aplicar**: qualquer remoção de opção de selectbox,
granularidade, modo, ou estado legado. Especialmente importante
quando o código defensivo é "silencioso" (não levanta exceção).

### 5.46 Single-day picker em granularidades ultra-finas (1 date_input + sync)

**Decisão**: Em granularidade Horário, mostrar **1 único `date_input`**
"Data" em vez de 2 (data_inicial + data_final). Pós-render,
sincronizar `state["data_fim"] = state["data_ini"]` pra que
filtragem `data >= data_ini & data <= data_fim` pegue exatamente
1 dia (24 horas).

**Caso que motivou**: Fase E.15. Granularidade Horário com range
>1 dia produzia 168+ barras (7×24), eixo X bagunçado, hover
unificado pesado. Single-day picker simplifica UX e elimina
necessidade de validação ">N dias".

**Implementação**:

```python
if gran_atual == "Horário":
    with col_di:
        st.date_input(
            "Data",
            min_value=min_d, max_value=max_d,
            key="termico_sistema_data_ini",
            format="DD/MM/YYYY",
        )
    # Sincroniza data_fim = data_ini (single-day)
    st.session_state["termico_sistema_data_fim"] = (
        st.session_state["termico_sistema_data_ini"]
    )
else:
    # 2 date_inputs como hoje
    ...
```

**Por quê escrita simples (não callback `on_change`)**: o widget de
`data_fim` NÃO é instanciado em modo Horário, portanto a key NÃO está
bound a widget. Escrita direta em `state["data_fim"]` é OK
(sem `StreamlitAPIException`).

**Reset block** seta ambas (`data_ini = data_fim = max_d`) na
transição pra Horário, garantindo estado coerente desde o 1º render.

**Quando aplicar**: qualquer granularidade ultra-fina (horária,
sub-horária) onde range >1 unidade explode volume de pontos.

### 5.47 Gráfico de área via `Scatter(stackgroup, mode="none", fillcolor)`

**Decisão**: Pra gráfico de **área stackada contínua**, usar
`go.Scatter` com `stackgroup="grupo"`, `mode="none"`, `fillcolor=cor`.
Não usar `go.Bar` em granularidades onde os pontos representam medição
contínua (ex: horária). Manter `go.Bar` em granularidades discretas
(mensal, trimestral).

**Caso que motivou**: Fase E.15. Despacho Térmico SIN em modo Horário
com 24+ pontos: `go.Bar` empilhado fica visualmente "serrado" e
dificulta perceber tendências. Área stackada (Plotly Scatter com fill)
suaviza visualmente e é o pattern correto pra séries temporais densas.

**Implementação** (render condicional dentro do loop dos motivos):

```python
for col in MOTIVOS_COLS:
    cor, label = PALETA[col]
    if gran_atual == "Horário":
        fig.add_trace(go.Scatter(
            x=agg["label"],
            y=agg[col],
            name=label,
            stackgroup="motivos",
            mode="none",          # sem linha/marker visível
            fillcolor=cor,
            hovertemplate=...,
        ))
    else:
        fig.add_trace(go.Bar(
            x=agg["label"],
            y=agg[col],
            name=label,
            marker_color=cor,
            hovertemplate=...,
        ))
```

`barmode="stack"` no `update_layout` é ignorado por Scatter (só aplica
a Bar) — sem efeito colateral em modo Horário.

**Trace Total Scatter invisível** (anchor pro hover unified): mantém
em ambos os modos. Já é Scatter sem stackgroup → fica isolado no plot.

**Quando aplicar**: granularidade horária ou minutária com 24+ pontos.
Em granularidades discretas (mensal, trimestral), Bar é mais apropriado
(representa "blocos" temporais distintos).

### 5.48 Checkbox decorativo via `::before` (☐/☑) sobre `st.button`

**Decisão**: Pra UI de "checkbox" com cor controlada Bauhaus, **NÃO
usar `st.checkbox`** (cor primária `#FF4B4B` rosa, frágil de override
sem `:has()`). Em vez disso, usar `st.button` com decoração CSS
`::before` que renderiza `☐` (inativo) ou `☑` (ativo, via
`button[kind="primary"]::before`).

**Caso que motivou**: Fase E.16. Despacho Térmico Trimestral. Usuário
pediu visual "checkbox" pros trims (1T/2T/3T/4T). `st.checkbox` tem
rosa Streamlit difícil de overridar; `:has()` está descartado pela
decisão 4.1 (trava o app no Streamlit 1.56). Solução: manter
`st.button` toggle (mesmo comportamento de checkbox) + decoração via
pseudo-elemento.

**Implementação**:

```css
[class*="st-key-prefix_btn_"] button[kind]::before {
    content: "☐";
    margin-right: 0.3rem;
    font-weight: 700;
    font-size: 1rem;
    line-height: 1;
}
[class*="st-key-prefix_btn_"] button[kind="primary"]::before {
    content: "☑";
}
```

**Variação "soltos"** (Fase E.16.1): se quiser remover framing do
botão (sem borda/background), adicionar override:

```css
[class*="st-key-prefix_btn_"] button[kind],
[class*="st-key-prefix_btn_"] button[kind="primary"] {
    background: transparent !important;
    background-color: transparent !important;
    border: none !important;
    box-shadow: none !important;
    color: #1A1A1A !important;
    font-weight: 400 !important;
}
[class*="st-key-prefix_btn_"] button[kind]:hover,
[class*="st-key-prefix_btn_"] button[kind="primary"]:hover {
    background: rgba(0, 0, 0, 0.05) !important;
    background-color: rgba(0, 0, 0, 0.05) !important;
    color: #1A1A1A !important;
}
```

**Trade-off**: tecnicamente é button, não checkbox. Acessibilidade via
`aria-pressed` do Streamlit garante leitor de tela.

**Quando aplicar**: qualquer UI multi-select com cores controladas
(Bauhaus ou outro design system) onde `st.checkbox` rosa quebra
estética.

**Refinamento (Fase H.1 — Ajuste 2):** Pattern revertido em
Trimestral (Despacho Térmico SIN + Eneva) — `st.button` + ::before
substituído por `st.checkbox` nativo. Aplicado em ENEVA + SIN.

Razão: a aba PLD já usava `st.checkbox` com workaround anti-rosa
em CSS GLOBAL desde antes (`app.py:416-450`):
```css
[data-testid="stAppViewContainer"] .stCheckbox label > span:first-child {
    filter: grayscale(1) brightness(0.6) contrast(5) !important;
}
```
A regra é GLOBAL — aplica em TODOS os checkboxes do app, não scoped
por aba. Quando a Fase H.1 trocou trims pra `st.checkbox`, eles
herdaram automaticamente o quadradinho preto + tick branco (via
`filter` que dessatura o rosa pra preto sem detectar estado).

**Implicação prática:** o pattern da decisão 5.48 (st.button +
::before) só vale agora em UIs com **3+ estados** (não só on/off)
ou onde `st.checkbox` não cabe estruturalmente. Pra checkbox
binário simples (case dos trims), `st.checkbox` + filter grayscale
global é mais limpo (1 widget nativo vs button + CSS dedicado).

**CSS scoped removido** em ambas sub-views: linhas Sistema (~3170-
3232) e Eneva (~3960-4006) reduzidas a SÓ `_btn_ano_*` (botões ano
Trimestral, que continuam usando `st.button` por causa da
necessidade de `type="primary"` pra estado ativo).

**Tipografia diferente:** `.stCheckbox label p` herda do CSS global
(Inter 0.92rem 600), em vez do botão (0.85rem do CSS scoped antigo).
Aceito como trade-off pela consistência com PLD.

### 5.49 Helper local pra caption do gráfico (escopo restrito à aba)

**Decisão**: Funções auxiliares específicas de uma aba (ex: caption
customizado) podem ser definidas **localmente dentro do bloco da aba**,
não no top-level. Re-criação a cada render tem custo desprezível
(~5µs por `def`). Trade-off: escopo limpo > micro-otimização.

**Caso que motivou**: Fase E.17.
`_render_termico_chart_caption(sub_label, gran_label, data_ini,
data_fim, unidade_label)` é usada apenas no Despacho Térmico
(sub-views Sistema + Eneva). Definir top-level poluiria namespace
global e não seria reutilizada por outras 5 abas (que usam pattern
diferente — `_format_periodo_br` + tag de granularidade da decisão
5.22).

**Implementação**:

```python
elif aba == "Despacho Térmico":
    # ... título, pills, init de state ...

    _ADJETIVOS = {"Mensal": "mensal", ...}

    def _render_chart_caption(sub_label, gran_label, ...):
        # ... HTML inline com top row + sub-caption ...

    if subview == "Sistema":
        # ... usa _render_chart_caption ...
    else:
        # ... usa _render_chart_caption ...
```

**Quando aplicar**: helpers usados em apenas 1 aba (não compartilhados).
Helpers compartilhados (ex: `_render_period_controls`,
`_format_periodo_br`) ficam top-level.

**Quando NÃO aplicar**: helpers chamados em loops apertados (perf
crítica) ou usados em 2+ abas.

### 5.50 `xaxis_kwargs` condicional (Plotly tickformat datetime)

**Decisão**: Pra eixos contextuais em Plotly (ex: tick format diferente
por granularidade), extrair `xaxis_kwargs = dict(...)` como variável
e adicionar keys condicionalmente antes de passar pro `update_layout`.
Evita duplicação de `update_layout` calls e mantém keys default
(paletas, ticks, fontes) inalteradas.

**Caso que motivou**: Fase E.14.1. Em modo Horário, eixo X precisa de
`tickformat="%H:00"` (curto) e hover precisa de
`hoverformat="%d/%m/%Y %H:00"` (rico). Outros modos usam `x=string`
(categorical implícito) e não precisam de format.

**Implementação**:

```python
xaxis_kwargs = dict(
    title=None, showgrid=False, showline=True,
    linewidth=2, linecolor=BAUHAUS_BLACK,
    ticks="outside", tickcolor=BAUHAUS_BLACK,
    tickfont=dict(family="Inter, sans-serif", size=12, color=BAUHAUS_BLACK),
)
if gran_atual == "Horário":
    xaxis_kwargs["tickformat"] = "%H:00"
    xaxis_kwargs["hoverformat"] = "%d/%m/%Y %H:00"

fig.update_layout(
    barmode="stack",
    ...
    xaxis=xaxis_kwargs,
    yaxis=dict(...),
)
```

**Pré-requisito**: em modo Horário, `agg["label"]` deve ser
**datetime nativo** (não string formatada). Plotly aplica `tickformat`
apenas em datetime; em string, ignora silenciosamente.

**Quando aplicar**: qualquer gráfico Plotly onde o formato do eixo
varia por contexto (granularidade, modo, etc.). Pattern aplicável
também a `yaxis_kwargs`, `legend_kwargs`.

### 5.51 H.8.B redefinida — escopo de "alinhamento bot ano" (não "movimentação MWM/GWH")

**Decisão**: A Fase H.8.B foi redefinida durante a sessão 2026-05-06. Escopo original (mover MWM/GWH em Eneva Trimestral pra row 2) substituído por escopo realizado (alinhar botões de ano e checkboxes em Eneva e Sistema Trimestral com selectbox Granularidade via cols_anos calibrado). Movimentação de MWM/GWH em Eneva Trimestral fica em backlog futuro (sem fase numerada definida).

**Caso que motivou**: Fase H.8.A. Após calibrar Eneva Mensal (MWM/GWH em row 2 alinhado com selectbox Usina), os ajustes de cols_anos no Eneva e Sistema Trimestral atingiram nível visual satisfatório sem necessidade de mover MWM/GWH em Trimestral. Decisão funcional: MWM/GWH no Eneva Trimestral permanece em col_meio porque (1) row 2 do Trimestral já é densa com 6 botões de ano + 4 checkboxes de trim, (2) MWM/GWH ao lado de Usina é UX aceitável, (3) movimento adiciona complexidade sem ganho proporcional.

**Implementação**: Margin-top -3.5rem do grupo `eneva_trimestral_row2` no CSS H.7.B-bis deixa de ser "temporário" (como descrito no commit `3c5257b`) e passa a ser **solução final**. Comentário inline no CSS deve ser atualizado em sessão futura pra remover a linguagem "recalibrar na H.8.B".

**Trade-off**: Ganha-se simplicidade (não há retrabalho de movimentação + recalibração margin-top) e velocidade de fechamento de fase. Perde-se uniformidade visual (Eneva Mensal tem MWM/GWH em row 2, Eneva Trimestral mantém em col_meio). Trade-off aceito porque as 2 sub-views são contextualmente diferentes (Mensal tem 2 botões de período presets, Trimestral tem 6 anos + 4 trims).

**Quando aplicar**: Quando uma fase futura for revisitar o Eneva Trimestral, lembrar que MWM/GWH ali está em col_meio por decisão e não por pendência.

**Quando NÃO aplica**: Não aplicável a outras sub-views — Eneva Mensal já tem MWM/GWH em row 2 (commit `3c5257b`), e SIN não tem MWM/GWH (toggle exclusivo do Eneva).

### 5.52 Refatoracao de st.radio principal pra loop de st.button (Fase Nav.1)

**Decisao**: o radio principal da sidebar (NAVEGACAO, 7 abas) foi
substituido por loop de `st.button` com state em
`session_state["aba_selecionada"]`. Padrao reusavel pra qualquer
sidebar que precise de hierarquia (sub-itens condicionais embaixo
de um item principal).

**Caso que motivou**: Fase Nav.2 precisa exibir sub-itens "Eneva" e
"SIN" embaixo do botao "Despacho Termico" SOMENTE quando essa aba
esta ativa. `st.radio` nao permite renderizar elementos
intercalados entre as opcoes - opcoes vivem em uma lista fechada
sem hooks de "apos a opcao X". Loop de `st.button` permite
intercalar arbitrariamente.

**Implementacao** (`app.py:1494-1541`):

```python
if "aba_selecionada" not in st.session_state:
    st.session_state["aba_selecionada"] = "PLD"

abas_principais = [
    "PLD", "Reservatorios", "ENA/Chuva", "Despacho Termico",
    "Geracao", "Carga", "Curtailment",
]

for _aba_opcao in abas_principais:
    _is_active = (st.session_state["aba_selecionada"] == _aba_opcao)
    if st.button(
        _aba_opcao,
        key=f"nav_aba_{_aba_opcao}",
        type="primary" if _is_active else "secondary",
        use_container_width=True,
    ):
        st.session_state["aba_selecionada"] = _aba_opcao
        st.rerun()
    # Sub-itens condicionais (Fase Nav.2) ficam aqui dentro do loop

aba = st.session_state["aba_selecionada"]
```

Variavel `aba` retorna do session_state - 100% compativel com os 7
branches `if/elif aba == ...` (PLD, Reservatorios, ENA, Despacho
Termico, Geracao, Carga, Curtailment) sem mudancas nesses branches.

**CSS scoped Fase Nav.1**:
- Keys com prefixo `nav_aba_` permitem seletor scoped:
  `[data-testid="stSidebar"] [class*="st-key-nav_aba_"] button`.
- Alinhamento esquerdo: `text-align: left` + `justify-content:
  flex-start` no botao + seletores filhos (`button > div`,
  `button > div > p`, `button p`, `button[kind] *`) pra cobrir
  o `<p>` interno que Streamlit pode renderizar.
- Primary (ativo): `#F6BD16` amarelo Bauhaus + texto preto.
- Secondary (inativo): transparente + texto cream `#F5F1E8`.
- Hover em inativo: vira amarelo Bauhaus completo (replica visual
  do ativo) - feedback de "selecionavel".
- Hover em ativo: `opacity: 0.9` (escurecimento sutil).
- Compactacao: `margin-bottom: -1rem` no wrapper +
  `padding-top/bottom: 0.3rem` no botao - botoes proximos
  verticalmente.

**Trade-offs considerados**:
- **DOM injection** (manipular DOM do `st.radio` via JS): rejeitada
  por fragilidade. Streamlit reescreve a estrutura interna a cada
  rerun, JS hook precisa ser re-anexado, ordem de execucao nao eh
  garantida.
- **Radio fora-da-lista** (radio com 7 opcoes + bloco condicional
  separado depois): rejeitada por UX nao intuitiva. Sub-itens
  ficariam visualmente desconectados do item pai.
- **Botoes custom** (escolhido): cada botao eh um widget separado,
  intercalar elementos eh trivial, CSS scoped ataca `[class*="st-
  key-..."]` pra estilizar sem afetar outros botoes do app.

**Trade-off aceito**: perda da semantica de "radio group" pra
acessibilidade (screen readers). Mitigado parcialmente pelo
`type="primary"` que sinaliza estado ativo. Aceitavel pra dashboard
interno que nao tem requisitos de acessibilidade rigorosos.

**Commit**: `a43ffce` (86 inserts, 5 deletes).

**Quando aplicar este pattern em outras abas/sidebars**:
- Quando precisar intercalar elementos condicionais entre as
  opcoes de navegacao (sub-itens, separadores contextuais, badges
  de estado).
- Quando o radio default do Streamlit nao oferece controle visual
  suficiente (ex: alinhamento, hover customizado, indicador
  customizado por opcao).

**Quando NAO aplica**:
- Navegacoes simples sem hierarquia ou sub-itens. `st.radio`
  continua sendo a opcao mais limpa e acessivel.
- Listas dinamicas onde a quantidade de opcoes muda em runtime -
  loop de buttons funciona, mas a complexidade de gerenciar keys
  unicas cresce.

### 5.53 Sub-itens contextuais Eneva/SIN no sidebar + remocao dos pills (Fase Nav.2)

**Decisao**: o controle de sub-view do Despacho Termico (Eneva /
SIN) foi MOVIDO dos pills no topo do conteudo principal pra
**sub-itens contextuais embaixo do botao "Despacho Termico"** na
sidebar. Sub-itens visiveis apenas quando essa aba esta ativa.

**Caso que motivou**: o controle de sub-view conceitualmente eh
"qual variante da aba estou vendo" - pertence a navegacao, nao ao
conteudo. Pills no topo do conteudo:
1. Ocupavam ~80px verticais que poderiam ser usados pelos graficos
2. Duplicavam a hierarquia (radio aba + pill sub-view) - 2 niveis
   de selecao em lugares visualmente desconectados
3. Forcavam o usuario a procurar o controle no conteudo apos
   selecionar a aba

A Fase Nav.1 (decisao 5.52) preparou o terreno trocando o radio
por loop de botoes - permite intercalar sub-itens condicionais.

**Implementacao** (`app.py:1543-1561`):

```python
# Dentro do loop nav_aba_:
if _aba_opcao == "Despacho Termico" and _is_active:
    if "termico_subview" not in st.session_state:
        st.session_state["termico_subview"] = "Eneva"
    _subviews = [("Eneva", "Eneva"), ("SIN", "Sistema")]
    for _label, _valor in _subviews:
        _is_sub_active = (
            st.session_state["termico_subview"] == _valor
        )
        # Indicador ativo: caractere | amarelo via Python label
        _label_display = (
            f"| {_label}" if _is_sub_active else _label
        )
        if st.button(
            _label_display,
            key=f"nav_sub_{_valor}",
            type="primary" if _is_sub_active else "secondary",
            use_container_width=True,
        ):
            st.session_state["termico_subview"] = _valor
            st.rerun()
```

Mapeamento label visual `"SIN"` -> state value `"Sistema"` via
tuple `(label, valor)` - preserva compatibilidade com o branch
`if subview == "Sistema":` no conteudo (`app.py:3343` apos a
remocao dos pills).

**CSS scoped Fase Nav.2**:
- Keys `nav_sub_*` permitem seletor scoped sem vazar pros itens
  principais (`nav_aba_*`).
- Indentacao: `padding-left: 3rem` no botao + `padding-left:
  0.8rem` no wrapper externo. Sub-itens visivelmente deslocados
  em relacao aos itens principais.
- Texto menor (`0.85rem` vs `0.95rem` dos principais),
  `font-weight: 400`. Hierarquia visual: pai mais forte, filho
  mais leve.
- Inativo (secondary): cinza discreto `#999999`.
- Ativo (primary): cream `#F5F1E8`. Sem amarelo de fundo (que
  competiria com o amarelo do item pai ativo).
- Hover: amarelo discreto `#F6BD16` no texto inteiro.
- Compactacao: `margin-bottom: -1rem` entre wrappers + `padding-
  top/bottom: 0.2rem` no botao - mais compactos que itens
  principais (que usam `0.3rem`).

**Indicador ativo - 3 abordagens consideradas**:
1. **`::before` pseudo-elemento absoluto** (rejeitada): linha de
   3px posicionada em `left: 1.2rem`, `top/bottom: 25%`. Funcionou
   visualmente mas o posicionamento absoluto interferia com o
   flex layout interno do botao do Streamlit. Manter
   sincronizacao em diferentes alturas de botao exigia hardcoding.
2. **`border-left: 3px`** (rejeitada): controle de altura
   limitado (sem maneira simples de fazer linha curta). Forcaria
   compensar `padding-left` via `calc(3rem - 3px)`.
3. **Caractere `|` (U+2502) prefixado no label** (escolhida):
   inserido no Python via label dinamico (`f"| {_label}"` se
   ativo, `_label` se inativo). CSS `::first-letter` aplica
   `color: #F6BD16` + `font-weight: 700` apenas no caractere
   `|`. Solucao 100% no fluxo do texto - sem posicionamento
   absoluto, sem fragilidade de altura.

**Pills removidos do conteudo principal** (60 linhas, `app.py`
linhas 3168-3228 antes da remocao):
- Comentario sobre "Controle binario Sistema/Eneva - pills
  full-width estilo Curtailment"
- Bloco `st.markdown` com CSS scoped
  `[class*="st-key-termico_btn_subview_"]`
- `_sub = ...` + `st.columns(2)` + 2 `st.button` ("Eneva", "SIN -
  Despacho Termeletrico Total")

**Preservado intacto**:
- Init `termico_subview` default `"Eneva"` (`app.py:3150-3152`)
- Titulo dinamico h1 (linha 3157-3161): muda conforme
  `termico_subview` selecionado pela sidebar
- Border-bottom Bauhaus do titulo
- Branch HOISTED Fase E (linha 3168 apos remocao)
- Branch `if subview == "Sistema":` (`app.py:3343` apos remocao)

**Trade-off aceito**: a sidebar fica visualmente mais densa quando
"Despacho Termico" esta ativo (botao pai + 2 sub-itens). Aceitavel
porque (1) a densidade eh contextual (so aparece em 1 das 7 abas),
(2) o ganho de ~80px verticais no conteudo principal compensa, (3)
hierarquia visual fica explicita.

**Commit**: `c5ecf15` (82 inserts, 61 deletes).

**Quando aplicar este pattern em outras abas**:
- Qualquer aba que tenha sub-views (variantes da mesma aba).
  Atualmente nenhuma alem de Despacho Termico.
- Quando o controle de sub-view eh persistente durante a sessao
  (nao eh um filtro temporario) e merece ficar na navegacao
  hierarquica.

**Quando NAO aplica**:
- Filtros temporarios dentro do conteudo (granularidade,
  submercado, periodo). Esses pertencem ao conteudo, nao a
  navegacao - sao "visoes do mesmo dado", nao "variantes da aba".
- Casos onde o usuario alterna sub-views frequentemente (cada
  troca causa rerun completo da pagina). Pills inline tem latencia
  ligeiramente menor.

### 5.54 Drill-down hierarquico SIN — fases A/B/B.0/C/D (07/05/2026)

Implementa drill-down clicavel no SIN do Despacho Termico em 3 niveis
hierarquicos: Mensal -> Diario -> Horario. Aparece apenas em modo
Mensal (sub-view Sistema). Eneva e outras granularidades inalteradas.

**Fase Drill.1**: extrai logica de agregacao do bloco Sistema em
helper `_agregar_termico_sistema(df_filt, modo, unidade) -> tuple`
retornando `(agg, sufixo_unidade, fmt_hover)`. 4 branches preservados
(Mensal/Diario/Horario/Trimestral). Habilita reuso pelos drill-down.
Stats: +110/-94 (+16 net). Commit `acdb336`.

**Fase Drill.2.A**: helpers de filtragem + state init.
- `_filtrar_termico_por_mes(df_term, mes_ref)`: mask por `dt.year` +
  `dt.month`, retorna copia.
- `_filtrar_termico_por_dia(df_term, dia_ref)`: mask por `dt.date`,
  normaliza datetime->date.
- State `termico_sistema_drill_mes` (Timestamp normalizado): default
  = 1o dia do mes mais recente do dataset.
- State `termico_sistema_drill_dia` (date): default = ultimo dia do
  dataset.

**Fase Drill.2.B.0**: extrai construcao da figura SIN em helper
`_construir_figura_termico_sin(agg, gran_label, sufixo_unidade,
fmt_hover, paleta, height=450) -> go.Figure`. Substitui MOTIVOS_COLS
externo por `list(paleta.keys())` — single source of truth.

**Fase Drill.2.B**: bloco condicional embaixo do grafico mensal SIN
que renderiza 2 graficos drill-down em colunas 50/50:
- Esquerda: Diario do mes selecionado.
- Direita: Horario do dia selecionado.

Defaults via state inicializado em Drill.2.A. Stats Drill.2.A+B.0+B
combinados: +202/-102. Commits `108ab8f` (A+B.0) e `3de3704` (B).

**Fase Drill.2.C**: click em barras pra navegar.
- C.1: click numa barra mensal -> atualiza `drill_mes` + cascata
  pro ultimo dia do novo mes (regra UX: drill_dia sempre dentro
  de drill_mes).
- C.2: click no drill diario -> atualiza `drill_dia` (sem cascata).
- Drill horario: nao-clicavel (nivel mais detalhado).

**Fase Drill.2.D** (polish): captions dos drill migrados pra
`st.markdown` inline com div centralizado, single line:
- Drill diario: `"DIARIO . MES/AA . data_ini a data_fim"`.
- Drill horario: `"HORARIO . dd/mm/aaaa"`.
- Mensal SIN e Eneva mantem `_render_termico_chart_caption`
  (layout esquerda+direita).

C+D consolidados no commit `b1f5c72`.

**Quando aplicar este pattern**: outras abas com hierarquia natural
de drill-down (mensal -> diario, diario -> horario). Reusa helper
`_agregar_termico_sistema` (modo + unidade) e `_construir_figura_*`.

**Quando NAO aplica**: drill-down nao-hierarquico (ex: clicar em
serie pra mostrar series relacionadas em vez de zoom temporal).

### 5.55 Captura de click em Plotly via streamlit-plotly-events (07/05/2026)

`st.plotly_chart` com `on_select="rerun"` + `hovermode="x unified"`
no Streamlit 1.56 NAO captura click simples — `selection.points`
retorna vazio. Testado exaustivamente:

- `clickmode="event"` e `clickmode="event+select"`.
- `selection_mode=("points",)`.
- `update_traces(unselected=...)` pra eliminar opacity drop.
- `hovermode="closest"` em vez de "x unified".

Nenhuma combo nativa funciona. Click em barra dispara box-select mode
que esvazia `selection.points`.

**Solucao**: `streamlit-plotly-events==0.0.6` (lib externa). Captura
click via componente customizado em iframe, retorna `list[dict]` com
keys camelCase (`curveNumber`, `pointNumber`, `x`, `y`).

```python
from streamlit_plotly_events import plotly_events

_event = plotly_events(
    fig,
    click_event=True,
    select_event=False,
    hover_event=False,
    key="...",
    override_height=550,
)
if _event:
    _idx = _event[0].get("pointNumber")
    # ...
```

**Trade-offs aceitos**:
- Lib inativa desde 2021 (risco baixo 6-12 meses).
- `override_height` fixo (nao `use_container_width`).
- Toolbar Plotly com logo (config nao suportado pela lib).
- Plotly precisa ser `<6.0` (lib quebra com APIs internas do 6.x —
  graficos renderizam com eixos invertidos).

**Quando aplicar**: necessidade real de captura de click em barras
Plotly + nenhuma alternativa nativa do Streamlit funciona. Drill-down
SIN da decisao 5.54 e o caso de uso atual.

**Quando NAO aplica**: outras formas de captura mais simples
(selectbox, date_input, radio, button) cobrem a UX. Lib externa eh
ultimo recurso.

### 5.56 JS injection pra eliminar fundo preto do iframe streamlit-plotly-events (07/05/2026)

PROBLEMA: tema dark do Streamlit (`config.toml backgroundColor=#0a0d10`)
injeta `--background-color` DENTRO do iframe da `streamlit-plotly-
events` via mecanismo automatico de theming pra custom components.
CSS injection externo NAO atravessa iframe (cross-document policy).

Sintoma: iframes do `plotly_events` aparecem com bordas pretas em
volta do conteudo Plotly cream. CSS externo `iframe { background-
color: #F5F1E8 }` nao funciona — pinta o quadro do iframe, nao o
conteudo HTML interno.

**Solucao**: `components.html` com `<script>` que acessa
`window.parent.document` e injeta `<style>` dentro de cada iframe
da lib (allow-same-origin desde Streamlit 0.73):

```python
import streamlit.components.v1 as components

components.html("""
<script>
function fixPlotlyEventsBg() {
    try {
        const iframes = window.parent.document.querySelectorAll(
            'iframe[title*="streamlit_plotly_events"]'
        );
        iframes.forEach(iframe => {
            const innerDoc = iframe.contentDocument;
            if (!innerDoc) return;
            if (innerDoc.getElementById('bauhaus-bg-override')) return;
            const style = innerDoc.createElement('style');
            style.id = 'bauhaus-bg-override';
            style.textContent = `
                :root { --background-color: #F5F1E8 !important; }
                body { background-color: #F5F1E8 !important; }
                html { background-color: #F5F1E8 !important; }
            `;
            innerDoc.head.appendChild(style);
        });
    } catch(e) { console.warn(e); }
}
fixPlotlyEventsBg();
setInterval(fixPlotlyEventsBg, 500);
</script>
""", height=0)
```

**Detalhes da implementacao**:
- Polling 500ms via `setInterval` pra capturar reruns do
  `plotly_events` (componente re-mounta entre cliques).
- Idempotencia via `id="bauhaus-bg-override"` — skip se ja injetado.
- 3 seletores cobertos (`:root`, `body`, `html`) por defesa.
- `try/catch` pra bloqueio cross-document silencioso.
- `height=0` no `components.html` torna o iframe injetor invisivel.

**Limitacoes conhecidas**:
- Flicker preto de ate 500ms na primeira renderizacao (limite do
  polling).
- Depende de `allow-same-origin` (Streamlit components custom desde
  0.73 — sempre presente).
- Frágil a mudancas de versao do Streamlit (se atributo `title` do
  iframe da lib mudar, seletor quebra).

**Quando aplicar**: tema dark do Streamlit + custom component em
iframe + necessidade de override visual interno. Drill-down SIN da
decisao 5.54 + lib `streamlit-plotly-events` da decisao 5.55.

**Quando NAO aplica**: 
- Tema light do Streamlit (sem fundo preto pra eliminar).
- Custom components com `theme.backgroundColor` controlavel via API
  da propria lib (raro).

### 5.57 Dual-loader pattern pra preservar granularidade fina sem OOM (08/05/2026)

PROBLEMA: aba precisa expor multiplos modos de granularidade
(ex: Mensal/Diario/Trimestral/Horario), mas o dataset HORARIO
completo eh muito grande pro Cloud free tier (~1GB+).

ABORDAGENS REJEITADAS:
1. **Loader unico horario sempre**: estourava OOM no Cloud (df_termico
   1.19GB / 4.2M rows).
2. **Loader unico agregado diario sempre**: perdia modo Horario (que
   precisa granularidade nativa).
3. **Reduzir ano_ini pra 2024**: quick fix mas perdia historico.

SOLUCAO ESCOLHIDA: 2 loaders dedicados.

```python
# Loader principal: dataset agregado DIARIO, range completo.
@st.cache_data(ttl=21600)
def carregar_termico(ano_ini=2022) -> pd.DataFrame:
    """Schema 13 cols sem hora. ~175k rows, ~50MB."""
    # Loop: download mes -> agregacao diaria por mes -> concat
    # _normalizar_motivos + _mapear_eneva APOS concat (decisao global)

# Loader lazy: HORARIO de 1 unico dia.
@st.cache_data(ttl=21600)
def carregar_termico_horario_dia(dia: date) -> pd.DataFrame:
    """Schema 14 cols com hora. ~1900 rows, ~250KB."""
    # Carrega APENAS o parquet do mes do dia, filtra mask data == dia
```

USAGE PATTERN no app.py: override pos-filter pra Horario:
```python
# Filtro normal (Mensal/Diario/Trimestral):
df_filt = df_term[mask_periodo].copy()

# OVERRIDE pra Horario (modo single-day, decisao 5.46):
if gran_atual == "Horário":
    df_filt = carregar_termico_horario_dia(data_ini_normalizada)
```

VANTAGENS DA ESTRATEGIA HIBRIDA (vs agregar no loop com normalize
local):
- Preserva decisoes globais (ex: substituicao val_verifinflexpura
  baseada em sum() do dataset inteiro - Fase A.1).
- Zero risco semantico em comportamentos all-or-nothing.
- Pico transitorio de RAM no concat eh trivial (~30MB com cada mes
  ja agregado).

CACHE INVALIDATION:
clear_termico_cache deve limpar AMBOS:
```python
carregar_termico.clear()
carregar_termico_horario_dia.clear()
```

QUANDO APLICAR ESTE PATTERN:
- Dataset agregado_modo_default >>> dataset_modo_excecao em
  cardinalidade.
- Modo excecao opera em janela pequena (single-day, single-week).
- Cache hit ratio do modo excecao baixo o suficiente pra justificar
  N entradas no cache (cada dia eh uma chamada).

QUANDO NAO APLICA:
- Todos os modos precisam de granularidade fina.
- Janela do "modo excecao" eh tao grande quanto o default.
- Custo de duplicar pipeline (normalize/mapear/etc) supera ganho de RAM.

### 5.58 Padrao `scripts/investigar_*.py` (one-off untracked) (08/05/2026)

PADRAO: scripts de investigacao/diagnostico one-off ficam em
`scripts/investigar_*.py` ou `scripts/inspect_*.py`, **untracked**
(gitignored implicitamente - nunca committados).

POR QUE:
- Investigacoes sao especificas a sessao/contexto, raramente reusadas.
- Versionar polui historico git com codigo descartavel.
- Permanecer no disco preserva historico de raciocinio pra revisitar.
- Padrao consistente: prefixos `investigar_*` ou `inspect_*` distinguem
  one-off de utilitarios versionados (ex: `scripts/discover_ccee_ids.py`).

ONDE APLICAR:
- Reproducao de bugs em ambiente isolado (sem rodar Streamlit).
- Comparacoes RAW vs cached (armadilha 4.9 - coerce numerico).
- Pipeline end-to-end fora do app.py (debug de logica de loader).
- Validacao empirica de hipoteses arquiteturais.

EXEMPLOS:
- Sessao Despacho Termico (08/05/2026, commit `0ec63e9`):
  `comparar_cache_vs_bruto.py`, `investigar_razoes_extras.py` -
  confirmaram que loader produz numeros consistentes com formula manual.
- Sessao Equatorial (08/05/2026): `investigar_equatorial_sheets.py`,
  `investigar_pipeline_solar_equatorial.py`,
  `investigar_serie_temporal_equatorial.py` - validaram backend 100%
  funcional, isolando bug em UI runtime.
- Sessao termico (07/05/2026): `inspect_termico_multimes.py` -
  descoberta empirica de inflexpura retroativa.

TRADE-OFFS:
- Vantagem: nao polui git, preserva contexto de investigacao.
- Desvantagem: nao versionado, pode haver redundancia entre scripts
  similares de sessoes diferentes.
- Mitigacao: nomes descritivos + comentario inicial com data + objetivo.

QUANDO ELEVAR PRA UTILITARIO VERSIONADO (`scripts/<nome>.py` sem prefixo
investigar/inspect):
- Script vira reusable (ex: `discover_ccee_ids.py` rodado anualmente).
- Logica eh referenciada em decisao do CLAUDE.md.
- Outras sessoes precisam reproduzir o teste (validacao recurrente).

REGRA pratica de prefixo:
- `investigar_*`: hipotese-driven, especifica de sessao
- `inspect_*`: descoberta inicial de schema/dataset
- (sem prefixo): utilitario reutilizavel, versionado

### 5.59 Refactor UI Curtailment - remove sub-abas, adiciona toggle %/GWh (08-09/05/2026)

CONTEXTO: aba Curtailment originalmente tinha 3 sub-abas no topo (Visao geral
/ Por usina / Por grupo). Apos implementacao do dropdown "Entidade" (que
permite escolher SIN, grupo proprietario, ou usina individual em 1 controle),
as sub-abas viraram redundantes - o dropdown ja cobre os mesmos casos de uso.

DECISAO:
1. Remover botoes de sub-aba do topo, forcar sub_aba="Visao geral" hardcoded.
2. Preservar funcoes _render_por_unidade e _placeholder_em_construcao no
   arquivo (dead code intencional) - pode haver retorno no futuro.
3. Adicionar toggle binario %/GWh entre presets de periodo e date_inputs,
   default % (modo atual). Mesma decomposicao por razao (ENE/CNF/REL).
4. Adicionar linha "Total" no hover unified como ultima linha (soma das 3
   razoes no periodo, usando PCT_TOTAL ou FRUSTRADO_TOTAL_MWH ja calculados
   por serie_temporal).

POR QUE:
- UI mais limpa: 1 linha de controles em vez de 2.
- Dropdown ja eh entidade abrangente, botoes eram redundantes.
- Toggle GWh permite analise de magnitude absoluta (volume em GWh frustrados),
  complementando a visao relativa em % curtailment.
- Linha Total no hover responde a pergunta "qual o curtailment total deste
  periodo?" sem precisar de KPI extra.

PADROES TECNICOS APLICADOS:
- Toggle: parametro opcional unit_toggle_key no helper compartilhado
  _render_period_controls_curt. Backward compat (None = layout legado).
- State em st.session_state["curt_unidade"], valores "pct"|"gwh".
- Plot condicional em _render_visao_geral via leitura de session_state no
  topo da funcao (C-I em vez de passar param - 1 caller so).
- Trace invisivel pro Total: go.Scatter mode=markers opacity=0 +
  showlegend=False. Plotly agrega no hover unified automaticamente.

REVERSIBILIDADE: alta. Botoes de sub-aba ficaram em historico git (commit
725b4e7 contem o codigo removido). Funcoes _render_por_unidade preservadas
no arquivo. Toggle eh aditivo - remover unit_toggle_key=... no caller
desativa sem outras mudancas.

REFERENCIA: commit 725b4e7 (sessao Sao Paulo BR).

### 5.60 Equatorial Solar 4T25: correção mapeamento Excel + UX hover "Total (E+S)" (11/05/2026)

**Contexto:** durante implementação da sub-aba "Eólica/Solar por
Grupo" (sessão 11/05/2026, commit `1eb6c5a`), descobriu-se que o
dashboard mostrava 148 MWm 4T25 pra Equatorial Solar vs 99 MWm
que a Equatorial reporta em release como geração líquida.

**Investigação:**

- Release Equatorial 4T25: Portfólio Solar (líquido) = 213,3 GWh
  / 96,6 MWm; Constrained-Off = 129,5 GWh / 58,6 MWm; ex-CO
  (potencial) = 342,8 GWh / 155,2 MWm.
- `OUTPUT_MWH` no `_padronizar` captura geração LÍQUIDA
  (pós-curtailment, verificada), equivalente à linha "Portfólio
  Solar" do release. `FRUSTRADO_MWH` captura geração frustrada
  (Constrained-Off). `OUTPUT_MWH + FRUSTRADO_MWH` = geração
  potencial pré-corte (= "ex Constrained-Off" do release).
  Confirmado empiricamente em 11/05/2026: ratio 1,04× vs release
  Equatorial 4T25 nos 3 indicadores.
- Dataset constrained-off ONS NÃO contém TODAS as usinas — só as
  que tiveram apuração de restrição no período. Cada linha é uma
  apuração de restrição.
- Migração pra `geracao-usina-2` (SMF/CCEE) investigada e
  DESCARTADA: dataset retorna IDÊNTICO ao constrained-off pras
  3 usinas Solar Equatorial 4T25 (148,4 MWm em ambos pré-fix).
  Schema do dataset `geracao-usina-2` confirmou modalidade
  "Conjunto de Usinas" pras 3 entradas — agregação ONS no nível
  do POI, não há vazamento por UFV individual.
- CKAN `datastore_search` NÃO funciona pra `geracao-usina-2` — só
  metadados estão no índice; arquivos S3 precisam de download
  direto. Se migrar no futuro, loader v2 vai precisar baixar
  parquet direto + cache disco (sem 3-strategy cascade ao estilo
  curtailment).

**Nota didática sobre o schema `OUTPUT_MWH` vs `FRUSTRADO_MWH`:**
`OUTPUT_MWH` = geração verificada pós-corte (LÍQUIDA, o que de
fato foi gerado e despachado). `FRUSTRADO_MWH` = geração que
teria sido gerada mas foi cortada pelo ONS (constrained-off).
A soma = capacidade potencial pré-corte. Esta interpretação foi
empiricamente validada na sessão 11/05/2026 contra release
Equatorial 4T25 — interpretações alternativas (e.g. `OUTPUT` =
potencial) NÃO fecham a aritmética.

**Correção aplicada no Excel
`data/curtailment/unidades_geradoras.xlsx`:**

- Sheet `Solar` linha 75 (`CONJ. RIBEIRO GONÇALVES 500 KV`):
  `Proprietário` "Equatorial" → "Other".
- Justificativa: planilha oficial Equatorial mostra apenas 7 UFVs
  Ribeiro Gonçalves (I-IV, VI-VIII) com entrada em operação em
  23/05/2024. NÃO há expansão de fase II em 2025. O
  `CONJ. RIBEIRO GONÇALVES 500 KV` que apareceu no ONS em
  17/09/2025 é de outro proprietário (provável Enerside/FG
  Soluções, São Miguel SPE ou Raios do Parnaíba — não confirmado).
- Backup: `data/curtailment/unidades_geradoras.xlsx.bak.20260511`.
- Approach "re-atribuir pra Other" (não deletar linha):
  reversível, preserva cobertura, diff git mostra 1 célula.
- Edit via `openpyxl` (preserva formatação/metadados — `pandas
  to_excel` reescreveria do zero).
- Pós-edit: Equatorial Solar = 2 USINAs (Ribeiro Gonçalves +
  Barreiras II 500 KV). Aritmética 4T25 (script
  `teste_equatorial_solar_correto.py`):
  - LÍQUIDA (`OUTPUT_MWH`): 221,02 GWh / 100,1 MWm
  - FRUSTRADO_MWH (Constrained-Off): 136,39 GWh / 61,8 MWm
  - POTENCIAL (`OUTPUT + FRUSTRADO`): 357,41 GWh / 161,9 MWm
  - Ratios vs release: LÍQ 1,04× (100,1 vs 96,6), CO 1,05×
    (61,8 vs 58,6), POT 1,04× (161,9 vs 155,2).
  - Gap residual ~4% provavelmente perímetro contábil, MRE
    ou GSF.

**UX no hover do gráfico Eólica/Solar por Grupo:**

- Label "Total" trocado pra "Total (E+S)" pra deixar explícito
  que a soma é sempre das DUAS séries, independente de qual está
  visível no plot via toggle de legenda.
- `ljust` ajustado de 8 pra 12 chars pra preservar alinhamento
  monospace no hover unified.
- Bug original: usuário esconde Eólica via legenda; "Total"
  continua somando ambas porque a Trace 2 invisível usa
  `df["TOTAL_Y"]` pré-calculado (Plotly não recalcula em runtime).
  Solução escolhida: deixar claro no label que sempre é soma das
  duas — Plotly não tem hook nativo pra reagir a `visible` toggle.

**Resolução conflito de fonte Sertão Solar Barreiras (11/05/2026):**
consulta RI das companhias (Equatorial e Engie) confirmou que
CONJ. SERTÃO SOLAR BARREIRAS pertence à Engie. Excel atual estava
correto. Pesquisa externa do Nava (planilha Equatorial mencionando
'UFV Sertão Solar Barreiras XV-XXI') referia-se provavelmente a
outro ativo com nome comercial similar ou erro de descrição na
planilha consultada.

**Pendências pra sessões futuras:**

- Confirmar dono real de `CONJ. RIBEIRO GONÇALVES 500 KV` via
  ANEEL (atualmente em "Other").
- Caso decisão futura mude mapeamento: também afeta histórico
  da aba Curtailment (Excel compartilhado entre as 2 abas).
- Padronizar UX "Total (E+S)" na aba Curtailment (mesmo pattern
  hoje usa apenas "Total" no hover unified do
  `_render_visao_geral`).
- Gap residual ~4% em todos os 3 indicadores (LÍQ/CO/POT) entre
  dashboard pós-fix e release Equatorial 4T25 — provavelmente
  UFVs Tipo III/MMGD não cobertas pelo dataset constrained-off,
  ou perímetro contábil (MRE/GSF). Difícil quantificar sem
  cruzar com dataset MMGD separado.

**Sessão produziu:**

- `components/tab_geracao_grupo.py` editado (label Total →
  Total (E+S)).
- `data/curtailment/unidades_geradoras.xlsx` editado (1 célula).
- `data/curtailment/unidades_geradoras.xlsx.bak.20260511` (backup
  pré-edit).
- 15+ scripts untracked em `scripts/investigar_*.py` /
  `scripts/teste_*.py` documentando investigação (padrão decisão
  5.58).

**Quando aplicar este pattern:**

- Auditoria de mapeamento de proprietários no Excel deve ser
  feita SEMPRE com benchmark externo (release corporativo, IR,
  ANEEL/SIGA) antes de assumir que o cadastro está correto.
- Renomeações estilo "Total" → "Total (E+S)" em gráficos
  stacked/grouped com toggle de legenda: aplicar preventivamente
  quando o hover unified inclui uma soma agregada que não
  responde ao toggle de visibilidade. Custo: ~2 linhas;
  benefício: zero confusão de usuário.

**Quando NÃO aplica:**

- Renomeações cosméticas sem investigação numérica empírica
  prévia — risco de re-atribuir errado e introduzir bug
  silencioso (vide rejeição da hipótese inicial "BARREIRAS II →
  SERTÃO SOLAR" desta sessão, refutada por aritmética).

### 5.61 — Aba Modulação: spread de captura por (submercado, fonte)

**Objetivo:** calcular e visualizar o spread de captura — diferença entre o PLD médio ponderado pela geração de cada fonte e o PLD médio flat do período — por submercado.

**Definição matemática (Fórmula A — horária pura, decidida nesta sessão):**

```
spread = PLD_ponderado_pela_geração − PLD_flat
       = Σh(mwmed × pld) / Σh(mwmed)  −  Σh(pld) / N_h
```

Interpretação: spread positivo = fonte gera mais nas horas caras (ganha vs. alocação flat). Spread negativo = gera mais nas horas baratas (perde vs. flat). Métrica padrão de mercados de energia (PJM/ERCOT/AESO).

**Variantes consideradas e descartadas:**
- Fórmula B (agregação diária primeiro, depois ponderar): perde a riqueza intradiária, mascararia o efeito real em solar.
- Fórmula C (spread diário, média mensal dos spreads): mede outra coisa — comportamento típico de um dia, não captura ao longo do mês.

**Fontes:** hidro, eólica, solar (long-format, coluna `fonte`). Termica e nuclear excluídas (objetivo é renováveis variáveis + hidráulica).

**Submercados:** SE, S, NE, N. **SIN excluído** porque `load_pld_horaria()` não tem nativo (decisão arquitetural — derivação por ponderação fica como backlog).

**Período:** 2022-01-01 até última hora da interseção balanço × PLD (gap típico: PLD CCEE 1-2 dias atrás de balanço ONS).

**Granularidades disponíveis:**

| Granularidade | Presets | Default | freq pandas |
|---|---|---|---|
| Mensal | 12M / Máx | 12M | M |
| Trimestral | 12M / 24M | 24M | Q |
| Semanal | 1M / 3M | 3M | W (Mon→Sun) |

Reset automático do preset ao trocar granularidade.

**Arquitetura:**

- Módulo: `components/tab_modulacao.py` (~566 linhas).
- Registrado em `app.py:41` (import) e `app.py:7831-7833` (branch dispatch).
- Re-exportado em `components/__init__.py`.
- Padrão wrapper defensivo: `render_aba_modulacao` + `_render_aba_modulacao_impl` (replica padrão de Curtailment/Geração Grupo).
- Função pura de cálculo: `_calcular_spread(granularidade: str) -> pd.DataFrame` retornando colunas `periodo_inicio, submercado, fonte, spread_rs_mwh, mwmed_medio, n_horas`.
- Resolver de janela isolado em `_resolver_janela(df, preset_label, granularidade)` — função pura, testável.
- Formatador único `_fmt_periodo(ts, granularidade)` cobre os 3 formatos: `mai/26` (mensal), `2T26` (trimestral), `S19/26` (ISO week semanal).

**Cache 2-layer:**

- RAM: `@st.cache_data(ttl=30d)` em `_calcular_spread`.
- Disco: 3 parquets independentes por granularidade:
  - `~/.cache/dashboard-setor-eletrico/modulacao_spread_v2_mensal.parquet`
  - `~/.cache/dashboard-setor-eletrico/modulacao_spread_v2_trimestral.parquet`
  - `~/.cache/dashboard-setor-eletrico/modulacao_spread_v2_semanal.parquet`
  - TTL 24h (mais conservador que default 6h porque PLD demora a fechar).
- Prefixo `v2_` é intencional: schema mudou de `ano_mes` (v1) pra `periodo_inicio` (v2). Parquet v1 antigo fica órfão no disco — sem prejuízo.
- Reusa `_make_disk_cache_helpers` do `data_loader.py` (decisão 5.15).

**Schema validado (Sessão Modulação Fase 1, 11/05/26):**

- Balanço: 572.400 linhas pós-filtro, 5 submercados, 3 fontes, frequência horária estrita (1h), 0 nulls/duplicatas/negativos/gaps.
- PLD horária: schema `{data: datetime com hora, submercado: str, pld: float R$/MWh}`. Coluna de timestamp é `data` (não `data_hora`) — renomeada no merge.
- Frequência: estritamente horária em ambos, merge inner por `(submercado, data_hora)` sem necessidade de resample.

**UX (decisões cosméticas):**

- Layout: 4 gráficos full-width empilhados (SE → S → NE → N).
- Cada gráfico: grouped bar (3 séries), eixo Y autônomo (escalas diferentes entre submercados).
- Linha horizontal y=0 em cada gráfico (referência crítica positivo/negativo).
- Cores das fontes: replicadas localmente do `CORES_FONTE_GEN` do `app.py` (decisão 5.33 pendente de refator pra `utils/bauhaus_palette.py`). Hidro `#4A6FA5`, Eólica `#8FA31E`, Solar `#F6BD16`.
- Título por gráfico: `SPREAD DE MODULAÇÃO · {NOME_COMPLETO}` em Bebas Neue, padrão decisão 5.22.
- Subtítulo simplificado: `{Granularidade} · (R$/MWh)`.
- Labels acima/abaixo das barras: bold, 12px, cor da barra (decisão consciente sobre baixo contraste do solar amarelo sobre fundo creme — usuário aceita).
- Controles: selectbox de granularidade à esquerda + 2 botões preset à direita, layout `st.columns([2,4,1,1])`.
- Decimal BR no hover via `customdata` + `.replace(".",",")` (foolproof vs. `separators`).
- Tipografia hover: `'IBM Plex Mono', 'Courier New', monospace` (alinhamento por largura fixa).

**Armadilhas / pontos de atenção:**

1. **SIN pré-agregado no balanço:** o filtro `submercado.isin(["SE","S","NE","N"])` exclui explicitamente o SIN. Sem isso, double-count em agregações.
2. **Solar = 0 em ~50% das horas (noite):** spread em janelas curtas pode ficar ruidoso. Mitigado em granularidades maiores (mensal/trimestral). Verificado empiricamente: SE × Solar tem spread negativo consistente (-50 a -190 R$/MWh) — reflete realidade do mercado em 2024-2026 (excesso de oferta solar + hidro cheia em horas diurnas).
3. **`mwmed_medio` calculado mas não usado visualmente:** coluna pronta no DataFrame retornado para implementar badge "baixa representatividade" futura (ex: opacity reduzida quando `mwmed_medio < X`).
4. **MIN_HORAS por granularidade:** drop hard de períodos parciais — `mensal=672`, `trimestral=2136`, `semanal=168`. Último período do dataset pode ser cortado.
5. **Plotly `weight="bold"` em textfont:** requer Plotly ≥ 5.14 (projeto está em 5.24.1, OK).
6. **Categórico no eixo X:** labels pré-formatados via `_fmt_periodo`, `xaxis.type="category"`. Perde zoom semântico, ganha previsibilidade visual.

**Sequência de commits (5 commits em produção):**

| # | Hash | Mensagem |
|---|---|---|
| 1 | 86df183 | feat: registra aba Modulação na sidebar |
| 2 | f322a87 | feat: adiciona granularidade + labels + título completo |
| 3 | ce1fdbf | style: refina labels e subtítulo |
| 4 | 87acfa9 | style: simplifica subtítulo |
| 5 | 99d4cc8 | style: troca defaults de preset (trimestral 24M, semanal 3M) |

**Próximos passos pendentes (backlog):**

1. PLD nacional ponderado (média carga/geração ponderada dos 4 submercados) pra habilitar visualização SIN agregada.
2. Refator paleta Bauhaus pra `utils/bauhaus_palette.py` (decisão 5.33) — bloqueado por circular import, mas o backlog cresceu (Curtailment + Geração Grupo + Modulação duplicam constantes).
3. Badge "baixa representatividade" usando `mwmed_medio` (já calculado e disponível no DataFrame).
4. Avaliar se solar amarelo sobre creme nos labels precisa de mostarda escura `#8B7A0F` (decisão atual: manter cor da barra, validamos no uso).

### 5.62 Customização de st.button via CSS scoped: gotchas e patterns

Conjunto de patterns descobertos ao customizar botões Streamlit em
escopo restrito (ex: toggles, presets). Sessão combinou 2 problemas
distintos com a mesma raiz arquitetural — `st.button` tem estrutura
DOM aninhada que torna seletores ingênuos inúteis.

**Pattern 1 — Botões com `help=` ganham wrapper `stTooltipHoverTarget`
que rouba espaço interno.** Em colunas estreitas, o texto quebra em 2
linhas (sintoma observado: "GWh" → "GW"/"h"). Fix:

```css
[class*="st-key-"][class*="<sufixo>"] button {
    white-space: nowrap !important;
    padding-left: 0.25rem !important;
    padding-right: 0.25rem !important;
}
```

Aplicado em `tab_curtailment.py` pro toggle `%`/`GWh` (commit `6d08e43`).
Seletor casa pelo sufixo da key (`unit_pct`, `unit_gwh`), independente
de `key_prefix` no Python.

**Pattern 2 — Para mudar `font-size` do TEXTO do botão, mirar
descendentes, NÃO o `<button>` em si.** Estrutura DOM real:

```
<button>
  <div data-testid="stMarkdownContainer">
    <span>
      <div data-testid="stMarkdownContainer">
        <p>texto</p>   ← texto vive aqui
      </div>
    </span>
  </div>
</button>
```

`font-size` aplicado em `button` não cascateia porque o `<p>` interno
tem regra própria do CSS de markdown do Streamlit com maior
especificidade. Fix:

```css
[class*="st-key-<prefix>"] button p,
[class*="st-key-<prefix>"] button div,
[class*="st-key-<prefix>"] button span {
    font-size: 0.95rem !important;
}
```

Aplicado em ambas sub-views do Despacho Térmico (Eneva e Sistema)
nos botões de ano (`_btn_ano_`). Commit `a1fdead` substituiu
tentativa anterior `e3afa56` que aplicava no `<button>` direto e era
dead code visual.

**Diagnóstico via DevTools:** quando uma regra CSS scoped "não tem
efeito", inspecionar pela aba Elements + Computed pra ver QUAL regra
realmente está vencendo. F12 → click no elemento → Computed →
procurar a propriedade. Se a regra esperada nem aparece na lista de
aplicadas, é cascata/herança quebrada — alvo do seletor errado.

**Quando aplicar este pattern:** customização visual de st.button
fora do amarelo Bauhaus default (decisão 5.6) — toggles, presets,
botões com help=, etc.

**Quando NÃO aplica:** botões que herdam o estilo Bauhaus global
sem customização (type="primary" + sem help= e em coluna larga).

### 5.63 "Máx" → "Max" no Despacho Térmico (escopo restrito)

**Decisão:** padronizar o label do preset Mensal `"Máx"` (com acento)
pra `"Max"` (sem acento) APENAS nas sub-views Eneva e Sistema do
Despacho Térmico. Outras abas (PLD, Reservatórios, ENA, Geração,
Carga, Curtailment, Modulação) **mantêm `"Máx"`** — não fazem parte
do escopo.

**Razões:**

1. **Glifo mais estreito** — `M`/`a`/`x` ASCII ocupam menos largura
   visual que `M`/`á`/`x` (acento adiciona ~1-2px). Em colunas
   estreitas (Eneva: 0.6/9.9 ≈ 60px por botão), folga importa.
2. **Evita problemas de encoding** — consistente com armadilha 4.6
   (PowerShell + UTF-8 + BOM). Embora o Write tool e `git commit -F`
   tratem acentos corretamente, label sem acento no código simplifica
   debug futuro.

**CSS scoped acompanhou** — regras `_btn_p_` adicionadas em ambas
sub-views com `white-space: nowrap + padding 0.25rem + min-width: 0`
pra equalizar visual com `_btn_ano_` do Trimestral. Commit `5003674`.

**Trade-off da inconsistência:** outras 7 abas mantêm `"Máx"`. Razão:
remover acento em TODAS as abas exigiria refator massivo (≥30
substituições espalhadas), mas a aba Despacho Térmico tem o caso
mais crítico de espaço (`cols [0.6, 0.6, 2.9, 1.155, 1.155, 3.59]`).
Inconsistência aceita por escopo cirúrgico.

**Quando aplicar este pattern:** rename de label visual sob restrição
de espaço, ESCOPO RESTRITO, sem afetar arquitetura.

### 5.64 Refactor Trimestral: wrapper + calibragem :first-child (Fase H bis)

**Decisão:** botões de ano (2022/2023/2024/2025/2026/LTM) das
sub-views Eneva e Sistema do Despacho Térmico saíram da estrutura
plana de 8 colunas `[0.1 + 6×0.55 + 6.6]` (soma 10, com spacers nas
extremidades) pra **wrapper aninhado** que alinha exatamente com a
largura do selectbox "Trimestral" da row 1:

```python
with st.container(key="termico_<sub>_trimestral_row2"):
    col_anos_wrapper, _spc_anos = st.columns([3.55, 6.45])
    with col_anos_wrapper:
        cols_anos = st.columns(6)
        for i, ano in enumerate(anos_disponiveis):
            ...
            with cols_anos[i]:
                if st.button(str(ano), ...):
                    ...
        with cols_anos[5]:  # LTM
            if st.button("LTM", ...):
                ...
```

**Calibragem empírica via DevTools** — wrapper começou em `3.7`,
iterou pra `3.55` medindo deltas left/right entre o primeiro/último
botão e as bordas do selectbox. Padrão da Fase H estendido (Fase H
bis).

**Calibragem fina do botão 2022 (`:first-child`):** o pattern "Botões
colados" (margin-left: -10px em TODOS `_btn_ano_`, decisão Fase H —
Item 4) puxava o 2022 10px à esquerda do limite do wrapper. Regra
sobrescritora:

```css
[class*="st-key-termico_<sub>_btn_ano_"]:first-child button[kind] {
    margin-left: 3px !important;
}
```

Especificidade `:first-child` (10) + `[kind]` vence a global `_btn_ano_`
sem `:first-child`. **4 iterações empíricas:** -12px → -7px → -3px →
+3px (final, alinhado com o "T" de Trimestral).

**Font-size aumentado** de 0.78rem → 0.95rem nas regras `_btn_ano_
p,div,span` (decisão 5.62, pattern 2). Aproveita espaço extra do
refactor pra texto mais legível.

**Assimetria intencional Eneva ↔ Sistema** ⚠ — a regra
`_btn_ano_ button[kind]` mantém `min-width: 0 !important` em **AMBAS**
sub-views. Tentativa de remover só do Sistema (commit `4a005ea`,
descartado via `git reset --hard 871234f`) **causou regressão na
Eneva** — botão 2022 saiu do alinhamento calibrado. Causa exata não
investigada. **Regra:** não remover `min-width: 0` sem testar
visualmente nas DUAS sub-views.

**Pendência conhecida — SIN Trimestral, botão LTM:** no Sistema, o
LTM aparece visualmente mais largo que os botões de ano porque tem
`help="Últimos 4 trimestres (móveis)"` que reserva espaço pro ícone
do tooltip. **Não foi fixado nesta sessão.** Caminhos pra explorar
em sessão futura:
- (a) `max-width: 100%` no botão LTM
- (b) Remover `help=` do LTM (perde tooltip, ganha consistência)
- (c) Regra `:not(:first-child):not(:last-child)` com `min-width: 0`
  seletivo

**Commits da Fase H bis** (sessão 12/05/2026):

| # | Hash | Mensagem |
|---|---|---|
| 1 | `6d08e43` | fix(curtailment): GWh button label em 1 linha |
| 2 | `5003674` | fix(despacho-termico): botões 12M/Max + padroniza grafia |
| 3 | `b20d201` | style(despacho-termico): aumenta padding dos botões |
| 4 | `e3afa56` | style(despacho-termico): reduz font-size dos botões de ano (dead code visual — substituído pelo a1fdead) |
| 5 | `a1fdead` | fix(despacho-termico): seletor correto pro font-size dos anos |
| 6 | `871234f` | refactor(despacho-termico): alinhamento + tamanho dos botões de ano |

### 5.65 Armadilha: st.markdown com `<script>` é sanitizado pelo Streamlit

**Sintoma:** bloco `st.markdown("""<script>...console.log(...)</script>""",
unsafe_allow_html=True)` adicionado pra medição empírica de DOM **não
aparece no Ctrl+Shift+F do DevTools** (pelo texto único do script).
Nenhum log no Console. Nenhum erro também — silenciosamente removido.

**Causa:** apesar de `unsafe_allow_html=True`, Streamlit (versão atual)
sanitiza tags `<script>` por segurança. Outras tags HTML passam.

**Workarounds:**

1. **Pra medição empírica descartável (uso desta sessão):** colar JS
   direto no Console do DevTools (F12 → Console → paste). Não vai pro
   git. Pattern aplicado na Fase H bis:

   ```javascript
   (() => {
     const sel = document.querySelector('[class*="st-key-<key>"]');
     const r = sel.getBoundingClientRect();
     console.log(r.left, r.right, r.width);
   })();
   ```

2. **Pra JS persistente em produção** (não usado nesta sessão, mas
   pattern conhecido): `streamlit.components.v1.html()` cria iframe
   isolado onde scripts rodam. Pra acessar DOM da página pai, usar
   `window.parent.document` dentro do iframe. Decisão 5.56 documenta
   o pattern aplicado no drill-down do Despacho Térmico SIN.

**Quando aplicar este pattern:** sempre que precisar de JS no app
Streamlit. Determinar se é descartável (Console) ou persistente
(components.v1.html).

**Quando NÃO aplica:** se basta CSS pra resolver — preferir CSS
sempre que possível.

### 5.66 DthAtualizaCadastralEmpreend é proxy confiável de "data de conexão" MMGD

Investigação empírica B.5 (Commit E 196a427) validou:
- Cross-check de 5 cutoffs MMGD vs gold standard EPE PDGD
- Viés ~2% nos anos com referência oficial (dez/2024: +1.9%, dez/2025: +2.4%)
- Sem evidência de picos artificiais por migração SISGD→MMGD (set/2025)
- 4.3M linhas; distribuição UCs por ano coerente com expansão real do setor

Antes da B.5: assumia-se que `DthAtualizaCadastralEmpreend` era proxy enviesada (~30%+) porque seria "data da última atualização cadastral", não "data de conexão". Hipótese descartada empiricamente — campo é razoavelmente próximo da entrada em operação real.

Implicações arquiteturais (não implementadas hoje, registradas pra próxima sessão):
1. Loader MMGD pode evoluir de hardcoded → dinâmico via SQL workaround §4.11 (5 cutoffs em ~20s, cache 24h, fallback hardcoded)
2. Carry-forward atual `abr/2026: 45.000 MW` provavelmente subestimado: SQL real retorna 48.032 MW
3. Anchors INFERIDOS 2022/2023 (20.000/28.000 MW) eram otimistas: reais ~18.100/26.600 MW

Não implementar mudança nos anchors sem nova validação com release PDGD ~abr/2027 (próximo gold standard).

### 5.67 Loader MMGD dinâmico via SQL CKAN com fallback hardcoded coexistindo

**Decisão (Sub-sessão G, Commit G 22403c5):** capacidade MMGD passa a ser carregada dinamicamente via ANEEL CKAN `datastore_search_sql` (workaround §4.11), com fallback automático pros anchor points hardcoded de `data_loader_aneel_mmgd.py` quando >50% das queries falham. Os 2 loaders **coexistem** — não há substituição/remoção do hardcoded.

**Arquitetura em 3 camadas:**

1. **`data_loaders/data_loader_aneel_mmgd_sql.py`** (NOVO): loader primary com queries paralelas via `ThreadPoolExecutor(max_workers=12)`, `timeout=60s`/query. Cache 2 camadas — `@st.cache_data(ttl=30d)` RAM + parquet local em `cache/mmgd_sql/`. Convenção de index: 1º do mês (igual SIGA — cutoffs de query usam fim de mês pra capturar todos os cadastros, INDEX retornado normaliza pra 1º). Expõe `attrs['source'] = 'sql_live'` quando query funciona.

2. **`data_loaders/data_loader_aneel_mmgd.py`** (PRESERVADO): anchor points hardcoded EPE PDGD. Função `load_mmgd_anual()` continua exportada. O loader SQL importa essa função como `load_mmgd_anual_fallback`. Expõe `attrs['source'] = 'fallback_anchors'` quando acionado.

3. **`components/tab_capacidade.py`** (consumer): chama `load_mmgd_anual()` do módulo SQL. Lê `serie.attrs['source']` pra escolher mini-nota visual (texto preto "ANEEL CKAN (live)" vs cinza "anchors hardcoded (ANEEL indisponível)"). Modo Mensal usa o mesmo padrão com `load_mmgd_mensal()` — quando `unavailable`, omite a 6ª trace MMGD do stack.

**Razão pra preservar o hardcoded como fallback:**

- ANEEL CKAN é flaky — sessão G observou 1 ciclo onde 5/5 queries retornaram HTTP 502/timeout (degradação completa transitória). Sem fallback, aba quebraria.
- Anchors do hardcoded são valores OFICIAIS publicados pela EPE PDGD (dez/2024: 36.200; dez/2025: 45.000) — não são estimativas internas. Servem como ground truth conservador.
- Custo de manter coexistência é baixo: ~94 linhas de loader hardcoded, atualizado anualmente (PDGD release abr/AAAA). O SQL loader importa e chama numa linha.

**Threshold de fallback `_MAX_FALHA_PCT = 0.5`:**

Se >50% das N queries paralelas falham, `_query_series_paralela()` retorna `None` e cai pro fallback. Razão: 1-2 falhas em 5 queries (≤40%) ainda é recuperável com warning em stderr; >50% indica degradação sistêmica do endpoint, não flakiness pontual.

**Convenção de cutoffs:**

- **Anual:** `dez/2022, dez/2023, dez/2024, dez/2025` (fixos, cobrem regime Lei 14.300/2022 + 2 anos com gold standard PDGD) + 5º cutoff = **último mês fechado** (não `today()`). Em hoje=2026-05-12, query usa `2026-04-30` e index retorna `2026-04-01`. Razão: mês corrente é parcial e bate com a última linha SIGA (também `2026-04-01`).
- **Mensal:** 12 cutoffs = 12 últimos meses fechados (exclui mês corrente). Mesmo padrão de re-indexação.

**Validação empírica (G.2 + G.4 + G.5.a):**

| Cutoff | SQL real | Anchor hardcoded | Δ |
|---|---|---|---|
| dez/2022 | 18.122 MW | 20.000 (INFERIDO) | −9,4% |
| dez/2023 | 26.633 MW | 28.000 (INFERIDO) | −4,9% |
| dez/2024 | 36.885 MW | 36.200 (CONFIRMADO PDGD) | +1,9% ✓ |
| dez/2025 | 46.061 MW | 45.000 (CONFIRMADO PDGD) | +2,4% ✓ |
| abr/2026 | 48.032 MW | 45.000 (carry-forward) | +6,7% |

SQL real bate com PDGD oficial dentro do viés ~2% documentado em §5.66. Anchors INFERIDOS 2022/2023 estavam otimistas (−5 a −10%) e carry-forward abr/2026 estava subestimado (+7%) — predições da §5.66 confirmadas empiricamente.

**O que esta decisão NÃO faz:**

- **Não remove** o hardcoded. Permanece como rede de segurança.
- **Não atualiza** os valores dos anchors com base no SQL real (substituir 20.000 → 18.122 etc). Pendência registrada em §5.66, dependente do próximo release PDGD (~abr/2027).
- **Não introduz** versionamento de cache (pattern §5.34). Cache disk atual é `cache/mmgd_sql/` simples; §4.12 documenta o risco de cache órfão pós-fix de convenção.

**Quando aplicar este padrão em outros loaders:**

Loaders que dependem de endpoint externo flaky com fonte fallback estática (sempre verdadeira mas potencialmente desatualizada) podem replicar:

- Primary: HTTP/SQL dinâmico com cache 2 camadas.
- Fallback: dataset estático curado manualmente.
- Sinalização: `attrs['source']` propagado pro consumer escolher UX (mini-nota cinza vs preta).
- Threshold de fallback: ≥50% falhas (configurável).

Candidatos futuros se surgir flakiness: CCEE PLD (tem cascade interno mas sem fallback estático), ENA ONS, carga ONS (caso S3 fique flaky).

### 5.68 Refactor PLD: filtragem via legenda + SIN só no data layer + reativação semanal

**Decisão (Sub-sessão pós-Commit-H):** 3 mudanças cirúrgicas consolidadas em commit único na aba PLD — remoção dos checkboxes SE/S/NE/N/SIN (filtragem migrada pra legenda nativa do Plotly), remoção do submercado SIN de toda a camada de UI (preservando dados), e reativação da granularidade "PLD médio semanal" (removida do dropdown em commit `bc8f466`, 1 mai 2026, que também introduziu a constante `_PLD_DEFAULTS_POR_GRANULARIDADE` da §5.36; loader intacto em `data_loader.py:865`).

**Motivação UX:** os 5 checkboxes ocupavam uma régua inteira logo abaixo dos botões de período, mais um guard "selecione ao menos um" que prendia o usuário em estado vazio. Plotly já oferece filtragem nativa via legenda (clique no item esconde/mostra a trace) — pattern conhecido e gratuito. Migração pra legenda reduz superfície de estado (sem `submercados_selecionados`/`mostrar_media` em session_state), elimina o caso de borda do guard, e libera ~25 linhas verticais. SIN removido da UI por análise de redundância — média dos 4 submercados é visualmente inferível do gráfico, e PLD é determinado por submercado individual (não pelo agregado sistêmico).

**Data layer preservado:** `pivot["Média BR"]` (`app.py:1991`) continua sendo computado (1 linha, custo trivial) e `CORES_SUBMERCADO["Média BR"]` (`app.py:103`) permanece na paleta global. Decisão consciente: se SIN voltar à UI no futuro (mudança de produto), o esforço é mínimo. Custo de manter dead code local: aceitável. Outras abas (Reservatórios, ENA, Geração, Capacidade, Carga, Curtailment) **não foram tocadas** — continuam consumindo SIN normalmente.

**Reativação do semanal — default 12M e ghost trace pro hover:** loader `load_pld_media_semanal` já existia (`data_loader.py:865`). `bc8f466` foi multi-escopo (remoção do semanal + introdução de `_PLD_DEFAULTS_POR_GRANULARIDADE` da §5.36); esta sub-sessão reverteu apenas a remoção do semanal (3 entradas: import, `GRANULARIDADES`, `opcoes_ordem`) e adicionou 3 entradas novas (entrada `"semanal"` em `_PLD_DEFAULTS_POR_GRANULARIDADE`, em `LABELS_GRAN`, e em `hoverformat`) + o ghost trace condicional — sem mexer no helper introduzido pela §5.36. Default 12M (365 dias) escolhido pra capturar ciclo úmido+seco completo (52 semanas) — bate com preset existente. **Hover unified** ganha primeira linha "Semana: DD/MM a DD/MM/YYYY" via trace `go.Scatter` invisível com `customdata` pré-computado — pattern de trace ghost análogo ao `TOTAL` no hover da Capacidade (Commit G). `xaxis.hoverformat` é format string estático que **não suporta aritmética temporal**, então o range exige customdata pré-computada via `pd.Timedelta(days=6)` no momento do render (recomendação do próprio `_normalize_semanal`). Customdata em formato 2D explícito (`[[s] for s in range_strs]`) pra evitar comportamento ambíguo do Plotly com customdata 1D.

**Trade-offs aceitos:**

1. **Filtragem por legenda só funciona no gráfico** — card "Último dia" e tabela "Estatísticas" mostram sempre os 4 submercados (HTML estático sem hook de legenda). Conscientemente preservado: tabelas servem como referência, não exploração.
2. **Hover semanal tem redundância leve** — header (`06/01/2025`) + ghost (`Semana: 06/01 a 12/01/2025`) coexistem. Sub-opção "header vazio + ghost" descartada porque header vazio sinaliza visualmente "info ausente"; header redundante é mais claro semanticamente.
3. **`pivot["Média BR"]` virou órfã dentro da PLD** — variável local computada mas não usada localmente. Custo trivial vs benefício de flexibilidade futura.

**Fora de escopo:**

- **Não remove** `CORES_SUBMERCADO["Média BR"]` da paleta global (`app.py:103`) — outras abas podem usar.
- **Não atualiza** a docstring desatualizada de `_normalize_semanal` (`data_loader.py:865-868`) — registrada como débito técnico em §9.1.
- **Não introduz** disk-cache pro semanal — decisão preservada (`data_loader.py:1593-1594`: "semanal/mensal NÃO recebem disk-cache").

### 5.69 Disk-cache pro PLD semanal e mensal (Frente 1 da sub-sessão pós-e152458)

**Decisão (Frente 1 da sub-sessão pós-e152458):** `load_pld_media_semanal` e `load_pld_media_mensal` ganharam disk-cache via `_make_disk_cache_helpers` (decisão 5.15), revisando o comentário de `data_loader.py:1593-1594` que excluía explicitamente as 2 granularidades. Pattern idêntico ao do diário/horário PLD: 1 parquet consolidado por loader em `~/.cache/dashboard-setor-eletrico/`, `try_read` no topo da função com early-return + reset de `_debug_erros`, `try_write` após cold load. Zero breaking change — assinatura e schema públicos preservados. `clear_cache()` estendido pra unlinkar os 2 novos parquets (tupla cresceu de 6 pra 8 disk-caches), mantendo a promessa "Atualizar = começar do zero" da docstring. Docstring desatualizada do semanal corrigida no mesmo commit (resolve caminho mínimo do §9.1).

**Motivação:** o commit `e152458` (decisão 5.68) reativou a granularidade semanal no dropdown PLD após meses fora da UI. Uso real revelou cold load de poucos segundos visível na UI — o comentário antigo ("datasets menores, dor menor") tinha sido escrito quando o semanal estava fora da UI; premissa mudou. Smoke test pós-implementação do semanal descobriu que o mensal sofria do mesmo problema (cold ~1.9s, não medido antes desta sub-sessão), justificando expansão de escopo dentro da mesma Frente 1. Horário ficou fora — Frente 2 separada, pattern estruturalmente diferente (já tem disk-cache desde a Sessão 1.5b, gargalo é ambíguo e requer diagnóstico antes de otimização).

**Pattern e escolhas técnicas:** replicação mecânica do pattern do diário (`data_loader.py:832-839`). Helpers criados via `_make_disk_cache_helpers("pld_media_semanal", ttl_sec=60 * 60 * 24)` e `_make_disk_cache_helpers("pld_media_mensal", ttl_sec=60 * 60 * 24)` no mesmo bloco dos 2 disk-caches PLD pré-existentes. TTL 24h alinhado com a frequência semanal de publicação CCEE (ciclo natural de atualização do semanal); pro mensal fica conservadoramente coberto pela mesma janela (re-baixar dataset de ~10KB a cada 24h é custo trivial, e mantém consistência arquitetural entre os 2 loaders). Estilo `60 * 60 * <horas>` segue o padrão dominante do projeto (`_DEFAULT_DISK_CACHE_TTL_SEC`, `@st.cache_data(ttl=60 * 60 * X)` etc.). Pendência colateral identificada: durante a redação inicial desta decisão, foi detectado que `clear_cache()` (`data_loader.py:1870`) não cobria os 2 novos parquets — fix incluído no mesmo commit por escopo natural (tupla de unlinks cresceu de 6 pra 8 elementos, docstring e comentário inline atualizados pra "8 disk-caches" / "8 parquets").

**Números empíricos medidos durante a sub-sessão:**

| Cenário | Semanal | Mensal |
|---|---|---|
| Baseline (pré-fix) | 4.013s | 1.856s |
| Cold pós-fix (cache vazio) | 3.004s | 1.654s |
| Warm-disk (RAM zerada) | 0.011s (~365×) | 0.020s (~92×) |
| Warm-RAM (mesma sessão) | sem print (cache intercepta) | sem print |

Tamanhos finais dos parquets: semanal ~33 KB (~5.200 linhas), mensal ~11 KB (~1.200 linhas). Paths reais: `~/.cache/dashboard-setor-eletrico/pld_media_semanal.parquet` e `pld_media_mensal.parquet`.

**Fora de escopo / trade-offs:**

- **TTL conservador pro mensal:** 24h é agressivo em relação à frequência de publicação mensal (1× por mês), mas evita debate sobre fronteira correta (12h? 7 dias?) — escolha de consistência com o semanal, custo trivial.
- **Horário do PLD** fica pra Frente 2 separada. JÁ tem disk-cache (decisão 5.15 aplicada na Sessão 1.5b); o gargalo de cold load não foi mensurado nesta sub-sessão.
- **Alternativo do §9.1** (adicionar coluna `data_fim` no `_normalize_semanal`): caminho mínimo aplicado (docstring corrigida), mas a coluna em si não foi adicionada. Comentário interno em `_normalize_semanal:551` mantém a decisão original ("pra evitar guardar coluna derivada"); reavaliar se houver consumidor adicional além do hover do PLD semanal de §5.68.

### 5.70 Disk-cache por ano fechado pro PLD horário e diário (Frente 2 da sub-sessão pós-883acec)

**Decisão (Frente 2 da sub-sessão pós-883acec):** `_download_year_pld_historico` (`data_loader.py:319`) refatorado pra usar disk-cache por ano fechado no lugar do `@st.cache_data(ttl=30d)` RAM da Sessão 1.5b. Cada `(ano, dataset)` ganha 1 parquet `pld_{dataset}_{ano}.parquet` em `~/.cache/dashboard-setor-eletrico/`, gerenciado via novo helper lazy `_get_pld_year_disk_helpers(ano, dataset)` (memoizado em dict global `_PLD_YEAR_HELPERS_CACHE`). Aplicado a horário + diário (escopo B-ambos — ambos os loaders compartilham `_download_year_pld_historico`). `clear_cache()` estendido com loop sobre `DATASET_YEARS_AVAILABLE` pra cobrir os parquets por ano fechado. Docstrings de `load_pld_horaria` e `load_pld_media_diaria` reescritas + comentário do bloco PLD (`data_loader.py:1619`) ganhou parágrafo final sobre Frente 2. Zero breaking change na API pública — assinatura e schema preservados.

**Motivação:** a Frente 2 começou após percepção subjetiva de lentidão no Cloud (~2-3s sentidos pelo usuário em rede móvel, classificado como "tolerável, só na primeira navegação" antes de medir empiricamente). O commit `883acec` (decisão 5.69) deixou o horário fora do escopo da Frente 1 explicitamente — "pattern estruturalmente diferente, gargalo ambíguo, requer diagnóstico antes de otimização". Instrumentação calibrada em `load_pld_horaria` (timer wrapper) + `_load_dataset` (acumuladores `download_total`, `normalize_total`, `ram_hits`, `http_calls` ao longo do loop por ano) revelou cold load real entre ~67s e ~76s em 2 medições no mesmo dia (variabilidade da API CCEE), com **~98% do tempo em HTTP** (~65-75s de download em 6 anos = ~11-13s/ano via Akamai). A docstring antiga mencionava "Disk-cache reduz pra ~1-2s", mas esse número era referente ao disk-cache consolidado (TTL 6h) — pós-expiração ou pós-restart do container, cold real reaparecia. Diagnóstico confirmou: as 3 camadas existentes (RAM externo 12h + RAM por ano 30d + disk consolidado 6h) cobriam *refresh dentro do mesmo processo*, mas **não cold restart do container do Streamlit Cloud free tier**. Solução aplicada: persistir os ~150-320 KB/ano em parquets individuais no disco com TTL 30 dias.

**Pattern e escolhas técnicas:**

- **Lazy via dict global** (`_PLD_YEAR_HELPERS_CACHE: dict[tuple[int, str], tuple] = {}`): chave `(ano, dataset)` espelha a ordem de argumentos de `_download_year_pld_historico(ano, dataset)`. Cada entry guarda os 4 callables retornados por `_make_disk_cache_helpers` — `(get_path, is_fresh, try_read, try_write)`. Primeira chamada de `_get_pld_year_disk_helpers(ano, dataset)` cria; chamadas subsequentes reusam.
- **Reuso da fábrica** `_make_disk_cache_helpers` (decisão 5.15): herda toda a infra de path cascade (`~/.cache/dashboard-setor-eletrico/` → `tempfile.gettempdir()`), write_test idempotente, error handling silencioso em FS read-only.
- **TTL 30 dias**: anos fechados são imutáveis na CCEE (mesma premissa da decisão 5.15 do balanço ONS). Aceita raras reedições — janela longa minimiza re-download HTTP.
- **String `"disk-cache-ano"`** retornada por `_download_year_pld_historico` quando disk hit — diferencia de `"disk-cache"` (consolidado) e de `"api"`/`"dump"`/`"pda"`/`"falhou"` (cascata HTTP) na chave `fontes_por_ano_horaria` em session_state debug.
- **Decorator `@st.cache_data(ttl=30d)` removido** de `_download_year_pld_historico`: tornou-se redundante porque o cache RAM externo de `load_pld_horaria` (TTL 12h) já intercepta múltiplas chamadas dentro de uma sessão. Manter as 2 camadas RAM seria duplicação sem benefício. Análise feita no design da Fase 3 antes da implementação — não foi remoção "casual".
- **Escopo B-ambos**: horário e diário compartilham `_download_year_pld_historico` — refactor de 1 função cobre ambos sem código duplicado. Decisão tomada na Fase 3 do design.

**Números empíricos** (medidos via instrumentação `[PERF horaria-frente2]` + `[PERF _load_dataset:horaria]` em runtime local Windows, 13/05/2026):

| Cenário | Tempo total | Significado |
|---|---|---|
| A — Cold first-run pós-deploy | **~67s** | Parquets por ano vazios; 6 HTTP calls, 0 disk hits |
| B — Cold pós-fix (parquets populados) | **~15s** | 5 disk-cache-ano (anos fechados) + 1 HTTP (ano corrente) |
| C — Warm-disk consolidado | **~33ms** | Disk hit do consolidado intercepta antes de `_load_dataset` |
| D — Warm-RAM (mesma sessão) | **sem print** | `@st.cache_data` externo intercepta antes do wrapper |

Speedup **B vs A: ~4,3×** (cenário recorrente — quando os parquets por ano estão populados, caso típico após primeira chamada de `load_pld_horaria` pós-restart do container). Volume processado: **188.064 linhas** consolidadas (horário pós-2021). Tamanhos dos 5 parquets por ano (horário):

| Ano | Tamanho |
|---|---|
| 2021 | ~320 KB |
| 2022 | ~242 KB |
| 2023 | ~228 KB |
| 2024 | ~282 KB |
| 2025 | ~320 KB |

Total horário: ~1,4 MB em disco. Diário **não foi medido empiricamente** nesta sub-sessão — mesma infra aplicada, mesma mecânica (5 anos fechados + 1 ano corrente), speedup análogo esperado.

**Fora de escopo / trade-offs:**

- **Streamlit Cloud disco efêmero (free tier):** parquets por ano são apagados a cada restart do container. Disk-cache cobre apenas a janela entre restarts. Mitigação real (storage externo tipo S3) está fora do escopo desta sub-sessão. Pra os usuários, a Frente 2 garante que o cold pesado só aconteça na *primeira* chamada de `load_pld_horaria` após cada restart do container do Cloud (deploys ou hibernation por inatividade ~20-30min no free tier) — chamadas subsequentes (dentro do TTL 30d) pegam disk-cache-ano nos parquets populados pela primeira chamada.
- **Diário não foi medido empiricamente** nesta sub-sessão. Mesma infra aplicada, speedup análogo esperado, mas sem confirmação por números reais. Tarefa futura se relevante.
- **Semanal/mensal não migrados** pra disk-cache por ano: já cobertos pelo disk-cache consolidado da Frente 1 (decisão 5.69); volume muito menor (~33 KB e ~11 KB consolidados) não justifica complexidade adicional.
- **Cache RAM 30d removido** de `_download_year_pld_historico`: análise pré-implementação concluiu que era redundante (RAM externo de `load_pld_horaria` já cobre o cenário de múltiplas chamadas mid-session). Caso a análise esteja errada e o ganho do RAM 30d seja relevante em algum cenário não antecipado, o fix é trivial (re-adicionar o decorator), mas aumentaria consumo de RAM.
- **Deprecation warnings observadas durante medições** (`st.components.v1.html` removal pós-2026-06-01; `use_container_width` → `width`): registradas em memória do projeto. Fora do escopo desta decisão.

### 5.71 Lazy loading do PLD horário via modal de confirmação (Frente 3 da sub-sessão pós-ff5d700)

**Decisão (Frente 3 da sub-sessão pós-ff5d700):** `load_pld_horaria` ganhou parâmetro `incluir_historico_completo: bool = False`, criando 2 variantes do dataset com disk-caches consolidados separados: `pld_horaria_recente.parquet` (default, ~2 anos = ano corrente + anterior, TTL 6h) e `pld_horaria.parquet` (canônico preservado, anos 2021+ completos, TTL 6h). UI da aba PLD horário dispara modal de confirmação `@st.dialog` antes de carregar histórico completo — botão "Máx" em modo recente abre o modal `_confirmar_historico_completo_pld_horario` em vez de filtrar o dataset diretamente. State `pld_horaria_historico_completo: bool` persiste a escolha em `session_state`; flag intermediária `_pld_horaria_pending_modal` desacopla helper compartilhado `_render_period_controls` do modal. Helper recebeu 2 params opcionais (`max_help_text_override` + `on_max_click_override`, defaults `None` preservam comportamento dos 5 outros callers existentes). `tab_modulacao.py:224` ajustado pra passar `incluir_historico_completo=True` explícito — preserva comportamento da aba Modulação que precisa do histórico completo pra computar spread em janelas longas. `clear_cache()` estendido pra cobrir as 2 novas keys de session_state + o parquet recente (tupla cresceu de 8 pra 9 disk-caches consolidados).

**Motivação:** o commit `ff5d700` (decisão 5.70) reduziu o cold load do horário de ~75s pra ~15s no cenário recorrente via disk-cache por ano fechado. Mas sintoma reportado no Cloud free tier: primeira chamada de `load_pld_horaria` após restart do container ainda atinge ~80s — pior caso onde container reiniciou (parquets por ano apagados) E latência CCEE Akamai é alta. UX dolorosa pra usuário que só queria ver o PLD horário do mês corrente. Análise: a grande maioria das navegações pra aba PLD horário consulta dados recentes (último mês, último trimestre); histórico completo é caso de uso minoritário (research, análises longas). Conclusão: torna default carregar só 2 anos recentes (~30s pior caso) e deixa o histórico completo como ação explícita do usuário, com modal de confirmação avisando do custo (~1-2 min na 1ª vez). Trade-off: usuário que quer todo o histórico paga 1 clique extra; usuário típico ganha rapidez na navegação default.

**Pattern e escolhas técnicas:**

- **Estrutura híbrida modal:** interna 1:1 com `_confirmar_historico_completo_gen` da Geração (`@st.dialog` + markdown bold + caption + 2 botões Cancelar/Carregar). Disparo via flag intermediária replicado do Curtailment (`_on_max_pld_horario_request` seta `_pld_horaria_pending_modal=True` + rerun; consumo no próximo render com `state.pop(...)` + dispatch do modal). Razão pra híbrido: helper compartilhado `_render_period_controls` não pode chamar `@st.dialog` direto sem complicar sua API genérica — flag desacopla.
- **State naming:** `pld_horaria_historico_completo` espelha `gen_historico_completo` da Geração (mesma semântica: bool sticky em session_state, default `False`, reset por `clear_cache`). Flag intermediária `_pld_horaria_pending_modal` com underscore inicial diferencia de state persistente.
- **Naming dos disk-caches:** `pld_horaria.parquet` mantido como canônico (modo completo = behavior anterior preservado, zero invalidação de cache existente); variante recente sufixada como `pld_horaria_recente.parquet`. Assimetria intencional pelo naming: variante completa = nome canônico, variante recente = sufixo descritivo. Considerado renomear pra `pld_horaria_completo.parquet` (simetria) mas rejeitado pra evitar lixo invisível em caches Cloud + localhost.
- **Range de anos:** modo recente = `[ano_corrente - 1, ano_corrente]` (2 anos calendário). Modo completo = `DATASET_YEARS_AVAILABLE["horaria"]` (lista discreta atual: 2021-2026). Range completo usa lista derivada de `RESOURCE_IDS_BY_DATASET`, atualiza automaticamente quando CCEE publicar 2027.
- **Parametrização de `_load_dataset`:** adicionado `anos_override: list[int] | None = None` (backward-compat, default cai pra `DATASET_YEARS_AVAILABLE[dataset]` se omitido). Permite `load_pld_horaria` reusar `_load_dataset` em vez de duplicar o loop por ano. 3 callers existentes (diária/semanal/mensal) não passam o param → comportamento inalterado.
- **Spinner dinâmico:** branch `granularidade == "horario"` em `app.py` com 3 textos baseados em `is_pld_horaria_cache_fresh(modo)` + `pld_horaria_historico_completo`: cache fresh → `"Carregando dados de PLD horário..."`; cold modo completo → `"Baixando histórico completo... 1 a 2 min na primeira vez."`; cold modo recente → `"Baixando últimos 2 anos... ~30s na primeira vez."`. Outras granularidades preservam o spinner genérico `"Carregando dados da CCEE…"`.
- **Tooltip do Máx em modo recente:** `"Carregar histórico completo (desde 01/01/2021) — 1 a 2 min na 1ª vez"`. Sem este override, tooltip default `f"Máx — desde {min_d.strftime(...)}"` seria enganoso em modo recente (mostraria 01/01/2025, sugerindo que Máx volta só até 2025 quando na verdade abre modal pra carregar 2021+).

**Validação empírica + trade-offs:**

Smoke test runtime durante o desenvolvimento confirmou backward compat dos 3 outros loaders PLD: `load_pld_media_diaria/semanal/mensal` retornam datasets completos sem mudança (`anos_override=None` default preserva comportamento). Smoke test do `load_pld_horaria(False)` retornou 47.808 linhas com `[2025, 2026]`; `load_pld_horaria(True)` retornou 188.064 linhas com `[2021-2026]`. Smoke test estático dos 6 callers do `_render_period_controls` confirmou que apenas o caller do PLD horário em modo recente passa os 2 params novos (Reservatórios, ENA, Geração, Carga, PLD não-horário, PLD horário em modo completo: todos preservam defaults `None`). Validação visual via Streamlit local em 7 cenários (modo recente cold/warm-disk/warm-RAM + modal com Carregar/Cancelar + modo completo cold/warm-disk/warm-RAM) reproduziu Cenário B da Frente 2 (~15s cold modo completo com parquets por ano populados). **Fora de escopo:** diário/semanal/mensal não migrados pra lazy loading (cold de ~5-30s não justifica complexidade adicional; default é histórico completo nos 3). **Frente 3.1 aplicada na sequência (mesma sub-sessão pós-ff5d700):** adicionou linha horizontal + range de datas à direita na aba PLD, espelhando padrão visual de outras abas (Reservatórios, ENA, Geração, Carga, Curtailment). Pattern inicial (flexbox com 2 spans, análogo às outras abas) deu desalinhamento visual — selectbox e range em rows verticais separadas pelo fluxo Streamlit. Migrou pra Estratégia B (st.columns([3, 2]) + 2 widgets separados + linha horizontal como `<div>` isolado abaixo) que garantiu alinhamento horizontal real. 3 polish edits cosméticos adicionais: removeu border-bottom do CSS do selectbox, removeu texto 'Indicadores do dia DD/MM/YYYY' (duplicava o range), borda da régua KPIs single-day mudou de #1A1A1A → #CCCCCC (régua coerente com 4 cards + dropdown). Pendência cosmética identificada na validação visual: texto do spinner dinâmico aparece com cor pouco visível (registrada em memória do projeto, sessão futura). Aba Modulação pode futuramente ganhar lazy loading análogo (registrada em memória do projeto, sessão futura).

### 5.72 Lazy loading da aba Modulação via modal de confirmação (análogo à Frente 3 do PLD)

**Decisão:** `_calcular_spread` (`components/tab_modulacao.py`) ganhou parâmetro `incluir_historico_completo: bool = False`, criando 2 variantes do cálculo de spread com disk-caches separados por granularidade — `modulacao_spread_v2_recente_{g}.parquet` (default, PLD horário recente ~2 anos) e `modulacao_spread_v2_{g}.parquet` (canônico preservado, histórico desde 2022). São 6 parquets no total: o dict `_DISK_CACHE_HELPERS` foi re-chaveado de `{g}` pra `{(modo, g)}`. A aba dispara modal `@st.dialog` `_confirmar_historico_completo_modulacao` (interno ao componente) antes de carregar o histórico completo — o botão "Máx" da granularidade Mensal em modo recente abre o modal em vez de filtrar direto. State `mod_historico_completo: bool` persiste a escolha em `session_state`; flag intermediária `_mod_pending_modal` desacopla o clique do botão da abertura do modal. Novo helper exportado `clear_modulacao_disk_cache()` (limpa RAM de `_calcular_spread` + os 6 parquets + o state) é chamado pelo botão "Atualizar" da sidebar (`app.py`) junto com `clear_cache()` — cobre um gap pré-existente (os parquets da Modulação nunca tinham sido cobertos pelo "Atualizar"). Zero breaking change na assinatura pública de `_calcular_spread` (param novo tem default).

**Motivação:** a primeira carga da aba Modulação levava >40s porque `tab_modulacao.py` chamava `load_pld_horaria(incluir_historico_completo=True)` incondicionalmente — o caminho mais lento que existe (o "monstro de ~80s" do PLD horário, decisão 5.70/5.71). A própria §5.71 já tinha sinalizado "Aba Modulação pode futuramente ganhar lazy loading análogo". Análise dos presets default: Mensal 12M (12 meses), Trimestral 24M (24 meses), Semanal 3M (13 semanas) — nenhuma visão default precisa de mais de 2 anos *exceto* o Trimestral 24M. Conclusão: torna o modo recente (~2 anos) o default e deixa o histórico completo como ação explícita, espelhando a Frente 3 do PLD.

**Pattern e escolhas técnicas:** réplica estrutural da Frente 3 (§5.71). Modal colocado *dentro* de `tab_modulacao.py` (não no `app.py` como o do PLD horário) pra manter o componente autocontido — `@st.dialog` funciona em qualquer módulo. Disparo via flag intermediária `_mod_pending_modal` replica o pattern do `_pld_horaria_pending_modal`. Naming dos disk-caches: variante completa mantém o nome canônico `modulacao_spread_v2_{g}.parquet` (zero invalidação de parquets já no disco), recente sufixada `_recente_` (assimetria intencional, idêntica ao `pld_horaria.parquet` vs `pld_horaria_recente.parquet` da §5.71). `clear_modulacao_disk_cache` mora no componente (não no `clear_cache()` do `data_loader.py`) porque `data_loader` não pode importar de `components` sem risco de import circular — `app.py` chama as duas funções em sequência no handler do "Atualizar".

**Trade-off aceito — Trimestral 24M parcial em modo recente:** `load_pld_horaria(False)` traz exatamente 2 anos calendário (`[ano_corrente-1, ano_corrente]`), que no meio do ano somam <24 meses. O preset default Trimestral 24M (8 trimestres) então mostra ~5 trimestres em modo recente (validado: 5 trimestres, 2025-Q1→2026-Q1 em 14/05/2026). `_resolver_janela` degrada graciosamente (mostra os períodos disponíveis, título reflete o range real) e o usuário que quer os 24 meses cheios clica "Máx" → modal → histórico completo. Mensal 12M e Semanal 3M são sempre cobertos pelos 2 anos recentes. Decisão consciente: não vale adicionar uma 3ª variante de range ao `load_pld_horaria` (a §5.71 deliberadamente o deixou binário recente/completo) só pra cobrir 1 preset.

**Validação empírica (smoke test runtime local, 14/05/2026):** modo recente Mensal cold em 11.2s (192 linhas, 2025-01→2026-04, 4 submercados) — vs. o caminho antigo que forçava o histórico PLD completo. Modo completo: 624 linhas, 2022-01→2026-04 (leu o parquet canônico pré-existente, 0.0s). Trimestral recente: 5 trimestres. Semanal recente: 70 semanas (default 3M = 13 semanas, amplamente coberto). 6º parquet `modulacao_spread_v2_recente_mensal.parquet` criado no disco (~7.8 KB). Compile-check OK em `app.py` + `tab_modulacao.py`.

**Fora de escopo:** (1) **Spinner estático mantido** — `_calcular_spread` tem `show_spinner` fixo no decorator `@st.cache_data`; spinner dinâmico (como o da §5.71 pro PLD horário) é awkward com o decorator e o modal já avisa "1 a 2 min". (2) **`load_balanco_subsistema` não restringido a modo recente** — o merge inner com o PLD recente (~2 anos) já clipa o output naturalmente; o balanço tem cache próprio (16 anos + disk-cache) e não expõe variante "recente". (3) **Parquet v1 órfão** `modulacao_spread_mensal.parquet` (schema pré-v2) continua no disco sem prejuízo — mesma situação registrada na §5.61. (4) `components/__init__.py` não re-exporta `clear_modulacao_disk_cache` — `app.py` importa direto do submódulo.

**Follow-up A (mesma sub-sessão) — uniformização dos presets + renomeação de rótulo:** dois ajustes pequenos sobre a base da §5.72. (1) **Trimestral: preset "24M" → "Máx".** O "24M" era enganoso em modo recente (a §5.72 já registrou o trade-off: `load_pld_horaria(False)` traz <24 meses no meio do ano, então 24M mostrava ~5 trimestres). Trocado pelo botão "Máx" com o mesmo critério do Mensal — dispara o modal de confirmação e carrega o histórico completo. `DEFAULT_PRESET_POR_GRANULARIDADE["trimestral"]` passou de `"24M"` pra `"12M"`. A máquina genérica de "Máx lazy" (`eh_max_lazy = label == "Máx" and not historico_completo`) já cobre o trimestral sem código novo; o guard defensivo `preset_atual not in labels_validos` migra state antigo (`"24M"` persistido) pro default. Layout de botões inalterado — trimestral continua com 2 presets. (2) **Rótulo "captura" → "modulação"** na caption abaixo do título ("Spread de modulação (R$/MWh) = ...") e no spinner do `_calcular_spread` ("Calculando spread de modulação..."). Decisão de vocabulário do produto — alinha com o nome da aba e os títulos dos gráficos (que já eram "SPREAD DE MODULAÇÃO"). Docstrings/comentários internos com "captura" não foram tocados (não são user-facing; "spread de captura" continua sendo o termo técnico de mercado). **Pendente pra próxima etapa da sub-sessão:** (3) adicionar "Máx" ao Semanal, (4) date_inputs início/fim à direita (padrão das outras abas — torna o "Máx" usável em todas as granularidades, inclusive semanal que senão mostraria ~220 barras), (6) parar de dropar o último período parcial — `GRANULARIDADE_MIN_HORAS` corta o mês/trim/semana corrente; o usuário quer ver a média parcial até a última data disponível.

**Follow-up B (mesma sub-sessão) — "Máx" no Semanal + date_inputs início/fim e refatoração do controle de período:** itens (3) e (4) do pendente acima. (3) **Semanal ganhou preset "Máx"** — `PRESETS_POR_GRANULARIDADE["semanal"]` passou de 2 pra 3 presets (`1M / 3M / Máx`), uniformizando o critério de primeira-carga em todas as granularidades. (4) **Date_inputs início/fim** adicionados na mesma linha dos controles, ancorados à direita (padrão das outras abas). Isso exigiu uma **refatoração do modelo de estado** do `_render_aba_modulacao_impl`: a fonte de verdade do recorte deixou de ser o label do preset (`mod_periodo_preset`, removido) e passou a ser o par de datas `mod_data_ini`/`mod_data_fim` em session_state. Os presets viraram atalhos que *setam* essas datas (via `_resolver_janela`); o destaque "primary" do botão é derivado por `_preset_ativo` (novo helper — compara a janela atual com a que cada preset produziria; retorna `None` quando o usuário escolheu datas custom). **NÃO reusa `_render_period_controls`** do app.py — aquele helper é day-based (`delta_days`/`timedelta`), e a Modulação conta *períodos* (mês/trim/semana), então o controle é próprio e period-aware. Layout: `st.columns([2, 1, 1, 1, 5.2, 1.5, 1.5])` — 7 colunas FIXAS (dropdown, 3 slots de preset, spacer, 2 datas); granularidades com 2 presets deixam o 3º slot vazio, com espaçamento visual idêntico ao caso de 3 presets. O `_calcular_spread` foi movido pra **antes** dos botões/date_inputs no fluxo (precisa do `df_spread` pra resolver presets→datas e pra definir `min_value`/`max_value` dos date_inputs). Pitfalls cobertos: (a) **clamp defensivo** das datas em `[min_d, max_d]` antes de instanciar os date_inputs — evita `StreamlitAPIException` se o dataset encolheu (completo→recente via "Atualizar"); (b) **troca de granularidade preserva as datas** [comportamento revisto na §5.73 — só datas *custom* persistem; datas não-custom re-derivam pro default da nova granularidade] — `mod_data_ini`/`mod_data_fim` são datas de calendário absolutas, portáveis entre granularidades (só muda o agrupamento mês/trim/semana); o clamp em `[min_d, max_d]` cobre as diferenças de range. Implementação: **layout de colunas fixo + sem `st.rerun()` na troca de granularidade**. (Histórico desta sub-sessão, vale registrar a armadilha: v1 dava `pop` nas datas na troca — resetava de propósito, errado; v2 só removeu o `pop` — **ainda resetava**, porque o `st.rerun()` explícito na troca de granularidade interrompia o script antes dos date_inputs renderizarem, e o Streamlit limpa keys de widget não-renderizado, apagando `mod_data_ini`/`mod_data_fim`; v3 = layout de 7 colunas fixo elimina a necessidade de rerun pra reconstruir o `st.columns`, então os date_inputs renderizam em todo run e as keys sobrevivem.); (c) **ordem de execução** — botões de preset (`cols[1..3]`) executam antes dos date_inputs (`cols[5..6]`) no código, então setar `st.session_state["mod_data_ini"]` no handler do botão + `st.rerun()` é seguro (widget ainda não instanciado nesse run) — mesmo pattern do `_render_period_controls`; (d) guard `data_ini > data_fim` → warning em vez de gráfico vazio. O modal `_confirmar_historico_completo_modulacao` parou de setar `mod_periodo_preset="Máx"` e agora seta a flag `_mod_pending_max` — consumida no render seguinte (após o `df_spread` completo carregar) pra aplicar a janela Máx sobre o dataset completo. `clear_modulacao_disk_cache` estendido pra dar `pop` em `mod_data_ini`/`mod_data_fim`/`mod_periodo_preset`/`_mod_pending_modal`/`_mod_pending_max` (além de `mod_historico_completo`). **Validação:** compile-check OK; smoke test do round-trip preset→`_resolver_janela`→`_preset_ativo` bate pros 3 defaults e pro "Máx" nas 3 granularidades; app sobe HTTP 200. **Não testado em browser nesta sessão** (extensão Chrome desconectada) — interação dos date_inputs (clamp, troca de granularidade, clique de preset, modal) precisa de verificação visual. **Fora de escopo:** date_input não faz "snapping" pro início de período — se o usuário escolher 10/05 em granularidade mensal, o período de maio (início 01/05) fica de fora do filtro `periodo_inicio >= data_ini`; comportamento consistente e os presets dão janelas limpas, mas registrar se virar atrito de UX. Pendente da sub-sessão: item (6) — período parcial corrente.

**Follow-up C (mesma sub-sessão) — rótulo do Semanal: numeração ISO → data do 1º dia da semana.** O Semanal mostrava `S19/26` (semana ISO + ano ISO), que exige contar semanas de cabeça. Trocado pela **data do primeiro dia da semana** (freq `W` → segunda-feira), formato tradicional e legível. `_fmt_periodo` ganhou parâmetro `longo: bool = False` que **só afeta o semanal**: `longo=False` → `DD/MM` (ex.: `06/01`), `longo=True` → `DD/MM/AA` (ex.: `06/01/26`). Mensal (`mai/26`) e trimestral (`2T26`) ignoram `longo` — já carregam o ano. Aplicação dos 3 contextos com formatos deliberadamente diferentes (não precisa ser o mesmo em tudo — compacto onde aperta, completo onde há espaço): **eixo X** usa `DD/MM` (cabe mais barras, ex. preset Máx com 70+ semanas); **título** (canto sup. direito) usa `longo=True` → `DD/MM/AA a DD/MM/AA`; **hover** ganha uma linha `Semana de DD/MM/AA`. O hover `x unified` mostra como header o valor do eixo X (que é o `DD/MM` curto), então pra injetar o ano sem ambiguidade foi adicionado um **trace fantasma** `go.Scatter` (`marker opacity=0`, `showlegend=False`, `customdata` 2D pré-computada) — pattern idêntico ao do PLD semanal (§5.68), adicionado antes das barras pra aparecer como 1ª linha do hover. Trace fantasma só é criado quando `granularidade == "semanal"`. Redundância leve aceita (header `06/01` + linha `Semana de 06/01/26`), mesma decisão consciente registrada na §5.68. Validação: compile-check OK, `_fmt_periodo` confere os 3 formatos × curto/longo, app sobe HTTP 200. **Não testado em browser** (extensão Chrome desconectada) — render do eixo/título/hover precisa de conferência visual.

**Follow-up D (mesma sub-sessão) — item (6): exibir o período parcial corrente.** O `_calcular_spread` dropava todo período com `n_horas < GRANULARIDADE_MIN_HORAS` (decisão 5.61, armadilha #4) — o que cortava o mês/trimestre/semana corrente, sempre incompleto. O usuário quer ver o spread acumulado **até a última data disponível**. Mudança cirúrgica no filtro: mantém o drop de períodos parciais **exceto o último** (`g["periodo_inicio"] == g["periodo_inicio"].max()`) — o período corrente passa, exibido com a média parcial das horas disponíveis; períodos parciais *no meio* da série (gaps históricos, raros — dados são horário-estrito) continuam dropados. Validação empírica pós-mudança (14/05/2026): mensal mantém 2026-05 (288h vs min 672), trimestral mantém Q2/2026 (1008h vs min 2136), semanal mantém a semana de 11/05 (48h vs min 168) — todos com as 12 linhas (4 submercados × 3 fontes). Os 6 parquets `modulacao_spread_v2_*` foram **deletados** ao aplicar a mudança (foram computados com o filtro antigo; sem isso o cache serviria dados sem o período corrente por até 24h — TTL). **Trade-offs aceitos:** (1) o último período parcial pode ser **ruidoso** — ex.: a semana corrente pode ter só ~2 dias de dados (48h), e solar é 0 em ~50% das horas (§5.61 armadilha #2); decisão consciente do usuário (quer ver "até a última data"). (2) **Sem distinção visual** do período parcial — a barra parece igual às completas; `n_horas` e `mwmed_medio` estão no DataFrame se um badge "parcial"/"baixa representatividade" for desejado no futuro (§5.61 armadilha #3). (3) Cache do período parcial fica até 24h estável (TTL) — período corrente "cresce" mas só re-renderiza no próximo ciclo de cache; aceito (§5.61 já escolheu TTL 24h conservador). **Fecha a sub-sessão da aba Modulação** (itens 2-6 todos aplicados; ver Follow-ups A-D).

### 5.73 Polish visual da sidebar + aba PLD; re-derivação de datas na troca de granularidade da Modulação

Sub-sessão de ajustes visuais (sidebar + aba PLD) e um fix de UX na aba Modulação, consolidados num commit único.

**Sidebar (`app.py`, 3 ajustes):** (1) título "Dashboard Setor Elétrico" → "Setor Elétrico · Brasil" (mesma classe `.sidebar-title`, separador `·` — padrão do projeto pra títulos); (2) ícone de pessoa (SVG inline, `fill="currentColor"` herda o cinza do `.sidebar-username`) antes do nome do usuário — `.sidebar-username` virou `display:flex; align-items:center; gap:0.4rem`; (3) "BBI Utilities Team:" → "BBI Utilities Team" (sem `:`). O rodapé da página (`app.py` ~linha 8019, fora da sidebar) mantém "Dashboard Setor Elétrico" — fora de escopo.

**Aba PLD — polish de layout da granularidade diária (`app.py`):** (a) caixa "ÚLTIMO DIA" (`.kpi-ultimo-row`): borda `#1A1A1A` → `#CCCCCC` (mesmo cinza dos KPIs do PLD horário, `.pld1d-kpi-card`/`.st-key-kpi_submercado_detalhe`); fontes internas levemente maiores. (b) "Estatísticas do período" + range de datas unidos numa linha só, num `<div>` em vez de `<h3>` — remove a `border-bottom` global do `h3` (decisão de UX: o cabeçalho preto da própria tabela já ancora visualmente); `margin` reposicionado (topo maior, base zero) + `.bauhaus-table` com `margin-top` negativo pra colar a tabela no rótulo. (c) distância controles→linha→gráfico reduzida via margens negativas no `<div>` da linha horizontal. (d) legenda do gráfico (SE/S/NE/N): fonte `17 → 22`, `legend.y 1.02 → 1.12`, `margin t 30 → 52`, `height 290 → 312` (área de plot ~240px preservada) — sobe a legenda pra ocupar de forma equilibrada o vão entre a linha e o gráfico. (e) seta ▾ do dropdown de granularidade: `font-size 1.7em → 1.85em` + `position:relative; top:0.06em` (maior e mais baixa, alinhada ao texto). **Revertido:** tentativa de aumentar a fonte do título "PLD MÉDIO DIÁRIO" (que é um selectbox achatado) — o BaseWeb renderizava mal em tamanho maior, voltou pro `1.1rem` original. Os valores de (c), (d), (e) são calibragem visual fina, ajustados em iterações com o usuário no Streamlit local (browser-automation indisponível nesta sessão).

**Aba Modulação — re-derivação de datas na troca de granularidade (revisa §5.72 Follow-up B(b)):** a §5.72 fez as datas persistirem entre granularidades. Mas mensal/trimestral/semanal têm `max_d` diferentes (01/mai, 01/abr, última segunda do dataset), e o clamp `[min_d, max_d]` prendia `data_fim` no menor `max_d` já visto — a aba passava a abrir sem o período corrente (ex.: trocar pra trimestral fixava `data_fim` em 01/abr e isso "vazava" pras outras granularidades). **Fix:** flag `mod_datas_custom`. Enquanto `False` (usuário não mexeu nos date_inputs), trocar de granularidade **re-deriva** a janela pro preset default da nova granularidade — que sempre alcança o último período disponível (validado por smoke test: default de cada granularidade resolve até o respectivo `max_d`). Quando `True` (usuário editou um date_input — detectado via `on_change=_marcar_datas_custom`), a janela custom persiste + clampa, como na §5.72. Clique de preset e confirmação do modal "Máx" zeram a flag (seleção "gerida", não custom). Novo state `mod_granularidade_anterior` detecta a troca de granularidade (comparação no fluxo, sem `st.rerun()` — mantém o fix de widget-state da §5.72 Follow-up B). `clear_modulacao_disk_cache` estendido pra `pop` em `mod_datas_custom` + `mod_granularidade_anterior`.

**Validação:** compile-check OK em `app.py` + `components/tab_modulacao.py`; app sobe HTTP 200; smoke test do round-trip preset→`_resolver_janela` confirma que o default de cada granularidade alcança o último período. Ajustes visuais do PLD confirmados pelo usuário por inspeção no Streamlit local.

### 5.74 Sub-aba "Receita por Empresa" da Modulação

**Decisão:** a aba Modulação virou um container de 2 sub-views (padrão das sub-views da Geração — §5.37): **"Por Submercado/Fonte"** (a aba original, `tab_modulacao.py`) e **"Receita por Empresa"** (nova, `components/tab_receita_modulacao.py`). Estima a receita de modulação por empresa de geração, por trimestre do ano corrente, em R$mn.

**Wiring (`app.py`):** import de `render_aba_receita_modulacao` no topo; sub-nav na sidebar dentro do loop de abas (`if _aba_opcao == "Modulação" and _is_active:` — state `modulacao_subview`, espelha o bloco da Geração); dispatch `elif aba == "Modulação":` ramifica por `modulacao_subview`.

**Modelo de cálculo:** `receita = (ACL + Spot, MWmed→MWh) × spread_ponderado × horas / 1e6`, onde `spread_ponderado = Σ_fonte (aloc%_fonte × spread_fonte)` — o spread de modulação de cada fonte (hidro/eólica/solar) do(s) submercado(s) da empresa, ponderado pelo mix de fontes da empresa. Vem do `_calcular_spread("trimestral")` da aba Modulação (lido pras 3 fontes, não só hidro). **A receita pode ser negativa** (empresa muito exposta a solar → spread negativo → perda). Trimestre fechado: trimestre cheio; trimestre corrente: pró-rata via `n_horas` + estimativa do cheio; trimestres futuros: estimativa com o spread ponderado corrente carregado pra frente.

**Empresas (`EMPRESAS_SUBMERCADO`):** Auren (SE), Cemig (SE), Engie (S), Copel (S), EQTL (NE) — 1 submercado cada; **Axia** é caso especial (ACL = média do spread de N+NE+SE+S; Spot = média de N+NE). Ordem alfabética case-insensitive.

**Duas tabelas editáveis (`st.data_editor` em blocos lado a lado — padrão da §5.73 Follow-up B):** (1) **Premissas — Vendas ACL e Spot (MWmed) + Spread**: ACL/Spot editáveis; coluna Spread read-only nos trimestres reais (spread ponderado apurado) e editável nos futuros (default = spread ponderado corrente). (2) **Alocação entre fontes da capacidade firme total (%)**: Hidro/Eólica/Solar editáveis por empresa×trimestre, default 100% hidro. Validação com aviso se uma linha não soma 100% (o `st.data_editor` não força a soma — célula-residual auto não atualiza de forma confiável no widget, mesma família de limitações do canvas/tema global já registradas).

**Ordem de render (containers):** a tabela 2 (alocação) é processada ANTES da tabela 1 no código (a tabela 1 precisa da alocação pra computar o spread ponderado), mas posicionada visualmente DEPOIS via `st.container()` reservado. O gráfico também usa container reservado no topo.

**Spread dos trimestres futuros — "None = auto, valor = override":** o default segue a alocação via `_spreads_auto` (spread ponderado do último trimestre real, **recalculado a cada render**). É editável. Ao salvar, `_para_salvar` grava `None` quando o valor bate com o auto (continua seguindo a alocação no reload) e o valor só quando é override manual. **Armadilha resolvida:** a 1ª versão pré-preenchia o spread futuro uma vez só (congelava no default hidro); a correção foi não pré-preencher + base do editor = `spreads_auto` recalculado. Mais: saves antigos (schema sem alocação) tinham spreads futuros congelados — resolvido com **versionamento** (`_PREMISSAS_VERSAO`): JSON de versão anterior é ignorado no load; chave de sessão versionada (`receita_premissas_base_v2`) força reload no schema novo.

**Persistência:** premissas (ACL/Spot/spread-override + alocação) salvas por usuário em `data/premissas_receita_modulacao.json` (gitignored — estado de runtime). Botão "Salvar premissas" usa `st.toast` (notificação transitória — some sozinha, evita a impressão de salvamento automático). No Streamlit Cloud o disco é efêmero (persiste só entre restarts — mesma ressalva do disk-cache).

**Gráfico:** barras trimestrais empilhadas por empresa (toggle de empresa via botões primary/secondary), **cor única vermelho Bauhaus** (`#D62828`) — "Realizado" sólido, "Estimativa" no vermelho esmaecido (`_blend` com o creme, tom sólido pra legenda casar). `barmode="relative"` + `zeroline` pra suportar barras negativas. Cada número vive na sua trace (some/volta junto no toggle da legenda). Nota explicativa do cálculo abaixo do gráfico.

**Defaults placeholder:** ACL 200 / Spot 50 MWmed, alocação 100% hidro — ilustrativos, o usuário substitui pelos reais e salva.

**Validação:** compile-check OK; smoke tests do cálculo (100% hidro = contínuo com o modelo hidro-puro anterior; 100% solar → receita negativa; EQTL/NE; `spreads_auto` segue a alocação; round-trip `_para_salvar`); app sobe HTTP 200. Iterações de UX (cores, layout das tabelas em blocos, alinhamento, toast, negativos) ajustadas com o usuário no Streamlit local — browser-automation indisponível nesta sessão.

**Limitações conhecidas do `st.data_editor` (registradas ao longo da sub-sessão):** não dá pra re-tematizar (canvas + tema global escuro), nem centralizar valores, nem cabeçalho de 2 níveis, nem célula-residual auto-atualizável. Contornos aplicados: blocos lado a lado pro efeito de cabeçalho-de-grupo + separação de trimestres; "Empresa" como coluna normal (não índice) pra legibilidade; CSS escopado pra gap mínimo + cantos quadrados; validação-com-aviso no lugar da célula-residual.

### 5.75 Fix do "desloga rapidamente" — cookie de re-autenticação + sessão de 24h

**Sintoma reportado:** usuário logava no dashboard e era deslogado rapidamente (na próxima reconexão de WebSocket ou refresh, voltava pra tela de login).

**Diagnóstico (streamlit-authenticator 0.4.2, lendo o source da lib):** dois fatores combinados em `auth.py`. (1) **`Authenticate(...)` era criado a cada rerun** dentro de `require_login()`. A streamlit-authenticator instancia o `extra_streamlit_components.CookieManager` dentro do `CookieModel.__init__`, então recriar `Authenticate` a cada rerun churna o componente de cookie (fonte conhecida de instabilidade). (2) **`Authenticate` recebia o dict de credenciais** (não um caminho de arquivo) → `self.path = None`. O `login()` da lib só dispara o `st.rerun()` pós-login quando `self.path` está setado (`if self.path and self.cookie_controller.get_cookie(): st.rerun()`); sem esse rerun, o cookie não tem ciclo de render limpo pra flushar no navegador. Combinado, a auth ficava vivendo **só no `st.session_state`**; qualquer reconexão de WebSocket / refresh / timeout zerava o session_state e o `st.context.cookies` (que a lib usa pra ler, frozen na conexão) não tinha o cookie de volta → tela de login.

**Fix em `auth.py`:** novo helper `_get_authenticator()` que cria `stauth.Authenticate(...)` **uma vez por sessão** (cacheado em `st.session_state["_authenticator"]`) e reutiliza nos reruns. Adicionado `st.rerun()` explícito no `require_login()` na transição "estava-deslogado → acabou-de-logar" (`auth_status is True and auth_status_before is not True`), suprindo o rerun interno que a 0.4.2 só faz com `self.path` setado.

**Duração da sessão:** `cookie.expiry_days` reduzido de `30` → `1` (=24h) em `config.yaml` e `config.yaml.example` — decisão do usuário (re-autenticação diária por padrão). No Streamlit Cloud, `cookie.expiry_days` vem de `st.secrets["auth_config"]["yaml_content"]` (não do `config.yaml` local) — o ajuste lá é manual via painel.

**Validação:** compile-check OK; app sobe HTTP 200; smoke teste de login na sessão local confirmou que a auth persiste entre refreshes/reconexões (antes do fix, refresh derrubava).

### 5.76 Migração Bauhaus → Bradesco (paleta institucional)

**Decisão:** trocar a paleta Bauhaus (vermelho cádmio + amarelo cromo + creme + preto Bauhaus) que vigorou até 2026-05-15 pela paleta institucional **Bradesco** (vermelho `#CC092F` + branco + cinza-quase-preto), refletindo a identidade da casa. Migração tocou todos os arquivos com cor — `app.py`, `auth.py`, todos os `components/tab_*.py` e o `.streamlit/config.toml` —, sumarizada por uma sequência de commits no branch `feature/paleta-bradesco` (mergeado em `main` via fast-forward).

**Single source of truth — `utils/paleta_bradesco.py` (novo):** arquivo puramente declarativo (zero imports do projeto, fica como folha do grafo de imports — sem risco de ciclo) com 4 layers:
1. **Estrutural (UI):** `COR_FUNDO #FFFFFF`, `COR_TEXTO #313131` (quase-preto Bradesco, contraste 12.6:1 WCAG AAA com fundo), `COR_GRID #E0E0E0`, sidebar `#313131` fundo + `#FFFFFF` texto.
2. **Semântico:** `COR_DESTAQUE #CC092F` (vermelho Bradesco — accent principal, antes era `BAUHAUS_RED`), `COR_ACCENT #0078B7` (azul Bradesco — accent secundário).
3. **Submercados:** SE `#CC092F` (vermelho), S `#0078B7` (azul), **NE `#560CAB` (roxo — substitui o amarelo Bauhaus)**, N `#313131` (quase-preto, linha **contínua** agora — antes era preto Bauhaus tracejado pra distinção B&W; com a nova paleta as 4 linhas são contínuas porque a distinção já se faz pela cor).
4. **Fontes de geração:** hidro azul, eólica verde, térmica laranja, solar amarelo, MMGD amarelo-claro — mantém o canônico do `utils/cores_fontes.py` (que vira fachada que re-exporta deste arquivo). Há também `CORES_MOTIVOS_TERMICO` consolidando o dict que vivia inline duplicado em 3 lugares (`app.py:4529, 5489, 5670`).

Aliases de compat (`BAUHAUS_BLACK = COR_TEXTO`, `BAUHAUS_CREAM = COR_FUNDO`, `BAUHAUS_LIGHT = COR_GRID`, `BAUHAUS_RED = COR_DESTAQUE`) ficam por enquanto nos consumidores pra não exigir rename simultâneo de ~26 usos por arquivo — rename pra `COR_*` fica como TODO no roadmap.

**Streamlit base `dark` → `light` (`.streamlit/config.toml`):** o tema base passou de escuro pra claro, com `primaryColor #CC092F`, `backgroundColor #FFFFFF`, `secondaryBackgroundColor #F5F5F5`, `textColor #313131`. Implicações:
- O `st.data_editor` (canvas) agora segue o tema light — fundo branco em vez do escuro registrado na §5.74 (algumas limitações daquela sub-sessão foram naturalmente resolvidas pela mudança de tema).
- O **header do Streamlit** (top-bar) com o tema light fica branco com texto escuro — fica visualmente solto sobre a sidebar escura. Decisão: forçar o header a ficar **escuro** (`COR_SIDEBAR_FUNDO #313131`) pra "fechar" o topo da página com a sidebar, e CSS pra clarear os ícones nativos do Streamlit (Deploy, menu kebab, status widget Running) que herdariam cor escura do tema light e ficariam ilegíveis.

**Armadilha do header — quadradinhos brancos:** a primeira tentativa do CSS do header forçava `fill: branco !important` em **todo `<svg>` e `<path>`** do `[data-testid="stHeader"]`. Os ícones modernos do Streamlit 1.56 usam SVGs com `<rect>` de fundo + `<path>`/`<circle>` do glifo — forçar fill em tudo pintava o rect E o glifo de branco, transformando o ícone num **quadradinho branco sólido sobre o header escuro**. Fix final: remover o `fill` blanket, manter só `color: branco` (ícones que usam `fill="currentColor"` herdam por cascata) + uma regra cirúrgica `fill: currentColor !important` SÓ pra elementos que já declaram `fill="currentColor"` — preserva o desenho de SVGs com fills explícitos.

**Sidebar:** botão ativo no vermelho Bradesco (`#CC092F`); inativo transparente sobre fundo escuro com texto branco; hover replica o ativo (feedback). A separação visual da barra vermelha do "PLD" (na sidebar) ficou perceptível.

**Linha do Norte:** removida a propriedade `dash` (antes tracejada pra distinguir do SE em monitores B&W) — paleta Bradesco distingue as 4 linhas só por cor (vermelho/azul/roxo/quase-preto), todas contínuas agora.

**Sequência de commits (`feature/paleta-bradesco` → `main` via fast-forward):**

| Hash | Mensagem |
|---|---|
| `a2d304e` | feat(paleta): adiciona utils/paleta_bradesco.py + fachada cores_fontes |
| `3602716` | refactor(paleta): substitui Bauhaus por Bradesco em código de produção |
| `c130146` | fix(paleta): balanceia cores de motivos térmicos pra distinção em barras empilhadas |
| `1f78e0b` | feat(theme): migra Streamlit base dark para light com cores Bradesco |
| `a86eca9` | fix(theme): restaura header escuro pós tema light pra coerência com sidebar |
| `6322859` | fix(pld): remove override legado de CORES_SUBMERCADO que pintava NE de cinza |
| `a8f8b79` | fix(theme): força ícones e texto claros no header escuro pra legibilidade |
| `1d00b00` | fix(theme): remove background branco indevido dos botões do header |
| `2e60c02` | fix(theme): catch-all transparente nos containers do header (resolve quadrado branco residual) |
| `2866920` | fix(theme): ícones do header sumindo como quadrados brancos (regra `fill` SVG/path agressiva demais) |

**Contraste WCAG (validado em `paleta_bradesco.py`):** `COR_TEXTO #313131` sobre `COR_FUNDO #FFFFFF` = 12.6:1 (AAA); `COR_DESTAQUE #CC092F` sobre branco = 7.1:1 (AAA); `COR_ACCENT #0078B7` sobre branco = 5.2:1 (AA, AAA pra texto grande); `COR_NE #560CAB` sobre branco = 9.9:1 (AAA); branco sobre `COR_SIDEBAR_FUNDO #313131` = 12.6:1 (AAA).

**Fora de escopo (registrado pra futuro):**
- Rename dos consumidores de `BAUHAUS_*` → `COR_*` (aliases de compat seguram por enquanto).
- Refator dos 3 dicts inline de motivos térmicos pra USAR `CORES_MOTIVOS_TERMICO` do `paleta_bradesco.py`.
- O secret `cookie.expiry_days` no Streamlit Cloud (`st.secrets["auth_config"]["yaml_content"]`) continua precisando ser ajustado manualmente pra refletir mudanças do `config.yaml.example` (não há sincronização automática).

### 5.77 Sub-aba GSF (Fator de Ajuste do MRE) — Sprint completo Fases 0 a 2D+++ (16/05/2026)

**Contexto.** GSF (Generation Scaling Factor / Fator de Ajuste do MRE) é a métrica oficial CCEE que indica se as UHEs participantes do Mecanismo de Realocação de Energia (MRE) entregaram acima (>100% = energia secundária) ou abaixo (<100% = déficit) da garantia física agregada no mês. Sub-aba implementada em "Geração → GSF" (3ª sub-view, após SIN e Eólica/Solar por Grupo). Spec completo em `docs/SPEC_gsf_v1.md`.

**Fórmula validada empiricamente (Fase 0).** A jornada de descoberta foi a parte mais cara do sprint — 8 hipóteses estruturadas testadas até bater. A versão inicial do spec assumia que `MRE_MENSAL` continha o numerador/denominador do GSF, mas testes contra 15 pontos oficiais (9 do Power BI público CCEE + 6 do InfoPLD) provaram que **`MRE_MENSAL` não tem GSF nem seus inputs diretos**: `ENTREGA_MRE` é volume de settlement (= `VALOR_ALOCADO_MRE / CUSTO_MRE`, identidade confirmada), não geração bruta UHE; `FATOR_REDUCAO_ACUMULADO` é produto dos 3 fatores de perda (interna × rede básica × disponibilidade), não GSF. A solução real veio do dataset `GERACAO_HORARIA_SUBMERCADO` com fórmula:

```
GSF_mês = Σ(GERACAO_MRE) / Σ(GARANTIA_FISICA_MRE)
          agregando 4 submercados × todas horas do mês
```

Validação: **12/12 hits ±0.5pp** contra os 15 pontos oficiais (3 fora do range do dataset porque cobertura é nov/2023+). Mean abs diff = 0.027pp; max = 0.158pp; 4 meses batem a 3 casas decimais. Cuidado crítico: **NÃO usar `GARANTIA_FISICA_MODULADA_MRE`** como denominador — é GF capada pós-modulação e a razão dá ~100% sempre, mascarando deficits. Também **NÃO usar `GERACAO`** (sem `_MRE`) — é geração TOTAL do submercado (todas as fontes), 3-4× maior que UHE MRE.

**Loader (`data_loaders/ccee_gsf.py`).** `load_gsf_mensal()` retorna DataFrame indexed por `mes_ref` (datetime64, 1º dia do mês), colunas `sum_geracao_mre_mwh`, `sum_gf_mre_mwh`, `gsf` (decimal), `fonte_dado`. Cache 2-layer (decisão 5.15): `@st.cache_data` TTL 6h em RAM + parquets por ano em `~/.cache/dashboard-setor-eletrico/gsf_v1/`. TTL diferenciado: anos fechados 30d, ano corrente/anterior 24h (recontabilização possível). 3-strategy cascade CKAN→dump. Resource IDs persistidos em `scripts/_resource_ids_gsf.json` (origem da população do dict inline `RESOURCE_IDS_BY_YEAR`). Cold load ~25s, warm-disk ~60ms, warm-RAM 0ms. `load_gsf_historico_pre2023()` stub que retorna df vazio se arquivo não existir (preparação V2). `clear_gsf_cache()` limpa RAM + apaga parquets por ano.

**UI (`components/tab_gsf.py`).** Estrutura visual de cima pra baixo: (1) header "GSF — FATOR DE AJUSTE DO MRE" com border-bottom 2px `#313131`; (2) period controls em 7 colunas FIXAS `[2, 1, 1, 1, 4.2, 2, 2]` (replica padrão Modulação adaptado — `cols[1..3]` vazios intencionalmente pra preservar alinhamento visual entre abas mesmo sem presets); (3) gráfico Plotly com fills semânticos déficit/secundária + linha principal preta + paridade 100% dashed; (4) tabela HTML "Detalhamento — Últimos 12 meses"; (5) footnote com fórmula MR.2.1; (6) expander de diagnóstico colapsado. Cores via `utils/paleta_bradesco.py`: linha principal `COR_TEXTO` (#313131), déficit `rgba(204,9,47, 0.15)` (= `COR_DESTAQUE` 15%), secundária `rgba(135,206,235, 0.30)` (sky blue 30% — verde `COR_SUCESSO` foi testado e trocado por feedback UX). Markers em GSF>100% e 3 KPIs topo planejados pra Fase 2E (não entregue neste sprint).

**Decisões arquiteturais.** (a) **Granularidades Mensal + Trimestral** (sem semanal — GSF é série mensal-nativa). (b) **Agregação trimestral em RENDER** via `df.groupby(pd.Grouper(freq='QS')).agg(sum, sum, first)` + recálculo `gsf = sum/sum` — não no loader, e NÃO média de GSFs mensais (semântica contábil correta). (c) **Drop trimestre incompleto NO INÍCIO** (`n_meses<3`) — exceto o último (parcial preservado). (d) **Selectbox MM/AAAA mensal e "1T26" trimestral** em vez de date_input — GSF é mensal-nativo, dia arbitrário não tem semântica. (e) **Defaults**: mensal `data_fim − 12 meses` (~13 month-starts visíveis), trimestral `data_fim − 21 meses` (exatamente 8 trimestres). (f) **Tabela 12m SEMPRE fixa mensal, independente dos period controls** — "tabela = estado recente, gráfico = evolução". (g) Helper `_construir_label_trimestre(ts)` → `"1T26"` formato BR; helper `_converter_periodo(ts, gran)` → start-of-period via `to_period(freq).start_time` (Dez/2024 mensal ↔ 4T24 trim); helper `_snap_to_options(ts, options)` snap pro option válido mais próximo `<= ts` (cobre migração de tipo, dataset shrinking, state stale).

**Bug widget cleanup cross-tab + fix shadow state (commit `b6068b3`).** Diagnosticado via prints temporários e logs do usuário: Streamlit faz cleanup das widget keys ao sair da aba (widgets não renderizados naquele frame). As 3 keys que são `key=` de selectbox (`gsf_granularidade`, `gsf_data_ini`, `gsf_data_fim`) são REMOVIDAS de `session_state`. Keys não-widget (`gsf_datas_custom`, `gsf_granularidade_anterior`) sobrevivem, gerando estado inconsistente: ao voltar pra GSF, `setdefault` reativa granularidade pra "mensal", init block re-seta defaults mensais, e o granularity-change block "converte" as datas DEFAULT recém-setadas (não as custom originais, que já se perderam). Resultado: UI sempre volta pro default mensal mesmo com state custom marcado. **Fix:** pattern de shadow state alinhado com decisão 5.18. `_SHADOW_MAP_GSF` mapeia cada widget key pra `gsf_shadow_*`. `_shadow_restore_gsf()` roda no INÍCIO de `render_aba_gsf` (ANTES de qualquer `setdefault`) e restaura se widget ausente + shadow presente. `_shadow_sync_gsf()` roda APÓS todas as mutações programáticas (init, granularity re-derive, snap), antes dos widgets renderizarem, espelhando widget keys → shadows. Em 1ª render absoluta o restore é no-op (nada existe), init defaults rola normal. Quatro cenários validados via simulação com mock `session_state`.

**Refinos visuais finais (commit `cc49a2e`).** (a) Caixas De/Até alargadas de 1.5 pra 2.0 (spacer encolheu de 5.2 pra 4.2, soma 15.2 preservada) — `Mar/2025` não corta mais. (b) Placeholder `<div color:transparent>` acima do selectbox de granularidade pra alinhar verticalmente com De/Até que têm labels visíveis. (c) Legenda do gráfico: size 14px + cor `COR_TEXTO` + family Inter (default cinza pequeno tinha legibilidade fraca).

**Modulação tem o mesmo bug estrutural mas NÃO foi corrigida** — estruturalmente as 3 widget keys (`mod_granularidade`, `mod_data_ini`, `mod_data_fim`) também são vulneráveis ao cleanup, mas o usuário reportou que cross-tab persiste na Modulação. Hipótese: bug existe mas é menos visível porque defaults entre granularidades são similares, OU Modulação tem mecanismo não-identificado que evita cleanup. Aplicar o mesmo fix lá é pendência se for reportado em uso real.

**Pendências.** Fase 2E (hover JetBrains Mono no Plotly, markers grandes em GSF>100% em sky blue, 3 KPIs topo: GSF mês mais recente, GSF acumulado 12 meses ponderado, Energia Secundária acumulada 12 meses em TWh). Fase 3 (`scripts/validar_gsf_calculado_vs_mre.py` automatizando a validação contra os 15 pontos oficiais — passa a ser parte da regressão). Fase 4 V2 (extensão histórica pré-nov/2023 dependente de arquivo manual `data/raw/gsf_historico_pre2023.csv`; loader stub já preparado). Atualização do `SPEC_gsf_v1.md` consolidando que `MRE_MENSAL` foi rejeitado e `GERACAO_HORARIA_SUBMERCADO` é a fonte canônica (revisão pós-Fase 0 já feita no commit `fed1cbd`).

### 5.78 Receita por Empresa: melhorias gráficas + Estimativa BBI (baseline admin)

**Contexto:** sub-sessão de polish do gráfico (§5.74) + introdução de uma camada de "baseline oficial" (Estimativa BBI) editável só por admins, com cenário pessoal opcional pros demais usuários. Pattern desenhado pra escalar pro GSF e outras premissas curadas centralmente (CCEE-reported, BBI-internal).

**Gráfico — refactor (`_render_grafico`):**

(a) **Linha de Spread em eixo secundário** (`yaxis2`, invisível — sem ticks/grid/título). Cor neutra escura (`#3A3A3A`), width 1.6, vértices `marker.size=9` com borda creme pra ancorar cada trimestre. **3 traces** (não 2): trace **real** (sólida, hover ON) cobre trimestres reais (fechado+corrente); trace **ponte** (tracejada, `hoverinfo="skip"`, sem markers) liga apenas o último real ao primeiro futuro; trace **futuro** (tracejada, hover ON) só os futuros. Versão anterior duplicava o ponto de transição em 2 traces → ambas contribuíam pro `hovermode="x unified"` → hover **duplicado** no trimestre de transição (sintoma reportado no 2T26 da EQTL).

(b) **Hover unificado com fonte única:** barras com `hoverinfo="skip"` (o R$mn já está dentro da barra como label — repetir no hover seria redundante); só a linha de spread contribui pro tooltip. Conteúdo (ordem): Spread modulação (2 decimais), Venda ACL (sem decimais), Venda Spot (sem decimais), **Total** em negrito. Prefixo inline `<span style='color:{COR_SPREAD}'>─●─</span>` colado em "Spread modulação" — em `hovermode="x unified"`, o símbolo automático da trace se centraliza verticalmente sobre o bloco inteiro (4 linhas → cai no meio); o prefixo inline resolve sem refactor.

(c) **Label única por barra** (não duas — realizado/incremento): trace `Scatter` text-only (`mode="text"`) posicionada FORA do tip (`top center` se positivo, `bottom center` se negativo), texto escuro contra fundo creme, `cliponaxis=False`. Valor = `receita_estimada` (altura total da barra). Razão: o spread é único por trimestre (`base = acl*ws_acl + spot*ws_spot` divide só por `n_horas` vs `horas_cheio` pra obter realizado vs estimado — sem mudar o spread), então quebrar a label em "Realizado: X / Estimativa: Y" não acrescenta info — alinhado com o hover.

(d) **Y1 com headroom + Y2 mapeado pra zona reservada:** `yaxis.range` setado explicitamente (não autoscale) com 40% extra acima do `bar_max` e 5% abaixo do `bar_min`. `yaxis2.range` calculado por mapeamento linear pra que `s_min`/`s_max` caiam em `[b_max + 0.12*amp, y1_top - 0.05*y1_height]` (top 25-30% visualmente). Sem isso, em barras pequenas (tip perto de 0), o label da barra (fora do tip) e o vértice da linha (no topo via push) competiam pela mesma faixa vertical → overlap visual. **Caso EQTL** (spread e receita ambos negativos) é o stress test — agora barras no andar de baixo, linha no andar de cima, sempre fisicamente separadas.

(e) **Helper `_para_salvar` reusado pra comparação** (relevante pra Estimativa BBI abaixo, mas a mecânica do gráfico depende disso): trimestres futuros podem ter `spread=None` (sinal de "segue o auto"). A versão materializada em RAM resolve o spread auto; a versão persistida no JSON guarda `None`. Comparações entre as duas devem usar SEMPRE a versão normalizada (`_para_salvar(...)` → `payload`).

**Estimativa BBI — baseline curado por admin:**

(f) **Cascata em 3 camadas (`_carregar_premissas`):** defaults de código → seção `"_bbi"` no JSON (baseline oficial) → seção do user (cenário pessoal). Cada camada sobrescreve campo a campo (`None = não sobrescreve`). `_BBI_KEY = "_bbi"` reservado — prefixo `_` separa de usernames reais.

(g) **Permissão por whitelist** (`ADMIN_USERS = {"Nava", "Fagundes", "Caruso"}`): admin vê 2 botões — `"Salvar como Estimativa BBI"` (primary, grava em `_bbi` via `_salvar_baseline_bbi`) e `"Salvar minhas premissas"` (cenário pessoal via `_salvar_premissas`). Não-admin vê `"Salvar minhas premissas"` (primary) + `"Resetar para Estimativa BBI"` (apaga seção pessoal via `_apagar_premissas_usuario` + pop session_state + `st.rerun()`). Helper `_gravar_secao(chave, premissas)` DRY entre os dois saves.

(h) **Rótulo de modo** (acima das tabelas, no container reservado `modo_box`): faixa vermelha com `📊 ESTIMATIVA BBI` quando `_premissas_iguais(payload, bbi_baseline)`; faixa cinza `"Cenário pessoal — diferente da Estimativa BBI"` quando divergiu. **Armadilha:** comparar `premissas_atual` (RAM, spreads futuros materializados) vs `bbi_baseline` (JSON, `spread=None` nos futuros que seguem o auto) dá falso "divergiu" eternamente. Fix: comparar `payload = _para_salvar(...)` (normalizado) contra `bbi_baseline`. `_premissas_iguais` faz tolerância de float (`1e-6`) e trata `None==None` como igual.

(i) **Modo preview pra admin** (`👁️ Admin: Ver como usuário comum (preview)`): checkbox abaixo dos botões + banner amarelo abaixo do checkbox quando ativo. `is_admin_efetivo = is_admin and not preview_user` controla qual conjunto de botões renderiza. **Posicionamento intencional:** valor lido via `session_state.get("receita_preview_user", False)` ANTES da renderização dos botões; o widget `st.checkbox` é instanciado DEPOIS dos botões — minimiza churn visual no toggle (só os botões trocam, checkbox fica parado). Banner abaixo do checkbox também, pra associação visual com o controle que ativou ele.

(j) **Migração inicial:** seção `_bbi` populada via script one-shot copiando os valores atuais do `Nava` (único admin com dados salvos antes da feature). O `Nava` mantém sua seção pessoal idêntica ao baseline (sem divergência inicial); novos admins (`Fagundes`, `Caruso`) e usuários futuros caem direto na cascata BBI ao primeiro login. Dono do app substitui o baseline pelos valores reais via `"Salvar como Estimativa BBI"`.

**Auth — 2 novos admins (`config.yaml`):** `Fagundes` e `Caruso` com hashes bcrypt gerados via `gen_password.py`; `preauthorized.emails` atualizado. Senhas iniciais comunicadas pelo dono pelo canal interno. Streamlit Cloud precisa atualizar `st.secrets["auth_config"]["yaml_content"]` espelhando o `config.yaml` (gitignored localmente).

**Pattern reutilizável pra GSF (próximo passo):** mesmo design escala pra Estimativa CCEE do GSF — admin atualiza valores conforme a CCEE publica, usuários veem como baseline read-only (sem cenário pessoal porque GSF não é negociável). Linha tracejada pra estimativa, sólida pra dado oficial fechado — mesma regra "tem dado oficial?" = "linha sólida" da Receita por Empresa, que já funciona automaticamente conforme `_spread_trimestral()` passa a devolver dados pra trimestres antes futuros.

**Validação:** compile-check OK em `tab_receita_modulacao.py`; smoke-test do round-trip BBI (save → reload → label `📊 ESTIMATIVA BBI` volta corretamente); preview toggle valida sem alterar dado persistido; comparação `_premissas_iguais` tolerante a `None`/float. Iterações de UX validadas com o usuário no Streamlit local (browser-automation indisponível nesta sessão).

---

## 6. Fluxo de Desenvolvimento

### 6.1 Subir o servidor local

- **Atalho:** duplo-clique em `abrir_dashboard.bat` (ativa venv + sobe
  Streamlit).
- **Manual:** `venv\Scripts\activate && streamlit run app.py`.
- URL: `http://localhost:8501`.
- Auto-reload detecta mudanças em `app.py` e `data_loader.py` (liga em
  Settings do Streamlit "Run on save").

### 6.2 Claude Code em paralelo

- Abrir **outro terminal** no projeto, rodar `claude`.
- Usar **Ctrl+Shift+R** no browser pra refresh duro após edições CSS
  (bypass cache).
- Ficar atento: Streamlit Cloud demora ~1-2 min pra redeployar após push.

### 6.3 Commits e push

- **Commit só com aprovação explícita do usuário.** Nunca commit automático.
- Mensagem padrão: `<tipo>(<escopo>): <resumo>`.
  Tipos: `feat`, `fix`, `refactor`, `docs`, `chore`.
- Sem rodapé `Co-Authored-By` (modelo de IA é ferramenta, não co-autor).
- Push pra `origin main` triggera redeploy automático no Streamlit Cloud.
- Antes de commitar: `git status` pra confirmar que `config.yaml` NÃO está
  na lista (nunca commitar segredos).

### 6.4 Scripts utilitários em `scripts/`

Utilitários de manutenção, **não executados pelo app**. Rodar manualmente.

- **`discover_ccee_ids.py`** — descobre UUIDs CKAN da CCEE por ano.
  Rodar quando CCEE publicar novo ano (janeiro) ou se algum `resource_id`
  quebrar. `venv\Scripts\python.exe scripts/discover_ccee_ids.py`.
- **`validate_reservatorios.py`** — valida schema/integridade do loader ONS.
  Rodar após ONS publicar novo ano ou se suspeitar de mudança no dataset.
  Checa shape, códigos de subsistema, cálculo do SIN com amostras.
- **`validar_casamento_excel_ons.py`** — valida casamento entre o Excel
  de proprietários (`data/curtailment/unidades_geradoras.xlsx`) e os nomes de
  usinas no ONS. Rodar após atualização do Excel ou quando o ONS publicar
  dados de novas usinas. Gera relatórios em `relatorio_casamento/`
  (gitignorado). Não modifica nada — só lê e reporta.
  `venv\Scripts\python.exe scripts/validar_casamento_excel_ons.py`.

### 6.5 Validação de deploy após mexer em `requirements.txt`

Quando adicionar ou editar dependência em `requirements.txt`:

1. **Fazer um push dedicado com só essa mudança** — antes de empilhar
   features em cima. Se o Cloud falhar, o commit de dep fica isolado e
   fácil de reverter.
2. Aguardar 2-3 min e abrir `dashboard-setor-eletrico.streamlit.app`.
3. Se falhou: pegar log via "Manage app" (ver armadilha 4.5).
4. **Não seguir desenvolvendo até o deploy estar verde.** Quando vários
   commits empilham antes de testar deploy, fica custoso isolar qual
   gerou o break.

Essa regra é especialmente importante porque o venv local **não re-resolve
constraints automaticamente** (armadilha 4.5) — erro de dep só aparece no
ambiente fresh do Cloud.

### 6.6 Pendências de manutenção

**Drift entre `validar_casamento_excel_ons.py` e produção**

O script utilitário usa normalização ligeiramente diferente da função
`normalizar_nome` em produção, gerando falsos positivos de "ONS sem par".
Casos confirmados (Apr/2026): EÓLICA CATAVENTOS DO ACARAÚ I, CONJ. BOM NOME,
CONJ. EOL. VENTOS SANTA EUGÊNIA — todos batem corretamente em produção.

Próxima manutenção do Excel: alinhar normalização do validator com
`normalizar_nome` de `data_loader_grupos_excel.py` antes de tomar decisões
baseadas no relatório.

---

## 7. Histórico de Features (timeline)

1. **MVP** — PLD diário por submercado (CCEE), filtros de período e
   submercado, tabela de stats, KPIs, export CSV.
2. **Renomeação de atalhos** — 7d/30d/90d/1A → 1M/3M/6M/12M (commit
   `3325c4a`).
3. **Fase 1 (PLD multi-granularidade backend)** — 3 loaders novos
   (horário, semanal, mensal) + refactor pra `RESOURCE_IDS_BY_DATASET`
   + 4 normalizers especializados.
4. **Fase 2 (dropdown granularidade visual)** — `st.selectbox` como
   título Bauhaus com CSS minimal (inicialmente `st.popover`, migrado).
5. **Fase 3 (integração)** — dropdown conectado ao gráfico, `hoverformat`
   por granularidade, KPIs/tabela hidden em não-diário. Commit `444ab28`.
6. **Fase A Reservatórios** — inspeção CKAN ONS, identificação de
   `ear-diario-por-subsistema`, doc `docs/reservatorios_research.md`.
7. **Fase B Reservatórios** — `load_reservatorios()` + SIN ponderado
   + cache split por ano (30d histórico + 2h externo).
8. **Fase C Reservatórios** — aba nova, 5 gráficos empilhados (SIN + SE
   + S + NE + N), atalhos 1A/3A/5A/10A/Máx, faixas azuis de período úmido
   hidrológico (1º nov – 30 abr), export CSV.
9. **Refactor `_render_period_controls`** — extração em função top-level
   reusável. CSS `primary button` global.
10. **Renomeação final** — radio "PLD Diário" → "PLD" (granularidade já
    está no dropdown interno).
11. **Fase A ENA** — descoberta dataset `ena-diario-por-subsistema` no CKAN
    ONS (análogo ao EAR). Schema validado via `scripts/inspect_ena.py`,
    doc em `docs/ena_research.md`. Descoberta relevante: parquet só cobre
    2021-2026 (vs EAR que cobre 2000-2026) → decisão de usar XLSX pra tudo.
12. **Fase B ENA** — `load_ena()` em `data_loader.py` com schema long-form
    (ena_mwmed, ena_armazenavel_mwmed, ena_mlt_pct). SIN dos MWmed via
    **soma simples** (fluxo); SIN do mlt_pct via **reversão da MLT absoluta**
    (`ena_mwmed / (pct/100)` por subsistema/data, somar, dividir soma-de-ENA
    por soma-de-MLT, multiplicar por 100). Cache split 30d/2h igual ao EAR.
    `scripts/validate_ena.py` análogo. 48.030 linhas × 2000-2026.
13. **Fase C/D ENA** — aba "ENA/Chuva" no radio da sidebar com 5 gráficos
    (SIN + SE/S/NE/N), eixo Y compartilhado fixo **0-250%** (métrica % MLT,
    **zero casas decimais**), hline tracejada em 100%, título
    "SUBSISTEMA · DD/MM/YYYY · XX%", hover em % MLT (mostra valor real
    mesmo quando ponto sai visualmente do range), export CSV com nomes
    curtos. Reusa `_render_period_controls` e `_add_wet_season_bands`.
    Métrica plotada é `ena_mlt_pct` — decisão consolidada em 5.7.
14. **KPI cards ENA** — acima de cada um dos 5 gráficos: 4 KPIs ponderados
    (Último mês / 3 meses / 12 meses / Período úmido atual). Cálculo:
    `sum(ena_mwmed) / sum(mlt_mwmed) × 100` sobre a janela, com MLT absoluta
    revertida por linha (`ena_mwmed / (ena_mlt_pct/100)`) — mesmo truque do
    `_compute_ena_sin_aggregate`. Helpers top-level em `app.py`:
    `_compute_kpi_mlt_pct(df, code, d_start, d_end)` +
    `_wet_season_window(last_date)`. Janelas são calculadas a partir da
    **última data do dataset** (não do filtro de período) — KPIs ficam
    estáveis ao mexer no período. SIN agregado sobre os 4 subsistemas base.
    Doc da fórmula em decisão 5.8.
15. **Publicação da feature ENA** — commit `87c8e72` consolidou tudo (Fases
    B+C+D: backend + UI + KPIs + docs, +1.218 linhas em 6 arquivos). Commit
    seguinte `80634b5` corrigiu upper bound do `pyarrow` no
    `requirements.txt` de `<22.0` pra `<24.0` — deploy no Streamlit Cloud
    falhou no 87c8e72 (ver armadilha 4.5). Feature online em
    `dashboard-setor-eletrico.streamlit.app`.
16. **Aba Geração — primeira versão (5 gráficos empilhados)** — commit
    `87a1eb1` (2026-04-23). Loader `load_balanco_subsistema()` (parquet
    2000-2026, SIN nativo do ONS), aba com 3 granularidades + 5 gráficos
    empilhados (SIN + SE/S/NE/N), modo "Data base + janela" na Horária
    (5.9), cor eólica verde-oliva `#8FA31E`, helpers
    `_render_period_controls_horaria` e `_format_periodo_br`, scripts
    `inspect_balanco`/`validate_balanco`. Doc `docs/aba_geracao_spec.md` +
    `docs/geracao_research.md`.
17. **Aba Geração — Sessão 1 (reversão pra gráfico único)** — 2º commit
    pendente em 2026-04-24. Reversão do layout dos 5 gráficos pra **1
    gráfico único com dropdown de submercado** (decisão 5.10) por causa
    de lentidão de render. KPIs e texto "Médias do período (X)" passam
    a seguir o submercado do dropdown (export CSV mantém os 5).
    Adicionada nota explicativa de intercâmbio. **Auto-ajuste de período
    ao trocar pra Mensal** (5.14). 5 bugs descobertos e corrigidos via
    debug `st.write` em runtime, viraram decisões: **5.11** (sentinela
    `_gen_dataset_max`), **5.12** (flag intermediário pra widget
    instanciado), **5.13** (inits separados quando widget pode escrever
    `None`). Detalhes em `docs/sessao_geracao_status.md` §3. Sessão 1.5
    (Performance) inserida no roadmap após user reportar lentidão geral
    da aba — ver mesmo doc.
18. **Aba Geração — Sessão 1.5 (Performance)** — 3º commit pendente em
    2026-04-25. 4 fixes mensurados com `time.perf_counter()` em Fase A
    de diagnóstico (instrumentação 100% removida pós-validação). **Fix #1:**
    pré-computar coluna `data` (datetime64[ns] normalizado) no loader,
    trocar `dt.date >= date(...)` por `data >= pd.Timestamp(...)` no
    filtro do `_build_pivot_submercado` — filter de ~11s/sub pra ~50ms/sub
    (50× speedup no hot path). **Fix #3:** disk-cache parquet local
    (`~/.cache/dashboard-setor-eletrico/balanco.parquet`) com cascade pra
    `tempfile.gettempdir()` em FS read-only, TTL 6h via mtime, helper
    público `is_balanco_cache_fresh()` exposto pra UI — cold start
    subsequente de 60s pra ~1-2s (decisão 5.15). **Fix #4:** spinner
    dinâmico no app.py (mensagem light se cache fresh, pesada com aviso
    de download longo se ausente). **Bug Cenário 3** descoberto:
    `KeyError 'gen_data_ini'` no clique Atualizar pós-Horária — causado
    por widget-state cleanup do Streamlit. Fix: estender sentinela do
    reset block com keys individuais (decisão 5.16). Tabela de ganhos
    medidos (3,7-11×) em `docs/sessao_geracao_status.md` §0.
19. **Sessão 1.5b — Performance global + default 15a Geração** — 4º commit
    pendente em 2026-04-25. Escopo expandido após user reportar Reservatórios
    ~20s e ENA ~30s no cold load. **3 partes:** (a) **Fábrica
    `_make_disk_cache_helpers(cache_name)`** em `data_loader.py` — closure
    independente com `lru_cache(maxsize=1)` próprio, gera 4 callables
    (get_path, is_fresh, try_read, try_write). Substitui ~120 linhas
    duplicadas que existiriam em 4 datasets. (b) **Disk-cache em
    Reservatórios e ENA** via 2 chamadas da fábrica + early-return + write
    nos respectivos loaders. Helpers públicos `is_reservatorios_cache_fresh`
    e `is_ena_cache_fresh` expostos. (c) **Default histórico 15 anos** na
    Geração (decisão 5.17 — dois eixos): `load_balanco_subsistema` ganha
    parâmetro `incluir_historico_completo: bool = False`. Caches em disco
    separados (`balanco_15anos.parquet` e `balanco_completo.parquet`). UI
    da Geração: state sticky `gen_historico_completo`, botão "📈 Carregar
    histórico completo (2000-2010)" abre `@st.dialog` de confirmação,
    confirmação seta flag + rerun → loader re-chamado com True →
    `min_d_gen` expande pra 2000. Presets revisados: Diária ganha 10A,
    Mensal ganha 10A + 15A. `clear_cache()` estendido pra unlinkar 4
    parquets + resetar `gen_historico_completo` (Atualizar = começar do
    zero).
20. **Sessão 1.6 — Ajustes estéticos & UX** — 5º commit em 2026-04-25.
    7 ajustes pequenos (1 bug + tipografia + UX) sem refator estrutural,
    com 3 bugs descobertos durante implementação que viraram fixes
    cirúrgicos. **Mudanças:** (#1+#6) lado direito errado do título
    Bauhaus removido + linha "Período" reaproveita o espaço (uniformizado
    com Reservatórios/ENA: Bebas Neue herdado, sem "Período:" prefix);
    (#3) bloqueio educativo Mensal <60d com `st.warning + st.stop`
    (decisão 5.24); (#4) refator dos 4 KPIs de `st.metric` pra HTML
    custom porque Bebas Neue é all-caps por design — "MWmed" virava
    "MWMED" (decisão 5.21, helper `_render_kpi_gen` com 4 classes
    `.gen-kpi-*`); (#5) resolvido implicitamente pelo refator do #4
    (margin-left 0.4rem entre número e unidade); (#7) tag compacta de
    granularidade entre título e gráfico ("Média mensal · MWmed" etc.,
    decisão 5.22), removida do bloco geral de notas. **#2 já era coberto
    pela 5.20 da 1.5b — confirmado em runtime sem trabalho.** **Bonus:**
    (a) helper `_format_periodo_br` ganha en dash `–` no lugar de ` a `
    + branch novo Horária ≥2D mesmo ano `DD/MM – DD/MM` sem ano (com
    fallback pra ano em ambos lados se atravessa virada); (b) override
    Bauhaus de `[data-testid="stAlert"]` em estratégia "container externo
    dita visual + descendentes transparentes" (decisão 5.23) — texto
    branco do tema dark sobre fundo amarelo do warning era ilegível,
    fundo passou pra `BAUHAUS_LIGHT` pra destacar da página; (c) guard
    `<2 pontos` movido pra ANTES dos KPIs com `st.stop()` final —
    coerência com guard Mensal <60d, KPIs/export bloqueiam junto com
    gráfico (decisão 5.24). **Bug grave descoberto pós-implementação:**
    ao sair de Geração + voltar de outra aba, `gen_data_ini` vira igual
    a `gen_data_fim` (0 dias) → guard ativa de novo. Diagnóstico em
    runtime via debug `st.write` em 3 pontos: cleanup parcial do
    Streamlit descarta `gen_data_ini`, preserva `gen_data_fim`. Widget
    re-instanciado sem session_state recria a key clamped pra `max_d`
    → fica `== gen_data_fim`. Sentinela 5.16 (que checa só ausência)
    não pega "presença com valor degenerado". Fix: 6ª condição no reset
    block detecta `gen_data_ini >= gen_data_fim` (range degenerado),
    com mesma exclusão `not em_horaria` da 5.19 (porque em Horária 1D
    isso é estado legítimo). Decisão 5.16 atualizada com "Extensão
    posterior (Sessão 1.6)" + 5.19 atualizada com aplicação ao 6º
    gatilho.
21. **Sessão 2 — Dia Típico (perfil 24h por hora-do-dia)** — 6º commit
    em 2026-04-25. Nova granularidade na aba Geração: stacked area com
    24 ticks `00:00...23:00` mostrando média de cada fonte em cada
    hora-do-dia ao longo do período selecionado (curva de pato canônica
    do setor elétrico). **Implementação reutiliza a infraestrutura
    existente** (decisão 5.25): `freq_map["Dia Típico"]=None` mantém
    pivot horário, helper novo `_build_dia_tipico_submercado` reusa
    `_build_pivot_submercado` + `groupby(index.hour).mean()` (5 linhas),
    despacho elegante via variável local `_build_pivot` (1 linha vs
    if/else espalhado). Eixo X categorial (`xaxis.type="category"`)
    preserva ordem natural sem precisar de `hoverformat` — hovermode
    unified mostra a string direto. Vline 29/04/2023 pulada (eixo é
    categorial, Timestamp não bate). **Configuração:** default 30D no
    reset block (decisão 5.20 estendida — sweet spot UX: captura padrão
    weekday/weekend, dilui anomalias diárias); presets `7D / 30D / 90D
    / 6M / 12M / 5A` (sem Máx — descontinuidade pré-2010 da matriz
    elétrica torna 25a sem sentido como "perfil típico"); guard `<7
    dias` com `st.warning + st.stop` (mesmo padrão da 5.24). **Tag
    explicativa estendida:** "Dia típico (média horária do período
    selecionado) · MWmed" — única das 4 tags da Geração que estende
    explicação porque o conceito não é universal (Mensal/Diária/Horária
    são óbvios). **Export CSV:** branch Dia Típico com coluna `Hora`
    string (`"00:00".."23:00"`) em vez de `Data` datetime, gran_slug
    `"dia_tipico"` no filename. Apenas 3 pontos divergem do flow
    tradicional: eixo X, vline, formato de export — KPIs/título/legenda/
    hover dos traces continuam reusados sem refator.
22. **Sessão 3 — GD descartada via ONS (sem código)** — 2026-04-26.
    Fase A de discovery do CKAN ONS via `scripts/inspect_gd.py` desmentiu
    a hipótese original da spec (que assumia "ONS publica MMGD mensal por
    subsistema"). Achado: ONS não publica série standalone de MMGD/GD —
    `balanco_energia_subsistema` não tem coluna de GD; MMGD vai embutida
    na carga pós-29/04/2023 (notes do `carga-energia` e `carga-mensal`
    confirmam); único dataset com MMGD isolada é `carga-energia-verificada`
    (semi-horária, por área de carga, via API/Swagger — custo/benefício
    ruim). **Decisão 5.26:** aba Geração mantém 4 fontes (térmica/hidro/
    eólica/solar centralizada), vline 29/04/2023 já comunica visualmente
    a existência de MMGD na carga. Plano C (ANEEL) reservado pra possível
    aba dedicada "GD Brasil" futura, não evolução desta aba. Atualizações:
    spec §4 reescrita, spec §7.2 e §13 marcadas como descartadas, decisão
    5.26 nova no CLAUDE.md, Sessão 3 fechada como ✅ SEM CÓDIGO no doc
    de status. **Roadmap original encerrado.**

23. **Sessão PLD 1D — preset "1D" em granularidade horária + KPIs do dia**
    — commit `c60283d` (2026-04-26) + refactor `aa2199a` (mesma data).
    Adiciona modo single-day no PLD horário: 5 presets
    (1D / 1S / 1M / 3M / Máx), substituindo os 2 `date_input` do range
    tradicional por **1 `date_input` "Dia" + 1 botão "Último dia"**
    quando o preset 1D está ativo. **Marcador de modo single-day é puro
    derivativo de runtime** (`data_ini == data_fim`) — sem session_state
    dedicada (decisão 5.28). Helper `_render_period_controls` ganhou
    parâmetro opcional `single_day_preset_label` que reusa toda a
    infraestrutura existente (presets + tooltip dinâmico no Máx + clamp
    em `min_d` da decisão 5.27). **4 KPIs do dia** acima do gráfico
    (PLD médio dia / máximo com horário / mínimo com horário / spread)
    — todos autocontidos, calculados sobre as 24 horas do dia
    selecionado (decisão 5.29). **Refactor lateral (`aa2199a`):**
    dropdown de submercado movido pra cima do gráfico, e termo informal
    "Média BR" passa a ser exibido como **"SIN"** seguindo vocabulário
    oficial do setor — chaves internas (`"Média BR"`) preservadas,
    tradução só na camada de display via `format_func` (decisão 5.30).
    Card "vs média do mês" descartado durante design (decisão 5.29) por
    (a) denominador móvel, (b) baixa acionabilidade, (c) redundância
    com o gráfico — comparações temporais ficam pra feature dedicada
    futura ("comparar com").

24. **Sessão 4a — Aba Carga (Blocos 1-5: Setup + KPIs + Glossário +
    Vizs 1 e 2)** — 5 commits entre 2026-04-27 e 2026-04-29 (`85be849`
    → `ac488a7` → `6768e2d` → `8478f38` → `7b5673a`). Aba nova
    reaproveitando `load_balanco_subsistema` da Geração (sem Fase A,
    mesmo pipeline + disk-cache 5.15 + reset block 5.20).
    **Bloco 1 (Setup):** radio na sidebar, dropdowns de granularidade
    (Diária/Mensal/Horária/Dia Típico) + submercado, presets de período
    compartilhados.
    **Bloco 2 (KPIs):** régua de 4 cards autocontidos (decisão 5.29).
    **Bloco 3 (Glossário):** explicação inline no topo da aba dos
    termos "Carga Total", "Carga Líquida", "MMGD", "Intercâmbio".
    **Bloco 4 — Viz 1 (Carga Total vs Líquida):** série temporal com
    2 linhas (azul = Total, vermelha = Líquida) + área verde-oliva
    entre elas representando "Renováveis variáveis cobriram"
    (eólica + solar) + vline 29/04/2023 marcando quebra MMGD.
    **Bloco 5 — Viz 2 (Composição da carga total):** stacked area com
    4 fontes na **ordem da carga líquida** (solar → eólica → hidro →
    térmica de baixo pra cima — decisão 5.31), linha dotted preta da
    Carga total sobreposta como linha de fecho, intercâmbio
    **stack-aware híbrido por recorte** (omitido em SIN, trace dashdot
    em submercado — decisão 5.32). Suporta as 4 granularidades
    incluindo Dia Típico (xaxis categorial + stackgroup, mesmo pattern
    da decisão 5.25 já aplicado na Viz 1).
    **Bug crítico descoberto durante Sub-bloco 5.5:** sanity check
    inicial (`carga ≈ stack + intercambio`) disparou aviso de 27.62%
    em SE×Dia Típico×5A. Diagnóstico empírico via comparação numérica
    revelou que dataset ONS usa convenção `intercambio > 0 = exportação`
    (oposto do esperado por estereótipo do setor) — fixes aplicados em
    `_residual_v2`, hovertemplate e decisão 5.32 (commit `8478f38`).
    **Lição registrada na 5.32:** convenções de sinal de datasets
    externos não devem ser inferidas — sempre validar numericamente
    quando o sinal carrega significado direcional.
    **Paleta canônica (decisão 5.33):** as 4 fontes ganharam constantes
    únicas (`COR_FONTE_SOLAR/EOLICA/HIDRO/TERMICA`) consistentes entre
    Geração e Carga — térmica terracota em vez de preto `BAUHAUS_BLACK`,
    hidro `#4A6FA5` em vez de `BAUHAUS_BLUE` (separa cor estrutural de
    cor de dado).
    **Sessão 4b futura** cobre Vizs 3 e 4 do escopo original
    (Comparação histórica + Curva de carga tipo).

25. **Sessão Despacho Térmico SIN — Layout C completo (Fases E.1 a
    E.17)** — maio/2026. Refactor completo da sub-view Sistema do
    Despacho Térmico, elevando-a a referência de UX e arquitetura pra
    próxima Fase D (replicação na sub-view Eneva).
    **Sub-fases (17):**
    - E.1: Layout C — selectbox de granularidade
      (Mensal/Diário/Trimestral)
    - E.2: Polimento — CSS scoped, 30 dias móveis no Diário
    - E.3: KPIs acompanhando toggle MWm/GWh + modo Trimestral
    - E.4: Filtro de anos (2022..2026) com 5 botões toggle
    - E.5: LTM + modo "ano completo" via inferência (bug fix cond_a
      state cleanup com disabled=True)
    - E.6: Identidade visual SIN+Eneva diferenciada (sem KPIs no SIN,
      sem toggle MWm/GWh no SIN)
    - E.7: Polimento final — formato BR DD/MM/YYYY, presets reduzidos
      a 12M/Máx no Mensal, validação >30 dias no Diário,
      traceorder="normal"
    - E.8: LTM trimestral = 4 trims (decisão 5.38)
    - E.9: Interface temporal contextual single↔multi-select
      (decisão 5.40)
    - E.10: Polimento visual SIN+Eneva (J3 trims compactos, J4 layout
      cols_p)
    - E.11: Título dinâmico (sub-view determina h1 da aba)
    - E.12: Fix KeyError state cleanup com .get(default) defensivo
      (refinamento da decisão 5.16)
    - E.13: Spacer pra cancelar margin global Bauhaus (decisão 5.43)
    - E.14: Granularidade Horário com groupby(["data", "hora"])
      (decisão 5.44)
    - E.14.1: Eixo X "HH:00" + hover rico "DD/MM/YYYY HH:00"
      (decisão 5.50)
    - E.15: Single-day picker + área stackada em Horário
      (decisões 5.46 + 5.47)
    - E.16: Checkbox decorativo nos trimestres (decisão 5.48)
    - E.16.1: Trims "soltos" (sem framing)
    - E.17: Títulos sem unidade + caption do gráfico no novo formato
      (top row Bebas Neue + sub-caption Inter italic, decisão 5.49)

    **Resultado final:** 4 granularidades funcionais
    (Mensal/Diário/Horário/Trimestral), identidade visual paralela
    SIN ↔ Eneva, interface temporal contextual (modos ano_completo /
    histórico), caption no formato Bauhaus (top row + sub-caption
    italic), helper `_render_termico_chart_caption` reaproveitável.

    **Bugs descobertos e corrigidos:** cond_a state cleanup (E.5),
    traceorder reverso em stacked bar (E.7), KeyError em transição
    entre sub-views (E.12), remap órfão de "Horário" interceptando
    seleção (E.14, decisão 5.45), overlap visual pills ×
    period_controls (E.13, decisão 5.43).

    **Arquivos principais:** `app.py` (bloco
    `elif aba == "Despacho Térmico":`, linhas ~2950-4170),
    `data_loaders/data_loader_termico.py` (intacto, dataset já
    horário), `docs/termico_research.md` (research da Fase A).

    **Próxima fase:** Fase D (Eneva replica Layout C com 4
    granularidades + checkbox + caption + lógica E.9, mantendo
    selectbox de Usina e toggle MWm/GWh).

26. **Sessao Bug-fix + Nav (07/05/2026)** - 3 commits sequenciais
    + 1 fix manual sem commit. Sessao mista de bugs e refactor de
    UX da sidebar.

    **Bug 1 (Reservatorios) - cache parquet truncado** (sem
    commit, fix manual via `clear_cache`):
    - Sintoma: botoes 1A/3A/5A/10A/Max nao funcionavam (todos
      caiam em `2026-01-01`, range zero ou poucos dias).
    - Diagnostico: `data_ini == data_fim == 2026-01-01`. Inspecao
      via debug temporario revelou `min_d` do dataset corrompido.
      Cache em disco `~/.cache/dashboard-setor-
      eletrico/reservatorios.parquet` tinha 10KB (vs ~900KB
      esperado), so contendo 2026.
    - Causa raiz: `load_reservatorios()` em `data_loader.py:1063-
      1100` consolida 27 anos. Se 26 dos 27 downloads falharam
      (rede ruim, Akamai), o loader persiste o resultado parcial
      no disco sem validacao de cobertura minima. TTL 6h faz o
      problema durar.
    - Fix imediato: `Remove-Item` no parquet truncado + Atualizar
      na sidebar (forca re-download fresh).
    - Bug arquitetural latente registrado: validar cobertura
      minima antes de `_try_write_reservatorios()`. Replicavel em
      ENA, balanco, etc. Nao implementado nesta sessao.

    **Bug 2 (Despacho Termico) - data_ini/data_fim ao trocar
    sub-view** (commit `7b57925`, 36 linhas):
    - Sintoma: Eneva Mensal customizado -> SIN Diario -> volta
      pra Eneva Mensal resultava em `data_ini == data_fim ==
      max_d` (range zero, grafico com 1 ponto).
    - Diagnostico via debug `st.write` em runtime: `prev_gran ==
      gran_atual == "Mensal"`, `em_transicao=False`, sentinelas
      de dataset inalteradas, `data_ini=None data_fim=None`
      (cleanup deletou as keys), `precisa_reset=False` no v1 do
      gatilho, widget recria keys clamped pra `max_value`.
    - Causa raiz: widget cleanup do Streamlit ao trocar sub-view
      DELETA `termico_<sub>_data_ini/_data_fim`. Reset block
      tinha 3 gatilhos (dataset_max, dataset_min, em_transicao)
      mas nenhum detectava cleanup. Gatilho prescrito em Geracao
      (decisao 5.16, Fase E.12) usava `data_ini >= data_fim` -
      mas em Despacho Termico as keys sao DELETADAS (nao stale),
      entao `"X" in state` retorna False e a comparacao `>=`
      nunca executa.
    - Fix v1 (rejeitado): replicar Geracao com `AND in state` -
      nao detectava cleanup.
    - Fix v2 (aplicado): trocar AND por OR no gatilho - dispara
      reset se `key not in state OR range degenerado`. Curto-
      circuito do `or` protege contra KeyError. Aplicado em
      Sistema (`app.py:3322`) e Eneva (`app.py:4229`). Refinou
      decisao 5.16 com nota sobre 2 modos do cleanup (Geracao =
      keys recriadas com valor stale; Despacho Termico = keys
      deletadas).

    **Fase Nav.1 - refator radio principal pra botoes custom**
    (commit `a43ffce`, 86 inserts / 5 deletes; decisao 5.52):
    - Substitui `st.radio NAVEGACAO` por loop de `st.button` com
      state `aba_selecionada`.
    - Pre-requisito pra Fase Nav.2 (intercalar sub-itens
      condicionais).
    - CSS scoped com keys `nav_aba_*`: alinhamento esquerdo,
      primary amarelo Bauhaus, secondary transparente cream,
      hover replica visual do ativo.
    - Compativel com 7 branches `if/elif aba == ...` sem mudancas
      (variavel `aba` retorna do state).

    **Fase Nav.2 - sub-itens Eneva/SIN no sidebar + remocao dos
    pills** (commit `c5ecf15`, 82 inserts / 61 deletes; decisao
    5.53):
    - Sub-itens condicionais embaixo de "Despacho Termico" via
      bloco condicional dentro do loop `nav_aba_`. Visiveis
      apenas quando essa aba esta ativa.
    - Indicador ativo: caractere `|` (U+2502) prefixado no label
      via Python (`f"| {nome}"` se ativo) + CSS `::first-letter`
      em amarelo Bauhaus. Solucao escolhida apos rejeitar `::
      before` (fragilidade com flex layout) e `border-left` (sem
      controle de altura).
    - Pills removidos do conteudo principal (60 linhas: CSS
      scoped + 2 `st.button`). Titulo dinamico h1 e branch `if
      subview == "Sistema":` preservados.

    **Bugs descobertos e corrigidos durante a sessao**:
    - Bug 1 (Reservatorios cache truncado) - inspecao via debug
      temporario revelou parquet stale.
    - Bug 2 v1 (gatilho de Geracao nao funciona em Despacho
      Termico) - debug em runtime revelou que cleanup deleta
      keys em vez de deixar stale.
    - PowerShell encoding hell (commit `c5ecf15` cleanup do
      em-dash) - documentado na armadilha 4.6 com 4 chars nao-
      ASCII no `.commit_msg.txt` apos `Set-Content -Encoding
      UTF8 + Get-Content -Raw`.

    **Bug pendente (nao incluido nesta sessao)**: granularidade
    Eneva/Sistema tambem nao preserva ao trocar sub-view. Mesma
    familia widget cleanup. Sintoma menos critico (volta pra
    Mensal default, ainda usavel). Fica pra proxima sessao -
    fix provavel: salvar `_termico_<sub>_last_gran` ao trocar
    sub-view, restaurar ao voltar.

    **Decisoes adicionadas nesta sessao**: 5.52 (Fase Nav.1),
    5.53 (Fase Nav.2). Refinamento aplicado: 5.16 (extensao
    para o caso de keys deletadas). Armadilha adicionada: 4.6
    (PowerShell 5.1 + UTF-8 + BOM).

27. **Drill-down hierarquico SIN completo (07/05/2026 - sessao 2)**.
    Continuacao da sessao 07/05/2026. Implementa drill-down clicavel
    no SIN do Despacho Termico do zero ate funcional (Mensal -> Diario
    -> Horario com cascata e click em barras).

    **Fases entregues** (6 sub-fases, 3 commits):
    - Drill.1 (`acdb336`): refactor agregacao SIN em
      `_agregar_termico_sistema` helper.
    - Drill.2.A + B.0 (`108ab8f`): helpers de filtragem
      (`_filtrar_termico_por_mes`, `_filtrar_termico_por_dia`) +
      state init (`drill_mes`, `drill_dia`) + extracao de figura
      em `_construir_figura_termico_sin`.
    - Drill.2.B (`3de3704`): renderizacao de 2 graficos drill-down
      estaticos em colunas 50/50 quando granularidade = "Mensal".
    - Drill.2.C + D (`b1f5c72`): click em barras + polish dos
      captions.

    **Cascata de drill-down**:
    - Click no Mensal -> atualiza `drill_mes` + cascata
      `drill_dia=ultimo_dia_do_mes`.
    - Click no Drill Diario -> atualiza `drill_dia` (sem cascata).
    - Drill Horario: nao-clicavel.

    **Trabalho diagnostico massivo durante a sessao**:
    - Diagnostico de inversao do grafico (causa: Streamlit rodando
      do Python global, nao do venv — armadilha 4.7 nova).
    - Diagnostico de fundo preto no iframe (causa: tema dark do
      Streamlit injetado em iframe da lib — decisao 5.56 nova).
    - Pesquisa exaustiva por libs alternativas
      (`streamlit-plotly-events-mod` nao existe;
      `streamlit-plotly-events-custom-data` inativo;
      Plotly events nativo nao funciona em "x unified").
    - Plotly downgrade pra `<6.0` (lib `streamlit-plotly-events`
      0.0.6 quebra com Plotly 6.x).

    **Workaround visual** (decisao 5.56): JS injection cross-iframe
    via `components.html` + `setInterval` 500ms pra capturar reruns
    do `plotly_events`. Idempotencia via `id="bauhaus-bg-override"`.

    **Decisoes documentadas nesta sessao**: 5.54 (drill-down
    hierarquico), 5.55 (captura de click via `streamlit-plotly-
    events`), 5.56 (JS injection pra fundo preto).

    **Armadilha documentada**: 4.7 (Streamlit Python global vs venv).

    **requirements.txt atualizado**:
    - `streamlit-plotly-events==0.0.6` adicionado.
    - `plotly>=5.22,<6.0` (apertado de `<7.0`).

    **Arquivos artefato gerados na sessao** (untracked, gitignore-
    avel): `test_fig.html` + `test_fig.py` (smoke test de
    construcao isolada de figura Plotly pra diagnostico).

    **Bugs pendentes** (nao incluidos nesta sessao):
    - Granularidade Eneva/Sistema preserva ao trocar sub-view (do
      entry 26).
    - Validacao cobertura minima em `load_reservatorios` (do
      entry 26).
    - Limpar import duplicado `streamlit.components.v1` (linhas
      590 + 631 do `app.py`).

    **Push final**: `b1f5c72` em `origin/main`. 14 commits
    acumulados na branch (alguns desta sessao + alguns da sessao
    anterior do mesmo dia 07/05/2026 entry 26).

28. **Refactor dual-loader Despacho Termico - resolve OOM Cloud (08/05/2026)**.
    Continuacao do "Oh no" da sessao 07/05/2026 entry 27. Drill.2.C tinha
    ido a producao mas aba inteira quebrava no Cloud.

    **Diagnostico**:
    - Browser DevTools mostrou WebSocket onclose + 503 nos endpoints.
    - Logs servidor sem traceback (sintoma de SIGKILL externo).
    - TEMP-DEBUG print confirmou OOM: 1190.1MB / 4,202,448 rows.

    **Solucao** (ver decisao 5.57): dual-loader.
    - carregar_termico passou a agregar DIARIO no worker (13 cols /
      ~175k rows / 49.4MB).
    - carregar_termico_horario_dia(dia) novo, lazy, single-day (14 cols /
      ~1900 rows / 250KB).

    **Implementacao em 5 fases**:
    - Fase 1: helper _agregar_diario_no_worker.
    - Fase 2: integrar agregador no carregar_termico (estrategia hibrida -
      agregar no loop, normalize/mapear pos-concat pra preservar decisao
      GLOBAL Fase A.1).
    - Fase 3: novo loader carregar_termico_horario_dia.
    - Fase 4: 4 edits em app.py (import + drill Horario + Sistema
      top-level + Eneva top-level), pattern OVERRIDE pos-filter.
    - Fase 5: cleanup (clear cache do novo loader, remove TEMP-DEBUG,
      RESTAURA setInterval do JS injection que tinha sido removido em
      02c65f1 supondo erradamente que era polling - agora seguro com
      RAM resolvida).

    **Hotfixes previos da mesma sessao** (todos parciais ou
    ortogonais):
    - 4e9cd95: data_loader_termico.py faltante (untracked).
    - 02c65f1: remove setInterval supondo polling.
    - d62215a: gc + del.
    - **0ec63e9: dual-loader (CAUSA RAIZ resolvida)**.

    **Decisoes documentadas**: 5.57 (dual-loader pattern).
    **Armadilhas documentadas**: 4.8 (OOM silencioso no Cloud).

    **Validacao**:
    - Local: TEMP-DEBUG mostrou 49.4MB / 175k rows (24x reducao).
    - Cloud: todos os modos OK (Sistema + Eneva, todas granularidades,
      drill-down clicavel).
    - Bordas pretas dos iframes plotly_events sumiram (setInterval
      restaurado).

29. **Aba Modulação criada (11/05/2026)** — spread de captura por
    (submercado, fonte), granularidades Mensal/Trimestral/Semanal.
    Decisão 5.61, 5 commits sequenciais (`86df183` → `99d4cc8`),
    deploy em produção.

    Fórmula A (horária pura): PLD ponderado pela geração − PLD flat
    (R$/MWh). Positivo = fonte gera mais nas horas caras; negativo =
    gera mais nas horas baratas. Padrão de mercados de energia.

    Arquitetura: `components/tab_modulacao.py` (~566 linhas), cache
    2-layer (RAM 30d + disk 24h), 3 parquets independentes por
    granularidade (`modulacao_spread_v2_{mensal,trimestral,semanal}`).
    Reusa `load_balanco_subsistema()` + `load_pld_horaria()` via
    merge inner por `(submercado, data_hora)`.

    UX: 4 gráficos full-width empilhados (SE/S/NE/N), grouped bar
    com linha y=0, eixo Y autônomo por submercado, labels bold
    coloridos acima das barras, hover decimal BR. Selectbox de
    granularidade + 2 botões preset contextuais (defaults 12M/24M/3M).

    Backlog: PLD nacional ponderado (habilita SIN), refator paleta
    Bauhaus pra `utils/bauhaus_palette.py` (decisão 5.33), badge
    "baixa representatividade" via `mwmed_medio`.

30. **Refactor PLD consolidado (12/05/2026)** — remoção dos checkboxes
    SE/S/NE/N/SIN (filtragem migrada pra legenda nativa do Plotly),
    remoção do SIN da camada de UI da aba PLD (data layer preservado),
    e reativação da granularidade "PLD médio semanal" — reverte
    parcialmente `bc8f466` (preserva §5.36 e seu helper
    `_aplica_default_pld_inline`), com hover via trace ghost no pattern
    da Capacidade (Commit G). Detalhes em §5.68. Débito técnico
    registrado em §9.1 (docstring desatualizada de
    `_normalize_semanal`).

31. **Disk-cache pro PLD semanal e mensal (13/05/2026)** — Frente 1 da
    sub-sessão pós-e152458. `load_pld_media_semanal` e
    `load_pld_media_mensal` ganharam disk-cache via `_make_disk_cache_helpers`
    (TTL 24h), revisando a decisão antiga (`data_loader.py:1593-1594`) que
    excluía as 2 granularidades. Motivação: uso real do semanal pós-
    reativação (decisão 5.68) revelou cold load de poucos segundos
    incômodo; smoke test descobriu dor análoga no mensal. Pattern idêntico
    ao do diário/horário PLD, zero breaking change. `clear_cache()`
    estendido pra cobrir os 2 novos parquets (tupla cresceu de 6 pra 8
    disk-caches) — gap identificado durante a redação inicial da decisão.
    Números: semanal 4.013s → 0.011s (~365×), mensal 1.856s → 0.020s
    (~92×). Docstring desatualizada do semanal corrigida no mesmo commit
    (resolve caminho mínimo do §9.1). Detalhes em §5.69. Horário fica
    pra Frente 2 separada (já tem disk-cache, gargalo ambíguo).

32. **Disk-cache por ano fechado pro PLD horário e diário (13/05/2026)** —
    Frente 2 da sub-sessão pós-883acec. `_download_year_pld_historico`
    refatorado pra usar disk-cache por ano fechado no lugar do
    `@st.cache_data(ttl=30d)` RAM da Sessão 1.5b — cada `(ano, dataset)`
    ganha 1 parquet `pld_{dataset}_{ano}.parquet` (TTL 30d, anos fechados
    imutáveis). Helper lazy `_get_pld_year_disk_helpers(ano, dataset)`
    com memoização em dict global `_PLD_YEAR_HELPERS_CACHE`. Escopo
    B-ambos (horário + diário compartilham a função refatorada).
    `clear_cache()` estendido com loop sobre `DATASET_YEARS_AVAILABLE`
    pra cobrir parquets por ano fechado. Diagnóstico empírico: cold load
    horário ~67-76s com 98% do tempo em HTTP CCEE Akamai (6 anos ×
    ~11-13s/ano). Pós-fix medido em 3 cenários: cold first-run pós-restart
    do container ~67s (parquets por ano vazios, idêntico ao pré-fix),
    cold pós-fix ~15s (5 disk-cache-ano + 1 HTTP do ano corrente),
    warm-disk consolidado ~33ms. Speedup B vs A: ~4,3×. Diário não foi
    medido empiricamente — mesma mecânica, speedup análogo esperado.
    Detalhes em §5.70.

33. **Lazy loading do PLD horário via modal de confirmação (13/05/2026)** —
    Frente 3 da sub-sessão pós-ff5d700. Sintoma reportado: primeira chamada
    de `load_pld_horaria` após restart do container do Cloud free tier ainda
    atinge ~80s mesmo pós-Frente 2. Refactor: `load_pld_horaria` ganhou
    `incluir_historico_completo: bool = False` — modo recente default (2
    anos, `pld_horaria_recente.parquet`) vs modo completo (anos 2021+,
    `pld_horaria.parquet` canônico). UI: modal `@st.dialog` disparado pelo
    botão "Máx" em modo recente, pattern híbrido (estrutura interna da
    Geração + flag intermediária `_pld_horaria_pending_modal` do Curtailment).
    `_render_period_controls` ganhou 2 params opcionais com defaults `None`
    (preservam 5 callers existentes). State `pld_horaria_historico_completo`
    em session_state, reset por `clear_cache`. `tab_modulacao.py:224` ajustado
    com flag explícita (Modulação precisa histórico completo). `clear_cache`
    estendido (2 pops novos + parquet recente, 9 consolidados ao total).
    Validação: smoke tests retornaram 47.808 linhas (recente) / 188.064
    (completo) + 7 cenários visuais aprovados localmente. Diário/semanal/mensal
    não migrados (cold ~5-30s, sem ganho). Frente 3.1 separada pendente
    (linha + range de datas na aba PLD, UI consistency). Detalhes em §5.71.

34. **Polish da aba PLD: linha + range de datas (13/05/2026)** —
    Frente 3.1 da sub-sessão pós-ff5d700 (polish da Frente 3 fechada no
    commit 8b54f9e). Adicionou linha horizontal + range de datas à direita
    na aba PLD, espelhando padrão visual de outras abas. Pattern inicial
    (flexbox com 2 spans, análogo a Reservatórios/ENA) deu desalinhamento
    visual; migrou pra Estratégia B (st.columns([3, 2]) + 2 widgets
    separados + linha como `<div>` isolado). 3 polish edits cosméticos
    adicionais: removeu border-bottom do CSS do selectbox, removeu
    "Indicadores do dia DD/MM/YYYY" (duplicava o range), borda da régua
    KPIs single-day #1A1A1A → #CCCCCC (régua coerente). Detalhes em §5.71.

35. **Sprint GSF — Fases 0 a 2D+++ (16/05/2026)** — sub-aba GSF (Fator
    de Ajuste do MRE) na aba Geração, 3ª sub-view depois de SIN e Eólica/
    Solar por Grupo. Fase 0 (descoberta da fórmula) foi a etapa mais cara:
    8 hipóteses estruturadas testadas — `MRE_MENSAL`, `MRE_HORARIO`,
    `GERACAO_UHE_V2`, alternativas de denominador (`GF_MODULADA_AJUSTADA_MRE`,
    `GF_FATOR_DISPONIBILIDADE`, `GF_SAZONALIZADA`), Itaipu (total + 50% +
    via `ENTREGA_MRE_ITAIPU`), exclusão de COTAS — todas rejeitadas até
    descobrir `GERACAO_HORARIA_SUBMERCADO` com `Σ(GERACAO_MRE) /
    Σ(GARANTIA_FISICA_MRE)` que bate 12/12 hits ±0.5pp contra 15 pontos
    oficiais (Power BI público CCEE + InfoPLD). Fase 1: loader
    `data_loaders/ccee_gsf.py` com cache 2-layer (RAM 6h + parquet por
    ano, TTL diferenciado 30d/24h), 3-strategy cascade CKAN→dump,
    `clear_gsf_cache()`. Fase 2: UI completa em `components/tab_gsf.py`
    — header + period controls (selectbox granularidade Mensal/Trimestral
    + selectbox MM/AAAA-ou-1T26 De/Até no padrão Modulação 7 colunas
    fixas) + gráfico Plotly (linha preta, paridade dashed, fills déficit
    vermelho e secundária sky blue, legenda topo 14px Inter) + tabela
    HTML "Últimos 12 meses" SEMPRE fixa mensal + footnote MR.2.1 +
    expander de diagnóstico. Bug widget cleanup cross-tab descoberto via
    prints temporários e resolvido com pattern shadow state (§5.18
    aplicado a GSF). Fases pendentes: 2E (KPIs + markers + hover
    JetBrains), 3 (validador automatizado), 4 (V2 histórico pré-2023).
    Modulação tem mesma vulnerabilidade estrutural mas fix não aplicado
    lá (não reportado em uso). Detalhes em §5.77.

---

## 8. Referências Cruzadas

- **`docs/roadmap.md`** — roadmap futuro do projeto (Sessão 4a fechada
  em 2026-04-29; sessões concluídas registradas na Seção 7 acima).
  Próximas sessões em ordem de prioridade: UX preservar estado entre
  abas e Curtailment (alta); GD ANEEL, comparar com, glossário inline
  e responsividade mobile (média); CSS caption (baixa); carga por
  classe, componentes da carga e carga vs PIB (menor).
- **`docs/sessao_geracao_status.md`** — status da aba Geração: roadmap
  de 3+1 sessões, histórico das mudanças, bugs descobertos/corrigidos
  na Sessão 1 (referenciados pelas decisões 5.11-5.13).
- **`docs/aba_geracao_spec.md`** — spec da aba Geração.
- **`docs/geracao_research.md`** — pesquisa Fase A Balanço de Energia
  (descoberta CKAN, schema parquet, smoke tests dos números 2024).
- **`docs/reservatorios_research.md`** — pesquisa detalhada da Fase A EAR
  (descobertas CKAN ONS, schema observado, validação do loader).
- **`docs/ena_research.md`** — pesquisa Fase A ENA (schema, URL pattern,
  4 métricas, fórmula SIN soma simples).
- **`docs/ons_dicionario_ear_subsistema.pdf`** — dicionário oficial ONS
  pro dataset `ear-diario-por-subsistema`.
- **`scripts/discover_ccee_ids.py`** — utilitário CKAN CCEE.
- **`scripts/validate_reservatorios.py`** — utilitário validação ONS EAR.
- **`scripts/validate_ena.py`** — utilitário validação ONS ENA.
- **`scripts/inspect_ena.py`** — utilitário de descoberta CKAN ENA (Fase A).
- **`scripts/inspect_gd.py`** — utilitário de descoberta CKAN ONS pra GD/MMGD
  (Sessão 3, 2026-04-26). Resultado: ONS não publica MMGD standalone por
  subsistema. Decisão 5.26 — GD descartada da aba Geração.
- **`requirements.txt`** — deps Python com versões.
- **`config.yaml.example`** — template de configuração de auth.
- **`.streamlit/config.toml`** — tema Streamlit.
- **`README.md`** — setup local + deploy.
- **`data_loaders/data_loader_termico.py`** — loader dataset
  `geracao_termica_despacho_2_ho` (ONS), schema horário nativo com
  coluna `hora` int8 (decisão 5.44).
- **`docs/termico_research.md`** — pesquisa Fase A (schema, URL pattern,
  smoke tests, USINAS_COBERTURA).

---

## 9. Pendências Abertas

Snapshot consolidado de tudo que aguarda execução. Cada item tem 1-3
linhas (o quê + ref §5.X de origem). Itens detalhados ficam na §5.X
correspondente — esta seção é o índice operacional.

### 9.1 Sprint GSF — fases não entregues (snapshot 16/05/2026)

- **Fase 3 — Script de validação automatizada.**
  `scripts/validar_gsf_calculado_vs_mre.py` rodando a fórmula do loader
  contra os 15 pontos oficiais com tolerância ±0,5pp. Útil como
  regressão contra mudanças silenciosas do dataset CCEE. Esforço
  ~1-2h. Detalhes em §5.77.

- **Fase 4 V2 — Extensão histórica pré-nov/2023.**
  Dataset CCEE só cobre nov/2023+. Loader stub
  `load_gsf_historico_pre2023()` preparado em `data_loaders/ccee_gsf.py`.
  Bloqueado em coleta manual de `data/raw/gsf_historico_pre2023.csv`.
  Detalhes em §5.77.

- **Fase 2E removida do roadmap (16/05/2026).**
  Hover JetBrains Mono + markers em GSF>100% + 3 KPIs topo foi
  descartado por decisão UX. Sub-aba GSF fica sem KPIs. Mantido aqui
  pra posteridade caso alguém pergunte por que não tem.

### 9.2 Modulação — bug widget cleanup pendente

- **Aplicar shadow state pattern na Modulação.**
  Mesma vulnerabilidade estrutural diagnosticada no GSF (§5.77 + §5.18):
  `mod_granularidade`, `mod_data_ini`, `mod_data_fim` são widget keys
  vulneráveis ao cleanup do Streamlit ao trocar de aba. Fix não
  aplicado lá porque o bug não foi reportado em uso real (suspeita:
  defaults entre granularidades são similares, então o reset é menos
  visível). Replicar `_SHADOW_MAP_MOD` + `_shadow_restore_mod()` +
  `_shadow_sync_mod()` seguindo o padrão de `components/tab_gsf.py`.
  Esforço ~30 min.

### 9.3 Deprecations Streamlit (com deadlines)

- **🔴 URGENTE — `st.components.v1.html` removido após 2026-06-01.**
  Provável uso no drill-down térmico SIN (§5.56 — JS injection
  cross-iframe). Substituir por `st.iframe`. Esforço ~1h. Deadline
  em ~2 semanas.

- **🟡 `use_container_width=True/False` → `width='stretch'`/`'content'`.**
  Sem deadline anunciado. Warnings aparecem no console. Esforço ~1h
  (find/replace seguro).

### 9.4 Backlog de UX e refatores

Itens documentados em §5.X que aguardam priorização:

- **PLD nacional ponderado SIN** — habilitaria visão SIN agregada na
  aba Modulação (hoje só 4 submercados — §5.61).
- **MWM/GWH em Eneva Trimestral** — backlog futuro (§5.51).
- **Refator paleta Bauhaus → `utils/bauhaus_palette.py`** — bloqueado
  por circular import, backlog cresceu com Curtailment + Geração Grupo
  + Modulação duplicando constantes (§5.61, §5.33).
- **Atualizar anchors MMGD** com valores reais SQL — depende do próximo
  release PDGD (~abr/2027) pra ter novo gold standard (§5.67).
- **Itens registrados na §5.66** "pra próxima sessão" (DthAtualiza-
  CadastralEmpreend / loader MMGD dinâmico).
- **Spinner CSS — texto invisível na aba PLD horário.** Investigar
  seletor `[data-testid='stSpinner']` específico do tema dark.
  Funcionalidade OK, problema é só visual.
- **Modulação lazy loading** — avaliar se o padrão da Frente 3 do PLD
  (§5.71, modo recente vs completo + modal) se aplica também à
  Modulação. Pode virar "Frente 4" ou generalização reusável.

### 9.5 Pendências de Curtailment (sessão 11/05/2026)

**Cosméticas:**

- Mover "Histórico em cache: XXX" pra footnote em `_render_visao_geral`.
- Padronizar UX "Total (E+S)" na aba Curtailment (alinhar com label
  introduzido em §5.60 pra Geração por Grupo).
- Padronizar grafia "Ribeiro Goncalves" / "Ribeiro Gonçalves" no Excel
  `data/curtailment/unidades_geradoras.xlsx`.
- Adicionar Enel Green Power em `_GRUPOS_PRIORIZADOS`.

**Validações de dados (sem urgência mas importantes):**

- Validar dono real de `CONJ. SERTÃO SOLAR BARREIRAS` via ANEEL/SIGA
  (§5.60 deixou em aberto após investigação não conclusiva).
- Confirmar dono real de `CONJ. RIBEIRO GONÇALVES 500 KV` via ANEEL —
  atualmente em "Other" (§5.60).
- Investigar 21k linhas marcadas como "Other" no rateio — pode haver
  grupos identificáveis perdidos.
- Gap residual ~4% pós-fix Equatorial Solar 4T25 pode ser MMGD/Tipo III
  não capturado pelo constrained-off — investigar separadamente (§5.60).

### 9.6 Débitos técnicos resolvidos (histórico)

Itens que já foram resolvidos pelo caminho mínimo mas onde resta um
caminho alternativo "melhor" — registro pra reavaliação futura.

**Docstring de `load_pld_media_semanal` — caminho mínimo resolvido.**
Resolvido na Frente 1 da sub-sessão pós-e152458 (decisão 5.69):
docstring corrigida de `(data=ini-semana, data_fim=fim-semana,
submercado, pld)` para `(data=ini-semana, submercado, pld)` — reflete
o schema real produzido por `_normalize_semanal`.

*Caminho alternativo segue pendente:* adicionar coluna `data_fim` no
`_normalize_semanal` (custo: ~1 linha; benefício: alinha código e
docstring, simplifica consumidores que precisem do fim da semana —
ex: hover do PLD semanal computado em §5.68 via `pd.Timedelta(days=6)`
no render). Rompe decisão original do comentário interno em
`_normalize_semanal:551` ("pra evitar guardar coluna derivada") —
reavaliar se o trade-off ainda faz sentido quando houver consumidor
adicional além do hover.
