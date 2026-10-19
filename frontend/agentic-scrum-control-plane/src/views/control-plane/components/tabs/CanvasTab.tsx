import React from 'react';
import { motion } from 'motion/react';
import { DelegationCanvas } from '../canvas/DelegationCanvas';
import { useScrum } from '../../context/ScrumContext';
import { Network, Zap, CheckCircle2, ShieldCheck, ArrowRight } from 'lucide-react';

export const CanvasTab: React.FC = () => {
  const { edges, agents, selectedAgent } = useScrum();
  const activeEdgeCount = edges.filter(e => e.isActive).length;

  return (
    <div className="flex-1 flex flex-col h-full relative select-none overflow-hidden">
      {/* Canvas Top Status Strip */}
      <div className="h-10 px-6 bg-[#FFFFFF] border-b border-[#E2E0D9] flex items-center justify-between z-10 shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-[12px] font-bold text-[#161616]">
            <Network className="w-4 h-4 text-[#161616]" />
            <span>TOPOLOGY & DELEGATION FABRIC</span>
          </div>

          <div className="h-3 w-[1px] bg-[#E2E0D9]" />

          <div className="flex items-center gap-2 text-[11px] mono text-[#5B5B5B]">
            <span className="flex items-center gap-1 text-[#E60000] font-semibold">
              <span className="w-2 h-2 rounded-full bg-[#E60000] live-pulse" />
              {activeEdgeCount} Active Transmissions
            </span>
            <span className="text-[#C9C6BC]">·</span>
            <span>Raft WAL Quorum 3-Node</span>
            <span className="text-[#C9C6BC]">·</span>
            <span>Zurich & Geneva Multi-Zone</span>
          </div>
        </div>

        <div className="flex items-center gap-2 text-[11px] text-[#5B5B5B]">
          <span className="text-[10.5px]">Click any node to activate</span>
          <span className="font-semibold text-[#161616] bg-[#F4F3EE] px-1.5 py-0.5 rounded-[4px] border border-[#E2E0D9]">
            Focus Mode
          </span>
        </div>
      </div>

      {/* Main Full-Bleed Delegation Canvas */}
      <div className="flex-1 relative overflow-hidden bg-[#FCFCFB]">
        <DelegationCanvas isMini={false} />
      </div>
    </div>
  );
};
