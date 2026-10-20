import { expect, test } from '@playwright/test';

test.describe('the Standup call screen in demo mode', () => {
  test.beforeEach(async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/');
    await page.waitForFunction(() => !document.body.textContent?.includes('Loading workspace…'));
    (page as unknown as { __errors: string[] }).__errors = errors;
    await page.getByRole('tab', { name: 'Standup' }).click();
    await expect(page.getByTestId('call-view')).toBeVisible();
  });

  test.afterEach(async ({ page }) => {
    const errors = (page as unknown as { __errors: string[] }).__errors ?? [];
    expect(errors, `uncaught page errors: ${errors.join('; ')}`).toHaveLength(0);
  });

  test('opens as a call: people at their desks, a shared screen with the question, the red line that says who needs you', async ({ page }) => {
    await expect(page.getByTestId('call-tile')).toHaveCount(10);
    await expect(page.getByTestId('needs-you')).toContainText('Sprint 1 planning needs you');
    await expect(page.getByTestId('needs-you')).toContainText('Is a limit of 10 timers right?');
    await expect(page.getByTestId('stage-title')).toHaveText('A question for the Business SME');
    await expect(page.getByTestId('call-tile').filter({ hasText: 'Business SME' })).toHaveAttribute('data-state', 'needs_sme');
    await expect(page.getByTestId('call-tile').filter({ hasText: 'Developer 03' })).toHaveAttribute('data-state', 'blocked');
    await expect(page.getByTestId('subtitle-text')).not.toBeEmpty();
    await page.screenshot({ path: 'e2e/screenshots/standup-call.png', fullPage: true });
  });

  test('answering on the shared screen carries the meeting on: lines are said one after another, the speaker gets the spotlight and the camera', async ({ page }) => {
    await page.getByTestId('call-stage').getByRole('button', { name: '10 (recommended)' }).click();
    await expect(page.getByTestId('needs-you')).toHaveCount(0, { timeout: 15_000 });
    await expect(page.getByTestId('meeting-status')).toHaveText('Finished', { timeout: 30_000 });
    await expect(page.getByTestId('call-stage')).toHaveAttribute('data-shown', /decision|actions|now|documents/);
    await page.screenshot({ path: 'e2e/screenshots/standup-call-after.png', fullPage: true });
  });

  test('shows who is speaking while a line is being said, and the line a sentence at a time', async ({ page }) => {
    await page.getByRole('button', { name: /Discovery: Jarvis timers and reminders/ }).first().click();
    await page.getByRole('button', { name: 'Replay this meeting' }).click();
    await page.getByRole('combobox', { name: 'Playback speed' }).selectOption('1');
    await page.getByRole('button', { name: 'Play replay' }).click();
    await expect(page.locator('[data-testid="call-tile"][data-speaking="true"]')).toHaveCount(1, { timeout: 20_000 });
    await expect(page.getByTestId('speech-bubble')).toBeVisible();
    await expect(page.getByTestId('sharing-badge')).toContainText('is sharing');
    await page.screenshot({ path: 'e2e/screenshots/standup-call-speaking.png', fullPage: true });
    await page.getByRole('button', { name: 'Pause replay' }).click();
  });

  test('has focus, tree and meetings-board views, a recap and a replay with highlights', async ({ page }) => {
    await page.getByRole('button', { name: 'Focus', exact: true }).click();
    await expect(page.getByTestId('call-view')).toHaveAttribute('data-layout', 'focus');
    await page.screenshot({ path: 'e2e/screenshots/standup-call-focus.png', fullPage: true });
    await page.getByRole('tab', { name: 'Tree' }).click();
    await expect(page.getByTestId('tree-view')).toBeVisible();
    await expect(page.getByTestId('tree-node')).toHaveCount(10);
    await page.screenshot({ path: 'e2e/screenshots/standup-tree.png', fullPage: true });
    await page.getByRole('tab', { name: 'Meetings' }).click();
    await expect(page.getByTestId('board-needs')).toContainText('Sprint 1 planning');
    await expect(page.getByTestId('board-done')).toContainText('Discovery');
    await page.screenshot({ path: 'e2e/screenshots/standup-board.png', fullPage: true });
    await page.getByRole('tab', { name: 'Call' }).click();
    await page.getByRole('button', { name: 'Recap' }).click();
    await expect(page.getByTestId('recap')).toBeVisible();
    await expect(page.getByTestId('kpi-people')).toHaveText('10');
    await page.screenshot({ path: 'e2e/screenshots/standup-recap.png' });
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('recap')).toHaveCount(0);
  });

  test('works from the keyboard: G goes to what needs you, T and B switch views, ? shows the shortcuts, Space pauses', async ({ page }) => {
    await page.getByRole('button', { name: /Discovery: Jarvis timers and reminders/ }).first().click();
    await expect(page.getByTestId('meeting-status')).toHaveText('Finished');
    await page.keyboard.press('g');
    await expect(page.getByRole('heading', { level: 1, name: 'Sprint 1 planning' })).toBeVisible();
    await page.keyboard.press('t');
    await expect(page.getByTestId('tree-view')).toBeVisible();
    await page.keyboard.press('t');
    await expect(page.getByTestId('call-view')).toBeVisible();
    await page.keyboard.press('b');
    await expect(page.getByTestId('meetings-board')).toBeVisible();
    await page.keyboard.press('b');
    await page.keyboard.press('?');
    await expect(page.getByTestId('shortcuts')).toBeVisible();
    await page.keyboard.press('Escape');
    await page.keyboard.press(' ');
    await expect(page.getByRole('button', { name: 'Resume lines' })).toBeVisible();
    await page.keyboard.press(' ');
    await expect(page.getByRole('button', { name: 'Pause lines' })).toBeVisible();
  });

  test('uses one row per person in a narrow window', async ({ page }) => {
    await page.setViewportSize({ width: 430, height: 900 });
    await expect(page.getByTestId('call-view')).toHaveAttribute('data-layout', 'compact');
    await page.screenshot({ path: 'e2e/screenshots/standup-call-narrow.png', fullPage: true });
  });
});
