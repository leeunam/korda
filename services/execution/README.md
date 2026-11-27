# Worker de execução da Korda

O worker processa o **lote sintético 01_demo** e **só orquestra**; não executa nada do pipeline:

1. **Planejamento da construção (`planejar`, antes da aprovação 1).** Uma chamada à API da Feita transforma o plano base (gabarito do [planejador](../planning/README.md)) e o contexto da descoberta no plano de construção. A própria LLM decide se há contexto para construir. Se houver, o documento entra no plano como `construction`, com nova `plan_version`, e a aprovação 1 cobre o que a LLM planejou. Se não houver, ela gera perguntas para a descoberta em `perguntas.json`, e nenhum plano novo é gerado.
2. **Sandbox.** Contêiner sem rede, com `models/` vazio.
3. **Harness.** O [harness](korda_execution/harness/README.md) constrói frete por entrega, OTIF e ocupação com DuckDB/dbt e corrige até três vezes. O loop roda no worker e conversa com a API da Feita; cada ferramenta que o modelo pede executa dentro da sandbox, e a chave nunca entra nela.
4. **Avaliação.** Um avaliador independente confere os resultados. Uma segunda decisão humana autoriza a cópia para uma pasta local. O [planejamento da integração](../../docs/plano-integracao-worker.md) situa essa entrega nas 17 issues do projeto.

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
set -a; . ./.env; set +a          # KORDA_EXECUTOR=chat, KORDA_PERMITIR_LLM_REAL=1 e KORDA_LLM_CHAVE (ignorado pelo Git)
python -m services.execution.korda_execution planejar runs/preparo/plano.json \
  --contexto packages/contracts/context/v0.1.0/examples/02_rateio_confirmado.json --saida runs/preparo/plano_construcao.json
