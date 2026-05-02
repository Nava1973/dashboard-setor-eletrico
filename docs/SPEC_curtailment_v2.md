# SPEC v2 — Curtailment por Unidade Geradora e por Grupo Econômico

**Projeto:** `Nava1973/dashboard-setor-eletrico`
**Aba:** Curtailment
**Data:** 2026-05-02
**Status:** aprovada, calibrada com código existente, pronta para implementação

> **Nota:** esta é a v2, calibrada após inspeção do código atual. Substitui a v1.
> Diferenças principais: nomes de colunas alinhados ao código real, cores das razões
> conforme constantes do projeto, decisão sobre períodos fixos vs presets registrada.

---

## 1. Contexto

A aba Curtailment em `components/tab_curtailment.py` já tem 3 sub-abas instanciadas
em `st.tabs(["Visão geral", "Por usina", "Por grupo"])`. Apenas "Visão geral" está
implementada. As outras duas estão como `_placeholder_em_construcao()`.

Esta spec descreve a implementação de:
- `_render_por_usina(df_filtrado)` — Visão (1)
- `_render_por_grupo(df_filtrado)` — Visão (2)

**O que NÃO está no escopo:** mudanças na Visão Geral, mudanças no pipeline de
ingestão, mudanças no framework de presets globais, mudanças em `data_loader_grupos_excel.py`.

---

## 2. O que o pipeline já entrega (df_filtrado)

Quando `_render_por_usina(df_filtrado)` ou `_render_por_grupo(df_filtrado)` é
chamado, recebe um DataFrame **já rateado e filtrado por fonte**, com colunas:

| Coluna | Tipo | Descrição |
|---|---|---|
| `USINA` | str | nome cru do ONS (não usar pra display) |
| `NOME_USINA_DASH` | str | nome amigável (usar pra display) |
| `PROPRIETARIO` | str | grupo econômico; "Other (sem mapeamento)" para sem-match |
| `DATA` | `datetime.date` | dia (granularidade diária; horária descartada por OOM) |
| `RAZAO` | str/None | "ENE" / "CNF" / "REL" / "PAR" / None |
| `FONTE` | str | "EOLICA" ou "SOLAR" (filtrada — nunca ambos no mesmo df) |
| `SUBMERCADO` | str/None | SE/S/NE/N |
| `UF` | str/None | sigla da UF |
| `FRUSTRADO_MWH` | float | **já multiplicado por PARTICIPACAO_RATEIO** |
| `OUTPUT_MWH` | float | **já multiplicado por PARTICIPACAO_RATEIO** |
| `PARTICIPACAO_RATEIO` | float | 0..1 (informativo; 1.0 nos sem-match e únicos) |

**Pegadinhas:**
- Cardinalidade explodida pelo rateio: 1 usina com 2 sócios 50/50 vira 2 linhas no
  mesmo dia, com FRUSTRADO/OUTPUT já divididos. Soma por dimensão (USINA, PROPRIETARIO)
  continua correta.
- `DATA_HORA` não existe mais. Granularidade horária é impossível sem mexer no loader.
- Colunas brutas do ONS (GERACAO_MW, GERACAO_REF_MW, etc.) foram descartadas no groupby
  diário. Só sobra o que está na tabela acima.

---

## 3. Funções utilitárias a reutilizar (utils_curtailment.py)

**Obrigatório usar essas, não reimplementar:**

### `calcular_pct_curtailment(df) -> dict`
Retorna `{pct_total, pct_ene, pct_cnf, pct_rel}` aplicando a fórmula canônica:

```
denom = sum(OUTPUT_MWH) + sum(FRUSTRADO_MWH)   # geração potencial
pct_X = sum(FRUSTRADO_MWH onde RAZAO=X) / denom
```

Garante que `pct_ene + pct_cnf + pct_rel == pct_total` (PAR excluído por default).

### `agregar_por_dimensao(df, dimensoes=[...])`
Agrega um df por uma ou mais dimensões (`PROPRIETARIO`, `NOME_USINA_DASH`, `UF`, etc.)
e calcula os pcts por bucket.

**Regra:** sempre que precisar do `%` em qualquer recorte, ir por essas funções.
Não fazer `sum(FRUSTRADO)/sum(OUTPUT)` à mão — denominador correto é
`sum(OUTPUT) + sum(FRUSTRADO)`, não só `sum(OUTPUT)`.

