import React, { useEffect, useRef } from 'react';

interface LiveTerminalProps {
  /** The agent's recent tool calls and output, newest last: `HH:MM:SS $ command`, `! error`, `# what the model said`. */
  lines: readonly string[];
  /** Whose terminal this is (for the accessible name). */
  agentName: string;
  maxHeight?: number;
}

const STAMP = /^(\d{2}:\d{2}:\d{2}) (.*)$/;

function tone(body: string): string {
  if (body.startsWith('$ ')) return 'text-[#7EE2A8]';
  if (body.startsWith('! ')) return 'text-[#FF8A8A]';
  if (body.startsWith('# ')) return 'text-[#9A9A94]';
  if (body.startsWith('~ ')) return 'text-[#F2C46D]';
  if (body.startsWith('  exit')) return 'text-[#6B6B66]';
  return 'text-[#E8E6DF]';
}

/** What an agent is doing right now, as a terminal: it follows the newest line unless you have scrolled up to read. */
export const LiveTerminal: React.FC<LiveTerminalProps> = ({ lines, agentName, maxHeight = 240 }) => {
  const box = useRef<HTMLDivElement>(null);
  const following = useRef(true);

  useEffect(() => {
    const element = box.current;
    if (element && following.current) element.scrollTop = element.scrollHeight;
  }, [lines]);

  return (
    <div
      ref={box}
      role="log"
      aria-label={`Live terminal: ${agentName}`}
      onScroll={(event) => {
        const el = event.currentTarget;
        following.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
      }}
      style={{ maxHeight }}
      className="bg-[#161616] rounded-[8px] p-2.5 overflow-y-auto font-mono text-[10.5px] leading-[15px] select-text"
    >
      {lines.length === 0 ? (
        <div className="text-[#6B6B66]">Waiting for {agentName} to run something...</div>
      ) : (
        lines.map((line, index) => {
          const parts = STAMP.exec(line);
          const body = parts ? parts[2] : line;
          return (
            <div key={`${index}-${line.slice(0, 24)}`} className="flex gap-2 whitespace-pre-wrap break-words">
              {parts && <span className="text-[#5B5B56] shrink-0">{parts[1]}</span>}
              <span className={`${tone(body)} min-w-0 break-all`}>{body}</span>
            </div>
          );
        })
      )}
    </div>
  );
};
