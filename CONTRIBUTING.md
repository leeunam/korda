# Como trabalhar na Korda

O responsável humano escolhe o resultado; a IA ajuda a produzir e verificar; outro integrante revisa a mudança.

## Antes de começar

1. Escolha uma issue e confirme objetivo, limites, dependências e critérios de aceite.
2. Assuma a issue. Defina o revisor antes de iniciar; autoria e revisão humana devem ser independentes.
3. Abra uma branch curta, como `feat/12-plano-aprovado`. Use um worktree separado quando houver agentes em paralelo.
4. Leia [AGENTS.md](AGENTS.md), o [escopo](docs/scope.md) e os contratos que a mudança afeta.

O quadro segue o [fluxo de trabalho](docs/workflow.md). Mantenha uma tarefa em execução por pessoa, até quatro no time. Um agente auxiliar pode investigar ou implementar uma parte isolada da mesma tarefa; isso não cria um novo dono nem remove a revisão.

## Durante a tarefa

- Um responsável coordena todos os agentes da issue. Evite dois agentes editando o mesmo arquivo.
- Declare os caminhos que cada agente pode alterar. Mudanças em contratos compartilhados devem ser combinadas antes de continuar.
- Prefira uma entrega pequena que possa ser demonstrada. Abra outra issue para expansão de escopo.
- Registre decisão, evidência e bloqueio na issue. Uma resposta de IA não confirma uma regra de negócio.
- Use somente dados sintéticos na demo e exemplos públicos autorizados. Nunca coloque credenciais em prompts, commits ou issues.
- Crie commits descritivos. Se reutilizar código aberto permitido pelo regulamento, indique origem e licença no commit.

## Pull request

Abra um PR ligado à issue (`Closes #N`) usando o template. Informe o resultado, caminhos alterados, como verificar e limitações. Quando usar IA, diga quais partes ela produziu e quais verificações o responsável fez; não publique transcrições com informações privadas.

O revisor confere o comportamento e as evidências, não apenas a aparência do código. A IA pode ajudar na revisão, mas a aprovação é humana. Ajuste testes quando uma mudança de requisito for aprovada; não remova uma verificação para esconder uma falha.

## Pronto significa

- Critérios de aceite demonstrados e dependências resolvidas.
- Verificações relevantes passaram; resultados e comandos estão no PR.
- Documentação e contratos refletem a mudança, sem alegações de funcionalidades inexistentes.
- Nenhum dado sensível ou segredo incluído.
- Revisão humana concluída e PR integrado em `main`.

Até existirem testes do produto, `python3 scripts/check_repo.py` valida apenas a estrutura e links locais. A configuração de CI está no repositório; proteção de branch, aprovação obrigatória e automações do quadro dependem de configuração no GitHub e precisam ser verificadas separadamente.
