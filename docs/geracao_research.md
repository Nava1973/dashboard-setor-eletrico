# Pesquisa Fase A — Balanço de Energia nos Subsistemas (ONS)

> Descoberta executada em 2026-04-23 via `scripts/inspect_balanco.py` +
> `scripts/inspect_balanco_smoke.py`. Serve de base pra implementação do
> loader `load_balanco_subsistema()` em `data_loader.py` e da aba Geração
> em `app.py`. Análogo ao `docs/ena_research.md` e `docs/reservatorios_research.md`.

---

## 1. Identificação do dataset

- **Dataset CKAN:** `balanco-energia-subsistema`
- **Título oficial:** *"Balanço de Energia nos Subsistemas"*
- **Licença:** Creative Commons Atribuição (CC-BY)
- **Última atualização observada:** 2026-04-22 22:01 UTC
- **Última observação no parquet 2026:** `2026-04-21 23:00:00` (dados até ontem)

CKAN API confirma **83 resources** (27 anos × 3 formatos + extras). Cobertura
confirmada **parquet + xlsx + csv para TODOS os anos 2000–2026** — diferente do
ENA, onde parquet só existe a partir de 2021.

---

## 2. URL pattern

```
https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/
  balanco_energia_subsistema_ho/
    BALANCO_ENERGIA_SUBSISTEMA_{ANO}.{parquet|xlsx|csv}
```

Slug S3 termina em `_ho` (indicando granularidade horária — sufixo já padrão
do ONS pra dataset horário no subsistema; cf. `ear_subsistema_di` = diário).

HEAD/GET funciona em todos os anos 2000-2026 (27/27 ✓). Tamanhos:

| Formato | Tamanho típico/ano | Observação |
|---|---|---|
| parquet | ~2.1–2.7 MB | **escolha padrão** |
| xlsx    | ~2.6–3.0 MB | evitar (parser mais lento) |
| csv     | ~4.1–5.1 MB | fallback |

**Total do dataset completo (27 anos parquet): ~60 MB.** É ~65× o EAR (900KB)
e ~30× o ENA (2MB). Cache interno por ano é ESSENCIAL; sem ele o refresh de
2h recarregaria 60MB. **Decisão:** seguir mesmo padrão split cache
(30d por ano fechado + 2h externo) — consistente com EAR/ENA.

---

## 3. Schema real (parquet)

**Fonte:** download completo de `BALANCO_ENERGIA_SUBSISTEMA_2016.parquet`
(2.29 MB, 43919 linhas × 9 colunas).

| Coluna | dtype raw | Natureza | Valores |
|---|---|---|---|
| `id_subsistema` | object | categórico | `'SE'`, `'S'`, `'NE'`, `'N'`, **`'SIN'`** |
| `nom_subsistema` | object | categórico | `'SUDESTE/CENTRO-OESTE'`, `'SUL'`, `'NORDESTE'`, `'NORTE'`, `'SISTEMA INTERLIGADO NACIONAL'` |
| `din_instante` | datetime64[ns] | timestamp horário | `2016-01-01 00:00` a `2016-12-31 23:00` |
| `val_gerhidraulica` | object (Decimal string) | MWmed | ex: `"2736.97290039"` |
| `val_gertermica` | object (Decimal string) | MWmed | inclui nuclear + biomassa |
| `val_gereolica` | object (Decimal string) | MWmed | |
| `val_gersolar` | object (Decimal string) | MWmed | ⚠️ **nome diferente da spec** |
| `val_carga` | object (Decimal string) | MWmed | |
| `val_intercambio` | object (Decimal string) | MWmed | líquido do subsistema |

### 3.1. ⚠️ Desvios frente à spec

| Spec dizia | Dataset real |
|---|---|
| `val_gerfotovoltaica` | **`val_gersolar`** |
| 6 colunas (s/ intercâmbio) | **7 colunas de métrica** (inclui `val_intercambio`) |
| "colunas podem variar" | nomes estáveis em 2016 e 2024, confirmado |

### 3.2. Dtype: strings Decimal, não float

Valores como `"2736.97290039"` e **`"0E-8"`** (zero em notação decimal
exponencial). pandas lê como `object`. **Todo `val_*` precisa de
`pd.to_numeric(..., errors="coerce")` no normalizer** — mesmo tratamento que o
ENA (onde xlsx também vem ambíguo).

