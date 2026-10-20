import { expect, test } from '@playwright/test';

test.describe('Standup in demo mode', () => {
  test.beforeEach(async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('/?layout=panels');
    await page.waitForFunction(() => !document.body.textContent?.includes('Loading workspace…'));
    (page as unknown as { __errors: string[] }).__errors = errors;
    await page.getByRole('tab', { name: 'Standup' }).click();
    await expect(page.getByTestId('standup-view')).toBeVisible();
  });

  test.afterEach(async ({ page }) => {
    const errors = (page as unknown as { __errors: string[] }).__errors ?? [];
    expect(errors, `uncaught page errors: ${errors.join('; ')}`).toHaveLength(0);
  });

  test('opens on the meeting that waits for the Business SME, with eight developers, shared skills and a blocked developer', async ({ page }) => {
    await expect(page.getByRole('heading', { level: 1, name: 'Sprint 1 planning' })).toBeVisible();
    await expect(page.getByTestId('participant-count')).toHaveText('10');
    await expect(page.getByTestId('meeting-status')).toHaveText('Waiting for the Business SME');
    expect(await page.getByTestId('skill-badge').filter({ hasText: 'Backend' }).count()).toBeGreaterThanOrEqual(2);
    await expect(page.getByTestId('participant-card').filter({ hasText: 'Developer 03' })).toHaveAttribute('data-status', 'blocked');
    await expect(page.getByTestId('participant-card').filter({ hasText: 'Business SME' })).toHaveAttribute('data-status', 'needs_sme');
    await page.screenshot({ path: 'e2e/screenshots/standup-waiting.png', fullPage: true });
  });

  test('takes the answer, then the meeting carries on to a decision and ends', async ({ page }) => {
    await page.getByRole('button', { name: '10 (recommended)' }).click();
    await expect(page.getByTestId('meeting-status')).toHaveText('Finished', { timeout: 20_000 });
    await expect(page.getByTestId('decision')).toContainText('Sprint 1: contracts, router and timer plugin in parallel');
    await expect(page.getByTestId('action-item')).toContainText('Freeze the Clock, Tick and announce interfaces today');
    await expect(page.getByRole('button', { name: 'Replay this meeting' })).toBeVisible();
    await page.screenshot({ path: 'e2e/screenshots/standup-finished.png', fullPage: true });
  });

  test('hands the waiting question to the autopilot, which answers it', async ({ page }) => {
    await page.getByRole('radio', { name: 'Autopilot SME' }).click();
    await expect(page.getByTestId('control-mode')).toHaveText('Autopilot Business SME');
    await expect(page.getByTestId('meeting-status')).toHaveText('Finished', { timeout: 25_000 });
  });

  test('replays the finished discovery meeting: the six generic developers, the question, the decision', async ({ page }) => {
    await page.getByRole('button', { name: /Discovery: Jarvis timers and reminders/ }).click();
    await expect(page.getByTestId('meeting-status')).toHaveText('Finished');
    await expect(page.getByTestId('participant-count')).toHaveText('8');
    await expect(page.getByTestId('skill-badge')).toHaveCount(0);
    await page.getByRole('button', { name: 'Replay this meeting' }).click();
    await expect(page.getByTestId('replay-controls')).toBeVisible();
    await page.getByRole('button', { name: 'Next question' }).click();
    await expect(page.getByTestId('question-card')).toBeVisible();
    await page.getByRole('button', { name: 'Next decision' }).click();
    await page.getByRole('button', { name: 'Play replay' }).click();
    await page.getByRole('combobox', { name: 'Playback speed' }).selectOption('8');
    await expect(page.getByTestId('replay-position')).toContainText('event 36 of 36', { timeout: 30_000 });
    await expect(page.getByTestId('decision')).toContainText('Alerts wait while Jarvis speaks or listens');
    await page.screenshot({ path: 'e2e/screenshots/standup-replay.png', fullPage: true });
    await page.getByRole('button', { name: 'Back to live' }).click();
    await expect(page.getByTestId('replay-controls')).toHaveCount(0);
  });

  test('shows the transcript and works from the keyboard', async ({ page }) => {
    await page.getByRole('button', { name: /Discovery: Jarvis timers and reminders/ }).click();
    await page.getByRole('button', { name: 'Open transcript' }).focus();
    await page.keyboard.press('Enter');
    const dialog = page.getByRole('dialog', { name: 'Transcript' });
    await expect(dialog).toContainText('Developer 04 — Challenge to Developer 03:');
    await page.keyboard.press('Enter'); // the Close button has focus
    await expect(dialog).toHaveCount(0);
  });

  test('keeps the open meeting in the address, so a reload opens the same one', async ({ page }) => {
    await page.getByRole('button', { name: /Discovery: Jarvis timers and reminders/ }).click();
    await expect(page).toHaveURL(/standup=discovery/);
    await page.reload();
    await page.getByRole('tab', { name: 'Standup' }).click();
    await expect(page.getByRole('heading', { level: 1, name: /Discovery: Jarvis/ })).toBeVisible();
  });
});
