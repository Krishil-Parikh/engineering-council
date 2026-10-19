import React from 'react';
import type { WorkspaceSprint } from '../../domain/types';

interface SprintsPanelProps {
  sprints: WorkspaceSprint[];
  totalMerged: number;
}

/** The real sprints of this run: what each is doing and how much of it is delivered. */
export const SprintsPanel: React.FC<SprintsPanelProps> = ({ sprints, totalMerged }) => (
  <div className="w-full h-full overflow-y-auto py-1 flex flex-col gap-3">
    <div className="flex items-center justify-between text-xs font-mono text-[#5B5B5B]">
      <span>{sprints.length === 0 ? 'No sprint has started yet' : `${sprints.length} sprint${sprints.length === 1 ? '' : 's'}`}</span>
      <span>{totalMerged} feature{totalMerged === 1 ? '' : 's'} merged in total</span>
    </div>
    {sprints.map((sprint) => (
      <div key={sprint.id} className="p-3 rounded-xl border border-[#E7E6DF] bg-[#FCFCFB]">
        <div className="flex items-center justify-between gap-3 text-xs">
          <span className="font-semibold text-[#161616] truncate">{sprint.title}</span>
          <span className="font-mono text-[#5B5B5B] shrink-0">
            {sprint.status === 'active' ? (sprint.phase || 'running') : 'closed'} · {Math.round(sprint.progress)}%
          </span>
        </div>
        <div className="mt-2 h-1.5 w-full bg-[#EAE9E2] rounded-full overflow-hidden">
          <div className="h-full bg-[#161616] rounded-full" style={{ width: `${Math.max(0, Math.min(100, sprint.progress))}%` }} />
        </div>
      </div>
    ))}
  </div>
);
