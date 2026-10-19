import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { useScrum } from '../../context/ScrumContext';
import { MessageSquare, Flame, ShieldAlert, CheckCircle2, Search, Filter, Terminal, Copy, Check } from 'lucide-react';
import { Message } from '../../types';

export const MeetTab: React.FC = () => {
  const {
    meets,
    selectedMeet,
    setSelectedMeetId,
    messages,
    triggerDebate,
    setIsSmeModalOpen
  } = useScrum();

  const [searchQuery, setSearchQuery] = useState('');
  const [filterType, setFilterType] = useState<string>('all');
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (copyTimer.current) clearTimeout(copyTimer.current);
  }, []);

  // Filter messages based on search query and message type
  const filteredMessages = messages.filter(msg => {
    const matchesSearch = 
      msg.text.toLowerCase().includes(searchQuery.toLowerCase()) ||
      msg.senderName.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (msg.codeSnippet && msg.codeSnippet.toLowerCase().includes(searchQuery.toLowerCase()));

    if (!matchesSearch) return false;
    if (filterType === 'all') return true;
    if (filterType === 'debates') return msg.type === 'debate_challenge' || msg.isContradiction;
    if (filterType === 'sme') return msg.type === 'sme_input';
    if (filterType === 'consensus') return msg.type === 'consensus';
    return true;
  });

  const handleCopyCode = (id: string, code: string) => {
    navigator.clipboard.writeText(code);
    setCopiedId(id);
    if (copyTimer.current) clearTimeout(copyTimer.current);
    copyTimer.current = setTimeout(() => setCopiedId(null), 2000);
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-[#FCFCFB] overflow-hidden select-none">
      {/* Top Meet Selector Row */}
      <div className="h-[52px] px-6 bg-[#FFFFFF] border-b border-[#E2E0D9] flex items-center justify-between shrink-0">
        {/* Meet Pills */}
        <div className="flex items-center gap-2">
          {meets.map(meet => {
            const isLive = meet.status === 'live';
            const isSelected = selectedMeet.id === meet.id;

            return (
              <button
                key={meet.id}
                onClick={() => setSelectedMeetId(meet.id)}
                className={`px-3 py-1.5 rounded-[8px] text-[12px] font-semibold flex items-center gap-2 transition-all cursor-pointer ${
                  isSelected
                    ? isLive
                      ? 'bg-[#FDECEC] text-[#E60000] border border-[#E60000] shadow-[0_0_16px_rgba(230,0,0,0.2)]'
                      : 'bg-[#161616] text-[#FFFFFF]'
                    : 'bg-[#F4F3EE] hover:bg-[#EDECE7] text-[#5B5B5B] hover:text-[#161616] border border-[#E2E0D9]'
                }`}
              >
                {isLive && (
                  <span className="w-2 h-2 rounded-full bg-[#E60000] live-pulse" />
                )}
                <span>Meet {meet.number}</span>
                {isLive ? (
                  <span className="text-[9px] uppercase font-bold tracking-wider">LIVE</span>
                ) : (
                  <span className="text-[10px] mono text-[#5B5B5B]">({meet.elapsedTime})</span>
                )}
              </button>
            );
          })}
        </div>

        {/* Search & Filter Controls */}
        <div className="flex items-center gap-3">
          {/* Search Box */}
          <div className="relative flex items-center">
            <Search className="w-3.5 h-3.5 absolute left-2.5 text-[#5B5B5B]" />
            <input
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="Search transcript, code, DDL..."
              className="pl-8 pr-3 py-1 bg-[#F4F3EE] border border-[#E2E0D9] rounded-[6px] text-[11.5px] text-[#161616] placeholder-[#5B5B5B] outline-none focus:border-[#161616] w-56"
            />
          </div>

          {/* Type Filter */}
          <div className="flex items-center bg-[#F4F3EE] p-0.5 rounded-[6px] border border-[#E2E0D9] text-[11px] font-medium text-[#5B5B5B]">
            <button
              onClick={() => setFilterType('all')}
              className={`px-2 py-0.5 rounded-[4px] cursor-pointer transition-colors ${
                filterType === 'all' ? 'bg-[#FFFFFF] text-[#161616] shadow-xs font-semibold' : ''
              }`}
            >
              All ({messages.length})
            </button>
            <button
              onClick={() => setFilterType('debates')}
              className={`px-2 py-0.5 rounded-[4px] cursor-pointer transition-colors ${
                filterType === 'debates' ? 'bg-[#FFFFFF] text-[#B27000] shadow-xs font-semibold' : ''
              }`}
            >
              Debates
            </button>
            <button
              onClick={() => setFilterType('sme')}
              className={`px-2 py-0.5 rounded-[4px] cursor-pointer transition-colors ${
                filterType === 'sme' ? 'bg-[#FFFFFF] text-[#0057B8] shadow-xs font-semibold' : ''
              }`}
            >
              SME
            </button>
            <button
              onClick={() => setFilterType('consensus')}
              className={`px-2 py-0.5 rounded-[4px] cursor-pointer transition-colors ${
                filterType === 'consensus' ? 'bg-[#FFFFFF] text-[#0F8A4B] shadow-xs font-semibold' : ''
              }`}
            >
              Consensus
            </button>
          </div>
        </div>
      </div>

      {/* Main Transcript Scrollable View */}
      <div className="flex-1 p-6 overflow-y-auto flex flex-col gap-4 max-w-4xl mx-auto w-full">
        {/* Meet Banner */}
        <div className="p-4 bg-[#FFFFFF] rounded-[12px] border border-[#E2E0D9] shadow-xs">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[11px] font-bold uppercase tracking-wider text-[#5B5B5B]">
              Agenda & Scope
            </span>
            <span className="text-[11px] mono text-[#0F8A4B] font-semibold">
              Consensus: {selectedMeet.consensusRate}%
            </span>
          </div>
          <h2 className="text-[16px] font-bold text-[#161616] mb-1">
            {selectedMeet.title}
          </h2>
          <p className="text-[12.5px] text-[#5B5B5B] leading-relaxed">
            {selectedMeet.topic}
          </p>
        </div>

        {/* Message Blocks */}
        <div className="flex flex-col gap-3">
          {filteredMessages.map((msg, index) => {
            const isChallenge = msg.type === 'debate_challenge' || msg.isContradiction;
            const isSme = msg.type === 'sme_input';
            const isConsensus = msg.type === 'consensus';
            const isArtifact = msg.type === 'artifact_update';

            return (
              <motion.div
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
                key={msg.id}
                className={`p-4 rounded-[12px] border text-[13px] leading-relaxed relative transition-shadow ${
                  isChallenge
                    ? 'bg-[#FBF1DC]/40 border-l-[4px] border-l-[#B27000] border-[#E2E0D9] shadow-xs'
                    : isSme
                    ? 'bg-[#E8F0FA]/50 border-l-[4px] border-l-[#0057B8] border-[#E2E0D9] shadow-xs'
                    : isConsensus
                    ? 'bg-[#E7F5EC]/50 border-l-[4px] border-l-[#0F8A4B] border-[#E2E0D9] shadow-xs'
                    : isArtifact
                    ? 'bg-[#F4F3EE] border-l-[4px] border-l-[#161616] border-[#E2E0D9]'
                    : 'bg-[#FFFFFF] border-l-[4px] border-l-[#5B5B5B] border-[#E2E0D9] shadow-xs'
                }`}
              >
                {/* Message Header */}
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-[13.5px] text-[#161616]">
                      {msg.senderName}
                    </span>
                    <span className="text-[11px] text-[#5B5B5B] font-medium">
                      ({msg.senderRole})
                    </span>

                    {/* Tag badge */}
                    {isChallenge && (
                      <span className="text-[10px] font-bold text-[#B27000] bg-[#FBF1DC] px-1.5 py-0.2 rounded-[3px] border border-[#B27000]/30 uppercase tracking-wide">
                        CHALLENGE / DEBATE
                      </span>
                    )}
                    {isSme && (
                      <span className="text-[10px] font-bold text-[#0057B8] bg-[#E8F0FA] px-1.5 py-0.2 rounded-[3px] border border-[#0057B8]/30 uppercase tracking-wide">
                        SME DIRECTIVE
                      </span>
                    )}
                    {isConsensus && (
                      <span className="text-[10px] font-bold text-[#0F8A4B] bg-[#E7F5EC] px-1.5 py-0.2 rounded-[3px] border border-[#0F8A4B]/30 uppercase tracking-wide">
                        CONSENSUS GATE
                      </span>
                    )}
                  </div>

                  <span className="mono text-[11px] text-[#5B5B5B] font-medium">
                    {msg.timestamp}
                  </span>
                </div>

                {/* Message Body */}
                <p className="text-[#161616] font-normal leading-relaxed whitespace-pre-line">
                  {msg.text}
                </p>

                {/* Code Snippet Box (if any) */}
                {msg.codeSnippet && (
                  <div className="mt-3 rounded-[8px] bg-[#161616] border border-[#2B2B2B] overflow-hidden">
                    <div className="px-3 py-1.5 bg-[#222222] border-b border-[#2B2B2B] flex items-center justify-between text-[11px] mono text-[#C9C6BC]">
                      <div className="flex items-center gap-1.5">
                        <Terminal className="w-3.5 h-3.5 text-[#0F8A4B]" />
                        <span>DDL / Code Verification</span>
                      </div>
                      <button
                        onClick={() => handleCopyCode(msg.id, msg.codeSnippet!)}
                        className="hover:text-[#FFFFFF] cursor-pointer flex items-center gap-1"
                      >
                        {copiedId === msg.id ? <Check className="w-3 h-3 text-[#0F8A4B]" /> : <Copy className="w-3 h-3" />}
                        <span>{copiedId === msg.id ? 'Copied' : 'Copy'}</span>
                      </button>
                    </div>
                    <pre className="p-3 text-[11.5px] mono text-[#F4F3EE] overflow-x-auto leading-normal">
                      <code>{msg.codeSnippet}</code>
                    </pre>
                  </div>
                )}
              </motion.div>
            );
          })}
          <div ref={bottomRef} />
        </div>

        {/* Quick Interaction Strip at bottom of Meet */}
        <div className="mt-4 p-3 bg-[#FFFFFF] rounded-[10px] border border-[#E2E0D9] flex items-center justify-between shadow-xs">
          <div className="text-[12px] text-[#5B5B5B]">
            Need to steer the ongoing debate or inject an invariant?
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={triggerDebate}
              className="px-3 py-1.5 text-[11.5px] font-semibold bg-[#F4F3EE] hover:bg-[#EDECE7] text-[#161616] rounded-[6px] border border-[#E2E0D9] cursor-pointer transition-colors"
            >
              Trigger Network Challenge
            </button>
            <button
              onClick={() => setIsSmeModalOpen(true)}
              className="px-3 py-1.5 text-[11.5px] font-semibold bg-[#0057B8] hover:bg-[#004694] text-[#FFFFFF] rounded-[6px] cursor-pointer transition-colors"
            >
              Enforce SME Directive
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
