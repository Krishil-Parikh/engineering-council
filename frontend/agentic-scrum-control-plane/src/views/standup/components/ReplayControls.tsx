import { ChevronLeft, ChevronRight, Pause, Play, RotateCcw } from 'lucide-react';
import { formatClock } from '../models/meeting-status';
import type { JumpKind } from '../models/meeting-events';
import type { MeetingReplay } from '../hooks/useMeetingReplay';
import { REPLAY_SPEEDS } from '../state/standupStore';
import type { ReplaySpeed } from '../state/standupStore';

const JUMPS: { kind: JumpKind; label: string }[] = [
  { kind: 'decision', label: 'decision' }, { kind: 'question', label: 'question' }, { kind: 'intervention', label: 'intervention' },
];

/** Play a finished (or running) meeting back: pause, step, change speed, drag the scrubber, jump to the decisions, the questions and the interventions. */
export function ReplayControls({ replay, elapsedAt, onBackToLive }: { replay: MeetingReplay; elapsedAt: number; onBackToLive?: () => void }) {
  return (
    <section aria-label="Replay controls" data-testid="replay-controls" className="flex flex-col gap-2 border-t border-[#E2E0D9] bg-white px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={replay.toggle} aria-label={replay.playing ? 'Pause replay' : 'Play replay'} className="flex h-8 w-8 items-center justify-center rounded-full bg-[#161616] text-white">
          {replay.playing ? <Pause size={14} aria-hidden /> : <Play size={14} aria-hidden />}
        </button>
        <button type="button" onClick={() => replay.step(-1)} disabled={replay.atStart} aria-label="Previous event" className="rounded-md border border-[#E2E0D9] p-1.5 disabled:opacity-40"><ChevronLeft size={14} aria-hidden /></button>
        <button type="button" onClick={() => replay.step(1)} disabled={replay.atEnd} aria-label="Next event" className="rounded-md border border-[#E2E0D9] p-1.5 disabled:opacity-40"><ChevronRight size={14} aria-hidden /></button>
        <button type="button" onClick={replay.restart} aria-label="Restart replay" className="rounded-md border border-[#E2E0D9] p-1.5"><RotateCcw size={14} aria-hidden /></button>
        <label className="ml-2 flex items-center gap-1 text-[11px] text-[#5B5B5B]">
          Speed
          <select
            aria-label="Playback speed"
            value={replay.speed}
            onChange={(e) => replay.setSpeed(Number(e.target.value) as ReplaySpeed)}
            className="rounded-md border border-[#E2E0D9] bg-white px-1.5 py-1 text-[12px]"
          >
            {REPLAY_SPEEDS.map((s) => <option key={s} value={s}>{s}×</option>)}
          </select>
        </label>
        <span className="ml-auto font-mono text-[11px] text-[#5B5B5B]" data-testid="replay-position">event {replay.position} of {replay.total} · {formatClock(elapsedAt)}</span>
        {onBackToLive && <button type="button" onClick={onBackToLive} className="rounded-md border border-[#161616] px-2.5 py-1 text-[12px] font-semibold">Back to live</button>}
      </div>
      <input
        type="range"
        aria-label="Replay position"
        aria-valuetext={`event ${replay.position} of ${replay.total}`}
        min={1}
        max={Math.max(1, replay.total)}
        value={Math.max(1, replay.position)}
        onChange={(e) => replay.seek(Number(e.target.value))}
        className="w-full accent-[#161616]"
      />
      <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-[#5B5B5B]">
        <span>Jump to</span>
        {JUMPS.map((j) => (
          <span key={j.kind} className="inline-flex overflow-hidden rounded-md border border-[#E2E0D9]">
            <button type="button" onClick={() => replay.jump(j.kind, -1)} aria-label={`Previous ${j.label}`} className="px-1.5 py-1 hover:bg-[#F4F3EE]">‹</button>
            <span className="border-x border-[#E2E0D9] bg-[#F4F3EE] px-2 py-1">{j.label}</span>
            <button type="button" onClick={() => replay.jump(j.kind, 1)} aria-label={`Next ${j.label}`} className="px-1.5 py-1 hover:bg-[#F4F3EE]">›</button>
          </span>
        ))}
      </div>
      {replay.error && <p role="alert" className="text-[12px] text-[#8F0000]">{replay.error}</p>}
    </section>
  );
}
