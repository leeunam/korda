# Harness do executor (K08, K09, K10)

**Status (26/11/2026): ligado ao worker.** O [`worker.py`](../worker.py) gera o documento-base, cria a sandbox com `models/` vazio e chama `construir_e_verificar`. Os aceites com Docker usam o cliente falso e o `roteirizado`. A única chamada real até agora foi o teste de fumaça do gateway (abaixo); **a construção nunca rodou com LLM real**. Plano: [`2026-11-25-harness-executor.md`](../../../../docs/superpowers/plans/2026-11-25-harness-executor.md).

## Papel

Decisão do responsável pela execução (25 e 27/11/2026): **o harness constrói o pipeline; o worker só orquestra.** Antes da aprovação 1, o comando `planejar` ([`planejamento.py`](../planejamento.py)) faz uma chamada à API da Feita que gera a construção, anexada ao plano, ou as perguntas para a descoberta. Depois da aprovação, o `executar` prepara a sandbox, intermedeia o harness com a mesma API e avalia. O pipeline dbt feito à mão no #21 deixa de ser o produto e vira o executor `roteirizado` (plano B da demo), fora do alcance do agente.

```
contexto (P1) ─▶ korda_planning (gabarito) ─▶ plano base
plano base + contexto ─▶ planejar: 1 chamada de API, sem ferramentas
        ├─ falta contexto ─▶ perguntas.json ─▶ descoberta (sem plano novo)
        └─ pronto ─▶ plano + construction (nova plan_version)
                                        │
                               aprovação 1 (cobre a construção)
                                        │
                                        ▼
                         executar: sandbox (sem rede, testes e fontes só leitura, models/ vazio)
                                        │
                                        ▼
               harness: construir_e_verificar(documento_base = construction.document)
                 1. ExecutorChat.construir(...)  → escreve bronze/prata/ouro
                 2. dbt build (testes protegidos) + exportação no contrato de saída
                 3. falhou? ExecutorChat(falha, tentativa)  → até 3 correções; depois, pede ajuda
                                        │
                                        ▼
                         worker: captura com hash → pacote de entrega → aprovação 2 → promoção
```

O modelo nunca executa nada: ele só pede ferramentas. Cada pedido passa pela política ([`politica.py`](politica.py)) e só então vira um comando na sandbox. A chave fica no processo do host.

## Executores

| `KORDA_EXECUTOR` | Arquivo | Usa LLM? | O que faz |
| --- | --- | --- | --- |
| `chat` | [`executor_chat.py`](executor_chat.py), [`sessao_chat.py`](sessao_chat.py), [`cliente_chat.py`](cliente_chat.py) | **Sim** | Constrói e corrige com loop próprio de ferramentas sobre uma API chat/completions (gateway da Feita). Custo estimado pelos tokens. |
| `agente_sdk` | [`agente_sdk.py`](agente_sdk.py) | **Sim** | Só correção, com o Claude Agent SDK. Guardado do #27 e **recusado pelo worker**: a construção usa a API da Feita. |
| `roteirizado` | [`roteirizado.py`](roteirizado.py) | Não | Plano B: `ConstrutorRoteirizado` copia o pipeline feito à mão; `CorretorRoteirizado` restaura o modelo revisado. **Não demonstra construção por IA.** |
| `falso` | [`falso.py`](falso.py), `ClienteChatFalso` | Não | Testes. Roteiro fixo de chamadas pelo mesmo caminho do agente; tokens e custo sintéticos. |

