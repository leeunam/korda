# Avaliação independente do contexto v0.2.0

Este ensaio usa dados **sintéticos**, escritos para exercitar relações, evidências,
correções, conflito e ausência de informação. Não demonstra validação comercial.
Os testes com modelos simulados verificam a mecânica, não a qualidade de uma IA real.

O [consumidor](consumer.py) lê somente as quatro operações HTTP de um projeto e de
uma revisão imutável. O [avaliador](judge.py) abre o [gabarito](expected.json) em uma
etapa separada; ele nunca é incluído no prompt. As [perguntas](questions.json) são
públicas. O [contexto de ensaio](fixtures/context.json) é um artefato sintético
independente, não uma saída comercial nem prova da extração por um modelo.

## Executar

Instale o backend pelo seu lock. Configure no ambiente, sem valores em comandos ou
arquivos versionados: `CONTEXT_CONSUMER_API_URL`, `CONTEXT_CONSUMER_PROJECT_TOKEN`,
`CONTEXT_LLM_API_KEY`, `CONTEXT_CONSUMER_MODEL` e, se necessário, `CONTEXT_LLM_URL`.
Use somente um projeto de demo com conteúdo sintético e uma revisão real exportada.

```bash
python evaluation/discovery_v02/consumer.py evaluation/discovery_v02/questions.json --project demo --revision 4 --output /tmp/consumer-report.json
python evaluation/discovery_v02/judge.py /tmp/consumer-report.json evaluation/discovery_v02/expected.json /tmp/context-revision-4.json --output /tmp/consumer-judgment.json
```

Os IDs do gabarito precisam corresponder ao contexto publicado no ensaio. Para um
contexto produzido por entrevista real, prepare e revise um gabarito independente
daquela revisão; não renomeie saídas para encaixar artificialmente neste exemplo.

No ambiente do consumidor monte apenas `consumer.py`, as perguntas e o pacote
instalado do backend. Não monte este diretório inteiro, o gabarito, o export usado
pelo avaliador, roteiros de persona ou `evaluation/golden/`. O avaliador roda em
outro processo/contêiner. A separação de arquivos precisa ser imposta pelo ambiente;
um comentário no prompt não implementa isolamento.

## Volume, evidência e GraphRAG

O orçamento inicial é de 8 mil tokens recuperados por pergunta. Como o gateway não
garante uma operação de contagem do tokenizer exato, o padrão executável limita
conservadoramente **8 mil bytes UTF-8** acumulados dos documentos recebidos. Isso é
identificado como `utf8_bytes_conservative`, não como medição exata de tokens.
`ContextReader` aceita um contador exato injetado quando disponível. O relatório
também preserva o uso de tokens e custo retornado pelo gateway; custo ausente não
é inventado. Instruções e pergunta não são confundidas com contexto recuperado.

O relatório registra operações, latência, modelo, chamadas, IDs recuperados e
evidências citadas. Os documentos completos ficam no processo consumidor e não
são copiados para o relatório por padrão. Credenciais nunca entram no relatório.

O avaliador distingue falhas de **extração** (a relação/fato esperado não existe no
contexto), **recuperação** (existe, mas não foi obtido) e **interpretação** (foi
obtido, porém a resposta ou citação está errada). Uma falha no limite conservador
de bytes precisa de medição exata antes de afirmar que 8 mil tokens foram necessários.

GraphRAG não é implementado nem aprovado por esse ensaio. Uma relação importante
presente e não recuperada, orçamento insuficiente ou pedido explícito do histórico
completo sinalizam um caso para comparação controlada. A comparação precisa usar
as mesmas perguntas, revisão, modelo e orçamento e preservar rastreabilidade e
isolamento. Respostas de provedores simulados não justificam adoção de GraphRAG.

## Testes locais

```bash
python -m pytest evaluation/discovery_v02/tests -q
```

O aceite do HTTP e do pipeline está nos testes do backend. Os casos de persistência
requerem PostgreSQL real via `CONTEXT_TEST_DATABASE_URL`; ausência desse banco é
registrada como teste não executado.
