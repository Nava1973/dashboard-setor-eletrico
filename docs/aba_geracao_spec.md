# Spec: Aba de Geração de Energia (ONS)

> **Para o Claude Code:** Este documento especifica a implementação da aba "Geração" do dashboard.
> Leia também os arquivos existentes do projeto (especialmente os `data_loader` e as abas de PLD já implementadas)
> para seguir os padrões arquiteturais, de estilo e de normalização já estabelecidos.

---

## 1. Contexto e objetivo

### 1.1. O que é esta aba
Visualizar a **geração de energia elétrica do SIN** (Sistema Interligado Nacional) decomposta por **fonte**,
com visão nacional e por submercado, em três granularidades temporais: **mensal, diária e horária**.

O gráfico principal é um **stacked area chart** (área empilhada), com a **linha de carga** sobreposta para contextualizar a oferta vs. demanda.

### 1.2. Perguntas que a aba responde
- Como o mix de geração brasileiro está evoluindo ao longo do tempo?
- Qual a diferença estrutural entre os submercados (SE/CO, S, NE, N)?
- Quando ocorre a "curva de pato" (queda de geração solar no fim de tarde e rampa de hidro/térmica)?
- Quanto a GD já representa da oferta nacional?

### 1.3. Fora do escopo desta aba (ficará em abas futuras)
- Curtailment de eólica/solar por ativo (próxima aba)
- Análise por grupo econômico
- Spread, ENA/MLT, reservatórios, tarifas ANEEL

---

## 2. Stack e padrões do projeto (já existentes — seguir)

- **Framework:** Streamlit (deploy em Streamlit Community Cloud)
- **Visualização:** Plotly
- **Dados:** pandas
- **Ingestão HTTP:** `curl_cffi` com `impersonate="chrome"` (padrão usado no CCEE — obrigatório porque o ONS também fica atrás de CDN com fingerprinting)
- **Arquitetura modular:** um `data_loader` por fonte de dados
- **Design system:** Bauhaus (ver seção 6)
- **Idioma:** Português (pt-BR) em toda a UI; números no formato BR (`.` milhar, `,` decimal); datas `DD/MM/YYYY`

**IMPORTANTE:** Antes de começar, examine os arquivos `data_loader_ccee_pld_*.py` (ou equivalente) e a aba de PLD
para reaproveitar:
- Cabeçalhos HTTP (`BROWSER_HEADERS`)
- Padrão de tratamento de erros (`st.session_state['_debug_erros']`)
- Normalização de submercado (SE/CO, S, NE, N)
- Patterns de cache com `@st.cache_data`

---

## 3. Fonte de dados primária: Balanço de Energia nos Subsistemas (ONS)

### 3.1. Identificação
- **Dataset:** `balanco-energia-subsistema` no portal `dados.ons.org.br`
- **Descrição oficial:** "Informações da carga e oferta de energia verificados em periodicidade horária por subsistema.
  A oferta é representada pelos valores de geração das usinas hidráulicas, térmicas, eólicas e fotovoltaicas, em MWmed."
- **Licença:** CC-BY
- **Atualização:** diária, 12h e 19h (horário de Brasília)
- **Histórico disponível:** 2000 até ano corrente

### 3.2. URLs de download (padrão estável anual)

Template direto no S3 público do ONS:
```
https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/balanco_energia_subsistema_ho/BALANCO_ENERGIA_SUBSISTEMA_{ANO}.{ext}
```

Onde `{ANO}` vai de 2000 ao ano corrente (ex.: `2026`) e `{ext}` pode ser `csv`, `xlsx` ou `parquet`.

**Recomendação forte: usar `parquet`.**
- Arquivos ~10x menores que CSV
- Tipagem preservada (datetime, float, string)
- Leitura direta com `pd.read_parquet(url)` — mais rápido e menos propenso a erros de parsing
- Fallback para CSV caso parquet falhe

### 3.3. Schema esperado (confirmar na primeira execução — ver seção 9)

Colunas esperadas (baseado no dicionário do ONS — **validar dinamicamente no loader**):

| Campo esperado | Tipo | Descrição |
|---|---|---|
| `nom_subsistema` ou `id_subsistema` | string | Nome/ID do subsistema (SE, S, NE, N) |
| `din_instante` | datetime | Timestamp horário (fuso BRT) |
| `val_gerhidraulica` | float | Geração hidráulica (MWmed) |
| `val_gertermica` | float | Geração térmica — inclui nuclear e biomassa (MWmed) |
| `val_gereolica` | float | Geração eólica (MWmed) |
| `val_gerfotovoltaica` | float | Geração solar centralizada (MWmed) |
| `val_carga` ou `val_cargaenergiamwmed` | float | Carga verificada (MWmed) |

