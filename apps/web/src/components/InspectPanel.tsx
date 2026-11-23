import { XMarkIcon } from "@heroicons/react/24/outline";
import type { RunView } from "@/lib/derive";
import type { RunEvent, StepId } from "@/lib/events";
import { formatNumber } from "@/lib/format";
import type { ApprovalStep, Mode } from "@/lib/player";
import { ApprovalActions } from "./ApprovalActions";
import { EventLog } from "./EventLog";
import { StateBadge } from "./nodes/StateBadge";

const TITLES: Record<StepId, string> = {
  plan: "Plano v1",
  approval_1: "Aprovação 1",
  agent: "Agente Korda",
  run_dbt: "run_dbt",
  write_hook: "write hook",
  approval_2: "Aprovação 2",
  deliver: "Entregar",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-ink-100 px-4 py-4">
      <h3 className="mb-3 text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-500">{title}</h3>
      {children}
    </section>
  );
}

function TestsTable({ view }: { view: RunView }) {
  if (view.tests.length === 0) return <p className="text-[12px] text-ink-500">Nenhum teste executado ainda.</p>;
  return (
    <div className="space-y-4">
      {view.tests.map((t) => (
        <div key={t.test}>
          <p className="flex items-center justify-between font-mono text-[13px] font-semibold">
            {t.test}
            <StateBadge state={t.passed ? "done" : "failed"} />
          </p>
          <table className="mt-2 w-full text-left text-[12px]">
            <thead className="text-ink-500">
              <tr>
                <th className="py-1 font-normal">Tentativa</th>
                <th className="py-1 text-right font-normal">Obtido</th>
                <th className="py-1 text-right font-normal">Esperado</th>
                <th className="py-1 text-right font-normal">Resultado</th>
              </tr>
            </thead>
            <tbody>
              {t.attempts.map((a) => (
                <tr key={a.attempt} className="border-t border-ink-100">
                  <td className="py-1.5">{a.attempt}</td>
                  <td className="py-1.5 text-right font-mono">{formatNumber(a.actual)}</td>
                  <td className="py-1.5 text-right font-mono">{formatNumber(a.expected)}</td>
                  <td className={`py-1.5 text-right font-semibold ${a.passed ? "" : "text-status-failed"}`}>
                    {a.passed ? "passou" : "falhou"}
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
  if (files.length === 0) return <p className="text-[12px] text-ink-500">{empty}</p>;
  return (
    <ul className="space-y-1">
      {files.map((f, i) => (
        <li key={`${f}-${i}`} className="font-mono text-[12px] text-ink-900">
          {f}
        </li>
      ))}
    </ul>
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
      <div>
        <Section title="Aprovações">
          <ApprovalActions view={view} mode={mode} onGrant={onGrant} />
        </Section>
        <Section title="Inspecionar">
          <p className="text-[12px] text-ink-500">Selecione um nó para inspecionar.</p>
        </Section>
        <Section title={`Todos os eventos (${events.length})`}>
          <EventLog events={events} showStep />
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
          <h2 className="text-[18px] font-bold tracking-[-0.03em]">{TITLES[selected]}</h2>
          <div className="mt-1">
            <StateBadge state={view.nodes[selected]} gate={isGate ? view.gates[selected] : undefined} />
          </div>
        </div>
        <button
          onClick={onClose}
          aria-label="Fechar inspeção"
          className="rounded-[6px] p-1 hover:bg-ink-100 focus-visible:outline-2 focus-visible:outline-ink-900"
        >
          <XMarkIcon className="h-5 w-5" strokeWidth={1.5} />
        </button>
      </div>

      {selected === "run_dbt" ? (
        <Section title="Testes de aceite">
          <TestsTable view={view} />
        </Section>
      ) : null}
      {selected === "write_hook" ? (
        <Section title="Escritas bloqueadas">
          <Files events={own} type="write_blocked" empty="Nenhuma escrita bloqueada." />
        </Section>
      ) : null}
      {selected === "agent" ? (
        <Section title="Arquivos escritos">
          <Files events={own} type="file_written" empty="Nenhum arquivo escrito ainda." />
        </Section>
      ) : null}
      {isGate ? (
        <Section title="Decisão">
          <ApprovalActions view={view} mode={mode} onGrant={onGrant} only={selected} />
        </Section>
      ) : null}

      <Section title={`Eventos (${own.length})`}>
        <EventLog events={own} />
      </Section>
    </div>
  );
}
