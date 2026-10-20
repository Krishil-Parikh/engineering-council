import type { Highlight } from './script';

const TONE: Record<Highlight['kind'], string> = {
  question: 'border-[#1F5FA8]/50', decision: 'border-[#0F8A4B]/50', intervention: 'border-[#7B3FA0]/50', risk: 'border-[#B8860B]/60', blocked: 'border-[#E60000]/50', approval: 'border-[#E60000]/40',
};

/** The moments worth jumping to in a replay, as chips: click one to go there. */
export function HighlightsBar({ highlights, position, onSeek }: { highlights: Highlight[]; position: number; onSeek: (sequence: number) => void }) {
  if (highlights.length === 0) return null;
  return (
    <div data-testid="highlights" role="group" aria-label="Highlights" className="flex max-h-[66px] flex-wrap items-center gap-1.5 overflow-y-auto">
      <span className="text-[11.5px] text-[#8E8E8E]">Highlights</span>
      {highlights.map((h) => (
        <button
          key={`${h.sequence}-${h.kind}`}
          type="button"
          onClick={() => onSeek(h.sequence)}
          aria-current={h.sequence === position ? 'true' : undefined}
          className={`rounded-full border bg-white px-2.5 py-0.5 text-[11.5px] text-[#161616] hover:bg-[#F4F3EE] ${TONE[h.kind]} ${h.sequence === position ? 'bg-[#161616] text-white hover:bg-[#161616]' : ''}`}
        >
          {h.label}
        </button>
      ))}
    </div>
  );
}
