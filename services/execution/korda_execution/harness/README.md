# Harness do executor (K08, K10)

**Status (25/11/2026): em construção, Fase A do [plano](../../../../docs/superpowers/plans/2026-11-25-harness-executor.md).** Ainda **não** está ligado ao worker: isso depende do PR #21. Nenhuma execução real com LLM foi feita.

O harness substitui o `corrigir(falha, tentativa)` do worker por um **corretor** escolhido por configuração. O corretor só pode alterar os modelos listados em `editable_models` do plano aprovado.

## Corretores

| Corretor | Arquivo | Usa LLM? | Para quê |
| --- | --- | --- | --- |
| `roteirizado` | [`roteirizado.py`](roteirizado.py) | Não | Plano B da demo. Restaura a versão revisada do modelo, como o `corrigir` atual do #21. Não descobre nada. Custo zero. |
| `falso` | [`falso.py`](falso.py) | Não | Testes. Segue um roteiro fixo de chamadas pelo mesmo hook e o mesmo despacho do agente. Tokens e custo são sintéticos. |
| `agente` | [`agente_sdk.py`](agente_sdk.py) | **Sim** | Correção real com o Claude Agent SDK. Exige a chave e `KORDA_PERMITIR_LLM_REAL=1`. |

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

## Corretor agente (Claude Agent SDK)

[`agente_sdk.py`](agente_sdk.py) é o único arquivo que importa o `claude-agent-sdk` (versão fixada em [`requirements-harness.txt`](../../../../requirements-harness.txt)). **Ainda não foi executado com LLM real.** O primeiro ensaio é a Tarefa 12 do plano, depois do merge do #21 e com autorização do responsável pela chave.

O SDK roda o CLI do Claude Code **no host**, onde estão o repositório e as respostas esperadas. Por isso, cada sessão:

- desliga as ferramentas embutidas (`tools=[]`, que o SDK 0.2.180 passa como `--tools ""`) e lista as embutidas em `disallowed_tools`;
- libera só as seis `mcp__korda__*`, em modo `dontAsk`, e o hook nega todo o resto;
- roda com `cwd` numa pasta temporária vazia e `setting_sources=[]` (não lê `CLAUDE.md` nem configurações do disco);
- é **abortada** (`ErroSegurancaHarness`) se o `init` da sessão listar qualquer ferramenta fora de `mcp__korda__*`. Se isso acontecer no primeiro ensaio real, o plano prevê trocar para a Messages API atrás do mesmo `Corretor`.

O SDK herda o ambiente do processo. Rode o worker com o ambiente mínimo, sem outras credenciais.

Limites por execução:

| Limite | Valor | Comportamento |
| --- | --- | --- |
| Orçamento total | `KORDA_ORCAMENTO_EXECUCAO_USD` (3,00) | Esgotado, a tentativa devolve `ok: False` sem abrir sessão, e a etapa escala para uma pessoa. |
| Teto por tentativa | `min(restante, total/3) × 0,9` | Folga de 10%, porque a estimativa do SDK pode passar do teto. |
| Turnos por tentativa | `KORDA_MAX_TURNOS_TENTATIVA` (12) | O SDK encerra com `error_max_turns`. |
| Tentativas | `limits.max_repair_attempts_per_step` do plano (3) | Controladas pelo ciclo do worker, não pelo harness. |

Resultado de cada tentativa: `ok: True` só se o agente escreveu um modelo autorizado e a sessão não terminou em erro. Quem julga a correção é o rebuild. Sem escrita, devolve `ok: False` com o motivo, e o ciclo escala na hora. Custo desconhecido vira `custo_centavos: None` (o ciclo escala) e consome o teto da tentativa no controle de orçamento. Cada tentativa emite `agent_finished` com `subtype`, turnos, custo, arquivos escritos e a lista de ferramentas da sessão.

## Camadas de proteção

Em ordem de autoridade:

1. **Kernel (a barreira real).** A sandbox monta o projeto dbt em modo somente leitura e deixa graváveis só os arquivos de `editable_models`, sem rede (`--network none`). No #21, isso fica em `sandbox.py`. Nesta branch a montagem por arquivo ainda não existe na `main`.
2. **Ferramentas restritas.** `caminhos.caminho_modelo` aceita só `models/**/*.sql`, e `FerramentasRestritas` recusa modelos fora do plano.
3. **Hook `PreToolUse`** ([`politica.py`](politica.py)). Recusa qualquer ferramenta fora de `mcp__korda__*` e qualquer escrita fora de `editable_models`, com motivo para o agente e evento `tool_refused` (`dados.origem = "hook"`). A mensagem do evento não repete a entrada da ferramenta.

O hook é uma camada extra. Sozinho, não garante isolamento.

## Ferramentas do agente

O agente só enxerga seis ferramentas, descritas em [`ferramentas_agente.py`](ferramentas_agente.py) e expostas como `mcp__korda__<nome>`. Todas passam por `FerramentasRestritas`, que executa dentro da sandbox:

