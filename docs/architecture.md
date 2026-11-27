# Arquitetura de referência

**Estado desta branch:** o planejamento e a execução da demo logística têm implementação local e testes. Um monorepositório facilita contratos e integração de uma equipe de quatro pessoas; os diretórios não obrigam microsserviços ou deploys separados.

## Responsabilidades

| Frente | Entrada | Saída | Área |
| --- | --- | --- | --- |
| P1 · Contexto | Conversa e fontes autorizadas | Evidências, lacunas e perfil das fontes | `services/context/` |
| P2 · Planejamento | Contexto validado | Plano versionado, regras e testes para aprovação | `services/planning/` |
| P3 · Execução | Plano aprovado e fontes sintéticas | Modelos, indicadores, testes e artefatos | `services/execution/` |
| P4 · Experiência | Estados e eventos | Revisão, duas aprovações e acompanhamento | `apps/web/` |

Não há atribuição nominal das frentes neste arquivo. Os responsáveis devem assumir as issues.

## Fluxo e controle

O contexto pode avançar como rascunho com lacunas. Lacunas críticas bloqueiam a parte afetada do plano. A primeira aprovação registra versão, aprovador e horário. O executor recebe essa versão, cria as camadas bronze, prata e ouro e roda os testes. Falhas geram correções limitadas ou solicitação humana. Passar nos testes não autoriza publicar: a segunda aprovação libera a promoção em destino compatível.

A UI deve distinguir execução concluída, aguardando aprovação e entrega promovida. Se o plano mudar, uma aprovação anterior não vale para a nova versão. O registro SQLite do operador persiste estados e decisões. A conexão da interface com esses estados é uma entrega da K12.

## Base técnica proposta

Python, DuckDB e dbt são a base para processamento local e modelos. O [backend de contexto](../services/context/README.md) implementa FastAPI, PostgreSQL e Procrastinate para entrevista WhatsApp com texto, áudio transcrito e contexto versionado. O recorte aprovado em 27/11/2026 deixa pesquisa, perfilamento e entrevista ao vivo fora desta entrega, substituindo essa parte do plano de 24/11. A publicação usa o Coolify existente; o ensaio com provedores reais depende de configurar as contas.

O frontend está em desenvolvimento por outro integrante. Sua conexão ao backend ocorrerá depois, com contratos OpenAPI, exemplos de respostas e alinhamento da autenticação. A stack e a hospedagem da interface pertencem àquela frente.

A sandbox local usa um processo de controle no host e um contêiner por execução. O contêiner recebe as fontes do lote, a cópia do projeto e limites de tempo, memória e CPU. O registro das duas decisões fica no host. O avaliador independente roda à parte, no host, só para medição (fora do fluxo do worker desde 27/11/2026).

O [guia de execução](../services/execution/README.md) descreve a lista de modelos graváveis do plano, o ciclo de correção da deduplicação, o pacote de entrega e a promoção local do manifesto. O [plano de integração](plano-integracao-worker.md) acompanha as frentes pendentes.

## Contratos antes de implementação paralela

Versionar em `packages/contracts/`: contexto/lacunas, plano, aprovação, evento, execução e manifesto de artefatos. Campos, enumerações, exemplos e transições são parte do aceite conjunto. Identificadores mínimos a avaliar: `project_id`, `run_id`, versão do plano e correlação do evento.

O executor deve escrever somente nos modelos permitidos e consultar fontes sem modificá-las. Testes de aceite e gabaritos ficam em área independente. Uma instrução de prompt, um arquivo somente leitura dentro do Git ou a revisão de um PR não substituem controles de execução.

## Avaliação

Testes estruturais do dbt cobrem qualidade de tabelas; uma avaliação independente compara indicadores com respostas conhecidas. Desde 27/11/2026 essa comparação não decide a execução: ela é medição offline (K11/K14), e a aprovação 2 é decisão humana sobre o pacote de entrega. Incluir duplicatas, cancelamentos, pedido incompleto, atraso e ocupação. Verificar também resultados por entidade: um total correto pode esconder um rateio incorreto.

Gabaritos públicos documentam a demo, mas não demonstram generalização. O runtime deve receber somente as fontes e as condições de aceite apropriadas, com resultados esperados calculados por um avaliador separado.
