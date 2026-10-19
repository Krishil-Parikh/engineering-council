import React from 'react';
import { Agent, Skill } from '../../types';
import { Cpu, GitBranch, CheckCircle2 } from 'lucide-react';

interface RosterPanelProps {
  agents: Agent[];
  skills: Skill[];
}

export const RosterPanel: React.FC<RosterPanelProps> = ({ agents, skills }) => {
  return (
    <div className="w-full h-full flex flex-col justify-between py-1">
      <div className="flex items-center justify-between pb-3 border-b border-[#E7E6DF]">
        <div className="flex items-center gap-3">
          <span className="text-xs font-semibold text-[#161616]">
            Active Agent Bench ({agents.length} generic templates)
          </span>
          <span className="text-xs text-[#8E8E8E]">·</span>
          <span className="text-xs text-[#5B5B5B] font-mono">
            {skills.length} available skill definitions
          </span>
        </div>
        <span className="text-[11px] font-mono text-[#8E8E8E]">
          Single-template architecture
        </span>
      </div>

      {/* Agents Horizontal Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3 my-3">
        {agents.map((agent) => (
          <div
            key={agent.id}
            className="p-3 rounded-xl bg-[#F4F3EE] border border-[#E7E6DF] flex flex-col justify-between text-xs"
          >
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-1.5">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      agent.status === 'active'
                        ? 'bg-[#E60000]'
                        : agent.status === 'reviewing'
                        ? 'bg-[#161616]'
                        : 'bg-[#8E8E8E]'
                    }`}
                  />
                  <span className="font-semibold text-[#161616]">{agent.name}</span>
                </div>
                <span className="text-[10px] font-mono px-1 rounded bg-[#FCFCFB] text-[#5B5B5B]">
                  {agent.claimedSkill || 'Idle'}
                </span>
              </div>
              <p className="text-[11px] text-[#5B5B5B] line-clamp-2 leading-tight">
                {agent.currentTask}
              </p>
            </div>

            <div className="mt-2 pt-2 border-t border-[#E7E6DF] flex items-center justify-between text-[10px] font-mono text-[#8E8E8E]">
              <span className="truncate">{agent.activeBranch}</span>
              <span>{agent.contextUsagePercent}%</span>
            </div>
          </div>
        ))}
      </div>

      {/* Skill Library Strip */}
      <div className="pt-2 border-t border-[#E7E6DF] flex items-center gap-4 text-xs text-[#5B5B5B] overflow-x-auto">
        <span className="font-mono text-[10.5px] uppercase text-[#8E8E8E] shrink-0">
          Claimed Skills:
        </span>
        {skills.map((skill) => (
          <div
            key={skill.id}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-[#F4F3EE] border border-[#E7E6DF] shrink-0"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-[#161616]" />
            <span className="font-medium text-[#161616]">{skill.name}</span>
            <span className="font-mono text-[10.5px] text-[#8E8E8E]">
              ({skill.claimedCount})
            </span>
            {skill.isNew && (
              <span className="text-[9px] font-mono uppercase bg-[#161616] text-[#FCFCFB] px-1 rounded">
                new
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};
