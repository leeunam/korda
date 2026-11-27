# Worker de execução da Korda

A demo transforma as fontes da transportadora fictícia `01_demo` em frete por entrega, OTIF e ocupação. O operador aprova a versão do plano que autoriza o trabalho. Depois do build com os testes protegidos e o contrato de saída, o worker guarda a infra construída e monta o pacote de entrega. Uma segunda decisão humana autoriza promover a entrega para o destino local daquele plano; não há comparação com gabarito no fluxo. [Planejador](../planning/README.md) · [Pipeline logístico](pipeline/README.md) · [Avaliador](../../evaluation/worker/README.md)

1. **Planejamento da construção (`planejar`, antes da aprovação 1).** Uma chamada à API da Feita transforma o plano base (gabarito do [planejador](../planning/README.md)) e o contexto da descoberta no plano de construção. A própria LLM decide se há contexto para construir. Se houver, o documento entra no plano como `construction`, com nova `plan_version`, e a aprovação 1 cobre o que a LLM planejou. Se não houver, ela gera perguntas para a descoberta em `perguntas.json`, e nenhum plano novo é gerado.
2. **Sandbox.** Contêiner sem rede, com `models/` vazio.
3. **Harness.** O [harness](korda_execution/harness/README.md) constrói frete por entrega, OTIF e ocupação com DuckDB/dbt e corrige até três vezes. O loop roda no worker e conversa com a API da Feita; cada ferramenta que o modelo pede executa dentro da sandbox, e a chave nunca entra nela.
4. **Entrega.** O worker guarda a infra construída (modelos, target do dbt e a prata em Parquet) e monta o pacote de entrega em dados para o front. Uma segunda decisão humana autoriza a cópia para uma pasta local. Não há comparação com gabarito no fluxo (decisão de 27/11/2026): o [avaliador independente](../../evaluation/worker/README.md) é só ferramenta offline de medição. O [planejamento da integração](../../docs/plano-integracao-worker.md) situa essa entrega nas 17 issues do projeto.

Para operar a partir de uma entrevista do WhatsApp, siga [Da entrevista à entrega no painel local](../../docs/entrevista-planejamento-painel.md).

## Escolher a ingestão

| Plano | O que a execução lê | Linhagem disponível |
| --- | --- | --- |
| N0 · arquivos exportados | Cinco CSVs do ERP/TMS e os XMLs de CT-e entram no contêiner de ingestão. O formato de saída é Parquet com manifesto. | Arquivo e linha para registros de CSV. Arquivo, chave e SHA-256 para cada parcela de CT-e usada no custo. |
| N1 · sistemas simulados | O simulador da 01 alimenta o ERP em PostgreSQL, o TMS por API e uma pasta de entrega de CT-e. A ingestão de referência segue a proposta aprovada e materializa as tabelas na mesma estrutura de landing. | Origem lógica, chave da entidade e carga para ERP/TMS. Arquivo de entrega, SHA-256, chave, carga e centavos para CT-e. |

O plano `plan/v0.2.0` vincula nível, janela, proposta de ingestão e os cinco caminhos SQL editáveis à versão aprovada. A proposta N1 precisa corresponder à empresa, ao projeto e à revisão do contexto. Para N1 integral, o worker percorre o replay até a última data. Num corte parcial, registra a ingestão e a necessidade de uma referência do mesmo período. A avaliação mensal da 01 só autoriza o lote integral. [Contrato do plano](../../packages/contracts/plan/v0.2.0/README.md) · [Proposta de ingestão](../../packages/contracts/ingestion_plan/v0.1.0/README.md)

Planos históricos v0.1 usam N0. A versão que autoriza `models/*` constrói os modelos sob esse escopo. A fixture mais antiga, que autorizou apenas corrigir `models/prata_ctes.sql`, continua executável pelo caminho roteirizado original. O manifesto da entrega v0.1 contém os três arquivos de resultados. A v0.2 acrescenta a ingestão N0/N1 ao mesmo pacote de entrega. [Contrato legado](../../packages/contracts/plan/v0.1.0/README.md)

