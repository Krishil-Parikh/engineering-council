import { describe, expect, it } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { WorkspaceProvider } from '../../state/WorkspaceProvider';
import { GenUIView } from './GenUIView';
import { buildLiveGraph } from './liveGraph';
import { LiveFakeRepository, idleLiveWorkspace } from '../../test/liveRepository';
import type { WorkspaceAgent, WorkspaceArtifact } from '../../domain/types';

const WORKSPACE = 'workspace-live';

function renderLive(repository = new LiveFakeRepository(idleLiveWorkspace(WORKSPACE))) {
  render(
    <WorkspaceProvider workspaceId={WORKSPACE} repository={repository}>
      <GenUIView />
    </WorkspaceProvider>,
  );
  return repository;
}

const developer = (n: number, extra: Partial<WorkspaceAgent> = {}): WorkspaceAgent => ({
  id: `agent-0${n}`, name: `DEV_${n}`, role: 'Backend Developer', status: 'idle', claimedSkill: 'Backend', avatarColor: '#E60000', ...extra,
});

const documents = (): WorkspaceArtifact[] => ['PRD.md', 'Technical_Approach.md', 'Design.md'].map((filename, index) => ({
  id: ['art-prd', 'art-tech', 'art-design'][index], title: ['Product Requirements', 'Technical Approach', 'Design'][index], filename, status: 'in_review' as const,
  currentVersion: 'v1.0', acceptedCount: 2, totalRequired: 7, acceptedBy: ['DEV_1', 'DEV_2'], markdownContent: `# ${filename}\n\nThe real text of ${filename}.`,
}));