**Padrão defensivo:** normalizar nomes de colunas (`.lower()` + identificar por keyword), igual ao já feito no CCEE.
Por exemplo: `col for col in df.columns if 'hidra' in col.lower()`.

### 3.4. Normalização de submercado

Mapear para padrão canônico do dashboard (o mesmo já usado no PLD):
```python
SUBMERCADO_MAP = {
    'SE': 'SE/CO',
    'SUDESTE': 'SE/CO',
    'CO': 'SE/CO',
    'SE/CO': 'SE/CO',
    'SUDESTE/CO': 'SE/CO',
    'S': 'S',
    'SUL': 'S',
    'NE': 'NE',
    'NORDESTE': 'NE',
    'N': 'N',
    'NORTE': 'N',
}
```

---

## 4. Fonte de dados secundária: GD mensal (ONS)

### 4.1. Por que separar
A Geração Distribuída **não** aparece no dataset `balanco_energia_subsistema`. Ela vem:
- Estimada (não medida) pelo ONS a partir de dados meteorológicos
- Em granularidade mensal
- Já incorporada à série de **carga** do ONS a partir de **29/04/2023** (ver seção 7 — quebra metodológica)

### 4.2. Implementação
Criar um `data_loader_ons_gd.py` **separado**, a ser implementado em etapa posterior.
Por ora, a aba deve funcionar **sem GD**, com um espaço reservado no stacked (faixa de GD desabilitável via toggle).

Para a primeira entrega: **implementar apenas o `balanco_energia_subsistema`** e deixar a estrutura
pronta para receber GD como uma 5ª faixa no topo do stacked.

---

## 5. Requisitos funcionais

### 5.1. Estrutura de navegação dentro da aba

```
[Aba Geração]
  ├─ Seletor de granularidade: Mensal | Diária | Horária
  ├─ Seletor de submercado: SIN | SE/CO | S | NE | N
  ├─ Seletor de período: date_input de/até + atalhos (7d, 30d, 90d, 1A, 5A, Máx)
  ├─ [Gráfico principal] Stacked area de geração por fonte + linha de carga
  ├─ [Métricas resumo] Cards com: geração total média, participação de renováveis (eólica+solar),
  │   geração térmica média, carga média
  └─ [Botão] Exportar CSV do período selecionado
```

### 5.2. Empilhamento (ordem base → topo)

1. **Térmica** (inclui nuclear + biomassa) — base, preto
2. **Hidro** — azul cobalto
3. **Eólica** — cinza
4. **Solar centralizada** — amarelo
5. **GD** — vermelho (topo, faixa reservada para etapa 2)

### 5.3. Regras de agregação por granularidade

| Granularidade | Agregação temporal | Agregação espacial (SIN) |
|---|---|---|
| Horária | Média horária (mantém horas) | Soma dos 4 submercados |
| Diária | Média das 24h do dia | Soma dos 4 submercados |
| Mensal | Média de todas as horas do mês | Soma dos 4 submercados |

Todos os valores ficam em **MWmed**. Nunca converter para MWh nesta aba.

### 5.4. Filtro de período — comportamento

Seguir o mesmo padrão já validado do PLD:
- `st.date_input` é a fonte única de verdade (`st.session_state['data_ini']`, `st.session_state['data_fim']`)
- Botões de atalho (7d/30d/90d/1A/5A/Máx) **atualizam** `session_state` e chamam `st.rerun()`
- Validar `data_ini <= data_fim` com `st.error()` + `st.stop()`
- Se `dataset_max` mudar, resetar state

**Atenção à granularidade horária:**
- Limitar automaticamente o período máximo a **90 dias** quando horária está selecionada (evita estouro de memória)
- Mostrar `st.warning` se o usuário pedir mais

### 5.5. Métricas de resumo (cards)

Quatro cards no topo ou abaixo do gráfico:
1. **Geração total média** no período (MWmed)
2. **% renovável variável** (eólica + solar + GD) / geração total
3. **Térmica média** (MWmed) — contexto de "o quanto o sistema está acionando térmica"
4. **Carga média** (MWmed)

Todos formatados em BR: `52.341 MWmed`, `23,4%`.

### 5.6. Export CSV

Formato Excel-friendly BR (mesmo padrão já usado no PLD):
- Pivot long → wide (uma coluna por fonte)
- `to_csv(sep=";", decimal=",", index=False)`
- Encoding `utf-8-sig`
- Nome do arquivo: `geracao_{granularidade}_{submercado}_{dataini}_a_{datafim}.csv`

---

## 6. Design system — Bauhaus (já aprovado no projeto)

### 6.1. Paleta (reuso do PLD)
```
Vermelho:      #D62828
Amarelo:       #F6BD16
Azul cobalto:  #1D3557
Preto:         #1A1A1A
Creme:         #F5F1E8
Cinza:         #6B6B6B
```

