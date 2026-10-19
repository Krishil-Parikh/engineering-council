import React, { useState, useEffect, useRef } from 'react';
import { ARTIFACTS_LIST } from '../../views/GenUIView/referenceArtifacts';
import { FileText, Download, Code, Check } from 'lucide-react';
import { ArtifactFile } from '../../types';

export const ArtifactsPanel: React.FC = () => {
  const [selectedArtifact, setSelectedArtifact] = useState<ArtifactFile>(ARTIFACTS_LIST[0]);
  const [copied, setCopied] = useState(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (copyTimer.current) clearTimeout(copyTimer.current);
  }, []);

  const handleCopy = () => {
    navigator.clipboard.writeText(selectedArtifact.content);
    setCopied(true);
    if (copyTimer.current) clearTimeout(copyTimer.current);
    copyTimer.current = setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="w-full h-full flex flex-col justify-between py-1">
      <div className="flex items-center justify-between pb-3 border-b border-[#E7E6DF]">
        <div className="flex items-center gap-3">
          <span className="text-xs font-semibold text-[#161616]">
            Cross-Phase Artifacts ({ARTIFACTS_LIST.length} generated documents)
          </span>
          <span className="text-xs text-[#8E8E8E]">·</span>
          <span className="text-xs text-[#5B5B5B] font-mono">
            Cryptographically signed specs
          </span>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleCopy}
            className="flex items-center gap-1 px-2 py-1 rounded bg-[#F4F3EE] hover:bg-[#EAE9E2] text-xs font-medium text-[#161616] transition-colors"
          >
            {copied ? <Check className="w-3 h-3 text-emerald-700" /> : <Code className="w-3 h-3" />}
            <span>{copied ? 'Copied' : 'Copy Spec'}</span>
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-12 gap-4 my-2 flex-1 min-h-0">
        {/* Left List */}
        <div className="md:col-span-4 space-y-1.5 overflow-y-auto max-h-[180px]">
          {ARTIFACTS_LIST.map((art) => (
            <button
              key={art.name}
              onClick={() => setSelectedArtifact(art)}
              className={`w-full text-left p-2.5 rounded-xl border transition-all flex items-center justify-between text-xs ${
                selectedArtifact.name === art.name
                  ? 'border-[#161616] bg-[#FCFCFB] shadow-xs font-medium text-[#161616]'
                  : 'border-[#E7E6DF] bg-[#F4F3EE] hover:bg-[#EAE9E2] text-[#5B5B5B]'
              }`}
            >
              <div className="flex items-center gap-2 truncate">
                <FileText className="w-3.5 h-3.5 shrink-0 text-[#161616]" />
                <span className="truncate font-mono">{art.name}</span>
              </div>
              <span className="text-[10px] font-mono text-[#8E8E8E] shrink-0 ml-2">
                {art.size}
              </span>
            </button>
          ))}
        </div>

        {/* Right Preview */}
        <div className="md:col-span-8 bg-[#F4F3EE] border border-[#E7E6DF] rounded-xl p-3 font-mono text-xs overflow-y-auto max-h-[180px] leading-relaxed text-[#161616]">
          <pre className="whitespace-pre-wrap font-mono text-[11.5px]">
            {selectedArtifact.content}
          </pre>
        </div>
      </div>

      <div className="pt-2 border-t border-[#E7E6DF] flex items-center justify-between text-[11px] text-[#8E8E8E] font-mono">
        <span>Artifact checksum: sha256:4f8e91a0...c32d</span>
        <span>Synced with git commit 7a92c81</span>
      </div>
    </div>
  );
};
