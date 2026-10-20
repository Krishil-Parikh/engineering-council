import { initials, typeTint } from '../models/lookup';
import { PARTICIPANT_LABEL } from '../models/meeting-status';
import type { StandupParticipant } from '../models/standup';
import { SkillBadge } from './SkillBadge';
import { SpeakerIndicator } from './SpeakerIndicator';

const STATUS_TEXT: Record<string, string> = {
  joined: 'Joined', thinking: 'Thinking', speaking: 'Speaking', listening: 'Listening', waiting: 'Waiting for an answer', blocked: 'Blocked', needs_sme: 'Needs you',
  reviewing: 'Reviewing', finished: 'Finished', left: 'Left',
};

const STATUS_STYLE: Record<string, string> = {
  needs_sme: 'border-[#E60000] bg-[#E60000]/5 text-[#8F0000]',
  blocked: 'border-[#B8860B]/60 bg-[#FFF7E0] text-[#6B4E00]',
  speaking: 'border-[#E60000]/40 bg-white text-[#161616]',
  waiting: 'border-[#E2E0D9] bg-[#F4F3EE] text-[#5B5B5B]',
};

export function ParticipantCard({ person }: { person: StandupParticipant }) {
  const label = STATUS_TEXT[person.status] ?? person.status;
  const emphasis = person.needs_sme ? 'border-[#E60000] shadow-[0_0_0_2px_rgba(230,0,0,0.12)]' : person.speaking ? 'border-[#161616]' : 'border-[#E2E0D9]';
  return (
    <li
      data-testid="participant-card"
      data-status={person.status}
      aria-label={`${person.display_name}, ${PARTICIPANT_LABEL[person.participant_type] ?? person.participant_type}${person.skill ? `, skill ${person.skill}` : ''}, ${label}`}
      className={`flex items-start gap-2.5 rounded-lg border bg-white p-2.5 transition-colors ${emphasis} ${person.status === 'left' ? 'opacity-50' : ''}`}
    >
      <span aria-hidden className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white" style={{ backgroundColor: typeTint(person.participant_type) }}>
        {initials(person.display_name)}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-[13px] font-semibold text-[#161616]">{person.display_name}</span>
          <SpeakerIndicator active={person.speaking} />
        </div>
        <div className="text-[10.5px] uppercase tracking-[0.1em] text-[#8E8E8E]">{PARTICIPANT_LABEL[person.participant_type] ?? person.participant_type}</div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <span className={`rounded-full border px-2 py-0.5 text-[10.5px] font-medium ${STATUS_STYLE[person.status] ?? 'border-[#E2E0D9] bg-[#F4F3EE] text-[#5B5B5B]'}`}>{label}</span>
          <SkillBadge skill={person.skill} role={person.role} />
        </div>
      </div>
    </li>
  );
}
