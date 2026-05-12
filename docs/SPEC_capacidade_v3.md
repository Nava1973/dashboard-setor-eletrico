# SPEC — Aba "Capacidade Instalada (Brasil + MMGD)" v3

**Status**: Final — pronto para implementação
**Versão anterior**: v2 (substituída — mudanças destacadas em §11)
**Autor**: Nava + Claude
**Data**: 12/maio/2026
**Branch de implementação alvo**: `feat/capacidade-instalada`

---

## 1. Objetivo

Criar nova aba no dashboard (`tab_capacidade.py`) com a **evolução mensal da capacidade instalada do Brasil + MMGD**, consolidando:
- **Geração centralizada Brasil**: SIGA (ANEEL) — fonte autoritária do regulador
- **MMGD**: ANEEL bruta (relação de empreendimentos de mini e microgeração distribuída)

Apresentada como série única total + decomposição visual entre as duas componentes.

A aba serve duas funções:
- **Macro**: linha do total Brasil para análise de tendência (cobertura de equity research de empresas do setor).
- **Decomposição**: visualizar o peso crescente da MMGD no parque gerador nacional.

**Decisão estratégica (v3)**: SIGA é fonte principal pela autoridade regulatória da ANEEL (defensibilidade em relatório) + coerência com o restante do dashboard (padrão ANEEL CKAN já estabelecido). ONS entra como validação cruzada silenciosa para capturar eventuais desativações relevantes.

---

## 2. Fontes de dados

### 2.1 SIGA — geração centralizada Brasil (FONTE PRINCIPAL)

- **Dataset**: SIGA - Sistema de Informações de Geração da ANEEL
- **Resource ID CKAN**: `11ec447d-698d-4ab8-977f-b424d5deee6a`
- **Endpoint**: `https://dadosabertos.aneel.gov.br/api/3/action/datastore_search`
- **Atualização**: mensal
- **Escopo**: todo o parque gerador nacional com outorga ANEEL (SIN + sistemas isolados)
- **Granularidade nativa**: 1 linha por empreendimento (~25k linhas)
- **Campo de data**: `DatEntradaOperacao`
- **Campo de capacidade**: `MdaPotenciaOutorgadaKw` (preferencial) ou `MdaPotenciaFiscalizadaKw` (validar na implementação)
- **Filtro obrigatório**: `SitFase = "Operação"` (descarta construção e empreendimentos revogados)
- **Limitação conhecida**: empreendimentos descomissionados saem de `SitFase = "Operação"`, portanto a série representa "capacidade viva hoje, retroprojetada por data de entrada". Subestima levemente histórico (compensado pelo cross-check ONS em §3.5).

### 2.2 MMGD — ANEEL bruta

- **Dataset**: Relação de empreendimentos de Mini e Micro Geração Distribuída
- **Endpoint CKAN**: mesma base ANEEL
- **Resource ID**: `b1bd71e7-d0ad-4214-9053-cbd58e9564a7`
- **Atualização**: contínua (mensal efetiva, com defasagem cadastral de semanas)
- **Granularidade nativa**: 1 linha por empreendimento conectado (vários milhões)
- **Campo de data**: `DataConexao`
  - **Fallback**: se nulo, usar `DthAtualizaCadastralEmpreend`
- **Campo de capacidade**: `MdaPotenciaInstaladaKW` (atenção: `KW` maiúsculo)

### 2.3 ONS Capacidade — cross-check silencioso de centralizada

- **Dataset**: Capacidade Instalada de Geração — ONS Dados Abertos
- **URL portal**: `https://dados.ons.org.br/dataset/capacidade-geracao`
- **Endpoint CKAN**: `https://dados.ons.org.br/api/3/action/datastore_search`
- **Resource ID**: **a confirmar na implementação** (3 candidatos: `a6412542-f2ce-408e-b51d-19a48cc50b62`, `515cc325-6976-4c32-b3bf-48d035b70277`, `03aff81f-4a46-40f3-b076-463458c94356`)
- **Uso**: APENAS validação cruzada silenciosa em background (§3.5)
- **Escopo coberto**: só usinas despachadas pelo ONS — exclui sistemas isolados (~1% do parque). Aceitável como referência de cross-check (não precisa cobrir 100% do universo SIGA, só sinalizar divergências relevantes na centralizada SIN, que é onde estão as empresas listadas).
- **Vantagem do cross-check**: ONS captura desativações via `dat_desativacao` (campo explícito), pegando descomissionamentos que o filtro `SitFase` do SIGA pode mascarar.
- **Campos relevantes**:
  - `dat_entradaoperacao` (DATETIME, não-nulo)
  - `dat_desativacao` (DATETIME, nulo = ativa)
  - `val_potenciaefetiva` (FLOAT, em MW)