| Ferramenta | Efeito |
| --- | --- |
| `ler_plano` | Projeção do plano aprovado. |
| `inspecionar_fonte` | Perfil de uma fonte do catálogo autorizado. |
| `ler_arquivo` | Leitura de um arquivo do projeto dbt. |
| `escrever_modelo` | Escrita de SQL só em `editable_models`. |
| `rodar_dbt` | dbt com subcomandos em lista branca. A saída devolvida ao agente fica nos últimos 8.000 caracteres. |
| `consultar_sql` | SQL somente leitura no DuckDB da execução. |

Entradas fora do formato (campo faltando, campo extra, valor que não é texto) são recusadas sem chamar a ferramenta.

## O que o agente vê

[`contexto.py`](contexto.py) monta o contexto de cada tentativa:

- um prompt de sistema fixo, com as regras: só `editable_models`, nunca testes, fontes ou regras; se a correção exigir mudar regra, parar e explicar;
- o número da tentativa e o limite do plano;
- o erro do build, já cortado pelo worker;
- a projeção do plano, só com `plan_version`, `editable_models`, `limits`, `rules` (valores) e `metrics[*].acceptance`;
- os perfis das fontes, cortados em 12.000 caracteres.

Evidências, fontes, destino e fórmulas não entram. As respostas esperadas (`evaluation/golden/`) nunca fazem parte do contexto. Se o planejador (K06) mudar, o harness depende só desses cinco campos.

## Medição

[`medicao.py`](medicao.py) acumula uma linha por tentativa e grava `medicao.json` (insumo da K14):

| Campo | Conteúdo |
| --- | --- |
| `run_id`, `corretor`, `modelo` | Identificação. |
| `synthetic` | `true` quando o corretor não é o `agente`: os números não medem um LLM real. |
| `tentativas`, `turnos`, `duracao_s` | Soma das tentativas do corretor. |
| `tokens_entrada`, `tokens_saida`, `tokens_cache_leitura` | Soma dos tokens informados. |
| `custo_usd`, `custo_centavos` | Custo informado; centavos de real pela taxa configurada. |
| `custo_completo` | `false` se alguma tentativa não informou o custo. |
| `por_tentativa` | Detalhe de cada tentativa, inclusive arquivos escritos e motivo de parada. |

A ligação com o worker (gravar em `revisao/<run>/medicao.json`) depende do #21.

## Adaptador de eventos para o front (provisório)

O worker grava `eventos.jsonl` no formato do `EmissorEventos` (steps em português, `dados`, `attempt` até 4). O front (`apps/web`) espera o [`events.schema.json`](../../../../packages/contracts/events.schema.json). [`adaptador_eventos.py`](adaptador_eventos.py) traduz um no outro e é o único ponto de contato. **O mapeamento é provisório**, pendente da K01 e do José (P4):

| Worker (`step/type`) | Front (`step/type`) |
| --- | --- |
| `plano/run_started` | `plan/task_started` |
| `modelos/test_failed` | `run_dbt/test_failed` |
| `modelos/test_passed` | `run_dbt/test_passed` |
| `modelos/fix_started` | `agent/task_started` |
| `modelos/fix_applied` | `agent/fix_applied` |
| `construcao/file_written` | `agent/file_written` (`dados.caminho` → `data.file`) |
| `construcao/tool_refused` de `escrever_modelo` ou do hook | `write_hook/write_blocked` |
| demais (`intervention_requested`, `evaluation_finished`, `run_failed`, `agent_finished`, `dbt_*`, `query_*`, recusas de leitura) | não mapeados: contados em `nao_mapeados` e fora da exportação |

`attempt` fora de 1 a 3 vira `null`, com o valor original em `data.attempt_original`. A exportação tem o formato de `apps/web/src/data/seed-run.json`:

```bash
cd services/execution
python3 -m korda_execution.harness.adaptador_eventos ../../runs/worker/revisao/<run>/eventos.jsonl --synthetic
```

Perguntas em aberto para o José: como representar o escalonamento (`intervention_requested`) e a avaliação no grafo; se `attempt` 4 vira `null` ou o schema passa a aceitar 4; se o front pode carregar esta exportação no lugar do seed.

## Contratos de que dependemos

O harness depende só de pontos estreitos, definidos em [`tipos.py`](tipos.py):

- `Corretor`: mesma assinatura do `corrigir(falha, tentativa)` do worker (#21). Devolve `{"ok", "erro"?, "custo_centavos"}`. `ok: True` quer dizer "apliquei uma alteração"; quem julga é o rebuild. Custo `None` significa desconhecido, e o ciclo escala em vez de assumir zero.
- `FerramentasAgente`: espelha os seis métodos de `FerramentasRestritas` do #21 (`ler_plano`, `inspecionar_fonte`, `ler_arquivo`, `escrever_modelo`, `rodar_dbt`, `consultar_sql`) sem importar a classe.
- `usd_para_centavos`: converte o custo do SDK (USD) em centavos de real, arredondando para cima.

## Verificação

```bash
python3 -m unittest discover -s services/execution/tests/harness -t services/execution
```
