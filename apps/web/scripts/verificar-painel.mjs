import assert from "node:assert/strict";

// Exercita recuperação da interface em uma sessão isolada. O fluxo do serviço,
// com Postgres, decisões e Docker, usa um contexto de navegador independente.
export async function verificarPainel(browser, baseUrl) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  try {
    const page = await context.newPage();
    const prefixo = "**/api/operador/projetos/mobile-demo";
    const estado = { project_id: "mobile-demo", plan: null, run: null, source: null };
    const hash = "c".repeat(64);
    let ultima = 0;
    let consultas = 0;
    const comandos = [];
    await page.route(prefixo, route => {
      consultas++;
      return route.fulfill({ status: consultas === 1 ? 502 : 200,
        json: consultas === 1 ? { error: "Serviço local indisponível." } : estado });
    });
    await page.route(prefixo + "/fonte", route => route.fulfill({ json: {
      revision: ultima, context_id: "entrevista-fixture", sha256: "b".repeat(64), estado: "pendente",
      pendencias: [{ pergunta: "Que evidência falta?" }], lacunas: [],
    } }));
    await page.route(prefixo + "/fonte?revision=2", route => route.fulfill({ json: {
      revision: 2, context_id: "entrevista-fixture", sha256: hash, estado: "pendente",
      pendencias: [{ pergunta: "Como confirmar o rateio?" }], lacunas: [],
    } }));
    await page.route(prefixo + "/importar", async route => {
      comandos.push(route.request().postDataJSON());
      await route.fulfill({ status: 409, json: { error: "A revisão mudou. Consulte a fonte novamente." } });
    });

    await page.goto(new URL("/operador", baseUrl).href);
    const botao = name => page.getByRole("button", { name, exact: true });
    await page.getByLabel("Projeto", { exact: true }).fill(estado.project_id);
    await botao("Abrir projeto").click();
    await page.getByRole("alert").waitFor();
    assert.match(await page.getByRole("alert").innerText(), /indisponível/);
    await botao("Abrir projeto").click();
    await botao("Consultar última revisão").click();
    await page.getByText("Revisão consultada · 0").waitFor();
    assert.equal(await page.getByLabel("Revisão da descoberta").inputValue(), "0");
    await page.getByLabel("Revisão da descoberta").fill("2");
    await botao("Consultar revisão").click();
    await page.getByTestId("source-hash").waitFor();
    assert.equal((await page.getByTestId("source-hash").innerText()).trim(), hash);
    assert.equal(await page.getByTestId("lacunas").getByText("Como confirmar o rateio?").count(), 1);
    assert.equal(await botao("Aprovar plano").count(), 0);
    await botao("Importar revisão").click();
    await page.getByText("A revisão mudou. Consulte a fonte novamente.").waitFor();
    assert.deepEqual(comandos, [{ revision: 2, context_sha256: hash }]);
    assert.equal(await botao("Importar revisão").count(), 0);
    assert.equal(await botao("Iniciar execução").count(), 0);
    // Outro operador importou a revisão 2. Antes de aprovar, consultamos uma revisão mais recente.
    estado.plan = { plan_version: "a".repeat(64), state: "aguardando_aprovacao", context_id: "entrevista-fixture",
      context_revision: 2, context_sha256: hash, destination: "destino-teste", ingestion_level: "n0",
      cost_estimate_brl_cents: 0, gaps: [], metrics: {}, rules: { rateio_cte: {
        status: "confirmada", value: "peso", confirmed_by: { role: "financeiro" }, evidence_ids: ["evidencia-7"],
      } } };
    await botao("Atualizar projeto").click();
    await page.getByLabel("Responsável pela decisão do plano").fill("Revisora fictícia");
    assert.equal(await botao("Aprovar plano").isEnabled(), true);
    await page.getByText("Indicadores e regras do plano").click();
    await page.getByText("evidencia-7").waitFor();
    await page.getByText("Confirmada por financeiro").waitFor();
    ultima = 3;
    await botao("Consultar última revisão").click();
    await page.getByText("Revisão consultada · 3").waitFor();
    assert.equal(await botao("Aprovar plano").isEnabled(), false);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.getByRole("link", { name: "Grafo de exemplo", exact: true }).click();
    await page.getByRole("link", { name: "Painel do operador" }).click();
    await page.getByRole("heading", { name: "Operação do projeto" }).waitFor();
  } finally {
    await context.close();
  }
}
