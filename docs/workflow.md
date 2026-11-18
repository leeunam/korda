# Como a equipe Undefined trabalha

Uma issue descreve uma entrega verificável. Uma pessoa responde por ela; a IA ajuda a executar e revisar, sem assumir decisões humanas.

[Repositório público](https://github.com/leeunam/korda) · [Issues](https://github.com/leeunam/korda/issues) · [Kanban da equipe](https://github.com/users/leeunam/projects/3/views/1)

O Kanban é privado para a equipe. As issues e seus critérios de aceite são públicos; registre somente informações apropriadas para esse público. O quadro é a referência do estado atual; [backlog.md](backlog.md) preserva a ordem e as dependências iniciais.

## Kanban

| Coluna | Regra |
| --- | --- |
| Backlog | Trabalho ainda sem prioridade imediata ou com dependências abertas. |
| Pronto | Escopo, entradas, saídas e aceite definidos; dependências concluídas. |
| Em andamento | Responsável assumiu a tarefa e abriu uma branch/worktree própria. |
| Em revisão | PR ligado à issue, com evidência suficiente para revisão humana. |
| Concluído | Aceite verificado por uma pessoa e mudança integrada. |

Use prioridade `priority:p0` para o essencial da entrega, `priority:p1` para o que fortalece a prova e `priority:p2` para extensões. As etiquetas `area:*` indicam a frente; `type:task` identifica as tarefas iniciais. Não confunda prioridade P1 com a frente de Contexto.

Uma dependência necessária para iniciar mantém a tarefa no Backlog. Dependências somente de integração ou conclusão devem estar identificadas separadamente: permitem trabalho independente, mas impedem concluir antes da integração. Se uma tarefa já iniciada bloquear, registre motivo, dependência e próximo passo; marque-a com `status:blocked`. Resolvido o motivo, retire a etiqueta. Não esconda trabalho parado nem crie vários cartões para a mesma entrega.

## Limites de trabalho

- Uma tarefa principal em andamento por pessoa: até quatro simultâneas no time.
- No máximo dois PRs aguardando revisão; revisar antes de iniciar trabalho novo.
- Preferir tarefas de até um dia. Se a issue for maior, dividi-la em entregas menores antes de iniciar, preservando dependências e aceite.
- Começar pelas issues independentes de contratos, definições de métricas, desenho da medição e regulamento. Não marcar tarefas dependentes como prontas só para preencher o quadro.

O ponto de partida tem quatro tarefas em **Pronto**: [#1 · contratos](https://github.com/leeunam/korda/issues/1), [#2 · regras dos indicadores](https://github.com/leeunam/korda/issues/2), [#14 · desenho da medição](https://github.com/leeunam/korda/issues/14) e [#16 · regulamento](https://github.com/leeunam/korda/issues/16). As outras 13 começam no Backlog. Mova os cartões conforme as condições forem atendidas.

## Fluxo com IA

1. **Assumir:** escolher uma issue pronta, registrar responsável e ler `AGENTS.md`, escopo e contratos afetados.
2. **Delimitar:** informar à IA o objetivo, arquivos permitidos, entradas, saídas, dependências e critérios de aceite. Propor mudança de contrato na issue antes de alterar consumidores.
3. **Executar:** trabalhar em branch/worktree própria. Agentes simultâneos devem ter arquivos de responsabilidade separados; cada pessoa mantém uma entrega principal.
4. **Verificar:** conferir o comportamento com evidência proporcional à mudança. Não inventar testes, resultados, métricas ou conclusão. Código e critérios de aceite não podem ser afrouxados só para passar.
5. **Revisar:** abrir PR pequeno com a issue, motivo da mudança, verificação e limitações. Uma pessoa revisa antes de integrar; a revisão de outra IA é complementar.
6. **Concluir:** integrar a mudança aceita, atualizar a issue e fechar o cartão. Mudanças de escopo voltam à decisão humana.

## Pronto para revisar

- [ ] PR resolve o escopo da issue e aponta a ela.
- [ ] Mudanças e evidências de funcionamento estão descritas.
- [ ] Contratos e documentação afetados estão atualizados.
- [ ] Não há segredos, dados reais nem afirmações de capacidades ainda ausentes.
- [ ] Limitações e decisões pendentes estão explícitas.

A revisão do desenvolvimento não substitui as duas aprovações do produto: uma pessoa aprova o plano antes da execução e outra decisão autoriza a entrega após os testes. A IA não concede essas aprovações em nome do usuário.
