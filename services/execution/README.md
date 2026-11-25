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
