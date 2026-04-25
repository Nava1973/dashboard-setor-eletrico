# Status da sessão — Aba Geração (ONS Balanço de Energia)

> **Sessão 2 (Dia Típico) FECHADA em 2026-04-25.** Nova granularidade
> "Dia Típico" implementada: stacked area com 24 ticks `00:00...23:00`
> mostrando média horária ao longo do período selecionado (curva de
> pato canônica). 1 decisão arquitetural nova (5.25) + 5.20 estendida
> com default 30D pra Dia Típico. Sintaxe ✅ após cada mudança;
> testes de ponta a ponta validados pelo user.
>
> Branch local: **6 commits no main** (5 pushed + 1 a pushar):
> - `87a1eb1` — 5 gráficos empilhados (pré-reversão)
> - `e7db917` — Sessão 1 (reversão pra gráfico único + fixes)
> - `efc7c38` — Sessão 1.5 (performance: disk-cache + filter sem dt.date)
> - `9142e9c` — Sessão 1.5b (perf global + default 15a + UX dois eixos)
> - `1d58509` — Sessão 1.6 (ajustes estéticos + bug retorno de aba)
> - **(pendente)** Sessão 2 (Dia Típico — perfil 24h)
>
> Push da Sessão 2: pendente, aguardando review da mensagem.
>
> Próxima sessão é a **3 (GD)** — última do roadmap original. Ver §0.

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

### Sessão 1.6 — Ajustes estéticos & UX · ✅ CONCLUÍDA (2026-04-25)

**Escopo:** os 7 ajustes da observação do user (1 bug + tipografia + UX),
sem mudança de escopo no meio. Sessão pequena/direta — sem refator
estrutural, só estética e consistência. 4 decisões arquiteturais novas
+ 5.16/5.19 estendidas + 1 bug grave descoberto e fixado pós-implementação
via debug runtime.

**Resultado por ajuste:**

| # | Item | Resultado |
|---|---|---|
| 1 | Remover lado direito errado do título | ✅ User pediu pra unir com #6 — lado direito reaproveita o espaço pra linha "Período" (uniformizado com Reservatórios/ENA) |
| 2 | Default Horária = `max_d_gen` 1ª entrada | ✅ Já coberto pela 5.20 da 1.5b — confirmado por user em runtime sem trabalho |
| 3 | Bloqueio educativo Mensal < 2 meses | ✅ `st.warning + st.stop` quando manual < 60d (decisão 5.24) |
| 4 | MWmed virando MWMED nos KPIs | ✅ Refator pra HTML custom: `gen-kpi-value-num` Bebas + `gen-kpi-value-unit` Inter mixed-case (decisão 5.21). **Causa raiz NÃO era `text-transform`** — era a fonte Bebas Neue all-caps por design |
| 5 | Tipografia comprimida nos KPIs | ✅ Resolvido implicitamente pelo refator do #4 (margin-left 0.4rem entre número e unidade) |
| 6 | Linha "Período" mais visível | ✅ Movida pro lado direito do título Bauhaus (mesmo padrão Reservatórios/ENA: Bebas Neue herdado, sem "Período:" prefix) |
| 7 | Realocar nota "Cada ponto representa..." | ✅ Tag compacta entre título e gráfico ("Média mensal · MWmed", decisão 5.22), removida do bloco geral de notas |

**Bonus aplicados durante a sessão (não estavam na lista original):**

1. **Travessão `–` no `_format_periodo_br`** — substituído ` a ` por
   ` – ` (en dash, U+2013) em todos os ramos. Convenção tipográfica
   pra ranges. Branch novo Horária ≥2D mesmo ano: formato curto
   `DD/MM – DD/MM` sem ano (com fallback pra ano em ambos lados se
   atravessa virada de ano — caso raro mas real em 90D ancorado em
   jan/fev).

2. **Override Bauhaus em `st.alert` (decisão 5.23)** — tema dark
   (`textColor: #f2f2f2`) deixava warning Mensal <60d com texto branco
   sobre fundo amarelo, ilegível. Override em camadas: container externo
   `[data-testid="stAlert"]` recebe TODO o visual (BAUHAUS_LIGHT + borda
   preta 2px sólida + box-shadow none + margins), descendentes ficam
   transparentes. Aplica a warning/info/error/success — diferenciação
   semântica preservada via ícone do Streamlit. Cor `BAUHAUS_LIGHT`
   (`#E8E3D4`, "elementos sutis" do sistema de cores §3.1) escolhida
   após teste com `BAUHAUS_CREAM` (igual ao fundo da página) que
   "transparentizava" o alert.

