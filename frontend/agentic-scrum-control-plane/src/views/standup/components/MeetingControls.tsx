import type { ControlMode } from '../models/meeting-status';

/** Who answers the team's product questions: the Business SME (you), or the autopilot SME. Documents and approvals always wait for you, whichever is chosen. */
export function MeetingControls({ mode, disabled, onChange }: { mode: ControlMode; disabled: boolean; onChange: (mode: ControlMode) => void }) {
  const options: { value: ControlMode; label: string; hint: string }[] = [
    { value: 'human', label: 'I answer', hint: 'Every question waits for you.' },
    { value: 'autopilot', label: 'Autopilot SME', hint: 'Answers product questions for you.' },
  ];
  return (
    <section aria-label="Business SME control" data-testid="meeting-controls" className="flex flex-col gap-1.5">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5B5B5B]">Business SME</h2>
      <div role="radiogroup" aria-label="Who answers product questions" className="inline-flex rounded-lg border border-[#E2E0D9] bg-[#F4F3EE] p-1">
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={mode === o.value}
            disabled={disabled}
            title={o.hint}
            onClick={() => mode !== o.value && onChange(o.value)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
                e.preventDefault();
                onChange(o.value === 'human' ? 'autopilot' : 'human');
              }
            }}
            className={`rounded-md px-3 py-1.5 text-[12px] font-semibold transition-colors disabled:opacity-40 ${mode === o.value ? 'bg-[#161616] text-white' : 'text-[#5B5B5B] hover:text-[#161616]'}`}
          >
            {o.label}
          </button>
        ))}
      </div>
      <p className="text-[11px] text-[#8E8E8E]">
        {mode === 'autopilot' ? 'The autopilot answers product questions only. Documents and approvals still wait for you.' : 'You answer every question. Switch to the autopilot when you step away.'}
      </p>
    </section>
  );
}