describe('GenUIView with a real backend', () => {
  it('starts with an empty brief, no pretend attachments and no canned presets', async () => {
    renderLive();
    const brief = (await screen.findByLabelText('Project brief')) as HTMLTextAreaElement;
    expect(brief.value).toBe('');
    expect(screen.queryByText('prd_template_v3.md')).not.toBeInTheDocument();
    expect(screen.queryByText(/High-Throughput/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Start the meet/ })).toBeDisabled();
  });

  it('sends the brief and project name as one sprint.start and nothing else', async () => {
    const repository = renderLive();
    fireEvent.change(await screen.findByLabelText('Project name'), { target: { value: 'Habitly' } });
    fireEvent.change(screen.getByLabelText('Project brief'), { target: { value: 'A habit tracker with a CLI.' } });
    fireEvent.click(screen.getByRole('button', { name: /Start the meet/ }));
    await waitFor(() => expect(repository.commandsOfType('sprint.start')).toHaveLength(1));
    expect(repository.commands).toEqual([{ type: 'sprint.start', workspaceId: WORKSPACE, brief: 'A habit tracker with a CLI.', title: 'Habitly' }]);
  });

  it('sends the GitHub repository when one is given, so the result is published there', async () => {
    const repository = renderLive();
    fireEvent.change(await screen.findByLabelText('GitHub repository'), { target: { value: ' https://github.com/me/habitly ' } });
    fireEvent.change(screen.getByLabelText('Project brief'), { target: { value: 'A habit tracker.' } });
    fireEvent.click(screen.getByRole('button', { name: /Start the meet/ }));
    await waitFor(() => expect(repository.commandsOfType('sprint.start')).toHaveLength(1));
    expect(repository.commands[0]).toMatchObject({ type: 'sprint.start', brief: 'A habit tracker.', repo: 'https://github.com/me/habitly' });
  });

  it('sends constraints one per line and loads a problem file into the brief', async () => {
    const repository = renderLive();
    const file = new File(['# Habit tracker\nTrack daily habits.'], 'problem.md', { type: 'text/markdown' });
    fireEvent.change(await screen.findByLabelText('Problem file'), { target: { files: [file] } });
    await waitFor(() => expect((screen.getByLabelText('Project brief') as HTMLTextAreaElement).value).toContain('Track daily habits.'));
    expect(screen.getByText(/Loaded problem.md/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Constraints'), { target: { value: 'Python only\n\n no network ' } });
    fireEvent.click(screen.getByRole('button', { name: /Start the meet/ }));
    await waitFor(() => expect(repository.commandsOfType('sprint.start')).toHaveLength(1));
    expect(repository.commands[0]).toMatchObject({ type: 'sprint.start', constraints: ['Python only', 'no network'] });
  });

  it('shows the meeting question with its own options and answers it by id', async () => {
    const repository = renderLive();
    await screen.findByLabelText('Project brief');
    repository.phase('brainstorm');
    repository.message({
      id: 'm-q1', kind: 'question', text: 'Question 1 of 1: Should tasks sync across devices?',
      question: { id: 'q-1', kind: 'meeting', context: 'Why it matters: changes the scope', options: ['Yes', 'No'], recommended: 'No' },
    });
    expect(await screen.findByText('Question 1 of 1: Should tasks sync across devices?')).toBeInTheDocument();
    expect(screen.queryByText(/Option A: Mandate Redis/)).not.toBeInTheDocument(); // the demo's canned choices are gone
    expect(screen.queryByText(/Conclude Meet/)).not.toBeInTheDocument(); // the meeting ends itself
    fireEvent.click(await screen.findByText(/^No\s+\(recommended\)/));
    await waitFor(() => expect(repository.commandsOfType('sme.directive.submit')).toHaveLength(1));
    expect(repository.commands[0]).toMatchObject({ type: 'sme.directive.submit', directive: 'No', questionId: 'q-1', meetId: 'meet-01' });
    expect(repository.commands).toHaveLength(1); // no scripted follow-up messages, no phase.advance
    act(() => repository.message({ id: 'm-a1', kind: 'answer', answersQuestion: 'q-1', text: 'No', senderId: 'sme-01', senderName: 'SME-01' }));
    expect(await screen.findByText(/Decision ratified by Business SME/)).toBeInTheDocument();
  });

  it('shows the real documents and waits for you: nothing is accepted on a timer', async () => {
    const repository = renderLive();
    await screen.findByLabelText('Project brief');
    act(() => {
      repository.phase('prd');
      for (const doc of documents()) repository.push('artifact.updated', doc);
      repository.message({
        id: 'm-docs', kind: 'question', text: 'Accept the project documents?', meetId: 'meet-prd',
        question: { id: 'APP-001', kind: 'documents', context: 'Read these', options: ['Approve', 'Decline'] },
      });
    });
    expect(await screen.findByText(/The real text of PRD.md/)).toBeInTheDocument();
    expect(screen.getByText('Waiting for your decision')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: /Design.md/ }));
    expect(screen.getByTestId('document-text').textContent).toContain('The real text of Design.md');
    await new Promise((resolve) => setTimeout(resolve, 4500)); // the demo screen used to sign everything off after about 4 seconds
    expect(repository.commands).toEqual([]);
  }, 10000);

  it('accepts the documents with prd.accept, and sends change requests back with the question id', async () => {
    const repository = renderLive();
    await screen.findByLabelText('Project brief');
    act(() => {
      repository.phase('prd');
      for (const doc of documents()) repository.push('artifact.updated', doc);
      repository.message({
        id: 'm-docs', kind: 'question', text: 'Accept the project documents?', meetId: 'meet-prd',
        question: { id: 'APP-001', kind: 'documents', context: 'Read these' },
      });
    });
    fireEvent.click(await screen.findByRole('button', { name: /Request changes/ }));
    fireEvent.change(screen.getByLabelText('What should change?'), { target: { value: 'add offline support' } });
    fireEvent.click(screen.getByRole('button', { name: /Send changes to the team/ }));
    await waitFor(() => expect(repository.commands).toHaveLength(1));
    expect(repository.commands[0]).toMatchObject({ type: 'sme.directive.submit', directive: 'Decline: add offline support', questionId: 'APP-001', meetId: 'meet-prd' });
    fireEvent.click(screen.getByRole('button', { name: /Accept all documents and start building/ }));
    await waitFor(() => expect(repository.commandsOfType('prd.accept')).toHaveLength(1));
    expect(repository.commandsOfType('phase.advance')).toHaveLength(0); // the backend moves the phase when the team really starts
  });

  it('draws the build from the team that exists, not from demo agents', async () => {
    const repository = renderLive();
    await screen.findByLabelText('Project brief');
    act(() => {
      repository.agent(developer(1, { status: 'active', activeTask: 'database-module: schema', activeBranch: 'feature/database-module' }));
      repository.agent(developer(2));
      repository.phase('build');
    });
    expect((await screen.findAllByText(/0 features? merged/)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/Spine timeline navigation/)).not.toBeInTheDocument();
    expect(screen.queryByText(/38 commits synced to main/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Advance to Review/)).not.toBeInTheDocument();
    expect(await screen.findByText('1 of 2 working')).toBeInTheDocument();
  });

  it('opens the live terminal of an agent from its card on the build screen', async () => {
    const repository = renderLive();
    await screen.findByLabelText('Project brief');
    act(() => {
      repository.agent(developer(1, { status: 'active', activeTask: 'storage: write the JSON file', activeBranch: 'feature/storage', terminal: ['10:00:01 $ git status', '10:00:03   exit 0'] }));
      repository.phase('build');
    });
    fireEvent.click(await screen.findByText('DEV_1'));
    const terminal = await screen.findByRole('log', { name: 'Live terminal: DEV_1' });
    expect(terminal).toHaveTextContent('$ git status');
    expect(screen.queryByText(/% utilized/)).not.toBeInTheDocument(); // the backend reports no such figure
    act(() => repository.agent(developer(1, { status: 'active', terminal: ['10:00:01 $ git status', '10:00:03   exit 0', '10:00:09 $ pytest -q'] })));
    await waitFor(() => expect(screen.getByRole('log', { name: 'Live terminal: DEV_1' })).toHaveTextContent('$ pytest -q'));
  });

  it('ends on a page about the real result and starts a new project with phase.advance kickoff', async () => {
    const repository = renderLive();
    await screen.findByLabelText('Project brief');
    act(() => {
      repository.push('artifact.updated', { ...documents()[0], id: 'art-team-report', title: 'Team report', filename: 'team_report.md', status: 'approved' });
      repository.message({ id: 'm-done', kind: 'system', text: 'Done: 6/6 features merged; verification passed. Review final/20261019-1; nothing was merged into main.' });
      repository.message({ id: 'm-final', kind: 'system', text: 'The final branch final/20261019-1 is ready for you to review. Nothing has been merged into main.' });
      repository.phase('ship');
    });
    act(() => repository.message({ id: 'm-push', kind: 'system', text: 'Pushed final/20261019-1, integration/20261019-1, feature/db to https://github.com/me/habitly' }));
    expect(await screen.findByText('The team has finished')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Pushed final/20261019-1, integration/20261019-1, feature/db to https://github.com/me/habitly');
    expect(screen.getByText('final/20261019-1')).toBeInTheDocument();
    expect(screen.getByText(/6\/6 features merged/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Start a new project/ }));
    await waitFor(() => expect(repository.commands).toHaveLength(1));
    expect(repository.commands[0]).toMatchObject({ type: 'phase.advance', phaseId: 'kickoff' });
  });

  it('says when the run stopped early and offers a new project', async () => {
    const repository = renderLive();
    await screen.findByLabelText('Project brief');
    act(() => {
      repository.phase('brainstorm');
      repository.message({ id: 'm-start', kind: 'system', text: 'Starting the pod meeting for "Habitly".' });
      repository.message({ id: 'm-stop', kind: 'system', text: 'The run stopped: Could not clone https://github.com/me/nothing: Repository not found' });
    });
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Could not clone https://github.com/me/nothing');
    fireEvent.click(screen.getByRole('button', { name: /Start a new project/ }));
    await waitFor(() => expect(repository.commandsOfType('phase.advance')).toHaveLength(1));
    expect(repository.commands[0]).toMatchObject({ type: 'phase.advance', phaseId: 'kickoff' });
  });

  it('says the team cannot be edited from the settings screen', async () => {
    renderLive();
    fireEvent.click(await screen.findByLabelText(/settings/i));
    expect(await screen.findByText(/Changes made here affect only this screen/)).toBeInTheDocument();
  });
});

