# Contratos compartilhados

Definir aqui os formatos e exemplos antes de integrar as frentes. O [contexto logístico sintético v0.1.0](context/v0.1.0/README.md) possui JSON Schema, validador e exemplos de rateio pendente/confirmado para o desenvolvimento local de P1/P2. O [plano v0.2.0](plan/v0.2.0/README.md) vincula os modelos e a ingestão N0 ou N1 à primeira aprovação. O worker também executa o [plano v0.1.0](plan/v0.1.0/README.md) com a permissão original. O registro local de aprovação, os eventos e o manifesto já são usados na demo. O aceite conjunto dessas interfaces pelas quatro frentes continua pendente.

| Contrato | Conteúdo necessário |
| --- | --- |
| Contexto | Respostas, evidências, lacunas, prioridade e estado |
| Plano | Versão, fontes, regras, indicadores, testes e tarefas |
| Aprovação | Tipo, versão aprovada, pessoa, horário e decisão |
| Evento | Execução, etapa, tipo, mensagem, tentativa e horário |
| Artefatos | Indicadores, modelos, relatórios, documentação e destino |

Revisar conjuntamente enumerações, obrigatoriedade, erros e compatibilidade. A proposta original de eventos inclui `task_started`, `file_written`, `test_passed`, `test_failed`, `fix_applied`, `approval_requested` e `run_completed`; ela não cobre sozinha todo o ciclo de promoção. Fechar esse ponto antes de conectar a UI.

## Rascunhos

- [events.schema.json](events.schema.json): evento de execução usado pela UI do grafo (K12). Acrescenta `write_blocked`, `approval_granted` e o campo opcional `data`. **Rascunho** até K01 fechar o contrato; o worker deve emitir este formato. Enquanto o worker emite outro formato, o [adaptador provisório](../../services/execution/korda_execution/harness/README.md#adaptador-de-eventos-para-o-front-provisório) traduz os eventos.

Proposta em andamento: [seção de ingestão do plano v0.1.0](ingestion_plan/v0.1.0/README.md), com schema, validador e exemplos sintéticos. Ainda sem revisão conjunta das frentes.
