import React from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { useScrum } from '../context/ScrumContext';
import { Odometer } from './common/Odometer';
import { ShieldAlert, Zap } from 'lucide-react';

export const TopBar: React.FC = () => {
  const {
    autopilot,
    setAutopilot,
    selectedMeet,
    activeTab,
    elapsedSeconds,
    remainingSeconds,
    formatTime,
    setIsSmeModalOpen,
    triggerDebate
  } = useScrum();

  const isUrgent = remainingSeconds < 120;

  const breadcrumbText = 
    activeTab === 'overview' ? `Sprint 03 / ${selectedMeet.title}` :
    activeTab === 'canvas' ? 'Sprint 03 / Multi-Agent Delegation Graph' :
    activeTab === 'meet' ? `Sprint 03 / ${selectedMeet.title}` :
    activeTab === 'artifacts' ? 'Sprint 03 / SDLC Deliverables & Version Diff' :
    'Sprint 03 / Sprint & Standup Timeline';

  return (
    <header className="h-[72px] bg-[#FFFFFF] border-b border-[#E2E0D9] px-6 flex items-center justify-between shrink-0 select-none z-30 relative shadow-[0_1px_2px_rgba(22,22,22,0.03)]">
      {/* Left: Mark & Brand Wordmark */}
      <div className="flex items-center gap-4 min-w-[280px]">
        {/* Geometric diamond with red corner accent */}
        <div className="relative w-5 h-5 flex items-center justify-center">
          <div className="w-4 h-4 bg-[#161616] rotate-45 rounded-[1px] relative shadow-xs">
            <span className="absolute top-0 right-0 w-1.5 h-1.5 bg-[#E60000] rounded-tl-[0.5px]" />
          </div>
        </div>

        <div className="flex items-baseline gap-2.5">
          <span className="font-bold text-[17px] tracking-tight text-[#161616]">
            CONTROL PLANE
          </span>
          <span className="text-[10px] font-semibold tracking-wider uppercase px-1.5 py-0.5 bg-[#F4F3EE] text-[#5B5B5B] rounded-[3px] border border-[#E2E0D9]">
            V2 DECK
          </span>
        </div>
      </div>

      {/* Center: Live Breadcrumb with AnimatePresence */}
      <div className="flex-1 flex items-center justify-center px-4 overflow-hidden">
        <AnimatePresence mode="wait">
          <motion.div
            key={breadcrumbText}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className="flex items-center gap-2 text-[13px] text-[#5B5B5B] truncate"
          >
            <span className="font-medium text-[#5B5B5B]">Fintech Clearing SDLC</span>
            <span className="text-[#C9C6BC]">/</span>
            <span className="font-semibold text-[#161616] truncate">{breadcrumbText}</span>
          </motion.div>
        </AnimatePresence>
      </div>

      {/* Center-Right & Right Controls */}
      <div className="flex items-center gap-3 min-w-[480px] justify-end">
        {/* Live Cluster Pill */}
        <div
          className={`flex items-center gap-3 px-3.5 py-1.5 rounded-full border transition-all duration-300 ${
            isUrgent
              ? 'bg-[#FDECEC] border-[#E60000] shadow-[0_0_24px_rgba(230,0,0,0.35)]'
              : 'bg-[#FCFCFB]/90 backdrop-blur-md border-[#E2E0D9] shadow-[0_0_0_1px_rgba(230,0,0,0.2),0_0_16px_rgba(230,0,0,0.12)]'
          }`}
        >
          {/* Pulsing Red Dot */}
          <div className="relative flex items-center justify-center w-2.5 h-2.5">
            <span className="absolute w-2.5 h-2.5 rounded-full bg-[#E60000] live-pulse" />
            <span className="relative w-2 h-2 rounded-full bg-[#E60000]" />
          </div>

          <span className="text-[10.5px] font-bold tracking-wider text-[#E60000] uppercase">
            LIVE
          </span>

          <div className="h-3 w-[1px] bg-[#E2E0D9]" />

          {/* Elapsed Time */}
          <div className="flex items-center gap-1.5 text-[12px] mono text-[#161616]">
            <span className="text-[10px] text-[#5B5B5B] uppercase font-sans font-medium">Elapsed</span>
            <Odometer value={formatTime(elapsedSeconds)} className="font-semibold" />
          </div>

          <div className="h-3 w-[1px] bg-[#E2E0D9]" />

          {/* Time Remaining */}
          <div className={`flex items-center gap-1.5 text-[12px] mono ${isUrgent ? 'text-[#E60000] font-bold' : 'text-[#5B5B5B]'}`}>
            <span className="text-[10px] uppercase font-sans font-medium">Left</span>
            <Odometer value={formatTime(remainingSeconds)} className="font-semibold" />
          </div>
        </div>

        {/* Business SME Directive Button */}
        <button
          onClick={() => setIsSmeModalOpen(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-semibold bg-[#F4F3EE] hover:bg-[#EDECE7] text-[#161616] border border-[#E2E0D9] rounded-[8px] transition-colors cursor-pointer active:scale-[0.98]"
          title="Intervene as Business SME to enforce compliance constraints"
        >
          <ShieldAlert className="w-3.5 h-3.5 text-[#0057B8]" />
          <span>SME Override</span>
        </button>

        {/* Quick Challenge Button */}
        <button
          onClick={triggerDebate}
          className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-semibold bg-[#F4F3EE] hover:bg-[#EDECE7] text-[#161616] border border-[#E2E0D9] rounded-[8px] transition-colors cursor-pointer active:scale-[0.98]"
          title="Inject an architectural challenge into the active meet"
        >
          <Zap className="w-3.5 h-3.5 text-[#E60000]" />
          <span>Inject Debate</span>
        </button>

        {/* Autopilot / Manual Segmented Toggle */}
        <div className="relative flex items-center bg-[#F4F3EE] p-1 rounded-full border border-[#E2E0D9]">
          <button
            onClick={() => setAutopilot(true)}
            className={`relative z-10 px-3 py-1 text-[11px] font-semibold tracking-wider uppercase transition-colors cursor-pointer ${
              autopilot ? 'text-[#FFFFFF]' : 'text-[#5B5B5B] hover:text-[#161616]'
            }`}
          >
            AUTOPILOT
          </button>
          <button
            onClick={() => setAutopilot(false)}
            className={`relative z-10 px-3 py-1 text-[11px] font-semibold tracking-wider uppercase transition-colors cursor-pointer ${
              !autopilot ? 'text-[#FFFFFF]' : 'text-[#5B5B5B] hover:text-[#161616]'
            }`}
          >
            MANUAL
          </button>

          {/* Sliding Pill Thumb */}
          <motion.div
            layout
            transition={{ type: 'spring', stiffness: 520, damping: 30, mass: 0.7 }}
            className={`absolute top-1 bottom-1 rounded-full ${
              autopilot ? 'left-1 w-[82px] bg-[#161616]' : 'left-[86px] w-[70px] bg-[#5B5B5B]'
            }`}
          />
        </div>
      </div>
    </header>
  );
};
