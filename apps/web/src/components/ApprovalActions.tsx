import type { RunView } from "@/lib/derive";
import type { ApprovalStep, Mode } from "@/lib/player";
import { StateBadge } from "./nodes/StateBadge";

const primary =
  "h-7 shrink-0 cursor-pointer rounded-[7px] bg-ink px-2.5 text-[12px] font-semibold text-on-ink shadow-btn transition-opacity duration-100 hover:opacity-85 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

/** Por que o botão não aparece. `null` quando a decisão cabe ao usuário agora. */
function reasonFor(step: ApprovalStep, view: RunView, mode: Mode): string | null {
  const gate = view.gates[step];
  if (gate === "approved") return null;
  if (mode === "replay") return "Recorded run, no action.";
  if (step === "approval_1") {
    return gate === "waiting" ? null : "Plan not submitted yet.";
  }
  if (!view.allTestsPassed) {
    const passed = view.tests.filter((t) => t.passed).length;
    return `Needs all tests passing (${passed}/3).`;
  }
  return view.canPromote ? null : "Promotion not requested yet.";
}

export function ApprovalActions({
  view,
  mode,
  onGrant,
  only,
}: {
  view: RunView;
  mode: Mode;
  onGrant: (step: ApprovalStep) => void;
  only?: ApprovalStep;
}) {
  const items: { step: ApprovalStep; n: number; label: string; title: string }[] = [
    { step: "approval_1", n: 1, label: "Approve", title: "Plan v1" },
    { step: "approval_2", n: 2, label: "Promote", title: "Delivery promotion" },
  ];
  return (
    <ol className="divide-y divide-rule">
      {items
        .filter((i) => !only || i.step === only)
        .map(({ step, n, label, title }) => {
          const gate = view.gates[step];
          const reason = reasonFor(step, view, mode);
          const enabled =
            mode === "simulation" &&
            (step === "approval_1" ? gate === "waiting" : view.canPromote);
          return (
            <li key={step} className="flex min-h-11 items-center justify-between gap-3 py-2 first:pt-0 last:pb-0">
              <div className="min-w-0">
                <p className="truncate text-[12.5px] font-medium text-ink">
                  <span className="mr-1.5 font-mono text-faint">{n}</span>
                  {title}
                </p>
                {reason ? <p className="mt-0.5 text-[11.5px] text-muted">{reason}</p> : null}
              </div>
              {enabled ? (
                <button className={primary} onClick={() => onGrant(step)}>
                  {label}
                </button>
              ) : (
                <StateBadge state="pending" gate={gate} />
              )}
            </li>
          );
        })}
    </ol>
  );
}
