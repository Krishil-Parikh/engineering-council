import React, { useState } from 'react';
import { ShieldAlert, Send } from 'lucide-react';
import type { WorkspaceMessage, WorkspaceQuestion } from '../../domain/types';

interface PendingDecisionsProps {
  questions: WorkspaceMessage[];
  /** Which kinds of question this panel shows (the phase screens show the others themselves). */
  kinds: WorkspaceQuestion['kind'][];
  onAnswer: (message: WorkspaceMessage, text: string) => void;
}

function DecisionCard({ message, onAnswer }: { message: WorkspaceMessage; onAnswer: PendingDecisionsProps['onAnswer'] }) {
  const question = message.question as WorkspaceQuestion;
  const [reply, setReply] = useState('');
  const options = question.options && question.options.length ? question.options : ['Approve', 'Decline'];

  const choose = (option: string) => {
    // "Decline" travels with whatever the person wrote as the reason, so the team knows what to change.
    const text = /^decline$/i.test(option) && reply.trim() ? `Decline: ${reply.trim()}` : option;
    onAnswer(message, text);
    setReply('');
  };

  return (
    <div className="rounded-2xl border border-[#161616] bg-[#FCFCFB] p-4 shadow-xl" data-testid="decision-card">
      <div className="mb-2 flex items-center gap-2">
        <ShieldAlert className="h-3.5 w-3.5 text-[#E60000]" />
        <span className="font-mono text-[10px] font-semibold uppercase tracking-wider text-[#161616]">Needs your decision</span>
      </div>
      <h3 className="mb-1 text-[13px] font-semibold leading-snug text-[#161616]">{message.text}</h3>
      {question.context && (
        <p className="mb-3 max-h-40 overflow-y-auto whitespace-pre-wrap text-[11.5px] leading-relaxed text-[#5B5B5B]">{question.context}</p>
      )}
      <div className="mb-3 flex flex-wrap gap-2">
        {options.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => choose(option)}
            className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
              /^decline$/i.test(option) ? 'border border-[#E60000]/40 bg-white text-[#8F0000] hover:bg-[#E60000]/5' : 'bg-[#161616] text-[#FCFCFB] hover:bg-black'
            }`}
          >
            {option}
            {question.recommended === option ? ' (recommended)' : ''}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-2 border-t border-[#E7E6DF] pt-2">
        <input
          value={reply}
          onChange={(event) => setReply(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && reply.trim()) {
              onAnswer(message, reply.trim());
              setReply('');
            }
          }}
          placeholder="Or answer in your own words, or say what to change…"
          aria-label="Your answer"
          className="flex-1 rounded-lg border border-[#E7E6DF] bg-[#F4F3EE] px-3 py-1.5 text-xs text-[#161616] focus:border-[#161616] focus:outline-none"
        />
        <button
          type="button"
          aria-label="Send answer"
          disabled={!reply.trim()}
          onClick={() => {
            onAnswer(message, reply.trim());
            setReply('');
          }}
          className="rounded-lg bg-[#161616] p-2 text-[#FCFCFB] disabled:opacity-40"
        >
          <Send className="h-3 w-3" />
        </button>
      </div>
    </div>
  );
}

/** Decisions the backend is waiting on, shown wherever the person happens to be (live backend only). */
export const PendingDecisions: React.FC<PendingDecisionsProps> = ({ questions, kinds, onAnswer }) => {
  const shown = questions.filter((message) => message.question && kinds.includes(message.question.kind));
  if (shown.length === 0) return null;
  return (
    <section
      role="region"
      aria-label="Decisions waiting for you"
      className="fixed bottom-4 right-4 z-[90] flex max-h-[80vh] w-[min(420px,calc(100vw-2rem))] flex-col gap-3 overflow-y-auto"
    >
      {shown.map((message) => (
        <DecisionCard key={message.id} message={message} onAnswer={onAnswer} />
      ))}
    </section>
  );
};
