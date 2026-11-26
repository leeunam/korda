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

## Camadas de proteção

Em ordem de autoridade:

1. **Kernel (a barreira real).** A sandbox monta o projeto dbt em modo somente leitura e deixa graváveis só os arquivos de `editable_models`, sem rede (`--network none`). No #21, isso fica em `sandbox.py`. Nesta branch a montagem por arquivo ainda não existe na `main`.
2. **Ferramentas restritas.** `caminhos.caminho_modelo` aceita só `models/**/*.sql`, e `FerramentasRestritas` recusa modelos fora do plano.
3. **Hook `PreToolUse`** ([`politica.py`](politica.py)). Recusa qualquer ferramenta fora de `mcp__korda__*` e qualquer escrita fora de `editable_models`, com motivo para o agente e evento `tool_refused` (`dados.origem = "hook"`). A mensagem do evento não repete a entrada da ferramenta.

O hook é uma camada extra. Sozinho, não garante isolamento.

## Contratos de que dependemos

O harness depende só de pontos estreitos, definidos em [`tipos.py`](tipos.py):

- `Corretor`: mesma assinatura do `corrigir(falha, tentativa)` do worker (#21). Devolve `{"ok", "erro"?, "custo_centavos"}`. `ok: True` quer dizer "apliquei uma alteração"; quem julga é o rebuild. Custo `None` significa desconhecido, e o ciclo escala em vez de assumir zero.
- `FerramentasAgente`: espelha os seis métodos de `FerramentasRestritas` do #21 (`ler_plano`, `inspecionar_fonte`, `ler_arquivo`, `escrever_modelo`, `rodar_dbt`, `consultar_sql`) sem importar a classe.
- `usd_para_centavos`: converte o custo do SDK (USD) em centavos de real, arredondando para cima.

## Verificação

```bash
python3 -m unittest discover -s services/execution/tests/harness -t services/execution
```
