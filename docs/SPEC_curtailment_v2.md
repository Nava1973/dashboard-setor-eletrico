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

---

## Fase G — UX Polish (pendente)

Ajustes pequenos de polimento descobertos pós-Fase F. Sem refator
estrutural, sem novo dado, sem mudança de cálculo. Empacotam de forma
coerente porque atacam coesão visual e clareza informacional da aba.

### G.1 — Renomear label "Proprietário" para "Grupo" na tabela Por usina

**Descrição:** trocar o cabeçalho da coluna "Proprietário" da tabela
da sub-aba "Por usina" para "Grupo". Mudança apenas de label visível
no HTML renderizado — DataFrame interno mantém a coluna como
`PROPRIETARIO` (chave técnica), pipeline upstream/downstream
inalterado.

**Justificativa:** alinha vocabulário com a sub-aba "Por grupo".
Hoje o usuário lê "Proprietário" numa aba e "Grupo" na outra pra
designar o mesmo conceito (entidade do Excel de grupos). Coerência
de vocabulário entre sub-abas reduz fricção cognitiva. Aplica o
padrão "display labels separados de variable names" (decisão 5.30
do CLAUDE.md) — vocabulário visível pode mudar sem mexer no data
layer.

**Atenção técnica:** tradução acontece no ponto onde o cabeçalho
HTML é construído (provavelmente uma f-string literal com `<th>`).
NÃO renomear:
- chave de coluna `PROPRIETARIO` no DataFrame
- variáveis Python (`df_proprietario`, `proprietario_alias`, etc.)
- chaves de dict, comparações `col == "PROPRIETARIO"`
- nomes em `data_loader_grupos_excel.py`

Validação: `Ctrl+F` por "Proprietário" no `tab_curtailment.py` —
contar ocorrências antes/depois pra confirmar que só o label de
header mudou (1 ocorrência esperada).

**Risco:** baixo. Mudança puramente cosmética de string. Sem
impacto em export CSV (que usa keys internas). Sem impacto em
testes (não há testes contra o label). Reversível em 1 commit.

### G.2 — Botão sub-aba selecionado: fundo amarelo (não branco)

**Descrição:** trocar o estilo do botão de sub-aba ATIVO de fundo
branco (`#FFFFFF`) para fundo amarelo Bauhaus (`#F6BD16` =
`BAUHAUS_YELLOW`). Manter borda preta 2px e texto preto.
Botões inativos continuam pretos com texto cream — sem mudança.

**Justificativa:** alinha com os botões de preset de período
(1M/3M/6M/12M/Máx) que já usam `type="primary"` com fundo amarelo
via CSS global. Hoje a aba Curtailment tem 2 famílias de botões
ATIVOS visualmente distintas: sub-abas em branco vs presets em
amarelo. Padronizar pra amarelo reforça "ativo = amarelo" como
linguagem visual única na aba e no resto do app.

**Atenção técnica:** os botões de sub-aba são `st.button`
customizados (não `st.segmented_control`), com CSS escopado em
`[class*="st-key-btn_curt_subaba_"] button[kind="primary"]`
(`tab_curtailment.py:1294`). A regressão visual antiga do
segmented_control (atributo de "ativo" instável, armadilha 4.3 do
CLAUDE.md) **NÃO se aplica** — atributo `kind="primary"` é estável
e semântico. Mudança é literal: trocar `background-color: #FFFFFF`
por `background-color: #F6BD16`. Texto continua `#1A1A1A`
(`BAUHAUS_BLACK`) — contraste de leitura preservado (preto sobre
amarelo é leitura clara).

**Risco:** baixo. CSS escopado por `[class*="st-key-btn_curt_subaba_"]`
não vaza pra outros botões da página (presets de período mantêm
amarelo via outro seletor; botões `secondary` não são afetados).
Validação visual em <30s — abrir aba, conferir as 3 sub-abas,
clicar em cada uma.

### G.3 — Mensagem informativa de carregamento diferenciada

**Descrição:** trocar o spinner anônimo da 1ª carga de dados de
curtailment por uma mensagem informativa explícita: **"Carregando
15 meses de dados ONS — primeira carga da sessão"**. Cargas
subsequentes (cache hit) usam spinner curto ou ficam silenciosas.

