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

**Decisão arquitetural nova (5.28)** consolidaria o pattern (5.27 foi
usada na Sessão 4a pelo ajuste de presets/tooltip do Máx).

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

## Sessão futura (prioridade média) — UX: Comportamento do preset 15A quando dados não cobrem

**Status:** prioridade média — fix técnico do crash já aplicado na
Sessão 4a (clamp em `min_d` no `_render_period_controls`,
`app.py:650-655`). Sessão futura discute apenas a UX do clamp.

**Comportamento atual (pós-fix):** quando preset pede período maior que
`(max_d - min_d).days` (ex: 15A na Carga sem histórico completo →
data_ini=2011-04-28 < min_d=2012-01-01), o clamp em `min_d` faz a
seleção degenerar pra equivalente de "Máx". Resultado: botão "Máx" fica
amarelo silenciosamente, 15A não fica destacado. Honesto sobre dados
disponíveis, mas pode confundir user que esperava "15 anos".

**3 alternativas a discutir:**

(a) **Manter atual** — Máx amarelo, sem caption. Honesto sobre dados
disponíveis, zero ruído visual. Custo: user pode não notar que pediu
15A e recebeu 14a.

(b) **Sugerir ativar histórico completo via caption** — quando o clamp
acontece, mostrar caption pequena "15A não disponível com dataset atual.
Carregue o histórico completo (botão acima) pra ver os 15 anos."
Educativo, conecta os 2 eixos da decisão 5.17. Custo: caption fica
visível em todo render desse cenário, pode virar ruído se o user
explicitamente quer ficar nos 15a.

(c) **Manter 15A amarelo + caption explicativo** — preserva sinal do
preset clicado mesmo após clamp + esclarece o que aconteceu. Mais
complexo (a detecção de "preset ativo" da linha 624 usa
`(max_d - data_ini).days == delta`, que não bate após clamp — exigiria
flag adicional `_<aba>_preset_clicado` em session_state). Trade-off:
mais state pra manter consistente, mas UX mais expressiva.

**Preferência inicial:** (b) — adiciona valor educativo sem complicar
state. Mas vale conversar com user antes.

**Esforço estimado:** **~30 min** (caso (b)) ou **~1h** (caso (c)).
Mudança contida ao `_render_period_controls` + caller (caption
condicional após o helper).

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
