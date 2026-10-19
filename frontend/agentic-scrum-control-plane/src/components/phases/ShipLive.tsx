import React from 'react';
import { motion } from 'framer-motion';
import { Check, Download, FileText, RotateCcw } from 'lucide-react';
import type { WorkspaceArtifact, WorkspaceMessage } from '../../domain/types';

interface ShipLiveProps {
  artifacts: WorkspaceArtifact[];
  messages: WorkspaceMessage[];
  totalMerged: number;
  onStartNextSprint: () => void;
}

function download(artifact: WorkspaceArtifact) {
  const blob = new Blob([artifact.markdownContent ?? ''], { type: 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = artifact.filename.split('/').pop() ?? 'document.md';
  link.click();
  URL.revokeObjectURL(url);
}

/** The run is over: the final branch is ready for the human to review and merge. Nothing has been merged into main. */
export const ShipLive: React.FC<ShipLiveProps> = ({ artifacts, messages, totalMerged, onStartNextSprint }) => {
  const summary = [...messages].reverse().find((m) => m.kind === 'system' && /^Done:/.test(m.text));
  const branch = [...messages].reverse().find((m) => /The final branch (\S+) is ready/.test(m.text));
  const branchName = branch ? (branch.text.match(/The final branch (\S+) is ready/)?.[1] ?? '') : '';
  const readable = artifacts.filter((a) => a.markdownContent);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
      className="mx-auto flex max-w-[720px] flex-col items-center px-6 py-12 text-center"
    >
      <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-full bg-[#161616] text-[#FCFCFB] shadow-sm">
        <Check className="h-6 w-6 stroke-[2.5]" />
      </div>
      <h1 className="mb-2 text-[24px] font-semibold tracking-tight text-[#161616]">The team has finished</h1>
      <p className="mb-6 max-w-md text-sm leading-relaxed text-[#5B5B5B]">
        {summary ? summary.text.replace(/^Done:\s*/, '') : `${totalMerged} feature${totalMerged === 1 ? '' : 's'} merged.`}
      </p>

      {branchName && (
        <div className="mb-6 w-full rounded-2xl border border-[#161616] bg-[#FCFCFB] p-4 text-left shadow-md">
          <div className="mb-1 font-mono text-[10px] font-semibold uppercase tracking-wider text-[#5B5B5B]">Review and merge this branch yourself</div>
          <code className="text-sm font-semibold text-[#161616]">{branchName}</code>
          <p className="mt-1 text-xs text-[#5B5B5B]">Nothing has been merged into main. If a repository was given, the branches have been pushed there.</p>
        </div>
      )}

      <div className="mb-8 w-full rounded-2xl border border-[#E7E6DF] bg-[#FCFCFB] p-5 text-left shadow-xs">
        <div className="mb-3 border-b border-[#E7E6DF] pb-2 font-mono text-xs font-semibold uppercase tracking-wider text-[#161616]">Documents from this run</div>
        <div className="space-y-2">
          {readable.map((artifact) => (
            <div key={artifact.id} className="flex items-center justify-between rounded-xl bg-[#F4F3EE] p-2.5">
              <div className="flex items-center gap-2.5">
                <FileText className="h-4 w-4 text-[#161616]" />
                <div>
                  <div className="font-mono text-xs font-medium text-[#161616]">{artifact.filename.replace('docs/agile/', '')}</div>
                  <div className="text-[10.5px] text-[#8E8E8E]">{artifact.title}</div>
                </div>
              </div>
              <button onClick={() => download(artifact)} className="rounded-lg p-1.5 text-[#5B5B5B] hover:bg-[#FCFCFB] hover:text-[#161616]" title="Download" aria-label={`Download ${artifact.filename}`}>
                <Download className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      </div>

      <button
        onClick={onStartNextSprint}
        className="flex items-center gap-2 rounded-xl bg-[#161616] px-5 py-2.5 text-xs font-medium text-[#FCFCFB] shadow-sm hover:bg-black"
      >
        <RotateCcw className="h-3.5 w-3.5" />
        <span>Start a new project</span>
      </button>
    </motion.div>
  );
};
