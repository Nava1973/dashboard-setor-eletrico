# Status da sessão — Aba Geração (ONS Balanço de Energia)

> **Sessão 1.5b (Performance global + default 15a) FECHADA + PUSHED em
> 2026-04-25.** Escopo expandido pra disk-cache em Reservatórios e ENA +
> default histórico 15a com expansão sob demanda na Geração. 4 decisões
> arquiteturais novas (5.17-5.20) + 1 marcada como superada (5.14). 3
> bugs encontrados/fixados durante implementação. 12 testes ✅.
>
> Branch local: **em sync com `origin/main`** (4 commits pushed):
> - `87a1eb1` — 5 gráficos empilhados (pré-reversão)
> - `e7db917` — Sessão 1 (reversão pra gráfico único + fixes)
> - `efc7c38` — Sessão 1.5 (performance: disk-cache + filter sem dt.date)
> - `9142e9c` — Sessão 1.5b (perf global + default 15a + UX dois eixos)
>
> Push: `4be9f33..9142e9c main -> main` em 2026-04-25. Streamlit Cloud
> redeployando em `dashboard-setor-eletrico.streamlit.app`.
>
> Próxima sessão é a **1.6 (ajustes estéticos)** ou **2 (Dia Típico)** —
> ordem flexível. Ver §0.

---

## 0. Roadmap — Geração

### Sessão 1 (2026-04-24) — Correções e reversão · ✅ CONCLUÍDA

**Objetivo cumprido:** destravar a aba (lentidão dos 5 gráficos), fechar
pendências de ontem, corrigir bugs descobertos durante a reversão.

1. ✅ **Reversão pra gráfico único com dropdown de submercado.**
   Decidido durante a sessão que **KPIs seguem o submercado** do dropdown
   (não fixos no SIN). Texto "Médias do período selecionado (SIN)." vira
   dinâmico: `(SIN)` / `(Sudeste/Centro-Oeste)` / `(Sul)` / `(Nordeste)` /
   `(Norte)`. Export CSV mantém os 5 subsistemas (tela ≠ CSV por design).
   Gráfico altura 450px, legenda sempre visível, anotação 29/04/2023 1×.
2. ✅ **Bug visual "Data inicial" fantasma.** Era artefato de
   carregamento (5 gráficos pesados), não bug funcional. Resolvido
   indiretamente pela reversão. Defesa preventiva: mode-transition
   cleanup que limpa keys da Horária ao sair do modo.
3. ✅ **Nota explicativa de intercâmbio adicionada.**
4. ✅ **Checklist visual completo:** Mensal (1M removido, formato
   `mai/2025 a abr/2026`), Horária (1D/7D/30D/90D), Diária, guard
   <2 pontos + botão "Ver curva horária", export CSV no Excel BR,
   anotação 29/04/2023, cor eólica verde-oliva.

### Sessão 1.5 — Performance da aba Geração · ✅ CONCLUÍDA (2026-04-25)

**Problema:** aba lenta em comparação com as outras (~60-90s por
interação vs. ~instantâneo nas outras). Causa: dataset de 6,7M linhas
× 27 anos, com filter `dt.date` chamado 5× por render no loop dos 5
submercados.

**Fluxo da sessão:**

1. **Fase A — Diagnóstico.** Instrumentou app.py e data_loader.py com
   `time.perf_counter()` em cada etapa. Descoberto que o gargalo não
   era render Plotly nem cache miss — era o filtro de período: cada
   chamada `df_gen["data_hora"].dt.date >= data_ini` materializa
   Series de 6,7M Python `date` objects. Loop dos 5 submercados =
   10× materializações = ~55s no hot path.

2. **Fix #1 — Pré-computar `data` no loader.** Adicionada coluna
   `df["data"] = df["data_hora"].dt.normalize()` em
   `load_balanco_subsistema` (1× total, cacheada). No `_build_pivot_submercado`
   trocado pra `df_gen["data"] >= pd.Timestamp(data_ini)` — comparação
   vetorizada em datetime64. **Filter de ~11s/sub pra ~50ms/sub** (50×).

3. **Fix #3 — Cache persistente em disco (parquet local).** Camada
   nova entre `@st.cache_data` em-memória e download HTTP. Path com
   cascade `~/.cache/dashboard-setor-eletrico/balanco.parquet` →
   `tempfile.gettempdir()/...` (degradação graciosa se FS read-only).
   TTL 6h via mtime. `clear_cache()` estendida pra `unlink()`. **Cold
   start subsequente: 60s → ~1-2s.**

