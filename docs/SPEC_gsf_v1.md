# SPEC — Sub-aba GSF (Generation Scaling Factor) — V1 + V2

**Status:** Draft inicial (sprint planejado em chat, mai/2026)
**Localização da sub-aba:** Geração → após "Solar" e antes do que vier depois
**Versão alvo:** V1 (realizado mensal SIN, 2023+) + V2 (extensão histórica pré-2023)
**Excluído explicitamente (V3 futuro):** projeção forward via InfoPLD PDF

---

## 1. Objetivo

Adicionar uma sub-aba **GSF** dentro da aba Geração, posicionada logo após as sub-abas Eólica e Solar, exibindo a série histórica do Fator de Ajuste do MRE (Generation Scaling Factor) realizado, com destaque visual para períodos de Energia Secundária (GSF > 100%).

## 2. Conceito (recap canônico)

**Fator de Ajuste do MRE (GSF)** = relação entre a geração total das UHEs participantes do MRE e a soma das garantias físicas dessas usinas no mês de referência.

Fórmula oficial (Regras de Comercialização CCEE, módulo MRE):

```
GSF_mes = ENTREGA_MRE_mes / GARANTIA_FISICA_REDE_BASICA_mes
```

Interpretação:
- **GSF < 100%** → déficit hidrológico, exposição no MCP, fator aplicado para reduzir GF alocada das usinas
- **GSF = 100%** → equilíbrio
- **GSF > 100%** → Energia Secundária (excedente rateado entre usinas participantes na proporção das GFs)

**O GSF é único para o SIN.** O MRE é um pool nacional — não há GSF por submercado no sentido contábil. Decomposições regionais que aparecem em alguns relatórios são analíticas, não contábeis.

## 3. Fonte de dados

### V1 — Realizado mensal (2023+)

**Dataset canônico:** `MRE_MENSAL` (organização Infomercado, portal Dados Abertos CCEE)
- URL base: `https://dadosabertos.ccee.org.br/dataset/mre_mensal`
- Granularidade: mensal, SIN agregado
- Histórico: jan/2023 até presente
- Frequência de atualização: 1×/mês, MS+22du (~22 dias úteis após fim do mês)
- Formato: CSV (1 arquivo por ano)

**Campos relevantes:**
- `MES_REFERENCIA` — chave temporal (formato numérico AAAAMM ou similar — Claude Code valida no primeiro carregamento)
- `ENTREGA_MRE` — energia hidráulica entregue ao MRE no mês (MWmed ou MWh — validar)
- `GARANTIA_FISICA_REDE_BASICA` — GF apurada para fins de MRE (mesmo denominador, mesma unidade)

**⚠️ Cuidado crítico — não usar:**
- `FATOR_REDUCAO_ACUMULADO` — NÃO é o GSF. É o produto dos fatores de perda (interna × rede básica × disponibilidade) que reduz a GF outorgada até a GF apurada. Confundi-los gera valores fora do range esperado.

### V2 — Histórico pré-2023

**Fonte:** arquivo local fornecido pelo usuário (a definir formato).

Provável origem: planilhas legadas do InfoMercado Dados Gerais descontinuado (até mai/2024), aba "002 MRE", tabela de fator de ajuste anual/mensal. Pode também ser série tabulada manualmente a partir de boletins históricos.

**Armazenamento:** `data/raw/gsf_historico_pre2023.csv` (ou `.parquet` se grande).
**Schema mínimo esperado:** `mes_ref` (YYYY-MM), `gsf` (decimal, ex: 0.823 para 82,3%).
**Concatenação:** carregado em separado e concatenado ao realizado do `MRE_MENSAL`, com flag `fonte_dado` ∈ {`mre_mensal`, `historico_legado`} para auditabilidade.

## 4. Arquitetura

### 4.1 Data loader

**Arquivo:** `data_loaders/ccee_mre.py` (novo).

