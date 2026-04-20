# Feature Reservatórios — Pesquisa da Fase A

> Contexto persistente das descobertas durante a Fase A (inspeção das fontes ONS).
> Atualize este doc a cada passo de pesquisa pra não perder contexto em reboots de sessão.
> Fonte primária das queries: script `scripts/inspect_ons_reservatorios.py`.

## Objetivo

Renderizar uma aba "Reservatórios" com 5 gráficos (SIN + SE/CO + S + NE + N) mostrando
**EAR (Energia Armazenada)** em **% da capacidade máxima**, série histórica diária.

## Descobertas até agora (2026-04-20)

### 1. ONS tem CKAN público
- Endpoint: `https://dados.ons.org.br/api/3/action/`
- Não bloqueia curl_cffi impersonate=chrome (responde HTTP 200 normal).
- `package_show?id=dados-hidrologicos-res` retorna 83 recursos:
  - 3 formatos por ano (CSV, XLSX, PARQUET) para anos 2000-2025+.
  - 1 Dicionário de Dados (PDF, id=`c137bf99`).
- Arquivos hospedados em S3 AWS (`ons-aws-prod-opendata.s3.amazonaws.com`) — sem Akamai.

### 2. Dataset `dados-hidrologicos-res` é granular por RESERVATÓRIO, não por subsistema

Exemplo: Excel 2025 tem 63.877 linhas × 25 colunas — 1 linha por (reservatório × dia).

**Schema observado (arquivo 2025):**
```
id_subsistema              (SE, S, NE, N)
nom_subsistema             (Nordeste, Norte, Sudeste/Centro-Oeste, Sul)
tip_reservatorio           (FIO, RCU, ...)
nom_bacia                  (JEQUITINHONHA, PARAGUACU, ...)
nom_ree                    (NORDESTE, ...)
id_reservatorio, cod_usina, nom_reservatorio
num_ordemcs
din_instante               (datetime)
val_nivelmontante          (float)
val_niveljusante           (float)
val_volumeutilcon          (float) ← provável % do volume útil (a confirmar via dicionário)
val_vazaoafluente          (float)
val_vazaoturbinada         (float)
val_vazaovertida           (float)
val_vazaooutrasestruturas  (float)
val_vazaodefluente         (float)
val_vazaotransferida       (float)
val_vazaonatural           (float)
val_vazaoartificial        (float)
val_vazaoincremental       (float)
val_vazaoevaporacaoliquida (float)
val_vazaousoconsuntivo     (float)
val_vazaoincrementalbruta  (float)
```

**NÃO existe coluna `EAR` ou `ear_percent` direta.** Esse dataset é sobre vazões e níveis
individuais, não sobre Energia Armazenada agregada.

### 3. Boletim SDRO é frameset HTML clássico

