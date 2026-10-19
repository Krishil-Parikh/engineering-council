import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import type { Agent, PhaseId, Skill, TranscriptMessage } from '../../types';
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
import { ToastCaption } from '../../components/common/ToastCaption';
import { useWorkspace } from '../../state/WorkspaceProvider';
import { readConfig } from '../../app/config';

const appConfig = readConfig();

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
  const { snapshot, executeCommand } = useWorkspace();

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

  const transcript: TranscriptMessage[] = useMemo(() => {
    const avatarBySender = new Map(snapshot.agents.map((agent) => [agent.id, agent.avatarColor ?? '#5B5B5B']));
    const roleBySender = new Map(snapshot.agents.map((agent) => [agent.id, agent.role]));
    return snapshot.messages.map((message): TranscriptMessage => ({
      id: message.id,
      speakerId: message.senderId,
      speakerName: message.senderName,
      speakerRole: roleBySender.get(message.senderId) ?? 'Workspace participant',
      avatarColor: avatarBySender.get(message.senderId) ?? '#5B5B5B',
      timestamp: message.timestamp,
      content: message.text,
      ...(message.id === SEED_SME_QUESTION_ID && message.meetId === GENUI_MEET_ID
        ? { isQuestionForSME: true, questionContext: SEED_SME_QUESTION_CONTEXT }
        : {}),
      ...(message.id === SEED_DEBATE_MESSAGE_ID && message.meetId === GENUI_MEET_ID ? { isDebate: true } : {}),
      ...(smeOverlay[message.id] ?? {}),
    }));
  }, [snapshot.messages, snapshot.agents, smeOverlay]);

  const prData = useMemo(() => snapshot.metrics.prHistory.map((entry) => ({ time: entry.time, prs: entry.prs })), [snapshot.metrics]);
  const totalPRs = snapshot.metrics.totalPRs;

  const advanceToPhase = useCallback((nextPhase: PhaseId, reasonToast: string) => {
    setToastMessage(reasonToast);
    void executeCommand({ type: 'phase.advance', workspaceId: appConfig.workspaceId, phaseId: nextPhase });
  }, [executeCommand]);

  const handleKickoffSubmit = (briefTitle: string, briefContent: string) => {
    setToastMessage(`Meet 01 started — Problem: ${briefTitle.slice(0, 32)}...`);
    void executeCommand({ type: 'sprint.start', workspaceId: appConfig.workspaceId, brief: briefContent });
    void executeCommand({
      type: 'message.create',
      workspaceId: appConfig.workspaceId,
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
    setSmeOverlay((prev) => ({ ...prev, [messageId]: { smeAnswered: true, smeResponse: decision } }));
    void executeCommand({
      type: 'sme.directive.submit',
      workspaceId: appConfig.workspaceId,
      meetId: 'meet-01',
      directive: decision,
    });
    timers.current.push(setTimeout(() => {
      void executeCommand({
        type: 'message.create',
        workspaceId: appConfig.workspaceId,
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
      void executeCommand({ type: 'prd.accept', workspaceId: appConfig.workspaceId, artifactId });
    }
    advanceToPhase('build', 'PRD accepted — Build phase has started');
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
    void executeCommand({ type: 'phase.advance', workspaceId: appConfig.workspaceId, phaseId: 'kickoff' });
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
      />
      <ToastCaption message={toastMessage} onDismiss={() => setToastMessage(null)} />
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
                <KickoffPhase agents={agents} onStartMeet={handleKickoffSubmit} />
              </motion.div>
            )}
            {viewingPhase === 'brainstorm' && (
              <motion.div key="brainstorm" initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.98 }} transition={{ duration: 0.24 }} className="w-full flex justify-center">
                <BrainstormPhase transcript={transcript} onSmeSubmitDecision={handleSmeSubmitDecision} onConcludeMeet={() => advanceToPhase('prd', 'Meet 01 concluded — Architecture compiled into PRD')} />
              </motion.div>
            )}
            {viewingPhase === 'prd' && (
              <motion.div key="prd" initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.98 }} transition={{ duration: 0.24 }} className="w-full flex justify-center">
                <PRDPhase agents={agents} onAcceptAllAndAdvance={handlePRDAccepted} />
              </motion.div>
            )}
            {viewingPhase === 'build' && (
              <motion.div key="build" initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.98 }} transition={{ duration: 0.24 }} className="w-full">
                <BuildPhase agents={agents} onFinishBuild={handleBuildFinished} />
              </motion.div>
            )}
            {viewingPhase === 'review' && (
              <motion.div key="review" initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.98 }} transition={{ duration: 0.24 }} className="w-full flex justify-center">
                <ReviewPhase agents={agents} onApproveAndShip={handleApproveAndShip} />
              </motion.div>
            )}
            {viewingPhase === 'ship' && (
              <motion.div key="ship" initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.98 }} transition={{ duration: 0.24 }} className="w-full flex justify-center">
                <ShipPhase onRestartSprint={handleRestartSprint} />
              </motion.div>
            )}
          </AnimatePresence>
        </main>
      </div>
      <RevealDrawer currentPhase={viewingPhase} agents={agents} skills={skills} transcript={transcript} prData={prData} totalPRs={totalPRs} />
      <SettingsModal isOpen={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} agents={agents} skills={skills} onAddAgent={handleAddAgent} onRemoveAgent={handleRemoveAgent} onAddSkill={handleAddSkill} />
    </div>
  );
}