4. **Fix #4 — Spinner dinâmico.** Helper público
   `is_balanco_cache_fresh()` exposto pelo data_loader. App escolhe
   mensagem antes do `with st.spinner(...)`: light ("Carregando dados
   de geração...") quando disk-cache fresco, pesado ("Baixando 27 anos
   de dados ONS (~25MB)...") quando ausente/expirado. Define expectativa
   honesta de ~1min só na 1ª vez.

5. **Bug descoberto: `KeyError 'gen_data_ini'` no Cenário 3.** Ao
   clicar Atualizar com sessão que passou por Horária, o widget-state
   cleanup do Streamlit pode descartar `gen_data_ini`/`gen_data_fim`
   (widgets não instanciados em algum rerun intermediário). Sentinela
   atual `_gen_dataset_max` não cobria. **Fix:** estender condição do
   reset block pra também disparar quando essas keys estão ausentes
   individualmente (decisão 5.16 do CLAUDE.md).

**Tabela de ganhos (medidos antes/depois nos mesmos cenários):**

| Cenário | Antes | Depois | Ganho |
|---|---:|---:|---:|
| Cold start (com disk-cache hit) | 81s | 7s | 11× |
| Hot path (troca de submercado, Diária 12M) | 59s | 8s | 7,5× |
| Mensal 12M | 57s | 15s | 3,7× |
| Horária 30D | 91s | 14s | 6,5× |

**Decisões arquiteturais consolidadas no CLAUDE.md:**

- **5.15** Disk-cache de parquets ONS (path com cascade + lru_cache +
  degradação graciosa).
- **5.16** Sentinela do reset block estendida com keys individuais
  contra widget-state cleanup do Streamlit.

**O que ficou pra Sessão 1.5b:** mesmo com disk-cache, 27 anos × 6,7M
linhas é desnecessário pra 99% dos usos. Próximo passo: default
histórico de 15 anos + carregamento sob demanda do completo (ver
abaixo).

### Sessão 1.5b — Performance global + default 15a · ✅ CONCLUÍDA (2026-04-25)

**Escopo expandido durante a sessão:** após reportar lentidão também em
Reservatórios (~20s) e ENA (~30s) no cold load, o escopo da 1.5b passou
de "só Geração 15a" pra **disk-cache global em todos os datasets ONS** +
default 15a na Geração.

**Implementação em 5 partes (ordem):**

1. **Fábrica `_make_disk_cache_helpers(cache_name, ttl_sec)`** —
   substitui ~120 linhas duplicadas que existiriam em 4 datasets. Closure
   independente com `lru_cache(maxsize=1)` próprio: cada `cache_name`
   gera 4 callables (`get_path`, `is_fresh`, `try_read`, `try_write`)
   que não compartilham estado. Path resolver com cascade
   `home/.cache → tempfile.gettempdir()` + `write_test` por instância
   (`.write_test_{cache_name}`).
2. **Disk-cache em Reservatórios e ENA** — 2 chamadas da fábrica
   (`reservatorios.parquet` e `ena.parquet`) + early-return no início de
   `load_reservatorios`/`load_ena` + write no fim. Helpers públicos
   `is_reservatorios_cache_fresh()` e `is_ena_cache_fresh()` expostos.
3. **`load_balanco_subsistema(incluir_historico_completo=False)`** com
   flag — 2 chamadas da fábrica (`balanco_15anos.parquet` /
   `balanco_completo.parquet`). Default baixa
   `range(ano_corrente-14, ano_corrente+1)` (~3.9M linhas); flag True
   baixa `range(2000, ano_corrente+1)` (~6.7M linhas).
4. **UI Geração** — state `gen_historico_completo` (sticky default
   False), botão "📈 Carregar histórico completo (2000-2010)" perto dos
   presets, dispara `@st.dialog` (helper `_confirmar_historico_completo_gen`
   top-level). Confirmação: seta flag + `st.rerun()`. Após confirmar:
   loader chamado com True, `min_d_gen` expande pra 2000, botão vira
   caption "✓ Histórico completo carregado". Spinner dinâmico ciente
   da variante (mensagens distintas pra 15a vs completo). Presets
   revisados:

   | Granularidade | Presets |
   |---|---|
   | Diária | 1M / 3M / 6M / 12M / 5A / **10A** / Máx |
   | Mensal | 3M / 6M / 12M / 5A / **10A** / **15A** / Máx |
   | Horária | 1D / 7D / 30D / 90D (inalterada) |

5. **`clear_cache()` estendido** — unlinks 4 parquets (15a, completo,
   reservatórios, ENA) via loop sobre os 4 `get_path`. Reseta
   `gen_historico_completo` da sessão pra coerência semântica
   ("Atualizar = começar do zero"). Decisão 5.17 do CLAUDE.md consolida
   o padrão (dois eixos: range do dataset vs período visível).

**Decisões arquiteturais consolidadas no CLAUDE.md (4 novas):**

- **5.17** Dois eixos: range do dataset (carregamento sob demanda
  via modal) vs período visível (presets). Não misturar — preset "Máx"
  navega dentro do range, expansão é ação separada.
- **5.18** Backup paralelo pra widgets selectbox sujeitos a cleanup.
  Mesmo padrão da 5.16 (que cobriu `st.date_input`), agora aplicado
  a `gen_granularidade` e `gen_submercado` na Geração. Defesa
  preventiva contra widget-state cleanup do Streamlit em ciclos
  pesados (clear_cache → rerun → load >5s).
- **5.19** Sentinela do reset com EXCEÇÃO por modo (refinamento da 5.16).
  Em modos onde keys são widget-state alheias e cleanup é normal/esperado
  (ex: Horária não usa `gen_data_ini`/`gen_data_fim`), excluir a checagem
  individual desse modo. Sem isso, reset disparava em todo render Horária
  pós-cleanup, popando window.
- **5.20** Defaults por granularidade + reset block unificado. Cada modo
  tem default próprio (Diária 1M, Mensal 12M, Horária 1D + max_d), aplicado
  pelo reset em 5 gatilhos (1ª visita / dataset mudou / transição /
  force_reset / keys ausentes não-Horária). Substitui blocos espalhados.
  **5.14 marcada como SUPERADA** — auto-ajuste Mensal absorvido pelos
  defaults novos.

**3 bugs descobertos e corrigidos durante teste pós-implementação:**

**Bug A — Datas cortadas no `_render_period_controls`.** Sintoma:
campos "Data inicial" / "Data final" mostravam `2025/04/2` (faltando
último dígito) na Geração após a 1.5b. Causa: 7 presets (vs 5 nas
outras abas) reduziam fração de coluna do `date_input` de ~16% (~161px)
pra ~13% (~131px) — abaixo do mínimo pra `dd/mm/yyyy` caber. Fix
cirúrgico em `app.py:537`: ratio adaptativo `1.8 if n > 5 else 1.4`
no helper. Outras 3 abas (PLD/Reservatórios/ENA) ficam intocadas.

**Bug B — Dessincronia de granularidade pós-Atualizar.** Sintoma:
após "Atualizar" com Mensal+histórico completo, dropdown visual
mostrava "Mensal" mas presets renderizavam de Diária e gráfico
renderizava como Diária. Workaround manual: trocar pra Diária e
voltar pra Mensal. Causa: widget-state cleanup do Streamlit (mesmo
padrão da decisão 5.16, que cobriu `gen_data_ini`/`gen_data_fim`).
No ciclo pesado pós-Atualizar (clear_cache → rerun → load 15s →
re-render), `gen_granularidade` é descartada do state. Widget
recria com default "Diária", mas DOM do navegador exibe valor
antigo cached por 1+ frame. Fix: backup paralelo (decisão 5.18 do
CLAUDE.md) — `_gen_granularidade_backup` e `_gen_submercado_backup`
em keys NÃO widget-state, restaurados antes do widget + atualizados
pós-render. Aplicado preventivamente também em `gen_submercado`
pelo mesmo risco.

**Bug C — Botões 7D/30D/90D na Horária não respondiam.** Sintoma:
em Horária, apenas 1D (default) funcionava. Cliques em 7D/30D/90D
não atualizavam nada — botão 1D continuava amarelo, gráfico continuava
mostrando 1 dia. Causa: regressão da própria decisão 5.16 (Sessão 1.5).
A sentinela estendida com `gen_data_ini`/`gen_data_fim` ausentes
disparava em TODO render Horária — esses keys são widget-state de
`st.date_input` em `_render_period_controls` (Diária/Mensal), e em
Horária esses widgets NÃO são instanciados → cleanup descarta
NORMALMENTE → reset disparava → popava `gen_horaria_window_dias` →
init re-setava pra 1 → click no 7D era perdido. Fix: decisão 5.19
EXCLUI a Horária da checagem de keys individuais — `em_horaria=True`
pula esse termo da condição. Reset continua disparando em Horária
por sentinela (1ª visita) ou mudança de dataset, mas não pelos keys
órfãos que são esperados estar ausentes.

**Estimativa de impacto (a validar pós-deploy):**
- Reservatórios cold com disk-cache hit: ~20s → ~1-2s (10×)
- ENA cold com disk-cache hit: ~30s → ~1-2s (15×)
- Geração 15a cold (sem disk): ~25s vs ~60s do 27a anterior (~2× só
  pela menor lista)
- Geração 15a cold com disk-cache: ~1-2s
- Geração completo cold (sob demanda): ~25s primeira vez, ~1-2s subsequentes

**Validação manual completa — 12 cenários (todos ✅):**

| # | Cenário | Resultado |
|---|---|---|
| 1 | Hard restart → 1ª entrada Geração | ✅ abre em Horária + 1D + max_d_gen |
| 2 | Trocar pra Diária | ✅ default 1M (max_d-30 → max_d) |
| 3 | Trocar pra Mensal | ✅ default 12M (max_d-365 → max_d) |
| 4 | Trocar pra Horária | ✅ default 1D + data_base = max_d |
| 5 | Mudar período manual em Diária (ex: 6M) | ✅ escolha preservada nos próximos reruns |
| 6 | Mensal → Horária 7D → Mensal | ✅ default 12M, sem cair no guard <2 pontos |
| 7 | Atualizar em Diária 6M | ✅ reseta pra Diária 1M (force_reset flag) |
| 8 | Atualizar em Mensal 5A | ✅ reseta pra Mensal 12M |
| 9 | Atualizar em Horária 30D | ✅ reseta pra Horária 1D + max_d_gen |
| 10 | Modal "Carregar histórico completo" + confirmar | ✅ range expande pra 2000-2026 |
| 11 | Botões 7D/30D/90D em Horária | ✅ funcionam (5.19 cobriu regressão) |
| 12 | Datas completas nos date_inputs (Diária 7 presets) | ✅ `dd/mm/yyyy` sem corte (5.20+ratio 1.8) |

### Sessão 1.6 — Ajustes estéticos & UX

Observações coletadas pelo user testando a aba ao final da Sessão 1.
Mistura **1 bug**, decisões de tipografia/hierarquia e pequenos
refinos de UX. Tarefas pequenas, mas afetam a percepção de polimento.

#### 1. [BUG] Data do canto superior direito do gráfico está incorreta

**Sintoma:** o lado direito do título Bauhaus mostra
`DD/MM/YYYY · X.XXX MWmed`, mas a data é **sempre a última do dataset**
(ex: 22/04/2026), não a do período visualizado. Não atualiza ao mudar
preset, data_base ou granularidade. Acontece em todas as granularidades.

**Decisão:** **remover totalmente o lado direito** do título Bauhaus
na aba Geração. A linha "Período: X a Y" abaixo do título já comunica
o período. Duas datas (uma errada) polui mais que ajuda.

**Onde mexer:** bloco do título em `app.py` (~linha 2380, dentro do
ramo `else` do guard `<2 pontos`). Remover a montagem de `right_side`
e o segundo `<span>` no `st.markdown` do título flex.

#### 2. Default da Horária = data mais recente do dataset

**Comportamento atual:** ao entrar em Horária pela 1ª vez (ou após
reset), `data_base` herda da seleção anterior (ex: `data_ini` da
Diária — pode ser arbitrária).

**Desejado:** ao entrar em Horária, abrir sempre com
`data_base = max_d_gen` + `window = 1D`. Usuário casual quer ver "como
foi ontem", não uma data aleatória que ele tinha selecionado antes.

**Onde mexer:** init de Horária em `app.py:~2099-2113`. Trocar o
`min(max_d_gen, get("gen_data_fim") or max_d_gen)` por
`max_d_gen` direto.

**Cuidado:** se o user manualmente escolheu uma data no `date_input`
"Data base" e depois trocou de aba/granularidade e voltou pra Horária,
ele vai perder a escolha. Avaliar se a regra "sempre `max_d_gen` no
init" é boa o suficiente, ou se vale uma flag tipo `_gen_data_base_user_set`
pra preservar escolha explícita.

#### 3. Mensal com período < 2 meses — fragilidade UX

**Problema atual:** o auto-ajuste implementado na Sessão 1 (decisão
5.14 do CLAUDE.md) dispara **silenciosamente** quando o user seleciona
< 60 dias em Mensal — força volta pra 3M sem avisar. Confuso para o
user ("escolhi 45 dias e o sistema mudou pra 90 sem explicar").

**Soluções a considerar (escolher na Sessão 1.6):**

a) **Validar + mensagem clara:** mostrar `st.warning` explicando
   *"Mensal requer pelo menos 2 meses. Selecione período maior ou
   troque pra Diária."*. Não auto-ajusta — bloqueia render do gráfico
   até user decidir.
