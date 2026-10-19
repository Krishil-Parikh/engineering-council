import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Clock, Send, CheckCircle2, MessageSquare, ArrowRight } from 'lucide-react';
import { TranscriptMessage } from '../../types';

interface BrainstormPhaseProps {
  transcript: TranscriptMessage[];
  onSmeSubmitDecision: (messageId: string, decision: string) => void;
  onConcludeMeet: () => void;
}

export const BrainstormPhase: React.FC<BrainstormPhaseProps> = ({
  transcript,
  onSmeSubmitDecision,
  onConcludeMeet,
}) => {
  const [secondsRemaining, setSecondsRemaining] = useState(882); // ~14m 42s left
  const [customReply, setCustomReply] = useState('');
  const [selectedQuickChoice, setSelectedQuickChoice] = useState<string | null>(null);

  // 15-minute meeting countdown timer
  useEffect(() => {
    const timer = setInterval(() => {
      setSecondsRemaining((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const formatTimer = (totalSecs: number) => {
    const m = Math.floor(totalSecs / 60);
    const s = totalSecs % 60;
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  const pendingSmeQuestion = transcript.find(
    (msg) => msg.isQuestionForSME && !msg.smeAnswered
  );

  const answeredSmeQuestions = transcript.filter(
    (msg) => msg.isQuestionForSME && msg.smeAnswered
  );

  const handleDecision = (text: string) => {
    if (!pendingSmeQuestion) return;
    onSmeSubmitDecision(pendingSmeQuestion.id, text);
    setCustomReply('');
    setSelectedQuickChoice(null);
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
      className="w-full max-w-[640px] mx-auto py-10 px-4 flex flex-col"
    >
      {/* Header bar within the phase column */}
      <div className="flex items-center justify-between pb-6 mb-8 border-b border-[#E7E6DF]">
        <div>
          <h2 className="text-[17px] font-semibold text-[#161616] tracking-tight">
            Meet 01: Architecture & Data Invariants
          </h2>
          <p className="text-xs text-[#5B5B5B] mt-0.5">
            Autonomous agent sync · Business SME supervision active
          </p>
        </div>

        {/* 15m Cutoff Timer */}
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-[#F4F3EE] border border-[#E7E6DF] text-xs font-mono text-[#161616]">
          <Clock className="w-3.5 h-3.5 text-[#E60000]" />
          <span>{formatTimer(secondsRemaining)}</span>
          <span className="text-[10px] text-[#8E8E8E]">/ 15m cutoff</span>
        </div>
      </div>

      {/* Transcript Messages Stream */}
      <div className="space-y-6">
        {transcript.map((msg, index) => {
          const isDebate = msg.isDebate;
          const isScrumMaster = msg.speakerId === 'scrum-master';

          return (
            <React.Fragment key={msg.id}>
              {/* Optional Debate Connector Indicator */}
              {isDebate && (
                <div className="flex items-center justify-center my-3">
                  <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-[#F4F3EE] border border-[#E7E6DF] text-[11px] font-mono text-[#5B5B5B]">
                    <span className="text-[#E60000]">⟷</span>
                    <span>divergent architectural opinions · live debate</span>
                  </div>
                </div>
              )}

              {/* Message Block */}
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.25, delay: index * 0.04 }}
                className={`group relative pl-4 border-l-2 transition-all ${
                  isScrumMaster
                    ? 'border-[#E60000]'
                    : msg.isQuestionForSME
                    ? 'border-[#161616]'
                    : 'border-[#D5D3CA]'
                }`}
              >
                {/* Speaker Header */}
                <div className="flex items-center justify-between mb-1.5">
                  <div className="flex items-center gap-2">
                    <span
                      className="w-2 h-2 rounded-full"
                      style={{ backgroundColor: msg.avatarColor }}
                    />
                    <span className="text-[13px] font-semibold text-[#161616]">
                      {msg.speakerName}
                    </span>
                    <span className="text-[11px] text-[#8E8E8E] font-medium">
                      {msg.speakerRole}
                    </span>
                  </div>
                  <span className="text-[11px] font-mono text-[#8E8E8E]">
                    {msg.timestamp}
                  </span>
                </div>

                {/* Message Content */}
                <p className="text-[14px] leading-[23px] text-[#161616] font-normal">
                  {msg.content}
                </p>

                {/* Answered SME decision display */}
                {msg.isQuestionForSME && msg.smeAnswered && msg.smeResponse && (
                  <div className="mt-3 p-3 rounded-lg bg-[#F4F3EE] border border-[#E7E6DF] text-xs text-[#161616]">
                    <div className="flex items-center gap-1.5 font-medium text-[#161616] mb-1">
                      <CheckCircle2 className="w-3.5 h-3.5 text-[#E60000]" />
                      <span>Decision ratified by Business SME:</span>
                    </div>
                    <p className="italic text-[#5B5B5B] pl-5">{msg.smeResponse}</p>
                  </div>
                )}
              </motion.div>
            </React.Fragment>
          );
        })}

        {/* SME Question Inline Card (§3.2) */}
        <AnimatePresence>
          {pendingSmeQuestion && (
            <motion.div
              initial={{ opacity: 0, scale: 0.96, y: 12 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.96, y: -8 }}
              transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
              className="mt-8 p-6 rounded-2xl bg-[#FCFCFB] border border-[#161616] shadow-xl relative overflow-hidden"
            >
              {/* Subtle top indicator */}
              <div className="flex items-center gap-2 mb-3">
                <span className="w-2 h-2 rounded-full bg-[#E60000] animate-ping" />
                <span className="text-xs font-semibold uppercase tracking-wider text-[#161616] font-mono">
                  Supervisory Checkpoint · Action Required
                </span>
              </div>

              <h3 className="text-[15px] font-semibold text-[#161616] mb-2 leading-snug">
                {pendingSmeQuestion.questionContext || 'Decision requested from Business SME'}
              </h3>
              <p className="text-xs text-[#5B5B5B] mb-5 leading-relaxed">
                The agent bench has converged on two implementation paths. Your guidance will be codified directly into Section 2.4 of the PRD.
              </p>

              {/* Quick Decision Options */}
              <div className="space-y-2 mb-4">
                {[
                  'Option A: Mandate Redis Pub/Sub + partitioned Postgres sessions for sub-50ms sync.',
                  'Option B: Use SQLite WAL mode with local memory ring buffer for airgap compliance.',
                ].map((option, idx) => (
                  <button
                    key={idx}
                    onClick={() => {
                      setSelectedQuickChoice(option);
                      handleDecision(option);
                    }}
                    className="w-full text-left p-3 rounded-xl border border-[#E7E6DF] bg-[#F4F3EE] hover:bg-[#EAE9E2] text-xs font-medium text-[#161616] transition-all flex items-center justify-between group active:scale-98"
                  >
                    <span>{option}</span>
                    <ArrowRight className="w-3.5 h-3.5 opacity-0 group-hover:opacity-100 transition-opacity text-[#E60000]" />
                  </button>
                ))}
              </div>

              {/* Or Custom Input */}
              <div className="flex items-center gap-2 pt-2 border-t border-[#E7E6DF]">
                <input
                  type="text"
                  value={customReply}
                  onChange={(e) => setCustomReply(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && customReply.trim()) {
                      handleDecision(customReply.trim());
                    }
                  }}
                  placeholder="Or enter custom directive for the agents..."
                  className="flex-1 px-3 py-2 text-xs bg-[#F4F3EE] border border-[#E7E6DF] rounded-lg focus:outline-none focus:border-[#161616] text-[#161616]"
                />
                <button
                  onClick={() => customReply.trim() && handleDecision(customReply.trim())}
                  disabled={!customReply.trim()}
                  className="px-3.5 py-2 rounded-lg bg-[#161616] text-[#FCFCFB] text-xs font-medium hover:bg-black disabled:opacity-40 transition-colors flex items-center gap-1.5"
                >
                  <Send className="w-3 h-3" />
                  <span>Submit</span>
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* If SME has answered, show synthesis action or auto-advance */}
        {answeredSmeQuestions.length > 0 && !pendingSmeQuestion && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="pt-8 pb-4 flex flex-col items-center text-center"
          >
            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-[#161616] text-[#FCFCFB] text-xs font-medium mb-3">
              <CheckCircle2 className="w-3.5 h-3.5 text-[#E60000]" />
              <span>Consensus reached · Scrum Master compiling PRD</span>
            </div>
            <button
              onClick={onConcludeMeet}
              className="px-5 py-2.5 rounded-xl bg-[#161616] text-[#FCFCFB] text-xs font-medium hover:bg-black transition-all shadow-sm flex items-center gap-2 active:scale-98"
            >
              <span>Conclude Meet 01 → Advance to PRD</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </motion.div>
        )}
      </div>
    </motion.div>
  );
};
