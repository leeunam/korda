import type { RunEvent } from "./events";
import type { EventStore } from "./store";

export type Mode = "simulation" | "replay";
export type Speed = 1 | 4;
export type PlayerStatus = "idle" | "playing" | "paused" | "waiting_human" | "finished";
export type ApprovalStep = "approval_1" | "approval_2";

export interface Player {
  play(): void;
  pause(): void;
  restart(): void;
  setSpeed(speed: Speed): void;
  grantApproval(step: ApprovalStep): void;
  readonly status: PlayerStatus;
  readonly speed: Speed;
  onStatus(listener: (status: PlayerStatus) => void): () => void;
  dispose(): void;
}

/**
 * Reproduz eventos gravados com os intervalos originais (divididos pela velocidade).
 * - replay: emite tudo como foi gravado, inclusive as aprovações e os horários.
 * - simulation: não emite as aprovações gravadas. Para em cada approval_requested
 *   até grantApproval(), que grava um approval_granted novo. Os eventos recebem o horário atual.
 */
export function createPlayer(opts: {
  mode: Mode;
  source: RunEvent[];
  store: EventStore;
  now?: () => Date;
}): Player {
  const { mode, store } = opts;
  const now = opts.now ?? (() => new Date());
  const source = [...opts.source].sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts));

  let index = 0; // próximo evento da fonte
  let prevTs: number | null = null; // ts gravado do último evento consumido
  let speed: Speed = 1;
  let status: PlayerStatus = "idle";
  let pendingApproval: ApprovalStep | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let generation = 0; // invalida timers de execuções anteriores
  const listeners = new Set<(s: PlayerStatus) => void>();

  const setStatus = (s: PlayerStatus) => {
    if (s === status) return;
    status = s;
    listeners.forEach((l) => l(s));
  };

  const clearTimer = () => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  };

  const skipRecordedApprovals = () => {
    if (mode !== "simulation") return;
    while (index < source.length && source[index].type === "approval_granted") {
      prevTs = Date.parse(source[index].ts);
      index += 1;
    }
  };

  const emitNext = () => {
    const event = source[index];
    index += 1;
    prevTs = Date.parse(event.ts);
    store.append(mode === "simulation" ? { ...event, ts: now().toISOString() } : event);

    if (mode === "simulation" && event.type === "approval_requested") {
      pendingApproval = event.step as ApprovalStep;
      setStatus("waiting_human");
      return;
    }
    schedule();
  };

  function schedule() {
    clearTimer();
    skipRecordedApprovals();
    if (index >= source.length) {
      setStatus("finished");
      return;
    }
    const nextTs = Date.parse(source[index].ts);
    const delay = prevTs === null ? 0 : Math.max(0, nextTs - prevTs) / speed;
    const gen = generation;
    timer = setTimeout(() => {
      timer = null;
      if (gen !== generation || status !== "playing") return;
      emitNext();
    }, delay);
  }

  return {
    get status() {
      return status;
    },
    get speed() {
      return speed;
    },
    play() {
      if (status === "playing" || status === "waiting_human" || status === "finished") return;
      setStatus("playing");
      schedule();
    },
    pause() {
      if (status !== "playing") return;
      clearTimer();
      setStatus("paused");
    },
    restart() {
      generation += 1;
      clearTimer();
      index = 0;
      prevTs = null;
      pendingApproval = null;
      store.reset();
      status = "idle";
      setStatus("playing");
      schedule();
    },
    setSpeed(s) {
      speed = s;
      if (status === "playing") schedule();
    },
    grantApproval(step) {
      if (mode !== "simulation" || status !== "waiting_human" || pendingApproval !== step) return;
      pendingApproval = null;
      store.append({
        run_id: source[0]?.run_id ?? "",
        step,
        type: "approval_granted",
        message: "Approved by the consultant",
        attempt: null,
        ts: now().toISOString(),
      });
      setStatus("playing");
      schedule();
    },
    onStatus(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    dispose() {
      generation += 1;
      clearTimer();
      listeners.clear();
      store.reset();
    },
  };
}
