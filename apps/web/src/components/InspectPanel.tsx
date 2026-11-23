import { XMarkIcon } from "@heroicons/react/24/outline";
import type { RunView } from "@/lib/derive";
import { STEPS, type RunEvent, type StepId } from "@/lib/events";
import type { NodeState } from "@/lib/derive";
import { formatNumber, formatTime } from "@/lib/format";
import { STEP_DETAILS } from "@/lib/graph";
import type { ApprovalStep, Mode } from "@/lib/player";
import { ApprovalActions } from "./ApprovalActions";
import { StateBadge } from "./nodes/StateBadge";
import { TaskRows, type TaskDetail, type TaskRow, type TaskStatus } from "./TaskRows";

const TITLES: Record<StepId, string> = {
  plan: "Ariadne (Planning Agent)",
  approval_1: "Approval 1",
  agent: "Theseus (Executor Agent)",
  run_dbt: "run_dbt",
  write_hook: "write hook",
  approval_2: "Approval 2",
  deliver: "Hermes (Delivery Agent)",
};

const TASK_STATUS: Record<NodeState, TaskStatus> = {
  pending: "pending",
  running: "running",
  done: "done",
  failed: "failed",
  waiting_approval: "waiting",
};

/** Uma linha por etapa com eventos, na ordem do pipeline; os eventos viram o detalhe. */
function stepRows(view: RunView): TaskRow[] {
  return STEPS.flatMap((step, i) => {
    const own = view.eventsByStep[step];
    if (own.length === 0) return [];
    return [
      {
        key: step,
        label: TITLES[step],
        amount: `${own.length} ${own.length === 1 ? "event" : "events"}`,
        status: TASK_STATUS[view.nodes[step]],
        step: i + 1,
        details: own.map((e, j) => ({
          key: `${e.ts}-${e.type}-${j}`,
          label: e.attempt ? `${e.message} · attempt ${e.attempt}` : e.message,
          meta: formatTime(e.ts),
        })),
      },
    ];
  });
}

/** Estado de um evento isolado; `task_started` só gira se for o último de uma etapa em execução. */
function eventStatus(e: RunEvent, isLast: boolean, node: NodeState): TaskStatus {
  switch (e.type) {
    case "test_failed":
    case "write_blocked":
      return "failed";
    case "approval_requested":
      return node === "waiting_approval" && isLast ? "waiting" : "done";
    case "task_started":
      return node === "running" && isLast ? "running" : "done";
    default:
      return "done";
  }
}

const fmt = (v: unknown) => (typeof v === "number" ? formatNumber(v) : String(v));

/** Uma linha por evento da etapa; o detalhe mostra o tipo, a tentativa e os dados estruturados. */
function eventRows(events: RunEvent[], node: NodeState): TaskRow[] {
  return events.map((e, i) => {
    const details: TaskDetail[] = [{ key: "type", label: "Type", meta: e.type }];
    if (e.attempt) details.push({ key: "attempt", label: "Attempt", meta: String(e.attempt) });
    for (const [k, v] of Object.entries(e.data ?? {})) {
      if (v !== undefined && v !== null) details.push({ key: `data-${k}`, label: k, meta: fmt(v) });
    }
    return {
      key: `${e.ts}-${e.type}-${i}`,
      label: e.message,
      amount: formatTime(e.ts),
      status: eventStatus(e, i === events.length - 1, node),
      step: i + 1,
      details,
      pill: e.type === "write_blocked" ? "Blocked" : undefined,
    };
  });
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-rule px-4 py-4">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h3 className="text-[12px] font-medium text-muted">{title}</h3>
        {hint ? <span className="truncate text-[11.5px] text-faint">{hint}</span> : null}
      </div>
      {children}
    </section>
  );
}

