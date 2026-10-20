import type { StandupParticipant } from './standup';

/** A person's name from their id (the id itself when they are not in the list: an action item may belong to someone who has left). */
export function participantName(participants: readonly StandupParticipant[], id: string | null | undefined): string {
  if (!id) return 'Someone';
  return participants.find((p) => p.participant_id === id)?.display_name ?? id;
}

export function initials(name: string): string {
  const words = name.replace(/[^A-Za-z0-9 ]+/g, ' ').trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return '?';
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  const last = words[words.length - 1];
  // "Developer 03" is D3, not D0: a number at the end tells people apart, so it is kept
  if (/^\d+$/.test(last)) return (words[0][0] + String(Number(last))).toUpperCase().slice(0, 3);
  return (words[0][0] + last[0]).toUpperCase();
}

const TYPE_TINT: Record<string, string> = {
  business_sme: '#E60000', scrum_master: '#161616', developer: '#1F5FA8', reviewer: '#7B3FA0', observer: '#5B5B5B',
};

export function typeTint(type: string): string {
  return TYPE_TINT[type] ?? '#5B5B5B';
}

export function cap(text: string): string {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}