---

## 4. Constantes canônicas (já no código)

### Cores e labels das razões

```python
# em components/tab_curtailment.py:68-80
CORES_RAZAO = {
    "ENE": "#D62828",  # vermelho Bauhaus
    "CNF": "#F6BD16",  # amarelo Bauhaus
    "REL": "#2A6F97",  # azul Bauhaus
    "PAR": "#1A1A1A",  # preto (excluído por default)
}
LABELS_RAZAO = {
    "ENE": "Energético",
    "CNF": "Confiabilidade",
    "REL": "Elétrico",
    "PAR": "Parecer Acesso",
}
RAZOES_OPERATIVAS = ["ENE", "CNF", "REL"]  # PAR fora
```

**Reusar essas constantes literalmente.** Não criar paleta paralela.

---

## 5. Decisão de UX — Períodos fixos vs presets

**Sub-abas (1) e (2):**
- 3 colunas de período fixas, calculadas a partir de `max_d = df_filtrado['DATA'].max()`
- Sem UI de seleção de período
- Períodos:
  - **Mês corrente:** 1º dia do mês de `max_d` até `max_d` (parcial)
  - **Mês anterior:** mês completo anterior ao de `max_d`
  - **Penúltimo mês:** mês completo dois meses antes do de `max_d`

**Drill-down (clique numa unidade/grupo):**
- Abre Visão Geral filtrada
- Mantém presets adaptativos atuais (30D / 90D / 6M / 12M / Máx) **sem alteração**
- Toggle de granularidade e fonte continuam funcionando como hoje

**Justificativa:** dois contextos de uso diferentes (comparação multi-entidade vs
análise profunda de uma entidade) pedem UIs diferentes. Não unificar.

---

## 6. Visão (1) — `_render_por_usina(df_filtrado)`

### 6.1 Layout

Tabela com colunas:

| `NOME_USINA_DASH` | `PROPRIETARIO` | Mês corrente | Mês anterior | Penúltimo |
|---|---|---|---|---|

Linhas: uma por unidade geradora presente no df_filtrado.

### 6.2 Controles próprios da sub-aba

- **Seletor de razão:** radio horizontal `[Total] [Energético] [Confiabilidade] [Elétrico]`
  - Default: Total
  - Controla qual `pct_X` aparece nas células das 3 colunas de período

### 6.3 Ordenação

Decrescente pelo % do mês corrente, segundo o seletor de razão ativo.

### 6.4 Hover (tooltip rico)

Ao passar o mouse sobre qualquer célula numérica, mostrar tabela maior:

```
┌──────────────────────────────────────────────┐
│ ARACATI II  ·  CPFL                           │  Bebas Neue, cobalt
│ Mês corrente · 01–02/mai/2026                 │  Inter, gray
├──────────────────────────────────────────────┤
│                       %        MWh            │
│ Total              4,2%      4.180            │  bold
│ ─────────────────────────────────────         │
│ ▮ Energético       2,1%      2.090            │  vermelho #D62828
│ ▮ Confiabilidade   1,1%      1.095            │  amarelo #F6BD16
│ ▮ Elétrico         1,0%        995            │  azul    #2A6F97
└──────────────────────────────────────────────┘
```

Largura ~280px, fonte JetBrains Mono nas colunas numéricas, borda preta 2px,
fundo cream `#F5F1E8`, sem border-radius. À direita da célula com fallback à
esquerda. Delay 200–300ms.

**Restrições técnicas (decisões prévias do projeto):**
- HTML puro via `st.markdown(unsafe_allow_html=True)`, NÃO `st.dataframe`
- NÃO usar `:has()` (congela o app)
- `:hover` direto no `<tr>` ou `<td>`, posição `absolute` com fallback

### 6.5 Click numa unidade

Atualiza `st.session_state['curtailment_view']` para `'detalhe_unidade'` e
`st.session_state['curtailment_unidade_selecionada']` com o `NOME_USINA_DASH`,
seguido de `st.rerun()`.

A view `detalhe_unidade` invoca a Visão Geral filtrada por aquela unidade
(vide §8).

### 6.6 Edge cases

- Unidades com `PROPRIETARIO = "Other (sem mapeamento)"`: aparecem normalmente.
  Coluna PROPRIETARIO mostra "Outros / Não classificado".