### 2.4 EPE PDGD — cross-check silencioso de MMGD

- **Fonte**: `https://dashboard.epe.gov.br/apps/pdgd/`
- **Uso**: validação anual hardcoded da série MMGD (§3.5)
- **Constantes iniciais** (a confirmar no PDGD):
  - dez/2023: ~24,0 GW
  - dez/2024: 36,2 GW
  - dez/2025: 45,0 GW

### 2.5 Premissa de não-sobreposição

SIGA centralizada e MMGD são regimes regulatórios distintos:
- SIGA → empreendimentos com outorga ANEEL (centralizada)
- MMGD → conexões sob REN 1.000/2021 art. 655 (compensação de energia, sem outorga)

**Assume-se ausência de dupla contagem.** Cross-checks via §3.5.

---

## 3. Decisões de design

### 3.1 Janela histórica
- **Início do gráfico**: `2023-01-01`
- **Motivo**: marco regulatório Lei 14.300/2022 (entrou em vigor jan/23), separa fase de "explosão" da MMGD pós-marco legal.
- **Tratamento de capacidade pré-2023**:
  - SIGA: `cumsum` considera todos os empreendimentos com `DatEntradaOperacao < 2023-01`, mas o gráfico só plota a partir de jan/23. O ponto jan/23 representa o **estoque** centralizado inicial.
  - MMGD: idem. Cumsum agrega todas conexões pré-2023; ponto jan/23 = estoque MMGD inicial.

### 3.2 Granularidade de saída
- **1 linha por mês × Brasil agregado**
- Schema final da tabela consolidada:

```
ANO_MES (date, primeiro dia do mês)
CAP_CENTRALIZADA_MW (float, vinda de SIGA)
CAP_MMGD_MW (float, vinda de ANEEL MMGD)
CAP_TOTAL_MW (float, soma das duas)
```

- Unidades: **MW** (converter kW → MW na agregação)
- Capacidade = **estoque acumulado** (cumsum)

### 3.3 Tratamento de desativações

**SIGA**: empreendimentos descomissionados saem da fase "Operação". Como o filtro é `SitFase = "Operação"` aplicado no snapshot atual, a série representa a capacidade **viva hoje, retroprojetada por data de entrada**. Aceitável para v3 — descomissionamentos são raros e pequenos no agregado Brasil. Cross-check ONS (§3.5) captura qualquer divergência relevante.

**MMGD**: sem campo de desativação. Assume-se irreversibilidade (compatível com a realidade do segmento — sistemas FV instalados não saem do cadastro).

### 3.4 Marcador de "mês em consolidação" (proteção contra defasagem cadastral MMGD)

Os últimos 2 meses da série MMGD geralmente vêm subestimados (cadastro ANEEL em backfill):
- Plotar os 2 últimos pontos da componente MMGD com **opacidade reduzida (0.4)**
- Footnote sutil abaixo do gráfico: *"Últimos 2 meses MMGD sujeitos a revisão por defasagem cadastral ANEEL"*

SIGA não precisa de marcador (atualização mensal estável).

### 3.5 Validação cruzada silenciosa (sem overlay visual)

Duas funções rodam em background no carregamento dos dados:

**`_validar_centralizada_vs_ons()`**:
- Compara `CAP_CENTRALIZADA_MW` (SIGA, último mês) vs ONS Capacidade agregado mesmo mês (filtrado para SIN apenas)
- Threshold de alerta: **5%** de divergência
- Esperado: SIGA ≥ ONS (SIGA inclui isolados, ~1% extra)
- Falha silenciosa em caso de match
- **Em caso de divergência significativa**: provável sinal de desativação relevante que o SIGA não capturou — investigar pontualmente

**`_validar_mmgd_vs_epe()`**:
- Compara `CAP_MMGD_MW` em dez/YYYY vs constantes hardcoded EPE
- Threshold de alerta: **5%** de divergência
- Atualização manual anual das constantes quando EPE publicar consolidação

