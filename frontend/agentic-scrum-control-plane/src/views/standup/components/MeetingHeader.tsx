import { isOver, meetingTypeLabel, statusLabel, statusTone } from '../models/meeting-status';
import type { StandupView, StreamState } from '../models/standup';
import { MeetingTimer } from './MeetingTimer';

const TONE: Record<string, string> = {
  live: 'border-[#0F8A4B]/40 bg-[#0F8A4B]/10 text-[#0B6636]',
  attention: 'border-[#E60000]/50 bg-[#E60000]/10 text-[#8F0000]',
  done: 'border-[#E2E0D9] bg-[#F4F3EE] text-[#5B5B5B]',
  warn: 'border-[#B8860B]/50 bg-[#FFF7E0] text-[#6B4E00]',
  idle: 'border-[#E2E0D9] bg-white text-[#5B5B5B]',
};

const STREAM_TEXT: Record<StreamState, string> = {
  connecting: 'Connecting…', connected: 'Live', reconnecting: 'Connection lost, reconnecting…', ended: 'Meeting over', closed: '',
};

export interface TimerReading { elapsed: number; remaining: number | null; overtime: boolean }

export function MeetingHeader({ view, stream, replaying, timer }: { view: StandupView; stream: StreamState; replaying: boolean; timer: TimerReading }) {
  const over = isOver(view.status);
  const tone = statusTone(view.status);
  return (
    <header className="flex flex-wrap items-start justify-between gap-3 border-b border-[#E2E0D9] bg-white px-4 py-3" data-testid="meeting-header">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span data-testid="meeting-type" className="rounded-[3px] bg-[#161616] px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-white">{meetingTypeLabel(view.meeting_type)}</span>
          <span data-testid="meeting-status" className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${TONE[tone]}`}>{statusLabel(view.status)}</span>
          <span data-testid="control-mode" className="rounded-full border border-[#E2E0D9] px-2 py-0.5 text-[11px] text-[#5B5B5B]">
            {view.control_mode === 'autopilot' ? 'Autopilot Business SME' : 'Business SME in control'}
          </span>
          {replaying ? (
            <span data-testid="stream-state" className="rounded-full border border-[#7B3FA0]/40 bg-[#7B3FA0]/10 px-2 py-0.5 text-[11px] font-semibold text-[#58297A]">Replay</span>
          ) : STREAM_TEXT[stream] && !over ? (
            <span data-testid="stream-state" role="status" className={`rounded-full px-2 py-0.5 text-[11px] ${stream === 'reconnecting' ? 'border border-[#E60000]/40 bg-[#E60000]/5 text-[#8F0000]' : 'text-[#5B5B5B]'}`}>
              {STREAM_TEXT[stream]}
            </span>
          ) : null}
        </div>
        <h1 className="mt-1 truncate text-[17px] font-semibold text-[#161616]">{view.title}</h1>
        {view.current_topic && !over && <p data-testid="current-topic" className="text-[12px] text-[#5B5B5B]"><span className="uppercase tracking-[0.1em] text-[#8E8E8E]">Now: </span>{view.current_topic}</p>}
      </div>
      <MeetingTimer elapsed={timer.elapsed} remaining={timer.remaining} paused={view.paused} over={over} overtime={timer.overtime} />
    </header>
  );
}