O documento-base (construção) é gerado no `planejar`, com o prompt de [`documento_base.py`](../documento_base.py). Entram o contexto (sem metadados irrelevantes), o plano base e os nomes fixos de modelos e colunas ([`contrato_saida.py`](../contrato_saida.py)), lidos dos testes protegidos e do `exportar.py`. A resposta começa com um bloco ```` ```json ```` com `pronto_para_construir` e `perguntas` (pergunta, lacuna, métricas afetadas, motivo), seguido das seções Modelos, Regras aplicadas, Métricas, Testes de aceite e Premissas e lacunas. O prompt pede evidência só pelo id, uma tabela por camada e até ~900 palavras por seção; a saída é limitada a 8.000 tokens, e uma resposta cortada é recusada. O prompt proíbe inventar regras. Lacuna que não impede construir fica em Premissas e lacunas. Se a lacuna impedir, a LLM gera as perguntas para a descoberta. Sem um bloco válido, nenhum plano é gerado. O bloco é removido antes de o documento entrar no plano como `construction`.

## Variáveis

Exemplo em [`.env.example`](../../../../.env.example). Validadas por `ConfigHarness.de_ambiente()` ([`config.py`](config.py)).

| Variável | Padrão | Efeito |
| --- | --- | --- |
| `KORDA_EXECUTOR` | `roteirizado` | `roteirizado` (plano B, sem LLM), `falso` (testes, sem LLM), `chat` (LLM real via chat/completions) ou `agente_sdk` (LLM real via Claude Agent SDK; guardado, recusado pelo worker). |
| `KORDA_PERMITIR_LLM_REAL` | vazio | Precisa ser `1` para `chat` ou `agente_sdk` rodarem. Proteção contra gasto acidental. |
| `KORDA_LLM_CHAVE` | vazio | Chave do gateway (Feita) para `chat`. Fica no host; nunca vai para a sandbox, eventos ou logs. |
| `KORDA_LLM_URL` | `https://api.feita.ai/gateway/v1` | Base da API chat/completions. Só `https`. |
| `ANTHROPIC_API_KEY` | vazio | Só para `agente_sdk`. |
| `KORDA_MODELO` | `anthropic/claude-opus-5.5` (`chat`) ou `claude-opus-5-5` (`agente_sdk`) | Modelo. |
| `KORDA_ORCAMENTO_EXECUCAO_USD` | `8.00` | Teto de gasto por execução: construção mais correções. |
| `KORDA_MAX_TURNOS_CONSTRUCAO` | `40` | Limite de turnos da construção. |
| `KORDA_MAX_TURNOS_TENTATIVA` | `12` | Limite de turnos de cada correção. |
| `KORDA_PRECO_ENTRADA_USD_MTOK`, `KORDA_PRECO_SAIDA_USD_MTOK` | `4.00`, `20.00` | Preço por milhão de tokens usado para **estimar** o custo no `chat` (o gateway cobra em créditos). |
| `KORDA_TAXA_USD_BRL` | `6.00` | Conversão para centavos de real. Suposição da equipe, não cotação. |

Sem a chave ou sem `KORDA_PERMITIR_LLM_REAL=1`, os executores com LLM falham com mensagem clara. `KORDA_CORRETOR`, da versão anterior, é recusada com aviso.

## Executor `agente_sdk` (Claude Agent SDK, só correção)

[`agente_sdk.py`](agente_sdk.py) é o único arquivo que importa o `claude-agent-sdk` (versão fixada em [`requirements-harness.txt`](../../../../requirements-harness.txt)). **Ainda não foi executado com LLM real.** Com a chave atual (gateway chat/completions da Feita), ele não se aplica; o executor usado é o `chat`.

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

1. **Kernel (a barreira real).** A sandbox ([`sandbox.py`](../sandbox.py)) monta o projeto dbt em modo somente leitura (`tests/`, `definicoes/`, configuração, `ingerir.py`, `exportar.py`) e só `models/` gravável, vazio no início, sem rede (`--network none`). O pipeline feito à mão não é montado.
2. **Ferramentas restritas.** `caminhos.caminho_modelo` aceita só `models/**/*.sql`, e `FerramentasRestritas` recusa o que não casa com `editable_models` (caminho exato ou padrão, como `models/*`; `caminhos.modelo_autorizado`).
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
| `run_id`, `executor`, `modelo` | Identificação. |
| `synthetic` | `true` com `falso` ou `roteirizado`: os números não medem um LLM real. |
| `tentativas`, `turnos`, `duracao_s` | Soma das sessões do agente (construção = tentativa 0); a duração inclui o documento-base. |
| `documento_base` | Reservado para uma chamada de documento-base dentro da execução; hoje `null`, porque o planejamento tem a própria `medicao.json`. |
| `tokens_entrada`, `tokens_saida`, `tokens_cache_leitura` | Soma dos tokens informados. |
| `custo_usd`, `custo_centavos` | Custo informado; centavos de real pela taxa configurada. |
| `custo_completo` | `false` se alguma tentativa não informou o custo. |
| `por_tentativa` | Detalhe de cada tentativa, inclusive arquivos escritos e motivo de parada. |

