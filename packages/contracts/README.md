# Contratos compartilhados

Definir aqui os formatos e exemplos antes de integrar as frentes. Ainda não existem schemas implementados.

| Contrato | Conteúdo necessário |
| --- | --- |
| Contexto | Respostas, evidências, lacunas, prioridade e estado |
| Plano | Versão, fontes, regras, indicadores, testes e tarefas |
| Aprovação | Tipo, versão aprovada, pessoa, horário e decisão |
| Evento | Execução, etapa, tipo, mensagem, tentativa e horário |
| Artefatos | Indicadores, modelos, relatórios, documentação e destino |

Revisar conjuntamente enumerações, obrigatoriedade, erros e compatibilidade. A proposta original de eventos inclui `task_started`, `file_written`, `test_passed`, `test_failed`, `fix_applied`, `approval_requested` e `run_completed`; ela não cobre sozinha todo o ciclo de promoção. Fechar esse ponto antes de conectar a UI.

## Rascunhos

- [events.schema.json](events.schema.json): evento de execução usado pela UI do grafo (K12). Acrescenta `write_blocked`, `approval_granted` e o campo opcional `data`. **Rascunho** até K01 fechar o contrato; o worker deve emitir este formato.