## Preparar o ambiente e o plano

Na raiz do repositório, use Python 3.11 ou superior e um usuário sem root com acesso a Docker. Para o primeiro ensaio, escolha a construção roteirizada, que usa os modelos de referência e tem custo de provedor zero. O consumo de CPU, memória, disco e tempo depende do host.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-worker.txt
docker build -t korda-sandbox:dev infra/sandbox
python data/synthetic/generator/generate.py --empresa 01_demo
export KORDA_EXECUTOR=roteirizado
mkdir -p runs/preparo
```

Para N0, gere o plano base com a revisão confirmada. O valor zero é a estimativa de custo de provedor para o ensaio roteirizado. Para usar o gateway, informe a estimativa aprovada para o ensaio em centavos no comando que gera o plano.

```bash
python -m services.planning.korda_planning \
  packages/contracts/context/v0.1.0/examples/02_rateio_confirmado.json \
  --nivel-ingestao n0 --destino revisao-logistica --custo-estimado-centavos 0 \
  > runs/preparo/plano-n0.json
```

Para N1, prepare também as imagens dos sistemas simulados e forneça o documento de ingestão. A omissão de `--ate-dia` seleciona o lote completo. `--ate-dia 2026-09-02` exemplifica um corte para testar o diagnóstico de janela parcial. As credenciais dos serviços são temporárias e ficam no ambiente do simulador.

```bash
docker build -t korda-simulados:dev infra/sistemas-simulados
docker pull postgres:17.6-alpine
python -m services.planning.korda_planning \
  packages/contracts/context/v0.1.0/examples/02_rateio_confirmado.json \
  --nivel-ingestao n1 \
  --proposta-ingestao packages/contracts/ingestion_plan/v0.1.0/examples/01_demo.json \
  --destino revisao-logistica --custo-estimado-centavos 0 \
  > runs/preparo/plano-n1.json
```

## Revisar, executar e entregar

Escolha o plano base de N0 ou de N1. O exemplo usa N1. No modo padrão `roteirizado`, registre o plano base diretamente. A construção usa os modelos de referência do host.

```bash
PLANO=runs/preparo/plano-n1.json
```

Para construção por chat, configure as variáveis do gateway no host e rode `planejar` **antes da primeira aprovação**. Essa chamada usa o contexto que originou o plano e pede à API da Feita um documento de construção ou perguntas para a descoberta. Escolha uma saída nova para essa revisão.

```bash
KORDA_EXECUTOR=chat python -m services.execution.korda_execution planejar "$PLANO" \
  --contexto packages/contracts/context/v0.1.0/examples/02_rateio_confirmado.json \
  --saida runs/preparo/plano-construcao.json
