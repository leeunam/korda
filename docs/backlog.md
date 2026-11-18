# Backlog inicial

As **17 issues iniciais estão publicadas** no [repositório Korda](https://github.com/leeunam/korda). Este arquivo preserva o ponto de partida; acompanhe mudanças nas [issues](https://github.com/leeunam/korda/issues) e no [Kanban privado da equipe](https://github.com/users/leeunam/projects/3/views/1). Os IDs K01–K17 correspondem às issues #1–#17.

| ID | Entrega | Prioridade | Frente | Estado inicial | Dependências para iniciar |
| --- | --- | --- | --- | --- | --- |
| [K01 · #1](https://github.com/leeunam/korda/issues/1) | Fechar contratos entre as quatro frentes | P0 | platform | Pronto | Nenhuma |
| [K02 · #2](https://github.com/leeunam/korda/issues/2) | Aprovar as regras dos três indicadores e os casos esperados | P0 | planning | Pronto | Nenhuma |
| [K03 · #3](https://github.com/leeunam/korda/issues/3) | Criar as fontes sintéticas ERP, TMS e CT-e | P0 | execution | Backlog | K01, K02 |
| [K04 · #4](https://github.com/leeunam/korda/issues/4) | Implementar a entrevista e o registro de lacunas | P0 | context | Backlog | K01 |
| [K05 · #5](https://github.com/leeunam/korda/issues/5) | Inspecionar as fontes e relacioná-las às regras | P0 | context | Backlog | K01, K03 |
| [K06 · #6](https://github.com/leeunam/korda/issues/6) | Gerar o plano rastreável de implementação | P0 | planning | Backlog | K01, K02, K04, K05 |
| [K07 · #7](https://github.com/leeunam/korda/issues/7) | Implementar as duas aprovações e os estados do trabalho | P0 | platform | Backlog | K01, K06 |
| [K08 · #8](https://github.com/leeunam/korda/issues/8) | Preparar o ambiente de execução e as ferramentas restritas | P0 | execution | Backlog | K01, K03 |
| [K09 · #9](https://github.com/leeunam/korda/issues/9) | Construir o pipeline dos três indicadores | P0 | execution | Backlog | K02, K03, K06, K07, K08 |
| [K10 · #10](https://github.com/leeunam/korda/issues/10) | Implementar o ciclo de correção com limite e escalonamento | P1 | execution | Backlog | K08, K09, K11 |
| [K11 · #11](https://github.com/leeunam/korda/issues/11) | Validar os resultados com testes independentes e protegidos | P0 | execution | Backlog | K02, K03, K08 |
| [K12 · #12](https://github.com/leeunam/korda/issues/12) | Montar o painel do cliente e a linha do tempo | P0 | web | Backlog | K01 |
| [K13 · #13](https://github.com/leeunam/korda/issues/13) | Entregar resultados, documentação e artefatos após autorização | P0 | platform | Backlog | K07, K09, K11, K12 |
| [K14 · #14](https://github.com/leeunam/korda/issues/14) | Medir esforço humano, custo e qualidade sem confundir metas com resultados | P1 | business | Pronto | Nenhuma |
| [K15 · #15](https://github.com/leeunam/korda/issues/15) | Preparar a demo completa e o roteiro de apresentação | P1 | business | Backlog | K10, K12, K13, K14, K16 |
| [K16 · #16](https://github.com/leeunam/korda/issues/16) | Conferir o regulamento e preparar o checklist de submissão | P0 | business | Pronto | Nenhuma |
| [K17 · #17](https://github.com/leeunam/korda/issues/17) | Acrescentar voz ou avatar com alternativa funcional | P2 | context | Backlog | K04, K12, K13 |

Critérios completos de aceite: [backlog.json](backlog.json). Fluxo: [workflow.md](workflow.md).

K12 pode iniciar a interface após K01; a integração final também depende de K04, K06 e K07. K14 pode iniciar o desenho da avaliação agora; a comparação completa depende de K04, K06, K11 e K13. Dependência para concluir não impede preparar trabalho independente.

Contas identificadas: [Leunam](https://github.com/leeunam), [Marcus](https://github.com/m4rcusml) e [Gabriel](https://github.com/Gabriel-smm). Falta confirmar a conta de José. As atribuições individuais devem ser combinadas na issue; conta identificada não significa tarefa assumida. Uma pessoa responde por cada tarefa; revisões de IA complementam a revisão humana.