b) **Converter automaticamente pra Diária** com `st.info` visível
   *"Período curto demais pra Mensal — exibindo em Diária."*
c) **Impedir a seleção:** limitar `min_value` do `date_input` em
   Mensal pra `max_d_gen - 60 dias` (não é escolha do user — proativo).

(a) preserva a intenção do user mas pede ação. (c) é preventivo
(impede o estado inválido). (b) é o auto-ajuste atual com aviso.

#### 4. Unidade `MWmed` (não `MWMED`)

**Padronização:** unidade escrita como `MWmed` (M e W maiúsculos, "med"
minúsculo) em **todos** os lugares — KPIs, hover do gráfico, eixo Y,
coluna do export CSV, notas explicativas.

**Bug visual atual:** nos KPIs, `MWmed` aparece como `MWMED` por causa
do `text-transform: uppercase` global do CSS Bauhaus aplicado a labels
de `st.metric`.

**Fix:** override CSS específico que remove `text-transform` da unidade
DENTRO dos cards de KPI, mantendo `uppercase` no rótulo
("GERAÇÃO TOTAL" / "TÉRMICA" / "% RENOV VARIÁVEL" / "CARGA").

#### 5. Tipografia comprimida nos KPIs

Os 4 cards estão com texto comprimido — número e unidade colados, sem
respiração. Revisar tipografia do componente KPI:

