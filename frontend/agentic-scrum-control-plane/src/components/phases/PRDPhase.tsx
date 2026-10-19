import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Check, UserCheck, Sparkles, ArrowRight, ShieldCheck } from 'lucide-react';
import { Agent } from '../../types';

interface PRDPhaseProps {
  agents: Agent[];
  onAcceptAllAndAdvance: () => void;
}

export const PRDPhase: React.FC<PRDPhaseProps> = ({ agents, onAcceptAllAndAdvance }) => {
  // 5 out of 6 accepted initially; 6th agent is reviewing section 3
  const [acceptedAgentIds, setAcceptedAgentIds] = useState<string[]>([
    'agent-01',
    'agent-02',
    'agent-03',
    'agent-04',
    'agent-05',
  ]);
  const [isHaloActive, setIsHaloActive] = useState(false);
  const [isAdvancing, setIsAdvancing] = useState(false);
  const choreographyTimers = useRef<Array<ReturnType<typeof setTimeout>>>([]);

  useEffect(() => () => {
    choreographyTimers.current.forEach((timer) => clearTimeout(timer));
  }, []);

  const totalAgents = agents.length || 6;
  const isFullyAccepted = acceptedAgentIds.length >= totalAgents;

  // Simulate or allow user to click Agent-06 acceptance
  const handleFinalSignoff = () => {
    if (isFullyAccepted) return;
    const pendingAgent = agents.find((a) => !acceptedAgentIds.includes(a.id)) || agents[5];
    if (pendingAgent) {
      setAcceptedAgentIds((prev) => [...prev, pendingAgent.id]);
      // Trigger the 900ms connecting halo around the card
      setIsHaloActive(true);
      choreographyTimers.current.push(setTimeout(() => {
        setIsHaloActive(false);
        setIsAdvancing(true);
        choreographyTimers.current.push(setTimeout(() => {
          onAcceptAllAndAdvance();
        }, 800));
      }, 950));
    }
  };

  // Optional auto-signoff after a few seconds if user is passive
  useEffect(() => {
    const timer = setTimeout(() => {
      if (!isFullyAccepted) {
        handleFinalSignoff();
      }
    }, 4000);
    return () => clearTimeout(timer);
  }, [isFullyAccepted]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
      className="max-w-[720px] mx-auto py-10 px-4 flex flex-col items-center"
    >
      {/* Document Meta Header */}
      <div className="w-full flex items-center justify-between mb-4 text-xs text-[#5B5B5B]">
        <div className="flex items-center gap-2">
          <span className="font-mono font-semibold text-[#161616]">PRD.md</span>
          <span className="text-[#8E8E8E]">·</span>
          <span>v3.0.4</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-[#E60000] animate-pulse" />
          <span className="font-mono text-[11px] text-[#5B5B5B]">Peer review in progress</span>
        </div>
      </div>

      {/* Main Document Card with 900ms Halo */}
      <div className="relative w-full">
        {/* The 900ms Connecting Halo Glow (§3.3) */}
        <AnimatePresence>
          {isHaloActive && (
            <motion.div
              initial={{ opacity: 0, scale: 0.99 }}
              animate={{ opacity: 1, scale: 1.01 }}
              exit={{ opacity: 0, scale: 1.02 }}
              transition={{ duration: 0.9, ease: 'easeOut' }}
              className="absolute -inset-1 rounded-2xl bg-gradient-to-r from-[#E60000] via-[#161616] to-[#E60000] blur-sm pointer-events-none z-0"
            />
          )}
        </AnimatePresence>

        <div className="relative z-10 w-full bg-[#FCFCFB] border border-[#E7E6DF] rounded-2xl p-8 shadow-sm">
          {/* Title */}
          <h1 className="text-[22px] font-semibold text-[#161616] mb-1 tracking-tight">
            # Product Requirements: Agentic SDLC Control Plane
          </h1>
          <p className="text-xs text-[#5B5B5B] font-mono mb-6">
            Scrum Master synthesized · Ratified by Business SME directive
          </p>

          <hr className="border-[#E7E6DF] mb-6" />

          {/* Section 1: Problem & Invariants with Agent-01 cursor */}
          <div className="relative mb-6">
            {/* Live presence indicator caret in margin */}
            <div className="absolute -left-7 top-1 flex items-center group">
              <span className="w-2 h-4 bg-[#E60000] rounded-sm" />
              <span className="absolute left-3 px-1.5 py-0.5 rounded bg-[#161616] text-[#FCFCFB] text-[9.5px] font-mono whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity">
                Agent-01 (Frontend)
              </span>
            </div>

            <h2 className="text-[15px] font-semibold text-[#161616] mb-2">
              1. Narrative Spine Discipline
            </h2>
            <p className="text-[14px] leading-[23px] text-[#5B5B5B]">
              The user interface rejects multi-tab fragmentation. A single 88px left spine represents the chronological life of the project. The focus stage renders one phase at a time with 100% breathing room. When agents reach verified milestones, the UI advances itself unprompted.
            </p>
          </div>

          {/* Section 2: Architecture & Data Partitioning with Agent-03 cursor */}
          <div className="relative mb-6">
            <div className="absolute -left-7 top-1 flex items-center group">
              <span className="w-2 h-4 bg-[#161616] rounded-sm" />
              <span className="absolute left-3 px-1.5 py-0.5 rounded bg-[#161616] text-[#FCFCFB] text-[9.5px] font-mono whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity">
                Agent-03 (Backend)
              </span>
            </div>

            <h2 className="text-[15px] font-semibold text-[#161616] mb-2">
              2. Session Partitioning & Redis Synchronization
            </h2>
            <p className="text-[14px] leading-[23px] text-[#5B5B5B]">
              As ratified by the Business SME, the orchestrator utilizes Redis Pub/Sub channels partitioned by sprint session ID. State mutations emit delta streams to connected agent workers, guaranteeing under 12ms p99 transmission latency across all delegation nodes.
            </p>
          </div>

          {/* Section 3: Acceptance Criteria with Agent-06 cursor */}
          <div className="relative">
            <div className="absolute -left-7 top-1 flex items-center group">
              <motion.span
                animate={{ opacity: [1, 0.3, 1] }}
                transition={{ repeat: Infinity, duration: 1.2 }}
                className="w-2 h-4 bg-[#E60000] rounded-sm"
              />
              <span className="absolute left-3 px-1.5 py-0.5 rounded bg-[#E60000] text-[#FCFCFB] text-[9.5px] font-mono whitespace-nowrap">
                Agent-06 (Reviewing...)
              </span>
            </div>

            <h2 className="text-[15px] font-semibold text-[#161616] mb-2">
              3. Verification & CI/CD Invariants
            </h2>
            <p className="text-[14px] leading-[23px] text-[#5B5B5B]">
              Generic developer agents must write hermetic integration test contracts before opening pull requests. No branch may be merged into main without 100% test coverage and zero regression flags.
            </p>
          </div>
        </div>
      </div>

      {/* Acceptance Tracker directly beneath document (§3.3) */}
      <div className="w-full mt-6 flex flex-col sm:flex-row items-center justify-between p-4 bg-[#FCFCFB] border border-[#E7E6DF] rounded-xl">
        <div className="flex items-center gap-3 mb-3 sm:mb-0">
          <span className="text-xs font-semibold text-[#161616]">Acceptance</span>
          
          {/* The 6 Acceptance Dots */}
          <div className="flex items-center gap-1.5">
            {agents.map((agent) => {
              const isAccepted = acceptedAgentIds.includes(agent.id);
              return (
                <div
                  key={agent.id}
                  className={`w-2.5 h-2.5 rounded-full transition-all duration-300 ${
                    isAccepted
                      ? 'bg-[#161616]'
                      : 'bg-[#FCFCFB] border-2 border-[#E60000] animate-pulse'
                  }`}
                  title={`${agent.name}: ${isAccepted ? 'Approved' : 'Reviewing section 3'}`}
                />
              );
            })}
          </div>

          <span className="text-xs font-mono font-medium text-[#161616]">
            {acceptedAgentIds.length} / {totalAgents}
          </span>
        </div>

        {/* Right status / Action */}
        <div className="flex items-center gap-3">
          {!isFullyAccepted ? (
            <button
              onClick={handleFinalSignoff}
              className="flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-[#F4F3EE] hover:bg-[#EAE9E2] border border-[#E7E6DF] text-xs font-medium text-[#161616] transition-colors"
            >
              <span>Agent-06 is reviewing section 3</span>
              <span className="text-[#E60000] font-mono text-[11px]">→ Sign off</span>
            </button>
          ) : (
            <div className="flex items-center gap-2 text-xs text-[#161616] font-medium">
              <ShieldCheck className="w-4 h-4 text-[#E60000]" />
              <span>Full Consensus Achieved · Advancing to Build...</span>
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
};
