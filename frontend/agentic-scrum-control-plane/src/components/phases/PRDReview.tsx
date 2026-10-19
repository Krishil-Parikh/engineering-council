import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Check, FileText, MessageSquareWarning, ShieldCheck } from 'lucide-react';
import type { WorkspaceArtifact } from '../../domain/types';

interface PRDReviewProps {
  /** The documents the pod meeting wrote (PRD, Technical Approach, Design), straight from the workspace. */
  documents: WorkspaceArtifact[];
  /** Whether the backend is waiting for you to accept them right now. */
  awaitingDecision: boolean;
  onAccept: (artifactId: string) => void;
  onRequestChanges: (feedback: string) => void;
}

/**
 * The real documents, read by a real person. Nothing here accepts on a timer: the team starts building only when the Accept button is pressed
 * (or declines with feedback and the documents come back revised).
 */
export const PRDReview: React.FC<PRDReviewProps> = ({ documents, awaitingDecision, onAccept, onRequestChanges }) => {
  const [selected, setSelected] = useState(0);
  const [asking, setAsking] = useState(false);
  const [feedback, setFeedback] = useState('');
  const current = documents[Math.min(selected, Math.max(documents.length - 1, 0))];
  const everyoneAgreed = documents.length > 0 && documents.every((d) => d.status === 'approved');

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
      className="mx-auto flex w-full max-w-[860px] flex-col px-4 py-8"
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2 text-xs text-[#5B5B5B]">
        <h2 className="text-[17px] font-semibold tracking-tight text-[#161616]">Read the documents before anything is built</h2>
        <span className="flex items-center gap-2 font-mono text-[11px]">
          <span className={`h-2 w-2 rounded-full ${awaitingDecision ? 'animate-pulse bg-[#E60000]' : 'bg-emerald-600'}`} />
          {awaitingDecision ? 'Waiting for your decision' : everyoneAgreed ? 'You accepted these' : 'Not ready yet'}
        </span>
      </div>

      {documents.length === 0 ? (
        <p className="rounded-2xl border border-[#E7E6DF] bg-[#FCFCFB] p-6 text-sm text-[#5B5B5B]">The documents are being written. They appear here when the meeting is done.</p>
      ) : (
        <>
          <div role="tablist" aria-label="Documents" className="mb-3 flex gap-1 rounded-lg border border-[#E7E6DF] bg-[#F4F3EE] p-1">
            {documents.map((doc, index) => (
              <button
                key={doc.id}
                role="tab"
                aria-selected={index === selected}
                onClick={() => setSelected(index)}
                className={`flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                  index === selected ? 'bg-[#FCFCFB] text-[#161616] shadow-sm' : 'text-[#5B5B5B] hover:text-[#161616]'
                }`}
              >
                <FileText className="h-3 w-3" />
                {doc.filename}
              </button>
            ))}
          </div>

          <article className="mb-4 rounded-2xl border border-[#E7E6DF] bg-[#FCFCFB] p-5 shadow-sm" aria-label={current.title}>
            <header className="mb-3 flex items-center justify-between border-b border-[#E7E6DF] pb-2 text-[11px] font-mono text-[#8E8E8E]">
              <span>{current.title} · {current.currentVersion}</span>
              <span>{current.acceptedCount} of {current.totalRequired} signed off</span>
            </header>
            <pre className="max-h-[52vh] overflow-y-auto whitespace-pre-wrap font-sans text-[13px] leading-[21px] text-[#161616]" data-testid="document-text">
              {current.markdownContent || 'This document has no text yet.'}
            </pre>
          </article>

          <div className="mb-5 flex flex-wrap items-center gap-2 text-[11px] text-[#5B5B5B]">
            <span className="font-mono uppercase tracking-wider">Signed off by</span>
            {(current.acceptedBy ?? []).length === 0 && <span className="text-[#8E8E8E]">no one yet</span>}
            {(current.acceptedBy ?? []).map((name) => (
              <span key={name} className="inline-flex items-center gap-1 rounded-md border border-[#E7E6DF] bg-[#F4F3EE] px-2 py-0.5 font-mono">
                <Check className="h-3 w-3 text-emerald-700" />
                {name}
              </span>
            ))}
          </div>
        </>
      )}

      {awaitingDecision && (
        <div className="rounded-2xl border border-[#161616] bg-[#FCFCFB] p-4 shadow-lg">
          {asking ? (
            <div className="flex flex-col gap-2">
              <label htmlFor="prd-feedback" className="text-xs font-semibold text-[#161616]">What should change?</label>
              <textarea
                id="prd-feedback"
                value={feedback}
                onChange={(event) => setFeedback(event.target.value)}
                rows={3}
                placeholder="For example: add offline support to the PRD, and use PostgreSQL instead of SQLite."
                className="w-full rounded-lg border border-[#E7E6DF] bg-[#F4F3EE] p-2 text-xs text-[#161616] focus:border-[#161616] focus:outline-none"
              />
              <div className="flex items-center justify-end gap-2">
                <button type="button" onClick={() => setAsking(false)} className="rounded-lg px-3 py-1.5 text-xs text-[#5B5B5B] hover:text-[#161616]">Cancel</button>
                <button
                  type="button"
                  disabled={!feedback.trim()}
                  onClick={() => {
                    onRequestChanges(feedback.trim());
                    setFeedback('');
                    setAsking(false);
                  }}
                  className="rounded-lg bg-[#161616] px-4 py-1.5 text-xs font-medium text-[#FCFCFB] disabled:opacity-40"
                >
                  Send changes to the team
                </button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="max-w-md text-xs leading-relaxed text-[#5B5B5B]">
                Nothing is built until you accept. Accepting starts the sprints; asking for changes sends your note to the scrum master, who revises all three documents and asks again.
              </p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setAsking(true)}
                  className="flex items-center gap-1.5 rounded-xl border border-[#E7E6DF] bg-white px-4 py-2 text-xs font-medium text-[#161616] hover:bg-[#F4F3EE]"
                >
                  <MessageSquareWarning className="h-3.5 w-3.5" />
                  Request changes
                </button>
                <button
                  type="button"
                  onClick={() => onAccept(documents[0]?.id ?? 'art-prd')}
                  className="flex items-center gap-1.5 rounded-xl bg-[#161616] px-4 py-2 text-xs font-medium text-[#FCFCFB] shadow-md hover:bg-black"
                >
                  <ShieldCheck className="h-4 w-4 text-[#E60000]" />
                  Accept all documents and start building
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </motion.div>
  );
};
