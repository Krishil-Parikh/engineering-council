import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { Agent, Artifact, Meet, Message, Sprint, TabType, DelegationEdge } from '../types';
import type { WorkspaceSnapshot } from '../../../domain/types';
import type { CommandResult, WorkspaceCommand } from '../../../domain/commands';
import type { MemoryApi } from '../../../domain/memory';
import type { WorkspaceAgent, WorkspaceMessage, WorkspaceMeet, WorkspaceArtifact, WorkspaceSprint, WorkspaceEdge, WorkspaceSkill } from '../../../domain/types';

interface ScrumContextType {
  activeTab: TabType;
  setActiveTab: (tab: TabType) => void;
  autopilot: boolean;
  setAutopilot: (val: boolean) => void;
  agents: Agent[];
  activeAgent: Agent;
  selectedAgent: Agent | null;
  setSelectedAgent: (agent: Agent | null) => void;
  meets: Meet[];
  selectedMeet: Meet;
  setSelectedMeetId: (id: string) => void;
  messages: Message[];
  artifacts: Artifact[];
  selectedArtifact: Artifact;
  setSelectedArtifactId: (id: string) => void;
  sprints: Sprint[];
  selectedSprint: Sprint;
  setSelectedSprintId: (id: string) => void;
  edges: DelegationEdge[];
  skills: WorkspaceSkill[];
  isSimulating: boolean;
  toggleSimulation: () => void;
  stepSimulation: () => void;
  /** A real backend is attached: the demo loop and the canned debate text are not offered. */
  live: boolean;
  /** The team's memory (a real backend only) and the workspace it belongs to. */
  memoryApi?: MemoryApi;
  workspaceKey: string;
  triggerDebate: () => void;
  triggerSmeIntervention: (directive: string) => void;
  isSmeModalOpen: boolean;
  setIsSmeModalOpen: (open: boolean) => void;
  elapsedSeconds: number;
  remainingSeconds: number;
  formatTime: (sec: number) => string;
  totalMessagesToday: number;
  activeAgentsCount: number;
  prdAcceptanceRatio: string;
  forceConsensus: () => void;
  reassignTask: (agentId: string, task: string) => void;
  /** What the real team is doing, for the header, the strip and the overview. Empty/zero with no backend. */
  phaseId: string;
  projectName: string;
  sprintLabel: string;
  totalPRs: number;
  documentsAccepted: { accepted: number; total: number };
  /** The ceremonies (planning, standups, review, report, retrospective) and documents of one sprint. */
  sprintMeets: (sprint: Sprint) => Meet[];
  sprintDocuments: (sprint: Sprint) => Artifact[];
}

export const PHASE_LABEL: Record<string, string> = {
  kickoff: 'Kickoff', brainstorm: 'Pod meeting', prd: 'Document review', build: 'Build', review: 'Verification', ship: 'Finished',
};

const CORE_DOCUMENTS = ['art-prd', 'art-tech', 'art-design'];
const sprintKey = (id: string) => {
  const match = /^(?:sprint-)?(r\d+-)?(?:s)?(\d+)/.exec(id);
  return match ? `${match[1] ?? ''}${Number(match[2])}` : '';
};

const ScrumContext = createContext<ScrumContextType | undefined>(undefined);

const DEFAULT_SPARKLINE = [22, 38, 55, 60, 48, 65, 78, 85, 92, 70];

function inferRole(roleTitle: string, id: string): Agent['role'] {
  const haystack = `${roleTitle} ${id}`.toLowerCase();
  if (haystack.includes('scrum') || id === 'agent-sm') return 'scrum_master';
  if (haystack.includes('frontend')) return 'frontend';
  if (haystack.includes('database') || haystack.includes('storage')) return 'database';
  if (haystack.includes('qa') || haystack.includes('chaos')) return 'qa';
  if (haystack.includes('sme')) return 'sme';
  if (haystack.includes('devops')) return 'devops';
  return 'backend';
}

