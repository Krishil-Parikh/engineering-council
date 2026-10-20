import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import type { Agent, ArtifactFile, PhaseId, Skill, TranscriptMessage } from '../../types';
import { TopBar } from '../../components/TopBar';
import { Spine } from '../../components/Spine';
import { KickoffPhase } from '../../components/phases/KickoffPhase';
import { BrainstormPhase } from '../../components/phases/BrainstormPhase';
import { PRDPhase } from '../../components/phases/PRDPhase';
import { BuildPhase } from '../../components/phases/BuildPhase';
import { ReviewPhase } from '../../components/phases/ReviewPhase';
import { ShipPhase } from '../../components/phases/ShipPhase';
import { RevealDrawer } from '../../components/drawer/RevealDrawer';
import { SettingsModal } from '../../components/settings/SettingsModal';
import { PRDReview } from '../../components/phases/PRDReview';
import { ReviewLive } from '../../components/phases/ReviewLive';
import { ShipLive } from '../../components/phases/ShipLive';
import { ToastCaption } from '../../components/common/ToastCaption';
import { useWorkspace } from '../../state/WorkspaceProvider';
import { selectAnswers, selectOpenQuestions } from '../../domain/selectors';
import { buildLiveGraph } from './liveGraph';

function toGenUIStatus(status: string): Agent['status'] {
  if (status === 'blocked') return 'blocked';
  if (status === 'complete') return 'complete';
  if (status === 'active' || status === 'speaking') return 'active';
  return 'idle';
}

/**
 * Demo-narrative flags that the canonical seed mapping drops (the shared
 * message model carries no UI-only fields) and this view restores for its
 * known seed messages. If the seed ids ever change, the GenUIView
 * SME-checkpoint test fails loudly instead of stranding the user with no
 * way to advance past brainstorm.
 */
const SEED_SME_QUESTION_ID = 'msg-06';
const SEED_SME_QUESTION_CONTEXT = 'Architecture Decision: Should we mandate Redis pub/sub with partitioned Postgres sessions for sub-50ms sync, or defer to SQLite/Local WAL for single-tenant airgap compliance?';
const SEED_DEBATE_MESSAGE_ID = 'msg-04';
// The demo seed reuses message ids across meets (pre-existing seed quirk),
// so flags are scoped to the GenUI meet to avoid tagging the twin.
const GENUI_MEET_ID = 'meet-01';

/**
 * GenUI view. All workspace data comes from the shared snapshot;
 * only navigation, overlays, and presentational flags stay local.
 */
