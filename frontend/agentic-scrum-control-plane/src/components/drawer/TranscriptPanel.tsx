import React, { useState } from 'react';
import { TranscriptMessage } from '../../types';
import { Search } from 'lucide-react';

interface TranscriptPanelProps {
  transcript: TranscriptMessage[];
}

export const TranscriptPanel: React.FC<TranscriptPanelProps> = ({ transcript }) => {
  const [query, setQuery] = useState('');

  const filtered = transcript.filter(
    (m) =>
      m.content.toLowerCase().includes(query.toLowerCase()) ||
      m.speakerName.toLowerCase().includes(query.toLowerCase())
  );

  return (
    <div className="w-full h-full flex flex-col justify-between py-1">
      <div className="flex items-center justify-between pb-3 border-b border-[#E7E6DF]">
        <div className="flex items-center gap-3">
          <span className="text-xs font-semibold text-[#161616]">
            Full SDLC Event & Dialogue Log
          </span>
          <span className="text-xs text-[#8E8E8E]">·</span>
          <span className="text-xs text-[#5B5B5B] font-mono">
            {transcript.length} logged entries
          </span>
        </div>

        {/* Search */}
        <div className="flex items-center gap-2 px-2.5 py-1 rounded-lg bg-[#F4F3EE] border border-[#E7E6DF] w-56">
          <Search className="w-3 h-3 text-[#8E8E8E]" />
          <input
            type="text"
            placeholder="Search transcript..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full bg-transparent border-0 text-xs focus:outline-none text-[#161616]"
          />
        </div>
      </div>

      <div className="space-y-2.5 my-2 overflow-y-auto max-h-[190px] pr-2">
        {filtered.map((msg) => (
          <div
            key={msg.id}
            className="p-2.5 rounded-lg bg-[#F4F3EE] border border-[#E7E6DF] text-xs"
          >
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-2">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: msg.avatarColor }}
                />
                <span className="font-semibold text-[#161616]">{msg.speakerName}</span>
                <span className="text-[10px] text-[#8E8E8E]">{msg.speakerRole}</span>
              </div>
              <span className="text-[10px] font-mono text-[#8E8E8E]">{msg.timestamp}</span>
            </div>
            <p className="text-[#5B5B5B] leading-relaxed">{msg.content}</p>
          </div>
        ))}
      </div>

      <div className="pt-2 border-t border-[#E7E6DF] flex items-center justify-between text-[11px] text-[#8E8E8E] font-mono">
        <span>Redis Stream ID: 1727038312000-0</span>
        <span>Continuous retention enabled</span>
      </div>
    </div>
  );
};