function toRichAgent(item: WorkspaceAgent, live = false): Agent {
  const role = inferRole(item.role, item.id);
  const isLive = item.status === 'speaking';
  const status: Agent['status'] = item.status === 'blocked'
    ? 'evaluating'
    : item.status === 'complete' || item.status === 'idle'
      ? 'idle'
      : item.status === 'active'
        ? 'orchestrating'
        : 'speaking';
  return {
    id: item.id,
    name: item.name,
    role,
    roleTitle: item.role,
    status,
    isLive,
    avatarNumber: item.id.replace('agent-', '').replace('agent', '').slice(0, 2) || 'SM',
    activeTask: item.activeTask ?? 'Awaiting assignment',
    // The backend reports none of the telemetry below, so a real team shows none of it rather than invented numbers.
    sparkline: live ? [] : DEFAULT_SPARKLINE,
    contextTokens: live ? 0 : 80000,
    tokensVelocity: live ? 0 : 900,
    model: live ? '' : 'gemini-2.5-flash',
    skills: item.claimedSkill ? [item.claimedSkill] : [],
    allocatedMemory: live ? '' : '2.8 GB',
    confidenceScore: item.confidenceScore ?? (live ? 0 : 95),
    recentTools: [],
    activeBranch: item.activeBranch,
    terminal: item.terminal,
  };
}

function toRichMessage(item: WorkspaceMessage, roleOf: (id: string) => string | undefined = () => undefined): Message {
  return {
    id: item.id,
    meetId: item.meetId,
    senderId: item.senderId,
    senderName: item.senderName,
    senderRole: roleOf(item.senderId) ?? (item.senderId === 'sme-01' ? 'Business SME' : item.senderId === 'agent-sm' ? 'Scrum Master' : 'Developer'),
    timestamp: item.timestamp,
    timeOffsetSec: 0,
    text: item.text,
    type: item.senderId === 'sme-01' ? 'sme_input' : 'speech',
  };
}

function toRichMeet(item: WorkspaceMeet, live = false): Meet {
  return {
    id: item.id,
    number: item.id.replace('meet-', ''),
    sprintId: live ? '' : 'sprint-03',
    title: item.title,
    topic: item.title,
    status: item.status,
    elapsedTime: live ? '' : '14:32',
    remainingTime: live ? '' : '04:12',
    elapsedSec: live ? 0 : 872,
    remainingSec: live ? 0 : 252,
    participants: [],
    consensusRate: item.consensusRate,
    debateIntensity: item.debateIntensity,
    heatSegments: [],
    summary: '',
  };
}

function toRichArtifact(item: WorkspaceArtifact): Artifact {
  const type: Artifact['type'] = item.filename.toLowerCase().includes('arch')
    ? 'architecture'
    : item.filename.toLowerCase().includes('design')
      ? 'design'
      : 'prd';
  return {
    id: item.id,
    title: item.title,
    filename: item.filename,
    type,
    currentVersion: item.currentVersion,
    status: item.status,
    acceptedCount: item.acceptedCount,
    totalRequired: item.totalRequired,
    acceptedBy: [...(item.acceptedBy ?? [])],
    versions: (item.versions ?? []).map((version) => ({
      version: version.version,
      timestamp: version.timestamp,
      author: version.author,
      summary: version.summary,
      diffAdditions: [...version.diffAdditions],
      diffDeletions: [...version.diffDeletions],
      acceptedBy: [...version.acceptedBy],
    })),
    markdownContent: item.markdownContent ?? '',
  };
}

function toRichSprint(item: WorkspaceSprint): Sprint {
  return {
    id: item.id,
    number: item.number,
    title: item.title,
    goal: '',
    phase: item.phase,
    progress: item.progress,
    status: item.status,
    startDate: '',
    targetDate: '',
    meets: [],
    smeReviewPoints: [],
    standup: { yesterday: [], today: [], blockers: [] },
    retro: { wentWell: [], toImprove: [], actionItems: [] },
  };
}

function toRichEdge(item: WorkspaceEdge): DelegationEdge {
  return {
    id: item.id,
    source: item.source,
    target: item.target,
    label: item.label,
    isActive: item.isActive,
    latencyMs: item.latencyMs,
  };
}

const DEBATE_TEXT = 'CHALLENGE: Under asymmetric network partition, Raft node Geneva cannot distinguish between crash stop and link cut. How do we prevent stale reads without a synchronous heartbeat round-trip that violates the 20ms SLA?';

const EMPTY_MEET: Meet = {
  id: 'meet-empty',
  number: '—',
  sprintId: '',
  title: 'No meet selected',
  topic: 'Workspace is empty',
  status: 'scheduled',
  elapsedTime: '00:00',
  remainingTime: '00:00',
  elapsedSec: 0,
  remainingSec: 0,
  participants: [],
  consensusRate: 0,
  debateIntensity: 0,
  heatSegments: [],
  summary: 'No meet data is available for this workspace yet.',
};

