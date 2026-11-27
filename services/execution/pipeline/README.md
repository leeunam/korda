# Pipeline sintético de logística

O worker calcula os três indicadores de `01_demo` sob as nove regras confirmadas da versão aprovada do plano. O script protegido `projeto/ingerir.py` recebe em `/work/fontes` a landing Parquet imutável de Gabriel nos níveis 0 e 1. O plano define a origem dos dados e a execução registra o nível. Os modelos de prata e ouro e as regras de negócio são os mesmos nos dois percursos.

## Contrato da landing

O manifesto usa `korda.landing/v0`. O nível 0 transforma os arquivos fictícios por meio de [korda_ingestao](../../../infra/sandbox/korda_ingestao/README.md). O nível 1 reúne o snapshot ERP, as cargas incrementais do TMS e os novos CT-e dos sistemas simulados. Cada tabela é lida do arquivo canônico no topo da landing. O worker verifica a contagem publicada de cada tabela consumida e recusa cargas com registros rejeitados.

| Caminho na landing | Grão | Uso |
| --- | --- | --- |
| `erp/erp_pedidos.parquet` | Pedido | Prazo prometido, volumes solicitados, peso bruto e vínculo de NF-e |
| `tms/tms_entregas.parquet` | Baixa de entrega | Volumes recebidos, data realizada e viagem |
| `tms/tms_viagens.parquet`, `tms/tms_veiculos.parquet` | Viagem e veículo | Tipo de viagem e capacidade em kg |
| `cte/cte.parquet`, `cte/cte_nfe.parquet` | Cópia física do documento e NF-e referenciada | Valor autorizado e pedidos atendidos |
| `cte/cte_evento.parquet` | Evento e retorno | Cancelamento 110111 homologado com cStat 135 |

Para reconstruir uma cópia individual do CT-e, o adaptador vincula os filhos ao cabeçalho por chave fiscal, arquivo, hash e, no nível 1, carga. A deduplicação por chave fiscal ocorre depois desse vínculo. A projeção bronze tipa centavos, volumes, pesos e datas, preserva as baixas sem data e impede inserir duas baixas para o mesmo pedido. O projeto dbt produz rateios, uma linha ouro por pedido e por viagem e os KPIs agregados.

| Indicador | Cálculo e explicação |
| --- | --- |
| Frete por entrega | Soma do frete rateado pelo peso das entregas cobertas por CT-e válido, dividida pela contagem dessas entregas. A distribuição conserva cada centavo, com desempate dos maiores restos pelo ID textual do pedido. |
| OTIF | Fração dos pedidos entregues até a data prometida inclusiva **e** com os volumes solicitados. A data ausente conta como falha. |
| Ocupação | Peso carregado em kg dividido pela capacidade somada, uma vez por viagem, inclusive viagens vazias. O detalhamento por viagem usa fração, o KPI agregado usa percentual. Excesso de capacidade fica visível. |

Um denominador vazio gera um valor nulo. O meio exato é arredondado para o par, com quatro casas nos KPIs e na fração de ocupação e duas no frete médio por viagem. O valor do frete mede custo, sem atribuir economia financeira ao indicador.

## Exportação e linhagem

`exportar.py` abre o DuckDB em leitura e prepara `kpis.json`, `por_pedido.csv` e `por_viagem.csv` em `/work/saida/resultados`. A publicação do diretório usa renomeação atômica. O coordenador conduz a avaliação independente e a aprovação da entrega.

| Origem | Linhagem preservada nos CSVs finais |
| --- | --- |
| N0 · exportações | `arquivo_*` e `linha_*` apontam para o CSV bruto. A linha 1 é o cabeçalho. |
| N1 · ERP e TMS simulados | `origem_*` e `carga_*` identificam tabela ou recurso e número da carga real. As respectivas chaves do pedido, da entrega, da viagem e do veículo completam a identificação. Os campos de arquivo e linha física ficam vazios. |
| XML em ambos os níveis | Cada parcela em `linhagem_cte` informa a chave, o arquivo relativo à fonte, SHA-256, frete original e centavos atribuídos ao pedido. No N1 a entrada inclui o número da carga; no N0 esse campo é nulo. |

Na exportação N0 de `01_demo`, o pedido 900001 está na linha 3550 de `erp/erp_pedidos.csv`, pesa 100 kg e recebeu R$ 100,00 do CT-e de R$ 400,00. O pedido 900002 tem os outros 300 kg e R$ 300,00. No replay N1, os pedidos vêm de `erp:erp_pedidos` e a baixa vem de `tms:/entregas`.

O manifesto de uma carga N1 descreve o estado acumulado observado. A comparação com o gabarito do mês completo exige cobertura integral comprovada pelo avaliador. A aprovação de um recorte parcial usando o gabarito mensal produziria uma conclusão inválida.

## Testes

Na raiz do repositório, use Python com as dependências de `requirements-synthetic.txt`, DuckDB na versão de `infra/sandbox/requirements.txt`, Jinja2 e SQLite 3.44 ou superior.

```bash
python3 -m unittest discover -s services/execution/pipeline/tests -v
```

A suíte materializa a landing N0 com o leitor oficial e cobre também N1 com o escritor de referência sobre registros sintéticos. O ensaio do lote inteiro regenera as fontes, lê os Parquets, executa os cinco modelos e os testes de qualidade em SQLite e compara os resultados no K11, com os XML e CSV fora do executor. A integração em Docker usa dbt e DuckDB do worker.
