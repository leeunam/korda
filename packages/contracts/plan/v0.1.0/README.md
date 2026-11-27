# Plano logístico sintético v0.1.0

O planejador e o worker compartilham um plano JSON que acompanha um único projeto e uma revisão de contexto. O documento conserva as fontes, os trechos de evidência, as regras confirmadas ou pendentes e os IDs das lacunas do [contrato P1](../../context/v0.1.0/README.md).

| Campo | Interpretação |
| --- | --- |
| `project_id`, `context_id`, `context_revision` | Identidade da revisão que originou o plano. |
| `plan_version` | SHA-256 hexadecimal do plano sem este campo, em JSON UTF-8 com chaves ordenadas recursivamente e sem espaços entre os elementos. |
| `state` | `rascunho` ou `aguardando_aprovacao`. A aprovação humana é um registro externo associado ao projeto e à versão exata. |
| `metrics` | Fórmula, grão, unidade, denominador, fontes, chaves, referências a `rules`, testes e IDs de lacunas bloqueantes por indicador. |
| `rules`, `source_profile`, `sources`, `evidence`, `gaps` | Rastreabilidade da descoberta. Papel e evidência de quem confirmou uma regra pertencem à entrevista. |
| `dataset`, `editable_models` | Lote de fontes sintéticas e modelos SQL que o harness pode criar e corrigir. Cada item é um caminho exato (`models/prata_ctes.sql`) ou um padrão com `*` só no último segmento (`models/*`, `models/prata/*.sql`), sempre dentro de `models/` e terminando em `.sql` ou `*`. A demo usa `models/*`. |
| `period`, `tasks`, `limits` | Escopo do lote, dependências entre tarefas, saídas verificáveis e limite proposto de correções por etapa. |
| `destination`, `cost_estimate_brl_cents` | Identificador lógico de destino e custo estimado em centavos de real. O valor nulo registra informação pendente. |
| `construction` (opcional) | Plano de construção gerado pelo planejamento do worker (uma chamada de LLM) a partir do plano base e do contexto: `document` (markdown com Modelos, Regras aplicadas, Métricas, Testes de aceite e Premissas e lacunas), `model` e `synthetic`. Entra no hash: a aprovação 1 cobre o que a LLM planejou. Gerado por `anexar_construcao`; o restante do plano continua vindo do gabarito. |

`schema_version` identifica o formato. Uma mudança no custo, no destino, em uma regra ou em suas evidências produz outra `plan_version`. O hash identifica conteúdo. A autorização vem do registro confiável de decisões humanas. A promoção exige uma decisão própria, vinculada ao resultado testado.

O schema usa referências relativas ao schema de contexto. O [validador do planejador](../../../../services/planning/korda_planning/plano.py) resolve ambos localmente, verifica os vínculos e reconstrói a proposta para conferir a versão. Os trechos de evidência e as fórmulas são dados de revisão. O runtime deve usar ferramentas restritas e identificar as regras que consegue executar. Os exemplos de geração a partir de duas revisões estão no [guia do planejador](../../../../services/planning/README.md).

## Mudanças

- **26/11/2026, sem mudar `schema_version`:** `editable_models` deixou de ser `const: models/prata_ctes.sql` e passou a aceitar caminho exato ou padrão em `models/`. Motivo: o harness passou a construir o pipeline inteiro a partir do plano, e não só a corrigir um modelo (decisão do responsável pela execução em 25/11). Planos antigos com `["models/prata_ctes.sql"]` continuam válidos no schema; o planejador agora emite `["models/*"]`, então a `plan_version` dos planos regenerados muda. Contrato compartilhado: a mudança precisa de concordância do time (K01/K06) no PR.
- **27/11/2026, sem mudar `schema_version`:** seção opcional `construction`. O comando `planejar` da execução a gera antes da aprovação 1; o `executar` com LLM passa a exigi-la. Planos sem a seção continuam válidos. Contrato compartilhado: precisa de concordância do time no PR.
