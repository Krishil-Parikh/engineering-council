import { participantName } from '../models/lookup';
import type { StandupActionItem, StandupParticipant } from '../models/standup';

const LABEL: Record<StandupActionItem['status'], string> = { open: 'Open', in_progress: 'In progress', done: 'Done', dropped: 'Dropped' };
const BADGE: Record<StandupActionItem['status'], string> = {
  open: 'border-[#E2E0D9] bg-[#F4F3EE] text-[#5B5B5B]', in_progress: 'border-[#1F5FA8]/40 bg-[#1F5FA8]/10 text-[#14447D]',
  done: 'border-[#0F8A4B]/40 bg-[#0F8A4B]/10 text-[#0B6636]', dropped: 'border-[#E2E0D9] bg-white text-[#8E8E8E] line-through',
};

export function ActionItemsPanel({ items, participants }: { items: StandupActionItem[]; participants: StandupParticipant[] }) {
  return (
    <section aria-label="Action items" data-testid="action-items-panel" className="flex flex-col gap-2">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5B5B5B]">Action items <span className="font-mono text-[#8E8E8E]">{items.length}</span></h2>
      {items.length === 0 && <p className="text-[13px] text-[#8E8E8E]">No action items yet.</p>}
      <ul className="space-y-1.5" role="list">
        {items.map((a) => (
          <li key={a.action_item_id} data-testid="action-item" data-status={a.status} className="rounded-lg border border-[#E2E0D9] bg-white p-2.5">
            <div className="flex items-start justify-between gap-2">
              <span className="text-[13px] text-[#161616]">{a.description}</span>
              <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10.5px] font-semibold ${BADGE[a.status]}`}>{LABEL[a.status]}</span>
            </div>
            <p className="mt-0.5 text-[10.5px] text-[#8E8E8E]">Owner: {participantName(participants, a.owner_id)}{a.due_reference ? ` · due ${a.due_reference}` : ''}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
