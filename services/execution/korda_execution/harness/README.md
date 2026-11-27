# Harness do executor (K08, K09, K10)

O harness escreve e corrige os modelos da demo `01_demo`. O worker cuida da ingestão, das ferramentas, dos limites e da revisão humana. A construção roteirizada e o cliente falso permitem exercitar o fluxo com custo de provedor zero. [Integração do worker](../construcao.py) · [Guia de execução](../../README.md)

## Planejar e construir

1. **Antes da aprovação 1**, `planejar` envia o contexto validado e o plano base para uma chamada de chat sem ferramentas. O documento cobre modelos, regras aplicadas, métricas, testes de aceite e premissas. Um bloco JSON declara `pronto_para_construir` e as perguntas. Quando faltam informações essenciais, o host grava `perguntas.json` com a lacuna, o indicador afetado, a pergunta e o motivo. A descoberta pode responder numa nova revisão.
2. **Quando a construção está pronta**, o planejador anexa o documento ao plano em `construction.document`, remove o bloco de decisão e recalcula `plan_version`. O revisor vê o texto e aprova a versão que o inclui. O planejamento registra sua própria resposta e medição no host.
3. **Na execução aprovada**, o worker prepara a landing N0 ou N1 e o adaptador protegido carrega a bronze no DuckDB. Em modo chat, o harness recebe exatamente o documento aprovado, a projeção do plano, os perfis das fontes e as ferramentas autorizadas. Na v0.2, escreve os cinco modelos prata e ouro em arquivos que começam vazios.
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
| `agente_sdk` | Adaptador experimental de correção do PR #27. O worker da demo recusa essa opção. |

