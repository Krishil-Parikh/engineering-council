import React, { useRef, useEffect } from 'react';
import { motion } from 'motion/react';
import { useScrum } from '../../context/ScrumContext';
import { Odometer } from '../common/Odometer';
import { Maximize2, ArrowUpRight, MessageSquare, Layers, Cpu, CheckCircle2, Flame, UserCheck } from 'lucide-react';
import { MiniCanvas } from './MiniCanvas';

export const OverviewTab: React.FC = () => {
  const {
    activeAgentsCount,
    agents,
    totalMessagesToday,
    prdAcceptanceRatio,
    messages,
    setActiveTab,
    setSelectedAgent,
    selectedMeet
  } = useScrum();

  const tickerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll transcript ticker on new message
  useEffect(() => {
    if (tickerRef.current) {
      tickerRef.current.scrollTop = tickerRef.current.scrollHeight;
    }
  }, [messages.length]);

  return (
    <div className="flex-1 flex flex-col p-6 overflow-y-auto gap-5 select-none bg-[#FCFCFB]">
      {/* ROW 1: Hero KPI Strip (4 Tiles, 96px tall, Mega numerals, distinct visualizations) */}
      <div className="grid grid-cols-4 gap-4">
        {/* Tile 1: Agents Active */}
        <div className="h-[96px] p-4 bg-[#FCFCFB]/90 backdrop-blur-md rounded-[16px] border border-[#E2E0D9] shadow-[0_1px_2px_rgba(22,22,22,0.04)] flex flex-col justify-between">
          <div className="flex items-center justify-between text-[10.5px] font-bold tracking-wider uppercase text-[#5B5B5B]">
            <span>AGENTS ACTIVE</span>
            <span className="w-2 h-2 rounded-full bg-[#0F8A4B]" />
          </div>
          <div className="text-[38px] leading-[40px] font-bold text-[#161616] tracking-tight">
            <Odometer value={`${activeAgentsCount}/6`} />
          </div>
          {/* Sparkline visualization */}
          <div className="flex items-end gap-[3px] h-3 w-full">
            {[20, 35, 60, 80, 70, 45, 90, 85, 95, 70].map((h, i) => (
              <div
                key={i}
                className="w-full bg-[#161616] rounded-xs"
                style={{ height: `${h}%` }}
              />
            ))}
          </div>
        </div>

        {/* Tile 2: Messages Today */}
        <div className="h-[96px] p-4 bg-[#FCFCFB]/90 backdrop-blur-md rounded-[16px] border border-[#E2E0D9] shadow-[0_1px_2px_rgba(22,22,22,0.04)] flex flex-col justify-between">
          <div className="flex items-center justify-between text-[10.5px] font-bold tracking-wider uppercase text-[#5B5B5B]">
            <span>MESSAGES TODAY</span>
            <span className="text-[10px] mono text-[#0F8A4B] font-semibold">+12%</span>
          </div>
          <div className="text-[38px] leading-[40px] font-bold text-[#161616] tracking-tight">
            <Odometer value={totalMessagesToday} />
          </div>
          {/* Micro bar distribution */}
          <div className="flex items-end gap-[3px] h-3 w-full">
            {[40, 25, 70, 85, 90, 65, 80, 95, 60, 88].map((h, i) => (
              <div
                key={i}
                className="w-full bg-[#5B5B5B] rounded-xs"
                style={{ height: `${h}%` }}
              />
            ))}
          </div>
        </div>

        {/* Tile 3: PRD Acceptance */}
        <div className="h-[96px] p-4 bg-[#FCFCFB]/90 backdrop-blur-md rounded-[16px] border border-[#E2E0D9] shadow-[0_1px_2px_rgba(22,22,22,0.04)] flex flex-col justify-between">
          <div className="flex items-center justify-between text-[10.5px] font-bold tracking-wider uppercase text-[#5B5B5B]">
            <span>PRD ACCEPTANCE</span>
            <span className="text-[10px] font-semibold text-[#0F8A4B]">Consensus</span>
          </div>
          <div className="text-[38px] leading-[40px] font-bold text-[#161616] tracking-tight">
            <Odometer value={prdAcceptanceRatio} />
          </div>
          {/* Dot Tracker: 6 circles */}
          <div className="flex items-center gap-2">
            {[1, 2, 3, 4, 5, 6].map(i => (
              <span
                key={i}
                className="w-2.5 h-2.5 rounded-full bg-[#0F8A4B]"
                title="Agent Verified & Approved"
              />
            ))}
          </div>
        </div>

        {/* Tile 4: Time in Phase */}
        <div className="h-[96px] p-4 bg-[#FCFCFB]/90 backdrop-blur-md rounded-[16px] border border-[#E2E0D9] shadow-[0_1px_2px_rgba(22,22,22,0.04)] flex flex-col justify-between">
          <div className="flex items-center justify-between text-[10.5px] font-bold tracking-wider uppercase text-[#5B5B5B]">
            <span>TIME IN PHASE</span>
            <span className="text-[10px] mono text-[#161616] font-semibold">Sprint 03</span>
          </div>
          <div className="text-[38px] leading-[40px] font-bold text-[#161616] tracking-tight">
            2h 14m
          </div>
          {/* Progress Bar 68% */}
          <div className="w-full h-2 bg-[#EDECE7] rounded-full overflow-hidden">
            <div className="h-full bg-[#161616] rounded-full w-[68%]" />
          </div>
        </div>
      </div>

      {/* ROW 2: Split Mini Canvas (60%) + Transcript Ticker (40%) (~520px) */}
      <div className="flex gap-4 h-[500px]">
        {/* Left 60%: Mini Canvas with Morph-To-Canvas */}
        <div className="w-[60%] bg-[#FFFFFF] rounded-[16px] border border-[#E2E0D9] flex flex-col overflow-hidden relative shadow-[0_1px_3px_rgba(22,22,22,0.04)]">
          {/* Mini Canvas Header */}
          <div className="h-10 px-4 border-b border-[#E2E0D9] flex items-center justify-between bg-[#FCFCFB]">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-[#E60000] live-pulse" />
              <span className="text-[11.5px] font-bold tracking-wider uppercase text-[#161616]">
                LIVE DELEGATION GRAPH
              </span>
              <span className="text-[10px] mono text-[#5B5B5B] bg-[#F4F3EE] px-1.5 py-0.2 rounded-[2px] border border-[#E2E0D9]">
                Interactive
              </span>
            </div>

            <button
              onClick={() => setActiveTab('canvas')}
              className="flex items-center gap-1.5 text-[11px] font-semibold text-[#161616] hover:text-[#E60000] transition-colors cursor-pointer bg-[#F4F3EE] hover:bg-[#EDECE7] px-2.5 py-1 rounded-[6px] border border-[#E2E0D9]"
            >
              <span>Expand</span>
              <Maximize2 className="w-3 h-3" />
            </button>
          </div>

          {/* Mini Canvas Body */}
          <div className="flex-1 relative bg-[#FCFCFB] overflow-hidden">
            <MiniCanvas onExpand={() => setActiveTab('canvas')} />
          </div>
        </div>

        {/* Right 40%: Live Transcript Ticker with Morph-To-Meet */}
        <div className="w-[40%] bg-[#FFFFFF] rounded-[16px] border border-[#E2E0D9] flex flex-col overflow-hidden shadow-[0_1px_3px_rgba(22,22,22,0.04)]">
          {/* Ticker Header */}
          <div className="h-10 px-4 border-b border-[#E2E0D9] flex items-center justify-between bg-[#FCFCFB]">
            <div className="flex items-center gap-2">
              <MessageSquare className="w-3.5 h-3.5 text-[#5B5B5B]" />
              <span className="text-[11.5px] font-bold tracking-wider uppercase text-[#161616]">
                {selectedMeet.title.split('—')[0]}
              </span>
            </div>

            <button
              onClick={() => setActiveTab('meet')}
              className="flex items-center gap-1 text-[11px] font-semibold text-[#0057B8] hover:underline cursor-pointer"
            >
              <span>Open full transcript</span>
              <ArrowUpRight className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Scrolling Ticker Messages */}
          <div
            ref={tickerRef}
            className="flex-1 p-3.5 overflow-y-auto flex flex-col gap-2.5 bg-[#FCFCFB]/50"
          >
            {messages.slice(-8).map(msg => {
              const isChallenge = msg.type === 'debate_challenge';
              const isSme = msg.type === 'sme_input';
              const isConsensus = msg.type === 'consensus';

              return (
                <div
                  key={msg.id}
                  className={`p-2.5 rounded-[8px] border text-[12px] leading-relaxed transition-all ${
                    isChallenge
                      ? 'bg-[#FBF1DC]/40 border-l-[3px] border-l-[#B27000] border-[#E2E0D9]'
                      : isSme
                      ? 'bg-[#E8F0FA]/50 border-l-[3px] border-l-[#0057B8] border-[#E2E0D9]'
                      : isConsensus
                      ? 'bg-[#E7F5EC]/40 border-l-[3px] border-l-[#0F8A4B] border-[#E2E0D9]'
                      : 'bg-[#FFFFFF] border-l-[3px] border-l-[#161616] border-[#E2E0D9]'
                  }`}
                >
                  <div className="flex items-center justify-between text-[10.5px] mb-1">
                    <span className="font-bold text-[#161616] flex items-center gap-1.5">
                      {msg.senderName}
                      <span className="text-[9.5px] font-normal text-[#5B5B5B]">({msg.senderRole})</span>
                    </span>
                    <span className="mono text-[#5B5B5B] text-[9.5px]">{msg.timestamp}</span>
                  </div>
                  <p className="text-[#161616] font-normal">{msg.text}</p>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* ROW 3: Agent Grid (Responsive row, glass on hover, Kowalski depth) */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-bold tracking-wider uppercase text-[#5B5B5B]">
            AGENT WORKBENCH (6 NODES)
          </span>
          <span className="text-[10.5px] text-[#5B5B5B]">Hover for context depth · Click to inspect</span>
        </div>

        <div className="grid grid-cols-6 gap-3">
          {agents.map(agent => (
            <motion.div
              key={agent.id}
              onClick={() => setSelectedAgent(agent)}
              whileHover={{ y: -2, transition: { duration: 0.16 } }}
              className={`p-3 rounded-[12px] border transition-all cursor-pointer select-none ${
                agent.isLive
                  ? 'bg-[#FFFFFF] border-[#E60000] shadow-[0_0_16px_rgba(230,0,0,0.18)]'
                  : 'bg-[#FFFFFF] hover:bg-[#FCFCFB] hover:backdrop-blur-md border-[#E2E0D9] hover:border-[#161616]/40 hover:shadow-[0_8px_24px_rgba(22,22,22,0.08)]'
              }`}
            >
              <div className="flex items-center justify-between mb-1.5">
                <span className="font-bold text-[12.5px] text-[#161616] truncate">
                  {agent.name}
                </span>
                <span className="text-[9px] mono font-semibold text-[#5B5B5B] bg-[#F4F3EE] px-1 rounded-xs">
                  {agent.avatarNumber}
                </span>
              </div>

              <div className="text-[10px] font-medium text-[#5B5B5B] truncate mb-2">
                {agent.roleTitle.split('·')[0]}
              </div>

              {/* Sparkline */}
              <div className="flex items-end gap-[2px] h-4 bg-[#F4F3EE] p-1 rounded-[4px] mb-2">
                {agent.sparkline.slice(-6).map((val, idx) => (
                  <div
                    key={idx}
                    className="w-full bg-[#161616] rounded-xs"
                    style={{ height: `${Math.max(20, (val / 100) * 100)}%` }}
                  />
                ))}
              </div>

              <div className="flex items-center justify-between text-[9.5px] mono text-[#5B5B5B]">
                <span>{agent.confidenceScore}% conf</span>
                {agent.isLive && <span className="text-[#E60000] font-bold uppercase">Live</span>}
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  );
};
