// Espelho TS de packages/contracts/events.schema.json (RASCUNHO, pendente de K01).

export const STEPS = [
  "plan",
  "approval_1",
  "agent",
  "run_dbt",
  "write_hook",
  "approval_2",
  "deliver",
] as const;
export type StepId = (typeof STEPS)[number];

export const EVENT_TYPES = [
  "task_started",
  "file_written",
  "test_passed",
  "test_failed",
  "fix_applied",
  "write_blocked",
  "approval_requested",
  "approval_granted",
  "run_completed",
] as const;
export type EventType = (typeof EVENT_TYPES)[number];

export type RunEvent = {
  run_id: string;
  step: StepId;
  type: EventType;
  /** Texto legível, pt-BR. */
  message: string;
  attempt: number | null;
  /** ISO 8601. */
  ts: string;
  /** Opcional: detalhes estruturados para o painel de inspeção. */
  data?: {
    test?: string;
    kpi?: string;
    actual?: number;
    expected?: number;
    file?: string;
    [key: string]: unknown;
  };
};

export function isStep(value: string): value is StepId {
  return (STEPS as readonly string[]).includes(value);
}
