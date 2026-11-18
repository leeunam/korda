# Backlog inicial

Este arquivo registra o ponto de partida. Depois da publicação, o estado atualizado fica nas issues e no Kanban do GitHub. IDs K01–K17 permitem vincular dependências antes da criação das issues.

| ID | Entrega | Prioridade | Frente | Estado inicial | Dependências para iniciar |
| --- | --- | --- | --- | --- | --- |
| K01 | Fechar contratos entre as quatro frentes | P0 | platform | Pronto | Nenhuma |
| K02 | Aprovar as regras dos três indicadores e os casos esperados | P0 | planning | Pronto | Nenhuma |
| K03 | Criar as fontes sintéticas ERP, TMS e CT-e | P0 | execution | Backlog | K01, K02 |
| K04 | Implementar a entrevista e o registro de lacunas | P0 | context | Backlog | K01 |
| K05 | Inspecionar as fontes e relacioná-las às regras | P0 | context | Backlog | K01, K03 |
| K06 | Gerar o plano rastreável de implementação | P0 | planning | Backlog | K01, K02, K04, K05 |
| K07 | Implementar as duas aprovações e os estados do trabalho | P0 | platform | Backlog | K01, K06 |
| K08 | Preparar o ambiente de execução e as ferramentas restritas | P0 | execution | Backlog | K01, K03 |
| K09 | Construir o pipeline dos três indicadores | P0 | execution | Backlog | K02, K03, K06, K07, K08 |
| K10 | Implementar o ciclo de correção com limite e escalonamento | P1 | execution | Backlog | K08, K09, K11 |
| K11 | Validar os resultados com testes independentes e protegidos | P0 | execution | Backlog | K02, K03, K08 |
| K12 | Montar o painel do cliente e a linha do tempo | P0 | web | Backlog | K01 |
| K13 | Entregar resultados, documentação e artefatos após autorização | P0 | platform | Backlog | K07, K09, K11, K12 |
| K14 | Medir esforço humano, custo e qualidade sem confundir metas com resultados | P1 | business | Pronto | Nenhuma |
| K15 | Preparar a demo completa e o roteiro de apresentação | P1 | business | Backlog | K10, K12, K13, K14, K16 |
| K16 | Conferir o regulamento e preparar o checklist de submissão | P0 | business | Pronto | Nenhuma |
| K17 | Acrescentar voz ou avatar com alternativa funcional | P2 | context | Backlog | K04, K12, K13 |

Critérios completos de aceite: [backlog.json](backlog.json). Fluxo: [workflow.md](workflow.md).

K12 pode iniciar a interface após K01; a integração final também depende de K04, K06 e K07. K14 pode iniciar o desenho da avaliação agora; a comparação completa depende de K04, K06, K11 e K13. Dependência para concluir não impede preparar trabalho independente.

As atribuições individuais serão feitas com as contas confirmadas. Uma pessoa responde por cada tarefa; revisões de IA complementam a revisão humana.
