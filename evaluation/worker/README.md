# Aceite independente do worker

O processo de revisão compara os resultados de uma execução encerrada com os arquivos versionados em `evaluation/golden/<empresa>/`. A comparação dos CSV de resultados usa a biblioteca padrão do Python 3.11+ em Linux. A revisão de uma landing lê Parquet com PyArrow 24.0.0 no host. Ele não executa modelos, lê bancos DuckDB gerados nem importa código do pipeline.

O responsável pela execução escolhe o cenário, a pasta de fontes efetivamente montada e a pasta de resultados. Para conferir um build da demo a partir da raiz do repositório, use os caminhos reais da execução.

```bash
python3 -m evaluation.worker.avaliador --empresa 01_demo \
    --resultados runs/minha-execucao/saida/resultados \
    --fontes data/synthetic/output/01_demo
python3 -m unittest discover -s evaluation/worker/tests -v
```

| Artefato do produtor | Verificação |
| --- | --- |
| `kpis.json` | Três indicadores no objeto `kpis`. OTIF e ocupação em porcentagem. Um resultado sem denominador deve ser nulo. |
| `por_pedido.csv` | Uma linha por pedido. Confere viagem, tipo, elegibilidade, CT-e, custo rateado, datas, prazo, completude e OTIF. |
| `por_viagem.csv` | Uma linha por viagem. Confere veículo, tipo, carga, capacidade, unidade, ocupação em fração, excesso, contagens e custos. |

A comparação admite mudanças na ordem das linhas e dos CT-e de um pedido. Identificadores ausentes, repetidos ou inesperados reprovam a execução. Os campos presentes e os cabeçalhos de referência estão nos CSVs de cada cenário. Custos por pedido e por viagem precisam coincidir até o centavo. Os indicadores e a ocupação por viagem admitem metade da última casa decimal publicada pelo gabarito. No empate exato comprovado por carga e capacidade da referência, a ocupação por viagem admite os dois vizinhos da quarta casa porque o gabarito histórico acumula a carga em ponto flutuante. Para a carga o limite é 0,0005 da unidade. Os arquivos de resultado têm limite de 8 MiB cada e 20 mil linhas por CSV.

O laudo JSON contém o cenário, as checagens de fontes e regras efetuadas, as contagens comparadas e até 20 divergências com os valores esperados e encontrados. A CLI sai com código 0 quando os resultados conferem e 1 em divergência ou erro. A função `avaliar(resultados, empresa_id, *, fontes=None, regras=None, landing=None, janela_replay=None)` também atende revisões avulsas de dados sintéticos. O controlador integrado fornece as fontes, regras e landing congeladas da execução. Na simulação N1, ele também informa o dia liberado e o último dia do catálogo. Ao informar as fontes, o avaliador confere o conjunto e o SHA-256 dos CSV de ERP/TMS e dos XML de CT-e. Um parâmetro omitido deixa a respectiva conferência desmarcada.

| Classe | Interpretação |
| --- | --- |
| `dados` | O conjunto de fontes ou seu conteúdo difere do manifesto do cenário. |
| `regra` | O cenário não tem referência disponível ou a política informada diverge da referência. Requer revisão humana. |
| `implementacao` | O pacote de resultados está incompleto, tem formato inválido ou apresenta valores divergentes. |
| `ok` | Os três artefatos coincidem com a referência para as verificações registradas. |

O controlador confiável deve encerrar os escritores antes da avaliação e manter a pasta de revisão fora das montagens do executor. O avaliador abre somente os três nomes previstos por descritor, recusa links, arquivos especiais e arquivos acima do limite. O laudo detalhado pertence ao revisor. Ao executor pode voltar o diagnóstico geral, sem os valores esperados. O aceite numérico de uma referência sintética continua sujeito à revisão humana das regras e à aprovação separada da promoção.

## Landing e replay da demonstração

Para a `01_demo`, o revisor começa pelos hashes do lote bruto no gabarito versionado. Num processo externo ao executor, abre os nove Parquets de origem e a tabela de rejeições. Compara as identidades e valores físicos de todos os registros ERP/TMS com o lote conferido. Para os documentos fiscais, verifica nomes e hashes de todos os arquivos, inclusive reenvios e cancelamentos, os campos usados pelos modelos, os vínculos com NF-e e a carga declarada. Em seguida confere a linhagem exportada por pedido e veículo, a associação dos CT-e e seus centavos com cada pedido e os indicadores por entidade.

| Entrada do revisor | Conferências específicas |
| --- | --- |
| N0, exportação de arquivos | O inventário de arquivos do manifesto coincide com os hashes de origem. As linhas de ERP/TMS remetem à posição física do registro no CSV. |
| N1, sistemas simulados | O dia liberado pelo controlador deve coincidir com o último dia do catálogo e do lote verificado. Consideram-se o último snapshot de ERP e os registros TMS/CT-e das cargas confirmadas. Origens, números de carga, marcas de atualização do TMS e inventário fiscal são confrontados com a landing e o estado persistido. |
| N1, janela parcial ou sem prova | A comparação com o gabarito integral fica bloqueada. O controlador pode consultar a janela parcial antes de construir modelos ou ler os resultados. |

O parâmetro `janela_replay` recebe duas datas ISO fornecidas pelo controlador a partir do ambiente sintético sob seu controle. Mantenha `evaluation/`, o lote de referência, o estado privado da ingestão e o laudo detalhado fora das montagens dos modelos. As verificações `landing_conferida` e `linhagem_conferida` aparecem no laudo do fluxo integrado. Para conferir uma execução integral pela CLI use `--landing`, `--fontes` e `--regras` com o arquivo de valores das regras. No N1, acrescente `--janela-replay DIA_ATUAL DIA_FINAL`.
