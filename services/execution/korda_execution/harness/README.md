# Harness do executor (K08, K09, K10)

O harness escreve e corrige os modelos da demo `01_demo`. O worker cuida da ingestão, das ferramentas, dos limites e da revisão humana. A construção roteirizada e o cliente falso permitem exercitar o fluxo com custo de provedor zero. [Integração do worker](../construcao.py) · [Guia de execução](../../README.md)

## Planejar e construir

1. **Antes da aprovação 1**, `planejar` envia o contexto validado e o plano base para uma chamada sem ferramentas (`chat`, pela Feita, ou `claude_cli`, pelo login do plano). O documento cobre modelos, regras aplicadas, métricas, testes de aceite e premissas. Um bloco JSON declara `pronto_para_construir` e as perguntas. Quando faltam informações essenciais, o host grava `perguntas.json` com a lacuna, o indicador afetado, a pergunta e o motivo. A descoberta pode responder numa nova revisão.
2. **Quando a construção está pronta**, o planejador anexa o documento ao plano em `construction.document`, remove o bloco de decisão e recalcula `plan_version`. O revisor vê o texto e aprova a versão que o inclui. O planejamento registra sua própria resposta e medição no host.
3. **Na execução aprovada**, o worker prepara a landing N0 ou N1 e o adaptador protegido carrega a bronze no DuckDB. Em modo `chat` ou `claude_cli`, o harness recebe exatamente o documento aprovado, a projeção do plano, os perfis das fontes e as ferramentas autorizadas. Na v0.2, escreve os cinco modelos prata e ouro em arquivos que começam vazios.
4. **Na verificação**, o worker exige o build dbt e a exportação segundo o contrato protegido. Falhas de implementação podem voltar ao harness, até o limite de três correções do plano. Inconsistências nos dados de origem ou problemas de infraestrutura pedem intervenção. O avaliador confere os resultados fora da sandbox. Uma pessoa decide a promoção para o destino aprovado.

```
contexto (P1) ─▶ korda_planning (gabarito) ─▶ plano base
plano base + contexto ─▶ planejar: 1 chamada de API, sem ferramentas
        ├─ falta contexto ─▶ perguntas.json ─▶ descoberta (sem plano novo)
        └─ pronto ─▶ plano + construction (nova plan_version)
                                        │
                               aprovação 1 (cobre a construção)
                                        │
                                        ▼
                         executar: lote N0/N1 → landing → bronze; sandbox (sem rede, testes e fontes só leitura, models/ vazio)
                                        │
                                        ▼
               harness: construir_e_verificar(documento_base = construction.document)
                 1. ExecutorChat.construir(...)  → escreve bronze/prata/ouro
                 2. dbt build (testes protegidos) + exportação no contrato de saída
                 3. falhou? ExecutorChat(falha, tentativa)  → até 3 correções; depois, pede ajuda
                                        │
                                        ▼
                         worker: captura com hash (resultados, modelos, target, prata) → pacote de entrega (entrega.py) → aprovação 2 → promoção
```

O modelo nunca executa nada: ele só pede ferramentas. Cada pedido passa pela política ([`politica.py`](politica.py)) e só então vira um comando na sandbox. A chave fica no processo do host.

O retorno das perguntas à descoberta está disponível em arquivo. A ligação direta à interface e a aprovação dos papéis pelos responsáveis da equipe continuam como pontos de integração. [Planejamento da construção](../planejamento.py) · [Documento-base](../documento_base.py)

## Executores