python -m services.execution.korda_execution registrar runs/preparo/plano_construcao.json
```

O `planejar` faz uma chamada (saída limitada a 8.000 tokens) e grava em `runs/worker/planejamento/<versão>-<instante>/`: `documento_base.md`, `resposta.json` (resposta bruta), `medicao.json` (tokens e custo estimado) e, conforme a decisão da LLM, `plano.json` ou `perguntas.json`. Sai com código 0 quando o plano está pronto e 3 quando há perguntas. As perguntas trazem pergunta, lacuna, métricas afetadas e motivo, mais `plan_version`, `context_id` e `context_revision`; voltam para a descoberta, e uma nova revisão de contexto gera outro plano base. Como a plataforma consome esse arquivo ainda está em aberto (P1/P4). Para o plano B, sem LLM, registre o plano base direto.

A mensagem leva o contexto sem metadados que não ajudam a planejar (fontes só com id e tipo, `confirmed_by` só com o papel) e os **nomes fixos** do pipeline, lidos por código em [`contrato_saida.py`](korda_execution/contrato_saida.py): modelos e colunas dos testes protegidos (`pipeline/projeto/tests/*.sql`) e do `exportar.py`. A decisão vem no início da resposta, para um corte não apagá-la. Se a resposta bater no teto (`finish_reason = length`), o `planejar` falha com "resposta cortada no limite de N tokens" e não gera plano.

O valor zero exemplifica a estimativa do operador para um ensaio local sem chamada a provedor. O custo de infraestrutura depende do ambiente. Para demonstrar uma lacuna, use a revisão `01_rateio_pendente.json`. Nela, o custo fica bloqueado até a confirmação do financeiro. Uma alteração de regras, destino ou estimativa muda o identificador da versão. [Contrato do plano](../../packages/contracts/plan/v0.1.0/README.md)

## Operar as duas aprovações

O comando `registrar` exibe projeto e versão. A pessoa responsável confere o plano e usa o identificador integral em `VERSAO`. Os comandos de decisão aceitam `aprovar` ou `rejeitar` e registram pessoa e instante UTC. A identificação é declarada pelo operador com acesso ao host. A integração da autenticação com a interface continua pendente.

```bash
python -m services.execution.korda_execution decidir-plano demo-01 "$VERSAO" aprovar --pessoa "$REVISOR"
python -m services.execution.korda_execution executar runs/preparo/plano_construcao.json --run-id demo-001
python -m services.execution.korda_execution consultar demo-001
```

Quem constrói é escolhido por `KORDA_EXECUTOR` ([variáveis](korda_execution/harness/README.md#variáveis)). O padrão é `roteirizado`: o plano B, que copia o pipeline feito à mão, sem LLM. `chat` usa a API da Feita, gasta créditos e só roda com `KORDA_PERMITIR_LLM_REAL=1` e `KORDA_LLM_CHAVE`. O worker recusa `agente_sdk` (guardado do #27, fora da demo). Com `chat`, o `executar` exige que o plano aprovado tenha `construction` e não faz nenhuma chamada de planejamento: o harness constrói a partir dela. A configuração é lida antes de reservar a execução: chave ou executor inválido falha sem criar sandbox.

O operador revisa o laudo e os resultados em `runs/worker/revisao/demo-001/`: `documento_base.md` (cópia da construção aprovada), `eventos.jsonl`, `fontes.json`, `medicao.json` (tempo, tokens e custo estimado, `synthetic: true` sem LLM real), `avaliacao.json` e `resultados/`. Após conferir o destino e os três arquivos do manifesto, pode registrar a segunda decisão e promover a entrega.

```bash
python -m services.execution.korda_execution decidir-entrega demo-001 aprovar --pessoa "$REVISOR"
python -m services.execution.korda_execution promover demo-001 revisao-logistica
```

Os três arquivos aparecem juntos em `runs/worker/entregas/revisao-logistica/demo-001/`. O identificador da execução é de uso único. O operador pode escolher uma raiz privada alternativa com a opção global `--raiz` antes do subcomando. O banco SQLite guarda o histórico inclusive após reinício. Uma versão substituída ou rejeitada invalida as autorizações pendentes.

## Controles e diagnóstico

| Recurso | Comportamento na execução do plano |
| --- | --- |
| Fontes | O host prepara uma cópia limitada dos cinco CSVs conhecidos e dos XML de CT-e. A sandbox os recebe em leitura. Perfis de ERP, TMS e XML usam amostras limitadas. O host mantém o perfil em `fontes.json`. |
| Projeto dbt | `models/` começa **vazio e gravável**: quem escreve os modelos é o harness. Configuração, testes, definições, macros, `ingerir.py` e `exportar.py` são somente leitura. O pipeline feito à mão não é copiado para a sandbox; só o executor `roteirizado` o escreve, pelas mesmas ferramentas. O plano do 01_demo autoriza `editable_models: ["models/*"]`. O diretório de trabalho para o DuckDB, logs e resultados tem escrita. |
| Execução | Contêiner sem rede, com usuário sem root, filesystem raiz de leitura, CPU, memória, processos e duração de comandos limitados. Compartilha o kernel do host. O processo de controle tem acesso ao daemon local. |
| Ferramentas | Leitura do plano projetado, perfilamento por identificador, escrita de SQL em `models/` que case com `editable_models` (caminho ou padrão), comandos dbt em lista permitida, consultas em modo leitura e emissão de eventos. A sandbox em nuvem fica fora desta versão da demo. |
| Construção e correção | O harness constrói (`construir_e_verificar`); uma construção sem modelos escala para uma pessoa sem build. Depois, `dbt build` com os testes protegidos e a exportação no contrato de saída (`exportar.py`). Toda falha do dbt com código 1 ou 2 (modelo, teste ou compilação) e da exportação vira `implementacao` e volta ao agente, até três correções; depois, `intervention_requested` e nenhuma avaliação. Tempo esgotado e falha de Docker ou sandbox escalam direto. Ações e custo estimado ficam em `eventos.jsonl` e `medicao.json`. |
| Avaliação | O contêiner para antes da captura. O host verifica tipo, tamanho e hash dos arquivos e compara fontes, regras, três KPIs, pedidos e viagens com a referência protegida. O laudo completo fica em `avaliacao.json`. |
| Entrega | A aprovação da entrega vincula a execução, o destino e o manifesto. A promoção copia `kpis.json`, `por_pedido.csv` e `por_viagem.csv` para a pasta autorizada. Modelos e documentação técnica estão no repositório. A embalagem completa para o cliente e a interface são itens de integração da K13. |

A sandbox avulsa da fixture do Gabriel copia os modelos da fixture para `models/`. No worker, `models/` começa vazio. A evidência de cálculo, as premissas fiscais da demo e o percurso de um resultado até a fonte estão no [pipeline logístico](pipeline/README.md). O [avaliador](../../evaluation/worker/README.md) documenta as tolerâncias e a comparação por entidade.

## Verificação

```bash
python scripts/check_repo.py
python -m unittest discover -s services/planning/tests
python -m unittest discover -s services/execution/pipeline/tests
python -m unittest discover -s evaluation/worker/tests
KORDA_EXIGIR_DOCKER=1 python -m unittest discover -s services/execution/tests -t services/execution -v
```

Os [aceites do worker](tests/test_worker_docker.py) usam o gerador da 01 e nenhum LLM. Com o executor `falso` (o mesmo caminho do `chat`, com respostas roteiradas pelo `ClienteChatFalso`): o agente constrói a partir de `models/` vazio e o avaliador aprova; uma falha sem solução para em `limite_atingido` depois de 3 correções, com uma `intervention_requested` e sem avaliação; uma construção sem modelos escala sem build. Com o `roteirizado`: um defeito plantado na cópia do modelo de CT-e falha no teste de unicidade, é corrigido no segundo build e o resultado aguarda a segunda aprovação. A recusa de escrita em testes e fontes é verificada no hook, nas ferramentas e no kernel ([`test_sandbox.py`](tests/test_sandbox.py), `TestSandboxDeConstrucao`). O job de execução da [CI](../../.github/workflows/ci.yml) exige acesso ao Docker e a imagem construída. Sem a variável de exigência, o unittest identifica os casos Docker pulados. [Planejamento e evidências desta entrega](../../docs/plano-integracao-worker.md)

Os testes de nível 1 também precisam de `docker build -t korda-simulados:dev infra/sistemas-simulados` e `docker pull postgres:17.6-alpine`. Sem Docker, sem as imagens ou sem as fontes geradas, os testes de integração são **pulados** (o resumo do unittest mostra `skipped`). Com `KORDA_EXIGIR_DOCKER=1`, isso vira falha, como no CI. A imagem pode ser trocada por `KORDA_SANDBOX_IMAGE`. A integração da ingestão com a 03_reservada só roda com `KORDA_MEDIR_03=1`, porque essa empresa é só para medição. Os unitários da ingestão rodam dentro da imagem (comando em [`korda_ingestao/README.md`](../../infra/sandbox/korda_ingestao/README.md#testes)).

## Estado (26/11/2026)

**Rascunho para [K08](https://github.com/leeunam/korda/issues/8), [K09](https://github.com/leeunam/korda/issues/9) e [K10](https://github.com/leeunam/korda/issues/10).** Existem a sandbox local em Docker, as ferramentas restritas, a ingestão de níveis 0 e 1, o worker com as duas aprovações, o ciclo de até três correções e o avaliador independente, com testes. **O worker está ligado ao harness** (decisão de 25/11/2026: o harness constrói; o worker orquestra). A construção, as correções e o retorno de perguntas foram verificados **só sem LLM**: com o executor `falso` e com o `roteirizado`, no Docker. **A construção nunca rodou com LLM real**; o único uso real até agora foi o teste de fumaça do gateway. O `planejar` gera a construção antes da aprovação 1 ou devolve perguntas quando falta contexto. **O `planejar` foi validado com duas chamadas reais em 27/11/2026** (`anthropic/claude-opus-5.5`, custo estimado pelos tokens): no contexto fictício 02 gerou um plano válido e registrável (4.870/6.729 tokens, ~US$ 0,15); no 01 devolveu uma pergunta sobre a base de rateio (4.690/5.216 tokens, ~US$ 0,12). As saídas estão em [`tests/fixtures/planejamento/`](tests/fixtures/planejamento/). O worker recusa o `agente_sdk`. **Ainda não existem nesta versão:** o ensaio real no 01_demo, a sandbox em nuvem e a unificação das duas ingestões. O worker ainda recebe fontes brutas (`exigir_manifesto=False`); a sandbox avulsa exige a landing zone. Os tipos de evento são provisórios até a [K01](https://github.com/leeunam/korda/issues/1).

## Componentes

| Caminho | Conteúdo |
| --- | --- |
| [`../../infra/sandbox/`](../../infra/sandbox/Dockerfile) | Imagem da sandbox: dbt-core, dbt-duckdb, duckdb e lxml fixados, usuário sem root, `consulta.py` (SQL somente leitura), `perfil.py` e o pacote de ingestão. |
| [`../../infra/sandbox/korda_ingestao/`](../../infra/sandbox/korda_ingestao/README.md) | Ingestão de nível 0 que roda no contêiner: CSV e CT-e em XML → Parquet, `_rejeitados` e `manifesto.json`. |
| [`korda_execution/ingestao.py`](korda_execution/ingestao.py) | `ingerir()` e CLI: sobe o contêiner de ingestão sem rede, com as fontes brutas somente leitura. |
| [`korda_execution/ingestao_n1.py`](korda_execution/ingestao_n1.py) | `executar_ingestao()`: roda um código de ingestão de nível 1 só na rede interna do [ambiente simulado](../../infra/sistemas-simulados/README.md), com plano, CT-e e código somente leitura e credenciais por `--env-file` temporário. |
| [`referencia/`](referencia/README.md) | Ingestão de nível 1 de referência (plano B e base de comparação), fora da imagem e fora do alcance do agente. |
| [`korda_execution/sandbox.py`](korda_execution/sandbox.py) | Interface `Sandbox` (`criar`, `enviar_arquivos`, `rodar_comando`, `destruir`) e `LocalDockerSandbox`. |
| [`korda_execution/worker.py`](korda_execution/worker.py) | Orquestração: configuração, documento-base, sandbox, harness, avaliador e revisão. |
| [`korda_execution/ferramentas.py`](korda_execution/ferramentas.py) | Ferramentas que o harness expõe ao agente. |
| [`korda_execution/caminhos.py`](korda_execution/caminhos.py) | Política de caminhos e lista branca do dbt. |
| [`korda_execution/harness/`](korda_execution/harness/README.md) | Executores (`chat` constrói e corrige pela API da Feita; `roteirizado` como plano B; `falso` para testes; `agente_sdk` guardado, recusado pelo worker), política e hook, contexto, orçamento, medição, `construir_e_verificar` e adaptador provisório de eventos (com custo) para o front. |
| [`korda_execution/planejamento.py`](korda_execution/planejamento.py) | Comando `planejar`: uma chamada à API gera a construção (anexada ao plano) ou as perguntas para a descoberta. |
| [`korda_execution/documento_base.py`](korda_execution/documento_base.py) | Prompt do planejamento da construção e leitura da decisão (`pronto_para_construir`, `perguntas`). |
| [`korda_execution/contrato_saida.py`](korda_execution/contrato_saida.py) | Nomes fixos de modelos e colunas, lidos dos testes protegidos e do `exportar.py`, enviados ao planejamento. |
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
| `/work/projeto` | cópia do projeto (`dbt_project.yml`, `profiles.yml`, `definicoes/`, `tests/`, `macros/`, `ingerir.py`, `exportar.py`) | somente leitura |
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