3. **Reposicionamento do guard `<2 pontos` + st.stop (decisão 5.24)** —
   guard estava DEPOIS dos KPIs/export, então KPIs apareciam com 1
   ponto (calculados sobre `pivot_sel.mean()` de 1 valor) + botão de
   export ficava ativo. Movido pra ANTES dos KPIs com `st.stop()`
   final. Refator de 18 linhas removidas + 143 linhas desindentadas
   (todo o conteúdo do antigo `else` do `if/else` legacy desindentado
   4 espaços) via script Python pra evitar erros manuais. Coerência
   total com o guard Mensal <60d (decisão 5.24).

**Iterações visuais durante a sessão (5 trocas de feedback):**

1. Fix #1 → user pediu pra unir com #6 (lado direito vira período em
   vez de remover totalmente).
2. Fix #1+#6 v1 (Inter italic 1rem com prefix "Período:") → user pediu
   uniformizar 100% com Reservatórios/ENA (Bebas Neue herdado, sem
   italic, sem prefix).
3. Tag granularidade v1 (0.78rem `#6B6B6B`) → discreta demais, ajustada
   pra 0.85rem `#4A4A4A`.
4. Override stAlert v1 (só externo) → borda azul interna persistia,
   ampliado pra cobrir wrappers internos (`[data-baseweb="notification"]`,
   `[data-testid="stAlertContainer"]`).
5. Override stAlert v2 (cream BAUHAUS_CREAM) → fundo igual ao da
   página, trocado pra BAUHAUS_LIGHT pra diferenciação.

**Bug grave descoberto e fixado pós-implementação — retorno de aba:**

Sintoma reproduzido pelo user em Mensal E em Diária:
1. Aplica período válido (Mensal 3M ou Diária 7D).
2. Sai pra outra aba (PLD).
3. Volta pra Geração.
4. Date_inputs mostram `data_ini == data_fim == max_d` (0 dias) →
   guard ativa (warning Mensal <60d ou info Diária <2 pontos).

**Diagnóstico em runtime:** debug `st.write` em 3 pontos do flow
(antes do backup paralelo, após reset block, após helper de período)
revelou que ao retornar:
- `gen_granularidade` e `gen_submercado` foram cleanup'ed (restaurados
  pelo backup paralelo da 5.18 — funcionou).
- `_gen_dataset_max`, `_gen_dataset_min`, `_gen_last_gran` sobreviveram
  (não-widget-state).
- `gen_data_fim` sobreviveu, mas `gen_data_ini` foi cleanup'ed.
- Quando o `st.date_input("Data inicial", key="gen_data_ini",
  min_value=..., max_value=max_d)` foi re-instanciado SEM `value=`,
  Streamlit recriou a key com value clamped pra `max_value` (= `max_d`).
- Resultado: `gen_data_ini == gen_data_fim == max_d`. Ambas keys
  PRESENTES, mas range degenerado.
- A sentinela 5.16 (que checa só ausência das keys) **não pegou** —
  ambas estavam em state.

**Fix:** 6º gatilho no reset block (`app.py:2261-2266`):

```python
or (
    not em_horaria
    and "gen_data_ini" in st.session_state
    and "gen_data_fim" in st.session_state
    and st.session_state["gen_data_ini"]
        >= st.session_state["gen_data_fim"]
)
```

Mesmo padrão `not em_horaria` da 5.19 — em Horária 1D, `data_ini ==
data_fim` é estado legítimo (window=1 + `data_base + 0 dias`), não bug.

**Validação de não-regressão (3 cenários ✅):**

| # | Cenário | Resultado |
|---|---|---|
| 1 | Mensal: aplica 3M → PLD → volta | ✅ vai pro default Mensal 12M (reset disparou via gatilho 6) |
| 2 | Diária: aplica 7D → PLD → volta | ✅ vai pro default Diária 1M (reset disparou via gatilho 6) |
| 3 | Horária: aplica 7D → PLD → volta | ✅ window 7D preservada (gatilho 6 EXCLUI Horária) |

**Decisões arquiteturais consolidadas no CLAUDE.md (4 novas + 2 estendidas):**

- **5.21** KPIs em HTML custom quando o value tem letras mixed-case.
  Bebas Neue all-caps por design — incompatível com `MWmed`.
- **5.22** Tag compacta de granularidade entre título e gráfico.
  Padrão reusável pra qualquer aba com modo/granularidade variável.
- **5.23** Override Bauhaus de st.alert em estratégia "container externo
  dita visual + descendentes transparentes". Resolve incompatibilidade
  do tema dark com fundos coloridos do alert padrão Streamlit.
- **5.24** st.stop após guards que invalidam o gráfico. KPIs/export
  bloqueiam junto. Coerência entre guards Mensal <60d e Diária <2 pontos.
