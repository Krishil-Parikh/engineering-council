import React, { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { Upload, FileText, ArrowRight, Sparkles, FolderUp } from 'lucide-react';
import { Agent } from '../../types';

interface KickoffPhaseProps {
  agents: Agent[];
  onStartMeet: (briefTitle: string, briefContent: string) => void;
}

const PRESET_BRIEFS = [
  {
    title: 'High-Throughput Multi-Tenant Agent SDLC Engine',
    desc: 'Orchestrate 6 generic developer agents with session partitioning, Redis pub/sub state cache, and real-time PR review contracts.',
  },
  {
    title: 'Idempotent Payment Router & Ledger Integration',
    desc: 'Dual-currency settlement bridge connecting Stripe & Adyen with automated reconciliation migrations and fault injection suites.',
  },
  {
    title: 'Distributed Vector Memory & Knowledge Graph Hub',
    desc: 'Self-hosted pgvector cluster with sub-5ms semantic indexing and live embedding cache eviction policies.',
  },
];

export const KickoffPhase: React.FC<KickoffPhaseProps> = ({ agents, onStartMeet }) => {
  const [briefText, setBriefText] = useState(
    'We need an ultra-low-latency SDLC orchestration engine where autonomous generic agents collaborate on PRDs, write integration contracts, and merge pull requests under Business SME supervision.'
  );
  const [activePreset, setActivePreset] = useState(0);
  const [attachedFiles, setAttachedFiles] = useState<string[]>([
    'prd_template_v3.md',
    'system_architecture_draft.png',
  ]);
  const [isDragging, setIsDragging] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const submitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (submitTimer.current) clearTimeout(submitTimer.current);
  }, []);

  const handleStart = () => {
    setIsSubmitting(true);
    if (submitTimer.current) clearTimeout(submitTimer.current);
    submitTimer.current = setTimeout(() => {
      onStartMeet(PRESET_BRIEFS[activePreset]?.title || 'System SDLC Sprint', briefText);
    }, 450);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const names = Array.from(e.dataTransfer.files).map((f) => f.name);
      setAttachedFiles((prev) => [...prev, ...names]);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.96 }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
      className="max-w-[760px] mx-auto py-12 px-6 flex flex-col items-center text-center"
    >
      {/* Editorial Hero Headline */}
      <h1 className="text-[30px] leading-[38px] font-semibold text-[#161616] tracking-tight mb-2">
        Give the team a problem to solve
      </h1>
      <p className="text-sm text-[#5B5B5B] max-w-lg mb-8 leading-relaxed">
        Drop reference specs, architecture folders, or write the mission brief. The Scrum Master and generic developer bench are assembled.
      </p>

      {/* Preset Quick Selectors */}
      <div className="w-full flex items-center justify-center gap-2 mb-4">
        {PRESET_BRIEFS.map((preset, idx) => (
          <button
            key={idx}
            onClick={() => {
              setActivePreset(idx);
              setBriefText(preset.desc);
            }}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all text-left ${
              activePreset === idx
                ? 'bg-[#161616] text-[#FCFCFB] shadow-sm'
                : 'bg-[#F4F3EE] text-[#5B5B5B] hover:text-[#161616] hover:bg-[#EAE9E2]'
            }`}
          >
            {preset.title.split(' ')[0]} {preset.title.split(' ')[1]}
          </button>
        ))}
      </div>

      {/* Input / Drop Zone Card */}
      <motion.div
        layoutId="kickoff-brief-card"
        className={`w-full bg-[#FCFCFB] border rounded-2xl p-6 shadow-sm transition-all duration-200 text-left relative ${
          isDragging ? 'border-[#E60000] bg-[#E60000]/5' : 'border-[#E7E6DF]'
        }`}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
      >
        <label className="block text-xs font-semibold uppercase tracking-wider text-[#5B5B5B] mb-2 font-mono">
          Sprint Objective & Problem Definition
        </label>
        <textarea
          value={briefText}
          onChange={(e) => setBriefText(e.target.value)}
          rows={4}
          placeholder="Describe the problem, target SLAs, schema constraints, or acceptance rules..."
          className="w-full text-sm text-[#161616] leading-relaxed bg-transparent border-0 focus:ring-0 focus:outline-none resize-none placeholder:text-[#8E8E8E]"
        />

        {/* Attached Files Strip */}
        <div className="mt-4 pt-4 border-t border-[#E7E6DF] flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            {attachedFiles.map((file, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1.5 text-xs text-[#5B5B5B] bg-[#F4F3EE] px-2.5 py-1 rounded-md border border-[#E7E6DF]"
              >
                <FileText className="w-3 h-3 text-[#161616]" />
                <span className="font-mono text-[11px]">{file}</span>
              </span>
            ))}

            <label className="cursor-pointer inline-flex items-center gap-1 text-xs text-[#5B5B5B] hover:text-[#161616] px-2 py-1 rounded hover:bg-[#F4F3EE] transition-colors">
              <FolderUp className="w-3.5 h-3.5" />
              <span>Attach folder</span>
              <input
                type="file"
                multiple
                className="hidden"
                onChange={(e) => {
                  if (e.target.files) {
                    const names = Array.from(e.target.files).map((f) => f.name);
                    setAttachedFiles((prev) => [...prev, ...names]);
                  }
                }}
              />
            </label>
          </div>

          <div className="flex items-center gap-1 text-[11px] text-[#8E8E8E] font-mono">
            <Upload className="w-3 h-3" />
            <span>Drag specs & diagrams</span>
          </div>
        </div>
      </motion.div>

      {/* Developer Agents Bench Status */}
      <div className="mt-10 mb-8 flex flex-col items-center">
        <span className="text-xs text-[#5B5B5B] mb-3 font-medium">
          {agents.length} generic developer agents assembled on the bench
        </span>

        {/* Breathing live agent dots */}
        <div className="flex items-center gap-3">
          {agents.map((agent, i) => (
            <div key={agent.id} className="relative group">
              <motion.div
                animate={{
                  scale: [1, 1.15, 1],
                  opacity: [0.85, 1, 0.85],
                }}
                transition={{
                  repeat: Infinity,
                  duration: 2.8,
                  delay: i * 0.35,
                  ease: 'easeInOut',
                }}
                className="w-3 h-3 rounded-full bg-[#161616] ring-4 ring-[#FCFCFB] shadow-sm cursor-default"
              />
              <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 hidden group-hover:block z-20 px-2 py-1 bg-[#161616] text-[#FCFCFB] text-[10.5px] rounded whitespace-nowrap font-mono pointer-events-none">
                {agent.name} · {agent.claimedSkill || 'Unclaimed template'}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Primary Action Button */}
      <button
        onClick={handleStart}
        disabled={isSubmitting}
        className="px-6 py-3 rounded-xl bg-[#161616] text-[#FCFCFB] text-sm font-medium hover:bg-black transition-all flex items-center gap-2.5 shadow-md active:scale-98 cursor-pointer disabled:opacity-50"
      >
        <span>Start the meet → becomes Brainstorm</span>
        <ArrowRight className="w-4 h-4" />
      </button>
    </motion.div>
  );
};
