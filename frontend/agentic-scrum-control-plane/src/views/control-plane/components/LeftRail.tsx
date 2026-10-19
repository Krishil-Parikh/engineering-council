import React from 'react';
import { motion, LayoutGroup } from 'motion/react';
import { useScrum } from '../context/ScrumContext';
import { Sparkles, Layers, Cpu } from 'lucide-react';
import { Agent } from '../types';

export const LeftRail: React.FC = () => {
  const { agents, selectedAgent, setSelectedAgent, skills } = useScrum();

  return (
    <aside className="w-[232px] bg-[#F4F3EE] border-r border-[#E2E0D9] flex flex-col shrink-0 select-none overflow-y-auto overflow-x-hidden">
      {/* Agents Header */}
      <div className="px-4 py-3 border-b border-[#E2E0D9] flex items-center justify-between">
        <span className="text-[11.5px] font-bold tracking-wider uppercase text-[#5B5B5B]">
          AGENTS
        </span>
        <div className="flex items-center gap-1.5 text-[11px] mono font-semibold text-[#5B5B5B]">
          <span>{agents.length}</span>
          <span className="text-[#C9C6BC]">·</span>
          <span className="text-[#0F8A4B]">Active</span>
        </div>
      </div>

      {/* Agent Roster with Framer Motion layout animation */}
      <div className="p-2.5 flex flex-col gap-1.5 flex-1">
        <LayoutGroup id="agent-roster">
          {agents.map(agent => {
            const isLive = agent.isLive;
            const isSelected = selectedAgent?.id === agent.id;

            if (isLive) {
              // Promoted Glass Card for Active Speaking/Acting Agent
              return (
                <motion.div
                  layout
                  layoutId={`agent-item-${agent.id}`}
                  key={agent.id}
                  onClick={() => setSelectedAgent(agent)}
                  transition={{ type: 'spring', stiffness: 480, damping: 32, mass: 0.8 }}
                  className={`relative p-3 rounded-[12px] bg-[#FFFFFF]/90 backdrop-blur-md cursor-pointer transition-shadow border border-[#E60000] shadow-[0_0_0_1px_rgba(230,0,0,0.3),0_0_24px_rgba(230,0,0,0.18)] ${
                    isSelected ? 'ring-2 ring-[#161616]' : ''
                  }`}
                >
                  {/* Top row: Status indicator + Name + Role */}
                  <div className="flex items-center justify-between gap-1.5 mb-1.5">
                    <div className="flex items-center gap-2 min-w-0">
                      <div className="relative flex items-center justify-center w-2.5 h-2.5 shrink-0">
                        <span className="absolute w-2.5 h-2.5 rounded-full bg-[#E60000] live-pulse" />
                        <span className="relative w-2 h-2 rounded-full bg-[#E60000]" />
                      </div>
                      <span className="font-bold text-[13px] text-[#161616] truncate">
                        {agent.name}
                      </span>
                    </div>

                    <span className="text-[9.5px] font-bold tracking-wider uppercase px-1.5 py-0.5 rounded-[4px] bg-[#FDECEC] text-[#E60000] border border-[#F9CFCF] shrink-0">
                      SPEAKING
                    </span>
                  </div>

                  {/* Role Title */}
                  <div className="text-[11px] font-medium text-[#5B5B5B] truncate mb-2">
                    {agent.roleTitle}
                  </div>

                  {/* Micro Sparkline visualization */}
                  <div className="flex items-end justify-between gap-[3px] h-6 bg-[#F4F3EE] p-1.5 rounded-[6px] border border-[#E2E0D9]">
                    {agent.sparkline.map((val, idx) => (
                      <div
                        key={idx}
                        className="w-full bg-[#161616] rounded-xs transition-all duration-300"
                        style={{ height: `${Math.max(15, (val / 100) * 100)}%` }}
                      />
                    ))}
                  </div>

                  {/* Active Task line */}
                  <div className="mt-2 text-[10.5px] leading-[14px] text-[#5B5B5B] line-clamp-2">
                    {agent.activeTask}
                  </div>

                  {/* Token Rate & Subagents */}
                  <div className="mt-2 pt-2 border-t border-[#EDECE7] flex items-center justify-between text-[10px] mono text-[#5B5B5B]">
                    <span>{agent.tokensVelocity} tok/s</span>
                    {agent.subAgentsCount ? (
                      <span className="font-medium text-[#161616]">+{agent.subAgentsCount} sub-agents</span>
                    ) : (
                      <span>{agent.allocatedMemory}</span>
                    )}
                  </div>
                </motion.div>
              );
            }

            // Quiet 36px row for resting agents
            return (
              <motion.div
                layout
                layoutId={`agent-item-${agent.id}`}
                key={agent.id}
                onClick={() => setSelectedAgent(agent)}
                transition={{ type: 'spring', stiffness: 480, damping: 32, mass: 0.8 }}
                className={`group h-[38px] px-2.5 rounded-[8px] flex items-center justify-between cursor-pointer transition-colors ${
                  isSelected
                    ? 'bg-[#EDECE7] text-[#161616] font-semibold'
                    : 'hover:bg-[#EDECE7]/60 text-[#5B5B5B] hover:text-[#161616]'
                }`}
              >
                <div className="flex items-center gap-2 min-w-0">
                  {/* Status dot */}
                  <div className="w-2 h-2 rounded-full border border-[#C9C6BC] shrink-0 flex items-center justify-center">
                    {agent.status === 'orchestrating' ? (
                      <div className="w-1.5 h-1.5 rounded-full bg-[#161616]" />
                    ) : agent.status === 'debating' ? (
                      <div className="w-1.5 h-1.5 rounded-full bg-[#B27000]" />
                    ) : (
                      <div className="w-1.5 h-1.5 rounded-full bg-transparent" />
                    )}
                  </div>

                  <span className="text-[12px] truncate font-medium group-hover:text-[#161616]">
                    {agent.name}
                  </span>
                </div>

                <span className="text-[10.5px] text-[#5B5B5B]/80 font-normal shrink-0">
                  {agent.role === 'scrum_master' ? 'Scrum' : agent.role.charAt(0).toUpperCase() + agent.role.slice(1)}
                </span>
              </motion.div>
            );
          })}
        </LayoutGroup>
      </div>

      {/* Skills Section with Solid/Hollow Square Indicators */}
      <div className="mt-auto border-t border-[#E2E0D9] p-3 bg-[#F4F3EE]">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[11px] font-bold tracking-wider uppercase text-[#5B5B5B]">
            SKILLS BENCH
          </span>
          <span className="text-[10px] mono text-[#5B5B5B]">5 mapped</span>
        </div>

        <div className="flex flex-col gap-1.5">
          {skills.map(skill => (
            <div key={skill.id} className="flex items-center justify-between text-[11.5px] text-[#5B5B5B] py-0.5">
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-[#161616]">
                  {skill.claimedCount > 0 ? '▪' : '▫'}
                </span>
                <span className="font-medium text-[#161616]">{skill.name}</span>
              </div>
              <span className="text-[10.5px] mono font-semibold text-[#5B5B5B] bg-[#EDECE7] px-1.5 py-0.2 rounded-[3px]">
                ×{skill.claimedCount}
              </span>
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
};
