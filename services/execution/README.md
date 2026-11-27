# Worker de execução da Korda

O worker recebe um plano aprovado para a transportadora sintética `01_demo`, prepara as fontes autorizadas e constrói frete por entrega, OTIF e ocupação. O avaliador compara os três indicadores e os resultados por pedido e viagem. A publicação em uma pasta local depende de uma segunda decisão humana. [Planejador](../planning/README.md) · [Pipeline logístico](pipeline/README.md) · [Avaliador](../../evaluation/worker/README.md)

## Escolher a ingestão

| Plano | O que a execução lê | Linhagem disponível |
| --- | --- | --- |
| N0 · arquivos exportados | Cinco CSVs do ERP/TMS e os XMLs de CT-e entram no contêiner de ingestão. O formato de saída é Parquet com manifesto. | Arquivo e linha para registros de CSV. Arquivo, chave e SHA-256 para cada parcela de CT-e usada no custo. |
| N1 · sistemas simulados | O simulador da 01 alimenta o ERP em PostgreSQL, o TMS por API e uma pasta de entrega de CT-e. A ingestão de referência segue a proposta aprovada e materializa as tabelas na mesma estrutura de landing. | Origem lógica, chave da entidade e carga para ERP/TMS. Arquivo de entrega, SHA-256, chave, carga e centavos para CT-e. |

O operador mantém compatibilidade com o plano v0.1 aprovado para a 01. Ele conserva a versão e a única permissão de correção em `models/prata_ctes.sql`; depois de validado, o revisor pode promover os três arquivos originais. O ZIP e a construção dos cinco modelos são entregas da v0.2. [Plano legado reproduzível](../../packages/contracts/plan/v0.1.0/examples/01_demo.json)

O plano `plan/v0.2.0` inclui nível, janela, proposta de ingestão e lista de modelos editáveis na versão que o operador aprova. O lote integral permite comparar N0 e N1 com o gabarito da 01. Em uma janela parcial N1, o worker registra o relatório da ingestão e a falta de referência adequada, interrompe a execução e mantém a entrega bloqueada. A proposta N1 exige o contexto confirmado da mesma empresa, projeto e revisão. [Contrato do plano](../../packages/contracts/plan/v0.2.0/README.md) · [Proposta e exemplos de ingestão](../../packages/contracts/ingestion_plan/v0.1.0/README.md)

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

Para N0, gere o plano com a revisão confirmada e a estimativa do ensaio.

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

Escolha um dos arquivos em `PLANO`. O exemplo usa N1. Defina `REVISOR` com a identificação de quem tomou a decisão e `RUN_ID` com um identificador novo. O registro guarda pessoa, decisão e instante UTC em SQLite. A identificação do revisor é declarada pelo operador com acesso ao host.