- **5.16 (estendida)** "Sentinela de reset estendida com keys individuais"
  ganha 6º gatilho na nova seção "Extensão posterior (Sessão 1.6)" —
  detecta `gen_data_ini >= gen_data_fim` (range degenerado), cobre o
  caso "keys presentes com valor degenerado" que a checagem de
  ausência pura não pegava.
- **5.19 (estendida)** ganha nota "Aplicação ao 6º gatilho (Sessão 1.6)" —
  o `not em_horaria` da exclusão por modo se aplica ao gatilho 6 pelo
  mesmo motivo da 5.16: em Horária 1D, `data_ini == data_fim` é estado
  válido derivado de `data_base + 0`, não bug.
- **5.14 reconfirmada como SUPERADA** — agora pelas 5.20 (transições)
  + 5.24 (seleção manual curta com warning educativo).

### Sessão 2 — Dia Típico · ✅ CONCLUÍDA (2026-04-25)

**Escopo:** nova granularidade "Dia Típico" na aba Geração — stacked
area com 24 ticks `00:00...23:00` mostrando média de cada fonte em
cada hora-do-dia ao longo do período selecionado. Curva de pato
canônica do setor elétrico (rampa térmica no fim de tarde, pico solar
ao meio-dia, perfil eólico noturno em alguns subsistemas).

**Notas de mudança de escopo durante o planejamento:**

- A versão original do roadmap considerava "5 gráficos empilhados (SIN +
  SE/S/NE/N)" pra Dia Típico — leve por ser só 24 pontos. **Descartado**
  durante o planejamento: mantém o pattern de gráfico único + dropdown
  de submercado (decisão 5.10) por consistência com o resto da aba.
  User explora um submercado de cada vez, igual nas outras granularidades.

**Decisões da spec (10 itens, todos confirmados pelo user no plano):**

| # | Item | Decisão |
|---|---|---|
| 1 | UI selectbox | 4ª opção "Dia Típico" (ordem: Mensal/Diária/Horária/Dia Típico) |
| 2 | Cálculo | `groupby(index.hour).mean()` sobre o pivot horário do período |
| 3 | Presets | `7D / 30D / 90D / 6M / 12M / 5A` (sem Máx — descontinuidade pré-2010) |
| 4 | Eixo X | Categorial 24 strings `"00:00".."23:00"` |
| 5 | Visual | Stacked area Bauhaus + linha carga tracejada (igual outras gran.) |
| 6 | Submercado | Mesmo dropdown SIN/SE/S/NE/N |
| 7 | Tag | "Dia típico (média horária do período selecionado) · MWmed" (estendida) |
| 8 | KPIs | Mantém os 4 cards (médias do período, conceito útil) |
| 9 | Lado direito do título | `DD/MM/YYYY – DD/MM/YYYY` (período sobre o qual a média foi calculada) |
| 10 | Hover | Mostra hora + fontes + carga, formato consistente com Plotly hover atual |

**Implementação em 7 passos (ordem):**

1. **Selectbox + presets + default 30D na 5.20** —
   `["Mensal", "Diária", "Horária", "Dia Típico"]` no selectbox; branch
   novo `"Dia Típico"` em `_aplica_default_periodo_gen` (max_d - 30d
   até max_d + pop horária keys); branch novo nos presets do
   `_render_period_controls` com 6 entradas sem Máx; comentário do
   reset block (5.20) atualizado com Dia Típico → 30D.

2. **Helper `_build_dia_tipico_submercado`** — 5 linhas, reusa
   `_build_pivot_submercado` (que retorna pivot horário quando
   `freq_map["Dia Típico"]=None`) + `groupby(index.hour).mean()` +
   `index = ["00:00",...,"23:00"]` + `index.name = "Hora"` (vira
   coluna no `reset_index` do export).

3. **Despacho elegante no loop dos 5 subsistemas** — variável local
   `_build_pivot = _build_dia_tipico_submercado if granularidade==X
   else _build_pivot_submercado`. 1 linha vs `if/else` espalhado.

4. **Guard `<7 dias`** com `st.warning + st.stop` (mesmo padrão da
   5.24): texto `"Dia típico precisa de pelo menos 7 dias pra ser
   representativo. Selecione um período maior ou troque pra Diária pra
   ver dia específico."`.

5. **Eixo X custom no Plotly** — `_xaxis_gen_dict` montado
   condicionalmente: `type="category"` em Dia Típico (preserva ordem
   00→23, hovermode unified mostra a string direto sem precisar de
   `hoverformat`); `hoverformat=hover_fmt_gen` nas outras
   granularidades. Vline 29/04/2023 pulada em Dia Típico (eixo é
   categorial, Timestamp não bate). `hover_fmt_gen` ganha entrada
   `"Dia Típico": None` (não-usado mas evita KeyError).

