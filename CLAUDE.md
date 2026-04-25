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

### 5.14 Auto-ajuste de período ao trocar pra granularidade incompatível

**Decisão:** ao trocar pra uma granularidade onde o período herdado
geraria <2 pontos no resample, **auto-ajustar** o período pra um
default razoável da nova granularidade.

**Caso concreto:** trocar de Horária 1D pra Mensal mantém
`data_ini == data_fim` (1 dia). Mensal resample MS = 1 ponto → guard
`<2 pontos` dispara. UX ruim — usuário não entende por que Mensal
"não funciona".

**Implementação** (Geração):
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