- Aumentar espaçamento entre número e unidade.
- Considerar aumentar tamanho da unidade.
- Avaliar peso visual geral dos cards (talvez número maior).

Tarefa de afinamento visual — comparar lado a lado com KPIs do PLD/ENA.

#### 6. Linha "Período" muito discreta

A linha `Período: DD/MM/YYYY a DD/MM/YYYY` abaixo do título está em
fonte pequena (~0.85rem) e cinza italic — quase invisível.

Sendo a **informação mais importante** da tela (qual período está
sendo visualizado), deveria ter peso visual maior.

**Sugestões:**
- Aumentar fonte (1rem ou 1.05rem).
- Trocar cinza claro por preto (pode manter italic).
- Negrito leve no número das datas.

#### 7. Realocar nota "Cada ponto representa..." pra perto do gráfico

**Atual:** a nota `Cada ponto representa a média X em MWmed` está no
bloco de notas do topo, junto com 4 outras notas (atualização ONS,
intercâmbio, GD, ...).

**Desejado:** mover essa nota pra **perto do gráfico** — à direita do
título do submercado, ou outra posição visualmente próxima.

**Princípio:** informação que descreve o gráfico fica perto do gráfico.
O bloco de notas do topo deve ficar reservado para contexto geral da
aba (data de atualização, intercâmbio, GD).