**Em caso de divergência**: `st.warning()` discreto no topo da aba.
Exemplo: *"⚠ Capacidade centralizada abr/2026: SIGA=205,1 GW vs ONS=193,8 GW (divergência 5,8%). Diferença esperada ~1% (isolados). Investigar."*

### 3.6 Sub-abas (futuro, não v3)

v3 não tem sub-abas. Estrutura preparada para iterações futuras:
- "Por fonte" (UHE/UTE/EOL/UFV/Biomassa/MMGD)
- "Por UF" (mapa do Brasil)
- "Adições mensais" (fluxo em vez de estoque)
- **Aba separada "Geração mensal (ONS)"** — registrada como roadmap, fora do escopo desta SPEC

---

## 4. Arquitetura técnica

### 4.1 Arquivos novos

```
data_loader_aneel_siga.py        ← loader SIGA (fonte principal centralizada)
data_loader_aneel_mmgd.py        ← loader MMGD com agregação na ingestão
data_loader_ons_capacidade.py    ← enxuto: APENAS para cross-check de §3.5
tab_capacidade.py                ← UI da aba
docs/SPEC_capacidade_v3.md       ← este documento
```

### 4.2 Padrão de ingestão

**ANEEL (SIGA + MMGD)**:
- Cascata 3-estratégias herdada do projeto: CKAN paginado (`limit=32000`) → `/datastore/dump/` → URL fixa
- `curl_cffi` com `impersonate="chrome"`, headers `BROWSER_HEADERS`

**ONS (`dados.ons.org.br`)**:
- Endpoint CKAN padrão (mesma estrutura da ANEEL)
- Provavelmente menos restritivo que ANEEL — manter `curl_cffi` por padrão
- Fallback: S3 direto (`ons-aws-prod-opendata.s3.amazonaws.com/dataset/capacidade-geracao/...`)

### 4.3 Estratégia de cache (padrão pós-Curtailment)

**Camada disco (`./.cache/`)**:
- `siga_snapshot.parquet` — snapshot bruto SIGA (~25k linhas, leve)
- `mmgd_serie_mensal.parquet` — **já agregado mensalmente** (resultado do `_padronizar_mmgd`)
- `ons_capacidade_snapshot.parquet` — apenas para cross-check (leve)

**Camada RAM (`@st.cache_data`)**:
- `ttl=30 dias` para a série consolidada (estoque histórico não muda retroativamente para meses fechados)
- `_CACHE_VERSION = "v1"` — bump em mudanças de schema

### 4.4 Funções `_padronizar`

**SIGA — leve, processamento direto (~25k linhas)**:
```python
def _padronizar_siga(df):
    df = df[df['SitFase'] == 'Operação'].copy()
    df['DATA'] = pd.to_datetime(df['DatEntradaOperacao'], errors='coerce')
    df['ANO_MES'] = df['DATA'].dt.to_period('M').dt.to_timestamp()
    df['CAP_MW'] = pd.to_numeric(df['MdaPotenciaOutorgadaKw'], errors='coerce') / 1000
    agg = df.groupby('ANO_MES')['CAP_MW'].sum().sort_index()
    return agg.cumsum().rename('CAP_CENTRALIZADA_MW')
```

**MMGD — agregação na ingestão (lição Curtailment OOM)**:
```python
def _padronizar_mmgd(df):
    df['DATA'] = pd.to_datetime(df['DataConexao'], errors='coerce')
    nulos = df['DATA'].isna()
    df.loc[nulos, 'DATA'] = pd.to_datetime(df.loc[nulos, 'DthAtualizaCadastralEmpreend'], errors='coerce')
    df = df.dropna(subset=['DATA'])
    df['ANO_MES'] = df['DATA'].dt.to_period('M').dt.to_timestamp()
    df['CAP_MW'] = pd.to_numeric(df['MdaPotenciaInstaladaKW'], errors='coerce') / 1000
    agg = df.groupby('ANO_MES')['CAP_MW'].sum().sort_index()
    return agg.cumsum().rename('CAP_MMGD_MW')
    # Pós-agregação: ~150 linhas em vez de milhões
```

