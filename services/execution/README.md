# Worker de execução da Korda

O worker processa o **lote sintético 01_demo**. Lê a versão de plano aprovada pelo operador, constrói frete por entrega, OTIF e ocupação com DuckDB/dbt e entrega os resultados a um avaliador independente. Uma segunda decisão humana autoriza a cópia para uma pasta local. O [planejamento da integração](../../docs/plano-integracao-worker.md) situa essa entrega nas 17 issues do projeto.

## Preparar o lote e o plano

Na raiz do repositório, use Python 3.11 ou superior, uma instalação local do Docker e um usuário sem root com permissão de usar o daemon. O host executa o operador e o gerador. A imagem contém as versões de dbt e DuckDB usadas pelo pipeline.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-contracts.txt -r requirements-synthetic.txt
docker build -t korda-sandbox:dev infra/sandbox
python data/synthetic/generator/generate.py --empresa 01_demo
mkdir -p runs/preparo
python -m services.planning.korda_planning \
  packages/contracts/context/v0.1.0/examples/02_rateio_confirmado.json \
  --destino revisao-logistica --custo-estimado-centavos 0 > runs/preparo/plano.json
python -m services.execution.korda_execution registrar runs/preparo/plano.json
```

O valor zero exemplifica a estimativa do operador para um ensaio local sem chamada a provedor. O custo de infraestrutura depende do ambiente. Para demonstrar uma lacuna, use a revisão `01_rateio_pendente.json`. Nela, o custo fica bloqueado até a confirmação do financeiro. Uma alteração de regras, destino ou estimativa muda o identificador da versão. [Contrato do plano](../../packages/contracts/plan/v0.1.0/README.md)

## Operar as duas aprovações

O comando `registrar` exibe projeto e versão. A pessoa responsável confere o plano e usa o identificador integral em `VERSAO`. Os comandos de decisão aceitam `aprovar` ou `rejeitar` e registram pessoa e instante UTC. A identificação é declarada pelo operador com acesso ao host. A integração da autenticação com a interface continua pendente.

```bash
python -m services.execution.korda_execution decidir-plano demo-01 "$VERSAO" aprovar --pessoa "$REVISOR"
python -m services.execution.korda_execution executar runs/preparo/plano.json --run-id demo-001
python -m services.execution.korda_execution consultar demo-001
```

O operador revisa o laudo e os resultados em `runs/worker/revisao/demo-001/`. Após conferir o destino e os três arquivos do manifesto, pode registrar a segunda decisão e promover a entrega.

```bash
python -m services.execution.korda_execution decidir-entrega demo-001 aprovar --pessoa "$REVISOR"
python -m services.execution.korda_execution promover demo-001 revisao-logistica
```

Os três arquivos aparecem juntos em `runs/worker/entregas/revisao-logistica/demo-001/`. O identificador da execução é de uso único. O operador pode escolher uma raiz privada alternativa com a opção global `--raiz` antes do subcomando. O banco SQLite guarda o histórico inclusive após reinício. Uma versão substituída ou rejeitada invalida as autorizações pendentes.

## Controles e diagnóstico

| Recurso | Comportamento na execução do plano |
| --- | --- |
| Fontes | O host prepara uma cópia limitada dos cinco CSVs conhecidos e dos XML de CT-e. A sandbox os recebe em leitura. Perfis de ERP, TMS e XML usam amostras limitadas. O host mantém o perfil em `fontes.json`. |
| Projeto dbt | Configuração, testes, macros e modelos de referência são protegidos. O plano deste cenário autoriza a escrita somente em `models/prata_ctes.sql`. O diretório de trabalho para o DuckDB, logs e resultados tem escrita. |
| Execução | Contêiner sem rede, com usuário sem root, filesystem raiz de leitura, CPU, memória, processos e duração de comandos limitados. Compartilha o kernel do host. O processo de controle tem acesso ao daemon local. |
| Ferramentas | Leitura do plano projetado, perfilamento por identificador, escrita de SQL autorizado, comandos dbt em lista permitida, consultas em modo leitura e emissão de eventos. O provedor de LLM e uma sandbox em nuvem ficam fora desta versão da demo. |
| Correção | Uma falha do teste protegido de unicidade dos CT-e permite restaurar o modelo de deduplicação revisado e repetir o build. O limite é de três correções por etapa. Falhas sem reparo aplicável pedem intervenção. Ações e custo informado ficam em `eventos.jsonl`. |
| Avaliação | O contêiner para antes da captura. O host verifica tipo, tamanho e hash dos arquivos e compara fontes, regras, três KPIs, pedidos e viagens com a referência protegida. O laudo completo fica em `avaliacao.json`. |
| Entrega | A aprovação da entrega vincula a execução, o destino e o manifesto. A promoção copia `kpis.json`, `por_pedido.csv` e `por_viagem.csv` para a pasta autorizada. Modelos e documentação técnica estão no repositório. A embalagem completa para o cliente e a interface são itens de integração da K13. |

A sandbox avulsa da fixture do Gabriel permite criar modelos dentro de `models/`. O comando de produto usa a lista exata do plano. A evidência de cálculo, as premissas fiscais da demo e o percurso de um resultado até a fonte estão no [pipeline logístico](pipeline/README.md). O [avaliador](../../evaluation/worker/README.md) documenta as tolerâncias e a comparação por entidade.

## Verificação

```bash
python scripts/check_repo.py
python -m unittest discover -s services/planning/tests
python -m unittest discover -s services/execution/pipeline/tests
python -m unittest discover -s evaluation/worker/tests
KORDA_EXIGIR_DOCKER=1 python -m unittest discover -s services/execution/tests -t services/execution -v
```

O [teste integrado](tests/test_worker_docker.py) usa o gerador da 01, introduz um defeito na cópia do modelo, exige a falha de unicidade, verifica a correção no segundo build e confere que o resultado testado ainda aguarda a segunda aprovação. O job de execução da [CI](../../.github/workflows/ci.yml) exige acesso ao Docker e a imagem construída. Sem a variável de exigência, o unittest identifica os casos Docker pulados. [Planejamento e evidências desta entrega](../../docs/plano-integracao-worker.md)

Os testes de nível 1 também precisam de `docker build -t korda-simulados:dev infra/sistemas-simulados` e `docker pull postgres:17.6-alpine`. Sem Docker, sem as imagens ou sem as fontes geradas, os testes de integração são **pulados** (o resumo do unittest mostra `skipped`). Com `KORDA_EXIGIR_DOCKER=1`, isso vira falha, como no CI. A imagem pode ser trocada por `KORDA_SANDBOX_IMAGE`. A integração da ingestão com a 03_reservada só roda com `KORDA_MEDIR_03=1`, porque essa empresa é só para medição. Os unitários da ingestão rodam dentro da imagem (comando em [`korda_ingestao/README.md`](../../infra/sandbox/korda_ingestao/README.md#testes)).

## Estado (25/11/2026)

**Rascunho para [K08](https://github.com/leeunam/korda/issues/8), [K09](https://github.com/leeunam/korda/issues/9) e [K10](https://github.com/leeunam/korda/issues/10).** Existem a sandbox local em Docker, as ferramentas restritas, a ingestão de níveis 0 e 1, o worker com as duas aprovações, o ciclo de até três correções e o avaliador independente, com testes. **O pipeline dbt dos três indicadores é escrito à mão** (referência e plano B da demo), e a correção é roteirizada. **Ainda não existem nesta versão:** o agente que constrói e corrige com LLM (harness, K10), a sandbox em nuvem e a unificação das duas ingestões. O worker ainda recebe fontes brutas (`exigir_manifesto=False`); a sandbox avulsa exige a landing zone. Os tipos de evento são provisórios até a [K01](https://github.com/leeunam/korda/issues/1).

## Componentes

| Caminho | Conteúdo |
| --- | --- |
| [`../../infra/sandbox/`](../../infra/sandbox/Dockerfile) | Imagem da sandbox: dbt-core, dbt-duckdb, duckdb e lxml fixados, usuário sem root, `consulta.py` (SQL somente leitura), `perfil.py` e o pacote de ingestão. |
| [`../../infra/sandbox/korda_ingestao/`](../../infra/sandbox/korda_ingestao/README.md) | Ingestão de nível 0 que roda no contêiner: CSV e CT-e em XML → Parquet, `_rejeitados` e `manifesto.json`. |
| [`korda_execution/ingestao.py`](korda_execution/ingestao.py) | `ingerir()` e CLI: sobe o contêiner de ingestão sem rede, com as fontes brutas somente leitura. |
| [`korda_execution/ingestao_n1.py`](korda_execution/ingestao_n1.py) | `executar_ingestao()`: roda um código de ingestão de nível 1 só na rede interna do [ambiente simulado](../../infra/sistemas-simulados/README.md), com plano, CT-e e código somente leitura e credenciais por `--env-file` temporário. |
| [`referencia/`](referencia/README.md) | Ingestão de nível 1 de referência (plano B e base de comparação), fora da imagem e fora do alcance do agente. |
| [`korda_execution/sandbox.py`](korda_execution/sandbox.py) | Interface `Sandbox` (`criar`, `enviar_arquivos`, `rodar_comando`, `destruir`) e `LocalDockerSandbox`. |
| [`korda_execution/ferramentas.py`](korda_execution/ferramentas.py) | Ferramentas que o harness vai expor ao agente. |
| [`korda_execution/caminhos.py`](korda_execution/caminhos.py) | Política de caminhos e lista branca do dbt. |
| [`korda_execution/eventos.py`](korda_execution/eventos.py) | `emit_event` provisório (JSONL por execução). |
| [`korda_execution/smoke.py`](korda_execution/smoke.py) | Teste de fumaça: ingere as fontes do gerador e sobe a sandbox sobre a landing. |
| [`pipeline/`](pipeline/README.md) | Pipeline dbt da 01 escrito à mão (referência e plano B). |
| [`tests/`](tests/fixtures/README.md) | Testes unitários e de integração; fixture dbt com dados sintéticos. |

O worker (processo Python no host) usa só a biblioteca padrão e o CLI do Docker. As dependências ficam na imagem.

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
| `/work/projeto` | cópia do projeto (`dbt_project.yml`, `profiles.yml`, `definicoes/`, `tests/`) | somente leitura |
| `/work/projeto/models` | `runs/<run_id>/projeto/models`; no worker, só os arquivos de `editable_models` | escrita |
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
