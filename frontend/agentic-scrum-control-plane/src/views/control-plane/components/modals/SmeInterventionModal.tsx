import React, { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { useScrum } from '../../context/ScrumContext';
import { ShieldAlert, X, ArrowRight, Check } from 'lucide-react';

const PRESET_DIRECTIVES = [
  'Must comply with Swiss FINMA Circular 2026/02: Ingestion ACK under 20ms p99 with zero data loss.',
  'Enforce synchronous SHA-256 cryptographic parent lineage before returning client ACK.',
  'Add dual-zone disaster recovery: active-active Raft consensus across Zurich and Geneva.',
  'Terminal UI must guarantee 60 FPS under peak bursts of 120,000 order ticks/second.'
];

export const SmeInterventionModal: React.FC = () => {
  const { isSmeModalOpen, setIsSmeModalOpen, triggerSmeIntervention } = useScrum();
  const [directiveText, setDirectiveText] = useState('');

  if (!isSmeModalOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (directiveText.trim()) {
      triggerSmeIntervention(directiveText.trim());
      setDirectiveText('');
      setIsSmeModalOpen(false);
    }
  };

  const handleSelectPreset = (preset: string) => {
    setDirectiveText(preset);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[#161616]/40 backdrop-blur-sm">
      <motion.div
        initial={{ opacity: 0, scale: 0.96, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.96, y: 10 }}
        transition={{ type: 'spring', stiffness: 450, damping: 32 }}
        className="w-full max-w-lg bg-[#FCFCFB] border border-[#E2E0D9] rounded-[16px] shadow-[0_20px_48px_rgba(22,22,22,0.16)] overflow-hidden flex flex-col"
      >
        {/* Header */}
        <div className="px-6 py-4 border-b border-[#E2E0D9] flex items-center justify-between bg-[#FFFFFF]">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-[8px] bg-[#E8F0FA] flex items-center justify-center border border-[#0057B8]/20">
              <ShieldAlert className="w-4 h-4 text-[#0057B8]" />
            </div>
            <div>
              <h3 className="font-bold text-[15px] text-[#161616]">
                Business SME Intervention
              </h3>
              <p className="text-[11.5px] text-[#5B5B5B]">
                Inject regulatory boundaries & architectural directives to the agent bench
              </p>
            </div>
          </div>

          <button
            onClick={() => setIsSmeModalOpen(false)}
            className="p-1.5 rounded-[6px] text-[#5B5B5B] hover:text-[#161616] hover:bg-[#F4F3EE] cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content & Form */}
        <form onSubmit={handleSubmit} className="p-6 flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-bold tracking-wider uppercase text-[#5B5B5B]">
              Regulatory or Strategic Directive
            </label>
            <textarea
              value={directiveText}
              onChange={e => setDirectiveText(e.target.value)}
              placeholder="e.g. Ingestion engine must acknowledge orders in under 18ms p99 with FINMA Art. 14 SHA-256 chain..."
              rows={3}
              required
              className="w-full p-3 bg-[#FFFFFF] border border-[#C9C6BC] rounded-[8px] text-[12.5px] text-[#161616] placeholder-[#5B5B5B]/60 outline-none focus:border-[#0057B8] focus:ring-1 focus:ring-[#0057B8]"
            />
          </div>

          {/* Presets */}
          <div className="flex flex-col gap-2">
            <span className="text-[10.5px] font-semibold text-[#5B5B5B] uppercase tracking-wider">
              Quick FINMA & Performance Presets:
            </span>
            <div className="flex flex-col gap-1.5">
              {PRESET_DIRECTIVES.map((preset, idx) => (
                <button
                  type="button"
                  key={idx}
                  onClick={() => handleSelectPreset(preset)}
                  className="text-left p-2 rounded-[6px] bg-[#F4F3EE] hover:bg-[#EDECE7] border border-[#E2E0D9] text-[11.5px] text-[#161616] transition-colors cursor-pointer flex items-center justify-between group"
                >
                  <span className="truncate pr-2">{preset}</span>
                  <ArrowRight className="w-3 h-3 text-[#5B5B5B] group-hover:text-[#161616] shrink-0" />
                </button>
              ))}
            </div>
          </div>

          {/* Footer actions */}
          <div className="mt-2 pt-4 border-t border-[#E2E0D9] flex items-center justify-end gap-3">
            <button
              type="button"
              onClick={() => setIsSmeModalOpen(false)}
              className="px-4 py-2 text-[12px] font-semibold text-[#5B5B5B] hover:text-[#161616] cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 bg-[#0057B8] hover:bg-[#004694] text-[#FFFFFF] text-[12px] font-semibold rounded-[8px] transition-all cursor-pointer flex items-center gap-1.5 shadow-sm active:scale-[0.98]"
            >
              <span>Broadcast Directive</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </form>
      </motion.div>
    </div>
  );
};
