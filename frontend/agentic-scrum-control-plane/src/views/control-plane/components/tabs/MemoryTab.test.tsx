import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { WorkspaceProvider } from '../../../../state/WorkspaceProvider';
import { WorkspaceShell } from '../../../../app/WorkspaceShell';
import { LiveFakeRepository, idleLiveWorkspace } from '../../../../test/liveRepository';
import type { MemoryApi, MemoryGraphData, MemoryHit, MemoryNode } from '../../../../domain/memory';

const WORKSPACE = 'workspace-live';
const node = (kind: string, name: string, extra: Partial<MemoryNode> = {}): MemoryNode => ({
  id: `${kind}:${name}`, kind, name, text: '', tags: [], owner: null, importance: 5, mentions: 1, created: 1000, updated: 2000, validFrom: 1000, validTo: null, supersededBy: null, degree: 1, ...extra,
});

const project: MemoryGraphData = {
  available: true, scope: 'project', agents: ['DEV_1', 'DEV_2'],
  overview: { project: { nodes: 4, edges: 3 }, agents: { DEV_1: { nodes: 2 }, DEV_2: { nodes: 1 } } },
  stats: { nodes: 4, edges: 3, replaced: 1 },
  nodes: [
    node('convention', 'inject time', { text: 'Never call time.monotonic(); take a Clock.', owner: 'DEV_1', importance: 8, tags: ['testing'] }),
    node('api', 'TimerRegistry', { text: 'next() returns the timer closest to expiry.', owner: 'DEV_2', importance: 7 }),
    node('file', 'jarvis/core/contracts.py', { text: 'defines Clock, FakeClock' }),
    node('convention', 'old limit', { text: 'At most 5 timers.', validTo: 3000, supersededBy: 'convention:inject time' }),
  ],
  edges: [
    { source: 'api:TimerRegistry', relation: 'depends_on', target: 'convention:inject time', weight: 1, note: '', owner: 'DEV_2', validTo: null },
    { source: 'convention:inject time', relation: 'about', target: 'file:jarvis/core/contracts.py', weight: 1, note: '', owner: 'DEV_1', validTo: null },
    { source: 'api:TimerRegistry', relation: 'imports', target: 'file:jarvis/core/contracts.py', weight: 1, note: '', owner: null, validTo: null },
  ],
};
const mine: MemoryGraphData = { ...project, scope: 'DEV_1', stats: { nodes: 1, edges: 0 }, nodes: [node('preference', 'my habit', { text: 'I write the test first.', owner: 'DEV_1' })], edges: [] };

function fakeMemory(search: MemoryHit[] = []): MemoryApi & { searches: unknown[][] } {
  const searches: unknown[][] = [];
  return {
    searches,
    graph: vi.fn(async (_workspace: string, scope: string) => (scope === 'project' ? project : mine)),
    search: vi.fn(async (...args: unknown[]) => { searches.push(args); return search; }),
  } as unknown as MemoryApi & { searches: unknown[][] };
}

function renderWithMemory(memory: MemoryApi | undefined) {
  const repository = new LiveFakeRepository({ ...idleLiveWorkspace(WORKSPACE), agents: [{ id: 'agent-sm', name: 'Scrum Master', role: 'Scrum Master', status: 'idle' }, { id: 'agent-01', name: 'DEV_1', role: 'Dev', status: 'idle' }] });
  Object.defineProperty(repository, 'memory', { value: memory });
  render(<WorkspaceProvider workspaceId={WORKSPACE} repository={repository}><WorkspaceShell /></WorkspaceProvider>);
}

async function openMemory() {
  fireEvent.click(await screen.findByRole('tab', { name: 'Control Plane' }));
  fireEvent.click(await screen.findByLabelText('Memory — Project & Agent Knowledge'));
}