**Função principal:** `load_gsf_mensal() -> pd.DataFrame`

**Retorno padronizado:**
```
colunas: mes_ref (datetime64, primeiro dia do mês), entrega_mre, gf_rede_basica, gsf (decimal), fonte_dado
índice: mes_ref ascendente, sem duplicatas
```

**Estratégia de ingestão (padrão estabelecido CLAUDE.md §5.x — 3-strategy cascade):**
1. CKAN `datastore_search` paginado
2. Dump endpoint
3. Fixed `pda-download` URL (fallback)

Usar `curl_cffi` impersonando Chrome (padrão consolidado para CCEE).

**Cache (padrão 2-layer CLAUDE.md):**
- `@st.cache_data(ttl=...)` na função pública
- Disk cache parquet por ano em `data/cache/mre_mensal_YYYY.parquet`
- **TTL diferenciado:**
  - Anos fechados (< ano atual − 1): 30 dias
  - Ano atual e anterior: 24h (recontabilização possível)
- `_CACHE_VERSION` próprio (`_CACHE_VERSION_MRE = 1`), incrementar a cada mudança de schema

### 4.2 Validação de integridade

**Script:** `scripts/validar_gsf_calculado_vs_mre.py`

Verifica:
1. GSF calculado (ENTREGA/GF) bate com valores publicamente divulgados pela CCEE em comunicados/InfoPLD para 3+ meses recentes — tolerância ±0,5pp
2. Não há valores fora do range plausível (0,5 a 1,3 — flagrar fora disso)
3. Continuidade temporal (sem meses faltando entre 2023-01 e mês mais recente do dataset)
4. Soma de fontes de dados V2+V1 não tem duplicatas no `mes_ref`

Script independente, executado manualmente quando há suspeita ou após upgrade do loader. Não roda no startup do app.

### 4.3 UI — Sub-aba GSF

**Localização no código:** integrar no módulo da aba Geração, adicionar render após Eólica e Solar.

**Layout principal (V1):**

**Bloco 1 — KPIs topo (3 cards Bauhaus):**
- GSF mês mais recente (% formatado com 1 casa)
- GSF acumulado 12 meses (média ponderada por ENTREGA/GF? — definir; provavelmente sum/sum)
- Energia Secundária acumulada últimos 12 meses (MWmed, soma de max(GSF−1,0) × GF_total quando aplicável)

**Bloco 2 — Gráfico principal: Linha temporal**
- Eixo X: tempo mensal contínuo (V2 estendendo para trás se disponível)
- Eixo Y: GSF em %
- Linha horizontal de referência em 100% (preta, dashed, label "Paridade GF")
- Linha do GSF: cor Bauhaus cobalt `#1D3557`, espessura 2px
- Preenchimento area abaixo de 100% em vermelho `#D62828` com baixa opacidade (~15%) — visual de "déficit"
- Preenchimento area acima de 100% em amarelo `#F6BD16` com baixa opacidade (~15%) — visual de "secundária"
- Hover em JetBrains Mono mostrando: mês, GSF%, fonte_dado (MRE_MENSAL ou histórico)
- Markers grandes nos pontos onde GSF > 100% (Energia Secundária — destaque pedido pelo usuário)
- Sem barras (decisão usuário: linha temporal pura)

**Bloco 3 — Tabela complementar (HTML, padrão estabelecido CLAUDE.md):**
- Últimos 12 meses
- Colunas: Mês, GSF (%), Entrega MRE (MWmed), GF Rede Básica (MWmed), Energia Secundária? (Sim/Não)
- Linha destacada (fundo amarelo claro) quando Energia Secundária

**Period controls:** seguir padrão do projeto — `date_input` como source of truth, shortcut buttons (12M, 24M, 5A, Máx) atualizam state + rerun. Padrão default: 24M.

### 4.4 Posicionamento e CSS

