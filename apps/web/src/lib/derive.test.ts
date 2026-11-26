import { describe, expect, it } from "vitest";
import { deriveState } from "./derive";
import { STEPS, type RunEvent } from "./events";

let clock = 0;
function ev(step: string, type: RunEvent["type"], extra: Partial<RunEvent> = {}): RunEvent {
  clock += 1000;
  return {
    run_id: "run_test",
    step: step as RunEvent["step"],
    type,
    message: `${step} ${type}`,
    attempt: null,
    ts: new Date(Date.UTC(2026, 10, 20, 17, 0, 0) + clock).toISOString(),
    ...extra,
  };
}

const failFrete = () =>
  ev("run_dbt", "test_failed", {
    attempt: 1,
    data: { test: "custo_frete_entrega", actual: 237.5, expected: 166.67 },
  });
const passFrete = () =>
  ev("run_dbt", "test_passed", {
    attempt: 2,
    data: { test: "custo_frete_entrega", actual: 166.67, expected: 166.67 },
  });
const pass = (test: string) => ev("run_dbt", "test_passed", { attempt: 1, data: { test } });

describe("deriveState", () => {
  it("sem eventos: tudo pendente e nada promovível", () => {
    const v = deriveState([]);
    for (const s of STEPS) expect(v.nodes[s]).toBe("pending");
    expect(v.gates).toEqual({ approval_1: "blocked", approval_2: "blocked" });
    expect(v.canPromote).toBe(false);
    expect(v.allTestsPassed).toBe(false);
  });

  it("teste falhou: run_dbt fica failed com valores da tentativa", () => {
    const v = deriveState([ev("run_dbt", "task_started"), failFrete()]);
    expect(v.nodes.run_dbt).toBe("failed");
    expect(v.tests).toHaveLength(1);
    expect(v.tests[0].test).toBe("custo_frete_entrega");
    expect(v.tests[0].attempts[0]).toMatchObject({ attempt: 1, passed: false, actual: 237.5, expected: 166.67 });
    expect(v.allTestsPassed).toBe(false);
  });

  it("falha, correção e nova tentativa aprovada: run_dbt done com duas tentativas", () => {
    const v = deriveState([
      ev("run_dbt", "task_started"),
      failFrete(),
      ev("agent", "fix_applied", { attempt: 2 }),
      passFrete(),
    ]);
    expect(v.nodes.run_dbt).toBe("done");
    expect(v.tests[0].passed).toBe(true);
    expect(v.tests[0].attempts).toHaveLength(2);
  });

  it("correção aplicada depois da falha: run_dbt volta a executar", () => {
    const v = deriveState([
      ev("run_dbt", "task_started"),
      failFrete(),
      ev("run_dbt", "task_started", { attempt: 2 }),
    ]);
    expect(v.nodes.run_dbt).toBe("running");
  });

  it("write_blocked não reprova o write hook", () => {
    const v = deriveState([
      ev("write_hook", "write_blocked", { data: { file: "tests/acceptance/custo_frete_entrega.yml" } }),
    ]);
    expect(v.nodes.write_hook).not.toBe("failed");
    expect(v.nodes.write_hook).toBe("done");
  });

  it("aprovação 1 pedida e concedida", () => {
    const requested = [ev("approval_1", "approval_requested")];
    expect(deriveState(requested).gates.approval_1).toBe("waiting");
    expect(deriveState(requested).nodes.approval_1).toBe("waiting_approval");
    const granted = [...requested, ev("approval_1", "approval_granted")];
    expect(deriveState(granted).gates.approval_1).toBe("approved");
    expect(deriveState(granted).nodes.approval_1).toBe("done");
  });

  it("aprovação 2 fica bloqueada enquanto algum teste falha", () => {
    const v = deriveState([failFrete(), pass("otif"), ev("approval_2", "approval_requested")]);
    expect(v.gates.approval_2).toBe("blocked");
    expect(v.canPromote).toBe(false);
  });

  it("promover só com todos os testes passando e aprovação 2 pedida", () => {
    const base = [failFrete(), passFrete(), pass("otif"), pass("ocupacao_veiculos")];
    expect(deriveState(base).canPromote).toBe(false);
    const requested = [...base, ev("approval_2", "approval_requested")];
    const v = deriveState(requested);
    expect(v.allTestsPassed).toBe(true);
    expect(v.gates.approval_2).toBe("waiting");
    expect(v.canPromote).toBe(true);
    const granted = deriveState([...requested, ev("approval_2", "approval_granted")]);
    expect(granted.gates.approval_2).toBe("approved");
    expect(granted.canPromote).toBe(false);
  });

  it("run_completed marca a execução concluída", () => {
    const v = deriveState([ev("deliver", "task_started"), ev("deliver", "run_completed")]);
    expect(v.completed).toBe(true);
    expect(v.nodes.deliver).toBe("done");
  });

  it("eventos fora de ordem de ts geram o mesmo resultado", () => {
    const ordered = [ev("run_dbt", "task_started"), failFrete(), ev("agent", "fix_applied"), passFrete()];
    const shuffled = [ordered[3], ordered[1], ordered[0], ordered[2]];
    expect(deriveState(shuffled)).toEqual(deriveState(ordered));
  });

  it("step desconhecido é ignorado sem quebrar", () => {
    const v = deriveState([ev("foo", "task_started"), ev("agent", "task_started")]);
    expect(v.nodes.agent).toBe("running");
    expect(Object.keys(v.eventsByStep)).toEqual([...STEPS]);
  });
});