```

- **Código 0** indica que o documento entrou em `construction`. A nova `plan_version` cobre esse texto. Para seguir pelo gateway, defina `PLANO=runs/preparo/plano-construcao.json` e `export KORDA_EXECUTOR=chat`.
- **Código 3** indica perguntas. Consulte `perguntas.json` na pasta indicada pelo comando, devolva as lacunas à descoberta e gere outro plano base a partir da revisão respondida. A pasta mantém `documento_base.md`, `resposta.json` e `medicao.json` dessa chamada. O fluxo só chega ao registro quando houver uma versão pronta.
- O gateway requer `KORDA_PERMITIR_LLM_REAL=1` e `KORDA_LLM_CHAVE` no host. A chamada de planejamento tem medição própria e até 8.000 tokens de saída. O teto em USD é aplicado separadamente ao planejamento e à execução aprovada. A suíte usa transporte local para verificar as duas respostas. [Planejamento da construção](korda_execution/planejamento.py) · [Configuração e medição](korda_execution/harness/README.md)

O `planejar` faz uma chamada (saída limitada a 8.000 tokens e ao orçamento autorizado) e grava em `runs/worker/planejamento/<versão>-<instante>/`: `documento_base.md`, `resposta.json` (resposta bruta), `medicao.json` (tokens e custo estimado) e, conforme a decisão da LLM, `plano.json` ou `perguntas.json`. Sai com código 0 quando o plano está pronto e 3 quando há perguntas. As perguntas trazem pergunta, lacuna, métricas afetadas e motivo, mais `plan_version`, `context_id` e `context_revision`; voltam para a descoberta, e uma nova revisão de contexto gera outro plano base. Como a plataforma consome esse arquivo ainda está em aberto (P1/P4).

A mensagem leva o contexto sem metadados que não ajudam a planejar (fontes só com id e tipo, `confirmed_by` só com o papel) e os **nomes fixos** do pipeline, lidos por código em [`contrato_saida.py`](korda_execution/contrato_saida.py): modelos e colunas dos testes protegidos (`pipeline/projeto/tests/*.sql`) e de `vars.contrato_exportacao` no `dbt_project.yml`. A decisão vem no início da resposta, para um corte não apagá-la. Se a resposta bater no teto (`finish_reason = length`), o `planejar` falha com "resposta cortada no limite de N tokens" e não gera plano.

Defina `REVISOR` com a identificação de quem tomou a decisão e `RUN_ID` com um identificador novo. O registro em SQLite guarda a pessoa declarada pelo operador, a decisão, a versão e o instante UTC.

```bash
RUN_ID=demo-n1-001
VERSAO=$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["plan_version"])' "$PLANO")
python -m services.execution.korda_execution registrar "$PLANO"
```

Depois da conferência do plano pela pessoa responsável, o operador pode registrar a decisão e iniciar o processamento.

```bash
python -m services.execution.korda_execution decidir-plano demo-01 "$VERSAO" aprovar --pessoa "$REVISOR"
python -m services.execution.korda_execution executar "$PLANO" --run-id "$RUN_ID"
python -m services.execution.korda_execution consultar "$RUN_ID"
```

Em `runs/worker/revisao/<run_id>/`, consulte `ingestao.json` para identificar a origem e a janela, `fontes.json` para o perfil, `documento_base.md` para a especificação usada pelo construtor, `medicao.json` para tentativas, tokens e custo estimado (`synthetic: true` sem LLM real), e `eventos.jsonl` para a sequência de ações. Em `resultados/` ficam `kpis.json`, `por_pedido.csv` e `por_viagem.csv`. Em `infra/` ficam os `models/*.sql` que o harness escreveu, `manifest.json`, `catalog.json` e `run_results.json` do dbt e as tabelas `prata_*` em Parquet com `linhas.json`, capturados com hash antes de destruir a sandbox. Em `entrega/` fica o pacote de entrega descrito abaixo. O registro verifica o manifesto antes da promoção.

O revisor confere o destino, o conteúdo e o manifesto daquela execução antes de autorizar a promoção. O comando também aceita `rejeitar`. A promoção grava a entrega em `runs/worker/entregas/<destino>/<run_id>/`. A opção global `--raiz`, antes do subcomando, permite escolher outra raiz do operador.

```bash
python -m services.execution.korda_execution decidir-entrega "$RUN_ID" aprovar --pessoa "$REVISOR"
python -m services.execution.korda_execution promover "$RUN_ID" revisao-logistica
```

O pacote inteiro aparece em `runs/worker/entregas/revisao-logistica/demo-001/`. O identificador da execução é de uso único. O operador pode escolher uma raiz privada alternativa com a opção global `--raiz` antes do subcomando. O banco SQLite guarda o histórico inclusive após reinício. Uma versão substituída ou rejeitada invalida as autorizações pendentes.

## Pacote de entrega (K13)

Ao fim de uma execução concluída (build, testes protegidos e contrato de saída), o worker monta `revisao/<run>/entrega/` ([`entrega.py`](korda_execution/entrega.py)), sem LLM e só com o que a execução produziu e o plano aprovado no registro. Se a montagem falhar, o evento `package_failed` fica registrado e a execução continua válida. Para remontar (por exemplo, depois de mudar o formato):

```bash
python -m services.execution.korda_execution empacotar demo-001
```

| Arquivo | Conteúdo |
| --- | --- |
| `entrega.json` | Contrato para o front (`entrega_version` 0.1.0, provisório): KPIs com fórmula, regras e conta refeita a partir de `dados/`; regras com evidência, trecho do SQL e teste; tabelas prata (arquivo, hash, linhas, colunas, origem); estrutura técnica (camadas, fontes, modelos, testes com status do build e dependências); `indisponivel` para insumos ausentes. |
| `projeto_dbt/` | Modelos escritos pelo agente, `dbt_project.yml`, `profiles.yml` (caminhos da sandbox, sem segredo), `definicoes/`, `tests/`, `macros/`, `ingerir.py`, `exportar.py`, `regras.json` (valores das regras do plano) e um `README.md` para rodar de novo na mesma imagem, sem rede. |
| `dados/` | `kpis.json`, `por_pedido.csv`, `por_viagem.csv` e `prata/`: cada tabela `prata_*` em Parquet e `linhas.json`. |
| `docs_dbt/` | `manifest.json`, `catalog.json` (se o `dbt docs generate` funcionou) e o `run_results.json` do build. |
| `decisoes.md` | Para cada regra: valor, evidência (`excerpt` e `locator`), métricas afetadas e o teste que a garante. |
| `execucao.md` | Tentativas, recusas da política, falhas, correções, custo estimado e tempo, a partir de `eventos.jsonl` e `medicao.json`. |
| `manifesto.json` | sha256 de cada arquivo do pacote e a cópia do manifesto da aprovação 2. |

O vínculo regra → modelo → teste não existe no plano: vem de uma tabela de domínio versionada em `entrega.py` (`REGRAS_DOMINIO`). O trecho de SQL é localizado por palavra-chave no modelo do agente e rotulado assim; se não for encontrado, sai `localizado: false` com o início do modelo. Regras sem teste dbt (cancelamento, sábado, no prazo, completo, sem data, unidade da ocupação) aparecem como "sem teste automatizado: conferir na revisão humana". A `conta` de cada KPI é refeita a partir de `dados/*.csv` e conferida com `kpis.json`: é consistência interna, não comparação com gabarito. O pacote nunca lê `evaluation/golden/`. É saída de execução e fica em `runs/`, fora do Git. A visualização fica no front (P4), que vai consumir o `entrega.json`.

## Construção e correção

| Executor | Construção, correção e medição |
| --- | --- |
| `roteirizado` | Padrão. Escreve os modelos SQL de referência pelos caminhos autorizados. O custo de provedor é zero. |
| `falso` | Transporte de teste injetado no host. Exercita a construção a partir de `construction`, uma falha de dbt e sua correção. A medição é sintética. |
| `chat` | O gateway no host recebe o documento já aprovado e ferramentas para construir e corrigir os modelos. O operador acompanha turnos, tokens e custo estimado. |
| `agente_sdk` | Adaptador experimental de correção preservado no harness. O worker da demo recusa esse modo. |

Para os planos de construção, os modelos começam sem SQL de referência na sandbox. O adaptador protegido apresenta a landing como tabelas bronze. O harness escreve prata e ouro, executa `dbt build` com os testes protegidos e verifica a exportação. Falhas de implementação podem voltar para até três correções. Esgotar o limite, identificar uma inconsistência de dados ou perder a infraestrutura requer intervenção. Mudar uma regra, o escopo dos modelos, a construção ou a ingestão exige reconsiderar a versão a aprovar. [Harness e variáveis](korda_execution/harness/README.md) · [Ciclo de correção](korda_execution/correcao.py)

## Montagens e credenciais

| Etapa | Acesso concedido |
| --- | --- |
| Ingestão N0 | Contêiner efêmero sem rede, arquivos autorizados em leitura e landing de saída. |
| Ingestão N1 | Contêiner efêmero na rede interna do simulador. O código de ingestão e o plano são de leitura, a landing recebe as cargas e o processo recebe credenciais temporárias dos serviços. |
| Construção e testes dbt | Contêiner sem rede. `/work/fontes` contém a landing com manifesto em leitura. O projeto protegido inclui macros, definições e testes. Na v0.2 há uma montagem gravável por modelo autorizado, além de `/work/saida`. No escopo histórico `models/*`, o host publica pelas ferramentas os arquivos SQL autorizados sobre a montagem de leitura. |
| Conclusão e entrega | O host encerra o produtor e verifica tipo, tamanho e hash de resultados, modelos, target e prata. A execução fica `aguardando_aprovacao_entrega` quando build, testes protegidos e contrato de saída passaram; não há comparação com gabarito no fluxo (medir contra o gabarito, K11/K14, é um passo offline com o [avaliador](../../evaluation/worker/README.md), que lê as respostas esperadas fora das montagens de construção). O registro serializa as decisões e a promoção do pacote `entrega/` inteiro para o destino autorizado. |

O isolamento foi desenhado para uma demonstração sintética. O contêiner compartilha o kernel do host. O controle usa o daemon Docker e quem administra o host controla os arquivos e os serviços. A API do TMS e o PostgreSQL pertencem ao simulador local da equipe. A autenticação dos usuários da interface e a integração com sistemas reais dependem de trabalho próprio. [Sandbox](korda_execution/sandbox.py) · [Simulador](../../infra/sistemas-simulados/README.md) · [Ingestão de referência](referencia/README.md)

## Verificação reproduzível

A suíte de execução no GitHub Actions constrói as imagens e prepara os lotes de ajuste. Para a revisão local rápida, rode os testes de planejamento, do harness, do pipeline e do avaliador. Estes comandos, a partir da raiz, executam os testes de ponta a ponta depois de preparar as imagens e o ambiente acima. A variável de exigência faz a suíte falhar se Docker ou uma imagem estiver indisponível.

```bash
python scripts/check_repo.py
python -m unittest discover -s services/planning/tests
python -m unittest discover -s services/execution/tests/harness -t services/execution
python -m unittest discover -s services/execution/pipeline/tests
python -m unittest discover -s evaluation/worker/tests
python data/synthetic/generator/generate.py --empresa 02_variacao
KORDA_EXIGIR_DOCKER=1 python -m unittest discover -s services/execution/tests -t services/execution -v
```

Para guardar a evidência do lote integral depois que os diretórios temporários forem removidos, defina `KORDA_EVIDENCIA_LOCAL` com o caminho de uma pasta nova ou vazia antes de executar o teste. Quando todas as verificações de paridade e linhagem passam, o teste grava a evidência. As pastas `n0/` e `n1/` contêm, cada uma, o pacote `entrega/`, `ingestao.json` e `medicao.json`. O pacote reúne os resultados da empresa fictícia. Os dois JSONs permitem conferir a origem da carga e o custo medido do executor.

- O E2E de N0 observa os modelos vazios antes da construção, injeta o defeito na primeira chamada ao dbt e exige reconstrução bem-sucedida após uma correção. Confere artefatos, a infra capturada (modelos, manifest, catalog e prata com hash), o pacote `entrega/`, registros de custo e espera pela aprovação da entrega, sem avaliação. Um segundo teste processa e promove os três arquivos originais com o plano v0.1 registrado e sua permissão única. [Teste do worker](tests/test_worker_docker.py)
- O E2E N0/N1 compara os três KPIs e cada pedido e viagem do lote completo. Confere a linhagem de ERP/TMS e a correspondência do SHA-256 dos CT-e aos XMLs da origem. Verifica a promoção, depois da segunda decisão, do pacote da mesma execução. Uma segunda execução N1 usa o corte de 02/09 para verificar a recusa antes de construir e a limpeza após a falha. [Teste dos dois níveis](tests/test_worker_ingestao_docker.py)
- Paginação, reexecução idempotente, falhas transitórias e mudança de esquema da ingestão N1 têm testes próprios. Os exemplos de ajuste são 01 e 02. A empresa reservada 03 tem execução de medição separada. [Testes de ingestão](tests/test_ingestao_n1.py) · [CI](../../.github/workflows/ci.yml)

Os testes de nível 1 também precisam de `docker build -t korda-simulados:dev infra/sistemas-simulados` e `docker pull postgres:17.6-alpine`. Sem Docker, sem as imagens ou sem as fontes geradas, os testes de integração são **pulados** (o resumo do unittest mostra `skipped`). Com `KORDA_EXIGIR_DOCKER=1`, isso vira falha, como no CI. A imagem pode ser trocada por `KORDA_SANDBOX_IMAGE`. A integração da ingestão com a 03_reservada só roda com `KORDA_MEDIR_03=1`, porque essa empresa é só para medição. Os unitários da ingestão rodam dentro da imagem (comando em [`korda_ingestao/README.md`](../../infra/sandbox/korda_ingestao/README.md#testes)).

## Estado (27/11/2026)

**Rascunho para [K08](https://github.com/leeunam/korda/issues/8), [K09](https://github.com/leeunam/korda/issues/9) e [K10](https://github.com/leeunam/korda/issues/10).** Existem a sandbox local em Docker, as ferramentas restritas, a ingestão de níveis 0 e 1, o worker com as duas aprovações, o ciclo de até três correções e o avaliador independente (offline, fora do fluxo desde 27/11/2026), com testes. **O worker está ligado ao harness** (decisão de 25/11/2026: o harness constrói; o worker orquestra). A construção, as correções e o retorno de perguntas foram verificados **só sem LLM**: com o executor `falso` e com o `roteirizado`, no Docker. **A construção nunca rodou com LLM real**; o único uso real até agora foi o teste de fumaça do gateway. O `planejar` gera a construção antes da aprovação 1 ou devolve perguntas quando falta contexto. **O `planejar` foi validado com duas chamadas reais em 27/11/2026** (`anthropic/claude-opus-5.5`, custo estimado pelos tokens): no contexto fictício 02 gerou um plano válido e registrável (4.870/6.729 tokens, ~US$ 0,15); no 01 devolveu uma pergunta sobre a base de rateio (4.690/5.216 tokens, ~US$ 0,12). As saídas estão em [`tests/fixtures/planejamento/`](tests/fixtures/planejamento/). O worker recusa o `agente_sdk`. Desde a K13, a execução aprovada guarda a infra construída e exporta a prata e monta o pacote de entrega em dados (`entrega.json`); isso também foi verificado só sem LLM (`roteirizado` e `falso`). **Ainda não existem nesta versão:** o ensaio real no 01_demo, a sandbox em nuvem e a unificação das duas ingestões. O worker ainda recebe fontes brutas (`exigir_manifesto=False`); a sandbox avulsa exige a landing zone. Os tipos de evento são provisórios até a [K01](https://github.com/leeunam/korda/issues/1).

## Componentes

| Caminho | Conteúdo |
| --- | --- |
| [`../../infra/sandbox/`](../../infra/sandbox/Dockerfile) | Imagem da sandbox: dbt-core, dbt-duckdb, duckdb e lxml fixados, usuário sem root, `consulta.py` (SQL somente leitura), `perfil.py` e o pacote de ingestão. |
| [`../../infra/sandbox/korda_ingestao/`](../../infra/sandbox/korda_ingestao/README.md) | Ingestão de nível 0 que roda no contêiner: CSV e CT-e em XML → Parquet, `_rejeitados` e `manifesto.json`. |
| [`korda_execution/ingestao.py`](korda_execution/ingestao.py) | `ingerir()` e CLI: sobe o contêiner de ingestão sem rede, com as fontes brutas somente leitura. |
| [`korda_execution/ingestao_n1.py`](korda_execution/ingestao_n1.py) | `executar_ingestao()`: roda um código de ingestão de nível 1 só na rede interna do [ambiente simulado](../../infra/sistemas-simulados/README.md), com plano, CT-e e código somente leitura e credenciais por `--env-file` temporário. |
| [`referencia/`](referencia/README.md) | Ingestão de nível 1 de referência (plano B e base de comparação), fora da imagem e fora do alcance do agente. |
| [`korda_execution/sandbox.py`](korda_execution/sandbox.py) | Interface `Sandbox` (`criar`, `enviar_arquivos`, `rodar_comando`, `destruir`) e `LocalDockerSandbox`. |
| [`korda_execution/worker.py`](korda_execution/worker.py) | Orquestração: lote e landing, bronze, sandbox, harness, captura e pacote de entrega. |
| [`korda_execution/construcao.py`](korda_execution/construcao.py) | Construção a partir do documento aprovado (executores `chat`, `falso` e `roteirizado`), verificação dbt + exportação e medição. |
| [`korda_execution/lote.py`](korda_execution/lote.py) | Lote autorizado → landing N0/N1 e `ingestao.json`. |
| [`korda_execution/operador.py`](korda_execution/operador.py) | Painel local (`/operador`): importa a revisão da entrevista, gera o plano, registra as duas decisões e serve o `pacote.zip` montado da pasta promovida. |
| [`korda_execution/ferramentas.py`](korda_execution/ferramentas.py) | Ferramentas que o harness expõe ao agente. |
| [`korda_execution/caminhos.py`](korda_execution/caminhos.py) | Política de caminhos e lista branca do dbt. |
| [`korda_execution/harness/`](korda_execution/harness/README.md) | Executores (`chat` constrói e corrige pela API da Feita; `roteirizado` como plano B; `falso` para testes; `agente_sdk` guardado, recusado pelo worker), política e hook, contexto, orçamento, medição, `construir_e_verificar` e adaptador provisório de eventos (com custo) para o front. |
| [`korda_execution/planejamento.py`](korda_execution/planejamento.py) | Comando `planejar`: uma chamada à API gera a construção (anexada ao plano) ou as perguntas para a descoberta. |
| [`korda_execution/documento_base.py`](korda_execution/documento_base.py) | Prompt do planejamento da construção e leitura da decisão (`pronto_para_construir`, `perguntas`). |
| [`korda_execution/artefatos.py`](korda_execution/artefatos.py) | Captura dos resultados e da infra (sem seguir links, com teto e hash) e promoção do pacote. |
| [`korda_execution/entrega.py`](korda_execution/entrega.py) | `empacotar`: dossiê da execução, `decisoes.md`, `execucao.md`, `projeto_dbt/` e `manifesto.json`. |
| [`korda_execution/contrato_saida.py`](korda_execution/contrato_saida.py) | Nomes fixos de modelos e colunas, lidos dos testes protegidos e de `vars.contrato_exportacao`, enviados ao planejamento. |
| [`korda_execution/eventos.py`](korda_execution/eventos.py) | `emit_event` provisório (JSONL por execução). |
| [`korda_execution/smoke.py`](korda_execution/smoke.py) | Teste de fumaça: ingere as fontes do gerador e sobe a sandbox sobre a landing. |
| [`pipeline/`](pipeline/README.md) | Projeto dbt da 01: testes, definições, ingestão e exportação (montados na sandbox) e o pipeline escrito à mão em `models/` (referência e plano B, nunca montado). |
| [`tests/`](tests/fixtures/README.md) | Testes unitários e de integração; fixture dbt com dados sintéticos. |

O worker (processo Python no host) usa só a biblioteca padrão e o CLI do Docker. As dependências ficam na imagem. O executor `chat` e o documento-base também usam só a biblioteca padrão. Só o `agente_sdk`, fora da demo, precisaria do `claude-agent-sdk` no host ([`requirements-harness.txt`](../../requirements-harness.txt)); os testes funcionam sem ele.

Fluxo de nível 0: **fontes brutas** (`data/synthetic/output/<empresa>`) → **ingestão** (contêiner efêmero) → **landing zone** em Parquet → **sandbox** (`/work/fontes`). A ingestão não limpa nada: duplicatas, cancelados e formatos mistos chegam intactos para o agente tratar conforme o plano. Detalhes em [`korda_ingestao/README.md`](../../infra/sandbox/korda_ingestao/README.md).

Fluxo de nível 1: **sistemas simulados** (ERP em Postgres, TMS por API, pasta de CT-e; replay por dias) → **código de ingestão** que segue a [seção de ingestão do plano](../../packages/contracts/ingestion_plan/v0.1.0/README.md) → a **mesma landing**, com cargas incrementais. Hoje o código é a [referência](referencia/README.md). Os testes de aceite do plano estão em [`tests/test_ingestao_n1.py`](tests/test_ingestao_n1.py).

Sandbox avulsa sobre a landing:

```bash
python3 data/synthetic/generator/generate.py --empresa 01_demo
cd services/execution
python3 -m korda_execution.ingestao --fontes ../../data/synthetic/output/01_demo --destino ../../data/synthetic/landing/01_demo
python3 -m korda_execution.smoke --landing ../../data/synthetic/landing/01_demo   # ou --fontes <bruto>, que ingere antes
```

## Montagens da sandbox

| Dentro do contêiner | Origem | Acesso |
| --- | --- | --- |
| `/work/fontes` | landing zone (Parquet + `manifesto.json`) na sandbox avulsa; cópia validada das fontes brutas no worker; `_gerador/` coberta por um tmpfs vazio, se existir | somente leitura |
| `/work/projeto` | cópia do projeto (`dbt_project.yml`, `profiles.yml`, `definicoes/`, `tests/`, `macros/`, `ingerir.py`, `exportar.py`, `exportar_prata.py`) | somente leitura |
| `/work/projeto/models` | `runs/<run_id>/projeto/models`; no worker começa vazio, e as ferramentas só escrevem o que casa com `editable_models` | escrita |
| `/work/saida` | `runs/<run_id>/saida` (`korda.duckdb`, `target/`, `logs/`) | escrita |
| `/tmp` | tmpfs de 256 MB, `noexec` | escrita |
| resto do sistema | imagem | somente leitura (`--read-only`) |

`LocalDockerSandbox` recusa, por padrão, uma pasta de fontes sem `manifesto.json` (`exigir_manifesto=True`), para que a sandbox não receba fontes brutas por engano. O worker do plano aprovado desliga essa exigência porque valida e copia as fontes brutas antes. As fontes do dbt na landing apontam para Parquet, por exemplo `external_location: "read_parquet('/work/fontes/{name}.parquet')"`. O projeto dbt precisa declarar `model-paths: ["models", "definicoes"]`. Fontes e testes de esquema ficam em `definicoes/` (protegida), e os modelos materializam como tabela, porque a consulta somente leitura não acessa arquivos.

## Limites conhecidos

- **Não é isolamento de produção.** O contêiner compartilha o kernel do host. Para dados de clientes seriam necessários microVM (gVisor, Firecracker) ou sandbox gerenciada, além de revisão de segurança.
- O worker precisa de acesso ao Docker (grupo `docker`, equivalente a root no host). O agente nunca recebe esse acesso nem o socket.
- Código do agente roda dentro da sandbox: um modelo Python do dbt ou um hook SQL executa com as permissões do contêiner. Ele pode escrever em `models/` e `saida/`, mas não em fontes nem em testes.
- A ingestão não valida o XSD dos CT-e, e sua heurística de cabeçalho pode errar em casos ambíguos (ver [limites da ingestão](../../infra/sandbox/korda_ingestao/README.md#limites-conhecidos)).
- `_gerador/` é ocultada por nome, na ingestão e na sandbox. Outra pasta de respostas dentro das fontes precisaria ser adicionada em `ocultar_nas_fontes`. Os gabaritos (`evaluation/`) não são montados.
- A imagem não tem git nem rede: `dbt deps` não funciona, e `dbt debug` só com `--connection`.
- As dependências transitivas da imagem não estão fixadas, só as três principais.
- Os eventos vão para um JSONL local; o backend (P4) não está escolhido.
