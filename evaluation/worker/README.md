# Aceite independente do worker

**Fora do fluxo do worker desde 27/11/2026.** Comparar cada execução com um gabarito escrito à mão prendia o agente a uma solução específica. O worker não chama mais este avaliador: a execução fica pronta para a aprovação 2 quando o build, os testes protegidos e o contrato de saída passam. O avaliador continua como ferramenta offline de medição (K11/K14, cenário `03_reservada`), rodada à mão sobre os resultados de uma execução encerrada.

O processo de revisão compara os resultados de uma execução encerrada com os arquivos versionados em `evaluation/golden/<empresa>/`. O avaliador usa apenas a biblioteca padrão do Python 3.11+ em Linux. Ele não executa modelos, lê bancos DuckDB gerados nem importa código do pipeline.

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

O laudo JSON contém o cenário, as checagens de fontes e regras efetuadas, as contagens comparadas e até 20 divergências com os valores esperados e encontrados. A CLI sai com código 0 quando os resultados conferem e 1 em divergência ou erro. A função `avaliar(resultados, empresa_id, *, fontes=None, regras=None)` aceita o mesmo caminho e, opcionalmente, as cinco regras variáveis no vocabulário de `regras_referencia`. Ao informar as fontes, o avaliador confere o conjunto e o SHA-256 dos CSV de ERP/TMS e dos XML de CT-e. Um parâmetro omitido deixa a respectiva conferência desmarcada.

| Classe | Interpretação |
| --- | --- |
| `dados` | O conjunto de fontes ou seu conteúdo difere do manifesto do cenário. |
| `regra` | O cenário não tem referência disponível ou a política informada diverge da referência. Requer revisão humana. |
| `implementacao` | O pacote de resultados está incompleto, tem formato inválido ou apresenta valores divergentes. |
| `ok` | Os três artefatos coincidem com a referência para as verificações registradas. |

O controlador confiável deve encerrar os escritores antes da avaliação e manter a pasta de revisão fora das montagens do executor. O avaliador abre somente os três nomes previstos por descritor, recusa links, arquivos especiais e arquivos acima do limite. O laudo detalhado pertence ao revisor. Ao executor pode voltar o diagnóstico geral, sem os valores esperados. O aceite numérico de uma referência sintética continua sujeito à revisão humana das regras e à aprovação separada da promoção.
