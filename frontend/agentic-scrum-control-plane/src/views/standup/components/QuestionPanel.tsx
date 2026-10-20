import { useState } from 'react';
import { participantName } from '../models/lookup';
import type { StandupParticipant, StandupQuestion } from '../models/standup';

/** What the Business SME is being asked. Answer with an option or in your own words; with the autopilot on, it answers too, and a person answering first simply wins. */
export function QuestionPanel({ questions, participants, autopilot, disabled, onAnswer }: {
  questions: StandupQuestion[]; participants: StandupParticipant[]; autopilot: boolean; disabled: boolean; onAnswer: (questionId: string, answer: string) => Promise<void> | void;
}) {
  return (
    <section aria-label="Questions for the Business SME" className="flex flex-col gap-2" data-testid="question-panel">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5B5B5B]">
        Questions {questions.length > 0 && <span className="ml-1 rounded-full bg-[#E60000] px-1.5 py-0.5 text-[10px] text-white" data-testid="open-question-count">{questions.length}</span>}
      </h2>
      {questions.length === 0 && <p className="text-[13px] text-[#8E8E8E]">Nothing is waiting for the Business SME.</p>}
      {questions.map((q) => <QuestionCard key={q.question_id} q={q} asker={participantName(participants, q.asked_by)} autopilot={autopilot} disabled={disabled} onAnswer={onAnswer} />)}
    </section>
  );
}

function QuestionCard({ q, asker, autopilot, disabled, onAnswer }: { q: StandupQuestion; asker: string; autopilot: boolean; disabled: boolean; onAnswer: (id: string, answer: string) => Promise<void> | void }) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const send = async (answer: string) => {
    if (!answer.trim() || busy) return;
    setBusy(true);
    try {
      await onAnswer(q.question_id, answer.trim());
      setText('');
    } finally {
      setBusy(false);
    }
  };
  return (
    <article data-testid="question-card" className="rounded-lg border border-[#E60000]/40 bg-white p-3 shadow-[0_0_0_2px_rgba(230,0,0,0.06)]">
      <div className="text-[11px] text-[#8E8E8E]">{asker} asks</div>
      <p className="mt-0.5 text-[13.5px] font-medium text-[#161616]">{q.text}</p>
      {q.options.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5" role="group" aria-label="Suggested answers">
          {q.options.map((option) => (
            <button
              key={option}
              type="button"
              disabled={disabled || busy}
              onClick={() => void send(option)}
              className="rounded-md border border-[#161616] px-2.5 py-1 text-[12px] font-medium text-[#161616] hover:bg-[#161616] hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
            >
              {option}{option === q.recommended ? ' (recommended)' : ''}
            </button>
          ))}
        </div>
      )}
      <form className="mt-2 flex gap-1.5" onSubmit={(e) => { e.preventDefault(); void send(text); }}>
        <label className="sr-only" htmlFor={`answer-${q.question_id}`}>Your answer</label>
        <input
          id={`answer-${q.question_id}`}
          value={text}
          disabled={disabled || busy}
          onChange={(e) => setText(e.target.value)}
          placeholder="Or answer in your own words"
          className="min-w-0 flex-1 rounded-md border border-[#E2E0D9] px-2 py-1.5 text-[12.5px] focus:border-[#161616] focus:outline-none disabled:bg-[#F4F3EE]"
        />
        <button type="submit" disabled={disabled || busy || !text.trim()} className="rounded-md bg-[#161616] px-3 py-1.5 text-[12px] font-semibold text-white disabled:opacity-40">Answer</button>
      </form>
      {autopilot && !disabled && <p className="mt-1.5 text-[11px] text-[#8E8E8E]">The autopilot will answer shortly. Answer now to take this one yourself.</p>}
    </article>
  );
}