**ONS — apenas para cross-check (com reconstrução temporal)**:
```python
def _serie_ons_para_validacao(df, mes_ref):
    """Retorna capacidade SIN ativa no mês de referência."""
    df['ENTRADA'] = pd.to_datetime(df['dat_entradaoperacao'], errors='coerce')
    df['DESATIVACAO'] = pd.to_datetime(df['dat_desativacao'], errors='coerce')
    df['CAP_MW'] = pd.to_numeric(df['val_potenciaefetiva'], errors='coerce')
    ativos = (df['ENTRADA'] <= mes_ref) & \
             (df['DESATIVACAO'].isna() | (df['DESATIVACAO'] > mes_ref))
    return df.loc[ativos, 'CAP_MW'].sum()
```

### 4.5 Consolidação

```python
def load_capacidade_consolidada():
    serie_siga = load_siga()                  # fonte principal
    serie_mmgd = load_mmgd()                  # fonte principal MMGD
    df = pd.concat([serie_siga, serie_mmgd], axis=1).fillna(method='ffill').fillna(0)
    df['CAP_TOTAL_MW'] = df['CAP_CENTRALIZADA_MW'] + df['CAP_MMGD_MW']
    df = df[df.index >= '2023-01-01']

    # Cross-checks silenciosos
    _alertas = []
    _alertas.extend(_validar_centralizada_vs_ons(serie_siga))
    _alertas.extend(_validar_mmgd_vs_epe(serie_mmgd))

    return df.reset_index(), _alertas
```

---

## 5. UI / Visualização

### 5.1 Estrutura da aba

```
┌────────────────────────────────────────────────────────┐
│ TÍTULO: CAPACIDADE INSTALADA — BRASIL + MMGD           │ ← Bebas Neue
├────────────────────────────────────────────────────────┤
│ [⚠ alertas de validação cruzada, se houver]            │ ← st.warning condicional
├────────────────────────────────────────────────────────┤
│ [Cap. Total]  [Cap. MMGD]  [% MMGD]  [Crescimento YoY] │ ← métricas Bauhaus
├────────────────────────────────────────────────────────┤
│ [date_input ini]  [date_input fim]  [3M] [12M] [Tudo]  │ ← controles padrão
├────────────────────────────────────────────────────────┤
│                                                        │
│   GRÁFICO PRINCIPAL (Plotly)                           │
│   - Stacked area: Centralizada (cobalt) + MMGD (yellow)│
│   - Linha sobreposta: Total (vermelho fino)            │
│   - Últimos 2 meses MMGD com opacidade reduzida        │
│   - Hover monospace alinhado                           │
│                                                        │
├────────────────────────────────────────────────────────┤
│ Nota: "Últimos 2 meses MMGD sujeitos a revisão por     │
│        defasagem cadastral ANEEL"                      │
├────────────────────────────────────────────────────────┤
│   TABELA — últimos 12 meses                            │
│   .bauhaus-table — Bebas Neue thead + Inter tbody      │
├────────────────────────────────────────────────────────┤
│   [Botão CSV: ;  decimal=,  utf-8-sig]                 │
└────────────────────────────────────────────────────────┘
```

### 5.2 Cores Bauhaus (padrão projeto)
- Centralizada (SIGA): `#1D3557` (cobalt)
- MMGD: `#F6BD16` (amarelo)
- Linha total: `#D62828` (vermelho, espessura 1px)
- Tipografia: Bebas Neue (títulos) + Inter (corpo) + JetBrains Mono (hover)

### 5.3 Métricas calculadas
- **Cap. Total atual**: último valor de `CAP_TOTAL_MW`
- **Cap. MMGD atual**: último valor de `CAP_MMGD_MW`
- **% MMGD do total**: `CAP_MMGD_MW / CAP_TOTAL_MW * 100`
- **Crescimento YoY**: `(atual - 12m atrás) / 12m atrás * 100`

### 5.4 Controles de período
Reaproveitar padrão validado (PLD/Curtailment):
- `date_input` como single source of truth em `session_state['cap_data_ini'/'cap_data_fim']`
- Atalhos `3M`, `12M`, `Tudo` (sem `st.radio`)
- Validar `data_ini > data_fim` com `st.error + st.stop()`

---

## 6. Modo DEMO

Compatibilidade com `DEMO_MODE=1`:
- Gerar série sintética 2023-01 → mês corrente
- Centralizada: começa em 200.000 MW, crescimento ~0,3% a.m.
- MMGD: começa em 17.000 MW, crescimento ~2,5% a.m.

---

## 7. Riscos e mitigações

