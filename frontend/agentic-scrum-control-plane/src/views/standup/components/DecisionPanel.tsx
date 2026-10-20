import { participantName } from '../models/lookup';
import type { StandupDecision, StandupParticipant } from '../models/standup';

const ORDER: StandupDecision['status'][] = ['proposed', 'accepted', 'deferred', 'rejected'];
const BADGE: Record<StandupDecision['status'], string> = {
  proposed: 'border-[#1F5FA8]/40 bg-[#1F5FA8]/10 text-[#14447D]',
  accepted: 'border-[#0F8A4B]/40 bg-[#0F8A4B]/10 text-[#0B6636]',
  rejected: 'border-[#E60000]/40 bg-[#E60000]/10 text-[#8F0000]',
  deferred: 'border-[#B8860B]/50 bg-[#FFF7E0] text-[#6B4E00]',
};
const LABEL: Record<StandupDecision['status'], string> = { proposed: 'Proposed', accepted: 'Accepted', rejected: 'Rejected', deferred: 'Deferred' };

/** Accepted decisions, rejected proposals and deferred ones, each with who proposed and who settled it. */
export function DecisionPanel({ decisions, participants }: { decisions: StandupDecision[]; participants: StandupParticipant[] }) {
  const sorted = [...decisions].sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status));
  return (
    <section aria-label="Decisions" data-testid="decision-panel" className="flex flex-col gap-2">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5B5B5B]">Decisions <span className="font-mono text-[#8E8E8E]">{decisions.length}</span></h2>
      {sorted.length === 0 && <p className="text-[13px] text-[#8E8E8E]">No decision has been proposed yet.</p>}
      <ul className="space-y-1.5" role="list">
        {sorted.map((d) => (
          <li key={d.decision_id} data-testid="decision" data-status={d.status} className="rounded-lg border border-[#E2E0D9] bg-white p-2.5">
            <div className="flex items-start justify-between gap-2">
              <span className="text-[13px] font-medium text-[#161616]">{d.title}</span>
              <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10.5px] font-semibold ${BADGE[d.status]}`}>{LABEL[d.status]}</span>
            </div>
            {d.selected_option && <p className="mt-0.5 text-[12px] text-[#161616]">Chosen: <strong>{d.selected_option}</strong></p>}
            {d.alternatives.length > 0 && !d.selected_option && <p className="mt-0.5 text-[11.5px] text-[#5B5B5B]">Options: {d.alternatives.join(', ')}</p>}
            {d.reason && <p className="mt-0.5 text-[11.5px] text-[#5B5B5B]">{d.reason}</p>}
            <p className="mt-0.5 text-[10.5px] text-[#8E8E8E]">
              {d.proposed_by && <>Proposed by {participantName(participants, d.proposed_by)}</>}
              {d.decided_by && d.status !== 'proposed' && <> · settled by {participantName(participants, d.decided_by)}</>}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
