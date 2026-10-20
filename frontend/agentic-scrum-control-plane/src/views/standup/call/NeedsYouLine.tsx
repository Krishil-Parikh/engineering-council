import { waitedLabel } from './script';

export interface WaitingItem {
  meetingId: string;
  title: string;
  /** The question or the approval, word for word (empty when the list only knows how many are waiting). */
  text: string;
  count: number;
  waitedSeconds: number | null;
}

/** One red line across the top of the call, always in view: who is waiting for the Business SME, what for, and for how long. A click (or G) goes there. */
export function NeedsYouLine({ items, onGo }: { items: WaitingItem[]; onGo: (meetingId: string) => void }) {
  if (items.length === 0) return null;
  const first = items[0];
  const others = items.slice(1).reduce((n, i) => n + i.count, 0) + (first.count - 1);
  return (
    <button
      type="button"
      data-testid="needs-you"
      onClick={() => onGo(first.meetingId)}
      title={items.map((i) => `${i.title}${i.text ? ` · ${i.text}` : ''}`).join('\n')}
      className="flex w-full items-center gap-2 border-b border-[#FF8A80] bg-[#C0392B] px-3 py-1.5 text-left text-[12.5px] font-semibold text-white hover:brightness-110 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-3px] focus-visible:outline-white"
    >
      <span className="min-w-0 flex-1 truncate">
        <span aria-hidden>✋ </span><b>{first.title}</b> needs you{first.text ? ` · ${first.text.replace(/\s+/g, ' ').slice(0, 120)}` : ''}{first.waitedSeconds !== null ? ` · ${waitedLabel(first.waitedSeconds)}` : ''}
      </span>
      {others > 0 && <span className="shrink-0 rounded-full bg-black/25 px-2 text-[11.5px]">+{others}</span>}
      <span className="shrink-0 text-[11px] font-medium opacity-80" aria-hidden>G</span>
    </button>
  );
}