### 6.2. Cores das fontes de geração (decisão desta aba)
```
Térmica:  #1A1A1A  (preto)
Hidro:    #1D3557  (azul cobalto)
Eólica:   #9B9B9B  (cinza médio — contrasta com #6B6B6B usado em outros contextos)
Solar:    #F6BD16  (amarelo Bauhaus)
GD:       #D62828  (vermelho — destaque, "o novo")
```

### 6.3. Linha de carga
Cor: `#1A1A1A` preto com `dash='dash'`, espessura 2px.
**Não** usar cor do submercado — a carga é sempre preto tracejado, para ser visualmente distinta do stacked.

### 6.4. Tipografia
- Títulos: Bebas Neue, UPPERCASE
- Corpo: Inter
- Hover do Plotly: `JetBrains Mono` ou `Courier New` (monospace, alinhamento correto — ver pattern já usado no PLD)

### 6.5. Hover
- Formato BR com `.replace('.', ',')` manual para decimal
- Submercados com `.ljust(2)` + 4 `&nbsp;` separadores
- `hovermode='x unified'`

### 6.6. Estilo do gráfico
- Sem border-radius (Bauhaus)
- Fundo creme `#F5F1E8`
- Grid fino cinza
- Eixo Y em MWmed, formatado BR

---

## 7. Tratamento da quebra metodológica da carga (29/04/2023)

**Fato:** A partir de 29/04/2023, a série de carga do ONS passou a incluir a estimativa de MMGD
(micro e minigeração distribuída). Antes dessa data, a carga era "líquida de GD" (só o que passava pelo fio).

### 7.1. Implementação escolhida (Opção 1 — anotar visualmente)

No gráfico, quando o período selecionado **cruzar** 29/04/2023:
1. Adicionar `fig.add_vline(x='2023-04-29', line_dash='dot', line_color='#6B6B6B')`
2. Adicionar `fig.add_annotation(...)` com o texto: **"ONS passa a incluir MMGD na carga"**
3. Posição da anotação: topo do gráfico, fonte pequena (10px), cor cinza

Não alterar os dados de carga — apenas sinalizar a quebra.

### 7.2. Ao implementar GD (etapa 2)
Aí sim faz sentido revisitar: pode ser necessário "subtrair" GD da carga pós-2023 para reconstruir
uma série consistente. Deixar comentário `# TODO: revisitar quando GD for implementada` no código.

---

## 8. Arquitetura de arquivos

Seguir estrutura modular do projeto. Criar:

```
data_loaders/
  data_loader_ons_balanco_subsistema.py     # NOVO (esta entrega)
  data_loader_ons_gd.py                     # Stub vazio para etapa 2

tabs/
  tab_geracao.py                            # NOVO (esta entrega)

utils/
  (reaproveitar helpers já existentes — ex.: formatação BR, normalização submercado)
```

E registrar `tab_geracao.py` no `app.py` como nova aba, entre as abas existentes na posição apropriada.

---

## 9. Passos de implementação sugeridos

### Passo 1 — Data loader (`data_loader_ons_balanco_subsistema.py`)

```python
# Pseudo-código / estrutura esperada

URL_TEMPLATE = "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/balanco_energia_subsistema_ho/BALANCO_ENERGIA_SUBSISTEMA_{ano}.{ext}"

@st.cache_data(ttl=3600*6, show_spinner=False)
def carregar_balanco_ons(ano_inicio=2000, ano_fim=None):
    """
    Baixa e consolida dados anuais do ONS.
    Tenta parquet primeiro, fallback para CSV.
    Usa curl_cffi com impersonate=chrome.
    """
    # 1. Definir anos a baixar
    # 2. Para cada ano: tentar parquet -> fallback CSV
    # 3. Concatenar DataFrames
    # 4. Normalizar nomes de colunas
    # 5. Normalizar submercado (usar SUBMERCADO_MAP)
    # 6. Converter tipos (din_instante -> datetime, val_* -> float)
    # 7. dropna em campos críticos
    # 8. Retornar DataFrame long:
    #    colunas: [din_instante, submercado, fonte, mwmed, carga]
    #    OU wide: [din_instante, submercado, val_hidro, val_termica, val_eolica, val_solar, val_carga]
    pass
```

**Decisão de schema de retorno:** manter **wide** (uma coluna por fonte) para facilitar o stacked do Plotly.
Converter para long apenas se necessário no export CSV.

### Passo 2 — Agregações (helper)

Função `agregar_por_granularidade(df, granularidade, submercado)`:
- Filtra submercado (ou soma tudo se "SIN")
- Resample temporal: `'h'`, `'D'`, `'ME'` (mês)
- Método: **média** (MWmed é grandeza de potência média, não soma)

### Passo 3 — Layout da aba (`tab_geracao.py`)

