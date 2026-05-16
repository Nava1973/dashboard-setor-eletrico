# SPEC — Sub-aba GSF (Generation Scaling Factor) — V1 + V2

**Status:** Pós Fase 0 (validada empiricamente em 16/mai/2026 — 12/12 hits ±0,5pp)
**Localização da sub-aba:** Geração → após "Solar"
**Versão alvo:** V1 (realizado mensal SIN, nov/2023+) + V2 (extensão histórica pré-nov/2023, se usuário fornecer)
**Excluído explicitamente (V3 futuro):** projeção forward via InfoPLD PDF

---

## 0. Histórico de descobertas da Fase 0

A versão inicial deste spec assumia que `MRE_MENSAL` continha os campos necessários. **Essa hipótese foi rejeitada empiricamente** após testes contra 15 pontos oficiais validados (9 do Power BI público da CCEE + 6 do InfoPLD).

8 hipóteses testadas; apenas a 8ª passou no critério ±0,5pp em 12/12 meses cobertos. Documentação completa em CLAUDE.md (seção dedicada pós-implementação).

---

## 1. Objetivo

Adicionar uma sub-aba **GSF** dentro da aba Geração, posicionada logo após Eólica e Solar, exibindo a série histórica do Fator de Ajuste do MRE (Generation Scaling Factor) realizado, com destaque visual para períodos de Energia Secundária (GSF > 100%).

## 2. Conceito

**Fator de Ajuste do MRE (GSF)** = relação entre a geração total das UHEs participantes do MRE e a soma das garantias físicas dessas usinas no mês de referência, ambas medidas **no centro de gravidade** (já descontadas de perdas).

**Fórmula validada empiricamente:**

```
GSF_mês = Σ(GERACAO_MRE) / Σ(GARANTIA_FISICA_MRE)
```

A soma percorre todos os 4 submercados (SE, S, NE, N) × todos os períodos de comercialização (1..744 horas) do mês de referência.

**Validação**: 12/12 meses cobertos batem dentro de ±0,5pp contra 15 valores oficiais consolidados de Power BI CCEE + InfoPLD. Mean abs diff = 0,027pp. Max abs diff = 0,158pp. 4 meses batem a 3+ casas decimais.

**Interpretação:**
- GSF < 100% → déficit hidrológico, exposição no MCP
- GSF = 100% → equilíbrio
- GSF > 100% → Energia Secundária (excedente rateado entre cotistas)

**Importante**: o GSF é único para o SIN. O MRE é um pool nacional — agregar os 4 submercados é mecânica, não decomposição.

## 3. Fonte de dados

### V1 — Realizado mensal (nov/2023+)

**Dataset canônico:** `GERACAO_HORARIA_SUBMERCADO` (Portal Dados Abertos CCEE)

- URL base: `https://dadosabertos.ccee.org.br/dataset/geracao_horaria_submercado`
- Dataset ID: `27fd4abf-9508-4c16-9885-289524b2d529`
- Granularidade nativa: **horária, por submercado** (4 submercados × 720-744 períodos/mês)
- Histórico: **nov/2023 até presente** (~29 meses em mai/2026)
- Frequência de atualização: **~MS+2 meses**
- Formato: CSV (1 arquivo por ano)

**Resource IDs por ano** (persistidos em `scripts/_resource_ids_gsf.json`):
```
2023: 18c785e6-ecb3-465c-af55-77dc9a374f95
2024: 9d619679-62fc-4afd-b725-ee63c5d511d8
2025: eeafc24a-97de-4e34-805b-bf5fc8146be2
2026: 4ff8ad16-93fa-4bf2-a7f3-03f23132fb38
```

**Volume**: ~35k linhas/ano. Total 4 anos ≈ 140k linhas. Trivial para cache.

**Schema relevante:**

| Coluna | Tipo | Uso |
|---|---|---|
| `MES_REFERENCIA` | str AAAAMM | Chave temporal |
| `SUBMERCADO` | str | NORDESTE, NORTE, SUDESTE, SUL |
| `PERIODO_COMERCIALIZACAO` | int 1..744 | Hora do mês |
| `GERACAO_MRE` | float MWh | **Numerador** da fórmula GSF |
| `GARANTIA_FISICA_MRE` | float MWh | **Denominador** da fórmula GSF |

### V2 — Histórico pré-nov/2023

Fonte: arquivo local fornecido pelo usuário (se disponível).

Possíveis origens: InfoMercado Dados Gerais (descontinuado em mai/2024), Power BI público CCEE (mostra GSF mensal desde set/2012), tabulação manual de boletins históricos.

