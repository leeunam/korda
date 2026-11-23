import { CommandLineIcon, DocumentTextIcon, LockClosedIcon, TruckIcon } from "@heroicons/react/24/outline";
import type { Edge } from "@xyflow/react";
import type { Field, KordaNode } from "@/components/nodes/types";
import type { RunView } from "./derive";
import type { StepId } from "./events";

/**
 * Layout vertical (de cima para baixo), como o flowchart de referência:
 * plano → aprovação 1 → agente → aprovação 2 → entrega, com as ferramentas à esquerda do agente.
 * Coordenadas = canto superior esquerdo de cada nó. Cartões compactos: ~56px de altura,
 * ~89px com rodapé (agente e ferramentas).
 */
const SPINE_X = 360; // centro da coluna principal
const at = (width: number, y: number) => ({ x: SPINE_X - width / 2, y });

const POS: Record<StepId, { x: number; y: number }> = {
  plan: at(260, 0),
  approval_1: at(260, 116),
  agent: at(280, 232),
  run_dbt: { x: -120, y: 170 },
  write_hook: { x: -120, y: 300 },
  approval_2: at(260, 381),
  deliver: at(260, 497),
};

/** Configuração de cada etapa, mostrada no painel de inspeção (não no cartão). */
export const STEP_DETAILS: Partial<Record<StepId, Field[]>> = {
  agent: [
    { label: "Model", value: "claude-opus-5-5" },
    {
      label: "Instructions",
      value:
        "Build bronze, silver and gold per the approved plan. Change only authorized models. Up to 3 fixes per step; then ask for a human decision.",
    },
  ],
  run_dbt: [
    { label: "Command", value: "dbt build --select gold+" },
    { label: "Tests", value: "custo_frete_entrega · otif · ocupacao_veiculos" },
  ],
  write_hook: [
    { label: "Allowed", value: "models/**" },
    { label: "Read-only", value: "tests/** · sources/**" },
  ],
};

const EDGES: { source: StepId; target: StepId; targetHandle?: string; sourceHandle?: string }[] = [
  { source: "plan", target: "approval_1" },
  { source: "approval_1", target: "agent", targetHandle: "plan" },
  { source: "run_dbt", target: "agent", targetHandle: "tools" },
  { source: "write_hook", target: "agent", targetHandle: "tools" },
  { source: "agent", target: "approval_2", sourceHandle: "models" },
  { source: "approval_2", target: "deliver" },
];

/** Ferramentas ligam na entrada "tools" do agente: quando executam, a aresta delas anima. */
const TOOLS = new Set<StepId>(["run_dbt", "write_hook"]);

export function buildNodes(view: RunView, selected: StepId | null): KordaNode[] {
  const s = view.nodes;
  const passed = view.tests.filter((t) => t.passed).length;
  const blocked = view.eventsByStep.write_hook.filter((e) => e.type === "write_blocked").length;
  const common = (id: StepId) => ({ id, position: POS[id], selected: selected === id, draggable: false });

  return [
    {
      ...common("plan"),
      type: "pill",
      data: { state: s.plan, icon: DocumentTextIcon, label: "Ariadne (Planning Agent)", caption: "KPIs, rules and tests", side: "input" },
    },
    {
      ...common("approval_1"),
      type: "gate",
      data: { state: s.approval_1, gate: view.gates.approval_1, title: "Approval 1", subtitle: "Plan v1" },
    },
    {
      ...common("run_dbt"),
      type: "tool",
      data: {
        state: s.run_dbt,
        icon: CommandLineIcon,
        title: "run_dbt",
        description: "dbt build and acceptance tests",
        footer: `${passed} of 3 tests passing`,
      },
    },
    {
      ...common("write_hook"),
      type: "tool",
      data: {
        state: s.write_hook,
        icon: LockClosedIcon,
        title: "write hook",
        description: "Writes only to models/**",
        footer: `${blocked} ${blocked === 1 ? "blocked write" : "blocked writes"}`,
      },
    },
    {
      ...common("agent"),
      type: "agent",
      data: {
        state: s.agent,
        title: "Theseus (Executor Agent)",
        subtitle: "Claude Agent SDK · Executor",
        output: "Output: dbt models",
      },
    },
    {
      ...common("approval_2"),
      type: "gate",
      data: { state: s.approval_2, gate: view.gates.approval_2, title: "Approval 2", subtitle: "Delivery promotion" },
    },
    {
      ...common("deliver"),
      type: "pill",
      data: { state: s.deliver, icon: TruckIcon, label: "Hermes (Delivery Agent)", caption: "Promote to the plan's destination", side: "output" },
    },
  ];
}

export function buildEdges(view: RunView, selected: StepId | null): Edge[] {
  return EDGES.map((e) => {
    const active =
      view.nodes[e.target] === "running" || (TOOLS.has(e.source) && view.nodes[e.source] === "running");
    // Linhas do nó selecionado: tracejado em movimento, na cor do texto (sem azul).
    const lit = selected === e.source || selected === e.target;
    const moving = active || lit;
    const stroke = moving ? "var(--color-ink)" : "var(--color-line-strong)";
    return {
      id: `${e.source}->${e.target}`,
      ...e,
      animated: moving,
      style: { stroke, strokeWidth: moving ? 1.75 : 1.25, transition: "stroke 150ms" },
    };
  });
}