A construção aparece como tentativa `0`. O worker grava `revisao/<run>/medicao.json`. O custo do planejamento fica no `medicao.json` da pasta do `planejar`; o orçamento de US$ 8 da execução cobre construção e correções.

## Orçamento do executor `chat`

| Limite | Valor | Comportamento |
| --- | --- | --- |
| Orçamento total | `KORDA_ORCAMENTO_EXECUCAO_USD` (8,00) | Esgotado, a fase devolve `ok: False` sem chamar a API, e uma pessoa decide. |
| Construção | até 60% do total, com folga de 10% | Para com `error_max_budget_usd` e escala. |
| Cada correção | restante ÷ tentativas que faltam, com folga de 10% | Idem. |
| Turnos | 40 na construção, 12 por correção | Para com `error_max_turns`. |

O custo é **estimado**: tokens informados pelo gateway × `KORDA_PRECO_*`. A Feita cobra em créditos; a referência real é o saldo. Sem `usage` na resposta, o custo fica desconhecido e consome o teto da fase no controle de orçamento.

## Adaptador de eventos para o front (provisório)

O worker grava `eventos.jsonl` no formato do `EmissorEventos` (steps em português, `dados`, `attempt` até 4). O front (`apps/web`) espera o [`events.schema.json`](../../../../packages/contracts/events.schema.json). [`adaptador_eventos.py`](adaptador_eventos.py) traduz um no outro e é o único ponto de contato. **O mapeamento é provisório**, pendente da K01 e do José (P4):

| Worker (`step/type`) | Front (`step/type`) |
| --- | --- |
| `plano/run_started` | `plan/task_started` |
| `modelos/test_failed` | `run_dbt/test_failed` |
| `modelos/test_passed` | `run_dbt/test_passed` |
| `modelos/fix_started` | `agent/task_started` |
| `modelos/fix_applied` | `agent/fix_applied` |
| `construcao/build_started` | `agent/task_started` |
| `construcao/file_written` | `agent/file_written` (`dados.caminho` → `data.file`) |
| `construcao/tool_refused` de `escrever_modelo` ou do hook | `write_hook/write_blocked` |
| demais (`intervention_requested`, `evaluation_finished`, `run_failed`, `agent_finished`, `dbt_*`, `query_*`, recusas de leitura) | não mapeados: contados em `nao_mapeados` e fora da exportação |

`attempt` fora de 1 a 3 vira `null`, com o valor original em `data.attempt_original`.

**Gasto no front.** Cada `agent_finished` traz o custo acumulado. A partir dele, todo evento exportado leva em `data` os campos `custo_total_centavos`, `orcamento_centavos` e `custo_estimado: true`, e a exportação ganha um bloco `custo` no topo com o valor mais recente. Não muda o contrato, porque `data` é aberto. O valor é **estimado** pelos tokens; o gateway cobra em créditos. A exportação tem o formato de `apps/web/src/data/seed-run.json`:

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

## Teste de fumaça do gateway

[`fumaca.py`](fumaca.py) faz no máximo duas chamadas curtas: pede ao modelo que chame uma ferramenta fictícia `ping` e devolve o resultado como mensagem `role: tool`.

```bash
set -a; . ./.env; set +a          # KORDA_LLM_CHAVE no .env (ignorado pelo Git)
cd services/execution
KORDA_EXECUTOR=chat KORDA_PERMITIR_LLM_REAL=1 python3 -m korda_execution.harness.fumaca
```

**Resultado em 25/11/2026** (`anthropic/claude-opus-5.5` via `https://api.feita.ai/gateway/v1`):
- gateway compatível: devolve `tool_calls` com JSON válido, aceita `role: tool` e informa `usage`;
- 2 chamadas, 914 tokens de entrada e 54 de saída, cerca de US$ 0,005 estimados.

O gateway fica atrás do Cloudflare, que recusa o `User-Agent` padrão do Python (HTTP 403, `error code: 1010`). O cliente envia `korda-harness/0.1`.

## Verificação

```bash
python3 -m unittest discover -s services/execution/tests/harness -t services/execution
```
