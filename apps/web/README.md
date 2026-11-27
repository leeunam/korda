# P4 · Experiência

Interface da Korda: Next.js (App Router) + TypeScript + Tailwind + React Flow. Primeira tela: o grafo de uma execução do agente ([desenho](../../docs/superpowers/specs/2026-11-23-run-graph-ui-design.md)).

Entregas esperadas: abertura do caso, conversa e lacunas, revisão do plano, aprovação 1, progresso com falhas e tentativas, resultados e aprovação 2. Mostrar estados reais do backend e separar conclusão da execução de promoção da entrega.

Começar com estados simulados identificados e contratos compartilhados. Acessibilidade básica, telas pequenas, erros compreensíveis e ausência de dados pessoais reais são critérios da demo. Não apresentar mock ou replay como execução ao vivo.

## Rodar

Requer Node 20+ e pnpm.

```bash
pnpm install
pnpm dev     # http://localhost:3000
pnpm test    # testes (Vitest)
pnpm build   # build de produção, como no Vercel
```

O grafo usa uma execução **sintética** gerada pelo seed. O painel do operador consulta a descoberta e o worker pelo serviço local.

## Painel local do operador

Em `/operador`, abra o projeto pelo identificador usado na descoberta. **Consultar última revisão** mostra a revisão congelada, suas pendências e o SHA-256. Também é possível consultar um número específico. **Importar revisão** vincula o conteúdo conferido ao projeto. Se a entrevista ainda tiver lacunas, o painel mostra as perguntas para a equipe responder na descoberta.

Quando houver um plano, confira a versão, o destino, as regras e suas evidências. Identifique o responsável e decida sobre o plano. **Iniciar execução** inicia o worker da versão aprovada. Ao fim do build, confira os indicadores; outra decisão explícita autoriza a entrega (não há comparação com gabarito no fluxo). **Promover entrega** publica os arquivos no destino do plano e habilita o download. Use **Atualizar projeto** para recuperar o estado persistido após fechar a janela ou após uma falha na conexão.

Inicie primeiro o serviço local do operador. No processo Next configure `KORDA_OPERADOR_TOKEN` com a mesma credencial do serviço. A variável opcional `KORDA_OPERADOR_URL` aponta para a raiz HTTP de loopback, por padrão `http://127.0.0.1:8790`. Essas variáveis pertencem ao servidor. Acesse o painel por `http://127.0.0.1:3000/operador`. O grafo de simulação e replay continua disponível em `/`.