export function GenUIView() {
  const { snapshot, executeCommand, live } = useWorkspace();
  const workspaceId = snapshot.workspaceId;

  const currentActivePhase = snapshot.phaseId as PhaseId;
  const [viewingPhase, setViewingPhase] = useState<PhaseId>(() => snapshot.phaseId as PhaseId);
  const [completedPhases, setCompletedPhases] = useState<PhaseId[]>([]);
  const [autoPlay, setAutoPlay] = useState<boolean>(true);
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(1);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [addedAgents, setAddedAgents] = useState<Agent[]>([]);
  const [removedAgentIds, setRemovedAgentIds] = useState<string[]>([]);
  const [addedSkills, setAddedSkills] = useState<Skill[]>([]);
  const [smeOverlay, setSmeOverlay] = useState<Record<string, { smeAnswered: boolean; smeResponse: string }>>({});
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const previousPhase = useRef<PhaseId>(currentActivePhase);

  useEffect(() => {
    if (previousPhase.current !== currentActivePhase) {
      setCompletedPhases((prev) => (prev.includes(previousPhase.current) ? prev : [...prev, previousPhase.current]));
      setViewingPhase(currentActivePhase);
      previousPhase.current = currentActivePhase;
    }
  }, [currentActivePhase]);

  useEffect(() => () => {
    timers.current.forEach((timer) => clearTimeout(timer));
  }, []);

  const agents: Agent[] = useMemo(() => {
    const removed = new Set(removedAgentIds);
    const base = snapshot.agents
      .filter((agent) => !removed.has(agent.id))
      .map((agent): Agent => ({
        id: agent.id,
        name: agent.name,
        role: agent.role,
        claimedSkill: agent.claimedSkill,
        status: toGenUIStatus(agent.status),
        currentTask: agent.activeTask,
        activeBranch: agent.activeBranch ?? 'main',
        contextUsagePercent: agent.contextUsagePercent ?? 0,
        avatarColor: agent.avatarColor ?? '#5B5B5B',
        terminal: agent.terminal,
      }));
    return [...base, ...addedAgents.filter((agent) => !removed.has(agent.id))];
  }, [snapshot.agents, addedAgents, removedAgentIds]);

  const skills: Skill[] = useMemo(() => [
    ...snapshot.skills.map((skill): Skill => ({
      id: skill.id,
      name: skill.name,
      instructions: skill.instructions ?? '',
      claimedCount: skill.claimedCount,
    })),
    ...addedSkills,
  ], [snapshot.skills, addedSkills]);

  const answers = useMemo(() => selectAnswers(snapshot), [snapshot]);
  const openQuestions = useMemo(() => selectOpenQuestions(snapshot), [snapshot]);
  const documentQuestion = openQuestions.find((message) => message.question?.kind === 'documents');

  const transcript: TranscriptMessage[] = useMemo(() => {
    const avatarBySender = new Map(snapshot.agents.map((agent) => [agent.id, agent.avatarColor ?? '#5B5B5B']));
    const roleBySender = new Map(snapshot.agents.map((agent) => [agent.id, agent.role]));
    // With a real backend the human's answers and the decision cards for documents and approvals are shown where they belong (the question card,
    // the document review, the decisions panel), not as lines in the meeting transcript.
    const shown = live
      ? snapshot.messages.filter((message) => message.kind !== 'answer' && !(message.question && message.question.kind !== 'meeting'))
      : snapshot.messages;
    return shown.map((message): TranscriptMessage => {
      const question = message.kind === 'question' ? message.question : undefined;
      const answer = question ? answers.get(question.id) : undefined;
      const flags = live
        ? question
          ? {
              isQuestionForSME: true,
              questionContext: message.text,
              questionDetail: question.context,
              questionId: question.id,
              questionOptions: question.options,
              questionRecommended: question.recommended,
              smeAnswered: answer !== undefined,
              smeResponse: answer ?? '',
            }
          : {}
        : {
            ...(message.id === SEED_SME_QUESTION_ID && message.meetId === GENUI_MEET_ID ? { isQuestionForSME: true, questionContext: SEED_SME_QUESTION_CONTEXT } : {}),
            ...(message.id === SEED_DEBATE_MESSAGE_ID && message.meetId === GENUI_MEET_ID ? { isDebate: true } : {}),
            ...(smeOverlay[message.id] ?? {}),
          };
      return {
        id: message.id,
        meetId: message.meetId,
        speakerId: message.senderId,
        speakerName: message.senderName,
        speakerRole: roleBySender.get(message.senderId) ?? 'Workspace participant',
        avatarColor: avatarBySender.get(message.senderId) ?? '#5B5B5B',
        timestamp: message.timestamp,
        content: message.text,
        ...flags,
      };
    });
  }, [snapshot.messages, snapshot.agents, smeOverlay, live, answers]);

  const documents = useMemo(() => snapshot.artifacts.filter((artifact) => ['art-prd', 'art-tech', 'art-design'].includes(artifact.id)), [snapshot.artifacts]);
  const artifactFiles: ArtifactFile[] | undefined = useMemo(
    () => (live ? snapshot.artifacts.filter((artifact) => artifact.markdownContent).map((artifact) => ({
      name: artifact.filename,
      size: `${(artifact.markdownContent ?? '').length.toLocaleString()} chars`,
      type: artifact.title,
      lastModified: artifact.currentVersion,
      content: artifact.markdownContent ?? '',
    })) : undefined),
    [live, snapshot.artifacts],
  );
  const liveGraph = useMemo(() => (live ? buildLiveGraph(agents, snapshot.edges) : undefined), [live, agents, snapshot.edges]);

  const prData = useMemo(() => snapshot.metrics.prHistory.map((entry) => ({ time: entry.time, prs: entry.prs })), [snapshot.metrics]);
  const totalPRs = snapshot.metrics.totalPRs;

  const advanceToPhase = useCallback((nextPhase: PhaseId, reasonToast: string) => {
    setToastMessage(reasonToast);
    void executeCommand({ type: 'phase.advance', workspaceId, phaseId: nextPhase });
  }, [executeCommand, workspaceId]);

  const handleKickoffSubmit = (briefTitle: string, briefContent: string, repo?: string, constraints?: string[]) => {
    if (live) {
      // The backend starts the meeting and narrates it; the screen follows the phase it reports.
      setToastMessage('The team is starting the kickoff meeting.');
      void executeCommand({ type: 'sprint.start', workspaceId, brief: briefContent, ...(briefTitle ? { title: briefTitle } : {}), ...(repo ? { repo } : {}), ...(constraints?.length ? { constraints } : {}) });
      return;
    }
    setToastMessage(`Meet 01 started — Problem: ${briefTitle.slice(0, 32)}...`);
    void executeCommand({ type: 'sprint.start', workspaceId, brief: briefContent });
    void executeCommand({
      type: 'message.create',
      workspaceId,
      message: {
        meetId: 'meet-01',
        senderId: 'scrum-master',
        senderName: 'Scrum Master',
        text: `SME mission ingested: "${briefContent}". Opening architecture brainstorm for 15m window.`,
        timestamp: new Date().toTimeString().slice(0, 8),
      },
    });
  };

  const handleSmeSubmitDecision = (messageId: string, decision: string) => {
    if (live) {
      const asked = transcript.find((message) => message.id === messageId);
      void executeCommand({
        type: 'sme.directive.submit', workspaceId, meetId: asked?.meetId ?? 'meet-01', directive: decision, ...(asked?.questionId ? { questionId: asked.questionId } : {}),
      });
      return;
    }
    setSmeOverlay((prev) => ({ ...prev, [messageId]: { smeAnswered: true, smeResponse: decision } }));
    void executeCommand({
      type: 'sme.directive.submit',
      workspaceId,
      meetId: 'meet-01',
      directive: decision,
    });
    timers.current.push(setTimeout(() => {
      void executeCommand({
        type: 'message.create',
        workspaceId,
        message: {
          meetId: 'meet-01',
          senderId: 'scrum-master',
          senderName: 'Scrum Master',
          text: `Directive logged. Synthesizing into PRD Section 2: "${decision}". Moving to peer review.`,
          timestamp: new Date().toTimeString().slice(0, 8),
        },
      });
      timers.current.push(setTimeout(() => {
        advanceToPhase('prd', 'Meet 01 concluded — Architecture compiled into PRD');
      }, 900));
    }, 450));
  };

  const handlePRDAccepted = () => {
    const artifactId = snapshot.artifacts[0]?.id;
    if (artifactId) {
      void executeCommand({ type: 'prd.accept', workspaceId, artifactId });
    }
    advanceToPhase('build', 'PRD accepted — Build phase has started');
  };

  const handleAcceptDocuments = (artifactId: string) => {
    setToastMessage('Documents accepted — the team starts building.');
    void executeCommand({ type: 'prd.accept', workspaceId, artifactId });
  };

  const handleRequestChanges = (feedback: string) => {
    if (!documentQuestion) return;
    setToastMessage('Your changes were sent to the scrum master.');
    void executeCommand({
      type: 'sme.directive.submit', workspaceId, meetId: documentQuestion.meetId, directive: `Decline: ${feedback}`, questionId: documentQuestion.question?.id,
    });
  };

  const handleBuildFinished = () => {
    advanceToPhase('review', 'All PRs passed hermetic tests — Advancing to Review');
  };

  const handleApproveAndShip = () => {
    advanceToPhase('ship', 'Release ratified — Sprint shipped to production');
  };

  const handleRestartSprint = () => {
    setCompletedPhases([]);
    setViewingPhase('kickoff');
    setToastMessage('New Sprint initialized — Awaiting mission brief');
    void executeCommand({ type: 'phase.advance', workspaceId, phaseId: 'kickoff' });
  };

  const handleSelectPhase = (phase: PhaseId) => {
    setViewingPhase(phase);
  };

  const handleReturnToLive = () => {
    setViewingPhase(currentActivePhase);
  };

  const handleAddAgent = () => {
    const nextNum = agents.length + 1;
    const padded = nextNum < 10 ? `0${nextNum}` : `${nextNum}`;
    setAddedAgents((prev) => [...prev, {
      id: `agent-${padded}-${Date.now()}`,
      name: `Agent-${padded}`,
      role: 'Developer Agent',
      claimedSkill: undefined,
      status: 'idle',
      currentTask: 'Bench standby — awaiting meet entry to claim skill',
      activeBranch: 'main',
      contextUsagePercent: 0,
      avatarColor: '#5B5B5B',
    }]);
  };

  const handleRemoveAgent = (agentId: string) => {
    setAddedAgents((prev) => prev.filter((a) => a.id !== agentId));
    setRemovedAgentIds((prev) => (prev.includes(agentId) ? prev : [...prev, agentId]));
  };

  const handleAddSkill = (name: string, instructions: string) => {
    setAddedSkills((prev) => [...prev, { id: `skill-${Date.now()}`, name, instructions, claimedCount: 0, isNew: true }]);
  };

  const isHistoricalView = viewingPhase !== currentActivePhase;

  // A run that ended early leaves the screen on the phase it reached. The gateway says so in a system message; show it, with a way out.
  const runStopped = (() => {
    if (!live || currentActivePhase === 'ship' || currentActivePhase === 'kickoff') return null;
    for (let index = snapshot.messages.length - 1; index >= 0; index -= 1) {
      const message = snapshot.messages[index];
      if (message.kind !== 'system') continue;
      if (/^Starting the pod meeting/.test(message.text)) return null;
      if (/^(The run stopped|The run was stopped|The documents were not accepted)/.test(message.text)) return message.text;
    }
    return null;
  })();

  return (
    <div className="min-h-screen bg-[#FCFCFB] text-[#161616] flex flex-col font-sans selection:bg-[#E60000]/15 selection:text-[#161616]">
      <TopBar
        currentPhase={viewingPhase}
        isLive={true}
        autoPlay={autoPlay}
        onToggleAutoPlay={() => setAutoPlay(!autoPlay)}
        playbackSpeed={playbackSpeed}
        onChangePlaybackSpeed={() => setPlaybackSpeed((s) => (s === 1 ? 2 : s === 2 ? 4 : 1))}
        onOpenSettings={() => setIsSettingsOpen(true)}
        live={live}
        projectName={snapshot.meets.find((meet) => meet.title.startsWith('Kickoff meeting:'))?.title.replace(/^Kickoff meeting:\s*/, '')}
      />
      <ToastCaption message={toastMessage} onDismiss={() => setToastMessage(null)} />
      {runStopped && (
        <div role="alert" className="mx-6 mt-3 p-3 rounded-xl border border-[#E60000]/40 bg-[#FDECEC] text-sm text-[#161616] flex items-center justify-between gap-4">
          <span><strong className="font-semibold">The run stopped.</strong> {runStopped.replace(/^The run stopped:\s*/, '')}</span>
          <button onClick={handleRestartSprint} className="shrink-0 px-3 py-1.5 rounded-lg bg-[#161616] text-[#FCFCFB] text-xs font-semibold hover:bg-[#2B2B2B]">Start a new project</button>
        </div>
      )}
      <div className="flex-1 flex w-full relative">
        <Spine
          currentActivePhase={currentActivePhase}
          viewingPhase={viewingPhase}
          completedPhases={completedPhases}
          onSelectPhase={handleSelectPhase}
          onReturnToLive={handleReturnToLive}
        />
        <main
          className={`flex-1 min-h-[calc(100vh-96px)] pb-14 transition-all duration-300 relative ${
            isHistoricalView ? 'opacity-85 filter contrast-95' : 'opacity-100'
          }`}
        >
          <AnimatePresence mode="wait" initial={false}>
            {viewingPhase === 'kickoff' && (
              <motion.div key="kickoff" initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.98 }} transition={{ duration: 0.24 }} className="w-full flex justify-center">
                <KickoffPhase agents={agents} onStartMeet={handleKickoffSubmit} live={live} />
              </motion.div>
            )}
            {viewingPhase === 'brainstorm' && (
              <motion.div key="brainstorm" initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.98 }} transition={{ duration: 0.24 }} className="w-full flex justify-center">
                <BrainstormPhase transcript={transcript} onSmeSubmitDecision={handleSmeSubmitDecision} onConcludeMeet={() => advanceToPhase('prd', 'Meet 01 concluded — Architecture compiled into PRD')} live={live} title={snapshot.meets.find((meet) => meet.id.endsWith('-01') && meet.title.startsWith('Kickoff'))?.title} />
              </motion.div>
            )}
            {viewingPhase === 'prd' && (
              <motion.div key="prd" initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.98 }} transition={{ duration: 0.24 }} className="w-full flex justify-center">
                {live
                  ? <PRDReview documents={documents} awaitingDecision={Boolean(documentQuestion)} onAccept={handleAcceptDocuments} onRequestChanges={handleRequestChanges} />
                  : <PRDPhase agents={agents} onAcceptAllAndAdvance={handlePRDAccepted} />}
              </motion.div>
            )}
            {viewingPhase === 'build' && (
              <motion.div key="build" initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.98 }} transition={{ duration: 0.24 }} className="w-full">
                <BuildPhase agents={agents} onFinishBuild={handleBuildFinished} live={live} graph={liveGraph} summary={`${snapshot.metrics.totalPRs} feature${snapshot.metrics.totalPRs === 1 ? '' : 's'} merged`} />
              </motion.div>
            )}
            {viewingPhase === 'review' && (
              <motion.div key="review" initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.98 }} transition={{ duration: 0.24 }} className="w-full flex justify-center">
                {live
                  ? <ReviewLive sprints={snapshot.sprints} artifacts={snapshot.artifacts} messages={snapshot.messages} />
                  : <ReviewPhase agents={agents} onApproveAndShip={handleApproveAndShip} />}
              </motion.div>
            )}
            {viewingPhase === 'ship' && (
              <motion.div key="ship" initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.98 }} transition={{ duration: 0.24 }} className="w-full flex justify-center">
                {live
                  ? <ShipLive artifacts={snapshot.artifacts} messages={snapshot.messages} totalMerged={snapshot.metrics.totalPRs} onStartNextSprint={handleRestartSprint} />
                  : <ShipPhase onRestartSprint={handleRestartSprint} />}
              </motion.div>
            )}
          </AnimatePresence>
        </main>
      </div>
      <RevealDrawer currentPhase={viewingPhase} agents={agents} skills={skills} transcript={transcript} prData={prData} totalPRs={totalPRs} artifacts={artifactFiles} live={live} sprints={snapshot.sprints} />
      <SettingsModal isOpen={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} agents={agents} skills={skills} onAddAgent={handleAddAgent} onRemoveAgent={handleRemoveAgent} onAddSkill={handleAddSkill} localOnly={live} />
    </div>
  );
}
