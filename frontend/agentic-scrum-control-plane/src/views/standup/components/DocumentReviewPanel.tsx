import { useState } from 'react';
import type { StandupApproval, StandupDocumentReview } from '../models/standup';

const LABEL: Record<StandupDocumentReview['status'], string> = { in_review: 'In review', approved: 'Approved', changes_requested: 'Changes requested' };
const BADGE: Record<StandupDocumentReview['status'], string> = {
  in_review: 'border-[#1F5FA8]/40 bg-[#1F5FA8]/10 text-[#14447D]', approved: 'border-[#0F8A4B]/40 bg-[#0F8A4B]/10 text-[#0B6636]',
  changes_requested: 'border-[#E60000]/40 bg-[#E60000]/10 text-[#8F0000]',
};

/** The documents under review and what waits for the Business SME's approval. Approving or asking for changes is never done for you by the autopilot. */
export function DocumentReviewPanel({ reviews, approvals, disabled, onDecide }: {
  reviews: StandupDocumentReview[]; approvals: StandupApproval[]; disabled: boolean; onDecide: (approval: StandupApproval, approve: boolean, feedback: string) => Promise<void> | void;
}) {
  return (
    <section aria-label="Document review" data-testid="document-review-panel" className="flex flex-col gap-2">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5B5B5B]">Documents and approvals</h2>
      {reviews.length === 0 && approvals.length === 0 && <p className="text-[13px] text-[#8E8E8E]">No document is under review.</p>}
      <ul className="space-y-1.5" role="list">
        {reviews.map((r) => (
          <li key={r.document_path} data-testid="document-review" data-status={r.status} className="rounded-lg border border-[#E2E0D9] bg-white p-2.5">
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-[12.5px] text-[#161616]">{r.document_path}</span>
              <span className={`rounded-full border px-2 py-0.5 text-[10.5px] font-semibold ${BADGE[r.status]}`}>{LABEL[r.status]}</span>
            </div>
            {r.comments.length > 0 && <ul className="mt-1 list-disc pl-4 text-[11.5px] text-[#5B5B5B]">{r.comments.map((c, i) => <li key={i}>{c}</li>)}</ul>}
          </li>
        ))}
      </ul>
      {approvals.map((a) => <ApprovalCard key={a.request_id} approval={a} disabled={disabled} onDecide={onDecide} />)}
    </section>
  );
}

function ApprovalCard({ approval, disabled, onDecide }: { approval: StandupApproval; disabled: boolean; onDecide: (a: StandupApproval, approve: boolean, feedback: string) => Promise<void> | void }) {
  const [feedback, setFeedback] = useState('');
  const [busy, setBusy] = useState(false);
  const decide = async (approve: boolean) => {
    setBusy(true);
    try {
      await onDecide(approval, approve, feedback.trim());
    } finally {
      setBusy(false);
    }
  };
  return (
    <article data-testid="approval" className="rounded-lg border border-[#E60000]/40 bg-white p-3">
      <p className="text-[13px] font-medium text-[#161616]">{approval.subject}</p>
      {approval.extra.context && <p className="mt-0.5 whitespace-pre-wrap text-[11.5px] text-[#5B5B5B]">{approval.extra.context}</p>}
      <label htmlFor={`fb-${approval.request_id}`} className="sr-only">Reason, if you ask for changes</label>
      <input
        id={`fb-${approval.request_id}`}
        value={feedback}
        disabled={disabled || busy}
        onChange={(e) => setFeedback(e.target.value)}
        placeholder="What should change? (for a request for changes)"
        className="mt-2 w-full rounded-md border border-[#E2E0D9] px-2 py-1.5 text-[12.5px] focus:border-[#161616] focus:outline-none disabled:bg-[#F4F3EE]"
      />
      <div className="mt-2 flex gap-1.5">
        <button type="button" disabled={disabled || busy} onClick={() => void decide(true)} className="rounded-md bg-[#161616] px-3 py-1.5 text-[12px] font-semibold text-white disabled:opacity-40">Approve</button>
        <button type="button" disabled={disabled || busy || !feedback.trim()} onClick={() => void decide(false)} className="rounded-md border border-[#161616] px-3 py-1.5 text-[12px] font-semibold text-[#161616] disabled:opacity-40">Request changes</button>
      </div>
    </article>
  );
}
