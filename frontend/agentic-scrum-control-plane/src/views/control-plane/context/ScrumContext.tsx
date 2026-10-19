import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { Agent, Artifact, Meet, Message, Sprint, TabType, DelegationEdge } from '../types';
import type { WorkspaceSnapshot } from '../../../domain/types';
import type { CommandResult, WorkspaceCommand } from '../../../domain/commands';
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
}

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

function toRichAgent(item: WorkspaceAgent): Agent {
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
    sparkline: DEFAULT_SPARKLINE,
    contextTokens: 80000,
    tokensVelocity: 900,
    model: 'gemini-2.5-flash',
    skills: item.claimedSkill ? [item.claimedSkill] : [],
    allocatedMemory: '2.8 GB',
    confidenceScore: item.confidenceScore ?? 95,
    recentTools: [],
  };
}

function toRichMessage(item: WorkspaceMessage): Message {
  return {
    id: item.id,
    meetId: item.meetId,
    senderId: item.senderId,
    senderName: item.senderName,
    senderRole: item.senderId === 'sme-01' ? 'Business SME' : item.senderId === 'agent-sm' ? 'Scrum Master' : 'Developer',
    timestamp: item.timestamp,
    timeOffsetSec: 0,
    text: item.text,
    type: item.senderId === 'sme-01' ? 'sme_input' : 'speech',
  };
}

function toRichMeet(item: WorkspaceMeet): Meet {
  return {
    id: item.id,
    number: item.id.replace('meet-', ''),
    sprintId: 'sprint-03',
    title: item.title,
    topic: item.title,
    status: item.status,
    elapsedTime: '14:32',
    remainingTime: '04:12',
    elapsedSec: 872,
    remainingSec: 252,
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

export const ScrumProvider: React.FC<{ children: React.ReactNode; sharedWorkspace?: WorkspaceSnapshot; sharedExecuteCommand?: (command: WorkspaceCommand) => Promise<CommandResult> }> = ({ children, sharedWorkspace, sharedExecuteCommand }) => {
  const [activeTab, setActiveTab] = useState<TabType>('overview');
  const [autopilot, setAutopilot] = useState<boolean>(false);
  const [agents, setAgents] = useState<Agent[]>(() => (sharedWorkspace ? sharedWorkspace.agents.map(toRichAgent) : []));
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [meets, setMeets] = useState<Meet[]>(() => (sharedWorkspace ? sharedWorkspace.meets.map(toRichMeet) : []));
  const [selectedMeetId, setSelectedMeetId] = useState<string>('meet-04');
  const [messages, setMessages] = useState<Message[]>(() => (sharedWorkspace ? sharedWorkspace.messages.map(toRichMessage) : []));
  const [artifacts, setArtifacts] = useState<Artifact[]>(() => (sharedWorkspace ? sharedWorkspace.artifacts.map(toRichArtifact) : []));
  const [selectedArtifactId, setSelectedArtifactId] = useState<string>('art-01');
  const [sprints, setSprints] = useState<Sprint[]>(() => (sharedWorkspace ? sharedWorkspace.sprints.map(toRichSprint) : []));
  const [selectedSprintId, setSelectedSprintId] = useState<string>('sprint-03');
  const [edges, setEdges] = useState<DelegationEdge[]>(() => (sharedWorkspace ? sharedWorkspace.edges.map(toRichEdge) : []));
  const [skills, setSkills] = useState<WorkspaceSkill[]>(() => sharedWorkspace?.skills ?? []);
  const [isSimulating, setIsSimulating] = useState<boolean>(false);
  const [isSmeModalOpen, setIsSmeModalOpen] = useState<boolean>(false);
  const [elapsedSeconds, setElapsedSeconds] = useState<number>(872);
  const [remainingSeconds, setRemainingSeconds] = useState<number>(252);
  const workspaceId = sharedWorkspace?.workspaceId ?? 'workspace-demo';

  const selectedMeet = meets.find(m => m.id === selectedMeetId) || meets[0] || EMPTY_MEET;
  const selectedArtifact = artifacts.find(a => a.id === selectedArtifactId) || artifacts[0] || EMPTY_ARTIFACT;
  const selectedSprint = sprints.find(s => s.id === selectedSprintId) || sprints[0] || EMPTY_SPRINT;
  const activeAgent = agents.find(a => a.isLive) || agents[0] || EMPTY_AGENT;

  useEffect(() => {
    if (!selectedAgent && agents.length > 0) {
      setSelectedAgent(agents[0]);
    } else if (selectedAgent && !agents.some(a => a.id === selectedAgent.id)) {
      setSelectedAgent(agents[0] ?? null);
    }
  }, [agents, selectedAgent]);

  useEffect(() => {
    if (!sharedWorkspace) return;
    setAgents(prev => {
      const previous = new Map(prev.map(agent => [agent.id, agent]));
      return sharedWorkspace.agents.map(item => {
        const existing = previous.get(item.id);
        const rich = toRichAgent(item);
        return existing ? { ...existing, activeTask: rich.activeTask, confidenceScore: rich.confidenceScore, isLive: rich.isLive, status: rich.status, name: rich.name, roleTitle: rich.roleTitle } : rich;
      });
    });
    setMessages(prev => {
      const known = new Set(prev.map(message => message.id));
      const incoming = sharedWorkspace.messages.filter(item => !known.has(item.id)).map(toRichMessage);
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
        const rich = toRichMeet(item);
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
        meetId: selectedMeetId,
        senderId: 'agent-03',
        senderName: 'Agent-03',
        text: `Manual simulation step ${manualStepIndex.current}: heartbeat verified, consensus holding.`,
        timestamp: new Date().toISOString().slice(11, 19),
      },
    });
  }, [selectedMeetId, sharedExecuteCommand, workspaceId]);

  const triggerDebate = () => {
    void sharedExecuteCommand?.({ type: 'debate.inject', workspaceId, meetId: selectedMeetId, text: DEBATE_TEXT });
  };

  const triggerSmeIntervention = (directive: string) => {
    void sharedExecuteCommand?.({ type: 'sme.directive.submit', workspaceId, meetId: selectedMeetId, directive });
  };

  const forceConsensus = () => {
    void sharedExecuteCommand?.({ type: 'consensus.force', workspaceId, meetId: selectedMeetId });
  };

  const reassignTask = (agentId: string, task: string) => {
    void sharedExecuteCommand?.({ type: 'agent.task.reassign', workspaceId, agentId, task });
  };

  const totalMessagesToday = messages.length;
  const activeAgentsCount = agents.filter(a => a.status !== 'idle').length;
  const prdAcceptanceRatio = artifacts[0] ? `${artifacts[0].acceptedCount}/${artifacts[0].totalRequired}` : '0/0';

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
        reassignTask
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
