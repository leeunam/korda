import { describe, expect, it } from "vitest";
import { deriveState } from "@/lib/derive";
import { STEPS } from "@/lib/events";
import { buildSeedRun } from "../../scripts/seed";
import seedRun from "./seed-run.json";

describe("seed-run.json", () => {
  const run = buildSeedRun();

  it("o arquivo versionado é igual ao gerado (seed determinístico)", () => {
    expect(seedRun).toEqual(JSON.parse(JSON.stringify(run)));
  });

  it("é identificado como sintético", () => {
    expect(run.synthetic).toBe(true);
    expect(run.client).toMatch(/fictional/);
  });

  it("tem ts estritamente crescente, um único run_id e no máximo 3 tentativas", () => {
    const times = run.events.map((e) => Date.parse(e.ts));
    times.slice(1).forEach((t, i) => expect(t).toBeGreaterThan(times[i]));
    expect(new Set(run.events.map((e) => e.run_id))).toEqual(new Set([run.run_id]));
    for (const e of run.events) if (e.attempt !== null) expect(e.attempt).toBeLessThanOrEqual(3);
  });

  it("conta a história do roteiro: falha de frete, escrita bloqueada, correção", () => {
    const failed = run.events.filter((e) => e.type === "test_failed");
    expect(failed).toHaveLength(1);
    expect(failed[0].data).toMatchObject({ test: "custo_frete_entrega", actual: 237.5, expected: 166.67 });
    expect(run.events.filter((e) => e.type === "write_blocked")).toHaveLength(1);
    expect(run.events.at(-1)?.type).toBe("run_completed");
  });

  it("ao final, tudo concluído e aprovado", () => {
    const v = deriveState(run.events);
    expect(v.completed).toBe(true);
    expect(v.allTestsPassed).toBe(true);
    expect(v.tests.map((t) => t.test).sort()).toEqual(
      ["custo_frete_entrega", "ocupacao_veiculos", "otif"],
    );
    for (const s of STEPS) expect(v.nodes[s]).toBe("done");
    expect(v.gates).toEqual({ approval_1: "approved", approval_2: "approved" });
  });

  it("logo após a falha, run_dbt aparece como falhou", () => {
    const i = run.events.findIndex((e) => e.type === "test_failed");
    expect(deriveState(run.events.slice(0, i + 1)).nodes.run_dbt).toBe("failed");
  });
});