| `KORDA_EXECUTOR` | Uso no worker |
| --- | --- |
| `roteirizado` | Padrão local. Escreve os modelos revisados que ficam no host e restaura os modelos autorizados que divergirem deles. O operador pode registrar o plano base diretamente. |
| `chat` | Usa a API chat/completions da Feita no host para planejar antes da aprovação e depois construir ou corrigir. A construção exige `construction` na versão aprovada e as chamadas consomem créditos. |
| `falso` | Usado por testes com cliente injetado. Exercita decisões e ferramentas com respostas preparadas. A construção também recebe um documento aprovado e a medição é sintética. |
| `claude_cli` | Usa o Claude Code CLI do host, autenticado pelo **login do plano pessoal** (`claude /login`, sem chave), para planejar, construir e corrigir. Mesma interface e mesmos tetos do `chat`. O custo informado pelo CLI é nocional; o limite real é a cota do plano. Ver [Executor `claude_cli`](#executor-claude_cli). |
| `agente_sdk` | Adaptador experimental de correção do PR #27. O worker da demo recusa essa opção. |

O documento-base (construção) é gerado no `planejar`, com o prompt de [`documento_base.py`](../documento_base.py). Entram o contexto (sem metadados irrelevantes), o plano base e os nomes fixos de modelos e colunas ([`contrato_saida.py`](../contrato_saida.py)), lidos dos testes protegidos e de `vars.contrato_exportacao` no `dbt_project.yml`. A resposta começa com um bloco ```` ```json ```` com `pronto_para_construir` e `perguntas` (pergunta, lacuna, métricas afetadas, motivo), seguido das seções Modelos, Regras aplicadas, Métricas, Testes de aceite e Premissas e lacunas. O prompt pede evidência só pelo id, uma tabela por camada e até ~900 palavras por seção; a saída é limitada a 8.000 tokens, e uma resposta cortada é recusada. O prompt proíbe inventar regras. Lacuna que não impede construir fica em Premissas e lacunas. Se a lacuna impedir, a LLM gera as perguntas para a descoberta. Sem um bloco válido, nenhum plano é gerado. O bloco é removido antes de o documento entrar no plano como `construction`.

A v0.1 com `models/*` conserva esse escopo de construção. A fixture histórica que só autorizava alterar `prata_ctes.sql` usa a correção roteirizada original. Os dois casos entregam os três arquivos de resultados próprios da v0.1. [Contrato v0.1](../../../../packages/contracts/plan/v0.1.0/README.md)

## Variáveis

Exemplo em [`.env.example`](../../../../.env.example). Validadas por `ConfigHarness.de_ambiente()` ([`config.py`](config.py)).

| Variável | Padrão | Efeito |
| --- | --- | --- |
| `KORDA_EXECUTOR` | `roteirizado` | Use `roteirizado` para a demo local, `chat` para o gateway habilitado ou `claude_cli` para o login do plano. Os testes usam `falso` com injeção de cliente. |
| `KORDA_PERMITIR_LLM_REAL` | vazio | Precisa ser `1` para `chat`, `claude_cli` ou `agente_sdk` rodarem. Proteção contra gasto acidental (créditos ou cota do plano). |
| `KORDA_LLM_CHAVE` | vazio | Chave do gateway (Feita) para `chat`. Fica no host; nunca vai para a sandbox, eventos ou logs. |
| `KORDA_LLM_URL` | `https://api.feita.ai/gateway/v1` | Base da API chat/completions. Só `https`. |
| `ANTHROPIC_API_KEY` | ausente | Variável do adaptador experimental de SDK. Com `claude_cli`, ela (e `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CODE_USE_BEDROCK/VERTEX/FOUNDRY`) não pode existir no ambiente, nem vazia. |
| `KORDA_MODELO` | `anthropic/claude-opus-5.5` (`chat`), `claude-opus-5-5` (`agente_sdk`) ou `sonnet` (`claude_cli`) | Modelo. No `claude_cli`, aceita os apelidos do CLI (`sonnet`, `opus`, `fable`) ou o nome completo. |
| `KORDA_ORCAMENTO_EXECUCAO_USD` | `8.00` | Teto estimado por invocação de planejamento. A execução aprovada usa um teto separado do mesmo valor para construção e correções. |
| `KORDA_MAX_TURNOS_CONSTRUCAO` | `40` | Limite de turnos da construção. |
| `KORDA_MAX_TURNOS_TENTATIVA` | `12` | Limite de turnos de cada correção. |
| `KORDA_PRECO_ENTRADA_USD_MTOK`, `KORDA_PRECO_SAIDA_USD_MTOK` | `4.00`, `20.00` | Preço por milhão de tokens usado para **estimar** o custo no `chat` (o gateway cobra em créditos). |
| `KORDA_TAXA_USD_BRL` | `6.00` | Conversão para centavos de real. Suposição da equipe, não cotação. |

Sem a chave ou sem `KORDA_PERMITIR_LLM_REAL=1`, os executores com LLM falham com mensagem clara. O `claude_cli` não usa chave: falha sem `KORDA_PERMITIR_LLM_REAL=1`, com credencial de API no ambiente ou sem login no CLI. `KORDA_CORRETOR`, da versão anterior, é recusada com aviso.

## Sandbox e ferramentas

A sandbox de construção recebe a landing aprovada em leitura e roda sem rede. O adaptador bronze, o exportador, as macros, os testes e a configuração permanecem em leitura. Em planos v0.2, os cinco arquivos SQL autorizados têm montagens individuais de escrita. Em planos de construção v0.1 com o padrão `models/*`, o diretório começa vazio em uma montagem de leitura. A ferramenta de escrita publica no host apenas arquivos SQL que correspondem ao padrão do plano, e eles ficam visíveis à sandbox. O código SQL de referência e o gabarito ficam no host. As permissões do Docker e a verificação de caminhos pelo worker atuam em conjunto. [Sandbox](../sandbox.py) · [Ferramentas restritas](../ferramentas.py) · [Política das ferramentas](politica.py)

O adaptador opcional de correção por SDK tem verificações próprias para limitar as ferramentas integradas, o diretório de trabalho e as configurações herdadas ao iniciar uma sessão. Sua implementação e as dependências ficam disponíveis para ensaios separados. [Adaptador SDK](agente_sdk.py) · [Dependências](../../../../requirements-harness.txt)

## Ferramentas do agente

O agente só enxerga seis ferramentas, descritas em [`ferramentas_agente.py`](ferramentas_agente.py) e expostas como `mcp__korda__<nome>`. O host valida cada pedido em `FerramentasRestritas` e o encaminha à montagem ou ao comando correspondente.

| Ferramenta | Efeito |
| --- | --- |
| `ler_plano` | Projeção do plano aprovado. |
| `inspecionar_fonte` | Perfil de uma fonte do catálogo autorizado. |
| `ler_arquivo` | Leitura de um arquivo do projeto dbt. |
| `escrever_modelo` | Escrita de SQL só em `editable_models`. |
| `rodar_dbt` | dbt com subcomandos em lista branca. A saída devolvida ao agente perde o progresso dos nós que passaram (cabeçalho, `START`, `OK`, `PASS`); erros, falhas, avisos e o placar `PASS=… ERROR=…` ficam, até 8.000 caracteres. A classificação da falha pelo worker usa a saída completa. |
| `consultar_sql` | SQL somente leitura no DuckDB da execução. |

Entradas fora do formato (campo faltando, campo extra, valor que não é texto) são recusadas sem chamar a ferramenta.

## O que o agente vê

[`contexto.py`](contexto.py) monta o contexto de cada tentativa:

- um prompt de sistema fixo, com as regras: só `editable_models`, nunca testes, fontes ou regras; se a correção exigir mudar regra, parar e explicar;
- o contrato de saída (modelos, colunas e fontes bronze), lido por código dos testes protegidos e de `vars.contrato_exportacao`, para o agente não gastar turnos lendo-os;
- o número da tentativa e o limite do plano;
- o erro do build, já cortado pelo worker;
- a versão, os modelos autorizados, os limites, os valores das regras, as fórmulas e os testes das métricas, além das tarefas em ordem de dependência (uma vez só: o bloco de tarefas sai da projeção);
- os perfis das fontes, cortados em 12.000 caracteres.

As regras dizem que não há modelos auxiliares (etapas intermediárias são CTEs nos cinco arquivos autorizados), pedem para escrever cedo, pedem `rodar_dbt build --select <modelo>+` durante a construção e um build completo no fim, e explicam que a bronze está no schema `main` (nos modelos, `source('sinteticas', …)`; em `consultar_sql`, `main.bronze_*`). O host consulta o `information_schema` antes da sessão e põe as colunas da bronze no prompt ([`construcao.py`](../construcao.py), `esquema_bronze`); os perfis aparecem como "perfis da landing", com os nomes crus de origem. O SQL de referência (`pipeline/projeto/models/*.sql`, plano B) nunca entra no prompt; há teste para isso.

**Histórico compactado.** A cada turno o histórico inteiro é reenviado. Só as saídas de ferramenta dos últimos 3 turnos seguem íntegras ([`sessao_chat.py`](sessao_chat.py), `MANTER_TURNOS`); as anteriores viram uma linha (`[saída antiga resumida: rodar_dbt build, erro, … Done. PASS=10 … ERROR=1 …]`), e o SQL das escritas correspondentes sai dos argumentos (o agente relê o modelo com `ler_arquivo`). Um resumo nunca muda depois de feito. A conta é por turno, não por saída: no ensaio-01, contando 4 saídas, o esquema da bronze sumia no turno seguinte a uma rodada de consultas paralelas e o agente o consultava de novo.

**Lembrete para escrever.** A cada 8 turnos (`TURNOS_ATE_ESCREVER`) sem escrita nova, o host acrescenta uma mensagem pedindo para escrever e usar o build para descobrir o que falta. Na construção, a mensagem lista os modelos de `editable_models` ainda não escritos e se repete enquanto faltar algum; na correção, pede a correção do modelo que falhou.

A chamada prévia de planejamento pode usar as evidências do contexto sintético. A projeção entregue às ferramentas omite as transcrições e o destino. As respostas esperadas em `evaluation/golden/` ficam fora das chamadas ao modelo.

## Medição

[`medicao.py`](medicao.py) acumula uma linha por tentativa e grava `medicao.json` (insumo da K14):

| Campo | Conteúdo |
| --- | --- |
| `run_id`, `executor`, `modelo` | Identificação. |
| `synthetic` | `true` para `roteirizado` ou `falso`. |
| `cobranca` | `api` (`chat`, `agente_sdk`: cobrado por uso), `assinatura` (`claude_cli`: custo nocional, dentro da cota do plano) ou `null` (sem LLM). |
| `tentativas`, `turnos`, `duracao_s` | Número de sessões, turnos e duração registrados. |
| `tokens_entrada`, `tokens_saida`, `tokens_cache_leitura` | Soma dos tokens informados. |
| `custo_usd`, `custo_centavos` | Estimativa a partir dos tokens e preços configurados, convertida para centavos pela taxa configurada. |
| `custo_completo` | `false` se alguma tentativa não informou o custo. |
| `por_tentativa` | Detalhe de cada tentativa, inclusive arquivos escritos e motivo de parada. |

Um erro HTTP do gateway inclui até 240 caracteres do corpo da resposta (com a chave trocada por `[chave]`), para mostrar o motivo, por exemplo crédito restrito a outro modelo. Cada `agent_finished` em `eventos.jsonl` traz também `ferramentas` (o catálogo `mcp__korda__*` oferecido à sessão), `tokens_por_turno` (`[entrada, saída]` informados pelo gateway em cada chamada) e, quando a API falhou, `erro_api` com a mensagem do `ErroLLM` (código HTTP ou tipo de falha de rede, nunca a chave).

A construção de chat aparece como tentativa `0`. O worker grava em `revisao/<run>/medicao.json` a versão aprovada, a identificação do documento-base, o executor, as sessões, os builds e as correções. A chamada anterior de `planejar` tem seu próprio `medicao.json` em `planejamento/<versão>-<instante>/`. Para medir o custo total do processo, some os custos dos dois registros depois de conferir `custo_completo` em cada um. [Medição](medicao.py)

## Executor `claude_cli`

Roda planejamento, construção e correção pelo CLI do Claude Code instalado no host (`claude`), autenticado pelo login do plano pessoal. Não usa chave de API. Código: [`agente_sdk.py`](agente_sdk.py) (`ExecutorClaudeCli`, `ClienteClaudeCli`, `rodar_sessao_cli`), pelo `claude-agent-sdk` ([`requirements-harness.txt`](../../../../requirements-harness.txt)).

**Portões.** `KORDA_EXECUTOR=claude_cli` e `KORDA_PERMITIR_LLM_REAL=1`, autorizado pelo dono do login. A configuração recusa iniciar se `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX` ou `CLAUDE_CODE_USE_FOUNDRY` existirem no ambiente, mesmo vazias: qualquer uma faria o CLI cobrar de outra conta. Antes de reservar o run (e antes do `planejar`), o host roda `claude auth status --json`, que não gasta cota, e exige `loggedIn`, `authMethod = claude.ai` e `apiProvider = firstParty`. Só o método e o tipo do plano são lidos; e-mail e organização não saem dali.

**Ambiente mínimo.** O SDK monta o ambiente do CLI como `os.environ` + `options.env` e não consegue remover variáveis. Por isso o `cli_path` aponta para um lançador gerado por sessão (numa pasta temporária, apagada no fim), que troca o ambiente inteiro por `HOME`, um `PATH` fixo, `USER`, `LANG`/`LC_ALL`, as variáveis que o próprio SDK passa (`CLAUDE_CODE_ENTRYPOINT`, `CLAUDE_AGENT_SDK_VERSION`, `CLAUDE_CODE_SDK_READS_SESSION_STATE`, `PWD`) e quatro que cortam tráfego fora da conversa (`DISABLE_AUTOUPDATER`, `DISABLE_TELEMETRY`, `DISABLE_ERROR_REPORTING`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`). `KORDA_LLM_CHAVE`, o resto do `.env` e qualquer `ANTHROPIC_*` não chegam ao CLI; se uma credencial de API chegar ao lançador, ele sai com código 97 sem executar o CLI.

**Isolamento da sessão.** O mesmo do `agente_sdk`: `--tools ""`, as embutidas em `--disallowedTools`, só as seis `mcp__korda__*` liberadas (num servidor MCP em processo que chama `despachar` → `FerramentasRestritas` → sandbox), `permission_mode = dontAsk`, o hook `politica.hook_pre_tool_use`, cwd numa pasta vazia e `setting_sources = []`. A mais: `--strict-mcp-config` (ignora o MCP do usuário), `--safe-mode` (desliga CLAUDE.md, skills, plugins, hooks e comandos do usuário, mantendo o login) e `--no-session-persistence` (a conversa não fica em `~/.claude/projects`). `--bare` não serve: nele o CLI nunca lê o login OAuth. O CLI roda no host, mas sem ferramenta de arquivo ou de shell: só enxerga o que as seis ferramentas devolvem, nunca o repositório, `evaluation/golden/` nem `pipeline/projeto/models/*.sql`.

**Conferência do init.** Antes do primeiro turno do modelo (abortar ali não gasta cota), a sessão é abortada com `ErroSegurancaHarness` se o init listar ferramenta fora de `mcp__korda__*`, faltar alguma das seis, aparecer servidor MCP além de `korda`, plugin, `apiKeySource` diferente de `none`, ou skill, agente ou comando com o nome de algum item de `~/.claude/skills`, `~/.claude/agents` ou `~/.claude/commands`. No planejamento, a sessão não tem servidor MCP nem ferramenta alguma.

**Custo e limites.** O `total_cost_usd` do CLI é **nocional** (preço de tabela da API), não cobrança: a medição e os eventos levam `custo_estimado: true` e `cobranca: "assinatura"`. Ele segue como freio, com os mesmos tetos do `chat` (60% do orçamento na construção, o restante dividido pelas correções, folga de 10%) em `max_budget_usd`, e `max_turns` 40 na construção e 12 por correção. O CLI só confere o teto depois do turno; até a fatia sem a folga, o resultado é aceito. O limite real é a cota do plano: se a sessão parar por limite de uso (`RateLimitEvent` com `status = rejected`, erro `rate_limit` ou HTTP 429), o motivo vai para `erro_api`, a fase devolve `codigo: limite_uso` e o executor não abre outra sessão naquela execução: o ciclo escala para uma pessoa, sem nova tentativa. O modelo padrão é `sonnet`, porque a cota do plano Pro acaba rápido com o Opus numa construção de 40 turnos. No `planejar`, o `medicao.json` guarda a estimativa pelos `KORDA_PRECO_*` (como no `chat`) e, à parte, `custo_nocional_cli_usd`.

**Diferenças em relação ao `chat`.** O loop de turnos é o do CLI, não o de [`sessao_chat.py`](sessao_chat.py): não há compactação de histórico (o CLI usa cache de prompt) nem o lembrete de modelos que faltam; o prompt da construção já lista os modelos obrigatórios. `tokens_entrada` soma tokens novos, criação e leitura de cache.

**Pendências.** (1) Falta o ensaio real; até lá, o comportamento do `--safe-mode` junto com o MCP em processo e a lista exata do init estão verificados só com mensagens roteirizadas. Se o `--safe-mode` desligar o servidor `korda`, a sessão aborta no init (sem gastar cota) e a saída é tirar o `--safe-mode`, mantendo `--strict-mcp-config` e `setting_sources = []`. (2) Isolar `HOME`/`CLAUDE_CONFIG_DIR` exigiria copiar a credencial OAuth, e a renovação do token na cópia pode invalidar o login principal; por isso não foi feito. (3) **Plano B**, se o SDK não aceitar a assinatura: chamar `claude -p --output-format stream-json` direto, com `--mcp-config` para um servidor MCP stdio que encaminha as seis ferramentas para `FerramentasRestritas` no host, `--strict-mcp-config`, `--allowedTools "mcp__korda__*"`, `--tools ""`, `--disallowedTools` com as embutidas, `--max-turns` e `--model`, lendo o `init` e o `result` do stream. Não implementado.

## Orçamento do executor `chat`

| Limite | Valor | Comportamento |
| --- | --- | --- |
| Orçamento total | `KORDA_ORCAMENTO_EXECUCAO_USD` (8,00) | Esgotado, a fase devolve `ok: False` sem chamar a API, e uma pessoa decide. |
| Construção | até 60% do orçamento de execução, com folga de 10% | Para com `error_max_budget_usd` e escala. |
| Cada correção | restante ÷ tentativas que faltam, com folga de 10% | Idem. |
| Turnos | 40 na construção, 12 por correção | Para com `error_max_turns`. |

O custo é **estimado**: tokens informados pelo gateway × `KORDA_PRECO_*`. A Feita cobra em créditos; a referência real é o saldo. Antes de cada chamada paga, o host confere a autorização, reserva uma estimativa conservadora dos tokens de entrada e limita os tokens de saída pelo saldo disponível. Uma resposta sem uso medido deixa o custo incompleto e interrompe novas chamadas pagas.

## Custo estimado da construção (simulador)

[`tests/harness/simulador_custo.py`](../../tests/harness/simulador_custo.py) roda a sessão com um cliente roteirizado e mede o que seria enviado em cada turno. É **estimativa**: caracteres ÷ 4 do JSON de mensagens + catálogo, sem tokenizer, com os preços padrão (4/20 US$ por MTok). Os arquivos lidos são os do projeto protegido; o SQL escrito é enchimento com tamanho típico. Roteiro típico: ler o plano, `exportar.py`, 2 testes, 3 perfis, 2 consultas, 5 modelos, 3 builds e 1 correção. Longo: lê tudo, 3 correções (31 turnos).

```bash
cd services/execution && python3 -m tests.harness.simulador_custo
```

| Cenário | Turnos | Entrada acumulada (antes → depois) | US$ (antes → depois) | US$ depois, ×2,2 |
| --- | ---: | ---: | ---: | ---: |
| Típico | 18 | 217 mil → 148 mil | 0,99 → 0,71 | 1,42 |
| Típico, com descoberta no prompt e builds seletivos (supõe que o agente pula 2 leituras) | 16 | 178 mil → 129 mil | 0,83 → 0,63 | 1,25 |
| Longo (3 correções) | 31 | 518 mil → 275 mil | 2,26 → 1,28 | 2,60 |

"Antes" é a `main` em 4560e5e. A compactação do histórico responde pela maior parte (típico sem ela: 0,97; longo: 2,21). O dbt enxuto e o prompt sem tarefas repetidas somam cerca de 3%. Cada correção começa uma sessão nova e não entra nesta tabela.

**Calibração pelo ensaio-01.** Um roteiro equivalente ao do ensaio real (mesmo documento, perfis e plano; 18 turnos, ~25 consultas, 5 `dbt ls`) é estimado em 152 mil tokens de entrada; o gateway informou 338 mil. A coluna "×2,2" aplica esse fator à entrada. Não se sabe ainda se a diferença é um custo fixo por chamada (catálogo de ferramentas e enquadramento do provedor) ou a tokenização do português; `tokens_por_turno` no próximo ensaio responde. Mesmo calibrado, o cenário longo (US$ 2,60) fica abaixo do teto da construção com orçamento de 7,50 (60% × 0,9 = US$ 4,05) ou de 5,00 (US$ 2,70); os 40 turnos param a sessão antes do dinheiro, e os limites não mudaram.

**Cache de prefixo:** não verificado. A página da Feita indicada (feita.ai/api-keys) não expõe documentação legível sem login, e não houve chamada real para testar. `tokens_cache_leitura` segue 0. Se o gateway fizer cache de prefixo, a compactação reduz o acerto apenas na fronteira que avança a cada turno.

## Ensaios reais da construção

| Ensaio | Plano | Resultado | Turnos | Tokens (entrada / saída) | US$ estimado | Duração |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| `ensaio-01` (27/11/2026) | `924f1ce5…` (v0.2, `planejar` real, US$ 0,139) | **Não aprovado.** Nenhum modelo escrito; a chamada do turno 19 falhou na API (`error_during_execution`, mensagem não registrada na época; provavelmente saldo esgotado, ver ensaio-02), custo incompleto, sem build nem avaliação | 18 | 338.174 / 6.417 | 1,48 + a chamada que falhou | 108 s |
| `ensaio-02` (27/11/2026) | o mesmo, com as correções abaixo | **Não rodou.** A primeira chamada recebeu HTTP 402 do gateway, registrado em `erro_api`. O corpo da resposta (lido depois pelo teste de fumaça) diz `insufficient_credits`: o crédito restante da conta só vale para `deepseek/deepseek-v4.1-flash-1017`, não para `anthropic/claude-opus-5.5` | 0 | 0 / 0 | 0 | 0,5 s |
| `ensaio-03` (27/11/2026) | o mesmo; construção com `deepseek/deepseek-v4.1-flash-1017` (o crédito da conta só vale para ele) e teto de 5,00 | **Não aprovado.** Escreveu os 5 modelos (1,1 a 4,5 kB cada); 5 builds `--select prata_ctes+` falharam; parou no teto da construção (`orçamento insuficiente para a próxima chamada`), o que na época contava como erro e não levou às correções. Os SQL e o erro do dbt não foram guardados | 34 | 510.294 / 20.692 | 2,46 **com os preços do Opus**; o DeepSeek custa bem menos | 181 s |
| `ensaio-04` (28/11/2026) | o mesmo; DeepSeek, teto de 7,50 (construção até 4,05) | **Não aprovado.** Ciclo completo: construção (40 turnos, 31 consultas, só `prata_ctes` escrito), 3 builds e 3 correções (escreveu `prata_rateios`), depois pedido de intervenção. Os builds falharam em `rastreabilidade_cte` (`p.sha256` ausente em `prata_ctes`) e em `contrato_exportacao` (`ouro_kpis` nunca escrito). SQL guardados em `falha/models/` | 76 | 1.080.446 / 30.172 | 4,93 com os preços do Opus | 317 s |
| `ensaio-05` (28/11/2026) | o mesmo; DeepSeek, teto de 7,50, com o contrato completo e o lembrete de modelos que faltam | **Build aprovado, avaliação reprovada.** Escreveu os 5 modelos na construção (parou nos 40 turnos); o build com os testes protegidos e a exportação passou de primeira, sem correções; a execução chegou a `aguardando_aprovacao_entrega`. O avaliador offline (fora do fluxo) acusou 4.259 divergências, todas de unidade: custos por pedido e viagem em centavos (gabarito em reais) e `ocupacao` por viagem em porcentagem (gabarito em fração). Os 3 KPIs batem com o gabarito na 4ª casa | 40 | 658.388 / 26.393 | 3,16 com os preços do Opus | 228 s |

O que o ensaio-01 mostrou, e o que mudou depois dele: o agente só investigou (~25 consultas e 5 `dbt ls`); repetiu 4 vezes a consulta ao `information_schema`, porque a compactação contava saídas e não turnos; tentou `sinteticas.bronze_documentos` em SQL direto, induzido pela redação do prompt; e o erro da API não foi registrado. Correções: compactação por turnos, colunas da bronze no prompt pelo host, regra sobre o schema `main`, lembrete para escrever e `erro_api` / `tokens_por_turno` nos eventos. Depois do ensaio-03: o teto atingido antes de uma chamada vira `error_max_budget_usd` (o que foi escrito segue para o build e as correções); numa falha, o worker guarda os SQL autorizados em `revisao/<run>/falha/models/` (evento `models_preserved`, fora da entrega); e `dbt_failed` traz `diagnostico`, o trecho final do erro sem o progresso.

Depois do ensaio-04: o contrato de saída passou a ler também as colunas usadas pelo apelido do modelo nos testes (`p.sha256`, `p.carga` em `rastreabilidade_cte`); antes, `prata_ctes` aparecia sem elas, no prompt da construção e no do planejamento. E o lembrete passou a listar e repetir os modelos que faltam.

Lição do ensaio-05: o `contrato_exportacao` confere nomes e tipos, não unidades. A unidade de cada coluna de detalhe (reais ou centavos, fração ou porcentagem) não chega ao agente pelo contrato; falta decidir se ela entra no contrato protegido ou só no prompt (pendência, sem mudança de teste nesta branch).

**Preço por modelo.** O custo e os tetos usam `KORDA_PRECO_ENTRADA_USD_MTOK` e `KORDA_PRECO_SAIDA_USD_MTOK` (padrão 4/20, do Opus). Com outro modelo, configure os preços dele; senão a estimativa fica pessimista e a sessão para cedo, como no ensaio-03. No ensaio-03 o primeiro turno teve 9,4 mil tokens e o maior, 20,3 mil (`tokens_por_turno`). Segurança no ensaio: hashes de `tests/` e `definicoes/` intactos, nenhuma recusa, só ferramentas `mcp__korda__*`. As correções ainda não foram exercidas com LLM real: o ensaio-02 parou por falta de créditos antes do primeiro turno.

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
python3 -m korda_execution.harness.adaptador_eventos "../../runs/worker/revisao/$RUN_ID/eventos.jsonl" --synthetic
```

Perguntas em aberto para o José: como representar o escalonamento (`intervention_requested`) e a avaliação no grafo; se `attempt` 4 vira `null` ou o schema passa a aceitar 4; se o front pode carregar esta exportação no lugar do seed.

## Contratos de que dependemos

O harness depende só de pontos estreitos, definidos em [`tipos.py`](tipos.py):

- `Corretor`: mesma assinatura do `corrigir(falha, tentativa)` do worker (#21). Devolve `{"ok", "erro"?, "custo_centavos"}`. `ok: True` quer dizer "apliquei uma alteração"; quem julga é o rebuild. Custo `None` significa desconhecido, e o ciclo escala em vez de assumir zero.
- `FerramentasAgente`: espelha os seis métodos de `FerramentasRestritas` do #21 (`ler_plano`, `inspecionar_fonte`, `ler_arquivo`, `escrever_modelo`, `rodar_dbt`, `consultar_sql`) sem importar a classe.
- `usd_para_centavos`: converte o custo do SDK (USD) em centavos de real, arredondando para cima.

## Teste de conectividade do gateway

O módulo de fumaça pede ao modelo uma chamada fictícia `ping` e envia a resposta como mensagem `role: tool`. É uma verificação opcional de protocolo, independente do aceite da construção. Para rodá-la após configurar e autorizar o gateway no host, use `KORDA_EXECUTOR=chat python -m services.execution.korda_execution.harness.fumaca` na raiz do repositório. [Teste de conectividade](fumaca.py)

## Verificação

```bash
python3 -m unittest discover -s services/execution/tests/harness -t services/execution
```
