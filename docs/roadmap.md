# Roadmap futuro do projeto

> Registro das próximas sessões discutidas e priorizadas, **fora do
> roadmap original da aba Geração** (que se encerrou em 2026-04-26 com
> a Sessão 3 — ver `docs/sessao_geracao_status.md`).
>
> Atualizado: **2026-04-28** (após Sessão PLD 1D + Sessão 4a parcial — Vizs 1+2 da Carga).
>
> Convenção: cada item lista escopo, fontes de dado conhecidas/a
> investigar, e se precisa Fase A de discovery antes de codar.

---

## Sessão 4a — Aba Carga (em andamento)

**Status:** em andamento. Iniciada em 2026-04-27. Aba Carga reaproveita
o `balanco_energia_subsistema` que já carregamos pra aba Geração
(coluna `val_carga` por subsistema horária 2000-2026) — **sem Fase A**.

**Concluído na Sessão 4a até agora:**

- Setup da aba (radio na sidebar, dataset, granularidades).
- KPIs (régua de 4 cards autocontidos — decisão 5.29).
- Glossário inline.
- **Viz 1** — Carga total vs líquida (vline 29/04/2023 marcando
  quebra MMGD).
- **Viz 2** — Composição da carga total (stacked area com ordem da
  carga líquida — decisão 5.31; intercâmbio stack-aware híbrido por
  recorte — decisão 5.32; paleta canônica — decisão 5.33).

**Pendências do Bloco 5 (Viz 2):**

- **Sub-bloco 5.5** — adaptação da Viz 2 pra granularidade Dia Típico
  (xaxis categorial + stackgroup, mesmo pattern da decisão 5.25 já
  aplicado na Viz 1).
- **Sub-bloco 5.6** — validação visual nos 4 cenários (SIN×Mensal,
  SIN×Diária, Submercado×Diária, Dia Típico) + remoção do sanity
  check inline usado durante desenvolvimento.
- **Sub-bloco 5.7** — limpeza final + atualizar Seção 7 do
  `CLAUDE.md` + commit fechando Sessão 4a.

**Sessão 4b (futura):** Vizs 3 e 4 do escopo original — Comparação
histórica (sobreposição de anos) e Curva de carga tipo (load duration
curve). Ficam pra sessão dedicada após fechamento da 4a.

**Reuso já validado na 4a:**
- `load_balanco_subsistema` (default 15a + flag completo).
- `_render_period_controls` + `_format_periodo_br` + reset block 5.20
  + disk-cache 5.15 + tag de granularidade 5.22.
- Decisões 5.16/5.18/5.19 (sentinela + backup paralelo) aplicadas
  preventivamente.

---

## Sessão futura (alta prioridade) — UX: Preservar estado de período entre trocas de aba

**Status:** alta prioridade — fricção UX recorrente reportada pelo user
no fluxo "abro Carga, customizo período, dou uma olhada em PLD, volto
pra Carga e tenho que refazer tudo".

**Comportamento atual (problema):** ao trocar de aba e voltar, as datas
podem zerar ou voltar pro default. Causa raiz é a decisão **5.16
estendida (Sessão 1.6)** + **6º gatilho do reset block** que detecta
`data_ini >= data_fim` (range degenerado) — necessário pra cobrir
widget-state cleanup do Streamlit, mas hoje sacrifica preservação
legítima da customização do user.

**Comportamento desejado:**
1. **1ª visita** → defaults da granularidade (mantém)
2. **Trocar granularidade** → aplicar default da nova granularidade
   (mantém — comportamento intencional, troca de modo é mudança de
   contexto)
3. **Trocar de aba e voltar** → preservar tudo: período exato, preset
   ativo, granularidade, submercado, qualquer customização

**Implementação proposta:**
- Estender **backup paralelo (decisão 5.18)** pras keys de período
  (`*_data_ini`, `*_data_fim`, `*_data_base`, `*_horaria_window_dias`)
  em todas as 5 abas (PLD, Reservatórios, ENA, Geração, Carga).
- Distinguir **2 gatilhos do reset block**:
  - **Reset hard** (defaults aplicados): 1ª visita absoluta, dataset
    mudou, transição de granularidade, force_reset (clear_cache).
  - **Restore soft** (backup paralelo restaurado): widget-state
    cleanup detectado mas user não trocou de granularidade — restaura
    do backup em vez de aplicar default.
- A diferença entre "cleanup parcial sem mudança de modo" e
  "transição genuína" é a sentinela `_<aba>_last_gran` (já usada na
  Geração e Carga) — se igual, é cleanup → restore; se diferente, é
  transição → reset.

