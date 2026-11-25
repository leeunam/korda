# Contratos compartilhados

Definir aqui os formatos e exemplos antes de integrar as frentes. O [contexto logístico sintético v0.1.0](context/v0.1.0/README.md) possui JSON Schema, validador e exemplos de rateio pendente/confirmado para o desenvolvimento local de P1/P2. Os demais contratos e o aceite conjunto das quatro frentes continuam pendentes.

| Contrato | Conteúdo necessário |
| --- | --- |
| Contexto | Respostas, evidências, lacunas, prioridade e estado |
| Plano | Versão, fontes, regras, indicadores, testes e tarefas |
| Aprovação | Tipo, versão aprovada, pessoa, horário e decisão |
| Evento | Execução, etapa, tipo, mensagem, tentativa e horário |
| Artefatos | Indicadores, modelos, relatórios, documentação e destino |

Revisar conjuntamente enumerações, obrigatoriedade, erros e compatibilidade. A proposta original de eventos inclui `task_started`, `file_written`, `test_passed`, `test_failed`, `fix_applied`, `approval_requested` e `run_completed`; ela não cobre sozinha todo o ciclo de promoção. Fechar esse ponto antes de conectar a UI.
