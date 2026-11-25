# Grafo da execução (K12) · plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tela em `apps/web/` que mostra uma execução da Korda como grafo React Flow, com estados derivados só de eventos, painel de inspeção, aprovações e replay, alimentada por um seed sintético.

**Architecture:** Next.js App Router, página única renderizada no cliente. Um `EventStore` em memória recebe eventos de um `Player` (simulação ou replay) que lê o seed JSON. `deriveState(events)` é uma função pura que produz o estado de cada nó; os componentes só leem esse resultado.

**Tech Stack:** Next.js (latest, App Router) · TypeScript · Tailwind v4 · `@xyflow/react` · `@heroicons/react` · Vitest · pnpm · `tsx` para o seed.

**Spec:** [docs/superpowers/specs/2026-11-23-run-graph-ui-design.md](../specs/2026-11-23-run-graph-ui-design.md)

## Global Constraints

- Cores: só `ink-900 #141414`, `ink-800 #2E2E2E`, `ink-500 #737373`, `ink-100 #E5E5E5`, `paper #FFFFFF`, mais status `status-done #3CBB71`, `status-waiting #E0A329`, `status-failed #C74238`. Sem gradientes nem sombras.
- Fonte Inter (400/600/700) via `next/font/google`. Ícones Heroicons outline 24, stroke 1.5.
- Todo estado tem rótulo em texto pt-BR: `pendente`, `executando`, `concluído`, `falhou`, `aguardando aprovação`; gates: `aprovado`, `aguardando`, `bloqueado`.
- Rótulos de modo exatos: `SIMULAÇÃO · dados sintéticos` e `REPLAY · gravado`. A palavra "ao vivo" não aparece em lugar nenhum.
- Estado de nó nunca é guardado fora de `deriveState(events)`.
- Nenhum arquivo em diretório chamado `runs/` (gitignored).
- Copy da UI em pt-BR.

## Review Focus

- Clicar em aprovar duas vezes rápido → um único `approval_granted` (teste no Task 4).
- Reiniciar ou trocar de modo no meio da execução → timers antigos não emitem eventos no store novo (teste no Task 4).
- Eventos fora de ordem de `ts` (worker real) → `deriveState` ordena por `ts` antes de derivar (teste no Task 2).
- Evento com `step` desconhecido → ignorado sem quebrar (teste no Task 2).
- Aba em segundo plano durante replay → ao voltar, eventos atrasados são emitidos em ordem, sem pular (o Player agenda pelo delta de `ts`, encadeado; coberto pelo teste de ordem no Task 4).

---

### Task 1: Esqueleto do app, tokens de status e tema

**Files:**
- Modify: `design-system/tokens.json` (adicionar `status-done`, `status-waiting`, `status-failed` em `color.tokens`, com `usage`)
- Modify: `design-system/README.md` (seção Color: uma linha sobre as cores de status, sempre com rótulo em texto)
- Create: `apps/web/` via `pnpm create next-app@latest apps/web --ts --tailwind --app --src-dir --eslint --use-pnpm --no-import-alias` (depois, alias `@/*` → `src/*` à mão)
- Modify: `apps/web/src/app/globals.css` (tokens como variáveis CSS + `@theme` do Tailwind: `--color-ink-900` … `--color-status-failed`, `--font-sans`; keyframes `blink` e classe `.cursor-blink`)
- Modify: `apps/web/src/app/layout.tsx` (Inter, `lang="pt-BR"`, título "Korda · execução")
- Modify: `apps/web/README.md` (como rodar: `pnpm i`, `pnpm dev`, `pnpm seed`, `pnpm test`)
- Copy: `design-system/logos/korda-wordmark-black.svg` e `korda-bar-black.svg` → `apps/web/public/`

- [ ] Instalar deps: `@xyflow/react @heroicons/react`; dev: `vitest tsx`. Scripts: `"test": "vitest run"`, `"seed": "tsx scripts/seed.ts"`.
- [ ] Página provisória com o wordmark e um quadrado de cada token de cor.
- [ ] Verificar: `pnpm build` passa; `pnpm dev` mostra a página; `python3 scripts/check_repo.py` passa.
- [ ] Mostrar ao usuário e commitar com a autorização dele.

### Task 2: Contrato de evento e `deriveState`