| Risco | Probabilidade | Mitigação |
|---|---|---|
| OOM na ingestão MMGD inicial | Média-Alta | Paginação CKAN com `limit=32000`, agregação incremental, parquet final apenas agregado |
| `DataConexao` muito esparso em registros antigos | Média | Fallback para `DthAtualizaCadastralEmpreend` |
| Resource ID ONS errado (3 candidatos) | Média | Testar os 3 na primeira execução, escolher o que tem dados mais recentes |
| Schema SIGA mudar | Baixa | Normalização por keyword UPPER, não por exact match |
| Akamai bloqueio em produção ANEEL | Baixa | `curl_cffi` já validado em outros loaders do projeto |
| Dupla contagem SIGA + MMGD | Baixa | Premissa documentada §2.5, cross-checks §3.5 |
| Desativações não capturadas no SIGA | Baixa-Média | Cross-check silencioso vs ONS (§3.5) sinaliza divergências |

---

## 8. Checklist de implementação

- [ ] `data_loader_aneel_siga.py` — função `load_siga()` + cache
- [ ] `data_loader_aneel_mmgd.py` — função `load_mmgd()` + agregação na ingestão
- [ ] `data_loader_ons_capacidade.py` — versão enxuta, só para `_serie_ons_para_validacao()`
- [ ] Funções `_validar_*` (cross-checks silenciosos)
- [ ] Função consolidadora `load_capacidade_consolidada()`
- [ ] Modo DEMO sintético
- [ ] `tab_capacidade.py` — UI completa com stacked area + linha total
- [ ] Marcador visual nos últimos 2 meses MMGD (opacidade 0.4)
- [ ] Renderização condicional de `st.warning` em caso de divergência cross-check
- [ ] Registrar aba no `app.py`
- [ ] CSS scoping `.st-key-` para controles desta aba
- [ ] Teste local (Windows): `python -m streamlit run app.py`
- [ ] Push GitHub Web → deploy Streamlit Cloud
- [ ] `Ctrl+Shift+R` pra bypass cache navegador
- [ ] Atualizar `CLAUDE.md` Seção 5 com decisões finais
- [ ] Atualizar `CLAUDE.md` Seção 7 com histórico

---

## 9. Pendências para resolução durante implementação

1. **SIGA — campo de capacidade**: `MdaPotenciaOutorgadaKw` ou `MdaPotenciaFiscalizadaKw`? Default: outorgada.
2. **SIGA — valor exato de `SitFase`**: testar `"Operação"`, `"OPERACAO"`, etc.
3. **Resource ID ONS correto**: testar `a6412542-...`, `515cc325-...`, `03aff81f-...` e escolher o de dados mais recentes.
4. **EPE — valores exatos das constantes hardcoded**: extrair do PDGD os números de dez/2023 e dez/2024 (dez/2025 = 45 GW já confirmado).

---

## 10. Roadmap pós-v3 (não implementar agora)

Registrado para futuras sessões:
- Sub-aba "Por fonte" (decomposição UHE/UTE/EOL/UFV/MMGD)
- Sub-aba "Por UF" (mapa do Brasil)
- Sub-aba "Adições mensais" (delta em vez de cumsum)
- **Aba separada "Geração mensal por fonte (ONS)"** — fonte: ONS, página `geracao_energia.aspx`

---

## 11. Diff vs SPEC v2 (mudanças nesta v3)

| Tópico | v2 | v3 |
|---|---|---|
| Fonte principal centralizada | ONS Capacidade Geração | **SIGA (ANEEL)** |
| ONS Capacidade | Fonte principal | **Cross-check silencioso** |
| Escopo geográfico | SIN apenas (~99% do parque) | **Brasil completo (SIN + isolados)** |
| Defensibilidade em relatório | ONS (operador) | **ANEEL (regulador)** |
| Tratamento de desativações | Explícito via `dat_desativacao` | Implícito via `SitFase` + sinalização via cross-check ONS |
| Série histórica | "Verdadeira" (reconstrução) | "Viva hoje retroprojetada" (limitação aceita) |
| Cross-check centralizada | SIGA validava ONS | **ONS valida SIGA (inverso)** |
| Coerência com projeto | Nova fonte ONS | **Mantém padrão ANEEL CKAN do projeto** |
| Nome da aba | "Capacidade Instalada (SIN + MMGD)" | **"Capacidade Instalada (Brasil + MMGD)"** |
