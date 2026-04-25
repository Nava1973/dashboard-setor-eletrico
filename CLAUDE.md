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
- Rodapé: `Co-Authored-By: Claude <noreply@anthropic.com>` (Opus 4.7).
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

---

## 8. Referências Cruzadas

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
- **`requirements.txt`** — deps Python com versões.
- **`config.yaml.example`** — template de configuração de auth.
- **`.streamlit/config.toml`** — tema Streamlit.
- **`README.md`** — setup local + deploy.
