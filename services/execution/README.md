# P3 · Execução

Recebe plano aprovado e fontes sintéticas. Produz modelos bronze/prata/ouro, indicadores, relatório de testes, documentação e linhagem. Base: Python, DuckDB e dbt.

O executor não modifica fontes, testes ou gabaritos. Até três correções por etapa é o limite inicial proposto. Falha persistente, mudança de regra ou lacuna crítica devem interromper o trecho afetado. Somente a aprovação 2 permite promover a entrega para destino definido.

## Estado (23/11/2026)

**Rascunho para [K08](https://github.com/leeunam/korda/issues/8) e [K09](https://github.com/leeunam/korda/issues/9).** Existem a sandbox local em Docker, as ferramentas restritas e a ingestão de nível 0 (arquivos exportados → landing zone em Parquet), com testes. **Ainda não existem:** o agente (harness com LLM, K10), o ciclo de correção com limite, os modelos dos três indicadores (K09), as aprovações (K07) e a sandbox em nuvem. Os tipos de evento são provisórios até a [K01](https://github.com/leeunam/korda/issues/1).

| Caminho | Conteúdo |
| --- | --- |
| [`../../infra/sandbox/`](../../infra/sandbox/Dockerfile) | Imagem da sandbox: dbt-core, dbt-duckdb, duckdb e lxml fixados, usuário sem root, `consulta.py` (SQL somente leitura) e o pacote de ingestão. |
| [`../../infra/sandbox/korda_ingestao/`](../../infra/sandbox/korda_ingestao/README.md) | Ingestão de nível 0 que roda no contêiner: CSV e CT-e em XML → Parquet, `_rejeitados` e `manifesto.json`. |
| [`korda_execution/ingestao.py`](korda_execution/ingestao.py) | `ingerir()` e CLI: sobe o contêiner de ingestão sem rede, com as fontes brutas somente leitura. |
| [`korda_execution/ingestao_n1.py`](korda_execution/ingestao_n1.py) | `executar_ingestao()`: roda um código de ingestão de nível 1 só na rede interna do [ambiente simulado](../../infra/sistemas-simulados/README.md), com plano, CT-e e código somente leitura e credenciais por `--env-file` temporário. |
| [`referencia/`](referencia/README.md) | Ingestão de nível 1 de referência (plano B e base de comparação), fora da imagem e fora do alcance do agente. |
| [`korda_execution/sandbox.py`](korda_execution/sandbox.py) | Interface `Sandbox` (`criar`, `enviar_arquivos`, `rodar_comando`, `destruir`) e `LocalDockerSandbox`. |
| [`korda_execution/ferramentas.py`](korda_execution/ferramentas.py) | Ferramentas que o harness vai expor ao agente. |
| [`korda_execution/caminhos.py`](korda_execution/caminhos.py) | Política de caminhos e lista branca do dbt. |
| [`korda_execution/eventos.py`](korda_execution/eventos.py) | `emit_event` provisório (JSONL por execução). |
| [`korda_execution/smoke.py`](korda_execution/smoke.py) | Teste de fumaça: ingere as fontes do gerador e sobe a sandbox sobre a landing. |
| [`tests/`](tests/fixtures/README.md) | Testes unitários e de integração; fixture dbt com dados sintéticos. |

O worker (processo Python no host) usa só a biblioteca padrão e o CLI do Docker. As dependências ficam na imagem.

Fluxo de nível 0: **fontes brutas** (`data/synthetic/output/<empresa>`) → **ingestão** (contêiner efêmero) → **landing zone** em Parquet → **sandbox** (`/work/fontes`). A ingestão não limpa nada: duplicatas, cancelados e formatos mistos chegam intactos para o agente tratar conforme o plano. Detalhes em [`korda_ingestao/README.md`](../../infra/sandbox/korda_ingestao/README.md).

Fluxo de nível 1: **sistemas simulados** (ERP em Postgres, TMS por API, pasta de CT-e; replay por dias) → **código de ingestão** que segue a [seção de ingestão do plano](../../packages/contracts/ingestion_plan/v0.1.0/README.md) → a **mesma landing**, com cargas incrementais. Hoje o código é a [referência](referencia/README.md); o agente (K10) ainda não existe. Os testes de aceite do plano estão em [`tests/test_ingestao_n1.py`](tests/test_ingestao_n1.py).

## Como rodar

Requer Docker e Python 3.11+.

```bash
docker build -t korda-sandbox:dev infra/sandbox
python3 -m unittest discover -s services/execution/tests -t services/execution

# Com as fontes do gerador (ver data/synthetic/README.md):
python3 data/synthetic/generator/generate.py --empresa 01_demo
cd services/execution
python3 -m korda_execution.ingestao --fontes ../../data/synthetic/output/01_demo --destino ../../data/synthetic/landing/01_demo
python3 -m korda_execution.smoke --landing ../../data/synthetic/landing/01_demo   # ou --fontes <bruto>, que ingere antes
```

Os testes de nível 1 também precisam de `docker build -t korda-simulados:dev infra/sistemas-simulados` e `docker pull postgres:17.6-alpine`. Sem Docker, sem as imagens ou sem as fontes geradas, os testes de integração são **pulados** (o resumo do unittest mostra `skipped`). Com `KORDA_EXIGIR_DOCKER=1`, isso vira falha, como no CI. A imagem pode ser trocada por `KORDA_SANDBOX_IMAGE`. A integração da ingestão com a 03_reservada só roda com `KORDA_MEDIR_03=1`, porque essa empresa é só para medição. Os unitários da ingestão rodam dentro da imagem (comando em [`korda_ingestao/README.md`](../../infra/sandbox/korda_ingestao/README.md#testes)).

## Como funciona

Cada execução cria `runs/<run_id>/` (ignorado pelo Git) com uma cópia do projeto dbt e uma pasta `saida/`, e sobe um contêiner com:

| Dentro do contêiner | Origem | Acesso |
| --- | --- | --- |
| `/work/fontes` | landing zone (Parquet + `manifesto.json`); `_gerador/` coberta por um tmpfs vazio, se existir | somente leitura |
| `/work/projeto` | cópia do projeto (`dbt_project.yml`, `profiles.yml`, `definicoes/`, `tests/`) | somente leitura |
| `/work/projeto/models` | `runs/<run_id>/projeto/models` | escrita |
| `/work/saida` | `runs/<run_id>/saida` (`korda.duckdb`, `target/`, `logs/`) | escrita |
| `/tmp` | tmpfs de 256 MB, `noexec` | escrita |
| resto do sistema | imagem | somente leitura (`--read-only`) |

Opções do contêiner: `--network none`, `--cap-drop ALL`, `no-new-privileges`, usuário do host (o worker se recusa a rodar como root), 2 GB de memória sem swap, 1 CPU, 256 processos. Cada comando roda com `timeout -s KILL` dentro do contêiner.

`LocalDockerSandbox` recusa uma pasta de fontes sem `manifesto.json` (`exigir_manifesto=True`), para que a sandbox não receba fontes brutas por engano. As fontes do dbt apontam para a landing, por exemplo `external_location: "read_parquet('/work/fontes/{name}.parquet')"`.

O projeto dbt precisa declarar `model-paths: ["models", "definicoes"]`. Fontes e testes de esquema ficam em `definicoes/` (protegida), e os modelos materializam como tabela, porque a consulta somente leitura não acessa arquivos.

### Ferramentas do agente

| Ferramenta | Permite | Recusa |
| --- | --- | --- |
| `escrever_modelo(caminho, conteudo)` | `models/**/*.sql` | YAML, Python, `..`, `.`, caminho absoluto, fora de `models/` |
| `ler_arquivo(caminho)` | arquivos do projeto dbt | caminhos fora de `/work/projeto` |
| `rodar_dbt(subcomando, selecao)` | `build`, `run`, `test`, `compile`, `ls`, `debug` | `deps`, `seed`, `run-operation`, opções na seleção |
| `consultar_sql(sql)` | `SELECT` no `korda.duckdb` (até 200 linhas) | escrita, `COPY`, `read_csv`, `ATTACH`, mudar configuração |

Há duas barreiras. A política em `caminhos.py` recusa cedo e explica o motivo ao agente. A barreira real são as montagens: escritas e leituras passam **por dentro do contêiner**, então o kernel recusa o que estiver fora de `models/` e `saida/`, mesmo via symlink. `rodar_comando` é interno do worker e não é exposto ao agente.

## Limites conhecidos

- **Não é isolamento de produção.** O contêiner compartilha o kernel do host. Para dados de clientes seriam necessários microVM (gVisor, Firecracker) ou sandbox gerenciada, além de revisão de segurança.
- O worker precisa de acesso ao Docker (grupo `docker`, equivalente a root no host). O agente nunca recebe esse acesso nem o socket.
- Código do agente roda dentro da sandbox: um modelo Python do dbt ou um hook SQL executa com as permissões do contêiner. Ele pode escrever em `models/` e `saida/`, mas não em fontes nem em testes.
- A ingestão não valida o XSD dos CT-e, e sua heurística de cabeçalho pode errar em casos ambíguos (ver [limites da ingestão](../../infra/sandbox/korda_ingestao/README.md#limites-conhecidos)).
- `_gerador/` é ocultada por nome, na ingestão e na sandbox. Outra pasta de respostas dentro das fontes precisaria ser adicionada em `ocultar_nas_fontes`. Os gabaritos (`evaluation/`) não são montados.
- A imagem não tem git nem rede: `dbt deps` não funciona, e `dbt debug` só com `--connection`.
- As dependências transitivas da imagem não estão fixadas, só as três principais.
- Os eventos vão para um JSONL local; o backend (P4) não está escolhido.
