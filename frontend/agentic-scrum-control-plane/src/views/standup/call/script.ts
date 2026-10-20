/** Pure helpers behind the call screen: what is on the shared screen, how a line is shown a piece at a time, the highlights, the recap and the look of each person.
 *  The caption timing (pieces of at most about 110 characters, the time spread over their length) and the Markdown recap are adapted from Agent Standup (MIT), see THIRD_PARTY_NOTICES.md. */
import type { MeetingEventWire } from '../models/meeting-events';
import type { StandupParticipant, StandupTimelineEntry, StandupView } from '../models/standup';
import { meetingTypeLabel, statusLabel } from '../models/meeting-status';

export const SPOKEN_KINDS: ReadonlySet<string> = new Set([
  'statement', 'brainstorm', 'proposal', 'challenge', 'counterargument', 'question', 'clarification_requested', 'clarification_answered', 'facilitator_intervention',
]);

export function isSpoken(entry: Pick<StandupTimelineEntry, 'event_type'>): boolean {
  return SPOKEN_KINDS.has(entry.event_type);
}

/** A line cut into pieces to be shown one after the other: sentences, and a long sentence cut at its commas, so no piece is much longer than a subtitle line. */
export function splitPieces(text: string, limit = 110): string[] {
  const clean = text.replace(/\s+/g, ' ').trim();
  if (!clean) return [];
  const out: string[] = [];
  const sentences = clean.split(/(?<=[.!?…]["')\]]*)\s+/);
  for (const sentence of sentences) {
    const t = sentence.trim();
    if (!t) continue;
    if (t.length <= limit) {
      out.push(t);
      continue;
    }
    let current = '';
    for (const part of t.split(/(?<=[,;:—])\s+/)) {
      if (current && current.length + part.length > limit - 20) {
        out.push(current);
        current = part;
      } else {
        current = current ? `${current} ${part}` : part;
      }
    }
    if (current) out.push(current);
  }
  return out;
}

/** How long a line takes to say, in milliseconds: about what a person needs, faster when the replay is faster. */
export function speechMs(text: string, speed = 1): number {
  const words = text.split(/\s+/).filter(Boolean).length;
  return Math.max(1400, Math.round((words * 330 + 500) / Math.max(0.25, speed)));
}

/** When each piece of a line starts, as milliseconds from the start: the total time is spread over the pieces by their length. */
export function pieceStarts(pieces: readonly string[], totalMs: number): number[] {
  const total = pieces.reduce((n, p) => n + p.length, 0) || 1;
  let at = 0;
  return pieces.map((p) => {
    const start = Math.round(at);
    at += (totalMs * p.length) / total;
    return start;
  });
}

/** A line that came with who it is for ("to Developer 01: ...") is shown without it. */
export function spokenText(entry: Pick<StandupTimelineEntry, 'text'>): string {
  return entry.text.replace(/^to [^:]{1,40}:\s*/, '');
}

export type StageKind = 'question' | 'documents' | 'decision' | 'actions' | 'risks' | 'now';

export const STAGE_LABEL: Record<StageKind, string> = {
  question: 'A question for the Business SME', documents: 'Documents and approvals', decision: 'Decisions', actions: 'Action items', risks: 'Risks and dependencies', now: 'This meeting',
};

const SETUP = new Set(['meeting_created', 'meeting_started', 'participant_joined', 'participant_left', 'skill_selected', 'role_assigned']);

/** What the shared screen shows when nobody pinned anything: what needs the Business SME first, otherwise what the meeting has just been doing. */
export function stageFor(view: StandupView): StageKind {
  if (view.open_questions.length > 0) return 'question';
  if (view.approvals_open.length > 0) return 'documents';
  const last = [...view.recent].reverse().find((e) => !SETUP.has(e.event_type) && !isSpoken(e) && !['topic_started', 'topic_completed'].includes(e.event_type));
  const speech = [...view.recent].reverse().find((e) => isSpoken(e));
  if (last && (!speech || last.sequence > speech.sequence - 2)) {
    if (last.event_type.startsWith('decision_') && view.decisions.length) return 'decision';
    if (last.event_type.startsWith('action_item_') && view.action_items.length) return 'actions';
    if ((last.event_type.startsWith('document_') || last.event_type.startsWith('sme_')) && (view.reviews.length || view.approvals_open.length)) return 'documents';
    if (['risk_raised', 'dependency_identified'].includes(last.event_type) && (view.risks.length || view.dependencies.length)) return 'risks';
  }
  return 'now';
}

/** What can be pinned on the shared screen right now (kinds with nothing to show are not offered). */
export function stageChoices(view: StandupView): StageKind[] {
  const out: StageKind[] = ['now'];
  if (view.open_questions.length) out.push('question');
  if (view.reviews.length || view.approvals_open.length) out.push('documents');
  if (view.decisions.length) out.push('decision');
  if (view.action_items.length) out.push('actions');
  if (view.risks.length || view.dependencies.length) out.push('risks');
  return out;
}

export function waitedSeconds(askedAt: string | null | undefined, now: number): number | null {
  if (!askedAt) return null;
  const t = Date.parse(askedAt);
  if (Number.isNaN(t)) return null;
  const seconds = Math.max(0, Math.floor((now - t) / 1000));
  return seconds > 7 * 24 * 3600 ? null : seconds; // a wait of weeks is a recording (the demo), not a person kept waiting
}

export function waitedLabel(seconds: number | null): string {
  if (seconds === null) return '';
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

// ---------------------------------------------------------------------------------------------- highlights

export interface Highlight { sequence: number; kind: 'question' | 'decision' | 'intervention' | 'risk' | 'blocked' | 'approval'; label: string }

const HIGHLIGHT_KINDS: Record<string, Highlight['kind']> = {
  clarification_requested: 'question', question: 'question', decision_accepted: 'decision', decision_rejected: 'decision', human_takeover: 'intervention', autopilot_enabled: 'intervention',
  facilitator_intervention: 'intervention', risk_raised: 'risk', participant_blocked: 'blocked', sme_approval_requested: 'approval', document_changes_requested: 'approval',
};

const clip = (text: string, n = 38) => (text.length > n ? `${text.slice(0, n - 1).trimEnd()}…` : text);

/** The moments worth jumping to in a replay, from the events alone: questions, decisions, interventions, risks, blockers, approvals. */
export function computeHighlights(events: readonly MeetingEventWire[]): Highlight[] {
  const out: Highlight[] = [];
  for (const e of events) {
    const kind = HIGHLIGHT_KINDS[e.event_type];
    if (!kind) continue;
    const p = e.payload as Record<string, unknown>;
    const text = String(p.text ?? p.title ?? p.subject ?? p.reason ?? p.decision_id ?? '');
    const label = {
      clarification_requested: `Question: ${clip(text)}`, question: `Question: ${clip(text)}`, decision_accepted: `Decided: ${clip(String(p.selected_option ?? p.decision_id ?? ''))}`,
      decision_rejected: 'Rejected a proposal', human_takeover: 'SME took control', autopilot_enabled: 'Autopilot on', facilitator_intervention: `Facilitator: ${clip(text, 30)}`,
      risk_raised: `Risk: ${clip(text, 30)}`, participant_blocked: `Blocked: ${clip(String(p.reason ?? ''), 30) || 'someone'}`, sme_approval_requested: `Approval: ${clip(text, 30)}`,
      document_changes_requested: 'Changes requested',
    }[e.event_type] ?? e.event_type;
    out.push({ sequence: e.sequence_number, kind, label });
  }
  return out;
}

// ---------------------------------------------------------------------------------------------- recap

export interface RecapCounts { people: number; statements: number; challenges: number; questions: number; decisions: number; actions: number; risks: number }

export function recapCounts(view: StandupView, events: readonly MeetingEventWire[]): RecapCounts {
  const count = (kinds: string[]) => events.filter((e) => kinds.includes(e.event_type)).length;
  return {
    people: view.participants.filter((p) => p.status !== 'left').length,
    statements: count([...SPOKEN_KINDS]),
    challenges: count(['challenge']),
    questions: count(['clarification_requested', 'question']),
    decisions: view.decisions.length,
    actions: view.action_items.length,
    risks: view.risks.length,
  };
}

/** Who spoke most, for the recap. */
export function busiest(view: StandupView, events: readonly MeetingEventWire[]): { person: StandupParticipant; lines: number }[] {
  const lines = new Map<string, number>();
  for (const e of events) if (SPOKEN_KINDS.has(e.event_type) && e.actor_id) lines.set(e.actor_id, (lines.get(e.actor_id) ?? 0) + 1);
  return view.participants.filter((p) => lines.has(p.participant_id)).map((person) => ({ person, lines: lines.get(person.participant_id) ?? 0 })).sort((a, b) => b.lines - a.lines).slice(0, 8);
}

/** The meeting as notes, ready to paste. */
export function recapMarkdown(view: StandupView): string {
  const people = view.participants.filter((p) => p.status !== 'left');
  const name = (id: string) => view.participants.find((p) => p.participant_id === id)?.display_name ?? id;
  const lines: string[] = [`# ${view.title}`, '', `${meetingTypeLabel(view.meeting_type)} · ${statusLabel(view.status)} · ${view.elapsed} · ${people.length} people`, ''];
  if (view.summary) lines.push('## Summary', view.summary, '');
  lines.push('## People', ...people.map((p) => `- ${p.display_name}${p.skill ? ` [${p.skill}]` : ''}${p.role ? ` (${p.role})` : ''}`), '');
  if (view.decisions.length) lines.push('## Decisions', ...view.decisions.map((d) => `- **${d.title}** — ${d.status}${d.selected_option ? `: ${d.selected_option}` : ''}${d.reason ? ` (${d.reason})` : ''}`), '');
  if (view.action_items.length) lines.push('## Action items', ...view.action_items.map((a) => `- [${a.status === 'done' ? 'x' : ' '}] ${a.description} — ${name(a.owner_id)}${a.due_reference ? `, due ${a.due_reference}` : ''}`), '');
  if (view.risks.length) lines.push('## Risks', ...view.risks.map((r) => `- (${r.severity}) ${r.text}`), '');
  if (view.dependencies.length) lines.push('## Dependencies', ...view.dependencies.map((d) => `- ${d.text}`), '');
  if (view.open_questions.length) lines.push('## Still open', ...view.open_questions.map((q) => `- ${q.text}`), '');
  if (view.reviews.length) lines.push('## Documents', ...view.reviews.map((r) => `- ${r.document_path}: ${r.status.replace('_', ' ')}${r.comments.length ? ` — ${r.comments.join('; ')}` : ''}`), '');
  return `${lines.join('\n').replace(/\n{3,}/g, '\n\n').trimEnd()}\n`;
}

// ---------------------------------------------------------------------------------------------- characters

export function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

const SKIN = ['#F6D6BD', '#EAB98E', '#D49A6A', '#B97A4B', '#8D5A3B', '#6B4128'];
const HAIR = ['#1C1C1C', '#4A2F1B', '#7A4B24', '#B8842F', '#8E8E8E', '#C0392B', '#2F4858'];
const SHIRT = ['#1F5FA8', '#2E7D6B', '#7B3FA0', '#B8860B', '#0891B2', '#C2410C', '#5B5B5B', '#DB2777'];
const DESK = [['#C98A5A', '#9A6238'], ['#6B6FA8', '#43467A'], ['#CAA27A', '#9C7650'], ['#86BE9A', '#5E9A77'], ['#B8A07A', '#8A7650']] as const;

export interface Look {
  skin: string; hair: string; shirt: string; hairStyle: 0 | 1 | 2 | 3 | 4; eyes: 0 | 1 | 2; glasses: boolean; accessory: 'none' | 'tie' | 'headset' | 'cap' | 'scarf';
  scene: 0 | 1 | 2 | 3; desk: readonly [string, string];
}

/** The same person always looks the same: derived from their id. The Business SME and the Scrum Master have a look of their own (a red tie; a headset). */
export function lookFor(id: string, type: string): Look {
  const h = hash(id);
  const base = {
    skin: SKIN[h % SKIN.length], hair: HAIR[(h >>> 3) % HAIR.length], hairStyle: ((h >>> 6) % 5) as Look['hairStyle'], eyes: ((h >>> 9) % 3) as Look['eyes'], glasses: ((h >>> 11) % 4) === 0,
    scene: ((h >>> 14) % 4) as Look['scene'], desk: DESK[(h >>> 16) % DESK.length],
  };
  if (type === 'business_sme') return { ...base, shirt: '#E60000', accessory: 'tie', scene: 0 };
  if (type === 'scrum_master') return { ...base, shirt: '#161616', accessory: 'headset', scene: 1 };
  const accessory = (['none', 'none', 'cap', 'scarf'] as const)[(h >>> 20) % 4];
  return { ...base, shirt: SHIRT[(h >>> 22) % SHIRT.length], accessory };
}
