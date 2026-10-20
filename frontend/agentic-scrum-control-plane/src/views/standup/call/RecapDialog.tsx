import { useState } from 'react';
import type { MeetingEventWire } from '../models/meeting-events';
import type { StandupView } from '../models/standup';
import { busiest, recapCounts, recapMarkdown } from './script';

/** The meeting at a glance: how much was said, who spoke most, what was decided and what is left to do. "Copy as Markdown" puts the notes on the clipboard. */
export function RecapDialog({ view, events, onClose }: { view: StandupView; events: readonly MeetingEventWire[]; onClose: () => void }) {
  const counts = recapCounts(view, events);
  const markdown = recapMarkdown(view);
  const [copied, setCopied] = useState<'idle' | 'ok' | 'failed'>('idle');
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(markdown);
      setCopied('ok');
    } catch {
      setCopied('failed');
    }
    setTimeout(() => setCopied('idle'), 2000);
  };
  const kpis: [number, string][] = [[counts.people, 'people'], [counts.statements, 'lines said'], [counts.challenges, 'challenges'], [counts.questions, 'questions'], [counts.decisions, 'decisions'], [counts.actions, 'action items'], [counts.risks, 'risks']];
  return (
    <div role="dialog" aria-modal="true" aria-label="Meeting recap" data-testid="recap" className="fixed inset-0 z-[120] flex items-center justify-center bg-black/50 p-4">
      <div className="flex max-h-[88vh] w-full max-w-2xl flex-col rounded-xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-[#E2E0D9] px-4 py-2.5">
          <h2 className="text-[14px] font-semibold">Recap · {view.title}</h2>
          <button type="button" onClick={onClose} autoFocus className="rounded-md border border-[#E2E0D9] px-2.5 py-1 text-[12px]">Close</button>
        </div>
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
            {kpis.map(([n, label]) => <div key={label} className="rounded-lg border border-[#E2E0D9] bg-[#F4F3EE] p-2 text-center"><b data-testid={`kpi-${label.replace(/ /g, '-')}`} className="block text-[18px]">{n}</b><span className="text-[11px] text-[#5B5B5B]">{label}</span></div>)}
          </div>
          {view.summary && <p className="rounded-lg bg-[#F4F3EE] p-3 text-[13px]">{view.summary}</p>}
          {busiest(view, events).length > 0 && (
            <section aria-label="Who spoke most">
              <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-[#5B5B5B]">Who spoke most</h3>
              <ul className="space-y-0.5 text-[12.5px]">{busiest(view, events).map(({ person, lines }) => <li key={person.participant_id} className="flex justify-between"><span>{person.display_name}</span><span className="font-mono text-[#5B5B5B]">{lines}</span></li>)}</ul>
            </section>
          )}
          {view.decisions.length > 0 && <section aria-label="Decisions"><h3 className="mb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-[#5B5B5B]">Decisions</h3><ul className="list-disc space-y-0.5 pl-5 text-[12.5px]">{view.decisions.map((d) => <li key={d.decision_id}><b>{d.title}</b> — {d.status}{d.selected_option ? `: ${d.selected_option}` : ''}</li>)}</ul></section>}
          {view.action_items.length > 0 && <section aria-label="Action items"><h3 className="mb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-[#5B5B5B]">Action items</h3><ul className="list-disc space-y-0.5 pl-5 text-[12.5px]">{view.action_items.map((a) => <li key={a.action_item_id}>{a.description} <span className="text-[#8E8E8E]">({a.status.replace('_', ' ')})</span></li>)}</ul></section>}
        </div>
        <div className="flex items-center justify-between border-t border-[#E2E0D9] px-4 py-2.5">
          <span role="status" className="text-[12px] text-[#5B5B5B]">{copied === 'ok' ? 'Copied.' : copied === 'failed' ? 'Copy failed: select the notes below instead.' : ''}</span>
          <button type="button" onClick={() => void copy()} className="rounded-md bg-[#161616] px-3 py-1.5 text-[12px] font-semibold text-white">Copy as Markdown</button>
        </div>
        {copied === 'failed' && <textarea readOnly aria-label="Notes" value={markdown} className="m-3 h-32 rounded-md border border-[#E2E0D9] p-2 font-mono text-[11.5px]" />}
      </div>
    </div>
  );
}
