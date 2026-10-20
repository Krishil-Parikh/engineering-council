import { PARTICIPANT_LABEL } from '../models/meeting-status';
import type { StandupParticipant } from '../models/standup';
import { CharacterAvatar } from './CharacterAvatar';
import './call.css';

const STATE_OF: Record<string, string> = { needs_sme: 'needs_sme', blocked: 'blocked', waiting: 'waiting', reviewing: 'reviewing', finished: 'finished' };
const STATUS_TEXT: Record<string, string> = {
  joined: '', thinking: 'Thinking', speaking: 'Speaking', listening: '', waiting: 'Waiting for an answer', blocked: 'Blocked', needs_sme: 'Needs you', reviewing: 'Reviewing', finished: 'Done', left: 'Left',
};
const BADGE: Record<string, string> = {
  needs_sme: 'bg-[#E60000] text-white', blocked: 'bg-[#C0392B] text-white', waiting: 'bg-[#0E0F18]/80 text-[#8FD3FF]', reviewing: 'bg-[#0E0F18]/80 text-[#FFD24A]',
  finished: 'bg-[#0E0F18]/80 text-[#58D68D]', speaking: 'bg-[#7C9CFF] text-[#0B1020]', thinking: 'bg-[#0E0F18]/80 text-[#CFD6E6]',
};

export interface CallTileProps {
  person: StandupParticipant;
  /** Who has the spotlight: the one whose line is being said (or, with nothing playing, the one the server says spoke last). */
  spotlight: boolean;
  /** Mouth moving: only while their line is being said. */
  talking: boolean;
  /** What they are saying, for the speech bubble (the subtitle bar has the same line, a piece at a time). */
  saying?: string;
  /** What they did last, in a few words. */
  lastAction?: string;
  size: 'normal' | 'small' | 'row';
  selected?: boolean;
  onSelect?: (id: string) => void;
}

export function CallTile({ person, spotlight, talking, saying, lastAction, size, selected, onSelect }: CallTileProps) {
  const state = STATE_OF[person.status] ?? 'idle';
  const status = talking ? 'speaking' : person.status;
  const label = STATUS_TEXT[status] ?? '';
  const ring = state === 'needs_sme' ? 'border-[#E60000]' : state === 'blocked' ? 'border-[#FF5252]' : spotlight ? 'border-[#7C9CFF] shadow-[0_0_0_3px_rgba(124,156,255,0.4),0_10px_30px_rgba(0,0,0,0.55)]' : 'border-white/10';
  if (size === 'row') {
    return (
      <li
        data-testid="call-tile"
        data-state={state}
        data-speaking={talking ? 'true' : 'false'}
        aria-label={`${person.display_name}, ${PARTICIPANT_LABEL[person.participant_type] ?? person.participant_type}${person.skill ? `, ${person.skill}` : ''}${label ? `, ${label}` : ''}`}
        className="su-tile flex items-center gap-2 rounded-lg border border-white/10 bg-[#1B1D27] p-1.5 text-[#E9EAF0]"
      >
        <span className="h-9 w-12 shrink-0 overflow-hidden rounded-md"><CharacterAvatar id={person.participant_id} type={person.participant_type} className="h-full w-full" /></span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[12.5px] font-semibold">{person.display_name}</span>
          <span className="block truncate text-[11px] text-[#9AA0B6]">{saying ?? lastAction ?? PARTICIPANT_LABEL[person.participant_type]}</span>
        </span>
        {label && <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-semibold ${BADGE[status] ?? 'bg-[#0E0F18]/80 text-[#CFD6E6]'}`}>{label}</span>}
      </li>
    );
  }
  return (
    <li
      data-testid="call-tile"
      data-state={state}
      data-speaking={talking ? 'true' : 'false'}
      data-spotlight={spotlight ? 'true' : 'false'}
      aria-label={`${person.display_name}, ${PARTICIPANT_LABEL[person.participant_type] ?? person.participant_type}${person.skill ? `, skill ${person.skill}` : ''}${person.role ? `, ${person.role}` : ''}${label ? `, ${label}` : ''}`}
      className={`su-tile su-join group relative overflow-visible rounded-[14px] border bg-[#222] shadow-[0_2px_12px_rgba(0,0,0,0.35)] transition-[border-color,box-shadow] ${ring} ${person.status === 'left' ? 'opacity-50' : ''} ${selected ? 'outline outline-2 outline-offset-2 outline-[#7C9CFF]' : ''} ${spotlight ? 'z-[4]' : ''}`}
    >
      <button type="button" onClick={() => onSelect?.(person.participant_id)} className="block aspect-[4/3] w-full overflow-hidden rounded-[13px] text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#7C9CFF]" aria-label={`Look at ${person.display_name}`}>
        <CharacterAvatar id={person.participant_id} type={person.participant_type} className={`block h-full w-full ${person.status === 'finished' ? 'saturate-75' : ''}`} />
      </button>
      {label && <span className={`pointer-events-none absolute right-1.5 top-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold backdrop-blur ${BADGE[status] ?? 'bg-[#0E0F18]/80 text-[#CFD6E6]'}`}>{label}</span>}
      {talking && saying && (
        <div data-testid="speech-bubble" className="su-bubble-in absolute left-1.5 top-1.5 z-[6] max-w-[calc(100%-12px)] rounded-[11px] bg-white px-2.5 py-1.5 text-[12px] leading-snug text-[#1B1D27] shadow-[0_4px_14px_rgba(0,0,0,0.35)] [overflow-wrap:anywhere]">
          <small className="block text-[10px] text-[#6A6F85]">{person.display_name}</small>
          {saying.length > 100 ? `${saying.slice(0, 99).trimEnd()}…` : saying}
        </div>
      )}
      {lastAction && !talking && size === 'normal' && (
        <div className="pointer-events-none absolute inset-x-1.5 bottom-7 truncate rounded-[5px] bg-[#0F1423]/80 px-1.5 py-0.5 font-mono text-[10px] text-white" data-testid="tile-ticker">{lastAction}</div>
      )}
      <div className="pointer-events-none absolute inset-x-1.5 bottom-1.5 flex gap-1">
        <b className="shrink-0 whitespace-nowrap rounded-full bg-[#0E0F18]/80 px-2 py-0.5 text-[11.5px] font-semibold text-white backdrop-blur">{person.display_name}</b>
        {size === 'normal' && (person.skill || person.role) && (
          <span className="min-w-0 truncate whitespace-nowrap rounded-full bg-[#0E0F18]/80 px-2 py-0.5 text-[10.5px] text-[#E3E6F0] backdrop-blur">
            {[person.skill ? person.skill.charAt(0).toUpperCase() + person.skill.slice(1) : null, person.role].filter(Boolean).join(' · ')}
          </span>
        )}
      </div>
    </li>
  );
}