**Justificativa:** o cold start da aba Curtailment custa ~40-45s
estimados pós-Fase G (carga 15M consolidada — ver plano Caminho 1
documentado em conversa anterior). Sem mensagem clara, o usuário
não sabe se o app travou ou se está fazendo trabalho legítimo.
Diferenciar 1ª carga (mensagem completa, expectativa de 30-60s)
de cargas subsequentes (silêncio ou "atualizando…", expectativa
<2s) calibra a expectativa do usuário pelo cenário real.

**Atenção técnica:** o helper público
`is_balanco_cache_fresh()` da decisão 5.15 é o pattern análogo —
expor um helper similar pro curtailment
(`is_curtailment_cache_fresh()` ou check direto via
`@st.cache_data`'s `_get_cache_key()`) pra UI escolher mensagem
antes do load. Implementação possível em 2 níveis:
- **Simples:** flag em `st.session_state["_curt_ja_carregou"]`
  que vira `True` após 1ª chamada da sessão. UI escolhe mensagem
  baseada nesse flag. Não detecta cache de disco persistente
  entre sessões — cada sessão nova mostra "primeira carga".
- **Robusto:** helper que checa se a janela 15M está cacheada
  (via Streamlit's internal cache check ou disk-cache fresh).
  Detecta cache quente entre sessões mas é mais frágil — APIs
  internas do Streamlit podem mudar entre versões.

**Recomendação:** implementação simples primeiro. Se o user
relatar "mensagem incorreta" (ex: cache de disco quente, mas
mostra "primeira carga"), promover pra robusto.

**Risco:** baixíssimo. Mensagem de UI sem efeito em cálculo,
dado, ou cache. Reversível em 1 commit. Trade-off conhecido:
versão simples mostra "primeira carga" no início de toda sessão
nova mesmo com disk-cache quente — aceito por simplicidade.

### G.4 — Layout wide moderado (1400px)

**Descrição:** trocar o `max-width` do `.block-container` em
`app.py` de **1000px** para **1400px**, mantendo `margin: 0 auto`
pra centralização. `st.set_page_config(layout="wide")` já está em
produção (app.py:51) — remove o limite default do Streamlit
(~704px), mas o CSS `.block-container { max-width }` é o que
limita visualmente. Mudança afeta TODAS as abas globalmente.

**Justificativa:** a tabela "Por usina" expandida da G.5 precisa
de mais largura pra acomodar 7 colunas de valor (3 meses + 4
trimestres) + Unidade + Grupo. 1000px aperta demais. 1400px é
sweet spot — acomoda tabela larga sem estirar feio em monitores
4K (onde largura total seria 2000-3000px). Outras abas (PLD,
Reservatórios, ENA, Geração, Carga) ganham respiro grátis sem
redesign.

**Atenção técnica:**
- Telas <1400px: max-width fica inativo, container ocupa tudo
  disponível (mesmo comportamento de hoje em telas <1000px).
- Telas ≥1400px: container limita a 1400px e centraliza.
  Mudança visível.
- Componentes filhos com `use_container_width=True` (default das
  abas) re-renderizam pra 1400px. **Risco real:** alguma viz
  Plotly calibrada pra 1000px pode ficar achatada/estranha
  (hover labels, alinhamentos manuais, larguras absolutas em
  px). Smoke test em 6 abas obrigatório antes de commit.
- `set_page_config` linha 51: NÃO mexer (já está
  `layout="wide"`).
- Outros `max-width: 100% !important` em CSS de selectbox
  (linhas 1561, 1703 em app.py): scoped a
  `[data-testid="stSelectbox"]`, sem conflito.
- CLAUDE.md §3.5 menciona "Página limitada a max-width: 1000px
  no .block-container" — atualizar manualmente em sessão futura
  (mesma família de comentários "1GB" pendentes).

**Risco:** moderado. Afeta visual de todas as abas
simultaneamente. Mitigação: smoke test obrigatório em PLD,
Reservatórios, ENA/Chuva, Geração, Carga, Curtailment antes do
commit. Reversível em 1 commit (revert do CSS `max-width`).

### G.5 — Tabela "Por usina" expandida (3 meses + 4 trimestres)

**Descrição:** expandir a tabela da sub-aba "Por usina" de **3
colunas de valor** (3 últimos meses) para **7 colunas de valor**
— os mesmos 3 meses + 4 trimestres adicionais (trimestre corrente
parcial + 3 trimestres fechados anteriores). Estrutura final:

```
| UNIDADE | GRUPO | ABR  | MAR  | FEV  | T2   | T1   | T4   | T3   |
|         |       | 2026 | 2026 | 2026 | 26   | 26   | 25   | 25   |
|         |       |(parc)|      |      |(parc)|      |      |      |
```

**Decisões de produto:**

1. **Header em 2 linhas:** rótulo (mês curto ou Tn) na 1ª linha,
   ano de 2 dígitos na 2ª. Sufixo `(até DD/MM)` no mês corrente
   E no trimestre corrente — comunica visualmente que estão
   parciais.

2. **Linha vertical sutil entre coluna FEV 2026 e T2 26:**
   separador conceitual (meses vs trimestres). CSS:
   `border-left: 1px solid #E0E0E0` ou similar — sutil, só
   marca a transição.

3. **Ordenação:** decrescente por **% no trimestre corrente
   (T2 26)**, não mais por mês corrente. Razão: trimestre é
   métrica mais robusta pra ranking (1 mês isolado pode ter
   ruído pontual; trimestre suaviza). Unidades sem dado em T2
   vão pro fim em ordem alfabética.

4. **Cobertura temporal:** usa exatamente a janela 15M já
   carregada pelo Caminho 1 (commit 47fe421) — sem custo
   adicional de download. T3 25 começa em 01/07/2025; janela
   ampla começa em 01/04/2025; sobra 1 trimestre de margem.

**Cálculo dos valores trimestrais:**

- **T2 26 corrente (parcial):** % FRUSTRADO sobre soma do
  trimestre **até `max_d`** (ex: 01/04/2026 → 30/04/2026 se
  max_d = 30/04/2026 — 1 mês de 3 do trimestre).
- **T1 26, T4 25, T3 25 fechados:** janelas trimestrais
  oficiais (T1 = jan-mar, T4 = out-dez, T3 = jul-set).
  Reutiliza `_inicio_trimestre_anterior(max_d, N)` que já
  existe em `tab_curtailment.py`.

**Atenção técnica:**

- Estender `calcular_3_periodos` em
  `utils/utils_curtailment.py` pra retornar 7 períodos (3
  meses + 4 trimestres), OU criar novo helper
  `calcular_periodos_completos`. Decisão: **estender** o
  existente — caller único (`_calcular_linhas_unidade`),
  rename pra `calcular_periodos_curtailment` se ficar
  semanticamente desonesto. Avaliar na implementação.
- `pct_no_periodo` em `utils/utils_curtailment.py` já aceita
  período arbitrário (`data_ini, data_fim`) — não precisa
  mudar. Funciona pra meses E trimestres sem distinção.
- `_calcular_linhas_unidade` em `tab_curtailment.py:793`
  passa a calcular 7 pcts em vez de 3. Loop interno itera
  sobre 7 períodos. Custo: ~270 unidades × 7 períodos =
  ~1890 chamadas a `pct_no_periodo` (vs 810 antes). Cache
  do resultado preserva.
- HTML da tabela passa a ter 9 colunas totais (Unidade +
  Grupo + 7 períodos). CSS precisa acomodar — provável
  ajuste de padding/font-size das colunas numéricas.
- Header em 2 linhas: usar `<br>` dentro do `<th>` ou
  `display: flex; flex-direction: column` no `<th>`.
  Decidir na implementação visual.

**Risco:** moderado. 4 frentes simultâneas (helper +
loop + HTML + CSS). Smoke test focado em Curtailment:
- Tabela renderiza com 9 colunas sem overflow.
- Sufixo `(até DD/MM)` aparece nas 2 colunas parciais.
- Linha vertical entre FEV 2026 e T2 26 visível mas sutil.
- Ordenação por T2 26 decrescente (1ª linha = maior % T2).
- Valores em formato BR (`12,34%`).
- Sem regressão em Visão Geral (não muda nessa sub-aba).

Reversível em 1 commit se algo quebrar.
