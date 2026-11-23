import { CommandLineIcon, DocumentTextIcon, LockClosedIcon, TruckIcon } from "@heroicons/react/24/outline";
import type { Edge } from "@xyflow/react";
import type { KordaNode } from "@/components/nodes/types";
import type { RunView } from "./derive";
import type { StepId } from "./events";

const POS: Record<StepId, { x: number; y: number }> = {
  plan: { x: 0, y: 40 },
  approval_1: { x: 190, y: 20 },
  run_dbt: { x: 150, y: 210 },
  write_hook: { x: 150, y: 520 },
  agent: { x: 480, y: 60 },
  approval_2: { x: 860, y: 150 },
  deliver: { x: 1080, y: 180 },
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
    { ...common("plan"), type: "pill", data: { state: s.plan, icon: DocumentTextIcon, label: "Plano v1", side: "input" } },
    {
      ...common("approval_1"),
      type: "gate",
      data: { state: s.approval_1, gate: view.gates.approval_1, title: "Aprovação 1", subtitle: "Plano v1" },
    },
    {
      ...common("run_dbt"),
      type: "tool",
      data: {
        state: s.run_dbt,
        icon: CommandLineIcon,
        title: "run_dbt",
        description: "Roda dbt build e os testes de aceite dos indicadores.",
        fields: [
          { label: "Comando", value: "dbt build --select gold+" },
          { label: "Testes de aceite", value: "custo_frete_entrega · otif · ocupacao_veiculos" },
        ],
        footer: `${passed} de 3 testes passando`,
      },
    },
    {
      ...common("write_hook"),
      type: "tool",
      data: {
        state: s.write_hook,
        icon: LockClosedIcon,
        title: "write hook",
        description: "Bloqueia escrita fora dos modelos autorizados.",
        fields: [
          { label: "Permitido", value: "models/**" },
          { label: "Somente leitura", value: "tests/** · sources/**" },
        ],
        footer: `${blocked} ${blocked === 1 ? "escrita bloqueada" : "escritas bloqueadas"}`,
      },
    },
    {
      ...common("agent"),
      type: "agent",
      data: {
        state: s.agent,
        title: "Agente Korda",
        subtitle: "Claude Agent SDK · executor",
        model: "claude-opus-5-5",
        instructions:
          "Construa bronze, prata e ouro conforme o plano aprovado. Altere só modelos autorizados. Até 3 correções por etapa; depois, peça decisão humana.",
        output: "Modelos dbt",
      },
    },
    {
      ...common("approval_2"),
      type: "gate",
      data: { state: s.approval_2, gate: view.gates.approval_2, title: "Aprovação 2", subtitle: "Promoção da entrega" },
    },
    { ...common("deliver"), type: "pill", data: { state: s.deliver, icon: TruckIcon, label: "Entregar", side: "output" } },
  ];
}

export function buildEdges(view: RunView): Edge[] {
  return EDGES.map((e) => {
    const active =
      view.nodes[e.target] === "running" || (TOOLS.has(e.source) && view.nodes[e.source] === "running");
    return {
      id: `${e.source}->${e.target}`,
      ...e,
      animated: active,
      style: { stroke: active ? "#141414" : "#737373", strokeWidth: active ? 2.5 : 1.5 },
    };
  });
}
