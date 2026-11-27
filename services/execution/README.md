# Worker de execução da Korda

A demo transforma as fontes da transportadora fictícia `01_demo` em frete por entrega, OTIF e ocupação. O operador aprova a versão do plano que autoriza o trabalho. Depois do build, um avaliador independente confere os três indicadores e cada pedido e viagem. Uma segunda decisão humana autoriza promover a entrega para o destino local daquele plano. [Planejador](../planning/README.md) · [Pipeline logístico](pipeline/README.md) · [Avaliador](../../evaluation/worker/README.md)

Para operar a partir de uma entrevista do WhatsApp, siga [Da entrevista à entrega no painel local](../../docs/entrevista-planejamento-painel.md).

## Escolher a ingestão

| Plano | O que a execução lê | Linhagem disponível |
| --- | --- | --- |
| N0 · arquivos exportados | Cinco CSVs do ERP/TMS e os XMLs de CT-e entram no contêiner de ingestão. O formato de saída é Parquet com manifesto. | Arquivo e linha para registros de CSV. Arquivo, chave e SHA-256 para cada parcela de CT-e usada no custo. |
| N1 · sistemas simulados | O simulador da 01 alimenta o ERP em PostgreSQL, o TMS por API e uma pasta de entrega de CT-e. A ingestão de referência segue a proposta aprovada e materializa as tabelas na mesma estrutura de landing. | Origem lógica, chave da entidade e carga para ERP/TMS. Arquivo de entrega, SHA-256, chave, carga e centavos para CT-e. |

O plano `plan/v0.2.0` vincula nível, janela, proposta de ingestão e os cinco caminhos SQL editáveis à versão aprovada. A proposta N1 precisa corresponder à empresa, ao projeto e à revisão do contexto. Para N1 integral, o worker percorre o replay até a última data. Num corte parcial, registra a ingestão e a necessidade de uma referência do mesmo período. A avaliação mensal da 01 só autoriza o lote integral. [Contrato do plano](../../packages/contracts/plan/v0.2.0/README.md) · [Proposta de ingestão](../../packages/contracts/ingestion_plan/v0.1.0/README.md)

Planos históricos v0.1 usam N0. A versão que autoriza `models/*` constrói os modelos sob esse escopo. A fixture mais antiga, que autorizou apenas corrigir `models/prata_ctes.sql`, continua executável pelo caminho roteirizado original. O manifesto da entrega v0.1 contém os três arquivos de resultados. A v0.2 acrescenta o pacote de reprodução. [Contrato legado](../../packages/contracts/plan/v0.1.0/README.md)

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
- O gateway requer `KORDA_PERMITIR_LLM_REAL=1` e `KORDA_LLM_CHAVE` no host. A chamada de planejamento tem medição própria e até 6.000 tokens de saída. O teto em USD é aplicado separadamente ao planejamento e à execução aprovada. A suíte usa transporte local para verificar as duas respostas. [Planejamento da construção](korda_execution/planejamento.py) · [Configuração e medição](korda_execution/harness/README.md)

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

Em `runs/worker/revisao/<run_id>/`, consulte `ingestao.json` para identificar a origem e a janela, `fontes.json` para o perfil, `documento_base.md` para a especificação usada pelo construtor, `medicao.json` para tentativas e custo, e `eventos.jsonl` para a sequência de ações. `avaliacao.json` contém a decisão técnica do avaliador. Em `resultados/` ficam `kpis.json`, `por_pedido.csv` e `por_viagem.csv`. Na v0.2, `pacote.zip` reúne modelos, testes, instruções de reprodução, resumo dos eventos e da medição, evidências do build e os resultados com linhagem. O registro verifica o manifesto antes da promoção. [Pacote](korda_execution/pacote.py)

O revisor confere o destino, o conteúdo e o manifesto daquela execução antes de autorizar a promoção. O comando também aceita `rejeitar`. A promoção grava a entrega em `runs/worker/entregas/<destino>/<run_id>/`. A opção global `--raiz`, antes do subcomando, permite escolher outra raiz do operador.

```bash
python -m services.execution.korda_execution decidir-entrega "$RUN_ID" aprovar --pessoa "$REVISOR"
python -m services.execution.korda_execution promover "$RUN_ID" revisao-logistica
```