describe('buildLiveGraph', () => {
  const agents = [
    { id: 'agent-sm', name: 'Scrum Master', role: 'Scrum Master', claimedSkill: undefined, status: 'idle' as const, currentTask: undefined, activeBranch: undefined, contextUsagePercent: 0, avatarColor: '#000' },
    ...[1, 2, 3, 4, 5].map((n) => ({ id: `agent-0${n}`, name: `DEV_${n}`, role: 'Dev', claimedSkill: 'Backend', status: 'active' as const, currentTask: `task ${n}`, activeBranch: `feature/f${n}`, contextUsagePercent: 0, avatarColor: '#000' })),
  ];

  it('places the scrum master on top and the developers in rows of four', () => {
    const { nodes } = buildLiveGraph(agents, []);
    expect(nodes.map((n) => n.id)).toEqual(['scrum-master', 'agent-01', 'agent-02', 'agent-03', 'agent-04', 'agent-05']);
    const rows = new Set(nodes.filter((n) => n.id.startsWith('agent-0')).map((n) => n.position.y));
    expect(rows.size).toBe(2);
    expect(nodes.find((n) => n.id === 'agent-01')?.data).toMatchObject({ name: 'DEV_1', skill: 'Backend', task: 'task 1', branch: 'feature/f1' });
  });

  it('maps the backend scrum master id to the graph node and drops edges to unknown agents', () => {
    const { edges } = buildLiveGraph(agents, [
      { id: 'e1', source: 'agent-sm', target: 'agent-01', label: 'Owns db', isActive: true, latencyMs: 0 },
      { id: 'e2', source: 'agent-sm', target: 'agent-09', label: 'ghost', isActive: true, latencyMs: 0 },
      { id: 'e3', source: 'agent-01', target: 'agent-02', isActive: false, latencyMs: 0 },
    ]);
    expect(edges.map((e) => [e.source, e.target, e.animated])).toEqual([['scrum-master', 'agent-01', true], ['agent-01', 'agent-02', false]]);
  });
});