const EMPTY_ARTIFACT: Artifact = {
  id: 'artifact-empty',
  title: 'No artifact',
  filename: 'empty.md',
  type: 'prd',
  currentVersion: 'v0.0',
  status: 'draft',
  acceptedCount: 0,
  totalRequired: 0,
  acceptedBy: [],
  versions: [],
  markdownContent: '',
};

const EMPTY_SPRINT: Sprint = {
  id: 'sprint-empty',
  number: '—',
  title: 'No sprint',
  goal: '',
  phase: '',
  progress: 0,
  status: 'active',
  startDate: '',
  targetDate: '',
  meets: [],
  smeReviewPoints: [],
  standup: { yesterday: [], today: [], blockers: [] },
  retro: { wentWell: [], toImprove: [], actionItems: [] },
};

const EMPTY_AGENT: Agent = {
  id: 'agent-empty',
  name: 'No agent',
  role: 'backend',
  roleTitle: 'No agent available',
  status: 'idle',
  isLive: false,
  avatarNumber: '—',
  activeTask: 'Workspace is empty',
  sparkline: DEFAULT_SPARKLINE,
  contextTokens: 0,
  tokensVelocity: 0,
  model: '',
  skills: [],
  allocatedMemory: '',
  confidenceScore: 0,
  recentTools: [],
};

const roleOfIn = (workspace: WorkspaceSnapshot) => {
  const roles = new Map(workspace.agents.map(agent => [agent.id, agent.role]));
  return (id: string) => roles.get(id);
};

