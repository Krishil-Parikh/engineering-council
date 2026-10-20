import { participantName } from '../models/lookup';
import type { StandupParticipant } from '../models/standup';
import type { ActiveLine } from './useCallScript';

const KIND: Record<string, string> = {
  statement: '', brainstorm: 'brainstorming', proposal: 'proposes', challenge: 'challenges', counterargument: 'replies', question: 'asks', clarification_requested: 'asks the Business SME',
  clarification_answered: 'answers', facilitator_intervention: 'facilitating',
};

/** The line being said, one piece at a time, like subtitles. It is a polite live region, so a screen reader hears each new line once. */
export function SubtitleBar({ active, participants, queued }: { active: ActiveLine | null; participants: StandupParticipant[]; queued: number }) {
  if (!active) {
    return <div data-testid="subtitle-bar" role="status" aria-live="polite" className="min-h-[44px] rounded-[10px] bg-[#0A0B10]/80 px-3 py-2 text-[12.5px] text-[#6B7089]">Nobody has spoken yet.</div>;
  }
  const who = participantName(participants, active.entry.actor_id);
  const kind = KIND[active.entry.event_type] ?? '';
  return (
    <div data-testid="subtitle-bar" role="status" aria-live="polite" aria-atomic="true" className="min-h-[44px] rounded-[10px] bg-[#0A0B10]/85 px-3 py-2 backdrop-blur">
      <div className="flex items-center gap-2 text-[11px] text-[#9AA0B6]">
        <span className="font-semibold text-[#E9EAF0]">{who}</span>
        {kind && <span>{kind}</span>}
        <span className="font-mono text-[10px] text-[#6B7089]">{active.entry.elapsed}</span>
        {queued > 0 && <span className="ml-auto rounded-full bg-white/10 px-2 py-0.5 text-[10px]" title="Lines waiting their turn">+{queued} next</span>}
      </div>
      <p data-testid="subtitle-text" className="mt-0.5 text-[14px] leading-snug text-white">{active.pieces[active.index] ?? ''}</p>
      {active.pieces.length > 1 && (
        <div className="mt-1 flex gap-1" aria-hidden>
          {active.pieces.map((_, i) => <span key={i} className={`h-[3px] flex-1 rounded-full ${i <= active.index ? 'bg-[#7C9CFF]' : 'bg-white/15'}`} />)}
        </div>
      )}
    </div>
  );
}
