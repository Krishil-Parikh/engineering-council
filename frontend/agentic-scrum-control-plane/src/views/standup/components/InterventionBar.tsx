import { useState } from 'react';

/** Interrupt or redirect: say something to the team. It reaches them the way a directive typed into the control plane does. */
export function InterventionBar({ disabled, note, onSend }: { disabled: boolean; note?: string | null; onSend: (text: string) => Promise<string | undefined> | void }) {
  const [text, setText] = useState('');
  const [reply, setReply] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);
  return (
    <form
      aria-label="Say something to the team"
      data-testid="intervention-bar"
      className="flex flex-col gap-1.5"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!text.trim() || busy) return;
        setBusy(true);
        try {
          setReply((await onSend(text.trim())) ?? undefined);
          setText('');
        } finally {
          setBusy(false);
        }
      }}
    >
      <label htmlFor="standup-intervene" className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5B5B5B]">Interrupt or redirect</label>
      <div className="flex gap-1.5">
        <input
          id="standup-intervene"
          value={text}
          disabled={disabled || busy}
          onChange={(e) => setText(e.target.value)}
          placeholder={disabled ? 'This meeting is over' : 'Tell the team something…'}
          className="min-w-0 flex-1 rounded-md border border-[#E2E0D9] px-2 py-1.5 text-[12.5px] focus:border-[#161616] focus:outline-none disabled:bg-[#F4F3EE]"
        />
        <button type="submit" disabled={disabled || busy || !text.trim()} className="rounded-md border border-[#161616] px-3 py-1.5 text-[12px] font-semibold text-[#161616] hover:bg-[#161616] hover:text-white disabled:opacity-40">Send</button>
      </div>
      {(reply || note) && <p role="status" className="text-[11px] text-[#5B5B5B]">{reply ?? note}</p>}
    </form>
  );
}
