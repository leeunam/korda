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

**Estado atual:** sem backend de eventos. A tela usa uma execução **sintética** gerada pelo seed; o worker Python emitirá os mesmos eventos depois.