URL `sdro.ons.org.br/SDRO/DIARIO/index.htm`:
- HTTP 200, 1424 bytes.
- `<frameset>` (HTML de 2000's, declaração XHTML 1.0 Frameset).
- Nenhum link "hidrologia/reservatório/json/csv" na página índice.
- Navegação real acontece dentro dos frames — vai ser scrape manual se for usado.

## Abordagens possíveis (a avaliar)

### A) Agregar do hidrológico + tabela de EARmax
- Baixar Excel/Parquet anual, pegar `val_volumeutilcon` por reservatório.
- Cruzar com tabela EARmax (MWh) por reservatório (precisa ACHAR essa tabela).
- Somar (vol% × EARmax) por subsistema → dividir por total_EARmax → % EAR.
- **Custo:** pesado (baixa N Excels, cruza tabelas). Parquet ajuda.

### B) Métrica alternativa — volume útil em %
- Se `val_volumeutilcon` já for %, agregar direto (média ponderada por reservatório?).
- Menos "correto" que EAR (EAR considera geração potencial, vol só volume), mas disponível.
- Aceitável se o objetivo é "mostrar quão cheio está cada subsistema".

### C) Dataset ONS pronto pra EAR agregada — a descobrir
- Fase de pesquisa ativa: ver próxima seção.

## DATASET IDEAL ENCONTRADO ✅

**`ear-diario-por-subsistema`** — exatamente o que precisamos.

### Origem dos arquivos — AWS S3 público (virtual-hosted style)

**Não é CKAN datastore_search**, nem CDN. O CKAN (`dados.ons.org.br/api/3/action/`)
é usado só pra descobrir metadados. Os arquivos ficam em S3 público direto.

Pattern de URL:
```
https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/ear_subsistema_di/EAR_DIARIO_SUBSISTEMA_{YYYY}.{parquet|xlsx|csv}
```

Exemplo real testado (Fase A, HTTP 200, 33.082 bytes, 1.460 linhas):
```
https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/ear_subsistema_di/EAR_DIARIO_SUBSISTEMA_2025.parquet
```

Vantagens S3-direto vs CKAN datastore_search:
- Sem paginação (CKAN retorna chunks de 1000)
- Parquet nativo (tipos + schema preservados)
- Muito mais rápido (33KB/arquivo vs milhares de chamadas JSON)
- Sem Akamai/bloqueio (S3 público não filtra)

### Cobertura
- **Anos disponíveis: 2000-2026** (27 anos, parquet + xlsx + csv por ano)
- **Parquet: 33KB/arquivo** → 27 anos ≈ 900KB total, download trivial

### Schema confirmado (parquet 2025, 1.460 linhas × 6 colunas)

```
id_subsistema                     object   # 'N', 'NE', 'S', 'SE'
nom_subsistema                    object   # 'NORTE', 'NORDESTE', 'SUL', 'SUDESTE'
ear_data                          object   # string ISO 'YYYY-MM-DD'
ear_max_subsistema                float64  # capacidade máxima em MWmês
ear_verif_subsistema_mwmes        float64  # EAR verificada em MWmês
ear_verif_subsistema_percentual   float64  # ← MÉTRICA PRINCIPAL (% da capacidade)
```

### Exemplo de linha (2025-01-01 SE)
```
SE | SUDESTE | 2025-01-01 | 204615.328 | 105698.119 | 51.657
```

### Capacidades (ear_max_subsistema, MWmês)
- SE: 204.615
- NE:  51.691
- S:   20.459
- N:   15.302
- SIN total: 292.067

### Cálculo do SIN
Dataset NÃO traz linha "SIN" — só os 4 subsistemas. Então:
```
SIN_pct(data) = sum(ear_verif_mwmes)   por subsistema  na data
               / sum(ear_max)          por subsistema
               × 100
```

### Nomenclatura
ONS usa **"SUDESTE"** (sem "/CENTRO-OESTE"). ID `SE`, não `SE_CO`. Mais simples
do que o schema planejado — vamos aderir a essa nomenclatura ONS pra consistência.

## RECOMENDAÇÃO: caminho **C** (dataset pronto)

Nem Fallback A (cálculo do hidrológico) nem B (usar volume util) são necessários.
O ONS publica EXATAMENTE o que queremos. Rolou sorte + pesquisa de 10 datasets.

## Status das fontes

- **Fonte principal (histórico):** `ear-diario-por-subsistema` parquet anual. ✓
- **Fonte complementar (gap recente):** a decidir. O dataset principal já é atualizado
  frequentemente ("A atualização desses dados no Portal ocorrem as 9:15h, 14:15 e 17h"
  segundo o dataset hidrológico — provavelmente mesma cadência). Se gap for pequeno
  (1-2 dias), pode valer pular o SDRO scrape.
- **SDRO boletim (sdro.ons.org.br):** frameset HTML antigo. **Não necessário** se o
  dataset principal estiver atualizado até hoje. Avaliar na Fase B com dados reais.

## VALIDAÇÃO DO LOADER (Fase B concluída — 2026-04-20)

Loader `load_reservatorios()` implementado em `data_loader.py`. Rodado via
`scripts/validate_reservatorios.py`:

### Shape
- **48.030 linhas × 4 colunas** (`data`, `subsistema_code`, `subsistema_nome`, `ear_pct`)
- **9.606 linhas por subsistema** (= 26,3 anos × 365 dias) — bate
- **5 subsistemas presentes**: N, NE, S, SE, SIN ✓

### Cobertura temporal
- **2000-01-01 → 2026-04-19** (atualizado até 1 dia antes do teste)
- Sem gaps anuais — todos os 27 anos carregaram

### Estatísticas históricas por subsistema

| Code | Range% min | Range% méd | Range% máx |
|---|---|---|---|
| N  | 12.14  | 65.70 | **103.66** (excede 100% — raro, esperado) |
| NE |  4.34  | 53.05 |  99.53  (crise NE 2015-17) |
| S  | 14.84  | 66.70 |  99.24 |
| SE | 15.12  | 53.10 |  89.62  (crise SE 2014-15) |
| SIN| 17.81  | 54.64 |  89.87 |

### Verificação matemática do SIN (amostras aleatórias)
SIN calculado puxa pra SE (peso 70% do EARmax total). Validado:
- `2018-05-14`: SE=43 → SIN=44.77 ✓
- `2009-05-30`: SE=82.13 → SIN=82.89 ✓
- `2008-04-02`: SE=78.58 → SIN=74.66 ✓

### Decisão: **RAW values, sem clamp em 100%**
Valores >100% são reais (reservatórios podem exceder capacidade nominal em
enchentes, revisões de EARmax). Visualização usa eixo Y compartilhado 0-110%
pra acomodar picos sem censura.

## Datasets bonus encontrados (relevantes pra futuras features)

- `ear-diario-por-bacia` / `ear-diario-por-ree` / `ear-diario-por-reservatorio` — outras granularidades de EAR (não necessárias agora).
- `ena-diario-por-subsistema` — Energia Natural Afluente (fluxo de chegada nos reservatórios).
- `balanco-energia-subsistema` — carga e oferta horária por subsistema.
- `carga-energia` — carga diária por subsistema.
- `intercambio-nacional` — fluxo entre subsistemas.

Guardados aqui pra roadmap futuro.

## Estratégia de execução

- Fase A → em andamento (esta pesquisa).
- Fase B → backend (data_loader_reservatorios.py ou extensão).
- Fase C → UI (radio sidebar + 5 gráficos).
- Fase D → polish (hover, caption, export).

## Observações técnicas

- Parquet existe como formato ONS — **preferir sobre XLSX**. Leitura ~10× mais rápida,
  tipos preservados. `pd.read_parquet` + `pyarrow` backend.
- Cache ttl=6h (reservatórios atualizam devagar).
- Se download de N anos (25+) ficar lento, considerar cache local em Parquet/disco
  (discutir com user antes de implementar).
- `requirements.txt` agora inclui `openpyxl>=3.1,<4.0` e `pyarrow>=15.0,<22.0`.
