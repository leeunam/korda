import type { RunView } from "@/lib/derive";
import type { ApprovalStep, Mode } from "@/lib/player";

const primary =
  "h-9 rounded-[6px] bg-ink-900 px-3 text-[13px] font-semibold text-paper hover:bg-ink-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink-900 disabled:bg-ink-100 disabled:text-ink-500";

function reasonFor(step: ApprovalStep, view: RunView, mode: Mode): string | null {
  if (mode === "replay") return "Replay: aprovações gravadas, sem ação.";
  const gate = view.gates[step];
  if (gate === "approved") return "Aprovado.";
  if (step === "approval_1") {
    return gate === "waiting" ? null : "Aguardando o plano ser enviado para aprovação.";
  }
  if (!view.allTestsPassed) {
    const passed = view.tests.filter((t) => t.passed).length;
    return `Aguardando todos os testes passarem (${passed} de 3).`;
  }
  return view.canPromote ? null : "Aguardando o pedido de promoção.";
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
  const items: { step: ApprovalStep; label: string; title: string }[] = [
    { step: "approval_1", label: "Aprovar plano", title: "Aprovação 1 · Plano v1" },
    { step: "approval_2", label: "Promover", title: "Aprovação 2 · Promoção da entrega" },
  ];
  return (
    <div className="space-y-3">
      {items
        .filter((i) => !only || i.step === only)
        .map(({ step, label, title }) => {
          const reason = reasonFor(step, view, mode);
          const enabled =
            mode === "simulation" &&
            (step === "approval_1" ? view.gates.approval_1 === "waiting" : view.canPromote);
          return (
            <div key={step} className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[12px] font-semibold text-ink-900">{title}</p>
                <p className="text-[12px] text-ink-500">{reason ?? "Sua decisão."}</p>
              </div>
              <button className={primary} disabled={!enabled} onClick={() => onGrant(step)}>
                {label}
              </button>
            </div>
          );
        })}
    </div>
  );
}
