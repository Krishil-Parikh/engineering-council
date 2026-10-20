import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test } from '@playwright/test';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** The Memory tab with a realistic memory (extracted by the real model from a team's work, plus this repository's own code structure). The gateway's answers are replaced. */
const fixtures = path.join(__dirname, 'fixtures');
const project = JSON.parse(fs.readFileSync(path.join(fixtures, 'memory-project.json'), 'utf-8'));
const agents: Record<string, unknown> = JSON.parse(fs.readFileSync(path.join(fixtures, 'memory-agents.json'), 'utf-8'));

const snapshot = {
  workspaceId: 'workspace-demo', version: 10, phaseId: 'build',
  agents: [
    { id: 'agent-sm', name: 'Scrum Master', role: 'Scrum Master', status: 'active' },
    { id: 'sme-01', name: 'SME-01', role: 'Business SME (you)', status: 'idle' },
    { id: 'agent-01', name: 'DEV_1', role: 'Backend Developer', status: 'active', claimedSkill: 'Backend', activeTask: 'core-contracts: write the Clock' },
  ],
  messages: [], skills: [], artifacts: [],
  meets: [{ id: 'meet-kickoff', title: 'Kickoff meeting: Jarvis Timers', status: 'completed', consensusRate: 80, debateIntensity: 20 }],
  sprints: [], edges: [], metrics: { totalMessagesToday: 0, totalPRs: 2, prHistory: [] }, processedEventIds: [],
};

test('the memory tab shows the project graph, each agent\'s own, and a search that explains itself', async ({ page }) => {
  await page.route('**/workspace/workspace-demo/snapshot', (route) => route.fulfill({ json: snapshot }));
  await page.route('**/workspace/workspace-demo/events', (route) => route.fulfill({ status: 200, contentType: 'text/event-stream', body: ': ok\n\n' }));
  await page.route('**/workspace/workspace-demo/memory?**', (route) => {
    const scope = new URL(route.request().url()).searchParams.get('scope') ?? 'project';
    return route.fulfill({ json: scope === 'project' ? project : (agents[scope] ?? { ...project, scope, nodes: [], edges: [], stats: {} }) });
  });
  await page.route('**/workspace/workspace-demo/memory/search**', (route) => route.fulfill({
    json: {
      query: 'x', scope: 'project',
      hits: [
        { ...project.nodes.find((n: { name: string }) => n.name.startsWith('Clock')) ?? project.nodes[0], score: 0.86, signals: { bm25: 1, dense: 1, cosine: 0.79, graph: 0.58, recency: 1, importance: 8, via: 'match', rerank: 1 } },
        { ...project.nodes.find((n: { kind: string }) => n.kind === 'insight') ?? project.nodes[1], score: 0.61, signals: { bm25: 3, dense: 2, cosine: 0.7, graph: 0.9, via: 'link', rerank: 2, importance: 8 } },
      ],
    },
  }));
  await page.setViewportSize({ width: 1500, height: 900 });
  await page.goto('/');
  await page.getByRole('tab', { name: 'Control Plane' }).click();
  await page.getByLabel('Memory — Project & Agent Knowledge').click();

  await expect(page.getByLabel('Memory graph')).toBeVisible();
  await expect(page.getByRole('tablist', { name: 'Memory scope' })).toContainText('Project (shared)');
  await expect(page.getByRole('tablist', { name: 'Memory scope' })).toContainText('DEV_1 (own)');
  await page.waitForTimeout(800);
  await page.screenshot({ path: 'e2e-live/screenshots/memory-project.png' });

  // a memory and how it connects
  const decision = page.getByRole('button', { name: /^decision:/ }).first();
  await decision.click();
  await expect(page.getByLabel('Memory details')).toContainText('Connected to');
  await page.screenshot({ path: 'e2e-live/screenshots/memory-detail.png' });

  // ask the memory
  await page.getByLabel('Ask the memory').fill('how do I handle time in my code so my tests do not need to wait?');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.getByLabel('Memory details')).toContainText('2 results');
  await expect(page.getByLabel('Memory details')).toContainText('meaning #1');
  await page.screenshot({ path: 'e2e-live/screenshots/memory-search.png' });
  await page.getByRole('button', { name: 'Clear search' }).click();

  // an agent's own memory, and the list view
  await page.getByRole('tab', { name: /DEV_1 \(own\)/ }).click();
  await expect(page.getByLabel('Memory details')).toContainText('Only DEV_1 reads it');
  await page.screenshot({ path: 'e2e-live/screenshots/memory-agent.png' });
  await page.getByRole('tab', { name: /Project \(shared\)/ }).click();
  await page.getByLabel('List view').click();
  await expect(page.getByRole('table')).toBeVisible();
  await page.screenshot({ path: 'e2e-live/screenshots/memory-list.png' });
});
