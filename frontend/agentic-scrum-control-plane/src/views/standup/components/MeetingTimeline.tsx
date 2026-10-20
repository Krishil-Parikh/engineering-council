import { useEffect, useMemo, useRef, useState } from 'react';
import type { StandupTimelineEntry, Tone } from '../models/standup';

const TONE_BORDER: Record<Tone, string> = {
  plain: 'border-l-[#E2E0D9]', warn: 'border-l-[#B8860B]', danger: 'border-l-[#E60000]', success: 'border-l-[#0F8A4B]', ask: 'border-l-[#1F5FA8]', info: 'border-l-[#7B3FA0]',
};

const KIND_LABEL: Record<string, string> = {
  statement: 'Statement', brainstorm: 'Brainstorm', proposal: 'Proposal', challenge: 'Challenge', counterargument: 'Counterargument', question: 'Question',
  clarification_requested: 'Question for the SME', clarification_answered: 'Answer', facilitator_intervention: 'Facilitator', risk_raised: 'Risk', dependency_identified: 'Dependency',
  decision_proposed: 'Decision proposed', decision_accepted: 'Decision accepted', decision_rejected: 'Decision rejected', decision_deferred: 'Decision deferred',
  action_item_created: 'Action item', action_item_updated: 'Action item', human_takeover: 'Control', autopilot_enabled: 'Control', summary_generated: 'Summary',
  topic_started: 'Topic', topic_completed: 'Topic', meeting_started: 'Meeting', meeting_ended: 'Meeting', meeting_paused: 'Meeting', meeting_resumed: 'Meeting',
  document_approved: 'Document', document_changes_requested: 'Document', document_review_started: 'Document', document_created: 'Document',
  sme_approval_requested: 'Approval', sme_approved: 'Approval', sme_rejected: 'Approval',
};

/** Who joined, which skill they took: kept in the record and the transcript, but not part of the conversation people read. */
export const SETUP_EVENTS = new Set(['meeting_created', 'meeting_started', 'participant_joined', 'participant_left', 'skill_selected', 'role_assigned']);

const SPOKEN = new Set(['statement', 'brainstorm', 'proposal', 'challenge', 'counterargument', 'question', 'clarification_requested', 'clarification_answered', 'facilitator_intervention']);

/** The conversation, newest last. It is a live region: a screen reader hears new lines. It follows the bottom unless the reader scrolled up to read. */
export function MeetingTimeline({ entries, highlight, onOpenTranscript }: { entries: StandupTimelineEntry[]; highlight?: number; onOpenTranscript?: () => void }) {
  const box = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const [showSetup, setShowSetup] = useState(false);
  const hidden = useMemo(() => entries.filter((e) => SETUP_EVENTS.has(e.event_type)).length, [entries]);
  const shown = showSetup ? entries : entries.filter((e) => !SETUP_EVENTS.has(e.event_type) || e.sequence === highlight);

  useEffect(() => {
    const el = box.current;
    if (el && following.current) el.scrollTop = el.scrollHeight;
  }, [shown.length]);

  return (
    <section aria-label="Meeting conversation" className="flex min-h-0 flex-1 flex-col">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5B5B5B]">Conversation</h2>
        <div className="flex items-center gap-3">
          {hidden > 0 && (
            <label className="flex items-center gap-1 text-[11px] text-[#5B5B5B]">
              <input type="checkbox" checked={showSetup} onChange={(e) => setShowSetup(e.target.checked)} />
              Show joins and setup ({hidden})
            </label>
          )}
          {onOpenTranscript && <button type="button" onClick={onOpenTranscript} className="text-[11px] font-medium text-[#1F5FA8] underline-offset-2 hover:underline">Open transcript</button>}
        </div>
      </div>
      <div
        ref={box}
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        tabIndex={0}
        data-testid="timeline"
        onScroll={(e) => {
          const el = e.currentTarget;
          following.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        }}
        className="max-h-[60vh] min-h-[220px] flex-1 space-y-2 overflow-y-auto rounded-lg border border-[#E2E0D9] bg-[#FBFAF7] p-3 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#161616]"
      >
        {shown.length === 0 && <p className="text-[13px] text-[#8E8E8E]">Nothing has been said yet.</p>}
        {shown.map((entry) => (
          <article
            key={entry.sequence}
            data-testid="timeline-entry"
            data-kind={entry.event_type}
            data-sequence={entry.sequence}
            className={`rounded-md border border-l-4 bg-white px-3 py-2 ${TONE_BORDER[entry.tone] ?? TONE_BORDER.plain} ${highlight === entry.sequence ? 'border-[#161616] ring-1 ring-[#161616]' : 'border-[#E2E0D9]'}`}
          >
            <div className="flex flex-wrap items-center gap-x-2 text-[11px] text-[#5B5B5B]">
              <span className="font-mono text-[#8E8E8E]">{entry.elapsed}</span>
              <span className="font-semibold text-[#161616]">{entry.actor_name}</span>
              <span className="rounded-[3px] bg-[#F4F3EE] px-1.5 py-0.5 text-[10px] uppercase tracking-[0.08em]">{KIND_LABEL[entry.event_type] ?? entry.event_type.replace(/_/g, ' ')}</span>
            </div>
            <p className={`mt-0.5 whitespace-pre-wrap break-words text-[13px] ${SPOKEN.has(entry.event_type) ? 'text-[#161616]' : 'text-[#5B5B5B]'}`}>{entry.text}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
