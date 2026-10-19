import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronUp, ChevronDown, Activity, Users, FileText, MessageSquare, X } from 'lucide-react';
import { PhaseId, Agent, Skill, TranscriptMessage, PRHourlyData } from '../../types';
import { PRSparkline } from './PRSparkline';
import { RosterPanel } from './RosterPanel';
import { ArtifactsPanel } from './ArtifactsPanel';
import { TranscriptPanel } from './TranscriptPanel';

interface RevealDrawerProps {
  currentPhase: PhaseId;
  agents: Agent[];
  skills: Skill[];
  transcript: TranscriptMessage[];
  prData: PRHourlyData[];
  totalPRs: number;
}

export const RevealDrawer: React.FC<RevealDrawerProps> = ({
  currentPhase,
  agents,
  skills,
  transcript,
  prData,
  totalPRs,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<'timeline' | 'roster' | 'artifacts' | 'transcript'>('timeline');

  // Contextual handle label based on current phase (§4)
  const getContextLabel = () => {
    switch (currentPhase) {
      case 'kickoff':
        return 'Agent roster & standby skills';
      case 'brainstorm':
        return 'Full dialogue transcript & debate telemetry';
      case 'prd':
        return 'Artifacts & acceptance signatures';
      case 'build':
        return 'PR velocity timeline & build logs';
      case 'review':
        return 'Code audit & test verification report';
      case 'ship':
        return 'Release package & git manifests';
      default:
        return 'Timeline & reference panels';
    }
  };

  return (
    <>
      {/* Dim Overlay on Focus Stage (8% ink overlay, §4) */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setIsOpen(false)}
            className="fixed inset-0 bg-[#161616]/8 z-40 cursor-pointer pointer-events-auto"
          />
        )}
      </AnimatePresence>

      {/* The Reveal Drawer Sheet */}
      <motion.div
        initial={false}
        animate={{ y: isOpen ? 0 : 300 }}
        transition={{ type: 'spring', stiffness: 420, damping: 38 }}
        className="fixed bottom-0 left-0 right-0 z-40 bg-[#FCFCFB] border-t border-[#E7E6DF] shadow-2xl flex flex-col h-[340px]"
      >
        {/* Permanent 40px Handle Bar (§4) */}
        <div
          onClick={() => setIsOpen(!isOpen)}
          className="h-10 bg-[#F4F3EE] hover:bg-[#EAE9E2] border-b border-[#E7E6DF] px-6 flex items-center justify-between cursor-pointer select-none transition-colors"
        >
          <div className="flex items-center gap-2 text-xs font-medium text-[#5B5B5B]">
            {isOpen ? (
              <ChevronDown className="w-3.5 h-3.5 text-[#161616]" />
            ) : (
              <ChevronUp className="w-3.5 h-3.5 text-[#161616]" />
            )}
            <span className="text-[#161616] font-semibold">Reveal Drawer:</span>
            <span>{getContextLabel()}</span>
          </div>

          <div className="flex items-center gap-4 text-xs text-[#8E8E8E] font-mono">
            <span className="hidden sm:inline">38 PRs merged · 6 agents active</span>
            <span className="text-[11px] px-1.5 py-0.5 rounded bg-[#FCFCFB] border border-[#E7E6DF] text-[#161616]">
              {isOpen ? 'Click to collapse' : 'Pull up reference'}
            </span>
          </div>
        </div>

        {/* Drawer Inner Body */}
        <div className="flex-1 flex flex-col px-8 py-4 overflow-hidden">
          {/* Sub-navigation Tabs */}
          <div className="flex items-center justify-between pb-3 mb-2 border-b border-[#E7E6DF]">
            <div className="flex items-center gap-2">
              <button
                onClick={() => setActiveTab('timeline')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  activeTab === 'timeline'
                    ? 'bg-[#161616] text-[#FCFCFB]'
                    : 'bg-[#F4F3EE] text-[#5B5B5B] hover:text-[#161616]'
                }`}
              >
                <Activity className="w-3 h-3" />
                <span>Timeline & Velocity</span>
              </button>

              <button
                onClick={() => setActiveTab('roster')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  activeTab === 'roster'
                    ? 'bg-[#161616] text-[#FCFCFB]'
                    : 'bg-[#F4F3EE] text-[#5B5B5B] hover:text-[#161616]'
                }`}
              >
                <Users className="w-3 h-3" />
                <span>Agent Roster</span>
              </button>

              <button
                onClick={() => setActiveTab('artifacts')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  activeTab === 'artifacts'
                    ? 'bg-[#161616] text-[#FCFCFB]'
                    : 'bg-[#F4F3EE] text-[#5B5B5B] hover:text-[#161616]'
                }`}
              >
                <FileText className="w-3 h-3" />
                <span>Artifacts</span>
              </button>

              <button
                onClick={() => setActiveTab('transcript')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  activeTab === 'transcript'
                    ? 'bg-[#161616] text-[#FCFCFB]'
                    : 'bg-[#F4F3EE] text-[#5B5B5B] hover:text-[#161616]'
                }`}
              >
                <MessageSquare className="w-3 h-3" />
                <span>Transcript Log</span>
              </button>
            </div>

            <button
              onClick={() => setIsOpen(false)}
              className="p-1 text-[#8E8E8E] hover:text-[#161616] rounded-md hover:bg-[#F4F3EE]"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Active Panel View */}
          <div className="flex-1 min-h-0">
            {activeTab === 'timeline' && (
              <PRSparkline data={prData} totalPRs={totalPRs} />
            )}
            {activeTab === 'roster' && (
              <RosterPanel agents={agents} skills={skills} />
            )}
            {activeTab === 'artifacts' && <ArtifactsPanel />}
            {activeTab === 'transcript' && (
              <TranscriptPanel transcript={transcript} />
            )}
          </div>
        </div>
      </motion.div>
    </>
  );
};