**Files:**
- Create: `packages/contracts/events.schema.json` (JSON Schema draft 2020-12, `"$comment": "RASCUNHO pendente de K01"`, campos do spec, `data` opcional)
- Modify: `packages/contracts/README.md` (link para o schema, status rascunho)
- Create: `apps/web/src/lib/events.ts`
- Create: `apps/web/src/lib/derive.ts`
- Test: `apps/web/src/lib/derive.test.ts`

**Interfaces — Produces:**
```ts
// events.ts
export const STEPS = ["plan","approval_1","agent","run_dbt","write_hook","approval_2","deliver"] as const;
export type StepId = typeof STEPS[number];
export type EventType = "task_started"|"file_written"|"test_passed"|"test_failed"|"fix_applied"|"write_blocked"|"approval_requested"|"approval_granted"|"run_completed";
export type RunEvent = { run_id: string; step: StepId; type: EventType; message: string; attempt: number|null; ts: string; data?: { test?: string; kpi?: string; actual?: number; expected?: number; file?: string; [k: string]: unknown } };

// derive.ts
export type NodeState = "pending"|"running"|"done"|"failed"|"waiting_approval";
export type GateState = "approved"|"waiting"|"blocked";
export type TestResult = { test: string; attempts: { attempt: number; passed: boolean; actual?: number; expected?: number; ts: string }[]; passed: boolean };
export type RunView = {
  nodes: Record<StepId, NodeState>;
  gates: { approval_1: GateState; approval_2: GateState };
  tests: TestResult[];          // por nome de teste, última tentativa decide `passed`
  allTestsPassed: boolean;      // tests.length > 0 && todos passed
  canPromote: boolean;          // allTestsPassed && approval_2 aguardando (requested, não granted)
  completed: boolean;           // houve run_completed
  eventsByStep: Record<StepId, RunEvent[]>;
};
export function deriveState(events: RunEvent[]): RunView;
```

Regras (do spec): `pending` sem eventos; `waiting_approval` se `approval_requested` sem `approval_granted`; `failed` se algum teste do passo tem último resultado `test_failed` e não houve `fix_applied`/`task_started` depois; `running` se o último evento do passo é `task_started`/`fix_applied`/`file_written` e não há conclusão; `done` caso contrário, quando há eventos. `write_blocked` nunca leva a `failed`. Gate `blocked` = não pode ser aprovado ainda (approval_2 com teste não aprovado ou sem `approval_requested`); `waiting` = requested; `approved` = granted. Ordenar por `ts` (estável) antes de derivar; ignorar `step` fora de `STEPS`.

- [ ] Escrever `derive.test.ts` com estes casos (eventos montados por um helper `ev(step, type, extra?)` com `ts` crescente):
  - lista vazia → todos `pending`, gates `blocked`, `canPromote === false`.
  - `test_failed` de `custo_frete_entrega` (attempt 1, actual 237.5, expected 166.67) → `nodes.run_dbt === "failed"`, `tests[0].attempts[0]` com esses valores, `allTestsPassed === false`.
  - o anterior + `fix_applied` + `test_passed` (attempt 2) → `run_dbt` `done`, `tests[0].passed === true`, duas tentativas.
  - `write_blocked` em `write_hook` → `nodes.write_hook !== "failed"`.
  - `approval_requested` em `approval_2` com um teste falhando → `gates.approval_2 === "blocked"`, `canPromote === false`; com todos passando → `"waiting"`, `canPromote === true`; após `approval_granted` → `"approved"`, `canPromote === false`.
  - eventos embaralhados por `ts` produzem o mesmo `RunView` que ordenados.
  - evento com `step: "foo"` é ignorado sem exceção.
- [ ] `pnpm test` → falha (módulo inexistente).
- [ ] Implementar `events.ts` e `derive.ts`.
- [ ] `pnpm test` → passa. Commit com autorização.

### Task 3: Seed sintético

**Files:**
- Create: `apps/web/scripts/seed.ts`
- Create (gerado e versionado): `apps/web/src/data/seed-run.json`
- Test: `apps/web/src/data/seed-run.test.ts`

**Interfaces — Consumes:** `RunEvent`, `deriveState`. **Produces:** `seed-run.json` = `{ run_id: "run_demo_0001", synthetic: true, client: "Transportadora Exemplo (fictícia)", events: RunEvent[] }`.

