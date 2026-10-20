import { participantName } from '../models/lookup';
import type { StandupDependency, StandupParticipant, StandupRisk } from '../models/standup';

export function RiskDependencyPanel({ risks, dependencies, participants }: { risks: StandupRisk[]; dependencies: StandupDependency[]; participants: StandupParticipant[] }) {
  if (risks.length === 0 && dependencies.length === 0) return null;
  return (
    <section aria-label="Risks and dependencies" data-testid="risk-panel" className="flex flex-col gap-2">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5B5B5B]">Risks and dependencies</h2>
      <ul className="space-y-1.5" role="list">
        {risks.map((r) => (
          <li key={r.risk_id} data-testid="risk" className="rounded-lg border border-[#B8860B]/40 bg-[#FFF7E0] p-2.5 text-[12.5px] text-[#4B3600]">
            <strong className="mr-1 uppercase text-[10.5px] tracking-[0.1em]">Risk · {r.severity}</strong>{r.text}
          </li>
        ))}
        {dependencies.map((d) => (
          <li key={d.dependency_id} data-testid="dependency" className="rounded-lg border border-[#E2E0D9] bg-white p-2.5 text-[12.5px] text-[#161616]">
            <strong className="mr-1 uppercase text-[10.5px] tracking-[0.1em] text-[#5B5B5B]">Dependency</strong>{d.text}
            {(d.from_id || d.to_id) && <span className="ml-1 text-[11px] text-[#8E8E8E]">({participantName(participants, d.from_id)} → {participantName(participants, d.to_id)})</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}