### Sessão 2 — Dia Típico

Nova granularidade **"Dia Típico"** — média por hora-do-dia ao longo do
período selecionado (24 pontos: 00h, 01h, ..., 23h). Útil pra visualizar
curva de pato (rampa térmica no fim de tarde).

**Considerar:** mostrar Dia Típico como **5 gráficos empilhados** (SIN +
SE/S/NE/N) — leve por ser só 24 pontos, não reintroduz a lentidão do
layout de 5 gráficos que motivou a reversão na Sessão 1.

### Sessão 3 — GD (Geração Distribuída)

Implementar `data_loader_ons_gd.py` de verdade (estimativa mensal do
ONS — hoje é stub). Adicionar GD como **5ª faixa vermelha no topo do
stacked**. Revisitar tratamento da quebra de 29/04/2023 na carga.

---

## 1. O que foi feito na sessão de ontem (2026-04-23)

> Histórico preservado pra referência. Marcadores `[MANTÉM]` /
> `[REVERTE]` / `[PARCIAL]` / `[OBSOLETO]` indicam o destino de cada
> item após a Sessão 1 (concluída — ver §0).

Duas micro-sessões consecutivas. Total de 9 ajustes implementados.
Commitados em `87a1eb1` (2026-04-24).

### 1.1. Pacote de 3 ajustes (manhã)

1. **[MANTÉM] Cor da eólica** trocada de cinza `#9B9B9B` → verde-oliva `#8FA31E`.
   Mudança pontual em `CORES_FONTE_GEN` no `app.py`. Cascata automática
   pra fill do stacked, hover e legenda.

