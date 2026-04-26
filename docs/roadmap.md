# Roadmap futuro do projeto

> Registro das próximas sessões discutidas e priorizadas, **fora do
> roadmap original da aba Geração** (que se encerrou em 2026-04-26 com
> a Sessão 3 — ver `docs/sessao_geracao_status.md`).
>
> Atualizado: **2026-04-26** (após encerramento do roadmap da Geração).
>
> Convenção: cada item lista escopo, fontes de dado conhecidas/a
> investigar, e se precisa Fase A de discovery antes de codar.

---

## Sessão 4 — Aba Carga (escopo enxuto)

**Status:** próxima na fila. **Não precisa Fase A** — reaproveita o
`balanco_energia_subsistema` que já carregamos pra aba Geração (coluna
`val_carga` por subsistema horária 2000-2026).

**4 visualizações planejadas:**

1. **Carga total vs líquida** — série temporal mostrando a quebra de
   29/04/2023 (pré: carga "líquida de GD"; pós: inclui MMGD).
2. **Decomposição** — separar componentes da carga até onde o dataset
   permitir (térmica/hidro/eólica/solar/intercâmbio bate carga ±
   intercâmbio internacional).
3. **Comparação histórica** — sobrepor anos pra ver trend (ex: 2024 vs
   2023 vs média 2015-2023). Útil pra mostrar crescimento e impacto
   COVID 2020.
4. **Curva de carga tipo (load duration curve)** — eixo X = % do tempo,
   eixo Y = MWmed ordenado decrescente. Padrão clássico do setor pra
   ver pico e base.

**Reuso esperado:**
- `load_balanco_subsistema` (default 15a + flag completo) já cobre o dado.
- `_render_period_controls` + `_format_periodo_br` + reset block 5.20
  + disk-cache 5.15 + tag de granularidade 5.22 — pattern já validado.
- Decisões 5.16/5.18/5.19 (sentinela + backup paralelo) — aplicar
  preventivamente em widgets da nova aba.

**Esforço estimado:** **1 sessão** (sem Fase A, todo o pipeline já
existe). Maior parte é UI nova + 4 plots Plotly distintos.

---

## Sessão futura (alta prioridade) — Curtailment

**Status:** alta prioridade — tema central da agenda regulatória ANEEL
(10-15% de curtailment no NE em 2024, bilhões de R$ em energia perdida).

**Datasets ONS conhecidos:**
- `restricao_coff_eolica` — constrained-off de usinas eólicas.
- `restricao_coff_fotovoltaica` — constrained-off de UFV (já visto na
  Fase A da Sessão 3, cobertura desde 2024).
- `restricao_coff_fotovoltaica_detail` — detalhamento por usina.
- Possivelmente `geracao_usina_2` — geração realizada por usina,
  necessária pra calcular taxa % (realizado / disponível).

**Visualizações planejadas:**
1. **Realizado vs disponível** — série temporal mostrando o "gap"
   curtailed.
2. **Taxa % de curtailment** — `disponível - realizado) / disponível`
   por subsistema, possivelmente normalizada por fonte.
3. **Dia típico de curtailment** (pattern decisão 5.25) — quando no dia
   o curtailment concentra (provável: meio-dia pra solar, madrugada pra
   eólica em alguns subsistemas).
4. **Ranking por usina/empresa** — top N usinas com mais curtailment
   absoluto/percentual no período.

**Justificativa estratégica:** tema atual da agenda regulatória, pouco
visualizado em dashboards públicos brasileiros. Diferencial vs outros
dashboards do setor (ONS Atlas, COP-BR, EPE).

**Fase A necessária:** cobertura temporal exata, schema das colunas
(MWh? MWmed? por hora?), granularidade temporal e espacial, validação
de mapping usina→subsistema. Custo de download (resources `_detail` por
mês = potencialmente muitos arquivos).

**Esforço estimado:** **2-3 sessões** — Fase A separada + implementação
+ ajustes UX. Mais pesado que Carga porque é fonte nova com schema
desconhecido.

---

## Sessão futura (prioridade média) — PLD horário com seleção de dia

**Status:** prioridade média — depois de Sessão 4a/4b da Carga, antes ou
junto com Curtailment.