- Adicionar sub-aba após Eólica e Solar dentro do conjunto de botões custom `.st-key-btn_geracao_subaba_*` (padrão estabelecido da Curtailment, ver CLAUDE.md §5.60)
- Active button style: amarelo `#F6BD16` + borda preta 2px
- Sem `:has()` (regra dura do projeto)
- Sem `display:none` em clickable

## 5. Decisões arquiteturais e trade-offs

| Decisão | Alternativa rejeitada | Razão |
|---|---|---|
| Usar `MRE_MENSAL` (não `MRE_HORARIO`) | `MRE_HORARIO` para granularidade fina | GSF é conceitualmente mensal; dataset menor; suficiente para análise visual |
| Calcular GSF = ENTREGA/GF (não ler `FATOR_REDUCAO_ACUMULADO`) | Ler campo direto | `FATOR_REDUCAO_ACUMULADO` é outra coisa (perdas), não GSF |
| Único GSF (SIN), não por submercado | Decompor por submercado | GSF contábil é único nacional; decomposição é só analítica |
| TTL diferenciado fechado/aberto | TTL único 30d | Recontabilização CCEE pode revisar meses recentes |
| V3 (forward) adiado | Implementar PDF parsing agora | Layout InfoPLD mudou dez/2025; alto risco/baixo ganho relativo |
| Linha temporal pura (sem barras) | Barras + linha | Decisão UX usuário |
| Energia Secundária como destaque visual | Apenas linha contínua | Decisão UX usuário — usinas credoras vs devedoras é central |

## 6. Riscos conhecidos

1. **Schema do CSV** — nomes/tipos/locale precisam confirmação no primeiro carregamento (Claude Code valida)
2. **Recontabilização** — meses fechados podem ser revisados por ações regulatórias/judiciais; mitigado pelo TTL curto em anos recentes
3. **Defasagem MS+22du** — mês corrente não existe no dataset até ~22du do mês seguinte; UI deve mostrar último disponível, sem inventar projeção
4. **Histórico pré-2023 V2** — depende de arquivo do usuário; pode ter schema diferente, harmonização necessária
5. **Estado pós-recontabilização extraordinária** — ações judiciais Apine/GSF podem gerar revisões retroativas; documentar mas sem tratamento especial em V1

## 7. Critérios de aceitação

### V1
- [ ] Loader baixa MRE_MENSAL 2023, 2024, 2025, 2026 com cascade
- [ ] Cache 2-layer funcional (RAM 30d + disk parquet)
- [ ] DataFrame retornado com schema padronizado
- [ ] Sub-aba GSF aparece após Solar com botão custom Bauhaus
- [ ] Gráfico linha temporal renderiza com paridade 100%, preenchimentos vermelho/amarelo, markers em Energia Secundária
- [ ] Tabela últimos 12 meses funcional, linhas destacadas em Energia Secundária
- [ ] KPIs topo carregam valores corretos
- [ ] Period controls (12M/24M/5A/Máx) funcionam
- [ ] Hover Plotly em JetBrains Mono
- [ ] Script de validação confirma GSF ≈ comunicados CCEE para 3 meses recentes (±0,5pp)
- [ ] App roda em Streamlit Cloud sem OOM (improvável, dataset é tiny)

### V2
- [ ] `data/raw/gsf_historico_pre2023.csv` carregado com flag `fonte_dado=historico_legado`
- [ ] Concatenação correta no `mes_ref`, sem duplicatas
- [ ] Série temporal estendida sem descontinuidades visuais

## 8. Documentação pós-implementação

Adicionar ao `CLAUDE.md` (próxima §5.x livre):
- Fonte canônica `MRE_MENSAL` + cuidado com `FATOR_REDUCAO_ACUMULADO`
- Padrão de cache TTL diferenciado para meses recém-fechados
- Esquema do schema padronizado `load_gsf_mensal()`
- Decisão GSF único SIN (não por submercado)
- Decisão V3 adiada e por quê
