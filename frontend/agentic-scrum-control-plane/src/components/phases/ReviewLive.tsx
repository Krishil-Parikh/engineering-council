import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { CheckCircle2, FileText, Loader2 } from 'lucide-react';
import type { WorkspaceArtifact, WorkspaceMessage, WorkspaceSprint } from '../../domain/types';

interface ReviewLiveProps {
  sprints: WorkspaceSprint[];
  artifacts: WorkspaceArtifact[];
  messages: WorkspaceMessage[];
}

/** The last stretch: the sprints are closed and the team is verifying the integrated project and preparing the final branch. */
export const ReviewLive: React.FC<ReviewLiveProps> = ({ sprints, artifacts, messages }) => {
  const reports = artifacts.filter((a) => a.filename.endsWith('sprint_report.md') || a.filename.endsWith('retrospective.md') || a.filename.endsWith('review.md'));
  const [selected, setSelected] = useState(0);
  const current = reports[Math.min(selected, Math.max(reports.length - 1, 0))];
  const verification = messages.filter((m) => /verification|final branch|repair/i.test(m.text) && m.kind === 'system').slice(-4);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
      className="mx-auto flex w-full max-w-[960px] flex-col px-6 py-8"
    >
      <div className="mb-6 flex items-center justify-between border-b border-[#E7E6DF] pb-4">
        <div>
          <h2 className="text-[17px] font-semibold text-[#161616]">Final verification</h2>
          <p className="mt-0.5 text-xs text-[#5B5B5B]">
            {sprints.length} sprint{sprints.length === 1 ? '' : 's'} closed. The team is running the project's own checks on the integrated code and preparing the final branch for you.
          </p>
        </div>
        <span className="flex items-center gap-2 font-mono text-[11px] text-[#5B5B5B]">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-[#E60000]" />
          working
        </span>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        <div className="lg:col-span-4">
          <h3 className="mb-2 font-mono text-xs font-semibold uppercase tracking-wider text-[#5B5B5B]">Sprints</h3>
          <ul className="mb-5 space-y-2">
            {sprints.map((sprint) => (
              <li key={sprint.id} className="flex items-center justify-between rounded-xl border border-[#E7E6DF] bg-[#FCFCFB] p-3 text-xs">
                <span className="mr-2 truncate font-medium text-[#161616]">{sprint.title}</span>
                <span className="flex items-center gap-1 font-mono text-[11px] text-[#5B5B5B]">
                  {sprint.status === 'completed' && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-700" />}
                  {sprint.progress}%
                </span>
              </li>
            ))}
          </ul>
          <h3 className="mb-2 font-mono text-xs font-semibold uppercase tracking-wider text-[#5B5B5B]">Reports</h3>
          <div className="space-y-1.5">
            {reports.length === 0 && <p className="text-xs text-[#8E8E8E]">The reports appear here as they are written.</p>}
            {reports.map((report, index) => (
              <button
                key={report.id}
                onClick={() => setSelected(index)}
                className={`flex w-full items-center gap-2 truncate rounded-xl border p-2.5 text-left text-xs transition-colors ${
                  index === selected ? 'border-[#161616] bg-[#FCFCFB] font-medium' : 'border-[#E7E6DF] bg-[#F4F3EE] text-[#5B5B5B] hover:bg-[#EAE9E2]'
                }`}
              >
                <FileText className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate font-mono">{report.filename.replace('docs/agile/', '')}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="lg:col-span-8">
          <article className="rounded-2xl border border-[#E7E6DF] bg-[#FCFCFB] p-5 shadow-sm">
            <pre className="max-h-[50vh] overflow-y-auto whitespace-pre-wrap font-sans text-[12.5px] leading-[20px] text-[#161616]">
              {current?.markdownContent || 'Select a report.'}
            </pre>
          </article>
          {verification.length > 0 && (
            <ul className="mt-4 space-y-1 text-xs text-[#5B5B5B]">
              {verification.map((m) => (
                <li key={m.id} className="font-mono">{m.text}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </motion.div>
  );
};
