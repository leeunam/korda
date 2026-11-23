/**
 * Gera uma execução SINTÉTICA da Korda para a UI funcionar antes do worker Python.
 * Transportadora fictícia, dados inventados. Não é resultado de validação.
 *
 * Uso: pnpm seed  →  grava src/data/seed-run.json (determinístico).
 */
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { EventType, RunEvent, StepId } from "../src/lib/events";

export type SeedRun = {
  run_id: string;
  synthetic: true;
  client: string;
  note: string;
  events: RunEvent[];
};

const RUN_ID = "run_demo_0001";
const START = Date.parse("2026-11-20T14:00:00-03:00");

type Beat = [
  seconds: number,
  step: StepId,
  type: EventType,
  message: string,
  extra?: { attempt?: number; data?: RunEvent["data"] },
];

/** Roteiro: segundos desde o início, passo, tipo, mensagem. */
const SCRIPT: Beat[] = [
  [0, "plan", "task_started", "Montando o plano a partir da entrevista e das fontes ERP, TMS e CT-e"],
  [3, "plan", "file_written", "Plano v1 gravado: 3 indicadores, 9 regras, 3 testes de aceite", { data: { file: "plan/v1.yaml" } }],
  [4.5, "approval_1", "approval_requested", "Plano v1 aguardando aprovação do consultor"],
  [12, "approval_1", "approval_granted", "Plano v1 aprovado pelo consultor"],

  [13, "agent", "task_started", "Executor iniciado com o plano v1"],
  [15, "agent", "file_written", "Camada bronze: entregas, fretes e viagens", { data: { file: "models/bronze/brz_entregas.sql" } }],
  [17, "agent", "file_written", "Camada bronze: CT-e emitidos", { data: { file: "models/bronze/brz_cte.sql" } }],
  [20, "agent", "file_written", "Camada prata: entregas elegíveis (sem canceladas)", { data: { file: "models/silver/slv_entregas_elegiveis.sql" } }],
  [23, "agent", "file_written", "Camada prata: viagens com capacidade do veículo", { data: { file: "models/silver/slv_viagens.sql" } }],
  [26, "agent", "file_written", "Ouro: custo de frete por entrega", { data: { file: "models/gold/custo_frete_entrega.sql", kpi: "custo_frete_entrega" } }],
  [28, "agent", "file_written", "Ouro: OTIF (no prazo e completo)", { data: { file: "models/gold/otif.sql", kpi: "otif" } }],
  [30, "agent", "file_written", "Ouro: ocupação dos veículos", { data: { file: "models/gold/ocupacao_veiculos.sql", kpi: "ocupacao_veiculos" } }],

  [31, "run_dbt", "task_started", "dbt build + testes de aceite: custo_frete_entrega", { attempt: 1 }],
  [35, "run_dbt", "test_failed", "custo_frete_entrega: obtido 237,50, esperado 166,67. CT-e reemitidos contados em dobro (342 linhas para 240 entregas)", {
    attempt: 1,
    data: { test: "custo_frete_entrega", kpi: "custo_frete_entrega", actual: 237.5, expected: 166.67 },
  }],
  [38, "agent", "fix_applied", "Correção 1/3: deduplicar CT-e pela chave de acesso, mantendo a última emissão", {
    attempt: 2,
    data: { file: "models/silver/slv_cte_dedup.sql" },
  }],
  [40, "write_hook", "write_blocked", "Escrita bloqueada: testes de aceite são somente leitura para o executor", {
    data: { file: "tests/acceptance/custo_frete_entrega.yml" },
  }],
  [42, "agent", "file_written", "Ouro: custo de frete por entrega usa CT-e deduplicados", { attempt: 2, data: { file: "models/gold/custo_frete_entrega.sql" } }],
  [43, "run_dbt", "task_started", "dbt build + testes de aceite: custo_frete_entrega", { attempt: 2 }],
  [47, "run_dbt", "test_passed", "custo_frete_entrega: obtido 166,67, esperado 166,67", {
    attempt: 2,
    data: { test: "custo_frete_entrega", kpi: "custo_frete_entrega", actual: 166.67, expected: 166.67 },
  }],

  [48, "run_dbt", "task_started", "Testes de aceite: otif", { attempt: 1 }],
  [52, "run_dbt", "test_passed", "otif: obtido 0,873, esperado 0,873 (no prazo e completo)", {
    attempt: 1,
    data: { test: "otif", kpi: "otif", actual: 0.873, expected: 0.873 },
  }],
  [53, "run_dbt", "task_started", "Testes de aceite: ocupacao_veiculos", { attempt: 1 }],
  [57, "run_dbt", "test_passed", "ocupacao_veiculos: obtido 0,712, esperado 0,712", {
    attempt: 1,
    data: { test: "ocupacao_veiculos", kpi: "ocupacao_veiculos", actual: 0.712, expected: 0.712 },
  }],

  [59, "approval_2", "approval_requested", "3 de 3 indicadores aprovados nos testes. Promoção aguardando autorização"],
  [69, "approval_2", "approval_granted", "Promoção autorizada pelo consultor"],
  [70, "deliver", "task_started", "Promovendo modelos para o destino definido no plano"],
  [74, "deliver", "run_completed", "Entrega promovida: 3 modelos ouro, relatório de testes e documentação"],
];

export function buildSeedRun(): SeedRun {
  return {
    run_id: RUN_ID,
    synthetic: true,
    client: "Transportadora Exemplo (fictícia)",
    note: "Execução sintética gerada por apps/web/scripts/seed.ts. Valores inventados; não são validação.",
    events: SCRIPT.map(([sec, step, type, message, extra]) => ({
      run_id: RUN_ID,
      step,
      type,
      message,
      attempt: extra?.attempt ?? null,
      ts: new Date(START + sec * 1000).toISOString(),
      ...(extra?.data ? { data: extra.data } : {}),
    })),
  };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const out = fileURLToPath(new URL("../src/data/seed-run.json", import.meta.url));
  writeFileSync(out, JSON.stringify(buildSeedRun(), null, 2) + "\n");
  console.log(`seed: ${out}`);
}