Roteiro (determinístico, `ts` a partir de `2026-11-20T14:00:00-03:00`, ~75 s no total, intervalos de 0,5–6 s): `plan` task_started/file_written(plano v1) → `approval_1` approval_requested → approval_granted (+8 s) → `agent` task_started → file_written de `models/bronze/*`, `models/silver/*`, `models/gold/custo_frete_entrega.sql`, `otif.sql`, `ocupacao_veiculos.sql` → `run_dbt` task_started → `test_failed` custo_frete_entrega (attempt 1, actual 237.50, expected 166.67, mensagem cita CT-e duplicado) → `agent` fix_applied (attempt 2, dedup por chave do CT-e) → `write_hook` write_blocked (`tests/acceptance/custo_frete_entrega.yml`, "somente leitura para o executor") → `run_dbt` test_passed custo_frete_entrega attempt 2 (166.67) → test_passed otif (attempt 1, ex.: 0.873) → test_passed ocupacao_veiculos (attempt 1, ex.: 0.712) → `approval_2` approval_requested → approval_granted (+10 s) → `deliver` task_started → run_completed. Todas as mensagens em pt-BR.

- [ ] Teste: o JSON tem `synthetic: true`; `ts` estritamente crescente; nenhuma `attempt` > 3; último evento é `run_completed`; `deriveState(events)` → `allTestsPassed`, `completed`, todos os nós `done`, gates `approved`; existe exatamente um `write_blocked`.
- [ ] Teste: rodar `seed.ts` duas vezes gera JSON idêntico (importar a função `buildSeedRun(): SeedRun` exportada pelo script e comparar com o arquivo).
- [ ] Implementar `buildSeedRun` e o `main` que grava o arquivo. `pnpm seed && pnpm test` → passa. Commit com autorização.

### Task 4: `EventStore` e `Player`

**Files:**
- Create: `apps/web/src/lib/store.ts`
- Create: `apps/web/src/lib/player.ts`
- Test: `apps/web/src/lib/player.test.ts`

**Interfaces — Produces:**
```ts
// store.ts — a interface que um backend real implementa depois
export interface EventStore { list(): RunEvent[]; append(e: RunEvent): void; subscribe(fn: (events: RunEvent[]) => void): () => void; reset(): void; }
export function createMemoryStore(): EventStore;
export function useRunEvents(store: EventStore): RunEvent[]; // useSyncExternalStore

// player.ts
export type Mode = "simulation" | "replay";
export type Speed = 1 | 2 | 4;
export interface Player { play(): void; pause(): void; restart(): void; setSpeed(s: Speed): void; grantApproval(step: "approval_1"|"approval_2"): void; readonly status: "idle"|"playing"|"paused"|"waiting_human"|"finished"; onStatus(fn: (s: Player["status"]) => void): () => void; dispose(): void; }
export function createPlayer(opts: { mode: Mode; source: RunEvent[]; store: EventStore; now?: () => Date }): Player;
```

Comportamento: emite eventos em ordem, cada um após `(ts[i] - ts[i-1]) / speed`, com um único `setTimeout` encadeado. Em `simulation`, os `approval_granted` do seed **não** são emitidos: ao emitir `approval_requested`, o status vira `waiting_human`; `grantApproval(step)` faz `append` de um `approval_granted` (`message: "Aprovado pelo consultor"`, `ts` = agora) e retoma. Em `replay`, emite tudo e `grantApproval` não faz nada. `restart`/`dispose` cancelam o timer pendente e limpam o store.

- [ ] Testes com `vi.useFakeTimers()` e um seed curto de 4 eventos:
  - replay emite na ordem e respeita os deltas (avançar 999 ms não emite o segundo evento de um delta de 1000 ms; 1000 ms emite).
  - `setSpeed(4)` → delta de 1000 ms emite em 250 ms.
  - simulação para em `approval_requested` (`status === "waiting_human"`, avançar 60 s não emite mais nada); `grantApproval` acrescenta um `approval_granted` e continua.
  - `grantApproval` chamado duas vezes → exatamente um `approval_granted` no store.
  - `restart()` no meio → store vazio e nenhum evento do timer antigo chega depois.
  - replay: `grantApproval` não altera o store.
- [ ] `pnpm test` → falha; implementar; `pnpm test` → passa. Commit com autorização.

### Task 5: Nós customizados e o grafo

**Files:**
- Create: `apps/web/src/components/nodes/ToolNode.tsx`, `AgentNode.tsx`, `GateNode.tsx`, `PillNode.tsx`, `StateBadge.tsx`
- Create: `apps/web/src/components/RunGraph.tsx`
- Create: `apps/web/src/lib/graph.ts` (nós e arestas fixos)

