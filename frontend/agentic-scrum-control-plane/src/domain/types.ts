export type PhaseId = 'kickoff' | 'brainstorm' | 'prd' | 'build' | 'review' | 'ship';

export type AgentStatus = 'idle' | 'active' | 'speaking' | 'blocked' | 'complete';

export interface WorkspaceAgent {
  id: string;
  name: string;
  role: string;
  status: AgentStatus;
  activeTask?: string;
  confidenceScore?: number;
  claimedSkill?: string;
  activeBranch?: string;
  contextUsagePercent?: number;
  avatarColor?: string;
}

export interface WorkspaceMessage {
  id: string;
  meetId: string;
  senderId: string;
  senderName: string;
  text: string;
  timestamp: string;
}

export interface WorkspaceSkill {
  id: string;
  name: string;
  instructions?: string;
  claimedCount: number;
}

export interface WorkspaceArtifactVersion {
  version: string;
  timestamp: string;
  author: string;
  summary: string;
  diffAdditions: string[];
  diffDeletions: string[];
  acceptedBy: string[];
}

export interface WorkspaceArtifact {
  id: string;
  title: string;
  filename: string;
  status: 'approved' | 'in_review' | 'draft';
  currentVersion: string;
  acceptedCount: number;
  totalRequired: number;
  /** Optional: full version history. Absent in metadata-only snapshots. */
  versions?: WorkspaceArtifactVersion[];
  /** Optional: current document body. Absent in metadata-only snapshots. */
  markdownContent?: string;
  /** Optional: agent names that accepted the current version. */
  acceptedBy?: string[];
}

export interface WorkspaceMeet {
  id: string;
  title: string;
  status: 'live' | 'completed' | 'scheduled';
  consensusRate: number;
  debateIntensity: number;
}

export interface WorkspaceSprint {
  id: string;
  number: string;
  title: string;
  phase: string;
  progress: number;
  status: 'active' | 'completed';
}

export interface WorkspaceEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
  isActive: boolean;
  latencyMs: number;
}

export interface WorkspaceMetrics {
  totalMessagesToday: number;
  totalPRs: number;
  prHistory: { time: string; prs: number }[];
}

export interface WorkspaceSnapshot {
  workspaceId: string;
  version: number;
  phaseId: PhaseId;
  agents: WorkspaceAgent[];
  messages: WorkspaceMessage[];
  skills: WorkspaceSkill[];
  artifacts: WorkspaceArtifact[];
  meets: WorkspaceMeet[];
  sprints: WorkspaceSprint[];
  edges: WorkspaceEdge[];
  metrics: WorkspaceMetrics;
  processedEventIds: string[];
}

export interface WorkspaceEventBase {
  eventId: string;
  workspaceId: string;
  occurredAt: string;
  version: number;
}

export type WorkspaceEvent =
  | (WorkspaceEventBase & { type: 'agent.updated'; payload: WorkspaceAgent })
  | (WorkspaceEventBase & { type: 'message.created'; payload: WorkspaceMessage })
  | (WorkspaceEventBase & { type: 'phase.changed'; payload: { phaseId: PhaseId } })
  | (WorkspaceEventBase & { type: 'artifact.updated'; payload: WorkspaceArtifact })
  | (WorkspaceEventBase & { type: 'meet.updated'; payload: WorkspaceMeet })
  | (WorkspaceEventBase & { type: 'metrics.updated'; payload: WorkspaceMetrics })
  | (WorkspaceEventBase & { type: 'skill.updated'; payload: WorkspaceSkill })
  | (WorkspaceEventBase & { type: 'sprint.updated'; payload: WorkspaceSprint })
  | (WorkspaceEventBase & { type: 'edge.updated'; payload: WorkspaceEdge });

export const PHASE_IDS: PhaseId[] = ['kickoff', 'brainstorm', 'prd', 'build', 'review', 'ship'];
