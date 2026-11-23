import { STEPS, isStep, type RunEvent, type StepId } from "./events";

export type NodeState = "pending" | "running" | "done" | "failed" | "waiting_approval";
export type GateState = "approved" | "waiting" | "blocked";

export type TestAttempt = {
  attempt: number;
  passed: boolean;
  actual?: number;
  expected?: number;
  message: string;
  ts: string;
};
export type TestResult = { test: string; attempts: TestAttempt[]; passed: boolean };

export type RunView = {
  nodes: Record<StepId, NodeState>;
  gates: { approval_1: GateState; approval_2: GateState };
  tests: TestResult[];
  allTestsPassed: boolean;
  canPromote: boolean;
  completed: boolean;
  eventsByStep: Record<StepId, RunEvent[]>;
};

/**
 * Ordem do fluxo principal. Um passo cujo último evento é "em andamento"
 * fecha quando um passo posterior desta lista começa (o trabalho foi entregue adiante).
 * run_dbt e write_hook são ferramentas do agente e ficam fora da lista.
 */
const PIPELINE: StepId[] = ["plan", "approval_1", "agent", "approval_2", "deliver"];
const IN_PROGRESS = new Set<RunEvent["type"]>(["task_started", "fix_applied", "file_written"]);

function sortByTs(events: RunEvent[]): RunEvent[] {
  return events
    .map((e, i) => ({ e, i, t: Date.parse(e.ts) }))
    .sort((a, b) => a.t - b.t || a.i - b.i)
    .map((x) => x.e);
}

function collectTests(events: RunEvent[]): TestResult[] {
  const byName = new Map<string, TestResult>();
  for (const e of events) {
    if (e.type !== "test_passed" && e.type !== "test_failed") continue;
    const name = e.data?.test ?? "teste";
    const entry = byName.get(name) ?? { test: name, attempts: [], passed: false };
    const passed = e.type === "test_passed";
    entry.attempts.push({
      attempt: e.attempt ?? entry.attempts.length + 1,
      passed,
      actual: e.data?.actual,
      expected: e.data?.expected,
      message: e.message,
      ts: e.ts,
    });
    entry.passed = passed;
    byName.set(name, entry);
  }
  return [...byName.values()];
}

function gateState(events: RunEvent[], canApprove: boolean): GateState {
  if (events.some((e) => e.type === "approval_granted")) return "approved";
  if (events.some((e) => e.type === "approval_requested") && canApprove) return "waiting";
  return "blocked";
}

export function deriveState(input: RunEvent[]): RunView {
  const events = sortByTs(input.filter((e) => isStep(e.step)));

  const eventsByStep = Object.fromEntries(STEPS.map((s) => [s, [] as RunEvent[]])) as Record<
    StepId,
    RunEvent[]
  >;
  for (const e of events) eventsByStep[e.step].push(e);

  const tests = collectTests(events);
  const allTestsPassed = tests.length > 0 && tests.every((t) => t.passed);
  const completed = events.some((e) => e.type === "run_completed");

  const gates = {
    approval_1: gateState(eventsByStep.approval_1, true),
    approval_2: gateState(eventsByStep.approval_2, allTestsPassed),
  };

  const laterPipelineStarted = (step: StepId) => {
    const idx = PIPELINE.indexOf(step);
    if (idx < 0) return completed;
    return completed || PIPELINE.slice(idx + 1).some((s) => eventsByStep[s].length > 0);
  };

  const nodes = {} as Record<StepId, NodeState>;
  for (const step of STEPS) {
    const own = eventsByStep[step];
    if (own.length === 0) {
      nodes[step] = "pending";
      continue;
    }
    const last = own[own.length - 1];

    if (step === "approval_1" || step === "approval_2") {
      const g = gates[step];
      nodes[step] = g === "approved" ? "done" : g === "waiting" ? "waiting_approval" : "pending";
      continue;
    }

    if (step === "run_dbt") {
      const ranTests = tests.length > 0;
      if (IN_PROGRESS.has(last.type) && !laterPipelineStarted(step)) nodes[step] = "running";
      else if (ranTests && !allTestsPassed) nodes[step] = "failed";
      else nodes[step] = "done";
      continue;
    }

    if (last.type === "run_completed") nodes[step] = "done";
    else if (IN_PROGRESS.has(last.type) && !laterPipelineStarted(step)) nodes[step] = "running";
    else nodes[step] = "done";
  }

  return {
    nodes,
    gates,
    tests,
    allTestsPassed,
    canPromote: allTestsPassed && gates.approval_2 === "waiting",
    completed,
    eventsByStep,
  };
}
