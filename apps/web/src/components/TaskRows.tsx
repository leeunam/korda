"use client";

import { useState, type ReactNode } from "react";

/*
 * Linhas de tarefa expansíveis, adaptadas do componente "Task Rows" de beautifului.dev
 * (MIT, © 2026 Shane Levine). A versão original roda uma sequência de demonstração com
 * timers; aqui o estado de cada linha vem dos eventos reais da execução.
 */

export type TaskStatus = "pending" | "running" | "waiting" | "done" | "failed";

/** Uma linha de detalhe mostrada quando a tarefa é expandida. */
export type TaskDetail = { key: string; label: string; meta: string };

export type TaskRow = {
  key: string;
  label: string;
  /** Texto curto à direita, ex.: "3 eventos". */
  amount: string;
  status: TaskStatus;
  /** Número exibido no anel enquanto pendente/executando. */
  step: number;
  details: TaskDetail[];
  /** Texto da pílula no lugar do padrão do estado, ex.: "Bloqueado". */
  pill?: string;
};

const PILL: Partial<Record<TaskStatus, { text: string; className: string }>> = {
  done: { text: "Done", className: "bg-status-done/12 text-status-done" },
  failed: { text: "Failed", className: "bg-status-failed/12 text-status-failed" },
  waiting: { text: "Waiting", className: "bg-status-waiting/12 text-status-waiting" },
};

function SpinnerRing({ active, children }: { active?: boolean; children?: ReactNode }) {
  const size = 24;
  const stroke = 2;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  return (
    <span className="relative inline-flex shrink-0 items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className={`absolute inset-0 ${active ? "task-spin" : ""}`} aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--color-rule)" strokeWidth={stroke} />
        {active && (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke="var(--color-faint)"
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${c * 0.28} ${c * 0.72}`}
          />
        )}
      </svg>
      <span className="relative text-[10.5px] font-semibold tabular-nums text-ink">{children}</span>
    </span>
  );
}

function Badge({ tone, children }: { tone: "red" | "green"; children: ReactNode }) {
  return (
    <span
      className={`flex size-5.5 shrink-0 items-center justify-center rounded-full text-white animate-pop-in ${
        tone === "red" ? "bg-status-failed" : "bg-status-done"
      }`}
    >
      {children}
    </span>
  );
}

const XIcon = (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" aria-hidden>
    <path d="M18 6L6 18M6 6l12 12" />
  </svg>
);
const CheckIcon = (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d="M20 6L9 17l-5-5" />
  </svg>
);

function badgeFor(row: TaskRow) {
  switch (row.status) {
    case "done":
      return <Badge tone="green">{CheckIcon}</Badge>;
    case "failed":
      return <Badge tone="red">{XIcon}</Badge>;
    case "running":
      return <SpinnerRing active>{row.step}</SpinnerRing>;
    default:
      return <SpinnerRing>{row.step}</SpinnerRing>;
  }
}

export function TaskRows({ rows, className }: { rows: TaskRow[]; className?: string }) {
  const [manualOpen, setManualOpen] = useState<Record<string, boolean>>({});

  return (
    <div className={`flex w-full flex-col gap-2${className ? ` ${className}` : ""}`}>
      {rows.map((row, i) => {
        // Abre sozinha enquanto executa ou quando falha; a pessoa pode sobrescrever.
        const open = manualOpen[row.key] ?? (row.status === "running" || row.status === "failed");
        const base = PILL[row.status];
        const pill = base && row.pill ? { ...base, text: row.pill } : base;
        const panelId = `task-${row.key}-details`;
        return (
          <div
            key={row.key}
            className="task-row self-stretch overflow-hidden bg-canvas shadow-card transition-[border-radius,background-color] duration-300 hover:bg-hover"
            style={{ borderRadius: open ? 14 : 22, animationDelay: `${i * 80}ms` }}
          >
            <button
              type="button"
              aria-expanded={open}
              aria-controls={panelId}
              onClick={() => setManualOpen((cur) => ({ ...cur, [row.key]: !open }))}
              className="flex h-11 w-full cursor-pointer items-center gap-2.5 rounded-[inherit] px-2.5 text-left focus-visible:outline-2 focus-visible:outline-accent"
            >
              <span className="flex size-6 shrink-0 items-center justify-center">{badgeFor(row)}</span>
              <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-ink">{row.label}</span>
              <span className="whitespace-nowrap text-[12.5px] tabular-nums text-muted">{row.amount}</span>
              {pill ? (
                <span
                  key={row.status}
                  className={`task-fade inline-flex h-5.5 items-center whitespace-nowrap rounded-full px-2 text-[11.5px] font-medium ${pill.className}`}
                >
                  {pill.text}
                </span>
              ) : row.status === "running" ? (
                <span className="sr-only">Running</span>
              ) : (
                <span className="sr-only">Pending</span>
              )}
              <span aria-hidden className="-ml-2 flex size-7 shrink-0 items-center justify-center rounded-full text-faint">
                <svg
                  width="15"
                  height="15"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="transition-transform duration-300"
                  style={{ transform: open ? "rotate(180deg)" : "rotate(0)" }}
                >
                  <path d="M6 9l6 6 6-6" />
                </svg>
              </span>
            </button>

            <div
              id={panelId}
              className="grid transition-[grid-template-rows,opacity] duration-300"
              style={{
                gridTemplateRows: open ? "1fr" : "0fr",
                opacity: open ? 1 : 0,
                transitionTimingFunction: "cubic-bezier(0.23, 1, 0.32, 1)",
              }}
              inert={!open}
            >
              <div className="overflow-hidden">
                <div className="mb-2.5 grid grid-cols-[24px_1fr] gap-x-2.5 px-2.5">
                  <span aria-hidden className="mx-auto h-full w-px bg-rule" />
                  <ol className="flex flex-col gap-1.5">
                    {row.details.map((d, j) => (
                      <li
                        key={d.key}
                        className={`flex items-start justify-between gap-3 ${open ? "task-row" : ""}`}
                        style={open ? { animationDelay: `${120 + j * 60}ms` } : undefined}
                      >
                        <span className="text-[12px] leading-snug text-muted">{d.label}</span>
                        <span className="shrink-0 font-mono text-[11.5px] tabular-nums text-faint">{d.meta}</span>
                      </li>
                    ))}
                  </ol>
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