function TestsTable({ view }: { view: RunView }) {
  if (view.tests.length === 0) return <p className="text-[12px] text-muted">No tests run yet.</p>;
  return (
    <div className="space-y-4">
      {view.tests.map((t) => (
        <div key={t.test}>
          <p className="flex items-center justify-between font-mono text-[13px] font-semibold">
            {t.test}
            <StateBadge state={t.passed ? "done" : "failed"} />
          </p>
          <table className="mt-2 w-full text-left text-[12px]">
            <thead className="text-muted">
              <tr>
                <th className="py-1 font-normal">Attempt</th>
                <th className="py-1 text-right font-normal">Actual</th>
                <th className="py-1 text-right font-normal">Expected</th>
                <th className="py-1 text-right font-normal">Result</th>
              </tr>
            </thead>
            <tbody>
              {t.attempts.map((a) => (
                <tr key={a.attempt} className="border-t border-rule">
                  <td className="py-1.5">{a.attempt}</td>
                  <td className="py-1.5 text-right font-mono">{formatNumber(a.actual)}</td>
                  <td className="py-1.5 text-right font-mono">{formatNumber(a.expected)}</td>
                  <td className="py-1.5 text-right font-semibold">
                    <span
                      className={`mr-1.5 inline-block h-1.5 w-1.5 rounded-full align-middle ${a.passed ? "bg-status-done" : "bg-status-failed"}`}
                      aria-hidden
                    />
                    {a.passed ? "Passed" : "Failed"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

function Files({ events, type, empty }: { events: RunEvent[]; type: RunEvent["type"]; empty: string }) {
  const files = events.filter((e) => e.type === type && e.data?.file).map((e) => e.data!.file as string);
  if (files.length === 0) return <p className="text-[12px] text-muted">{empty}</p>;
  return (
    <ul className="space-y-1">
      {files.map((f, i) => (
        <li key={`${f}-${i}`} className="font-mono text-[12px] text-ink">
          {f}
        </li>
      ))}
    </ul>
  );
}

function Details({ step }: { step: StepId }) {
  const fields = STEP_DETAILS[step];
  if (!fields) return null;
  return (
    <Section title="Configuration">
      <dl className="space-y-2.5">
        {fields.map((f) => (
          <div key={f.label}>
            <dt className="text-[12px] text-muted">{f.label}</dt>
            <dd className={`mt-0.5 text-[12.5px] leading-snug text-ink ${f.value.length < 60 ? "font-mono" : ""}`}>
              {f.value}
            </dd>
          </div>
        ))}
      </dl>
    </Section>
  );
}

export function InspectPanel({
  view,
  events,
  selected,
  mode,
  onGrant,
  onClose,
}: {
  view: RunView;
  events: RunEvent[];
  selected: StepId | null;
  mode: Mode;
  onGrant: (step: ApprovalStep) => void;
  onClose: () => void;
}) {
  if (!selected) {
    return (
      <div className="[&>section:first-child]:border-t-0">
        <Section title="Approvals">
          <ApprovalActions view={view} mode={mode} onGrant={onGrant} />
        </Section>
        <Section title={`All events (${events.length})`} hint="Click a node for details">
          {events.length === 0 ? (
            <p className="text-[12px] text-muted">No events yet.</p>
          ) : (
            <TaskRows rows={stepRows(view)} />
          )}
        </Section>
      </div>
    );
  }

  const own = view.eventsByStep[selected];
  const isGate = selected === "approval_1" || selected === "approval_2";
  return (
    <div>
      <div className="flex items-start justify-between gap-3 px-4 py-4">
        <div>
          <h2 className="text-[16px] font-semibold tracking-[-0.02em]">{TITLES[selected]}</h2>
          <div className="mt-1">
            <StateBadge state={view.nodes[selected]} gate={isGate ? view.gates[selected] : undefined} />
          </div>
        </div>
        <button
          onClick={onClose}
          aria-label="Close inspector"
          className="cursor-pointer rounded-[8px] p-1 text-muted hover:bg-hover hover:text-ink focus-visible:outline-2 focus-visible:outline-accent"
        >
          <XMarkIcon className="h-5 w-5" strokeWidth={1.5} />
        </button>
      </div>

      <Details step={selected} />
      {selected === "run_dbt" ? (
        <Section title="Acceptance tests">
          <TestsTable view={view} />
        </Section>
      ) : null}
      {selected === "write_hook" ? (
        <Section title="Blocked writes">
          <Files events={own} type="write_blocked" empty="No blocked writes." />
        </Section>
      ) : null}
      {selected === "agent" ? (
        <Section title="Files written">
          <Files events={own} type="file_written" empty="No files written yet." />
        </Section>
      ) : null}
      {isGate ? (
        <Section title="Decision">
          <ApprovalActions view={view} mode={mode} onGrant={onGrant} only={selected} />
        </Section>
      ) : null}

      <Section title={`Events (${own.length})`}>
        {own.length === 0 ? (
          <p className="text-[12px] text-muted">No events yet.</p>
        ) : (
          <TaskRows rows={eventRows(own, view.nodes[selected])} />
        )}
      </Section>
    </div>
  );
}
