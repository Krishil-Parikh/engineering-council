import React, { useState } from 'react';
import { useScrum } from '../../context/ScrumContext';
import { FileText, CheckCircle2, Clock, GitCompare, History, ArrowRight } from 'lucide-react';
import { Artifact, ArtifactVersion } from '../../types';

export const ArtifactsTab: React.FC = () => {
  const { artifacts, selectedArtifact, setSelectedArtifactId } = useScrum();
  const [selectedVersionIndex, setSelectedVersionIndex] = useState<number>(0);
  const [showDiffMode, setShowDiffMode] = useState<boolean>(true);

  const versions = selectedArtifact.versions;
  // Canonical snapshots may carry no version history (or document body).
  // Degrade to the current-version metadata instead of crashing.
  const currentVersionData: ArtifactVersion | null =
    versions[selectedVersionIndex] ?? versions[0] ?? null;

  return (
    <div className="flex-1 flex h-full select-none bg-[#FCFCFB] overflow-hidden">
      {/* Sub-navigation column: Artifact Documents List */}
      <div className="w-[260px] border-r border-[#E2E0D9] bg-[#FFFFFF] p-3 flex flex-col gap-2 shrink-0">
        <div className="text-[11px] font-bold tracking-wider uppercase text-[#5B5B5B] px-1 mb-1">
          DOCUMENTS ({artifacts.length})
        </div>

        {artifacts.map(doc => {
          const isSelected = selectedArtifact.id === doc.id;
          const isApproved = doc.status === 'approved';

          return (
            <button
              key={doc.id}
              onClick={() => {
                setSelectedArtifactId(doc.id);
                setSelectedVersionIndex(0);
              }}
              className={`text-left p-3 rounded-[8px] border transition-all cursor-pointer ${
                isSelected
                  ? 'bg-[#F4F3EE] border-[#161616] shadow-xs'
                  : 'bg-[#FCFCFB] hover:bg-[#F4F3EE]/60 border-[#E2E0D9]'
              }`}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="font-mono font-bold text-[12px] text-[#161616] truncate">
                  {doc.filename}
                </span>
                <span className="text-[10px] mono text-[#5B5B5B] font-semibold bg-[#EDECE7] px-1 rounded-xs">
                  {doc.currentVersion}
                </span>
              </div>

              <div className="text-[11px] text-[#5B5B5B] line-clamp-1 mb-2 font-medium">
                {doc.title}
              </div>

              {/* Acceptance Dots Tracker */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1">
                  {Array.from({ length: doc.totalRequired }).map((_, idx) => (
                    <span
                      key={idx}
                      className={`w-2 h-2 rounded-full ${
                        idx < doc.acceptedCount ? 'bg-[#0F8A4B]' : 'bg-[#E2E0D9]'
                      }`}
                    />
                  ))}
                </div>
                <span className="text-[10px] font-semibold mono text-[#5B5B5B]">
                  {doc.acceptedCount}/{doc.totalRequired}
                </span>
              </div>
            </button>
          );
        })}
      </div>

      {/* Main Document Content Area */}
      <div className="flex-1 flex flex-col overflow-y-auto">
        {/* Document Header & Version Timeline Strip */}
        <div className="px-8 py-4 bg-[#FFFFFF] border-b border-[#E2E0D9] flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <FileText className="w-5 h-5 text-[#161616]" />
              <div>
                <h1 className="text-[18px] font-bold text-[#161616]">
                  {selectedArtifact.title}
                </h1>
                <div className="flex items-center gap-2 text-[11px] mono text-[#5B5B5B] mt-0.5">
                  <span>{selectedArtifact.filename}</span>
                  <span className="text-[#C9C6BC]">·</span>
                  <span className="text-[#0F8A4B] font-semibold flex items-center gap-1">
                    <CheckCircle2 className="w-3 h-3" />
                    {selectedArtifact.status === 'approved' ? 'Approved & Locked' : 'Under Active Review'}
                  </span>
                </div>
              </div>
            </div>

            {/* Toggle Diff Preview */}
            <button
              onClick={() => setShowDiffMode(!showDiffMode)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-[6px] border text-[11.5px] font-semibold cursor-pointer transition-colors ${
                showDiffMode
                  ? 'bg-[#161616] text-[#FFFFFF] border-[#161616]'
                  : 'bg-[#F4F3EE] text-[#161616] border-[#E2E0D9] hover:bg-[#EDECE7]'
              }`}
            >
              <GitCompare className="w-3.5 h-3.5" />
              <span>{showDiffMode ? 'Hide Inline Diff' : 'Show Version Diff'}</span>
            </button>
          </div>

          {/* Version Timeline Strip with Clickable Ticks */}
          <div className="pt-2 border-t border-[#EDECE7] flex items-center justify-between">
            <div className="flex items-center gap-4">
              <span className="text-[10px] font-bold uppercase tracking-wider text-[#5B5B5B] flex items-center gap-1">
                <History className="w-3 h-3" />
                <span>Version Timeline:</span>
              </span>

              <div className="flex items-center gap-3">
                {currentVersionData ? (
                  versions.map((ver, idx) => {
                    const isCurrent = idx === selectedVersionIndex;

                    return (
                      <button
                        key={ver.version}
                        onClick={() => setSelectedVersionIndex(idx)}
                        className={`flex items-center gap-1.5 px-2.5 py-1 rounded-[4px] text-[11px] mono font-semibold cursor-pointer transition-all ${
                          isCurrent
                            ? 'bg-[#FDECEC] text-[#E60000] border border-[#E60000]'
                            : 'bg-[#F4F3EE] hover:bg-[#EDECE7] text-[#5B5B5B] border border-[#E2E0D9]'
                        }`}
                      >
                        <span className={`w-1.5 h-1.5 rounded-full ${isCurrent ? 'bg-[#E60000]' : 'bg-[#C9C6BC]'}`} />
                        <span>{ver.version}</span>
                        <span className="text-[9.5px] font-sans font-normal text-[#5B5B5B]">({ver.timestamp})</span>
                      </button>
                    );
                  })
                ) : (
                  <span className="px-2.5 py-1 rounded-[4px] text-[11px] mono font-semibold bg-[#F4F3EE] text-[#5B5B5B] border border-[#E2E0D9]">
                    {selectedArtifact.currentVersion} · history unavailable in snapshot
                  </span>
                )}
              </div>
            </div>

            <div className="text-[11px] text-[#5B5B5B] font-medium">
              Author: <span className="font-semibold text-[#161616]">{currentVersionData?.author ?? 'Unknown'}</span>
            </div>
          </div>
        </div>

        {/* Document Body (Capped at 740px for clean reading) */}
        <div className="p-8 max-w-[760px] mx-auto w-full flex flex-col gap-6">
          {/* Version Diff Box (if enabled and history exists) */}
          {showDiffMode && currentVersionData && (
            <div className="p-4 bg-[#FFFFFF] rounded-[10px] border border-[#E2E0D9] shadow-xs">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-bold uppercase text-[#5B5B5B]">
                  Diff Summary for {currentVersionData.version}
                </span>
                <span className="text-[11px] text-[#5B5B5B]">{currentVersionData.summary}</span>
              </div>

              {/* Additions */}
              {currentVersionData.diffAdditions.map((line, idx) => (
                <div
                  key={`add-${idx}`}
                  className="p-1.5 mb-1 rounded-[4px] bg-[#E7F5EC] text-[#0F8A4B] text-[12px] mono border-l-2 border-[#0F8A4B]"
                >
                  {line}
                </div>
              ))}

              {/* Deletions */}
              {currentVersionData.diffDeletions.map((line, idx) => (
                <div
                  key={`del-${idx}`}
                  className="p-1.5 mb-1 rounded-[4px] bg-[#FDECEC] text-[#A30000] text-[12px] mono line-through border-l-2 border-[#E60000]"
                >
                  {line}
                </div>
              ))}
            </div>
          )}
          {showDiffMode && !currentVersionData && (
            <div className="p-4 bg-[#FFFFFF] rounded-[10px] border border-[#E2E0D9] shadow-xs text-[12px] text-[#5B5B5B]">
              <span className="text-[11px] font-bold uppercase">
                {selectedArtifact.currentVersion} · {selectedArtifact.acceptedCount}/{selectedArtifact.totalRequired} accepted
              </span>
              <p className="mt-1">Version history is unavailable for this artifact in the current snapshot.</p>
            </div>
          )}

          {/* Rendered Document Text */}
          <article className="prose prose-sm max-w-none text-[#161616] leading-relaxed bg-[#FFFFFF] p-8 rounded-[12px] border border-[#E2E0D9] shadow-xs">
            <pre className="whitespace-pre-wrap font-sans text-[13px] leading-relaxed text-[#161616]">
              {selectedArtifact.markdownContent || 'Document body is unavailable for this artifact in the current snapshot.'}
            </pre>
          </article>
        </div>
      </div>
    </div>
  );
};
