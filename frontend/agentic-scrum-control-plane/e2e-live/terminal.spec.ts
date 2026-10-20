import { expect, test } from '@playwright/test';

/** The live terminal of an agent, in both screens, with a build-phase snapshot (the gateway's snapshot is replaced; no model is needed). */
const snapshot = {
  workspaceId: 'workspace-demo', version: 10, phaseId: 'build',
  agents: [
    { id: 'agent-sm', name: 'Scrum Master', role: 'Scrum Master', status: 'active', activeTask: 'Merging feature/core-contracts', terminal: ['10:21:40 $ git merge --no-ff feature/core-contracts', '10:21:41   exit 0', '10:21:44 # Merged; running the safety tests.'] },
    { id: 'sme-01', name: 'SME-01', role: 'Business SME (you)', status: 'idle' },
    {
      id: 'agent-01', name: 'DEV_1', role: 'Backend Developer', status: 'active', claimedSkill: 'Backend', activeTask: 'timer-plugin: write the registry', activeBranch: 'feature/timer-plugin',
      terminal: [
        '10:20:01 read jarvis/core/contracts.py:40', '10:20:03 glob tests/*.py', '10:20:09 write jarvis/plugins/timer/timer_plugin.py',
        '10:20:15 $ pytest -q tests/test_timer_plugin.py', '10:20:19   exit 1', '10:20:20 ! File not found: jarvis/core/protocols.py', '10:20:31 # The Clock goes in contracts.py; fixing the import.',
        '10:20:40 $ pytest -q tests/test_timer_plugin.py', '10:20:44   exit 0',
      ],
    },
    { id: 'agent-02', name: 'DEV_2', role: 'Test Developer', status: 'idle', claimedSkill: 'Testing' },
  ],
  messages: [], skills: [], artifacts: [],
  meets: [{ id: 'meet-kickoff', title: 'Kickoff meeting: Jarvis Timers', status: 'completed', consensusRate: 80, debateIntensity: 20 }],
  sprints: [], edges: [{ id: 'e1', source: 'agent-sm', target: 'agent-01', label: 'Delegation', isActive: true, latencyMs: 0 }],
  metrics: { totalMessagesToday: 0, totalPRs: 2, prHistory: [] }, processedEventIds: [],
};

test('clicking an agent shows its live terminal, on the build screen and in the control plane', async ({ page }) => {
  await page.route('**/workspace/workspace-demo/snapshot', (route) => route.fulfill({ json: snapshot }));
  await page.route('**/workspace/workspace-demo/events', (route) => route.fulfill({ status: 200, contentType: 'text/event-stream', body: ': ok\n\n' }));
  await page.setViewportSize({ width: 1400, height: 900 });
  await page.goto('/');

  // build screen: click the developer's card
  await page.getByText('DEV_1', { exact: true }).first().click();
  const terminal = page.getByRole('log', { name: 'Live terminal: DEV_1' });
  await expect(terminal).toBeVisible();
  await expect(terminal).toContainText('$ pytest -q tests/test_timer_plugin.py');
  await expect(terminal).toContainText('! File not found: jarvis/core/protocols.py');
  await expect(page.getByText('% utilized')).toHaveCount(0);
  await page.screenshot({ path: 'e2e-live/screenshots/terminal-build.png' });

  // control plane: select the agent in the roster
  await page.getByRole('tab', { name: 'Control Plane' }).click();
  await page.getByText('DEV_1', { exact: true }).first().click();
  await expect(page.getByRole('log', { name: 'Live terminal: DEV_1' })).toContainText('exit 0');
  await page.screenshot({ path: 'e2e-live/screenshots/terminal-control-plane.png' });

  // the scrum master's terminal is the integrator's work
  await page.getByText('Scrum Master', { exact: true }).first().click();
  await expect(page.getByRole('log', { name: 'Live terminal: Scrum Master' })).toContainText('git merge --no-ff');
});