export const ScrumProvider: React.FC<{ children: React.ReactNode; sharedWorkspace?: WorkspaceSnapshot; sharedExecuteCommand?: (command: WorkspaceCommand) => Promise<CommandResult>; live?: boolean; memoryApi?: MemoryApi }> = ({ children, sharedWorkspace, sharedExecuteCommand, live = false, memoryApi }) => {
  const [activeTab, setActiveTab] = useState<TabType>('overview');
  const [autopilot, setAutopilot] = useState<boolean>(false);
  const [agents, setAgents] = useState<Agent[]>(() => (sharedWorkspace ? sharedWorkspace.agents.map(item => toRichAgent(item, live)) : []));
  // The chosen agent is remembered by id and looked up on every render, so what it shows (its live terminal) keeps changing as the team works.
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const selectedAgent = agents.find(a => a.id === selectedAgentId) ?? null;
  const setSelectedAgent = useCallback((agent: Agent | null) => setSelectedAgentId(agent ? agent.id : null), []);
  const [meets, setMeets] = useState<Meet[]>(() => (sharedWorkspace ? sharedWorkspace.meets.map(item => toRichMeet(item, live)) : []));
  const [selectedMeetId, setSelectedMeetId] = useState<string>(live ? '' : 'meet-04');
  const [messages, setMessages] = useState<Message[]>(() => (sharedWorkspace ? sharedWorkspace.messages.map(item => toRichMessage(item, roleOfIn(sharedWorkspace))) : []));
  const [artifacts, setArtifacts] = useState<Artifact[]>(() => (sharedWorkspace ? sharedWorkspace.artifacts.map(toRichArtifact) : []));
  const [selectedArtifactId, setSelectedArtifactId] = useState<string>(live ? '' : 'art-01');
  const [sprints, setSprints] = useState<Sprint[]>(() => (sharedWorkspace ? sharedWorkspace.sprints.map(toRichSprint) : []));
  const [selectedSprintId, setSelectedSprintId] = useState<string>(live ? '' : 'sprint-03');
  const [edges, setEdges] = useState<DelegationEdge[]>(() => (sharedWorkspace ? sharedWorkspace.edges.map(toRichEdge) : []));
  const [skills, setSkills] = useState<WorkspaceSkill[]>(() => sharedWorkspace?.skills ?? []);
  const [isSimulating, setIsSimulating] = useState<boolean>(false);
  const [isSmeModalOpen, setIsSmeModalOpen] = useState<boolean>(false);
  const [elapsedSeconds, setElapsedSeconds] = useState<number>(live ? 0 : 872);
  const [remainingSeconds, setRemainingSeconds] = useState<number>(live ? 0 : 252);
  const workspaceId = sharedWorkspace?.workspaceId ?? 'workspace-demo';

  // With a real team, "nothing chosen" follows the action: the meeting that is happening, the sprint that is running.
  const defaultMeet = live ? meets.find(m => m.status === 'live') ?? meets[meets.length - 1] : meets[0];
  const defaultSprint = live ? sprints.find(s => s.status === 'active') ?? sprints[sprints.length - 1] : sprints[0];
  const selectedMeet = meets.find(m => m.id === selectedMeetId) || defaultMeet || EMPTY_MEET;
  const selectedArtifact = artifacts.find(a => a.id === selectedArtifactId) || artifacts[0] || EMPTY_ARTIFACT;
  const selectedSprint = sprints.find(s => s.id === selectedSprintId) || defaultSprint || EMPTY_SPRINT;
  const activeAgent = agents.find(a => a.isLive) || agents[0] || EMPTY_AGENT;

  useEffect(() => {
    if (agents.length > 0 && !agents.some(a => a.id === selectedAgentId)) {
      setSelectedAgentId(agents[0].id);
    } else if (agents.length === 0 && selectedAgentId !== null) {
      setSelectedAgentId(null);
    }
  }, [agents, selectedAgentId]);

  useEffect(() => {
    if (!sharedWorkspace) return;
    setAgents(prev => {
      const previous = new Map(prev.map(agent => [agent.id, agent]));
      return sharedWorkspace.agents.map(item => {
        const existing = previous.get(item.id);
        const rich = toRichAgent(item, live);
        return existing ? { ...existing, activeBranch: rich.activeBranch, terminal: rich.terminal, activeTask: rich.activeTask, confidenceScore: rich.confidenceScore, isLive: rich.isLive, status: rich.status, name: rich.name, roleTitle: rich.roleTitle } : rich;
      });
    });
    setMessages(prev => {
      const known = new Set(prev.map(message => message.id));
      const incoming = sharedWorkspace.messages.filter(item => !known.has(item.id)).map(item => toRichMessage(item, roleOfIn(sharedWorkspace)));
      const updated = prev.map(message => {
        const shared = sharedWorkspace.messages.find(item => item.id === message.id);
        return shared ? { ...message, text: shared.text, timestamp: shared.timestamp } : message;
      });
      return incoming.length ? [...updated, ...incoming] : updated;
    });
    setMeets(prev => {
      const previous = new Map(prev.map(meet => [meet.id, meet]));
      return sharedWorkspace.meets.map(item => {
        const existing = previous.get(item.id);
        const rich = toRichMeet(item, live);
        return existing ? { ...existing, consensusRate: rich.consensusRate, debateIntensity: rich.debateIntensity, status: rich.status, title: rich.title } : rich;
      });
    });
    setArtifacts(prev => {
      const previous = new Map(prev.map(artifact => [artifact.id, artifact]));
      return sharedWorkspace.artifacts.map(item => {
        const existing = previous.get(item.id);
        const rich = toRichArtifact(item);
        return existing ? { ...existing, status: rich.status, acceptedCount: rich.acceptedCount, totalRequired: rich.totalRequired, currentVersion: rich.currentVersion, versions: rich.versions, markdownContent: rich.markdownContent, acceptedBy: rich.acceptedBy } : rich;
      });
    });
    setSprints(prev => {
      const previous = new Map(prev.map(sprint => [sprint.id, sprint]));
      return sharedWorkspace.sprints.map(item => {
        const existing = previous.get(item.id);
        const rich = toRichSprint(item);
        return existing ? { ...existing, progress: rich.progress, status: rich.status, phase: rich.phase } : rich;
      });
    });
    setEdges(prev => {
      const previous = new Map(prev.map(edge => [edge.id, edge]));
      return sharedWorkspace.edges.map(item => {
        const existing = previous.get(item.id);
        const rich = toRichEdge(item);
        return existing ? { ...existing, isActive: rich.isActive, latencyMs: rich.latencyMs } : rich;
      });
    });
    setSkills(sharedWorkspace.skills);
  }, [sharedWorkspace]);

  const formatTime = (totalSec: number) => {
    const mins = Math.floor(Math.abs(totalSec) / 60);
    const secs = Math.abs(totalSec) % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  // Presentational clock only. Domain simulation lives in the centralized
  // workspace simulation adapter; this component never generates domain data.
  useEffect(() => {
    if (!isSimulating) return;
    const interval = setInterval(() => {
      setElapsedSeconds(prev => prev + 1);
      setRemainingSeconds(prev => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(interval);
  }, [isSimulating]);

  const manualStepIndex = useRef(0);
  const stepSimulation = useCallback(() => {
    manualStepIndex.current += 1;
    void sharedExecuteCommand?.({
      type: 'message.create',
      workspaceId,
      message: {
        meetId: selectedMeet.id,
        senderId: 'agent-03',
        senderName: 'Agent-03',
        text: `Manual simulation step ${manualStepIndex.current}: heartbeat verified, consensus holding.`,
        timestamp: new Date().toISOString().slice(11, 19),
      },
    });
  }, [selectedMeetId, sharedExecuteCommand, workspaceId]);

  const triggerDebate = () => {
    // The canned challenge is about the demo's own subject. With a real team the person writes the challenge themselves.
    if (live) {
      setIsSmeModalOpen(true);
      return;
    }
    void sharedExecuteCommand?.({ type: 'debate.inject', workspaceId, meetId: selectedMeetId, text: DEBATE_TEXT });
  };

  const triggerSmeIntervention = (directive: string) => {
    void sharedExecuteCommand?.({ type: 'sme.directive.submit', workspaceId, meetId: selectedMeet.id, directive });
  };

  const forceConsensus = () => {
    void sharedExecuteCommand?.({ type: 'consensus.force', workspaceId, meetId: selectedMeet.id });
  };

  const reassignTask = (agentId: string, task: string) => {
    void sharedExecuteCommand?.({ type: 'agent.task.reassign', workspaceId, agentId, task });
  };

  const totalMessagesToday = messages.length;
  const activeAgentsCount = agents.filter(a => a.status !== 'idle').length;
  const prdAcceptanceRatio = artifacts[0] ? `${artifacts[0].acceptedCount}/${artifacts[0].totalRequired}` : '0/0';

  const phaseId = sharedWorkspace?.phaseId ?? 'kickoff';
  const kickoffMeet = meets.find(m => m.title.startsWith('Kickoff meeting:'));
  const projectName = kickoffMeet ? kickoffMeet.title.replace(/^Kickoff meeting:\s*/, '') : '';
  const runningSprint = sprints.find(s => s.status === 'active') ?? sprints[sprints.length - 1];
  const sprintLabel = phaseId === 'build' && runningSprint ? `Sprint ${runningSprint.number}` : PHASE_LABEL[phaseId] ?? phaseId;
  const totalPRs = sharedWorkspace?.metrics.totalPRs ?? 0;
  const coreDocuments = artifacts.filter(a => CORE_DOCUMENTS.includes(a.id));
  const documentsAccepted = { accepted: coreDocuments.filter(a => a.status === 'approved').length, total: coreDocuments.length };
  const sprintMeets = (sprint: Sprint) => meets.filter(m => sprintKey(m.id) !== '' && sprintKey(m.id) === sprintKey(sprint.id));
  const sprintDocuments = (sprint: Sprint) => {
    const number = Number(sprintKey(sprint.id).replace(/^r\d+-/, ''));
    return artifacts.filter(a => Number(/sprint-(\d+)\//.exec(a.filename)?.[1] ?? -1) === number);
  };

  return (
    <ScrumContext.Provider
      value={{
        activeTab,
        setActiveTab,
        autopilot,
        setAutopilot,
        agents,
        activeAgent,
        selectedAgent,
        setSelectedAgent,
        meets,
        selectedMeet,
        setSelectedMeetId,
        messages,
        artifacts,
        selectedArtifact,
        setSelectedArtifactId,
        sprints,
        selectedSprint,
        setSelectedSprintId,
        edges,
        skills,
        isSimulating,
        toggleSimulation: () => setIsSimulating(!isSimulating),
        stepSimulation,
        live,
        memoryApi,
        workspaceKey: workspaceId,
        triggerDebate,
        triggerSmeIntervention,
        isSmeModalOpen,
        setIsSmeModalOpen,
        elapsedSeconds,
        remainingSeconds,
        formatTime,
        totalMessagesToday,
        activeAgentsCount,
        prdAcceptanceRatio,
        forceConsensus,
        reassignTask,
        phaseId,
        projectName,
        sprintLabel,
        totalPRs,
        documentsAccepted,
        sprintMeets,
        sprintDocuments
      }}
    >
      {children}
    </ScrumContext.Provider>
  );
};

export const useScrum = () => {
  const context = useContext(ScrumContext);
  if (!context) {
    throw new Error('useScrum must be used within a ScrumProvider');
  }
  return context;
};
