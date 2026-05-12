# B.5 Findings — Investigação MMGD via ANEEL CKAN SQL

Data da investigação: 2026-05-12  
Sessão: post-Commit D 4bba871 (branch feat/capacidade-instalada).

## Descoberta arquitetural

ANEEL CKAN tem endpoint `datastore_search_sql` habilitado com whitelist de funções:

| Função | Status |
|--------|--------|
| `COUNT()` | ✅ Permitida |
| `SUM()` | ✅ Permitida |
| `replace()` | ✅ Permitida |
| `::float` (cast operator) | ✅ Permitido |
| `CAST()` (cast function) | ❌ Blacklisted (Authorization Error) |
| `to_number()` | ❌ Blacklisted |

## Query mágica

```sql
SELECT SUM(replace("MdaPotenciaInstaladaKW", ',', '.')::float) AS total_kw
FROM "b1bd71e7-d0ad-4214-9053-cbd58e9564a7"
WHERE "DthAtualizaCadastralEmpreend" <= '{cutoff}'
```

Tempo típico: ~7s/query. Sem truncamento. Sem timeout.

## Cross-check empírico vs MMGD_ANCHORS atuais

| Cutoff | Esperado (MW) | Reconstruído (MW) | Diff (MW) | Diff % | Fonte | Tempo |
|--------|---------------|-------------------|-----------|--------|-------|-------|
| 2022-12-31 | 20,000 | 18,121.8 | -1,878.2 | -9.4% | INFERIDO | 4.0s |
| 2023-12-31 | 28,000 | 26,632.9 | -1,367.1 | -4.9% | INFERIDO | 3.4s |
| 2024-12-31 | 36,200 | 36,885.2 | +685.2 | +1.9% | CONFIRMADO PDGD | 3.7s |
| 2025-12-31 | 45,000 | 46,060.5 | +1,060.5 | +2.4% | CONFIRMADO PDGD | 3.7s |
| 2026-05-12 | 45,000 | 48,032.5 | +3,032.5 | +6.7% | CARRY-FORWARD | 3.4s |

## Implicações pra próxima sessão

1. **Workaround viável**: SUM server-side com `replace(...)::float` + WHERE temporal.
2. **DthAtualiza ≈ data de conexão** com viés ~2% nos anos com gold standard EPE PDGD (dez/2024: +1.9%, dez/2025: +2.4%). Anchors INFERIDOS (2022/2023) divergem mais (~5-9%, viés pra cima nos meus chutes originais).
3. **Possível upgrade futuro**: substituir `MMGD_ANCHORS` hardcoded por loader dinâmico:
   - Query 5 cutoffs (dez/22..dez/25 + today) via SQL workaround
   - Cache `@st.cache_data(ttl=24h)`
   - Fallback pro hardcoded em caso de timeout/erro
4. **Possível decisão**: atualizar carry-forward abr/2026 (atualmente 45.000 MW) para valor reconstruído via SQL: 48.032 MW. Reconsiderar tambem anchors INFERIDOS 2022/2023 (20.000/28.000 → ~18.100/26.600 MW reais).

## Distribuição UCs MMGD por ano (DthAtualiza)

Sem evidência de pico artificial set/2025 (migração SISGD→MMGD).
Crescimento coerente com expansão real do setor.

```
2020:    223.326 UCs  ( 5,4%)
2021:    451.438 UCs  (10,8%)
2022:    798.177 UCs  (19,2%)  ← pico Lei 14.300 (jan/2022)
2023:    685.656 UCs  (16,5%)
2024:    907.286 UCs  (21,8%)  ← pico de adesão
2025:    876.173 UCs  (21,0%)
2026:    221.956 UCs  ( 5,3%)  ← parcial (jan-mai/2026)
─────────────────────────────────────────
Total: 4.164.012 UCs (sample T5; total dataset: 4.342.212)
```
