# Pipeline sintético de logística

O projeto dbt implementa o layout físico de `01_demo` e as nove decisões do exemplo de contexto v0.1.0 com rateio confirmado. A execução depende da aprovação humana do plano correspondente. Alterar uma regra ou apresentar outro layout exige um plano compatível e implementação correspondente.

Os modelos em `projeto/models/` são escritos à mão: referência e plano B (`KORDA_EXECUTOR=roteirizado`). O worker não os monta na sandbox; ali `models/` começa vazio, e quem escreve é o harness. Testes, definições, `ingerir.py` e `exportar.py` (o contrato de saída) são montados somente leitura.

| Etapa | Origem e destino | Verificação |
| --- | --- | --- |
| Ingestão | `ingerir.py` abre os quatro CSV de pedidos, entregas, veículos e viagens e os XML da pasta `cte/`. Escreve cinco tabelas bronze em uma transação. | Schema, grão e formatos das datas. Campos usados retêm arquivo e linha no CSV e arquivo e SHA-256 no XML. O evento precisa coincidir com o retorno. |
| Custo | `prata_ctes` agrupa chave fiscal e NF-e, seleciona autorizados e exclui cancelamento 110111 homologado com cStat 135. `prata_rateios` divide centavos pelo peso bruto, com desempate pelo ID textual nos maiores restos. | Conservação de centavos por documento, duplicidade, divergências entre cópias e NF-e sem pedido. O denominador conta entregas cobertas por CT-e válido. |
| OTIF | `ouro_por_pedido` une TMS e ERP pelo pedido, compara a data local à data prometida inclusiva e volumes entregues aos pedidos. | Uma baixa por pedido. Baixa sem data ou entrega parcial conta como falha no denominador de OTIF. O prazo do layout já vem materializado no ERP. |
| Ocupação | `ouro_por_viagem` soma o peso bruto em kg e usa a capacidade do veículo uma vez por viagem, inclusive vazia. `ouro_kpis` divide carga total por capacidade total. | Preserva valores acima de 100%. A coluna por viagem é fração. O agregado é percentual. |
| Exportação | `exportar.py` abre o DuckDB em leitura e prepara `kpis.json`, `por_pedido.csv` e `por_viagem.csv` em `/work/saida/resultados/`. | O diretório aparece completo por renomeação na mesma partição. O worker controla a aprovação da entrega. |
| Entrega | Depois do build, o worker roda `dbt docs generate` sem rede e guarda os modelos e o target. O pacote de entrega leva `projeto_dbt/` (modelos do agente + os arquivos protegidos deste projeto + `regras.json`) e `docs_dbt/`. | Ver [pacote de entrega](../README.md#pacote-de-entrega-k13). O `projeto_dbt/` entregue roda de novo na imagem da sandbox e, no 01_demo, reproduz os mesmos `kpis.json` e `por_pedido.csv`. |

O pacote preserva a linhagem mesmo depois de fechar o banco. Em `por_pedido.csv`, a coluna `linhagem_cte` guarda, para cada parcela, a chave e o SHA-256 do XML, seu caminho no lote, o valor original e os centavos atribuídos ao pedido. No lote `01_demo`, o pedido **900001** aparece na linha 3550 de `erp/erp_pedidos.csv`, pesa 100 kg e recebeu R$ 100,00 do CT-e de R$ 400,00 cuja chave termina em `126126880`. O pedido 900002 tem os outros 300 kg e R$ 300,00. A baixa do primeiro pedido, na linha 300 de `tms/tms_entregas.csv`, informa os quatro volumes entregues no prazo. `por_viagem.csv` identifica arquivo e linha da viagem e do veículo. A tabela interna `bronze_documentos` também permite encontrar as cópias e eventos pela chave antes de encerrar a sandbox.

No cenário de ajuste, o modelo calcula a média de frete das entregas elegíveis. Esse número em reais é um indicador de custo. A demo não mede economia financeira realizada. Os denominadores vazios geram valores nulos. As razões são arredondadas em meios exatos para o par, com quatro casas decimais nos KPIs e na fração de ocupação e duas no frete médio por viagem.

## Reproduzir o ensaio de lote completo

Na raiz do repositório, use um Python com SQLite 3.44 ou superior, Jinja2 e as dependências de `requirements-synthetic.txt`. O comando roda a fixture calculada à mão e gera o lote inteiro de `01_demo` em um diretório temporário.

```bash
python3 -m unittest discover -s services/execution/pipeline/tests -v
```

O teste de lote executa os cinco modelos e as verificações SQL de `projeto/tests/` em SQLite, exporta os resultados e chama o avaliador independente K11 depois de fechar o banco. Também percorre o pacote entregue, confere as linhas físicas e os hashes dos XML e exige a conservação de cada centavo por CT-e. O comando exercita os cálculos e a linhagem sem Docker. A integração do worker com dbt e DuckDB na imagem real tem seu próprio teste em `services/execution/tests/test_worker_docker.py`.
