import { expect, test } from '@playwright/test';

test.describe('workspace shell smoke', () => {
  test.beforeEach(async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('/');
    await expect(page.getByRole('tablist', { name: 'Workspace view' })).toBeVisible();
    await page.waitForFunction(() => !document.body.textContent?.includes('Loading workspace…'));
    (page as unknown as { __errors: string[] }).__errors = errors;
  });

  test.afterEach(async ({ page }) => {
    const errors = (page as unknown as { __errors: string[] }).__errors ?? [];
    expect(errors, `uncaught page errors: ${errors.join('; ')}`).toHaveLength(0);
  });

  test('GenUI boots on the canonical phase', async ({ page }) => {
    await expect(page.getByText('Agent roster & standby skills')).toBeVisible();
  });

  test('mode switch preserves workspace state in both views', async ({ page }) => {
    await page.getByRole('tab', { name: 'Control Plane' }).click();
    await expect(page.getByText('LIVE DELEGATION GRAPH')).toBeVisible();
    await expect(page.getByText('Agent-01').first()).toBeVisible();
    await page.getByRole('tab', { name: 'GenUI' }).click();
    await expect(page.getByText('Agent roster & standby skills')).toBeVisible();
  });

  test('keyboard arrows switch modes', async ({ page }) => {
    await page.getByRole('tab', { name: 'GenUI' }).press('ArrowRight');
    await expect(page.getByText('LIVE DELEGATION GRAPH')).toBeVisible();
    await page.getByRole('tab', { name: 'Control Plane' }).press('ArrowLeft');
    await expect(page.getByText('Agent roster & standby skills')).toBeVisible();
  });

  test('desktop and narrow viewports capture both modes', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.getByRole('tab', { name: 'GenUI' }).click();
    await expect(page.getByText('Agent roster & standby skills')).toBeVisible();
    await page.screenshot({ path: 'e2e/screenshots/genui-desktop.png' });
    await page.getByRole('tab', { name: 'Control Plane' }).click();
    await expect(page.getByText('LIVE DELEGATION GRAPH')).toBeVisible();
    await page.screenshot({ path: 'e2e/screenshots/control-plane-desktop.png' });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole('tab', { name: 'GenUI' }).click();
    await expect(page.getByText('Agent roster & standby skills')).toBeVisible();
    await page.screenshot({ path: 'e2e/screenshots/genui-narrow.png' });
    await page.getByRole('tab', { name: 'Control Plane' }).click();
    await expect(page.getByText('LIVE DELEGATION GRAPH')).toBeVisible();
    await page.screenshot({ path: 'e2e/screenshots/control-plane-narrow.png' });
  });
});