## Construção e correção

| Executor | Construção, correção e medição |
| --- | --- |
| `roteirizado` | Padrão. Escreve os modelos SQL de referência pelos caminhos autorizados. O custo de provedor é zero. |
| `falso` | Transporte de teste injetado no host. Exercita a construção a partir de `construction`, uma falha de dbt e sua correção. A medição é sintética. |
| `chat` | O gateway no host recebe o documento já aprovado e ferramentas para construir e corrigir os modelos. O operador acompanha turnos, tokens e custo estimado. |
| `agente_sdk` | Adaptador experimental de correção preservado no harness. O worker da demo recusa esse modo. |

Para os planos de construção, os modelos começam sem SQL de referência na sandbox. O adaptador protegido apresenta a landing como tabelas bronze. O harness escreve prata e ouro, executa `dbt build` com os testes protegidos e verifica a exportação. Falhas de implementação podem voltar para até três correções. Esgotar o limite, identificar uma inconsistência de dados ou perder a infraestrutura requer intervenção. Mudar uma regra, o escopo dos modelos, a construção ou a ingestão exige reconsiderar a versão a aprovar. [Harness e variáveis](korda_execution/harness/README.md) · [Ciclo de correção](korda_execution/correcao.py)

## Montagens, credenciais e separação do avaliador

| Etapa | Acesso concedido |
| --- | --- |
| Ingestão N0 | Contêiner efêmero sem rede, arquivos autorizados em leitura e landing de saída. |
| Ingestão N1 | Contêiner efêmero na rede interna do simulador. O código de ingestão e o plano são de leitura, a landing recebe as cargas e o processo recebe credenciais temporárias dos serviços. |
| Construção e testes dbt | Contêiner sem rede. `/work/fontes` contém a landing com manifesto em leitura. O projeto protegido inclui macros, definições e testes. Na v0.2 há uma montagem gravável por modelo autorizado, além de `/work/saida`. No escopo histórico `models/*`, o host publica pelas ferramentas os arquivos SQL autorizados sobre a montagem de leitura. |
| Avaliação e entrega | O host encerra o produtor e compara as saídas congeladas. O avaliador lê as respostas esperadas fora das montagens de construção. O registro serializa as decisões e a promoção para o destino autorizado. |

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

Para guardar a evidência do lote integral depois que os diretórios temporários forem removidos, defina `KORDA_EVIDENCIA_LOCAL` com o caminho de uma pasta nova ou vazia antes de executar o teste. Quando todas as verificações de paridade e linhagem passam, o teste grava oito arquivos. As pastas `n0/` e `n1/` contêm, cada uma, `pacote.zip`, `avaliacao.json`, `ingestao.json` e `medicao.json`. O pacote reúne os resultados da empresa fictícia. Os três JSONs permitem conferir, respectivamente, o aceite técnico, a origem da carga e o custo medido do executor roteirizado.

- O E2E de N0 observa os modelos vazios antes da construção, injeta o defeito na primeira chamada ao dbt e exige reconstrução bem-sucedida após uma correção. Confere artefatos, registros de custo e espera pela aprovação da entrega. Um segundo teste processa e promove os três arquivos originais com o plano v0.1 registrado e sua permissão única. [Teste do worker](tests/test_worker_docker.py)
- O E2E N0/N1 compara os três KPIs e cada pedido e viagem do lote completo. Confere a linhagem de ERP/TMS e a correspondência do SHA-256 dos CT-e aos XMLs da origem. Verifica a promoção, depois da segunda decisão, do pacote da mesma execução. Uma segunda execução N1 usa o corte de 02/09 para verificar a recusa antes de construir e a limpeza após a falha. [Teste dos dois níveis](tests/test_worker_ingestao_docker.py)
- Paginação, reexecução idempotente, falhas transitórias e mudança de esquema da ingestão N1 têm testes próprios. Os exemplos de ajuste são 01 e 02. A empresa reservada 03 tem execução de medição separada. [Testes de ingestão](tests/test_ingestao_n1.py) · [CI](../../.github/workflows/ci.yml)
