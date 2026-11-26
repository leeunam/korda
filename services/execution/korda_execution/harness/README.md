# Harness do executor (K08, K10)

**Status (25/11/2026): em construção, Fase A do [plano](../../../../docs/superpowers/plans/2026-11-25-harness-executor.md).** Ainda **não** está ligado ao worker: isso depende do PR #21. Nenhuma execução real com LLM foi feita.

O harness substitui o `corrigir(falha, tentativa)` do worker por um **corretor** escolhido por configuração. O corretor só pode alterar os modelos listados em `editable_models` do plano aprovado.

## Variáveis

Exemplo em [`.env.example`](../../../../.env.example).

| Variável | Padrão | Efeito |
| --- | --- | --- |
| `KORDA_CORRETOR` | `roteirizado` | `roteirizado` (sem LLM), `falso` (testes, sem LLM) ou `agente` (LLM real). |
| `KORDA_PERMITIR_LLM_REAL` | vazio | Precisa ser `1` para o `agente` rodar. Proteção contra gasto acidental. |
| `ANTHROPIC_API_KEY` | vazio | Obrigatória só para o `agente`. Lida do ambiente do host; nunca vai para a sandbox, eventos ou logs. |
| `KORDA_MODELO` | `claude-opus-5-5` | Modelo do agente. |
| `KORDA_ORCAMENTO_EXECUCAO_USD` | `3.00` | Teto de gasto por execução, somando as tentativas. |
| `KORDA_MAX_TURNOS_TENTATIVA` | `12` | Limite de turnos do agente em cada tentativa. |
| `KORDA_TAXA_USD_BRL` | `6.00` | Conversão para `custo_centavos` (centavos de real). Suposição da equipe, não cotação. |

`ConfigHarness.de_ambiente()` ([`config.py`](config.py)) valida essas variáveis. Com `KORDA_CORRETOR=agente`, ela falha com mensagem clara se faltar a chave ou a permissão explícita.

## Verificação

```bash
python3 -m unittest discover -s services/execution/tests/harness -t services/execution
```
