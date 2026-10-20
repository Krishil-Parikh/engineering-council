import type { StandupParticipant } from '../models/standup';
import { ParticipantCard } from './ParticipantCard';

/** Everyone in the meeting, whoever needs attention first. Nothing here knows how many developers there are or what each is "for". */
export function ParticipantGrid({ participants }: { participants: StandupParticipant[] }) {
  const present = participants.filter((p) => p.status !== 'left');
  const gone = participants.filter((p) => p.status === 'left');
  return (
    <section aria-label="Participants" className="flex flex-col gap-2">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5B5B5B]">
        People <span data-testid="participant-count" className="font-mono text-[#8E8E8E]">{present.length}</span>
      </h2>
      {participants.length === 0 ? (
        <p className="rounded-lg border border-dashed border-[#E2E0D9] p-4 text-[13px] text-[#8E8E8E]">Nobody has joined this meeting yet.</p>
      ) : (
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2" role="list">
          {[...present, ...gone].map((p) => <ParticipantCard key={p.participant_id} person={p} />)}
        </ul>
      )}
    </section>
  );
}
