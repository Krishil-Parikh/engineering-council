import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Check, ArrowRight } from 'lucide-react';
import { PhaseId } from '../types';

export interface SpineProps {
  currentActivePhase: PhaseId; // The actual live phase of the system
  viewingPhase: PhaseId; // The phase currently displayed on focus stage
  completedPhases: PhaseId[];
  onSelectPhase: (phase: PhaseId) => void;
  onReturnToLive: () => void;
}

export const PHASES: { id: PhaseId; label: string; index: number }[] = [
  { id: 'kickoff', label: 'Kickoff', index: 0 },
  { id: 'brainstorm', label: 'Brainstorm', index: 1 },
  { id: 'prd', label: 'PRD', index: 2 },
  { id: 'build', label: 'Build', index: 3 },
  { id: 'review', label: 'Review', index: 4 },
  { id: 'ship', label: 'Ship', index: 5 },
];

export const Spine: React.FC<SpineProps> = ({
  currentActivePhase,
  viewingPhase,
  completedPhases,
  onSelectPhase,
  onReturnToLive,
}) => {
  const [hoveredPhase, setHoveredPhase] = useState<PhaseId | null>(null);

  const isHistorical = viewingPhase !== currentActivePhase;
  const currentActiveIndex = PHASES.findIndex((p) => p.id === currentActivePhase);

  return (
    <aside className="w-[88px] shrink-0 border-r border-[#E7E6DF] bg-[#FCFCFB] flex flex-col items-center py-8 select-none relative z-30 min-h-[calc(100vh-56px)]">
      {/* Floating 'Return to live' pill if viewing history */}
      {isHistorical && (
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          className="absolute -top-1 left-24 z-50 whitespace-nowrap"
        >
          <button
            onClick={onReturnToLive}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-[#161616] text-[#FCFCFB] text-xs font-medium shadow-md hover:bg-black transition-transform active:scale-95"
          >
            <span>Return to live</span>
            <span className="w-1.5 h-1.5 rounded-full bg-[#E60000] animate-ping" />
            <ArrowRight className="w-3 h-3 text-[#FCFCFB]" />
          </button>
        </motion.div>
      )}

      {/* Vertical Spine Rail */}
      <div className="flex-1 flex flex-col items-center justify-between relative w-full my-4">
        {/* SVG animated connecting line */}
        <div className="absolute top-4 bottom-4 left-1/2 -translate-x-1/2 w-[2px] pointer-events-none">
          {/* Base background line */}
          <div className="w-full h-full bg-[#E7E6DF]" />
          {/* Animated active progress fill line */}
          <motion.div
            className="absolute top-0 left-0 w-full bg-[#161616] origin-top"
            animate={{
              height: `${(Math.max(0, currentActiveIndex) / (PHASES.length - 1)) * 100}%`,
            }}
            transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
          />
        </div>

        {/* Phase Nodes */}
        {PHASES.map((phase) => {
          const isComplete = completedPhases.includes(phase.id);
          const isLiveActive = phase.id === currentActivePhase;
          const isCurrentlyViewing = phase.id === viewingPhase;
          const isAccessible = isComplete || isLiveActive;
          const isHovered = hoveredPhase === phase.id;
          const showLabel = isCurrentlyViewing || isHovered || isLiveActive;

          return (
            <div
              key={phase.id}
              className="relative flex items-center justify-center w-full my-2 group"
              onMouseEnter={() => setHoveredPhase(phase.id)}
              onMouseLeave={() => setHoveredPhase(null)}
            >
              {/* The Node Affordance */}
              <button
                onClick={() => {
                  if (isAccessible) {
                    onSelectPhase(phase.id);
                  }
                }}
                disabled={!isAccessible}
                className={`relative z-10 flex items-center justify-center w-7 h-7 rounded-full transition-all duration-200 ${
                  isAccessible ? 'cursor-pointer hover:scale-105 active:scale-95' : 'cursor-not-allowed'
                }`}
                aria-label={`Go to ${phase.label} phase`}
              >
                {/* Active node state: filled red with glow & slow pulse */}
                {isLiveActive && (
                  <>
                    <motion.span
                      className="absolute inset-0 rounded-full bg-[#E60000]"
                      animate={{
                        boxShadow: [
                          '0 0 0 0px rgba(230, 0, 0, 0.35)',
                          '0 0 0 8px rgba(230, 0, 0, 0)',
                        ],
                      }}
                      transition={{
                        repeat: Infinity,
                        duration: 2.2,
                        ease: 'easeInOut',
                      }}
                    />
                    <span className="relative w-3.5 h-3.5 rounded-full bg-[#E60000] border-2 border-[#FCFCFB] shadow-md" />
                  </>
                )}

                {/* Completed node state: filled ink with small checkmark */}
                {isComplete && !isLiveActive && (
                  <span className="flex items-center justify-center w-5 h-5 rounded-full bg-[#161616] text-[#FCFCFB] transition-transform group-hover:scale-110">
                    <Check className="w-3 h-3 stroke-[2.5]" />
                  </span>
                )}

                {/* Not yet reached state: hollow ring */}
                {!isComplete && !isLiveActive && (
                  <span className="w-3.5 h-3.5 rounded-full border-2 border-[#D5D3CA] bg-[#FCFCFB] transition-colors group-hover:border-[#5B5B5B]" />
                )}
              </button>

              {/* Floating label revealed on hover or when active/viewing */}
              {showLabel && (
                <motion.div
                  initial={{ opacity: 0, x: -4 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -4 }}
                  transition={{ duration: 0.15 }}
                  className={`absolute left-14 px-2 py-0.5 rounded text-[11.5px] font-medium whitespace-nowrap pointer-events-none transition-colors ${
                    isCurrentlyViewing
                      ? 'bg-[#161616] text-[#FCFCFB] shadow-sm'
                      : isLiveActive
                      ? 'bg-[#E60000]/10 text-[#E60000]'
                      : 'bg-[#F4F3EE] text-[#5B5B5B]'
                  }`}
                >
                  {phase.label}
                  {isLiveActive && (
                    <span className="ml-1 text-[9px] font-mono uppercase tracking-wider text-[#E60000]">
                      · live
                    </span>
                  )}
                </motion.div>
              )}
            </div>
          );
        })}
      </div>

      {/* Bottom marker */}
      <div className="text-[10px] font-mono text-[#8E8E8E] text-center pt-2">
        <span>v3</span>
      </div>
    </aside>
  );
};
