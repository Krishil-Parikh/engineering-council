export type MeetingStatus =
  | 'created' | 'waiting_for_participants' | 'active' | 'paused' | 'waiting_for_sme' | 'reviewing' | 'awaiting_approval' | 'completed' | 'cancelled' | 'timed_out';

export type ControlMode = 'human' | 'autopilot';

export type ParticipantStatus = 'joined' | 'thinking' | 'speaking' | 'listening' | 'waiting' | 'blocked' | 'needs_sme' | 'reviewing' | 'finished' | 'left';

export const OVER_STATUSES: readonly MeetingStatus[] = ['completed', 'cancelled', 'timed_out'];

export const STATUS_LABEL: Record<MeetingStatus, string> = {
  created: 'Not started',
  waiting_for_participants: 'Waiting for people',
  active: 'In progress',
  paused: 'Paused',
  waiting_for_sme: 'Waiting for the Business SME',
  reviewing: 'Reviewing a document',
  awaiting_approval: 'Waiting for approval',
  completed: 'Finished',
  cancelled: 'Cancelled',
  timed_out: 'Ran out of time',
};

export const MEETING_TYPE_LABEL: Record<string, string> = {
  discovery: 'Discovery', prd_review: 'PRD review', architecture_review: 'Architecture review', design_review: 'Design review', sprint_planning: 'Sprint planning',
  daily_standup: 'Daily standup', sprint_review: 'Sprint review', sprint_retrospective: 'Retrospective', sme_checkpoint: 'SME checkpoint', custom: 'Meeting',
};

export const PARTICIPANT_LABEL: Record<string, string> = {
  business_sme: 'Business SME', scrum_master: 'Scrum Master', developer: 'Developer', reviewer: 'Reviewer', observer: 'Observer',
};

export function isOver(status: string): boolean {
  return (OVER_STATUSES as readonly string[]).includes(status);
}

export function statusLabel(status: string): string {
  return STATUS_LABEL[status as MeetingStatus] ?? status.replace(/_/g, ' ');
}

export function meetingTypeLabel(type: string): string {
  return MEETING_TYPE_LABEL[type] ?? type.replace(/_/g, ' ');
}

/** How a status reads on a badge: "attention" asks something of the person watching. */
export function statusTone(status: string): 'live' | 'attention' | 'done' | 'warn' | 'idle' {
  if (status === 'waiting_for_sme' || status === 'awaiting_approval') return 'attention';
  if (status === 'active' || status === 'reviewing') return 'live';
  if (status === 'completed') return 'done';
  if (status === 'timed_out' || status === 'cancelled') return 'warn';
  return 'idle';
}

export function formatClock(seconds: number | null | undefined): string {
  const total = Math.max(0, Math.floor(seconds ?? 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}
