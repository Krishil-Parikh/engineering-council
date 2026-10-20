import { isOver, meetingTypeLabel, statusLabel, statusTone } from '../models/meeting-status';
import type { StandupMeetingRow } from '../models/standup';

const DOT: Record<string, string> = { live: 'bg-[#0F8A4B]', attention: 'bg-[#E60000]', done: 'bg-[#8E8E8E]', warn: 'bg-[#B8860B]', idle: 'bg-[#E2E0D9]' };

/** The formal meetings of the run, newest at the bottom. Choose one to watch it live or replay it. */
export function MeetingPicker({ rows, selectedId, onSelect, records, record, current, onRecord }: {
  rows: StandupMeetingRow[]; selectedId: string | null; onSelect: (id: string) => void; records: string[]; record: string | undefined; current: string; onRecord: (record: string | undefined) => void;
}) {
  return (
    <nav aria-label="Meetings" data-testid="meeting-picker" className="flex flex-col gap-2">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5B5B5B]">Meetings <span className="font-mono text-[#8E8E8E]">{rows.length}</span></h2>
      {records.length > 1 && (
        <label className="flex flex-col gap-0.5 text-[11px] text-[#5B5B5B]">
          Project record
          <select aria-label="Project record" value={record ?? current} onChange={(e) => onRecord(e.target.value === current ? undefined : e.target.value)} className="rounded-md border border-[#E2E0D9] bg-white px-1.5 py-1 text-[12px]">
            {records.map((r) => <option key={r} value={r}>{r === current ? `${r} (this project)` : r}</option>)}
          </select>
        </label>
      )}
      {rows.length === 0 && <p className="text-[13px] text-[#8E8E8E]">No meeting has started yet. Formal meetings appear here as the team holds them.</p>}
      <ul className="space-y-1" role="list">
        {rows.map((row) => {
          const tone = statusTone(row.status);
          const selected = row.meeting_id === selectedId;
          return (
            <li key={row.meeting_id}>
              <button
                type="button"
                onClick={() => onSelect(row.meeting_id)}
                aria-current={selected ? 'true' : undefined}
                data-testid="meeting-row"
                className={`w-full rounded-lg border p-2.5 text-left transition-colors ${selected ? 'border-[#161616] bg-white shadow-sm' : 'border-[#E2E0D9] bg-[#FBFAF7] hover:bg-white'}`}
              >
                <div className="flex items-center gap-2">
                  <span aria-hidden className={`h-2 w-2 shrink-0 rounded-full ${DOT[tone]}`} />
                  <span className="truncate text-[13px] font-semibold text-[#161616]">{row.title}</span>
                </div>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[10.5px] text-[#5B5B5B]">
                  <span className="uppercase tracking-[0.08em]">{meetingTypeLabel(row.meeting_type)}</span>
                  <span>{statusLabel(row.status)}</span>
                  {row.open_questions > 0 && !isOver(row.status) && <span className="font-semibold text-[#8F0000]">{row.open_questions} waiting for you</span>}
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