O documento-base (construção) é gerado no `planejar`, com o prompt de [`documento_base.py`](../documento_base.py). Entram o contexto (sem metadados irrelevantes), o plano base e os nomes fixos de modelos e colunas ([`contrato_saida.py`](../contrato_saida.py)), lidos dos testes protegidos e de `vars.contrato_exportacao` no `dbt_project.yml`. A resposta começa com um bloco ```` ```json ```` com `pronto_para_construir` e `perguntas` (pergunta, lacuna, métricas afetadas, motivo), seguido das seções Modelos, Regras aplicadas, Métricas, Testes de aceite e Premissas e lacunas. O prompt pede evidência só pelo id, uma tabela por camada e até ~900 palavras por seção; a saída é limitada a 8.000 tokens, e uma resposta cortada é recusada. O prompt proíbe inventar regras. Lacuna que não impede construir fica em Premissas e lacunas. Se a lacuna impedir, a LLM gera as perguntas para a descoberta. Sem um bloco válido, nenhum plano é gerado. O bloco é removido antes de o documento entrar no plano como `construction`.

A v0.1 com `models/*` conserva esse escopo de construção. A fixture histórica que só autorizava alterar `prata_ctes.sql` usa a correção roteirizada original. Os dois casos entregam os três arquivos de resultados próprios da v0.1. [Contrato v0.1](../../../../packages/contracts/plan/v0.1.0/README.md)

## Variáveis

Exemplo em [`.env.example`](../../../../.env.example). Validadas por `ConfigHarness.de_ambiente()` ([`config.py`](config.py)).

| Variável | Padrão | Efeito |
| --- | --- | --- |
| `KORDA_EXECUTOR` | `roteirizado` | Use `roteirizado` para a demo local ou `chat` para o gateway habilitado. Os testes usam `falso` com injeção de cliente. |
| `KORDA_PERMITIR_LLM_REAL` | vazio | Precisa ser `1` para `chat` ou `agente_sdk` rodarem. Proteção contra gasto acidental. |
| `KORDA_LLM_CHAVE` | vazio | Chave do gateway (Feita) para `chat`. Fica no host; nunca vai para a sandbox, eventos ou logs. |
| `KORDA_LLM_URL` | `https://api.feita.ai/gateway/v1` | Base da API chat/completions. Só `https`. |
| `ANTHROPIC_API_KEY` | vazio | Variável do adaptador experimental de SDK. |
| `KORDA_MODELO` | `anthropic/claude-opus-5.5` (`chat`) ou `claude-opus-5-5` (`agente_sdk`) | Modelo. |
| `KORDA_ORCAMENTO_EXECUCAO_USD` | `8.00` | Teto estimado por invocação de planejamento. A execução aprovada usa um teto separado do mesmo valor para construção e correções. |
| `KORDA_MAX_TURNOS_CONSTRUCAO` | `40` | Limite de turnos da construção. |
| `KORDA_MAX_TURNOS_TENTATIVA` | `12` | Limite de turnos de cada correção. |
| `KORDA_PRECO_ENTRADA_USD_MTOK`, `KORDA_PRECO_SAIDA_USD_MTOK` | `4.00`, `20.00` | Preço por milhão de tokens usado para **estimar** o custo no `chat` (o gateway cobra em créditos). |
| `KORDA_TAXA_USD_BRL` | `6.00` | Conversão para centavos de real. Suposição da equipe, não cotação. |

Sem a chave ou sem `KORDA_PERMITIR_LLM_REAL=1`, os executores com LLM falham com mensagem clara. `KORDA_CORRETOR`, da versão anterior, é recusada com aviso.

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
| `rodar_dbt` | dbt com subcomandos em lista branca. A saída devolvida ao agente fica nos últimos 8.000 caracteres. |
| `consultar_sql` | SQL somente leitura no DuckDB da execução. |

Entradas fora do formato (campo faltando, campo extra, valor que não é texto) são recusadas sem chamar a ferramenta.

## O que o agente vê

[`contexto.py`](contexto.py) monta o contexto de cada tentativa:

- um prompt de sistema fixo, com as regras: só `editable_models`, nunca testes, fontes ou regras; se a correção exigir mudar regra, parar e explicar;
- o número da tentativa e o limite do plano;
- o erro do build, já cortado pelo worker;
- a versão, os modelos autorizados, os limites, os valores das regras, as fórmulas e os testes das métricas, além das tarefas em ordem de dependência;
- os perfis das fontes, cortados em 12.000 caracteres.

A chamada prévia de planejamento pode usar as evidências do contexto sintético. A projeção entregue às ferramentas omite as transcrições e o destino. As respostas esperadas em `evaluation/golden/` ficam fora das chamadas ao modelo.

## Medição

[`medicao.py`](medicao.py) acumula uma linha por tentativa e grava `medicao.json` (insumo da K14):

| Campo | Conteúdo |
| --- | --- |
| `run_id`, `executor`, `modelo` | Identificação. |
| `synthetic` | `true` para `roteirizado` ou `falso`. |
| `tentativas`, `turnos`, `duracao_s` | Número de sessões, turnos e duração registrados. |
| `tokens_entrada`, `tokens_saida`, `tokens_cache_leitura` | Soma dos tokens informados. |
| `custo_usd`, `custo_centavos` | Estimativa a partir dos tokens e preços configurados, convertida para centavos pela taxa configurada. |
| `custo_completo` | `false` se alguma tentativa não informou o custo. |
| `por_tentativa` | Detalhe de cada tentativa, inclusive arquivos escritos e motivo de parada. |

A construção de chat aparece como tentativa `0`. O worker grava em `revisao/<run>/medicao.json` a versão aprovada, a identificação do documento-base, o executor, as sessões, os builds e as correções. A chamada anterior de `planejar` tem seu próprio `medicao.json` em `planejamento/<versão>-<instante>/`. Para medir o custo total do processo, some os custos dos dois registros depois de conferir `custo_completo` em cada um. [Medição](medicao.py)

## Orçamento do executor `chat`

| Limite | Valor | Comportamento |
| --- | --- | --- |
| Orçamento total | `KORDA_ORCAMENTO_EXECUCAO_USD` (8,00) | Esgotado, a fase devolve `ok: False` sem chamar a API, e uma pessoa decide. |
| Construção | até 60% do orçamento de execução, com folga de 10% | Para com `error_max_budget_usd` e escala. |
| Cada correção | restante ÷ tentativas que faltam, com folga de 10% | Idem. |
| Turnos | 40 na construção, 12 por correção | Para com `error_max_turns`. |

O custo é **estimado**: tokens informados pelo gateway × `KORDA_PRECO_*`. A Feita cobra em créditos; a referência real é o saldo. Antes de cada chamada paga, o host confere a autorização, reserva uma estimativa conservadora dos tokens de entrada e limita os tokens de saída pelo saldo disponível. Uma resposta sem uso medido deixa o custo incompleto e interrompe novas chamadas pagas.

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
