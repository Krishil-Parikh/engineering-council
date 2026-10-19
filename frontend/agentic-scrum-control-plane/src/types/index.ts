export type PhaseId = 'kickoff' | 'brainstorm' | 'prd' | 'build' | 'review' | 'ship';

export interface PhaseInfo {
  id: PhaseId;
  label: string;
  shortDesc: string;
  estimatedMinutes?: number;
}

export type AgentStatus = 'idle' | 'active' | 'reviewing' | 'blocked' | 'complete';

export interface Agent {
  id: string;
  name: string;
  role: string;
  claimedSkill?: string;
  status: AgentStatus;
  currentTask?: string;
  activeBranch?: string;
  contextUsagePercent?: number;
  avatarColor: string;
}

export interface Skill {
  id: string;
  name: string;
  instructions: string;
  claimedCount: number;
  isNew?: boolean;
}

export interface TranscriptMessage {
  id: string;
  speakerId: string;
  speakerName: string;
  speakerRole: string;
  avatarColor: string;
  timestamp: string;
  content: string;
  isQuestionForSME?: boolean;
  questionContext?: string;
  smeAnswered?: boolean;
  smeResponse?: string;
  isDebate?: boolean;
}

export interface PRHourlyData {
  time: string;
  prs: number;
  commitHash?: string;
}

export interface ArtifactFile {
  name: string;
  size: string;
  type: string;
  lastModified: string;
  content: string;
}
