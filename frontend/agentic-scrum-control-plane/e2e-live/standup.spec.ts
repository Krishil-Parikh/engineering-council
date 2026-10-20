import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

/**
 * Formal meetings through the real gateway (scripted models): a run is started, the Business SME answers inside the Standup tab, the documents wait for a person whatever the
 * mode, and the finished meetings can be read back, replayed and found on disk as structured events. Runs after full-run.spec.ts (alphabetical), which leaves a finished project.
 */
const GATEWAY = 'http://127.0.0.1:8765';
const WORKSPACE = 'workspace-demo';
const BRIEF = 'A small command line task list with add, list and done commands, stored in a JSON file.';

async function start(request: APIRequestContext, title: string) {
  const response = await request.post(`${GATEWAY}/workspace/${WORKSPACE}/commands`, {
    data: { type: 'sprint.start', workspaceId: WORKSPACE, brief: BRIEF, title },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
}

async function phase(request: APIRequestContext) {
  return (await (await request.get(`${GATEWAY}/workspace/${WORKSPACE}/snapshot`)).json()).phaseId as string;
}

async function openStandup(page: Page) {
  await page.goto('/?layout=panels');
  await page.getByRole('tab', { name: 'Standup' }).click();
  await expect(page.getByTestId('standup-view')).toBeVisible();
}

test('the Business SME answers the kickoff question in the Standup tab and the documents wait for approval there', async ({ page, request }) => {
  await start(request, 'Standup Todo');
  await openStandup(page);

  // the kickoff meeting appears as a live meeting, with its people, and asks its product question
  const kickoff = page.getByRole('button', { name: /Kickoff meeting: Standup Todo/ });
  await expect(kickoff).toBeVisible({ timeout: 60_000 });
  await kickoff.click();
  await expect(page.getByTestId('question-card')).toContainText('Should tasks sync across devices?', { timeout: 120_000 });
  await expect(page.getByTestId('meeting-status')).toHaveText('Waiting for the Business SME');
  await expect(page.getByTestId('participant-card').filter({ hasText: 'Business SME' }).first()).toHaveAttribute('data-status', 'needs_sme');
  expect(await page.getByTestId('participant-card').count()).toBeGreaterThanOrEqual(8);
  await page.screenshot({ path: 'e2e-live/screenshots/standup-question.png', fullPage: true });

  await page.getByTestId('question-panel').getByRole('button', { name: /^No \(recommended\)/ }).click(); // the floating decision card offers the same option; this is the Standup panel's
  await expect(page.getByTestId('question-card')).toHaveCount(0, { timeout: 30_000 });
  await expect(page.getByTestId('timeline-entry').filter({ hasText: 'No' }).first()).toBeVisible();

  // the meeting ends with the documents; the approval is waiting in the document-review meeting, for a person
  const review = page.getByRole('button', { name: /Document review/ });
  await expect(review).toBeVisible({ timeout: 240_000 });
  await review.click();
  const approval = page.getByTestId('approval');
  await expect(approval).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId('document-review').first()).toBeVisible();
  await page.waitForTimeout(4000);
  await expect(approval).toBeVisible(); // nothing accepted it on a timer
  expect(await phase(request)).toBe('prd');
  await page.screenshot({ path: 'e2e-live/screenshots/standup-documents.png', fullPage: true });

  await approval.getByRole('button', { name: 'Approve' }).click();
  await expect.poll(() => phase(request), { timeout: 60_000 }).toMatch(/build|review|ship/);

  // let the run finish (the team asks a few things; approve them here too)
  const deadline = Date.now() + 6 * 60 * 1000;
  while ((await phase(request)) !== 'ship' && Date.now() < deadline) {
    // whatever is waiting for the Business SME, in whichever meeting it is: the list says which
    const needing = page.getByTestId('meeting-row').filter({ hasText: 'waiting for you' });
    if (await needing.count()) await needing.first().click().catch(() => undefined);
    if (await page.getByTestId('approval').count()) await page.getByTestId('approval').first().getByRole('button', { name: 'Approve' }).click().catch(() => undefined);
    for (const card of await page.getByTestId('question-card').all()) {
      await card.getByRole('button').first().click().catch(() => undefined);
    }
    await page.waitForTimeout(700);
  }
  expect(await phase(request)).toBe('ship');
});

test('the finished run left real meetings: structured events, a transcript, and no merge chatter', async ({ page, request }) => {
  const listing = await (await request.get(`${GATEWAY}/workspace/${WORKSPACE}/standup/meetings`)).json();
  const ids: string[] = listing.meetings.map((m: { meeting_id: string }) => m.meeting_id);
  expect(ids).toContain('kickoff');
  expect(ids).toContain('document-review');
  expect(ids.some((id) => /^s1-standup\d+$/.test(id))).toBe(true);
  expect(ids.some((id) => /planning$/.test(id))).toBe(true);
  expect(ids.filter((id) => ['merge', 'team', 'briefings'].includes(id))).toEqual([]);

  const events = await (await request.get(`${GATEWAY}/workspace/${WORKSPACE}/standup/meetings/kickoff/events?limit=1000`)).json();
  const sequence: number[] = events.events.map((e: { sequence_number: number }) => e.sequence_number);
  expect(sequence).toEqual(sequence.map((_, i) => i + 1));
  const types = new Set<string>(events.events.map((e: { event_type: string }) => e.event_type));
  for (const t of ['meeting_created', 'meeting_started', 'participant_joined', 'clarification_requested', 'clarification_answered', 'meeting_ended']) expect(types).toContain(t);
  const transcript = await (await request.get(`${GATEWAY}/workspace/${WORKSPACE}/standup/meetings/kickoff/transcript`)).text();
  expect(transcript).toContain('Meeting created: Kickoff meeting: Standup Todo');
  expect(transcript).toContain('Should tasks sync across devices?');

  // and the browser can replay it
  await openStandup(page);
  await page.getByRole('button', { name: /Kickoff meeting: Standup Todo/ }).click();
  await expect(page.getByTestId('meeting-status')).toHaveText('Finished');
  await page.getByRole('button', { name: 'Replay this meeting' }).click();
  await page.getByRole('button', { name: 'Next question' }).click();
  await expect(page.getByTestId('question-card')).toContainText('Should tasks sync across devices?');
  await page.getByRole('button', { name: 'Open transcript' }).click().catch(() => undefined);
  await page.screenshot({ path: 'e2e-live/screenshots/standup-replay.png', fullPage: true });
});

test('with the autopilot on, the product question is answered for the Business SME, and the documents still wait for a person', async ({ page, request }) => {
  await start(request, 'Autopilot Todo');
  await openStandup(page);
  const kickoff = page.getByRole('button', { name: /Kickoff meeting: Autopilot Todo/ });
  await expect(kickoff).toBeVisible({ timeout: 60_000 });
  await kickoff.click();
  await page.getByRole('radio', { name: 'Autopilot SME' }).click();
  await expect(page.getByTestId('control-mode')).toHaveText('Autopilot Business SME');

  // nobody answers; the autopilot does (after a short moment in which a person could still take over)
  const transcript = async () => (await request.get(`${GATEWAY}/workspace/${WORKSPACE}/standup/meetings/kickoff/events?limit=1000`)).json();
  await expect.poll(async () => (await transcript()).events.some((e: { event_type: string; payload: { source?: string } }) => e.event_type === 'clarification_answered' && e.payload.source === 'autopilot'), { timeout: 180_000 }).toBe(true);
  await page.screenshot({ path: 'e2e-live/screenshots/standup-autopilot.png', fullPage: true });

  // but the documents are a decision for a person, whatever the mode
  await page.getByRole('button', { name: /Document review/ }).click({ timeout: 240_000 });
  await expect(page.getByTestId('approval')).toBeVisible({ timeout: 60_000 });
  await page.waitForTimeout(6000);
  await expect(page.getByTestId('approval')).toBeVisible();
  expect(await phase(request)).toBe('prd');

  // taking control back is recorded
  await page.getByRole('radio', { name: 'I answer' }).click();
  await expect.poll(async () => (await transcript()).events.some((e: { event_type: string }) => e.event_type === 'human_takeover'), { timeout: 20_000 }).toBe(true);
});
