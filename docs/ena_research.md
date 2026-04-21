# Feature ENA / Chuva — Pesquisa da Fase A

> Contexto persistente das descobertas durante a Fase A (inspeção ONS).
> Atualize este doc a cada passo de pesquisa pra não perder contexto entre sessões.
> Fonte primária das queries: script `scripts/inspect_ena.py`.

## Objetivo

Renderizar uma aba "ENA / Chuva" com 5 gráficos empilhados (SIN + SE + S + NE + N)
mostrando **ENA (Energia Natural Afluente)** em **MWmed**, série histórica diária.
Complemento ao EAR: ENA mede o fluxo de entrada (chuva/vazões), EAR mede o estoque.

## Descobertas (2026-04-21)

### 1. Dataset ideal existe ✅

**`ena-diario-por-subsistema`** no CKAN ONS — análogo direto do
`ear-diario-por-subsistema`. Mesma infraestrutura, mesmo S3 público, schema
espelhado.

- CKAN metadata: `https://dados.ons.org.br/api/3/action/package_show?id=ena-diario-por-subsistema`
- Responde HTTP 200 com curl_cffi `impersonate="chrome"`, como o EAR.
- **62 resources totais** (27 CSV + 27 XLSX + 6 PARQUET + 1 PDF dicionário + 1 JSON).

### 2. URL pattern S3 (virtual-hosted)

```
https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/ena_subsistema_di/ENA_DIARIO_SUBSISTEMA_{YYYY}.{parquet|xlsx|csv}
```

Confirmado via HTTP GET direto — S3 público, sem Akamai, funciona igual EAR.

### 3. Cobertura temporal

| Formato | Anos     | N arquivos | Tamanho/arquivo |
|---------|----------|------------|-----------------|
| CSV     | 2000-2026 | 27        | ~107 KB (sep `;`, decimal `.`) |
| XLSX    | 2000-2026 | 27        | ~65-85 KB       |
| PARQUET | **2021-2026** | **6** | ~55-80 KB       |

**⚠ Diferença importante vs Reservatórios:** parquet só existe a partir de 2021.
ONS não republicou parquet histórico como fez no EAR. Anos 2000-2020 só em
XLSX/CSV.

**Implicações:**
- Não dá pra usar só parquet — perderia 21 anos de histórico.
- Opções: (a) XLSX pra tudo (27×~75KB ≈ 2MB, simples), (b) PARQUET 2021+ +
  XLSX pra 2000-2020 (código híbrido, menos 0.4MB só), (c) CSV pra tudo.
- **Recomendação: XLSX pra tudo** — schema idêntico entre os formatos,
  dtypes corretos, sem parsing decimal. 2MB total é irrelevante. Cache de
  30d por ano histórico mantém download pontual.

### 4. Schema confirmado (idêntico entre XLSX 2015 e PARQUET 2025)

```
id_subsistema                         object   # 'N', 'NE', 'S', 'SE' (NÃO tem SIN)
nom_subsistema                        object   # 'NORTE', 'NORDESTE', 'SUL', 'SUDESTE'
ena_data                              object (ISO YYYY-MM-DD) ou datetime
ena_bruta_regiao_mwmed                float64  # ENA bruta total (MWmed)
ena_bruta_regiao_percentualmlt        float64  # % da MLT (Média Longo Termo)
ena_armazenavel_regiao_mwmed          float64  # ENA que pode ser armazenada
ena_armazenavel_regiao_percentualmlt  float64  # % da MLT
```

- 1.460 linhas/ano (= 4 subsistemas × 365 dias), 7 colunas
- **NÃO tem linha SIN** — só os 4 subsistemas. SIN é calculado.

### 5. Unidade confirmada: **MWmed** ✅

Exatamente o que o user especificou. Não aparece "MWmês" nem "MWh" em lugar
nenhum das colunas ENA — ONS publica direto em MW médios por dia.

### 6. Definições das 4 métricas disponíveis

- **`ena_bruta_regiao_mwmed`** — ENA bruta: toda a energia natural afluente
  ao subsistema (chuva convertida em energia hidrelétrica potencial). É a
  métrica "total da entrada".
