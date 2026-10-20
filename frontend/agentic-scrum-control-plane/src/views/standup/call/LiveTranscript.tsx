import { useEffect, useMemo, useRef } from 'react';
import type { MeetingEventWire } from '../models/meeting-events';
import { participantName } from '../models/lookup';
import type { StandupParticipant } from '../models/standup';
import { formatClock } from '../models/meeting-status';
import { SPOKEN_KINDS } from './script';
import type { ActiveLine } from './useCallScript';

const KIND: Record<string, string> = {
  statement: '', brainstorm: 'brainstorm', proposal: 'proposal', challenge: 'challenge', counterargument: 'reply', question: 'question', clarification_requested: 'asks the SME',
  clarification_answered: 'answer', facilitator_intervention: 'facilitator',
};
const MAX_LINES = 400;

export interface TranscriptLine { sequence: number; actorId: string | null; name: string; kind: string; text: string; at: number }

/** Everything said so far, from the events: who said it, what kind of line it was, and when. */
export function transcriptLines(events: readonly MeetingEventWire[], participants: readonly StandupParticipant[]): TranscriptLine[] {
  const lines: TranscriptLine[] = [];
  for (const e of events) {
    if (!SPOKEN_KINDS.has(e.event_type)) continue;
    const p = e.payload as Record<string, unknown>;
    const text = String(p.text ?? p.answer ?? '').trim();
    if (!text) continue;
    lines.push({ sequence: e.sequence_number, actorId: e.actor_id ?? null, name: participantName(participants, e.actor_id), kind: KIND[e.event_type] ?? '', text, at: e.elapsed_seconds });
  }
  return lines.slice(-MAX_LINES);
}

/** The transcript as the meeting goes: it follows the line being said, shows which sentence is being said now, and lets a replay jump to any line. */
export function LiveTranscript({ events, participants, active, replaying, onSeek }: {
  events: readonly MeetingEventWire[]; participants: readonly StandupParticipant[]; active: ActiveLine | null; replaying: boolean; onSeek?: (sequence: number) => void;
}) {
  const lines = useMemo(() => transcriptLines(events, participants), [events, participants]);
  const box = useRef<HTMLOListElement>(null);
  const following = useRef(true);
  const nowSeq = active?.entry.sequence ?? null;

  useEffect(() => {
    const el = box.current;
    if (el && following.current) el.scrollTop = el.scrollHeight;
  }, [lines.length, nowSeq, active?.index]);

  return (
    <section aria-label="Live transcript" data-testid="live-transcript" className="flex min-h-0 flex-col rounded-xl border border-white/10 bg-[#1B1D27] text-[#E9EAF0]">
      <h2 className="flex items-center justify-between border-b border-white/10 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-[#9AA0B6]">
        Live transcript <span className="font-mono normal-case tracking-normal text-[#6B7089]">{lines.length} {lines.length === 1 ? 'line' : 'lines'}</span>
      </h2>
      <ol
        ref={box}
        role="log"
        aria-live="off"
        tabIndex={0}
        aria-label="What has been said"
        onScroll={(e) => {
          const el = e.currentTarget;
          following.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        }}
        className="max-h-[520px] min-h-[200px] flex-1 space-y-2 overflow-y-auto p-3 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#7C9CFF]"
      >
        {lines.length === 0 && <li className="text-[12.5px] text-[#6B7089]">Nothing has been said yet.</li>}
        {lines.map((line) => {
          const now = nowSeq === line.sequence;
          const body = now && active ? (
            <>
              {active.pieces.map((piece, i) => (
                <span key={i} data-testid={i === active.index ? 'transcript-now' : undefined} className={i === active.index && active.animating ? 'rounded bg-[#7C9CFF]/25 px-0.5 text-white' : i > active.index && active.animating ? 'text-[#6B7089]' : ''}>{piece}{' '}</span>
              ))}
            </>
          ) : line.text;
          const content = (
            <>
              <div className="flex items-baseline gap-2 text-[11px] text-[#9AA0B6]">
                <span className="font-semibold text-[#E9EAF0]">{line.name}</span>
                {line.kind && <span>{line.kind}</span>}
                <span className="ml-auto font-mono text-[10px] text-[#6B7089]">{formatClock(line.at)}</span>
              </div>
              <p className="mt-0.5 text-[13px] leading-snug">{body}</p>
            </>
          );
          return (
            <li key={line.sequence} data-testid="transcript-line" data-sequence={line.sequence} data-now={now ? 'true' : 'false'} className={`rounded-lg px-2 py-1.5 ${now ? 'bg-white/10 ring-1 ring-[#7C9CFF]/60' : ''}`}>
              {replaying && onSeek ? <button type="button" onClick={() => onSeek(line.sequence)} className="block w-full text-left" aria-label={`Go to ${line.name} at ${formatClock(line.at)}`}>{content}</button> : content}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