```python
def render_tab_geracao():
    st.title("GERAÇÃO DE ENERGIA")
    st.markdown("Fonte: ONS — Balanço de Energia nos Subsistemas. Atualização diária.")

    # Controles (colunas)
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        granularidade = st.radio("Granularidade", ["Mensal", "Diária", "Horária"], horizontal=True)
    with col2:
        submercado = st.selectbox("Subsistema", ["SIN", "SE/CO", "S", "NE", "N"])
    with col3:
        # Period selector (date_input + atalhos) — reusar pattern do PLD
        data_ini, data_fim = render_period_selector(granularidade)

    # Carga de dados
    df = carregar_balanco_ons()
    df_filtrado = agregar_por_granularidade(df, granularidade, submercado)
    df_filtrado = df_filtrado[(df_filtrado['din_instante'] >= data_ini) & (df_filtrado['din_instante'] <= data_fim)]

    # Métricas
    render_metricas(df_filtrado)

    # Gráfico principal
    fig = build_stacked_area(df_filtrado, granularidade, submercado, data_ini, data_fim)
    st.plotly_chart(fig, use_container_width=True)

    # Export
    render_export_csv(df_filtrado, granularidade, submercado)
```

### Passo 4 — Gráfico principal (`build_stacked_area`)

- `go.Figure()` com `go.Scatter(stackgroup='one', fill='tonexty')` para cada fonte
- Ordem: Térmica (primeiro) → Hidro → Eólica → Solar → GD (quando existir)
- Linha de carga: `go.Scatter(mode='lines', line=dict(dash='dash', color='#1A1A1A', width=2))`
- Anotação de 29/04/2023 quando aplicável (seção 7)
- Hover unificado, fonte monospace, formato BR

---

## 10. Critérios de aceitação (checklist)

Funcional:
- [ ] Aba carrega em menos de 5s na primeira vez (posterior: cache hit instantâneo)
- [ ] Seletores de granularidade / submercado / período funcionam sem erro
- [ ] Gráfico stacked renderiza com as 4 fontes (Térmica, Hidro, Eólica, Solar) nas cores corretas
- [ ] Linha de carga aparece tracejada em preto por cima do stacked
- [ ] Anotação de 29/04/2023 aparece quando o período selecionado atravessa essa data
- [ ] Horária limitada a 90 dias; warning aparece se usuário tentar mais
- [ ] SIN = soma dos 4 submercados (validar numericamente com submercados individuais)
- [ ] Export CSV baixa arquivo corretamente, abre bem no Excel BR
- [ ] Métricas corretas (validar amostra manual: um mês de 2024)

Visual:
- [ ] Paleta Bauhaus aplicada
- [ ] Tipografia Bebas Neue + Inter
- [ ] Hover formatado em português e números BR
- [ ] Sem border-radius em elementos

Código:
- [ ] `data_loader` segue padrão do CCEE (3 estratégias + `curl_cffi`)
- [ ] Erros capturados em `st.session_state['_debug_erros']` — nunca silenciosos
- [ ] `@st.cache_data` aplicado na carga pesada
- [ ] Módulos separados conforme seção 8

---

## 11. Validações numéricas (smoke test)

Após implementar, validar estes números conhecidos (consultar fontes externas se precisar):

- **Geração média SIN em 2024** deve estar em torno de **75-80 GWmed**
- **Carga média SIN em 2024** deve estar em torno de **75-80 GWmed** (bate com geração ± intercâmbio internacional)
- **Participação solar+eólica em 2024** no SIN: ordem de **22-25%**
- **NE 2024**: geração eólica+solar chega perto de **80%** da geração do submercado em vários meses
- **Sul 2024**: participação térmica maior que a média nacional (carvão + gás)

Se os números derem fora dessas faixas, há erro na agregação ou na normalização de submercado.

---

## 12. Como usar esta spec com o Claude Code

1. Salve este arquivo no repositório em `docs/aba_geracao_spec.md`
2. Commit no GitHub
3. No Claude Code, rode:
   ```
   Leia docs/aba_geracao_spec.md e implemente a aba de Geração seguindo essa spec.
   Antes de começar, examine os arquivos existentes (data_loaders e abas já implementadas)
   para reaproveitar padrões. Me mostre seu plano antes de começar a codar.
   ```
4. Deixe o Claude Code propor o plano, valide, e só então deixe ele implementar.
5. Itere o resultado no app rodando local (`python -m streamlit run app.py`).

---

## 13. Etapas futuras (fora desta entrega)

- **Etapa 2:** Implementar `data_loader_ons_gd.py` e adicionar GD ao stacked
- **Etapa 3:** Pequenos múltiplos — 4 mini stacked areas lado a lado (um por submercado)
- **Etapa 4:** Revisitar quebra de 29/04/2023 ao implementar aba de Carga
- **Etapa 5:** Aba de curtailment (datasets de restrição + `geracao_usina_2`)

