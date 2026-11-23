# Grafo da execução · desenho da UI (K12)

**Status:** rascunho para aprovação. **Issue:** [K12 · #12](https://github.com/leeunam/korda/issues/12). **Área:** `apps/web/`.

## Intenção

A Korda transforma entrevistas com o cliente em modelos dbt testados. Esta tela mostra uma execução do agente como um grafo de nós no estilo Langflow. O consultor acompanha o que o agente faz, vê por que um teste falhou e dá as duas aprovações do produto. A UI precisa funcionar antes do worker Python existir. Por isso, um script de seed gera uma execução sintética realista, e o worker vai emitir os mesmos eventos depois.

## Objetivos

- Renderizar o grafo da execução com React Flow, usando quatro tipos de nó próprios.
- Derivar o estado de todo nó **somente** dos eventos.
- Painel de inspeção do nó selecionado: eventos, tentativas, valor obtido × esperado.
- Botões de aprovação que acrescentam `approval_granted`. "Promover" desabilitado até todos os testes passarem.
- Replay de uma execução gravada com o tempo original e o rótulo visível `REPLAY · gravado`.
- Seed com uma transportadora fictícia e três indicadores: custo de frete por entrega, OTIF e ocupação dos veículos.

## Não objetivos

- Backend de eventos, persistência, autenticação ou multiusuário.
- Execução real de dbt ou de agente.
- As outras telas de K12: entrevista, lacunas e revisão do plano.

## Antiobjetivos

- Apresentar dados sintéticos ou replay como execução ao vivo (`apps/web/README.md`).
- Estado de nó guardado fora dos eventos (flags locais, `useState` por nó).
- Cor como único sinal de estado.
- A IA conceder aprovações. Só o clique humano gera `approval_granted`.

## Restrições

- Next.js (App Router) + TypeScript + Tailwind + `@xyflow/react`. Deploy no Vercel.
- Korda Design System: preto, branco e quatro cinzas, Inter, ícones Heroicons outline, a barra como único ornamento. Os tamanhos dos tokens são de slide; na tela uso uma escala menor derivada deles.
- Cores de status (novas, entram em `design-system/tokens.json`): `status-done` #3CBB71, `status-waiting` #E0A329, `status-failed` #C74238. Cada estado também tem rótulo em texto.
- Sem dados pessoais reais. Todo dado do seed é identificado como sintético.
- `runs/` está no `.gitignore`: o seed não pode ser gravado em diretório com esse nome.

## Abordagens consideradas

1. **Store em memória no navegador + seed em JSON (escolhida).** Roda igual em local e no Vercel, sem backend, e o replay vem de graça. Contra: recarregar a página perde as aprovações, e o worker ainda não consegue escrever.
2. **API route + memória no servidor + SSE.** Mais próxima do fluxo real. Contra: no Vercel as instâncias serverless não compartilham memória.
3. **Arquivo JSONL local + polling.** Contra: não roda no Vercel.

Convex foi adiado pela equipe porque acrescenta complexidade agora. O armazenamento fica atrás da interface `EventStore`, então trocar de backend depois muda um arquivo.

## Desenho

### Contrato de evento (rascunho, pendente de K01)

```ts
type RunEvent = {
  run_id: string;
  step: StepId;          // nó a que o evento pertence
  type: EventType;
  message: string;       // texto legível, pt-BR
  attempt: number | null;
  ts: string;            // ISO 8601
  data?: Record<string, unknown>; // opcional: { test, kpi, actual, expected, file, ... }
};
type EventType = "task_started" | "file_written" | "test_passed" | "test_failed"
  | "fix_applied" | "write_blocked" | "approval_requested" | "approval_granted" | "run_completed";
```

O campo opcional `data` é decisão minha. Sem ele, o painel teria que extrair "237.50 / 166.67" do texto de `message`. O contrato fica em `packages/contracts/events.schema.json`, marcado como rascunho, com o tipo TS espelhado em `apps/web`.

### Grafo

```
[Plano v1]──▶[Aprovação 1]──▶ plan ┐
                                    [Agente Korda]──▶ Modelos dbt ──▶[Aprovação 2]──▶[Entregar]
[run_dbt]────────────────────▶ tools┘
[write hook]─────────────────▶ tools┘
```

| Nó | Tipo | `step` |
| --- | --- | --- |
| Plano v1 | PillNode (entrada) | `plan` |
| Aprovação 1 | GateNode | `approval_1` |
| Agente Korda | AgentNode: modelo, instruções, handles `tools` e `plan`, saída "Modelos dbt" | `agent` |
| run_dbt | ToolNode | `run_dbt` |
| write hook | ToolNode | `write_hook` |
| Aprovação 2 | GateNode | `approval_2` |
| Entregar | PillNode (saída) | `deliver` |

### Derivação de estado (função pura `deriveState(events)`)

- `pending`: nenhum evento no passo.
- `running`: `task_started` (ou `fix_applied`) sem resultado posterior. Borda grossa, cursor piscando, arestas de entrada animadas.
- `failed`: o último resultado de teste de algum teste do passo é `test_failed`.
- `done`: todos os testes do passo passaram, ou `run_completed`/conclusão do passo.
- `waiting_approval`: `approval_requested` sem `approval_granted`.
- Gates mostram `aprovado` / `aguardando` / `bloqueado`. Aprovação 2 fica `bloqueado` enquanto algum teste não passou. "Promover" só habilita com todos os testes passando **e** `approval_requested` em `approval_2`.
- `write_blocked` aparece no write hook como evento de sucesso do hook (ele bloqueou a escrita), não como falha do nó.

### Modos

- **Simulação · dados sintéticos:** o simulador emite os eventos do seed com o tempo original e para em cada `approval_requested` até o clique humano. É o modo interativo.
- **REPLAY · gravado:** reproduz uma execução completa gravada, com aprovações incluídas e botões desabilitados. Controles: play/pausa, reiniciar e velocidade 1×/2×/4× (a velocidade é decisão minha).

Os dois modos mostram o rótulo do modo e "dados sintéticos" no cabeçalho. Nenhum mostra "ao vivo".

### Seed

`apps/web/scripts/seed.ts` gera `apps/web/src/data/seed-run.json` de forma determinística, cerca de 60–90 s de execução:
aprovação 1 → agente escreve bronze/prata/ouro (`file_written`) → `run_dbt` testa os três indicadores → `custo_frete_entrega` falha (tentativa 1: 237.50, esperado 166.67, por duplicatas de CT-e) → `fix_applied` → o agente tenta editar um teste de aceite → `write_blocked` → tentativa 2 passa → OTIF e ocupação passam → `approval_requested` (aprovação 2) → `approval_granted` → `run_completed`. O limite de três tentativas por etapa é respeitado.

### Layout

```
┌ korda ▌  run_0001 · Transportadora Exemplo   [SIMULAÇÃO · dados sintéticos]  ▶ ⟲ 1× ┐
├───────────────────────────────────────────────┬────────────────────────────────────┤
│                                               │ run_dbt               ● falhou     │
│          canvas React Flow                    │ custo_frete_entrega                │
│                                               │  tent. 1  237.50  esperado 166.67 ✕│
│                                               │  tent. 2  166.67  esperado 166.67 ✓│
│                                               │ ─ eventos ───────────────────────  │
│                                               │ 14:02:11 test_failed …             │
└───────────────────────────────────────────────┴────────────────────────────────────┘
```

Em tela estreita, o painel vira uma folha inferior.

### Testes

Vitest sobre `deriveState` com cenários do domínio: falha seguida de correção, aprovação pendente, `write_blocked` não falha o nó, "Promover" bloqueado com teste falhando. Mais `python3 scripts/check_repo.py`, `next build` e verificação manual no navegador.

## Fica com quem constrói

Posições dos nós, textos das instruções do agente, escala tipográfica de tela e animações exatas.