Armazenamento: `data/raw/gsf_historico_pre2023.csv`.
Schema mínimo: `mes_ref` (YYYY-MM), `gsf` (decimal).
Integração: flag `fonte_dado` ∈ {`ccee_horaria`, `historico_legado`} para auditabilidade.

## 4. Arquitetura

### 4.1 Data loader

**Arquivo:** `data_loaders/ccee_gsf.py` (novo)

**Função principal:** `load_gsf_mensal() -> pd.DataFrame`

**Schema retornado:**
```
colunas: mes_ref (datetime64, primeiro dia do mês),
         sum_geracao_mre_mwh,
         sum_gf_mre_mwh,
         gsf (decimal, ex: 0.8497),
         fonte_dado
índice: mes_ref ascendente, sem duplicatas
```

**Ingestão (padrão estabelecido CLAUDE.md — 3-strategy cascade):**
1. CKAN `datastore_search` paginado (1000 linhas/request)
2. Dump endpoint
3. Fixed `pda-download` URL (fallback)

`curl_cffi` impersonating Chrome (padrão consolidado para CCEE).

**Cache (padrão 2-layer):**
- `@st.cache_data` na função pública
- Disk cache parquet por ano: `data/cache/gsf_horaria_YYYY.parquet`
- TTL diferenciado:
  - Anos fechados (< ano atual − 1): 30 dias
  - Ano atual e anterior: 24h
- `_CACHE_VERSION_GSF = 1`

**Agregação para mensal (no loader):**
```python
gsf_mensal = (
    df.groupby('mes_ref')
      .agg(
          sum_geracao_mre_mwh=('GERACAO_MRE', 'sum'),
          sum_gf_mre_mwh=('GARANTIA_FISICA_MRE', 'sum'),
      )
)
gsf_mensal['gsf'] = (
    gsf_mensal['sum_geracao_mre_mwh'] / gsf_mensal['sum_gf_mre_mwh']
)
```

### 4.2 Validação de integridade

**Script:** `scripts/validar_gsf_vs_oficial.py`

**15 pontos oficiais consolidados:**

```python
GSF_OFICIAL_15PTS = {
    "2023-03": 1.01564, "2023-07": 0.77957, "2024-03": 0.95041,
    "2024-07": 0.84975, "2025-01": 1.13213, "2025-02": 1.10957,
    "2025-06": 0.87700, "2025-07": 0.69330, "2025-08": 0.62600,
    "2025-09": 0.63000, "2025-10": 0.63100, "2025-11": 0.65700,
    "2025-12": 0.73600, "2026-01": 0.81207, "2026-02": 1.00318,
}
```

**Critério**: 12+/12 cobertos pelo dataset dentro de ±0,5pp. (3 ficam fora — 202303, 202307, 202403 — porque o dataset começa em nov/2023; só V2 pode cobrir esses.)

### 4.3 UI — Sub-aba GSF

**Localização:** módulo da aba Geração, render após sub-abas Eólica e Solar.

**Bloco 1 — KPIs topo (3 cards Bauhaus):**
- GSF mês mais recente (% formatado com 1 casa)
- GSF acumulado 12 meses (média ponderada: `sum(GERACAO)/sum(GF)` dos últimos 12 meses)
- Energia Secundária acumulada 12 meses (TWh, soma do excedente sobre GF quando GSF > 1)

**Bloco 2 — Gráfico principal: Linha temporal**
- Eixo X: tempo mensal contínuo (V2 estendendo retroativamente quando disponível)
- Eixo Y: GSF em %
- Linha horizontal de referência em 100% (preta, dashed, label "Paridade GF")
- Linha do GSF: cor Bauhaus cobalt `#1D3557`, espessura 2px
- Preenchimento abaixo de 100%: vermelho `#D62828` opacidade 15% — "déficit"
- Preenchimento acima de 100%: amarelo `#F6BD16` opacidade 15% — "secundária"
- Hover em JetBrains Mono: mês, GSF%, fonte_dado
- Markers grandes nos pontos onde GSF > 100%

**Bloco 3 — Tabela complementar (HTML, padrão CLAUDE.md):**
- Últimos 12 meses
- Colunas: Mês, GSF (%), Geração MRE (TWh), GF MRE (TWh), Energia Secundária? (Sim/Não)
- Linha destacada quando Energia Secundária

**Period controls:** padrão do projeto — `date_input` + shortcut buttons (12M, 24M, 5A, Máx). Default: 24M.

