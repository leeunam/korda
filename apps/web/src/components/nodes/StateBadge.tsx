import type { GateState, NodeState } from "@/lib/derive";

export const NODE_LABEL: Record<NodeState, string> = {
  pending: "pendente",
  running: "executando",
  done: "concluído",
  failed: "falhou",
  waiting_approval: "aguardando aprovação",
};

export const GATE_LABEL: Record<GateState, string> = {
  approved: "aprovado",
  waiting: "aguardando",
  blocked: "bloqueado",
};

const DOT: Record<NodeState | GateState, string> = {
  pending: "bg-ink-100",
  running: "bg-ink-900",
  done: "bg-status-done",
  failed: "bg-status-failed",
  waiting_approval: "bg-status-waiting",
  approved: "bg-status-done",
  waiting: "bg-status-waiting",
  blocked: "bg-ink-500",
};

export function StateBadge({ state, gate }: { state: NodeState; gate?: GateState }) {
  const key = gate ?? state;
  const label = gate ? GATE_LABEL[gate] : NODE_LABEL[state];
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-900">
      <span className={`h-2 w-2 rounded-full ${DOT[key]}`} aria-hidden />
      {label}
    </span>
  );
}

/** Borda do cartão por estado. A cor nunca vem sozinha: o StateBadge diz o estado em texto. */
export function frameClass(state: NodeState, selected: boolean): string {
  const border: Record<NodeState, string> = {
    pending: "border border-ink-100",
    running: "border-[3px] border-ink-900",
    done: "border border-ink-900",
    failed: "border-2 border-status-failed",
    waiting_approval: "border-2 border-status-waiting",
  };
  const ring = selected ? "outline-2 outline-offset-4 outline-ink-500" : "";
  return `${border[state]} ${ring}`;
}

export function titleClass(state: NodeState): string {
  return state === "pending" ? "text-ink-500" : "text-ink-900";
}

export function RunningCursor({ state }: { state: NodeState }) {
  return state === "running" ? <span className="cursor-blink ml-1.5" aria-hidden /> : null;
}