```bash
PLANO=runs/preparo/plano-n1.json
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

Em `runs/worker/revisao/<run_id>/`, consulte `ingestao.json` para identificar a origem e a janela, `fontes.json` para o perfil, `documento_base.md` para a especificação usada pelo construtor, `medicao.json` para tentativas e custo, e `eventos.jsonl` para a sequência de ações. `avaliacao.json` contém a decisão técnica do avaliador. Em `resultados/` ficam `kpis.json`, `por_pedido.csv`, `por_viagem.csv` e `pacote.zip`. O ZIP reúne os modelos executados, testes, documentação de reprodução, evidências do build e os resultados com linhagem. O registro verifica o manifesto antes da promoção. [Pacote](korda_execution/pacote.py)

O revisor confere o destino, o conteúdo e o manifesto daquela execução antes de autorizar a promoção. O comando também aceita `rejeitar`. A promoção grava a entrega em `runs/worker/entregas/<destino>/<run_id>/`. A opção global `--raiz`, antes do subcomando, permite escolher outra raiz do operador.

```bash
python -m services.execution.korda_execution decidir-entrega "$RUN_ID" aprovar --pessoa "$REVISOR"
python -m services.execution.korda_execution promover "$RUN_ID" revisao-logistica
```

## Construção e correção

| Executor | Construção, correção e medição |
| --- | --- |
| `roteirizado` | Usa o documento do plano e escreve os modelos de referência autorizados. O operador pode reproduzir a demo offline. O relatório identifica o modo e o custo de provedor zero. |
| `falso` | Exercita o protocolo de chat e suas ferramentas a partir de respostas preparadas. O teste integrado usa esse transporte para construir os modelos, observar a falha de unicidade do CT-e, corrigir o modelo e repetir o build. A medição é sintética. |
| `chat` | Usa o gateway configurado no host para gerar o documento-base e construir e corrigir os modelos. Exige habilitação explícita e credencial. A medição registra uso informado e custo estimado. |
| `agente_sdk` | Usa construção roteirizada e o SDK na correção. Exige a dependência opcional no host, credencial e habilitação explícita. |

Cada execução começa com arquivos SQL vazios para os modelos autorizados. As fontes e a configuração do dbt chegam em leitura. O worker limita o número de correções por etapa e registra a intervenção quando faltam condições para prosseguir. Uma nova regra ou outro nível de ingestão exige reavaliar o plano e registrar uma aprovação compatível. O transporte falso e a construção roteirizada permitem verificar o fluxo inteiro com dados sintéticos e custo de provedor zero. [Harness e variáveis](korda_execution/harness/README.md) · [Documento-base](korda_execution/documento_base.py) · [Ciclo de correção](korda_execution/correcao.py)

## Montagens, credenciais e separação do avaliador

| Etapa | Acesso concedido |
| --- | --- |
| Ingestão N0 | Contêiner efêmero sem rede, arquivos autorizados em leitura e landing de saída. |
| Ingestão N1 | Contêiner efêmero na rede interna do simulador. O código de ingestão e o plano são de leitura, a landing recebe as cargas e o processo recebe credenciais temporárias dos serviços. |
| Construção e testes dbt | Contêiner sem rede. `/work/fontes` contém a landing com manifesto em leitura. O projeto protegido inclui macros, definições e testes. Cada arquivo de `editable_models` e `/work/saida` recebe escrita. |
| Avaliação e entrega | O host encerra o produtor e compara as saídas congeladas. O avaliador lê as respostas esperadas fora das montagens de construção. O registro serializa as decisões e a promoção para o destino autorizado. |

O isolamento foi desenhado para uma demonstração sintética. O contêiner compartilha o kernel do host. O controle usa o daemon Docker e quem administra o host controla os arquivos e os serviços. A API do TMS e o PostgreSQL pertencem ao simulador local da equipe. A autenticação dos usuários da interface e a integração com sistemas reais dependem de trabalho próprio. [Sandbox](korda_execution/sandbox.py) · [Simulador](../../infra/sistemas-simulados/README.md) · [Ingestão de referência](referencia/README.md)

## Verificação reproduzível

A suíte de execução no GitHub Actions constrói as imagens e prepara os lotes de ajuste. Estes comandos, a partir da raiz, executam os testes de ponta a ponta depois de preparar as imagens e o ambiente acima. A variável de exigência faz a suíte falhar se Docker ou uma imagem estiver indisponível.

```bash
KORDA_EXIGIR_DOCKER=1 python -m unittest discover -s services/execution/tests \
  -t services/execution -p 'test_worker*docker.py' -v
```

- O E2E de N0 observa os modelos vazios antes da construção, injeta o defeito na primeira chamada ao dbt e exige reconstrução bem-sucedida após uma correção. Confere artefatos, registros de custo e espera pela aprovação da entrega. Um segundo teste processa e promove os três arquivos originais com o plano v0.1 registrado e sua permissão única. [Teste do worker](tests/test_worker_docker.py)
- O E2E N0/N1 compara os três KPIs e cada pedido e viagem do lote completo. Confere a linhagem de ERP/TMS e a correspondência do SHA-256 dos CT-e aos XMLs da origem. Verifica a promoção, depois da segunda decisão, do pacote da mesma execução. Uma segunda execução N1 usa o corte de 02/09 para verificar a recusa antes de construir e a limpeza após a falha. [Teste dos dois níveis](tests/test_worker_ingestao_docker.py)
- Paginação, reexecução idempotente, falhas transitórias e mudança de esquema da ingestão N1 têm testes próprios. Os exemplos de ajuste são 01 e 02. A empresa reservada 03 tem execução de medição separada. [Testes de ingestão](tests/test_ingestao_n1.py) · [CI](../../.github/workflows/ci.yml)
