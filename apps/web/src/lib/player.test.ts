import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { deriveState } from "./derive";
import type { RunEvent } from "./events";
import { createPlayer } from "./player";
import { createMemoryStore } from "./store";

const T0 = Date.parse("2026-11-20T14:00:00-03:00");
function ev(sec: number, step: RunEvent["step"], type: RunEvent["type"]): RunEvent {
  return { run_id: "r", step, type, message: type, attempt: null, ts: new Date(T0 + sec * 1000).toISOString() };
}

// Fonte curta: a aprovação gravada aos 3 s; o agente começa 1 s depois.
const source: RunEvent[] = [
  ev(0, "plan", "task_started"),
  ev(1, "plan", "file_written"),
  ev(2, "approval_1", "approval_requested"),
  ev(3, "approval_1", "approval_granted"),
  ev(4, "agent", "task_started"),
];

beforeEach(() => vi.useFakeTimers({ now: new Date("2026-11-23T15:00:00Z") }));
afterEach(() => vi.useRealTimers());

describe("Player · replay", () => {
  it("emite na ordem e respeita os intervalos originais", () => {
    const store = createMemoryStore();
    const p = createPlayer({ mode: "replay", source, store });
    p.play();
    vi.advanceTimersByTime(0);
    expect(store.list()).toHaveLength(1);
    vi.advanceTimersByTime(999);
    expect(store.list()).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(store.list()).toHaveLength(2);
    vi.advanceTimersByTime(10_000);
    expect(store.list().map((e) => e.type)).toEqual(source.map((e) => e.type));
    expect(store.list().map((e) => e.ts)).toEqual(source.map((e) => e.ts));
    expect(p.status).toBe("finished");
  });

  it("velocidade 4× divide os intervalos", () => {
    const store = createMemoryStore();
    const p = createPlayer({ mode: "replay", source, store });
    p.setSpeed(4);
    p.play();
    vi.advanceTimersByTime(0);
    vi.advanceTimersByTime(249);
    expect(store.list()).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(store.list()).toHaveLength(2);
  });

  it("grantApproval não altera o store", () => {
    const store = createMemoryStore();
    const p = createPlayer({ mode: "replay", source, store });
    p.play();
    vi.advanceTimersByTime(2000);
    p.grantApproval("approval_1");
    expect(store.list().filter((e) => e.type === "approval_granted")).toHaveLength(0);
  });

  it("pausa interrompe a emissão até play", () => {
    const store = createMemoryStore();
    const p = createPlayer({ mode: "replay", source, store });
    p.play();
    vi.advanceTimersByTime(0);
    p.pause();
    vi.advanceTimersByTime(10_000);
    expect(store.list()).toHaveLength(1);
    expect(p.status).toBe("paused");
    p.play();
    vi.advanceTimersByTime(10_000);
    expect(store.list()).toHaveLength(source.length);
  });
});

describe("Player · simulação", () => {
  it("para na aprovação até o clique humano e depois continua", () => {
    const store = createMemoryStore();
    const p = createPlayer({ mode: "simulation", source, store });
    p.play();
    vi.advanceTimersByTime(2000);
    expect(store.list().at(-1)?.type).toBe("approval_requested");
    expect(p.status).toBe("waiting_human");
    vi.advanceTimersByTime(60_000);
    expect(store.list()).toHaveLength(3);

    p.grantApproval("approval_1");
    const granted = store.list().filter((e) => e.type === "approval_granted");
    expect(granted).toHaveLength(1);
    expect(granted[0].message).toBe("Aprovado pelo consultor");
    expect(p.status).toBe("playing");

    vi.advanceTimersByTime(1000);
    expect(store.list().at(-1)?.type).toBe("task_started");
    const v = deriveState(store.list());
    expect(v.gates.approval_1).toBe("approved");
    expect(v.nodes.agent).toBe("running");
  });

  it("dois cliques rápidos geram um único approval_granted", () => {
    const store = createMemoryStore();
    const p = createPlayer({ mode: "simulation", source, store });
    p.play();
    vi.advanceTimersByTime(2000);
    p.grantApproval("approval_1");
    p.grantApproval("approval_1");
    expect(store.list().filter((e) => e.type === "approval_granted")).toHaveLength(1);
  });

  it("aprovar o gate errado não faz nada", () => {
    const store = createMemoryStore();
    const p = createPlayer({ mode: "simulation", source, store });
    p.play();
    vi.advanceTimersByTime(2000);
    p.grantApproval("approval_2");
    expect(store.list().filter((e) => e.type === "approval_granted")).toHaveLength(0);
    expect(p.status).toBe("waiting_human");
  });

  it("restart no meio limpa o store e o timer antigo não emite depois", () => {
    const store = createMemoryStore();
    const p = createPlayer({ mode: "simulation", source, store });
    p.play();
    vi.advanceTimersByTime(500);
    p.restart();
    expect(store.list()).toHaveLength(0);
    vi.advanceTimersByTime(1500);
    // depois do restart: eventos de 0 s e 1 s, sem duplicatas do timer antigo
    expect(store.list().map((e) => e.type)).toEqual(["task_started", "file_written"]);
  });

  it("dispose cancela o timer pendente", () => {
    const store = createMemoryStore();
    const p = createPlayer({ mode: "replay", source, store });
    p.play();
    vi.advanceTimersByTime(0);
    p.dispose();
    vi.advanceTimersByTime(10_000);
    expect(store.list()).toHaveLength(0);
  });
});