- Unidades sem dado em algum dos 3 períodos: célula mostra `—` (não 0%).

---

## 7. Visão (2) — `_render_por_grupo(df_filtrado)`

### 7.1 Layout

Tabela com colunas:

| `PROPRIETARIO` | Mês corrente | Mês anterior | Penúltimo |
|---|---|---|---|

Cada linha é um grupo agregado.

### 7.2 Estrutura visual em 2 zonas (sem header explícito)

**Zona 1 — Listadas em bolsa**, sempre no topo, ordenadas por % do mês corrente
decrescente.

Mapeamento `PROPRIETARIO` (Excel) → label exibido + presença por fonte:

| `PROPRIETARIO` no Excel | Label exibido | Eólica | Solar |
|---|---|---|---|
| `Auren` | Auren | ✅ | ✅ |
| `Engie` | Engie | ✅ | ✅ |
| `CPFL` | CPFL | ✅ | ❌ |
| `EQTL (Echo)` | **Equatorial** | ✅ | ✅ |
| `Copel` | Copel | ✅ | ❌ |
| `Alupar` | Alupar | ✅ | ✅ |
| `Neoenergia` | Neoenergia | ✅ | ✅ |
| `Eneva` | Eneva | ❌ | ✅ |

**Regra de exibição:** quando o grupo não tem ativos na fonte selecionada,
**suprimir da tabela** (não mostrar linha com zeros).

**Linha divisória forte** (não um header) separa zona 1 da zona 2.

**Zona 2 — Demais grupos**, ordenados por % do mês corrente decrescente.

**Posição final fixa:** `Other (sem mapeamento)` sempre na última posição,
fora da ordenação. Label exibido: "Outros / Não classificado", em cinza sutil.
Inclui os casos de rateio "other Cos." que recaem no mesmo balde.

### 7.3 Controles próprios

Mesmo seletor de razão da Visão (1).

### 7.4 Hover (tooltip rico)

Mesmo modelo da Visão (1), composição agregada do grupo inteiro.

### 7.5 Expansão inline (chevron)

Cada linha de grupo tem chevron `▸` na ponta esquerda da primeira coluna.

- **Click no nome do grupo** → drill-down (vide §8)
- **Click no chevron** → expande inline na tabela uma sub-tabela das usinas:

```
▾ Engie            3,1%   2,8%   3,2%
    └ Caetité         BA   100%   4,1%   1.230 MWh
    └ Cassilândia     MS   100%   3,5%     980 MWh
    └ Lar do Sol      MG    40%   2,8%     650 MWh
    └ ...
▸ CPFL             1,8%   2,0%   1,7%
```

Apenas mês corrente nas filhas (não os 3 períodos). Indentação leve, fundo cinza
claríssimo, fonte Inter 1pt menor. Múltiplos grupos podem ficar expandidos
simultaneamente. Toggle via JS sem `:has()`.

### 7.6 Click num grupo

Atualiza `st.session_state['curtailment_view']` para `'detalhe_grupo'` e
`st.session_state['curtailment_grupo_selecionado']`, seguido de `st.rerun()`.

---

## 8. Drill-down — Visão Geral filtrada

### 8.1 Abordagem: extrair função reutilizável

Refatorar a `_render_visao_geral` atual para aceitar filtro opcional:

```python
def _render_visao_geral(
    df: pd.DataFrame,
    *,
    filtro_unidade: Optional[str] = None,    # NOME_USINA_DASH
    filtro_grupo: Optional[str] = None,      # PROPRIETARIO
    titulo_contexto: Optional[str] = None,   # ex: "Engie · Eólica"
) -> None:
    if filtro_unidade is not None:
        df = df[df['NOME_USINA_DASH'] == filtro_unidade]
    elif filtro_grupo is not None:
        df = df[df['PROPRIETARIO'] == filtro_grupo]
    # resto da lógica atual permanece igual
```

Validar: apenas um dos dois filtros pode ser não-nulo.

### 8.2 UI no modo drill-down

- Breadcrumb/badge no topo: `Curtailment › Por grupo › Engie (Eólica)`
- Botão de voltar: `← Voltar para tabela de grupos`
  - Reseta `curtailment_view` para `'tabela_grupos'` (ou `'tabela_unidades'`) e `st.rerun()`