6. **Tag "Dia típico (média horária do período selecionado) · MWmed"**
   no dict `tag_granularidade_gen`. Outras 3 tags (Mensal/Diária/
   Horária) preservadas — só Dia Típico estende a explicação porque o
   conceito não é universal.

7. **Validação de sintaxe** + ajustes do export CSV descobertos
   durante o passo 6: branch novo Dia Típico no export — coluna
   `"Hora"` string (`"00:00".."23:00"`) em vez de `"Data"` datetime,
   sem `pd.to_datetime` (já é string), `gran_slug = "dia_tipico"` no
   filename.

**Tag final adotada:** `"Dia típico (média horária do período
selecionado) · MWmed"` — única das 4 tags que estende explicação,
porque "dia típico" exige glossário inline (Mensal/Diária/Horária são
autoexplicativos).

**Resultado dos testes (validados pelo user):**

| # | Cenário | Resultado |
|---|---|---|
| 1 | Sanity: Diária/Mensal/Horária continuam funcionando | ✅ não-regressão |
| 2 | Trocar pra Dia Típico → reset aplica 30D | ✅ |
| 3 | Tag mostra texto explicativo estendido | ✅ |
| 4 | Gráfico com 24 ticks "00:00..23:00" no eixo X | ✅ |
| 5 | Hover unified mostra hora + 4 fontes + carga | ✅ |
| 6 | KPIs: médias do período (mesmo conceito das outras gran.) | ✅ |
| 7 | Lado direito do título: período BR `DD/MM/YYYY – DD/MM/YYYY` | ✅ |
| 8 | 6 presets sem Máx | ✅ |
| 9 | Guard <7 dias dispara com warning Bauhaus + bloqueio | ✅ |
| 10 | Transições aplicam defaults corretos (Diária 1M, Mensal 12M, Horária 1D, Dia Típico 30D) | ✅ |
| 11 | Submercados mostram perfis distintivos (SIN curva de pato, NE eólica/solar dominantes, N hidro plana) | ✅ |
| 12 | Bug retorno de aba (5.16 estendida): volta pro 30D default | ✅ |
| 13 | Export CSV em Dia Típico: coluna `Hora` string, 120 linhas (24 × 5 subs), filename `geracao_dia_tipico_*.csv` | ✅ |
| 14 | Vline 29/04/2023 NÃO aparece em Dia Típico (correto, eixo categorial) | ✅ |

**Decisão arquitetural consolidada no CLAUDE.md (1 nova + 1 estendida):**

- **5.25** "Dia Típico" como granularidade não-temporal via reagregação
  por hora-do-dia. Pattern de 6 pontos (freq_map, helper paralelo,
  despacho elegante, eixo categorial, default no reset, guard mínimo).
  Reusa filter+pivot+disk-cache da 1.5/1.5b sem refator. Apenas 3
  pontos divergem do flow tradicional: eixo X, vline 29/04/2023, formato
  do export CSV. Pattern aplicável a futuros candidatos: "Mês típico"
  em Reservatórios/ENA, "Hora útil vs FDS" em PLD.
- **5.20 estendida** com default Dia Típico → 30D (sweet spot UX:
  captura padrão weekday/weekend, dilui anomalias diárias).

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
  5.15 disk-cache, 5.16 widget-state cleanup + 6º gatilho range
  degenerado (Sessão 1.6), 5.17 dois eixos range vs período visível,
  5.18 backup paralelo selectbox, 5.19 exceção por modo no reset +
  aplicação ao 6º gatilho (Sessão 1.6), 5.20 defaults por
  granularidade + reset block unificado + Dia Típico 30D (Sessão 2),
  5.21 KPIs HTML custom (Bauhaus all-caps), 5.22 tag compacta
  granularidade, 5.23 override Bauhaus de st.alert, 5.24 st.stop
  pós-guard, **5.25 "Dia Típico" como granularidade não-temporal via
  reagregação por hora-do-dia (Sessão 2)**; 5.14 marcada como SUPERADA
  pela 5.20 + 5.24).
- Commits relevantes (5 em `origin/main` após push em 2026-04-25 +
  1 pendente da Sessão 2):
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
  - `1d58509` (2026-04-25) — Sessão 1.6: 7 ajustes estéticos + 3
    bonus + bug retorno de aba + decisões 5.21-5.24 + 5.16/5.19
    estendidas.
  - **(pendente)** Sessão 2: nova granularidade Dia Típico (perfil
    24h por hora-do-dia) + decisão 5.25 + 5.20 estendida com default
    30D.
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
