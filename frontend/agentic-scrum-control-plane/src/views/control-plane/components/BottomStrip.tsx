import React from 'react';
import { useScrum } from '../context/ScrumContext';
import { Play, Pause, SkipForward, CheckCircle2, AlertCircle, FileText, Activity } from 'lucide-react';
import { Odometer } from './common/Odometer';

export const BottomStrip: React.FC = () => {
  const {
    selectedSprint,
    artifacts,
    setActiveTab,
    setSelectedArtifactId,
    isSimulating,
    toggleSimulation,
    stepSimulation
  } = useScrum();

  return (
    <footer className="h-[40px] bg-[#FFFFFF] border-t border-[#E2E0D9] px-4 flex items-center justify-between shrink-0 select-none z-20 text-[11px] text-[#5B5B5B]">
      {/* Left: Phase Progress */}
      <div className="flex items-center gap-3 min-w-[340px]">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-[#161616] truncate max-w-[200px]">
            {selectedSprint.phase}
          </span>
          <span className="mono font-semibold text-[#161616]">
            {selectedSprint.progress}%
          </span>
        </div>

        {/* Subtle Progress Bar */}
        <div className="w-24 h-1.5 bg-[#F4F3EE] rounded-full overflow-hidden border border-[#E2E0D9]">
          <div
            className="h-full bg-[#161616] rounded-full transition-all duration-300"
            style={{ width: `${selectedSprint.progress}%` }}
          />
        </div>
      </div>

      {/* Center: Live Artifact Tray */}
      <div className="hidden lg:flex items-center gap-3">
        <span className="text-[10px] uppercase font-bold text-[#5B5B5B]/80 tracking-wider">
          ARTIFACT TRAY:
        </span>

        {artifacts.map(art => {
          const isApproved = art.status === 'approved';

          return (
            <button
              key={art.id}
              onClick={() => {
                setSelectedArtifactId(art.id);
                setActiveTab('artifacts');
              }}
              className="flex items-center gap-1.5 px-2 py-0.5 rounded-[4px] bg-[#F4F3EE] hover:bg-[#EDECE7] border border-[#E2E0D9] transition-colors cursor-pointer text-[#161616]"
            >
              <FileText className="w-3 h-3 text-[#5B5B5B]" />
              <span className="font-mono font-medium text-[10.5px]">{art.filename}</span>
              <span className="text-[9.5px] mono text-[#5B5B5B]">({art.currentVersion})</span>
              {isApproved ? (
                <CheckCircle2 className="w-3 h-3 text-[#0F8A4B]" />
              ) : (
                <span className="text-[9px] font-bold text-[#B27000] bg-[#FBF1DC] px-1 rounded-xs">
                  {art.acceptedCount}/{art.totalRequired}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Right: Simulation Controls & Telemetry */}
      <div className="flex items-center gap-4">
        {/* Real-time telemetry */}
        <div className="hidden md:flex items-center gap-3 text-[10.5px] mono">
          <span className="text-[#0F8A4B] flex items-center gap-1 font-semibold">
            <span className="w-1.5 h-1.5 rounded-full bg-[#0F8A4B]" />
            FINMA Compliant
          </span>
          <span className="text-[#C9C6BC]">·</span>
          <span>14ms Latency</span>
          <span className="text-[#C9C6BC]">·</span>
          <span>4.2k tok/s</span>
        </div>

        <div className="h-3 w-[1px] bg-[#E2E0D9]" />

        {/* Play/Pause & Step Controls */}
        <div className="flex items-center gap-1 bg-[#F4F3EE] p-0.5 rounded-[6px] border border-[#E2E0D9]">
          <button
            onClick={toggleSimulation}
            className="p-1 hover:bg-[#EDECE7] rounded-[4px] text-[#161616] cursor-pointer transition-colors"
            title={isSimulating ? 'Pause Automated Loop' : 'Resume Automated Loop'}
          >
            {isSimulating ? <Pause className="w-3 h-3" /> : <Play className="w-3 h-3 text-[#0F8A4B]" />}
          </button>
          <button
            onClick={stepSimulation}
            className="p-1 hover:bg-[#EDECE7] rounded-[4px] text-[#161616] cursor-pointer transition-colors"
            title="Step next agent message & pulse"
          >
            <SkipForward className="w-3 h-3" />
          </button>
        </div>
      </div>
    </footer>
  );
};
