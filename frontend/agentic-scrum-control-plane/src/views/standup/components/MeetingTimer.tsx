import { formatClock } from '../models/meeting-status';

export function MeetingTimer({ elapsed, remaining, paused, over, overtime }: { elapsed: number; remaining: number | null; paused: boolean; over: boolean; overtime: boolean }) {
  return (
    <div role="timer" aria-live="off" data-testid="meeting-timer" className="flex items-center gap-3 font-mono text-[12px] text-[#161616]">
      <span title="Time in the meeting, not counting pauses">
        <span className="mr-1 font-sans text-[10px] uppercase tracking-[0.12em] text-[#8E8E8E]">Elapsed</span>
        <span data-testid="elapsed">{formatClock(elapsed)}</span>
      </span>
      {remaining !== null && (
        <span title="Time left before the meeting is closed">
          <span className="mr-1 font-sans text-[10px] uppercase tracking-[0.12em] text-[#8E8E8E]">Left</span>
          <span data-testid="remaining" className={overtime ? 'text-[#E60000]' : ''}>{formatClock(remaining)}</span>
        </span>
      )}
      {paused && !over && <span className="rounded-full border border-[#B8860B]/50 bg-[#FFF7E0] px-2 py-0.5 font-sans text-[10.5px] font-semibold text-[#6B4E00]">Paused</span>}
    </div>
  );
}