- Comportamento dos presets de período (30D/90D/6M/12M/Máx): **idêntico ao atual**

### 8.3 State machine

```
st.session_state['curtailment_view'] ∈ {
    'geral',              # default, sem filtro (modo atual)
    'tabela_unidades',    # sub-aba "Por usina"
    'tabela_grupos',      # sub-aba "Por grupo"
    'detalhe_unidade',    # drill-down de unidade
    'detalhe_grupo',      # drill-down de grupo
}
```

**Decisão:** as sub-abas "Por usina" e "Por grupo" do `st.tabs` ainda existem.
O drill-down NÃO muda de sub-aba — sobrepõe o conteúdo da sub-aba atual com
o renderização da Visão Geral filtrada. Voltar restaura a tabela.

---

## 9. Plano de implementação faseado

Cada fase verificável antes da próxima.

**Fase A — Refator de `_render_visao_geral`**
- Adicionar parâmetros opcionais `filtro_unidade`, `filtro_grupo`, `titulo_contexto`
- Verificar que comportamento sem filtros é idêntico ao atual (smoke test manual)
- Sem mudanças visíveis pra usuário

**Fase B — Helpers de período fixos**
- Função `_calcular_3_periodos(max_d) -> dict` retornando os 3 intervalos
- Função `_pct_no_periodo(df, data_ini, data_fim, razao=None) -> float` usando
  `calcular_pct_curtailment` num subset
- Testes manuais com df mockado

**Fase C — Visão (1) Por unidade**
- HTML puro com tabela, seletor de razão, ordenação
- Tooltip rico
- Click handler → state machine
- Sem chevron (esse é da visão de grupo)

**Fase D — Visão (2) Por grupo**
- Mesma base da Fase C
- Adicionar lógica de zona 1 (listadas) + zona 2 + "Other" no fim
- Adicionar chevron de expansão inline

**Fase E — Drill-down**
- Conectar clicks → `_render_visao_geral` com filtros
- Breadcrumb + botão voltar

**Fase F — Polimento**
- Nota de rodapé sobre não-aditividade de %
- Edge cases: usinas sem match, grupos sem dados no período, max_d perto do início do mês
- Validação visual com mês real

---

## 10. Pontos abertos pendentes de Nava

1. **`PAR` na decomposição:** seguir convenção do projeto (excluído de `RAZOES_OPERATIVAS`).
   Nas sub-abas novas, mostrar só ENE/CNF/REL no tooltip e Total. Confirmar?
2. **`max_d` no df_filtrado pode estar muito perto do início de um mês** (ex: dia 2).
   Mês corrente parcial fica com 1–2 dias só, números ruidosos. Mostrar mesmo assim,
   mostrar com `—`, ou com aviso?
3. **Listadas em bolsa que fazem match parcial:** se aparecer `EQTL Energia S.A.` no
   Excel diferente de `EQTL (Echo)`, não bate com a regra atual. **Por enquanto, regra
   é match exato em string.** Se aparecerem variações, cria aliases no CSV.

---

## 11. Coerência matemática (auditável)

```
Σ FRUSTRADO_MWH (df_filtrado) == Σ FRUSTRADO_MWH (Visão Geral mesmo período/fonte)
Σ OUTPUT_MWH    (df_filtrado) == Σ OUTPUT_MWH    (Visão Geral mesmo período/fonte)
```

**MWh é aditivo.** Soma do MWh frustrado de qualquer recorte (por usina, por grupo)
no mesmo período/fonte deve bater com a Visão Geral.

**% NÃO é aditivo entre linhas.** É razão local.
**Nota de rodapé** nas duas tabelas (sutil, Inter cinza, pequena):
> *"% individuais não somam o total do sistema. Para auditar contra a Visão Geral,
> compare os MWh absolutos (visíveis no tooltip)."*

---

## 12. Restrições técnicas (lições já internalizadas no projeto)

- HTML puro via `st.markdown(unsafe_allow_html=True)`, NÃO `st.dataframe`
- NÃO usar `:has()` — congela o app
- NÃO usar `display:none` em elementos clicáveis — bloqueia `.click()`
  (usar `visibility:hidden + position:absolute + 1px`)
- CSS em f-string com `{{}}` escapados, separar de HTML em concat simples
- Sem border-radius, bordas pretas 2px, paleta Bauhaus
