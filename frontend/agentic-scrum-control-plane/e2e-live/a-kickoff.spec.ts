import { expect, test } from '@playwright/test';

// Runs first (file name order): the gateway is still idle, so the kickoff screen is showing.
test('the kickoff screen asks for name, repository, problem and constraints, and has a problem-file loader', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1000 });
  await page.goto('/');
  for (const label of ['Project name', 'GitHub repository', 'Project brief', 'Constraints']) {
    await expect(page.getByLabel(label)).toBeVisible();
  }
  await expect(page.getByLabel('Problem file')).toBeAttached();
  await page.getByLabel('Problem file').setInputFiles({ name: 'problem.md', mimeType: 'text/markdown', buffer: Buffer.from('# Todo CLI\nA task list.') });
  await expect(page.getByLabel('Project brief')).toHaveValue('# Todo CLI\nA task list.');
  await page.screenshot({ path: 'e2e-live/screenshots/kickoff.png', fullPage: true });
});