**Riscos a considerar:**
- O 6º gatilho (`data_ini >= data_fim`) não pode ser puramente
  removido — protege contra recriação degenerada do `st.date_input`
  sem `value=`. Solução: substituir o reset por restore-do-backup
  quando esse gatilho dispara fora de transição de granularidade.
- Backup precisa rodar TODO render (não só pré-widget) — se cleanup
  ocorrer entre rerun A (backup feito) e rerun B (cleanup), o restore
  no início de B usa o backup mais recente.
- Coerência com decisão 5.17 (dois eixos): backup preserva período
  visível, mas range do dataset (`gen_historico_completo`) continua
  sendo flag explícita do user.

**Decisão arquitetural nova (próximo número disponível, atualmente 5.34)**
consolidaria o pattern.

**Esforço estimado:** **2-3h** — UI inalterada, todo o trabalho fica
no reset block + backup paralelo de cada aba. Maior risco é
regressão em algum dos 12 cenários validados na Sessão 1.5b — exigir
re-validação completa.

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

## Sessão futura (prioridade média) — Aba GD Brasil via ANEEL

**Status:** prioridade média. **Plano C separado da decisão 5.26** —
que descartou camada de GD na Viz 1 da Carga porque ONS não publica
MMGD standalone por subsistema (vline 29/04/2023 cumpre o papel
informativo lá). Esta é uma abordagem diferente: **aba dedicada** com
dataset ANEEL próprio, não camada empilhada na Carga.

**Fontes a investigar (Fase A obrigatória):**
- Portal de dados abertos ANEEL (CIEFSE? SCG? outro?).
- Cadastro de unidades consumidoras com micro/minigeração distribuída.
- Granularidade provável: mensal, por estado/distribuidora.
- Cobertura provável: 2014+ (regulamentação MMGD veio em 2012, dado
  acumulado começa ~2014).

**Visualizações esperadas (a definir após Fase A):**
- Capacidade instalada acumulada por estado/subsistema ao longo do
  tempo.
- Crescimento mensal/anual (incremento de novas instalações).
- Composição por fonte (solar fotovoltaica >> outras no Brasil).

**Esforço estimado:** 2-3 sessões — Fase A pesada (fonte nova, schema
desconhecido, mapping estado→subsistema) + implementação + ajustes UX.

---

## Sessão futura (prioridade média) — Feature "comparar com" / aba histórico

**Status:** prioridade média. **Origem: consequência da decisão 5.29**
(KPI cards autocontidos, comparações temporais ficam pra feature
dedicada).

**Motivação:** durante design dos KPIs do PLD horário 1D, o card "vs
média do mês" foi descartado porque (a) denominador móvel cria ruído
conceitual, (b) delta % isolado num card não substitui ver a curva, (c)
gráfico abaixo já permite "olhar pro lado" e comparar dias. Mas a
necessidade de comparação temporal continua válida — só não como card
enxertado em outro contexto.

**Escopo provável:**
- Comparações típicas: vs ontem, vs ano anterior, vs média móvel 30d,
  vs média histórica do mês/ano.
- UX provável: toggle ou aba dedicada dentro de cada aba (ex: PLD
  Histórico, Carga Histórico).
- Aplicável a: PLD, Carga, possivelmente Geração (PLD é candidato
  natural por ter granularidade horária + 4 submercados).

**Esforço estimado:** 2 sessões — design UX (definir formato:
toggle? aba? overlay?) + implementação por aba.

---

## Sessão futura (prioridade média) — Responsividade mobile

**Status:** prioridade média. Problema conhecido reportado pelo user
em viewports estreitos (iPhone).

**Sintomas observados:**
- Presets de período (1M/3M/6M/12M/Máx) ficam empilhados verticalmente
  em vez de horizontal — quebra a régua de botões.
- KPIs em régua de 4-5 cards perdem alinhamento — alguns cards
  estouram a largura, outros encolhem.
- Dropdowns lado-a-lado (granularidade + submercado da Geração)
  podem sobrepor.
- Tipografia Bauhaus em telas estreitas pode ficar ilegível em alguns
  títulos.

**Escopo:** revisão CSS dos elementos com layout horizontal fixo. 5
abas afetadas (PLD, Reservatórios, ENA, Geração, Carga). Princípio:
breakpoints CSS no `<style>` global do `app.py` (linhas ~58-400) com
ajuste pra `max-width: 768px` (tablet) e `max-width: 480px` (mobile).

**Trade-off:** Streamlit tem comportamento responsivo default
(columns viram empilhadas em mobile), mas nossos overrides Bauhaus
(width fixo, primary button amarelo, etc.) podem brigar com isso.
Precisa testar caso a caso.

**Esforço estimado:** 1-2 sessões — auditoria visual em devtools mobile
(Chrome) + breakpoints + validação manual em iPhone.

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