---

## 4. Descoberta crítica: linha SIN vem PRÉ-CALCULADA

Ao contrário do EAR e ENA (onde o loader calcula SIN agregando os 4
subsistemas), o **Balanço publica a linha SIN diretamente** com
`id_subsistema='SIN'`, `nom_subsistema='SISTEMA INTERLIGADO NACIONAL'`.

### 4.1. Validação: SIN publicado vs soma dos 4

Comparando `ONS_SIN(t)` vs `SE(t)+S(t)+NE(t)+N(t)` em 2016 (8784 timestamps):

| Métrica | max_diff_abs (MWmed) | max_diff_rel |
|---|---|---|
| `val_gerhidraulica` | 0.00 | 0.000% |
| `val_gertermica`    | 0.00 | 0.000% |
| `val_gereolica`     | 0.00 | 0.000% |
| `val_carga`         | 0.01 | 0.000% |

SIN publicado é **exatamente a soma dos 4** (diferença abaixo do ruído de
ponto flutuante). ONS garante consistência.

### 4.2. Decisão arquitetural

**Usar a linha SIN direto do dataset** em vez de calcular — diferente de
EAR/ENA. Razões:

1. ONS já garante consistência numérica (validado acima).
2. Evita introduzir lógica de agregação no loader (menos superfície pra bug).
3. Evita race condition se ONS emitir uma linha ausente para um submercado
   num timestamp específico (caso nosso soma daria NaN, mas a linha SIN
   pronta ainda estaria correta).

Registrar isso como decisão em CLAUDE.md seção 5.

### 4.3. Intercâmbio: NÃO somar entre submercados

`val_intercambio` do SIN é **~0 com ruído** (mean 2016: +20 MWmed, amplitude
±1500). Não é a soma dos intercâmbios subsistema — é o intercâmbio
**internacional** do SIN (Argentina, Uruguai, Venezuela). Intercâmbios
inter-submercado se cancelam dentro do país.

Implicação: **não usar `val_intercambio` pra reconciliar geração vs carga**
do SIN nesta aba. Deixar coluna passar pelo loader mas não exibir.

---

## 5. Cardinalidade e integridade

- 365 dias × 24h × 5 submercados (SIN incluso) = **43800 linhas/ano**
  (não-bissexto); **43920/ano** (bissexto: 2016, 2020, 2024).
- Medido: 2016 = 43919 linhas (1 missing — aceitável, ~0.002%).
- Medido: 2024 = 43920 linhas (completo).
- NaN em qualquer coluna em 2016: **0**.
- Registros por (dia, submercado): min=23, max=24, mode=24 — 1 dia com
  missing hour (provavelmente horário de verão, dataset descontinuou DST em
  2019; 2016 ainda tinha).

---

## 6. Smoke test dos números conhecidos (spec seção 11)

Calculado em `scripts/inspect_balanco_smoke.py` sobre 2024 completo (8784h
SIN), usando a linha `id_subsistema='SIN'`:

| Métrica SIN 2024 | Observado | Spec (alvo) | Resultado |
|---|---|---|---|
| Geração total (hidro+term+eol+sol) | **79.12 GWmed** | 75–80 | ✓ |
| Carga | **78.94 GWmed** | 75–80 | ✓ |
| % renov variável (eol+sol)/ger | **26.02%** | 22–25 | ≈ (2024 teve ano eólico forte) |
| NE % renov variável (anual) | **76.90%** | — | — |
| NE % renov variável (pico jul) | **80.80%** | ~80% | ✓ |
| Sul % térmica | **7.57%** | "> SIN" (=12.35%) | ✗ **spec errada em 2024** |

### 6.1. Observação sobre Sul térmica

A spec diz "Sul 2024: participação térmica maior que a média nacional".
**Não foi o caso.** 2024 teve hidrologia excelente no Sul (EAR Sul médio alto
durante o ano), deslocando térmica. Em anos secos do Sul (ex. 2021) a
heurística pode valer, mas **não é invariante**. Não usar esse check como
assertion de integridade — só como contexto.

### 6.2. Composição detalhada SIN 2024