### 4.4 Posicionamento e CSS

- Sub-aba após Solar dentro do conjunto custom `.st-key-btn_geracao_subaba_gsf` (padrão Curtailment, CLAUDE.md §5.60)
- Active button: amarelo `#F6BD16` + borda preta 2px
- Sem `:has()` (regra dura)
- Sem `display:none` em clickable

## 5. Decisões arquiteturais

| Decisão | Alternativa rejeitada | Razão |
|---|---|---|
| `GERACAO_HORARIA_SUBMERCADO` | `MRE_MENSAL`, `GERACAO_UHE_V2` | Únicos campos no centro de gravidade que casam com GSF oficial |
| `GERACAO_MRE / GARANTIA_FISICA_MRE` | 7 outras combinações | Única que bate 12/12 ±0,5pp |
| Agregar horário → mensal no loader | Manter horário no app | Sub-aba é mensal; agregar uma vez no cache |
| Único GSF (SIN) | Decomposição por submercado | Conceito MRE é nacional |
| TTL diferenciado | TTL único | Recontabilização possível em anos recentes |
| V3 adiado | PDF parsing agora | Custo alto, fragilidade alta, valor incremental baixo |

## 6. Armadilhas críticas (Fase 0)

**Colunas que parecem mas não são:**

| Coluna | O que parece | O que é | Não usar |
|---|---|---|---|
| `GERACAO` (sem `_MRE`) | Geração das UHEs MRE | Geração TOTAL do submercado (todas fontes) | Inflaria 3-4x |
| `GARANTIA_FISICA_MODULADA_MRE` | GF para GSF | GF capada pós-modulação | Sempre ≈ 100% |
| `ENTREGA_MRE` (MRE_MENSAL) | Geração ao MRE | Volume settled (VALOR/CUSTO) | Não é geração |
| `FATOR_REDUCAO_ACUMULADO` | GSF | Produto de fatores de perda | Confunde conceitos |
| `MEDICAO_GERACAO_MENSAL` (GERACAO_UHE_V2) | Numerador | Geração na barra, sem perdas | Viés +1,5% |

**Itaipu**: incluída na fórmula via `PARTICIPANTE_MRE='Sim'`. Não precisa tratamento especial (testado e rejeitado).

## 7. Riscos conhecidos

1. **Cobertura pré-nov/2023**: dataset não cobre. Dependente de V2 ou aceitação de limite na V1.
2. **Recontabilização**: mitigado por TTL curto em anos recentes.
3. **Defasagem MS+2 meses**: UI deve indicar claramente o último mês disponível.
4. **V2 schema**: arquivo do usuário pode requerer harmonização.

## 8. Critérios de aceitação

### V1
- [ ] Loader baixa `GERACAO_HORARIA_SUBMERCADO` 2023+ com cascade
- [ ] Agrega horário → mensal corretamente
- [ ] Cache 2-layer funcional
- [ ] Schema padronizado retornado
- [ ] Sub-aba GSF aparece após Solar (botão Bauhaus)
- [ ] Gráfico linha temporal com paridade 100%, preenchimentos vermelho/amarelo, markers em Energia Secundária
- [ ] Tabela últimos 12 meses
- [ ] KPIs topo
- [ ] Period controls funcionais
- [ ] Hover JetBrains Mono
- [ ] Script de validação: 12/12 hits ±0,5pp
- [ ] Roda em Streamlit Cloud sem OOM

### V2
- [ ] `data/raw/gsf_historico_pre2023.csv` integrado com flag `fonte_dado=historico_legado`
- [ ] Concat sem duplicatas
- [ ] Série temporal estendida visualmente contínua

## 9. Documentação pós-implementação no CLAUDE.md

Próxima §5.x livre deve registrar:
- **Fonte canônica**: `GERACAO_HORARIA_SUBMERCADO`
- **Fórmula validada**: `sum(GERACAO_MRE) / sum(GARANTIA_FISICA_MRE)`
- **3 armadilhas** (lista da seção 6)
- **15 pontos oficiais** de referência
- **Decisões**: GSF único SIN, V3 adiada
- **Resource IDs** persistidos em JSON

## 10. Referências

- Power BI público CCEE: `https://www.ccee.org.br/en/dados-e-analises/dados-geracao`
- Regras de Comercialização CCEE, módulo MRE, item MR.2.1
- Dataset: `https://dadosabertos.ccee.org.br/dataset/geracao_horaria_submercado`
- InfoPLD Diário (dez/2025+) — fonte de validação cruzada
