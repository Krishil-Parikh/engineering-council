import React from 'react';
import { Settings, Play, Pause, FastForward } from 'lucide-react';
import { PhaseId } from '../types';

interface TopBarProps {
  currentPhase: PhaseId;
  isLive: boolean;
  autoPlay: boolean;
  onToggleAutoPlay: () => void;
  playbackSpeed: number;
  onChangePlaybackSpeed: () => void;
  onOpenSettings: () => void;
}

export const TopBar: React.FC<TopBarProps> = ({
  isLive,
  autoPlay,
  onToggleAutoPlay,
  playbackSpeed,
  onChangePlaybackSpeed,
  onOpenSettings,
}) => {
  return (
    <header className="h-14 border-b border-[#E7E6DF] bg-[#FCFCFB]/90 backdrop-blur-md sticky top-0 z-40 px-6 flex items-center justify-between select-none">
      {/* Brand Zone */}
      <div className="flex items-center gap-3">
        <span className="text-[#E60000] text-sm">◆</span>
        <span className="text-[13px] font-semibold tracking-wide uppercase text-[#161616]">
          Control Plane
        </span>
        <span className="text-xs text-[#8E8E8E] hidden sm:inline" aria-hidden="true">/</span>
        <span className="text-xs text-[#5B5B5B] font-mono hidden sm:inline">
          sdlc.agent-mesh.v3
        </span>
      </div>

      {/* Center Zone: Generative Co-Pilot Orchestrator */}
      <div className="hidden md:flex items-center gap-3">
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-[#F4F3EE] border border-[#E7E6DF] text-xs text-[#5B5B5B]">
          <span className="text-[11px] font-mono uppercase text-[#8E8E8E]">Orchestrator:</span>
          <button
            onClick={onToggleAutoPlay}
            className="flex items-center gap-1 px-2 py-0.5 rounded text-[11.5px] font-medium text-[#161616] hover:bg-[#EAE9E2] transition-colors"
            title={autoPlay ? 'Pause autonomous phase progression' : 'Resume autonomous phase progression'}
          >
            {autoPlay ? <Pause className="w-3 h-3 text-[#E60000]" /> : <Play className="w-3 h-3 text-[#161616]" />}
            <span>{autoPlay ? 'Autonomous' : 'Paused'}</span>
          </button>
          <span className="text-[#D5D3CA]">|</span>
          <button
            onClick={onChangePlaybackSpeed}
            className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-mono text-[#5B5B5B] hover:text-[#161616] hover:bg-[#EAE9E2] transition-colors"
            title="Adjust simulation speed"
          >
            <FastForward className="w-2.5 h-2.5" />
            <span>{playbackSpeed}x</span>
          </button>
        </div>
      </div>

      {/* Right Zone: Live Indicator & Settings */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            {isLive && (
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#E60000] opacity-75" />
            )}
            <span className={`relative inline-flex rounded-full h-2 w-2 ${isLive ? 'bg-[#E60000]' : 'bg-[#8E8E8E]'}`} />
          </span>
          <span className="text-xs font-mono font-medium text-[#161616]">Live</span>
        </div>

        <button
          onClick={onOpenSettings}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-[#5B5B5B] hover:text-[#161616] hover:bg-[#F4F3EE] transition-all"
          aria-label="Open system settings"
        >
          <Settings className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">Settings</span>
        </button>
      </div>
    </header>
  );
};
