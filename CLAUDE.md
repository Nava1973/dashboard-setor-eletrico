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
