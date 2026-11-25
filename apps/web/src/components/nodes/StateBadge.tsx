import type { CSSProperties, ReactNode } from "react";
import { Handle, Position, type HandleProps } from "@xyflow/react";
import type { GateState, NodeState } from "@/lib/derive";
import type { Icon } from "./types";

export const NODE_LABEL: Record<NodeState, string> = {
  pending: "Pending",
  running: "Running",
  done: "Done",
  failed: "Failed",
  waiting_approval: "Waiting for approval",
};

export const GATE_LABEL: Record<GateState, string> = {
  approved: "Approved",
  waiting: "Waiting",
  blocked: "Blocked",
};

/** Pílula tingida por estado, no mesmo estilo das pílulas de tarefa. */
const PILL: Record<NodeState | GateState, string> = {
  pending: "bg-field text-muted",
  running: "bg-ink text-on-ink",
  done: "bg-status-done/12 text-status-done",
  failed: "bg-status-failed/12 text-status-failed",
  waiting_approval: "bg-status-waiting/12 text-status-waiting",
  approved: "bg-status-done/12 text-status-done",
  waiting: "bg-status-waiting/12 text-status-waiting",
  blocked: "bg-field text-faint",
};

/** O estado sempre em texto; a cor da pílula só acompanha. */
export function StateBadge({ state, gate }: { state: NodeState; gate?: GateState }) {
  const key = gate ?? state;
  const label = gate ? GATE_LABEL[gate] : NODE_LABEL[state];
  return (
    <span
      className={`inline-flex h-6 shrink-0 items-center whitespace-nowrap rounded-[7px] px-2 text-[12px] font-medium ${PILL[key]}`}
    >
      {label}
    </span>
  );
}

/** Mistura um tom com a superfície, como no flowchart de referência. */
export const mix = (hue: string, pct: number, base = "var(--color-canvas)") =>
  `color-mix(in srgb, ${hue} ${pct}%, ${base})`;

export function IconTile({ icon: Icon, hue }: { icon: Icon; hue: string }) {
  return (
    <span
      className="flex size-9 shrink-0 items-center justify-center rounded-[8px]"
      style={{ background: mix(hue, 12), color: hue, boxShadow: `0 0 0 1px ${mix(hue, 20)}` }}
    >
      <Icon className="size-[18px]" strokeWidth={1.8} aria-hidden />
    </span>
  );
}

/** Anel do cartão por estado (executando, falhou, aguardando). Os demais usam shadow-card. */
function frameStyle(state: NodeState): CSSProperties {
  const ring = (color: string, w: number) => `0 0 0 ${w}px ${color}, 0 2px 10px rgb(0 0 0 / 0.05)`;
  switch (state) {
    case "running":
      return { boxShadow: ring("var(--color-ink)", 2) };
    case "failed":
      return { boxShadow: ring("var(--color-status-failed)", 1.5) };
    case "waiting_approval":
      return { boxShadow: ring("var(--color-status-waiting)", 1.5) };
    default:
      return {};
  }
}

export function NodeCard({
  state,
  gate,
  selected,
  kind,
  width,
  children,
}: {
  state: NodeState;
  gate?: GateState;
  selected: boolean;
  /** Tipo do nó (Entrada, Agente...). A cor do ícone já o indica; o texto fica para leitores de tela. */
  kind: string;
  width: number;
  children: ReactNode;
}) {
  // Com anel de estado (executando, falhou, aguardando), a seleção não acrescenta um segundo contorno.
  const plain = state === "pending" || state === "done";
  return (
    <div
      aria-roledescription={kind}
      className={`relative rounded-card bg-canvas transition-shadow duration-150 ${
        plain ? "shadow-card hover:shadow-raised" : ""
      } ${selected && plain ? "outline outline-[1.5px] outline-offset-[3px] outline-ink" : ""}`}
      style={{ width, ...frameStyle(state) }}
    >
      {/* Estado em pílula acima do cartão, fora do anel de seleção. */}
      <span className="pointer-events-none absolute bottom-full left-0 mb-2.5 flex">
        <StateBadge state={state} gate={gate} />
      </span>
      {children}
    </div>
  );
}

/** Cabeçalho comum: ícone, título e uma linha de apoio. O estado fica na pílula acima do cartão. */
export function NodeHead({
  icon,
  hue,
  title,
  subtitle,
  mono = false,
}: {
  icon: Icon;
  hue: string;
  title: string;
  subtitle?: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center gap-2.5 p-2.5">
      <IconTile icon={icon} hue={hue} />
      <div className="min-w-0 flex-1">
        <p className={`truncate text-[13px] font-semibold leading-tight text-ink ${mono ? "font-mono" : ""}`}>
          {title}
        </p>
        {subtitle ? <p className="mt-0.5 truncate text-[12px] leading-snug text-muted">{subtitle}</p> : null}
      </div>
    </div>
  );
}

/** Rodapé discreto com uma métrica; o handle de saída fica nele. */
export function NodeFooter({ children }: { children: ReactNode }) {
  return (
    <div className="relative flex items-center border-t border-rule px-3 py-2 text-[12px] text-muted">{children}</div>
  );
}

/**
 * Ponto de conexão afastado do cartão, fora do anel de seleção (offset 3px + 1.5px),
 * para a aresta não encostar na borda. As arestas seguem a posição do handle.
 */
const GAP = -12;
const AWAY: Record<Position, CSSProperties> = {
  [Position.Top]: { top: GAP },
  [Position.Bottom]: { bottom: GAP },
  [Position.Left]: { left: GAP },
  [Position.Right]: { right: GAP },
};

/** `lit`: nó selecionado; o ponto fica na cor de seleção. */
export function NodeHandle({ lit = false, ...props }: HandleProps & { lit?: boolean }) {
  const color = lit ? { borderColor: "var(--color-ink)", background: "var(--color-ink)" } : {};
  return <Handle {...props} style={{ ...AWAY[props.position], ...color, ...props.style }} />;
}