2. **[MANTÉM] Presets condicionais à granularidade** — `1D/7D/30D/90D` na Horária
   (era `7D/30D/90D`). Diária e Mensal preservam `1M/3M/6M/12M/5A/Máx`
   (até #4 da tarde alterar Mensal).

3. **[MANTÉM] Modo "Data base + janela" na Horária** — refator maior:
   - Helper top-level **`_render_period_controls_horaria(...)`**, gêmeo
     assimétrico do `_render_period_controls`. 1 `date_input` "Data
     base" + presets como window de N dias terminando em data base.
   - Novas chaves session_state com prefixo `gen_`: `gen_data_base`
     (date) e `gen_horaria_window_dias` (int).
   - Em Horária, `data_ini/data_fim` são **DERIVADOS** de base+window e
     espelhados no state "range" pra preservar coerência ao alternar pra
     Diária/Mensal.
   - Bloco de reset de dataset (novo ano ONS) limpa também
     `gen_data_base` e `gen_horaria_window_dias`.
   - Botão "Ver curva horária deste dia" agora seta explicitamente
     `gen_data_base = data_fim_gen` e `gen_horaria_window_dias = 1`
     antes do rerun (não herda state stale).

### 1.2. Pacote de 6 ajustes (tarde)

Ordem: #5 → #4 → #1 → #2 → #3 → #6.

1. **[MANTÉM] #5 Diagnóstico 30D/90D em Horária** — análise estática NÃO
   identificou bug funcional. Hipótese provável: lentidão de render no
   browser por hover unified com 2.880 (30D) ou 8.640 (90D) pontos no
   stacked. Mitigação inicial: caption de aviso + spinner. **Sessão 1
   removeu o spinner (gráfico único é mais leve), manteve a caption.**
   **Sessão 1.5 vai atacar a lentidão na raiz.**

2. **[MANTÉM] #4 Removido "1M" de Mensal** — 1 mês = 1 ponto, caía no
   guard. Lista de presets ramifica por granularidade dentro do branch
   não-Horária. **Sessão 1 adicionou auto-ajuste pra 3M ao entrar em
   Mensal com período herdado curto (ver §3.5).**

3. **[PARCIAL → simplificado] #1 Linha "Período: ..." abaixo do
   título** — helper `_format_periodo_br(data_ini, data_fim, granularidade)`.
   Pós-reversão Sessão 1: renderização passa de 5× pra 1×.

4. **[MANTÉM] #2 Nota explicativa por granularidade** — adicionada como
   2ª nota no bloco de notas do topo da aba.

5. **[MANTÉM → dinâmica] #3 "Médias do período selecionado (SIN)."** —
   Sessão 1 trocou pra texto dinâmico por submercado: `(SIN)` /
   `(Sudeste/Centro-Oeste)` / `(Sul)` / `(Nordeste)` / `(Norte)`.

6. **[REVERTE] #6 Reorganização SIN + submercados empilhados** —
   revertido na Sessão 1. Loop dos 5 gráficos removido. Voltou a 1
   gráfico único com dropdown de submercado. **Preservado:** export
   CSV long-wide com 5 subsistemas, helpers `_build_pivot_submercado`
   e `pivots_por_sub`, guard <2 pontos.

### 1.3. Validação de sintaxe

`python -c "import ast; ast.parse(open('app.py'))"` → OK.

### 1.4. Teste visual parcial pelo usuário

Testou Diária + 1M, viu SUDESTE e SUL no layout vertical. Identificou
o "campo fantasma" (resolvido na Sessão 1 — era artefato de
carregamento, não bug funcional).

---

## 2. Pendências da sessão de ontem — TODAS RESOLVIDAS NA SESSÃO 1

### 2.1. ✅ BUG visual "Data inicial" fantasma — RESOLVIDO

**Diagnóstico real:** artefato de carregamento dos 5 gráficos pesados,
não bug funcional. Aparece e some quando a aba termina de renderizar.
Resolvido indiretamente pela reversão pra gráfico único (Sessão 1
item 1).

**Defesa preventiva adicionada** (`app.py:2042-2046`): mode-transition
cleanup que limpa `gen_data_base`/`gen_horaria_window_dias` ao sair
de Horária — evita widget órfão no Streamlit 1.56 caso o sintoma
volte por outra causa.

### 2.2. ✅ Nota explicativa de intercâmbio — ADICIONADA

3ª nota do bloco `notas_gen` (entre granularidade e GD). Texto exato
no `app.py:2185-2187`.

### 2.3. ✅ Checklist visual — TODOS PASSARAM

- ✅ **Mensal**: 1M removido, formato `mai/2025 a abr/2026`.
- ✅ **Horária**: 1D/7D/30D/90D — funcionando (após cadeia de bugs
  descobertos e corrigidos, ver §3).
- ✅ **Diária**: 1M/3M/6M/12M/5A/Máx.
- ✅ **Guard <2 pontos** em Diária 1 dia + botão "Ver curva horária
  deste dia" → troca pra Horária 1D corretamente (após fix §3.1).
- ✅ **Export CSV**: 5 subsistemas no Excel BR, dropdown não afeta CSV.
- ✅ **Anotação 29/04/2023**: 1× só (preset 5A ou Máx atravessa).
- ✅ **Cor eólica verde-oliva** em todos os submercados.
- ✅ **KPIs dinâmicos** por submercado (Norte ~0% renov, NE ~80%).

### 2.4. ✅ Atualização do CLAUDE.md — FEITA NESTA SESSÃO

CLAUDE.md atualizado com decisões 5.9 a 5.14 (numeração consecutiva,
não 5.15-5.21 como rascunhei antes — última decisão pré-existente
era 5.8):

- **5.9** Modo "Data base + janela" na Horária (Geração).
- **5.10** Geração: gráfico único com dropdown vs. 5 gráficos
  empilhados — tela ≠ CSV por design.
- **5.11** Sentinela `_gen_dataset_max` (não `gen_data_ini`) como
  heurística de "1ª visita" — descoberto em §3.2.
- **5.12** Flag intermediário pra modificar session_state de widget
  já instanciado — descoberto em §3.1.
- **5.13** Inits separados quando widget pode escrever `None` na key —
  descoberto em §3.4.
- **5.14** Auto-ajuste de período ao trocar pra granularidade
  incompatível — descoberto em §3.5.

Também atualizado: §3.4 (helpers `_render_period_controls_horaria` e
`_format_periodo_br`) e §7 (timeline entries 16-17 — primeira versão da
Geração + Sessão 1).

### 2.5. ✅ Commit da Sessão 1 — FEITO (push protelado)

- **Commit `87a1eb1`** (2026-04-23) — trabalho de ontem (5 gráficos
  empilhados, antes da reversão).
- **Commit `e7db917`** (2026-04-24) — Sessão 1: reversão pra gráfico
  único + 5 fixes + auto-ajuste Mensal + nota intercâmbio + atualização
  CLAUDE.md/sessao_geracao_status.md. 758 inserções, 454 remoções em 3
  arquivos.
- **Push: NÃO FEITO.** Decisão do user: protelar push pra após Sessão
  1.5 (performance) estar testada, evitando 2 redeploys seguidos no
  Streamlit Cloud. Quando pushar, ambos commits saem juntos pra
  `origin main`.

### 2.6. Pendentes de sessões anteriores → Sessões 2/3 do roadmap

- ~~**Granularidade "Dia Típico"**~~ → **Sessão 2 do roadmap (§0)**.
- ~~**`data_loader_ons_gd.py` real**~~ → **Sessão 3 do roadmap (§0)**.
- **[SEGUE]** Etapas 3/4/5 da spec original (pequenos múltiplos, aba
  Carga dedicada, aba curtailment) — fora de escopo até decisão posterior.

---

## 3. Bugs descobertos e corrigidos durante a Sessão 1

Durante a implementação da reversão, **5 bugs** foram descobertos. Cada
um foi resolvido cirurgicamente, sem refator. Documentados aqui pra
futura referência (alguns viram decisões em CLAUDE.md, ver §2.4).

### 3.1. `StreamlitAPIException` no botão "Ver curva horária deste dia"

**Sintoma:** clicar no botão dispara erro:

> `st.session_state.gen_granularidade cannot be modified after the
> widget with key gen_granularidade is instantiated.`

**Causa:** o botão estava no guard `<2 pontos` (depois do selectbox
de granularidade ser instanciado). Ele tentava setar
`session_state["gen_granularidade"] = "Horária"` direto, mas Streamlit
proíbe modificar a key de um widget já instanciado no mesmo run.

**Fix** (`app.py:2020-2025`): flag intermediário `_gen_force_horaria`
setado pelo botão + consumido com `pop()` no topo do bloco da aba,
antes do selectbox ser instanciado. Permite o botão alterar
granularidade sem violar a regra do Streamlit.

### 3.2. Heurística do reset de dataset disparando em todo render Horária

**Sintoma:** presets 7D/30D/90D em Horária não funcionavam — ao
clicar, gráfico permanecia em 1D, botão 1D continuava amarelo.

**Diagnóstico** (via debug `st.write` temporário): o reset block
(`app.py:2061+`) usava `"gen_data_ini" not in st.session_state` como
heurística de "1ª visita". Mas em Horária, `gen_data_ini` é
**derivado pós-helper** de `gen_data_base`/`window` — em todo render
Horária, a key não estava no state ANTES do reset block rodar →
reset disparava sempre → popava `gen_data_base` e
`gen_horaria_window_dias` → init re-setava window=1 → preset
clicado era ignorado.

**Fix** (`app.py:2065-2078`): trocar a sentinela pra
`"_gen_dataset_max" not in st.session_state`. `_gen_dataset_max` é
setado SÓ pelo próprio reset block, então é uma sentinela
confiável de "reset já rodou nesta sessão".

### 3.3. `gen_data_fim` sem fallback no init de Horária

**Sintoma:** `KeyError: 'st.session_state has no key "gen_data_fim"'`
ao entrar direto em Horária sem passar por Diária.

**Causa:** o init usava `st.session_state["gen_data_fim"]` (brackets,
sem default). Mas a key não existia se o reset block não tinha
disparado ainda nesse fluxo específico.

**Fix** (`app.py:2099-2104`): trocar por
`st.session_state.get("gen_data_fim") or max_d_gen`. `or` trata tanto
ausência quanto `None`.

### 3.4. Init de Horária resetando `window` ao reinicializar `gen_data_base`

**Sintoma:** mesmo após o fix do reset (§3.2), os presets 7D/30D/90D
ainda falhavam — `gen_data_base` aparecia como `None` no debug.

**Diagnóstico:** `st.date_input` em Streamlit 1.56 pode escrever
`None` em `session_state[key]` em alguns reruns (causa exata não
verificada, mas reproduzível). O check do init era
`if "gen_data_base" not in st.session_state:` — não cobria o caso de
key presente com valor `None`.

**Fix** (`app.py:2099-2113`): dois ajustes combinados:

1. Init de `gen_data_base` agora usa `not get(...)` (cobre ausência E
   `None`).
2. **Inits separados** de `gen_data_base` e `gen_horaria_window_dias`
   — reinicializar `gen_data_base` (porque virou `None`) **NÃO reseta
   `window` pra 1**. Antes, eram setados juntos no mesmo bloco, e
   reinicializar um destruía o outro.

### 3.5. Mensal caindo no guard `<2 pontos` ao vir de Horária 1D

**Sintoma:** trocar de Horária 1D pra Mensal sempre dispara o guard
(mostra `st.info` em vez do gráfico).

**Causa:** Horária 1D sempre tem `data_ini == data_fim` (1 dia).
Trocar pra Mensal mantém esse range. Mensal resample MS = 1 ponto
por mês → 1 ponto. Guard dispara.

**Fix** (`app.py:2135-2147`): auto-ajuste de período ao entrar em
Mensal — se período herdado < 60 dias, força 3M ancorado em
`max_d_gen` (equivalente a clicar no preset 3M). Aplicado **ANTES**
de `_render_period_controls` ser chamado, pra não colidir com a
regra de "não modifica session_state de widget instanciado".

---

## 4. Como retomar

Próxima sessão é a **Sessão 1.6 (ajustes estéticos & UX)** ou
**Sessão 2 (Dia Típico)** — ordem flexível.

1. **Confirmar que o Streamlit Cloud está verde** após o redeploy do
   commit `9142e9c` (push em 2026-04-25). URL:
   `dashboard-setor-eletrico.streamlit.app`. Em caso de falha, ver log
   via "Manage app" (armadilha 4.5 do CLAUDE.md).
2. **Validar ganhos da 1.5b em produção** abrindo Reservatórios e ENA
   pela 1ª vez (cold) — esperado ~20-30s na 1ª request do container,
   ~1-2s nas subsequentes (disk-cache hit em
   `/home/appuser/.cache/dashboard-setor-eletrico/`).
3. Validar a Geração com defaults novos: 1ª entrada = Horária 1D +
   max_d_gen, transições aplicam defaults da nova granularidade
   (Diária 1M, Mensal 12M, Horária 1D), modal "Carregar histórico
   completo" funcional.
4. Pra 1.6, abrir `docs/sessao_geracao_status.md` §0 itens 1-7 (lista de
   ajustes mistos: 1 bug + tipografia + UX).

---

## 5. Referências cruzadas

- `docs/aba_geracao_spec.md` — spec original.
- `docs/geracao_research.md` — Fase A (descoberta CKAN, schema, números).
- `CLAUDE.md` — guia geral do projeto (atualizado com decisões
  5.15 disk-cache, 5.16 widget-state cleanup, 5.17 dois eixos
  range vs período visível, 5.18 backup paralelo selectbox, 5.19
  exceção por modo no reset, 5.20 defaults por granularidade +
  reset block unificado; 5.14 marcada como SUPERADA pela 5.20).
- Commits relevantes (todos em `origin/main` após push em 2026-04-25):
  - `87a1eb1` (2026-04-23) — Geração 1ª versão (5 gráficos empilhados,
    antes da reversão).
  - `e7db917` (2026-04-24) — Sessão 1: reversão pra gráfico único +
    5 fixes + auto-ajuste Mensal + docs.
  - `efc7c38` (2026-04-25) — Sessão 1.5: Fix #1 (filter sem dt.date)
    + Fix #3 (disk-cache balanço) + Fix #4 (spinner) + extensão
    sentinela.
  - `9142e9c` (2026-04-25) — Sessão 1.5b: fábrica de helpers +
    disk-cache em Reservatórios/ENA + default 15a Geração + modal
    expansão + presets revisados + 3 bugs fixados (datas cortadas,
    dessincronia granularidade, regressão botões Horária) + decisões
    5.17-5.20.
  - Anteriores (já estavam em `origin/main`): `4be9f33`, `80634b5`,
    `87c8e72`.
- Disk-caches dos datasets ONS (Sessão 1.5b):
  `~/.cache/dashboard-setor-eletrico/{nome}.parquet` onde `{nome}` ∈
  `{balanco_15anos, balanco_completo, reservatorios, ena}`. Windows:
  `C:\Users\<USER>\.cache\dashboard-setor-eletrico\`. Fallback automático
  pra `tempfile.gettempdir()/dashboard-setor-eletrico/` se home for
  read-only.
- Helpers introduzidos (top-level no `app.py`):
  - `_render_period_controls_horaria` — modo "Data base + janela".
  - `_format_periodo_br` — string de período no formato BR por
    granularidade.
  - `_MESES_BR` — tabela de meses pt-BR.
- Helpers locais à aba Geração:
  - `_build_pivot_submercado(code)` — filtra+pivota por submercado.
    Pós-Sessão 1, alimenta tanto o dropdown de submercado quanto o
    loop do export CSV.
  - `_fmt_br_gen(v, casas)` — formato numérico BR.
- Constantes (no escopo do bloco da aba Geração):
  - `ORDEM_SUBSISTEMA_GEN`, `LABELS_SUBSISTEMA_GEN` (uppercase, pra
    título Bauhaus do gráfico) — agora também `NOME_SUB_LONGO`
    (title-case, pra dropdown e texto dos KPIs).
