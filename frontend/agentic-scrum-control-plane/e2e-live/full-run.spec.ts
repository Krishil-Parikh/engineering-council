import { expect, test } from '@playwright/test';

/**
 * One whole run, driven through the real UI against the real gateway (scripted models): type a brief, answer the meeting's question, read and accept the
 * documents, watch the sprints, decide what the team asks, and end on the final branch.
 */
test('a brief becomes documents you accept and then a finished project', async ({ page }) => {
  await page.goto('/');

  // 1. kickoff: nothing is pre-filled
  const brief = page.getByLabel('Project brief');
  await expect(brief).toHaveValue('');
  await page.getByLabel('Project name').fill('Todo CLI');
  await brief.fill('A small command line task list with add, list and done commands, stored in a JSON file.');
  await page.getByRole('button', { name: /Start the meet/ }).click();

  // 2. the meeting asks a product question; the options come from the question, not from the demo
  await expect(page.getByText(/Should tasks sync across devices\?/).first()).toBeVisible({ timeout: 120_000 });
  await expect(page.getByText(/Option A: Mandate Redis/)).toHaveCount(0);
  await page.getByRole('button', { name: /^No\s+\(recommended\)/ }).click();
  await expect(page.getByText(/Decision ratified by Business SME/)).toBeVisible({ timeout: 60_000 });

  // 3. the documents appear and nothing is built until you accept
  await expect(page.getByRole('heading', { name: /Read the documents before anything is built/ })).toBeVisible({ timeout: 180_000 });
  await expect(page.getByTestId('document-text')).not.toBeEmpty();
  await page.getByRole('tab', { name: /Design.md/ }).click();
  await expect(page.getByTestId('document-text')).toContainText('Design');
  await expect(page.getByText('Waiting for your decision')).toBeVisible();
  await page.waitForTimeout(5000); // longer than the demo's old auto sign-off: it must still be waiting
  await expect(page.getByRole('button', { name: /Accept all documents and start building/ })).toBeVisible();
  await page.screenshot({ path: 'e2e-live/screenshots/documents.png' });
  await page.getByRole('button', { name: /Accept all documents and start building/ }).click();

  // 4. the build: the graph is the real team; decisions the team needs appear and are answered
  await expect(page.getByText(/features? merged/).first()).toBeVisible({ timeout: 120_000 });
  await expect(page.getByText('Spine timeline navigation with SVG stroke animations')).toHaveCount(0);
  await page.screenshot({ path: 'e2e-live/screenshots/build.png' });

  const finished = page.getByRole('heading', { name: 'The team has finished' });
  const deadline = Date.now() + 6 * 60 * 1000;
  while (!(await finished.isVisible()) && Date.now() < deadline) {
    const panel = page.getByRole('region', { name: 'Decisions waiting for you' });
    if (await panel.isVisible()) {
      await panel.getByRole('button', { name: 'Approve' }).first().click();
    }
    await page.waitForTimeout(500);
  }

  // 5. the end: the final branch, for you to review; nothing was merged into main
  await expect(finished).toBeVisible();
  await expect(page.getByText(/final\/\d{8}-\d{6}|final\//).first()).toBeVisible();
  await expect(page.getByText(/Nothing has been merged into main/).first()).toBeVisible();
  await page.screenshot({ path: 'e2e-live/screenshots/finished.png' });
});

test('the control plane shows the finished run with real data and none of the demo content', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('tab', { name: 'Control Plane' }).click();
  await expect(page.getByTitle('Inject an architectural challenge into the active meet')).toBeVisible();
  await expect(page.getByTitle('Step next agent message & pulse')).toHaveCount(0);
  await expect(page.getByText('Todo CLI', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('DOCUMENTS ACCEPTED', { exact: true })).toBeVisible();
  await expect(page.getByText('3/3').first()).toBeVisible();
  await expect(page.getByText('FEATURES MERGED', { exact: true })).toBeVisible();
  for (const demo of ['Fintech Clearing SDLC', 'FINMA', 'AUTOPILOT', 'Elapsed', '4.2k tok/s', 'Zurich', 'Kafka']) {
    await expect(page.getByText(demo)).toHaveCount(0);
  }
  // each tab shows real content
  for (const tab of ['Canvas', 'Meet', 'Artifacts', 'Timeline']) {
    await page.getByRole('button', { name: new RegExp(`^${tab}`) }).click();
  }
  await expect(page.getByText(/^SPRINT DOCUMENTS/)).toBeVisible();
});