- **`ena_armazenavel_regiao_mwmed`** — ENA armazenável: parcela da bruta que
  pode efetivamente ser guardada no reservatório (desconta o que passa como
  fio d'água). Mais estrita.
- **`ena_bruta_regiao_percentualmlt`** — % da MLT (Média Longo Termo do
  subsistema). Permite comparar entre subsistemas com capacidades diferentes:
  100% = média histórica, >100% = chuva acima do normal.
- **`ena_armazenavel_regiao_percentualmlt`** — idem % da armazenável.

**Recomendação:** usar **`ena_bruta_regiao_mwmed`** como métrica principal
(alinhado com "ENA em MWmed" pedido pelo user). Se depois fizer sentido,
dá pra adicionar um toggle bruta/armazenável ou MWmed/%MLT. **A decidir com
user antes da Fase C.**

### 7. SIN — soma simples (validado)

Dataset não traz linha SIN. Cálculo:
```
SIN_mwmed(data) = N + NE + S + SE   (soma simples)
```

Validado em 3 amostras (parquet 2025):

| Data        | N       | NE      | S       | SE       | SIN        |
|-------------|---------|---------|---------|----------|------------|
| 2025-01-15  | 16.981  | 17.596  |  4.006  | 70.115   | 108.698    |
| 2025-07-02  |  4.318  |  1.728  | 33.713  | 25.917   |  65.675    |
| 2025-12-20  |  5.893  |  4.615  |  4.068  | 47.877   |  62.453    |

Faz sentido físico (ENA é variável de fluxo — soma direta). Não precisa
ponderação como o EAR.

### 8. Range de valores observado (2025)

```
min    :    993 MWmed  (NE, seco)
25%    :  2.873
mediana:  7.638
75%    : 20.090
max    : 73.289 MWmed  (SE, cheia)
```

**Gap entre subsistemas é enorme** (S em cheia: 33k MWmed; NE no seco: 1.7k).
Escala Y compartilhada esmagaria N e NE visualmente. **Recomendação:
escala Y AUTOMÁTICA por gráfico** — cada subsistema no próprio zoom.

### 9. Nomenclatura

Idêntica ao EAR: ONS usa `SE` (SUDESTE), sem "/CENTRO-OESTE". Aderimos à
convenção oficial. Mapa `SUBSISTEMA_NOMES` do data_loader.py (`N → NORTE`,
etc.) já cobre.

## Datasets alternativos (descartados)

- **`ena-diario-por-reservatorio`** — por reservatório individual (análogo ao
  `dados-hidrologicos-res` do EAR). Milhares de linhas/ano, exige agregação.
  Descartado pela mesma razão do EAR: dataset agregado já existe e é perfeito.
- **`ena-diario-por-bacia`** / **`ena-diario-por-ree`** — outras granularidades.
  Não necessárias pra feature.
- **SDRO boletim** — frameset HTML, não necessário se o dataset CKAN atualiza
  3x/dia (igual EAR). Reavaliar na Fase B se houver gap de dados recentes.

## Status das fontes

- **Fonte principal:** `ena-diario-por-subsistema` — XLSX anual (recomendado)
  ou PARQUET 2021+ se decidir híbrido. ✓
- **Fonte complementar (gap recente):** dispensável como no EAR. ONS atualiza
  9:15/14:15/17h. Se gap ≤ 1-2 dias, não precisa scrape SDRO.

## Estratégia de execução

- **Fase A** → concluída (esta pesquisa). Aguarda aprovação do user pra seguir.
- **Fase B** → backend: `load_ena()` em `data_loader.py`, schema long-form
  (`data`, `subsistema_code`, `subsistema_nome`, `ena_mwmed`), SIN via soma,
  cache split por ano (30d histórico + 2h externo). `scripts/validate_ena.py`.
- **Fase C** → UI: aba radio "ENA/Chuva" abaixo de Reservatórios,
  5 gráficos empilhados, `_render_period_controls` com prefix `ena_`,
  faixas azuis do período úmido reusando função existente do app.
- **Fase D** → polish: título "SUBSISTEMA  DD/MM/YYYY · XX MWmed", hover
  format MWmed, caption ONS, export CSV.

## Decisões consolidadas (Fases B/C concluídas)

1. **Métrica principal:** `ena_bruta_regiao_percentualmlt` (% da MLT).
   Normalizada, permite comparação direta entre subsistemas.
   - `ena_bruta_regiao_mwmed` e `ena_armazenavel_regiao_mwmed` continuam
     no DataFrame retornado por `load_ena()` (schema long-form com 3 métricas),
     mas não são plotadas na UI atual. Reservados pra toggle futuro.
2. **Eixo Y:** compartilhado entre os 5 gráficos, **range fixo 0-250%**.
   Diferente da decisão inicial (eixo independente pra MWmed absoluto).
   Ver CLAUDE.md decisão 5.7 — escolha de eixo segue a natureza da métrica
   (normalizada vs absoluta), não o dataset. Valores acima de 250% ficam
   visualmente cortados mas o hover mostra o valor real.
3. **Formato de download:** XLSX pra todos os anos (2000-2026, ~2MB total).
   Parquet só existe 2021+, não cobre histórico.
4. **SIN em % MLT:** calculado via reversão da MLT absoluta
   (`mlt_abs_sub = ena_mwmed_sub / (pct_mlt_sub/100)`), depois
   `SIN_mlt_pct = sum(ena_mwmed) / sum(mlt_abs) × 100`. Validado em
   `scripts/validate_ena.py` com diff = 0.0000 em 3 amostras aleatórias.