**Interfaces — Consumes:** `RunView`, `StepId`. **Produces:** `<RunGraph view={RunView} selected={StepId|null} onSelect={(s: StepId) => void} />`; `graph.ts` exporta `baseNodes: Node[]`, `baseEdges: Edge[]` com `id === StepId`.

Visual (do spec): ToolNode = ícone + título no cabeçalho, descrição, campos chave/valor, rodapé `ink-900` com texto branco e handle de saída. AgentNode = título "Agente Korda", campo modelo `claude-opus-5-5`, instruções (2–3 linhas), handles de entrada `tools` e `plan` rotulados, saída "Modelos dbt". GateNode = "Aprovação 1/2" + `StateBadge`. PillNode = pílula arredondada (`radius-pill`), "Plano v1" com saída, "Entregar" com entrada. Estados: borda 1px `ink-100` (pending, texto `ink-500`), 3px `ink-900` + cursor piscando ao lado do título (running), barra lateral/badge `status-done`, `status-failed`, `status-waiting`. Arestas cujo alvo está `running` ficam `animated`. `StateBadge` = ponto de cor + rótulo em texto.

- [ ] Página provisória renderiza `RunGraph` com `deriveState(seed.events.slice(0, n))` para um `n` escolhido por `?n=` na URL. Verificar no navegador: n=0 tudo pendente; n no meio do `test_failed` → run_dbt falhou; n=total → tudo concluído.
- [ ] `pnpm build` passa. Mostrar ao usuário. Commit com autorização.

### Task 6: Página completa — cabeçalho, controles, inspeção, aprovações

**Files:**
- Create: `apps/web/src/components/RunHeader.tsx`, `InspectPanel.tsx`, `ApprovalActions.tsx`, `EventLog.tsx`
- Modify: `apps/web/src/app/page.tsx`

**Interfaces — Consumes:** `createMemoryStore`, `useRunEvents`, `createPlayer`, `deriveState`, `RunGraph`.

- Cabeçalho: barra Korda + `run_id` + cliente fictício + rótulo do modo (`SIMULAÇÃO · dados sintéticos` / `REPLAY · gravado`) em caixa com borda `ink-900`, uppercase, sempre visível; seletor de modo; play/pausa, reiniciar, 1×/2×/4×.
- InspectPanel do nó selecionado: nome, `StateBadge`; para `run_dbt`, tabela por teste com `tentativa · obtido · esperado · ✓/✕` (ex.: `tentativa 1 · 237,50 · esperado 166,67 · falhou`); para `write_hook`, arquivos bloqueados; para gates, botão de aprovação; lista de eventos do passo (hora, tipo, mensagem). Sem seleção: texto "Selecione um nó para inspecionar".
- ApprovalActions: "Aprovar plano" (approval_1) e "Promover" (approval_2) chamam `player.grantApproval`. "Promover" `disabled` quando `!view.canPromote`, com motivo em texto ("Aguardando todos os testes passarem"). Em replay, ambos desabilitados com "Replay: aprovações gravadas".
- Trocar de modo faz `dispose` no player antigo e cria outro.
- [ ] Verificar no navegador (simulação): para na Aprovação 1; aprovar continua; run_dbt fica vermelho com o painel mostrando 237,50 × 166,67; "Promover" desabilitado até os três testes passarem; aprovar conclui.
- [ ] Verificar (replay): rótulo `REPLAY · gravado` visível, roda até o fim sem intervenção, botões desabilitados.
- [ ] `pnpm test && pnpm build` passam. Mostrar ao usuário. Commit com autorização.

### Task 7: Tela estreita e acabamento

**Files:** Modify `page.tsx`, `InspectPanel.tsx`, `globals.css`.

- [ ] Abaixo de 768 px, o painel vira folha inferior (máx. 50vh, rolável); o canvas usa `fitView`. Sem rolagem horizontal da página.
- [ ] Foco visível nos botões; `aria-label` nos controles só com ícone; `prefers-reduced-motion` desliga o cursor piscando e as arestas animadas.
- [ ] Verificar no navegador em 390 px e 1440 px. `pnpm build`, `pnpm test`, `python3 scripts/check_repo.py` passam. Mostrar ao usuário. Commit com autorização.
