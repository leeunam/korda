import type { RunEvent } from "@/lib/events";
import { formatTime } from "@/lib/format";

const MARK: Partial<Record<RunEvent["type"], string>> = {
  test_failed: "bg-status-failed",
  test_passed: "bg-status-done",
  approval_requested: "bg-status-waiting",
  approval_granted: "bg-status-done",
  run_completed: "bg-status-done",
  write_blocked: "bg-ink-900",
};

export function EventLog({ events, showStep = false }: { events: RunEvent[]; showStep?: boolean }) {
  if (events.length === 0) return <p className="text-[12px] text-ink-500">Nenhum evento ainda.</p>;
  return (
    <ol className="space-y-2">
      {[...events].reverse().map((e, i) => (
        <li key={`${e.ts}-${e.type}-${i}`} className="grid grid-cols-[auto_1fr] gap-x-2 text-[12px]">
          <span className="font-mono text-ink-500">{formatTime(e.ts)}</span>
          <span className="flex items-center gap-1.5 font-mono font-semibold text-ink-900">
            <span className={`h-1.5 w-1.5 rounded-full ${MARK[e.type] ?? "bg-ink-100"}`} aria-hidden />
            {e.type}
            {showStep ? <span className="font-normal text-ink-500">· {e.step}</span> : null}
            {e.attempt ? <span className="font-normal text-ink-500">· tent. {e.attempt}</span> : null}
          </span>
          <span />
          <span className="text-ink-900">{e.message}</span>
        </li>
      ))}
    </ol>
  );
}