Hoje a aba PLD tem 4 granularidades (Horário/Diário/Semanal/Mensal) num
dropdown, mas a granularidade Horária mostra todo o range de período
selecionado — em janela longa fica ilegível (8.760 pontos × 12 meses).

**Mudança proposta:** modo "1D" análogo ao da Geração (decisão 5.9).
1 `date_input` "Data base" + presets de janela curta (1D/7D), mostrando
as 24h × N dias do dia selecionado.

**Útil pra:**
- Análise de spike intradiário (PLD nas horas de pico).
- Comparação entre dias específicos (ex: feriado vs dia útil).
- Análise regulatória de momentos críticos.

**Reuso esperado:**
- `_render_period_controls_horaria` (5.9) já existe.
- Loader `load_pld_horaria()` já existe — só precisa do switch de UI.

**Esforço estimado:** ~1-1.5h. Maior parte é UI (switch granularidade
Horária → modo "Data base + janela", sem mexer em loader). Bug previsto:
session_state da granularidade do PLD precisa do mesmo padrão de reset
block unificado (5.20) que a Geração ganhou.

---

## Sessões futuras (menor prioridade)

Cada uma exige Fase A própria. Listadas em ordem de afinidade temática
com o escopo atual do dashboard.

### Carga por classe (residencial / industrial / comercial)

**Fonte provável:** ANEEL ou EPE (Empresa de Pesquisa Energética). ONS
não desagrega carga por classe de consumidor — é dado de
distribuidoras/comercializadoras agregado pelo regulador.

**Fase A:** investigar portal de dados abertos ANEEL e BDPS (Base de
Dados de Pesquisas Setoriais) da EPE. Granularidade provável: mensal,
por estado ou subsistema. Cobertura provavelmente curta (5-10 anos).

**Diferencial:** decomposição da demanda — útil pra entender onde
crescimento vem (ar condicionado residencial? indústria de exportação?
comércio pós-COVID?).

### Componentes da carga (5 parcelas do ONS, traz GD junto)

**Fonte:** `carga-energia-verificada` (mesmo dataset citado na decisão
5.26 da Sessão 3 como "única fonte ONS com MMGD isolada"). Tem 5
parcelas explícitas:
1. Parcela supervisionada pelo ONS
2. Geração tipo I, IIA, IIB, IIC + intercâmbios
3. Geração tipo III (sistema de medição CCEE)
4. **MMGD** ← esta seria a "GD via ONS" deferida na Sessão 3
5. Parcela atendida por redução de demanda

**Fase A:** API/Swagger ONS, mapping área de carga → subsistema,
cobertura temporal real. Esforço médio-alto (API nova, paginação).

**Conexão com decisão 5.26:** se esta sessão acontecer, a "GD via
ONS" seria viabilizada como subproduto — não como 5ª faixa do stacked
da Geração, mas como uma das 5 parcelas exibidas em aba dedicada de
componentes da carga. Mantém a decisão 5.26 (GD descartada da aba
Geração) intacta.

### Carga vs PIB

**Fonte:** IBGE (PIB trimestral) + BCB (séries macro) cruzados com
carga ONS.

**Fase A:** API IBGE Sidra + APIs BCB SGS, alinhamento temporal
(carga horária/diária × PIB trimestral exige re-agregação),
normalização (MWmed × R$ bilhões).

**Diferencial:** intensidade energética da economia brasileira,
elasticidade carga-PIB. Útil pra leitura macro do setor.

---

## Convenções aplicáveis a todas as sessões futuras

- **Padrão Fase A obrigatório** quando a fonte de dado é nova (lição
  da Sessão 3 — ver decisão 5.26 do `CLAUDE.md`). Não escrever spec
  baseada em hipótese sobre dataset externo sem validar via discovery.
- Documentar Fase A em `docs/<tema>_research.md` (segue padrão
  Reservatórios/ENA/Geração).
- Reusar infraestrutura validada: disk-cache (5.15), reset block
  unificado (5.20), backup paralelo (5.18), tag compacta (5.22),
  guards com st.stop (5.24).
- Commits de discovery (script `inspect_*.py` + decisão arquitetural)
  podem ser `docs:` ou `chore:` mesmo sem código de feature — vide
  Sessão 3 (commit `78c59c3`).
