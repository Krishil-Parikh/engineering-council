import { isOver, meetingTypeLabel, statusLabel } from '../models/meeting-status';
import type { StandupMeetingRow } from '../models/standup';

const SECTIONS: { id: string; title: string; pick: (r: StandupMeetingRow) => boolean }[] = [
  { id: 'needs', title: 'Needs you', pick: (r) => !isOver(r.status) && r.open_questions > 0 },
  { id: 'running', title: 'In progress', pick: (r) => !isOver(r.status) && r.open_questions === 0 },
  { id: 'done', title: 'Finished', pick: (r) => isOver(r.status) },
];

/** Every meeting of the run on one board, grouped by what it needs, the one waiting for you first. A click opens it as a call. */
export function MeetingsBoard({ rows, selectedId, onOpen }: { rows: StandupMeetingRow[]; selectedId: string | null; onOpen: (id: string) => void }) {
  return (
    <section aria-label="All meetings" data-testid="meetings-board" className="rounded-xl bg-[#12131A] p-4 text-[#E9EAF0]">
      {rows.length === 0 && <p className="text-[13px] text-[#9AA0B6]">No meeting has started yet.</p>}
      {SECTIONS.map((section) => {
        const items = rows.filter(section.pick);
        if (items.length === 0) return null;
        return (
          <div key={section.id} className="mb-5" data-testid={`board-${section.id}`}>
            <h3 className={`mb-2 flex items-center gap-2 text-[12.5px] font-bold ${section.id === 'needs' ? 'text-[#FF8A80]' : 'text-[#9AA0B6]'}`}>
              {section.title} <i className="rounded-full border border-white/15 bg-white/5 px-2 text-[11.5px] font-semibold not-italic">{items.length}</i>
            </h3>
            <ul className="grid gap-2.5 [grid-template-columns:repeat(auto-fill,minmax(250px,1fr))]" role="list">
              {items.map((r) => (
                <li key={r.meeting_id}>
                  <button
                    type="button"
                    onClick={() => onOpen(r.meeting_id)}
                    aria-current={selectedId === r.meeting_id ? 'true' : undefined}
                    className={`flex w-full flex-col gap-1 rounded-xl border bg-[#232634] p-3 text-left hover:border-[#7C9CFF] ${section.id === 'needs' ? 'border-[#FF5252] shadow-[0_0_0_2px_rgba(255,82,82,0.25)]' : 'border-[#2A2D3B]'} ${section.id === 'done' ? 'opacity-75' : ''}`}
                  >
                    <span className="line-clamp-2 text-[13.5px] font-semibold">{r.title}</span>
                    <span className="text-[11.5px] text-[#9AA0B6]">{meetingTypeLabel(r.meeting_type)} · {statusLabel(r.status)} · {r.participants} people</span>
                    {r.open_questions > 0 && !isOver(r.status) && <span className="border-l-2 border-[#FF5252] pl-2 text-[12.5px]">{r.open_questions} waiting for you</span>}
                    <span className="text-[11px] text-[#9AA0B6]">{r.decisions} decisions · {r.action_items} action items</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </section>
  );
}