describe('the Memory tab', () => {
  it('is only there with a real backend', async () => {
    renderWithMemory(undefined);
    fireEvent.click(await screen.findByRole('tab', { name: 'Control Plane' }));
    await screen.findByTitle('Inject an architectural challenge into the active meet');
    expect(screen.queryByLabelText('Memory — Project & Agent Knowledge')).not.toBeInTheDocument();
  });

  it('shows the project memory as a graph, with the scopes of every agent that has its own', async () => {
    renderWithMemory(fakeMemory());
    await openMemory();
    expect(await screen.findByLabelText('Memory graph')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'convention: inject time' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'api: TimerRegistry' })).toBeInTheDocument();
    const scopes = screen.getByRole('tablist', { name: 'Memory scope' });
    expect(within(scopes).getByRole('tab', { name: /Project \(shared\)/ })).toHaveAttribute('aria-selected', 'true');
    expect(within(scopes).getByRole('tab', { name: /DEV_1 \(own\)/ })).toBeInTheDocument();
    expect(within(scopes).getByRole('tab', { name: /DEV_2 \(own\)/ })).toBeInTheDocument();
  });

  it('shows what a memory says and what it is connected to, and follows a link', async () => {
    renderWithMemory(fakeMemory());
    await openMemory();
    fireEvent.click(await screen.findByRole('button', { name: 'api: TimerRegistry' }));
    const details = screen.getByLabelText('Memory details');
    expect(within(details).getByText('next() returns the timer closest to expiry.')).toBeInTheDocument();
    expect(within(details).getByText(/Connected to \(2\)/)).toBeInTheDocument();
    fireEvent.click(within(details).getByRole('button', { name: /inject time/ }));
    expect(within(screen.getByLabelText('Memory details')).getByText('Never call time.monotonic(); take a Clock.')).toBeInTheDocument();
  });

  it('shows an agent\'s own memory separately from the project memory', async () => {
    renderWithMemory(fakeMemory());
    await openMemory();
    fireEvent.click(await screen.findByRole('tab', { name: /DEV_1 \(own\)/ }));
    expect(await screen.findByRole('button', { name: 'preference: my habit' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'api: TimerRegistry' })).not.toBeInTheDocument();
    expect(screen.getByText(/Only DEV_1 reads it/)).toBeInTheDocument();
  });

  it('answers a question with ranked results and says why each one was found', async () => {
    const memory = fakeMemory([{
      ...node('convention', 'inject time', { text: 'Never call time.monotonic(); take a Clock.', importance: 8 }),
      score: 0.86, signals: { bm25: 1, dense: 2, cosine: 0.79, via: 'match', rerank: 1, importance: 8 },
    }]);
    renderWithMemory(memory);
    await openMemory();
    await screen.findByLabelText('Memory graph');
    fireEvent.change(screen.getByLabelText('Ask the memory'), { target: { value: 'how do we handle time in tests?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    expect(await screen.findByText('1 result')).toBeInTheDocument();
    const panel = screen.getByLabelText('Memory details');
    expect(within(panel).getByText('words #1')).toBeInTheDocument();
    expect(within(panel).getByText('meaning #2 (0.79)')).toBeInTheDocument();
    expect(within(panel).getByText('reranked #1')).toBeInTheDocument();
    expect(memory.searches[0]).toEqual([WORKSPACE, 'project', 'how do we handle time in tests?', true]);
    fireEvent.click(screen.getByRole('button', { name: 'Clear search' }));
    await waitFor(() => expect(screen.queryByText('1 result')).not.toBeInTheDocument());
  });

  it('marks a fact that is no longer true, and can hide whole kinds of memory', async () => {
    renderWithMemory(fakeMemory());
    await openMemory();
    fireEvent.click(await screen.findByRole('button', { name: 'convention: old limit' }));
    expect(within(screen.getByLabelText('Memory details')).getByText(/No longer true since/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { pressed: true, name: /^file/ }));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'file: jarvis/core/contracts.py' })).not.toBeInTheDocument());
  });

  it('says so before the team exists', async () => {
    renderWithMemory({ graph: async () => ({ ...project, available: false, nodes: [], edges: [], agents: [] }), search: async () => [] });
    await openMemory();
    expect(await screen.findByText(/appears as soon as the build starts/)).toBeInTheDocument();
  });
});
