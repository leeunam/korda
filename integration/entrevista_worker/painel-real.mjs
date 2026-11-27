import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';
import { verificarPainel } from '../../apps/web/scripts/verificar-painel.mjs';

const [baseUrl, manifestPath, output] = process.argv.slice(2);
const interview = JSON.parse(await readFile(manifestPath, 'utf8'));
const browser = await chromium.launch({ headless: true });
try {
  await verificarPainel(browser, baseUrl);
  const page = await browser.newPage({ acceptDownloads: true });
  page.setDefaultTimeout(15000);
  const button = name => page.getByRole('button', { name, exact: true });
  const testId = name => page.getByTestId(name);
  const active = async name => (await button(name).count()) > 0 && await button(name).isEnabled();
  const zip = page.getByRole('link', { name: 'pacote.zip', exact: true });
  async function importRevision(revision) {
    await page.getByLabel('Revisão da descoberta', { exact: true }).fill(String(revision));
    await button('Consultar revisão').click();
    await testId('source-hash').waitFor();
    await button('Importar revisão').click();
    await page.getByRole('heading', { name: 'Revisão importada · ' + revision, exact: true }).waitFor();
  }
  await page.goto(new URL('/operador', baseUrl).href);
  await page.getByLabel('Projeto', { exact: true }).fill(interview.project_id);
  await button('Abrir projeto').click();
  await importRevision(interview.pending_revision);
  await testId('lacunas').waitFor();
  assert.match(await testId('lacunas').innerText(), /rateio|frete/i);
  assert.equal(await active('Aprovar plano'), false);
  assert.equal(await active('Iniciar execução'), false);
  await importRevision(interview.ready_revision);
  await testId('plan-version').waitFor();
  await page.getByLabel('Responsável pela decisão do plano', { exact: true }).fill('Revisor da demonstração');
  await button('Aprovar plano').click();
  await button('Iniciar execução').click();
  const state = testId('run-state');
  await state.waitFor();
  await page.waitForFunction(() => {
    const value = document.querySelector('[data-testid="run-state"]')?.getAttribute('data-state');
    return ['aguardando_aprovacao_entrega', 'falhou', 'invalidada'].includes(value);
  }, undefined, { timeout: 360000 });
  assert.equal(await state.getAttribute('data-state'), 'aguardando_aprovacao_entrega');
  await testId('kpis').waitFor();
  // Sem gabarito no fluxo (27/11/2026): a pessoa decide a entrega olhando os indicadores.
  assert.equal(await testId('avaliacao').count(), 0);
  assert.match(await testId('kpis').innerText(), /OTIF/);
  assert.match(await testId('kpis').innerText(), /Ocupação/);
  assert.equal(await zip.count(), 0);
  assert.equal(await active('Promover entrega'), false);
  const run = (await testId('run-id').innerText()).trim();
  const plan = (await testId('plan-version').innerText()).trim();
  const premature = await page.request.get(new URL('/api/operador/projetos/' + encodeURIComponent(interview.project_id) +
    '/runs/' + encodeURIComponent(run) + '/arquivos/pacote.zip', baseUrl).href);
  assert.ok([403, 404, 409].includes(premature.status()));
  await page.getByLabel('Responsável pela decisão da entrega', { exact: true }).fill('Revisora da entrega');
  await button('Autorizar entrega').click();
  await button('Promover entrega').click();
  await zip.waitFor();
  assert.equal(await state.getAttribute('data-state'), 'promovida');
  const download = page.waitForEvent('download');
  await zip.click();
  await (await download).saveAs(path.join(output, 'pacote.zip'));
  await writeFile(path.join(output, 'observado.json'), JSON.stringify({ run_id: run, plan_version: plan }));
} finally {
  await browser.close();
}
