export type TabType = 'overview' | 'canvas' | 'meet' | 'artifacts' | 'timeline';

export type AgentRole = 'scrum_master' | 'frontend' | 'backend' | 'database' | 'devops' | 'sme' | 'qa';

export type AgentStatus = 'idle' | 'speaking' | 'orchestrating' | 'debating' | 'evaluating';

export interface Agent {
  id: string;
  name: string;
  role: AgentRole;
  roleTitle: string;
  status: AgentStatus;
  isLive: boolean;
  avatarNumber: string;
  activeTask: string;
  sparkline: number[];
  contextTokens: number;
  tokensVelocity: number;
  model: string;
  skills: string[];
  subAgentsCount?: number;
  allocatedMemory: string;
  confidenceScore: number;
  recentTools: string[];
}

export interface SkillCategory {
  id: string;
  name: string;
  activeCount: number;
  totalCount: number;
  isSolid: boolean;
}

export type MessageType = 
  | 'speech' 
  | 'debate_challenge' 
  | 'consensus' 
  | 'sme_input' 
  | 'artifact_update'
  | 'system';

export interface Message {
  id: string;
  meetId: string;
  senderId: string;
  senderName: string;
  senderRole: string;
  timestamp: string;
  timeOffsetSec: number;
  text: string;
  type: MessageType;
  inResponseTo?: string;
  codeSnippet?: string;
  tags?: string[];
  isContradiction?: boolean;
}

export interface Meet {
  id: string;
  number: string;
  sprintId: string;
  title: string;
  topic: string;
  status: 'live' | 'completed' | 'scheduled';
  elapsedTime: string;
  remainingTime: string;
  elapsedSec: number;
  remainingSec: number;
  participants: string[];
  consensusRate: number;
  debateIntensity: number; // 0-100
  heatSegments: { minute: number; intensity: number; isDebate: boolean }[];
  summary: string;
}

export interface ArtifactVersion {
  version: string;
  timestamp: string;
  author: string;
  summary: string;
  diffAdditions: string[];
  diffDeletions: string[];
  acceptedBy: string[];
}

export interface Artifact {
  id: string;
  title: string;
  filename: string;
  type: 'prd' | 'architecture' | 'design';
  currentVersion: string;
  status: 'approved' | 'in_review' | 'draft';
  acceptedCount: number;
  totalRequired: number;
  acceptedBy: string[];
  versions: ArtifactVersion[];
  markdownContent: string;
}

export interface Sprint {
  id: string;
  number: string;
  title: string;
  goal: string;
  phase: string;
  progress: number;
  status: 'active' | 'completed';
  startDate: string;
  targetDate: string;
  meets: {
    id: string;
    label: string;
    title: string;
    outcome: 'consensus' | 'pivot' | 'blocked';
    duration: string;
  }[];
  smeReviewPoints: {
    label: string;
    date: string;
    approved: boolean;
    note: string;
  }[];
  standup: {
    yesterday: string[];
    today: string[];
    blockers: string[];
  };
  retro: {
    wentWell: string[];
    toImprove: string[];
    actionItems: string[];
  };
}

export interface DelegationEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
  isActive: boolean;
  dataPacket?: string;
  latencyMs: number;
}