- Hidráulica: 48.76 GWmed (61.6%)
- Térmica:     9.77 GWmed (12.4%)
- Eólica:     12.24 GWmed (15.5%)
- Solar:       8.35 GWmed (10.5%)

Números coerentes com EPE/ANEEL para 2024.

---

## 7. Implicações para o loader

1. **Formato: parquet** (menor, dtype preservado, leitura `pd.read_parquet`).
   Fallback: CSV (spec seção 3.2).
2. **Anos disponíveis: 2000–2026** (lista estática inicial; rever em janeiro
   de cada ano junto com EAR/ENA).
3. **Colunas mapeadas** (identificador tolerante por `keyword`, estilo
   `_identify_column`):
   ```python
   col_id_sub  = "id_subsistema"
   col_nom_sub = "nom_subsistema"
   col_time    = "din_instante"
   col_hidro   = "val_gerhidraulica"
   col_term    = "val_gertermica"
   col_eol     = "val_gereolica"
   col_sol     = "val_gersolar"       # ≠ spec
   col_carga   = "val_carga"
   # val_intercambio: lido mas não exposto na UI inicial
   ```
4. **Schema de saída (long-form):**
   ```
   data_hora        datetime64[ns]
   submercado       str    'SE'|'S'|'NE'|'N'|'SIN'
   fonte            str    'hidro'|'termica'|'eolica'|'solar'|'carga'
   mwmed            float
   ```
   Long-form facilita (a) export CSV pivot, (b) iteração genérica no stacked,
   (c) futura inclusão de GD como mais um valor de `fonte`.

5. **SIN não calculado — usa linha nativa.** Normalizer filtra os 5 códigos
   (`SE`, `S`, `NE`, `N`, `SIN`) direto.

6. **Cache:**
   - Externo `load_balanco_subsistema()`: TTL **6h** (ONS atualiza 12h e 19h
     BRT — 6h pega as duas atualizações com margem).
   - Interno `_download_balanco_parquet_historico(ano)`: TTL **30d** pra anos
     fechados (mesmo padrão do EAR/ENA).

7. **Tratamento de erros:** mesmo padrão —
   `st.session_state["_debug_erros"]` + `_erros_carga_balanco`.

---

## 8. Implicações para a aba

1. **SIN é opção equivalente aos submercados** (não calculada — basta
   `df[df['submercado']=='SIN']`). Selectbox: `["SIN", "SE", "S", "NE", "N"]`.
   Default: `"SIN"`.

2. **Granularidades** — agregação em MWmed (média, não soma):
   - Horária: `din_instante` como está (sem resample). Teto 90 dias (spec).
   - Diária: `resample('D')` com `mean()`.
   - Mensal: `resample('MS')` com `mean()` (1º dia do mês, alinhado com PLD
     mensal do CCEE pra consistência entre abas).

3. **Linha de carga** — trace separado do stacked, `dash='dash'`,
   `color='#1A1A1A'`. Hover separado (diferente de stackgroup).

4. **Anotação 29/04/2023** — só aparece se
   `data_ini <= 2023-04-29 <= data_fim`.

5. **KPIs** calculados do `dff` filtrado (mesma janela do gráfico). 4 cards:
   geração total média, % renov variável, térmica média, carga média. Formato
   BR (`fmt_br`, reusável do PLD).

6. **Session keys prefixo `gen_`** (regra CLAUDE.md 3.2).

---

## 9. Pontos abertos (fora da Fase A)

- **Horário de verão pré-2019:** 1 hora/ano missing em 2016-2018
  (começo/fim DST). `resample('D').mean()` absorve isso sem artefato. Deixar
  como está.
- **GD (Geração Distribuída):** não está neste dataset — fica pra data
  loader separado (spec seção 4). Stub estrutural no `load_gd_ons()`.
- **Subtração de GD da carga pós-29/04/2023:** `# TODO` no código quando
  GD for implementado (spec seção 7.2).
- **`val_intercambio`:** capturado pelo loader mas não usado na UI. Útil se
  uma aba futura analisar dependência de importação por submercado.

---

## 10. Referências

- Spec: `docs/aba_geracao_spec.md`
- Scripts: `scripts/inspect_balanco.py`, `scripts/inspect_balanco_smoke.py`
- Análogos: `docs/ena_research.md`, `docs/reservatorios_research.md`
