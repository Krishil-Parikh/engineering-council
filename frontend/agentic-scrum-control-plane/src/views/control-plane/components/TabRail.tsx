import React, { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { LayoutDashboard, Network, MessageSquare, FileText, Activity } from 'lucide-react';
import { useScrum } from '../context/ScrumContext';
import { TabType } from '../types';

interface NavItem {
  id: TabType;
  label: string;
  icon: React.ElementType;
  badge?: string;
}

const NAV_ITEMS: NavItem[] = [
  { id: 'overview', label: 'Overview — The Command Deck', icon: LayoutDashboard },
  { id: 'canvas', label: 'Canvas — Agent Delegation Graph', icon: Network },
  { id: 'meet', label: 'Meet — Live Transcript & Debate', icon: MessageSquare, badge: 'LIVE' },
  { id: 'artifacts', label: 'Artifacts — PRD & Architecture Diffs', icon: FileText },
  { id: 'timeline', label: 'Timeline — Sprints & Standups', icon: Activity }
];

export const TabRail: React.FC = () => {
  const { activeTab, setActiveTab } = useScrum();
  const [hoveredTab, setHoveredTab] = useState<string | null>(null);

  return (
    <aside className="w-[64px] bg-[#FFFFFF] border-r border-[#E2E0D9] flex flex-col items-center py-4 shrink-0 z-20 select-none">
      <div className="flex flex-col gap-2.5 w-full items-center">
        {NAV_ITEMS.map(item => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;
          const isHovered = hoveredTab === item.id;

          return (
            <div key={item.id} className="relative group w-full flex justify-center">
              <button
                onClick={() => setActiveTab(item.id)}
                onMouseEnter={() => setHoveredTab(item.id)}
                onMouseLeave={() => setHoveredTab(null)}
                className={`relative w-[44px] h-[44px] rounded-[8px] flex items-center justify-center transition-all cursor-pointer ${
                  isActive
                    ? 'bg-[#F4F3EE] text-[#161616]'
                    : 'text-[#5B5B5B] hover:text-[#161616] hover:bg-[#F4F3EE]/60'
                }`}
                aria-label={item.label}
              >
                {/* 3px Active Indicator Bar on Left Edge */}
                {isActive && (
                  <motion.div
                    layoutId="tab-active-indicator"
                    transition={{ type: 'spring', stiffness: 500, damping: 35 }}
                    className="absolute left-[-10px] top-[6px] bottom-[6px] w-[3px] bg-[#E60000] rounded-r-[2px]"
                  />
                )}

                <Icon className={`w-5 h-5 transition-transform ${isActive ? 'scale-105' : 'group-hover:scale-105'}`} />

                {/* Badge if any */}
                {item.badge && (
                  <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-[#E60000] ring-2 ring-[#FFFFFF]" />
                )}
              </button>

              {/* High-craft Tooltip with AnimatePresence */}
              <AnimatePresence>
                {isHovered && (
                  <motion.div
                    initial={{ opacity: 0, x: 8, scale: 0.96 }}
                    animate={{ opacity: 1, x: 0, scale: 1 }}
                    exit={{ opacity: 0, x: 6, scale: 0.96 }}
                    transition={{ duration: 0.15, ease: [0.16, 1, 0.3, 1] }}
                    className="absolute left-[68px] top-1/2 -translate-y-1/2 z-50 px-3 py-1.5 bg-[#161616] text-[#FFFFFF] text-[11.5px] font-medium tracking-tight rounded-[6px] shadow-lg whitespace-nowrap pointer-events-none flex items-center gap-2"
                  >
                    <span>{item.label}</span>
                    {item.badge && (
                      <span className="text-[9px] font-bold text-[#E60000] uppercase bg-[#E60000]/20 px-1 py-0.2 rounded-[2px]">
                        {item.badge}
                      </span>
                    )}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>

      {/* Subtle bottom indicator */}
      <div className="mt-auto flex flex-col items-center gap-2">
        <div className="w-1.5 h-1.5 rounded-full bg-[#0F8A4B]" title="Subsystem Consensus Healthy" />
        <span className="text-[9px] mono text-[#C9C6BC]">v2.4</span>
      </div>
    </aside>
  );
};
