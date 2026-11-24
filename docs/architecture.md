# Arquitetura de referência

**Status:** desenho inicial, não implementação verificada. Um monorepositório facilita contratos e integração de uma equipe de quatro pessoas; os diretórios não obrigam microsserviços ou deploys separados.

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

A UI deve distinguir execução concluída, aguardando aprovação e entrega promovida. Se o plano mudar, uma aprovação anterior não vale para a nova versão. A máquina de estados, as validações e a persistência ainda serão implementadas.

## Base técnica proposta

Python, DuckDB e dbt são a base para processamento local e modelos. O [plano técnico da descoberta](plano-arquitetura-agentes-descoberta.md), atualizado em 24/11/2026, propõe FastAPI, PostgreSQL e Procrastinate para o backend de Marcus, com pesquisa, entrevista, perfilamento e contexto versionado. LiveKit e Tavus são candidatos para a entrevista ao vivo, com retomada por texto. Essas integrações ainda serão implementadas e testadas.

O frontend está em desenvolvimento por outro integrante. Sua conexão ao backend ocorrerá depois, com contratos OpenAPI, exemplos de respostas e alinhamento da autenticação. A stack e a hospedagem da interface pertencem àquela frente.

A sandbox da demo pode começar com um worker controlado e um diretório por execução. Isso **não equivale a isolamento de produção**. Antes de executar código gerado, impor limites de tempo/memória, operações permitidas, diretórios montados e acesso de rede. Credenciais e respostas esperadas não entram no contexto do executor.

## Contratos antes de implementação paralela

Versionar em `packages/contracts/`: contexto/lacunas, plano, aprovação, evento, execução e manifesto de artefatos. Campos, enumerações, exemplos e transições são parte do aceite conjunto. Identificadores mínimos a avaliar: `project_id`, `run_id`, versão do plano e correlação do evento.

O executor deve escrever somente nos modelos permitidos e consultar fontes sem modificá-las. Testes de aceite e gabaritos ficam em área independente. Uma instrução de prompt, um arquivo somente leitura dentro do Git ou a revisão de um PR não substituem controles de execução.

## Avaliação

Testes estruturais do dbt cobrem qualidade de tabelas; uma avaliação independente compara indicadores com respostas conhecidas. Incluir duplicatas, cancelamentos, pedido incompleto, atraso e ocupação. Verificar também resultados por entidade: um total correto pode esconder um rateio incorreto.

Gabaritos públicos documentam a demo, mas não demonstram generalização. O runtime deve receber somente as fontes e as condições de aceite apropriadas, com resultados esperados calculados por um avaliador separado.
