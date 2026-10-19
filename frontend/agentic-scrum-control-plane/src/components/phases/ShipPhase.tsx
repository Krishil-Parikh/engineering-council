import React from 'react';
import { motion } from 'framer-motion';
import { Check, Download, RotateCcw, FileText, CheckCircle2 } from 'lucide-react';
import { ARTIFACTS_LIST } from '../../views/GenUIView/referenceArtifacts';

interface ShipPhaseProps {
  onRestartSprint: () => void;
}

export const ShipPhase: React.FC<ShipPhaseProps> = ({ onRestartSprint }) => {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
      className="max-w-[700px] mx-auto py-12 px-6 flex flex-col items-center text-center"
    >
      {/* Restrained Completion Marker (§3.6: No confetti, calm elegance) */}
      <div className="w-12 h-12 rounded-full bg-[#161616] text-[#FCFCFB] flex items-center justify-center mb-5 shadow-sm">
        <Check className="w-6 h-6 stroke-[2.5]" />
      </div>

      <h1 className="text-[24px] font-semibold text-[#161616] tracking-tight mb-2">
        Sprint 03 Shipped to Production
      </h1>

      {/* One-line retro summary */}
      <p className="text-sm text-[#5B5B5B] max-w-md mb-8 leading-relaxed">
        38 pull requests merged across 6 agents. Redis session partitioning validated with sub-10ms p99 latency SLA. Zero defects reported.
      </p>

      {/* Shipped Artifacts List Card */}
      <div className="w-full bg-[#FCFCFB] border border-[#E7E6DF] rounded-2xl p-6 text-left mb-8 shadow-xs">
        <div className="flex items-center justify-between pb-3 mb-4 border-b border-[#E7E6DF]">
          <span className="text-xs font-semibold uppercase tracking-wider text-[#161616] font-mono">
            Shipped Release Artifacts · v3.0.0
          </span>
          <span className="text-xs text-emerald-700 font-mono flex items-center gap-1">
            <CheckCircle2 className="w-3.5 h-3.5" />
            <span>Integrity Verified</span>
          </span>
        </div>

        <div className="space-y-3">
          {ARTIFACTS_LIST.map((artifact) => (
            <div
              key={artifact.name}
              className="flex items-center justify-between p-2.5 rounded-xl bg-[#F4F3EE] hover:bg-[#EAE9E2] transition-colors"
            >
              <div className="flex items-center gap-2.5">
                <FileText className="w-4 h-4 text-[#161616]" />
                <div>
                  <div className="text-xs font-medium font-mono text-[#161616]">
                    {artifact.name}
                  </div>
                  <div className="text-[10.5px] text-[#8E8E8E]">
                    {artifact.type} · {artifact.size}
                  </div>
                </div>
              </div>

              <button
                onClick={() => {
                  const blob = new Blob([artifact.content], { type: 'text/plain' });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = artifact.name;
                  a.click();
                }}
                className="p-1.5 rounded-lg text-[#5B5B5B] hover:text-[#161616] hover:bg-[#FCFCFB] transition-colors"
                title="Download artifact"
              >
                <Download className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-4">
        <button
          onClick={onRestartSprint}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[#161616] text-[#FCFCFB] text-xs font-medium hover:bg-black transition-all shadow-sm active:scale-98"
        >
          <RotateCcw className="w-3.5 h-3.5" />
          <span>Start Next Sprint (Sprint 04)</span>
        </button>
      </div>
    </motion.div>
  );
};
