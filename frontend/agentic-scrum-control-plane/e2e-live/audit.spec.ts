import fs from 'node:fs';
import { expect, test, type Page } from '@playwright/test';

/**
 * Audit, not a pass/fail test of behaviour: walks a whole live run, screenshots every phase in both views, lists every button and
 * tab it can see, clicks the harmless ones, and writes what it found (plus console errors and failed requests) to e2e-live/audit/.
 * Run on its own: npx playwright test -c playwright.live.config.ts audit
 */
const OUT = 'e2e-live/audit';
const problems: string[] = [];
const inventory: Record<string, string[]> = {};

async function buttons(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const seen = new Set<string>();
    document.querySelectorAll<HTMLElement>('button, [role="tab"], a[href], input, textarea, select, [role="button"]').forEach((el) => {
      const rect = el.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const name = (el.getAttribute('aria-label') || el.getAttribute('title') || el.textContent || el.getAttribute('placeholder') || '').trim().replace(/\s+/g, ' ').slice(0, 70);
      const disabled = (el as HTMLButtonElement).disabled ? ' [disabled]' : '';
      seen.add(`${el.tagName.toLowerCase()}: ${name}${disabled}`);
    });
    return [...seen];
  });
}

async function snap(page: Page, name: string) {
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
  inventory[name] = await buttons(page);
}

test.use({ actionTimeout: 15_000 });

test.beforeAll(() => { fs.mkdirSync(OUT, { recursive: true }); });
test.afterAll(() => {
  fs.writeFileSync(`${OUT}/report.json`, JSON.stringify({ problems, inventory }, null, 2));
});

test('audit a whole live run', async ({ page }) => {
  page.on('console', (m) => { if (m.type() === 'error') problems.push(`console: ${m.text().slice(0, 200)}`); });
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message.slice(0, 200)}`));
  page.on('requestfailed', (r) => problems.push(`request failed: ${r.method()} ${r.url()} ${r.failure()?.errorText}`));
  page.on('response', (r) => { if (r.status() >= 400) problems.push(`http ${r.status()}: ${r.request().method()} ${r.url()}`); });

  await page.setViewportSize({ width: 1400, height: 1000 });
  await page.goto('/');
  await expect(page.getByLabel('Project brief')).toBeVisible();
  await snap(page, '01-kickoff-genui');

  // settings, drawer tabs and the control plane before anything started
  await page.getByText('Settings').first().click();
  await snap(page, '02-settings');
  await page.keyboard.press('Escape');
  await page.getByText('Reveal Drawer:').click();
  await snap(page, '03-drawer-open');
  for (const tab of ['Agent Roster', 'Artifacts', 'Transcript Log', 'Timeline & Velocity']) {
    const t = page.getByText(tab, { exact: true }).first();
    if (await t.isVisible().catch(() => false)) { await t.click(); await snap(page, `03-drawer-${tab.replace(/\W+/g, '-').toLowerCase()}`); }
  }
  await page.getByText('Reveal Drawer:').click(); // close it again
  await page.getByRole('tab', { name: 'Control Plane' }).click();
  await snap(page, '04-control-plane-idle');
  await page.getByRole('tab', { name: 'GenUI' }).click();

  // start
  await page.getByLabel('Project name').fill('Todo CLI');
  await page.getByLabel('GitHub repository').fill('https://github.com/example/todo-cli');
  await page.getByLabel('Constraints').fill('Python only\nno network');
  await page.getByLabel('Project brief').fill('A small command line task list with add, list and done commands, stored in a JSON file.');
  await snap(page, '05-kickoff-filled');
  await page.getByLabel('GitHub repository').fill(''); // a real repository would be cloned; the scripted run builds locally
  await page.getByRole('button', { name: /Start the meet/ }).click();

  // meeting
  await expect(page.getByText(/Should tasks sync across devices\?/).first()).toBeVisible({ timeout: 120_000 });
  await snap(page, '06-brainstorm-question-genui');
  await page.getByRole('tab', { name: 'Control Plane' }).click();
  await snap(page, '07-control-plane-meeting');
  await page.getByRole('tab', { name: 'GenUI' }).click();
  await page.getByRole('button', { name: /^No\s+\(recommended\)/ }).click();
  await expect(page.getByText(/Decision ratified by Business SME/)).toBeVisible({ timeout: 60_000 });
  await snap(page, '08-brainstorm-answered');

  // documents
  await expect(page.getByRole('heading', { name: /Read the documents before anything is built/ })).toBeVisible({ timeout: 180_000 });
  await snap(page, '09-documents-prd');
  for (const doc of [/Technical_Approach/, /Design.md/]) {
    await page.getByRole('tab', { name: doc }).click();
    await snap(page, `10-documents-${String(doc).replace(/\W+/g, '')}`);
  }
  await page.getByRole('button', { name: /Request changes/ }).click();
  await snap(page, '11-documents-request-changes');
  await page.getByRole('tab', { name: 'Control Plane' }).click();
  await snap(page, '12-control-plane-documents');
  await page.getByRole('tab', { name: 'GenUI' }).click();
  await page.getByRole('button', { name: /Accept all documents and start building/ }).click();

  // build
  await expect(page.getByText(/features? merged/).first()).toBeVisible({ timeout: 120_000 });
  await snap(page, '13-build-genui');
  await page.getByRole('tab', { name: 'Control Plane' }).click();
  await snap(page, '14-control-plane-build');
  await page.getByRole('tab', { name: 'GenUI' }).click();

  const finished = page.getByRole('heading', { name: 'The team has finished' });
  const deadline = Date.now() + 6 * 60 * 1000;
  let shots = 0;
  while (!(await finished.isVisible()) && Date.now() < deadline) {
    const panel = page.getByRole('region', { name: 'Decisions waiting for you' });
    if (await panel.isVisible()) {
      if (shots < 2) { await snap(page, `15-decision-${shots++}`); }
      await panel.getByRole('button', { name: 'Approve' }).first().click();
    }
    await page.waitForTimeout(500);
  }
  await expect(finished).toBeVisible();
  await snap(page, '16-finished-genui');
  await page.getByRole('tab', { name: 'Control Plane' }).click();
  await snap(page, '17-control-plane-finished');

  // narrow
  await page.setViewportSize({ width: 420, height: 900 });
  await snap(page, '18-control-plane-narrow');
  await page.getByRole('tab', { name: 'GenUI' }).click();
  await snap(page, '19-finished-narrow');
});
