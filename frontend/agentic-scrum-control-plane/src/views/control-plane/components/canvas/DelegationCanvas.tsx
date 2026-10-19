import React, { useState, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { useScrum } from '../../context/ScrumContext';
import { Agent, DelegationEdge } from '../../types';
import { 
  ZoomIn, 
  ZoomOut, 
  Maximize2, 
  RotateCcw, 
  Layers, 
  Sparkles, 
  ShieldCheck, 
  FileText,
  Activity,
  Cpu
} from 'lucide-react';

interface NodeLayout {
  id: string;
  x: number;
  y: number;
  type: 'agent' | 'sme' | 'artifact';
  label: string;
  roleTitle?: string;
  agentRef?: Agent;
  artifactRef?: { name: string; version: string; status: string };
}

interface DelegationCanvasProps {
  isMini?: boolean;
  onExpand?: () => void;
}

export const DelegationCanvas: React.FC<DelegationCanvasProps> = ({ isMini = false, onExpand }) => {
  const { agents, edges, selectedAgent, setSelectedAgent, artifacts } = useScrum();
  const [zoom, setZoom] = useState<number>(isMini ? 0.78 : 1);
  const [pan, setPan] = useState<{ x: number; y: number }>({ x: isMini ? -20 : 40, y: isMini ? -10 : 30 });
  const [isDragging, setIsDragging] = useState(false);
  const dragStartRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });

  // Node position map (hierarchical layout matching fintech command architecture)
  const nodes: NodeLayout[] = [
    // Top Row: Scrum Master & SME
    { id: 'agent-sm', x: 380, y: 50, type: 'agent', label: 'ScrumMaster', roleTitle: 'Sprint Arbiter', agentRef: agents.find(a => a.id === 'agent-sm') },
    { id: 'sme-01', x: 680, y: 50, type: 'sme', label: 'Business SME', roleTitle: 'FINMA Compliance' },

    // Middle Row: Backend Lead, DB Lead, Frontend Lead
    { id: 'agent-03', x: 200, y: 220, type: 'agent', label: 'Agent-03', roleTitle: 'Backend Lead · Raft', agentRef: agents.find(a => a.id === 'agent-03') },
    { id: 'agent-05', x: 440, y: 220, type: 'agent', label: 'Agent-05', roleTitle: 'Database · Partitioning', agentRef: agents.find(a => a.id === 'agent-05') },
    { id: 'agent-01', x: 680, y: 220, type: 'agent', label: 'Agent-01', roleTitle: 'Frontend Principal', agentRef: agents.find(a => a.id === 'agent-01') },

    // Third Row: Streaming, QA/Chaos, Telemetry
    { id: 'agent-04', x: 120, y: 390, type: 'agent', label: 'Agent-04', roleTitle: 'Stream Infra · Kafka', agentRef: agents.find(a => a.id === 'agent-04') },
    { id: 'agent-06', x: 340, y: 390, type: 'agent', label: 'Agent-06', roleTitle: 'QA · Chaos & Splits', agentRef: agents.find(a => a.id === 'agent-06') },
    { id: 'agent-02', x: 680, y: 390, type: 'agent', label: 'Agent-02', roleTitle: 'Real-time WebSocket', agentRef: agents.find(a => a.id === 'agent-02') },

    // Bottom Row: Target Artifacts
    { id: 'art-01', x: 260, y: 540, type: 'artifact', label: 'PRD.md', artifactRef: { name: 'PRD.md', version: 'v2.3', status: 'Approved (6/6)' } },
    { id: 'art-02', x: 500, y: 540, type: 'artifact', label: 'architecture.md', artifactRef: { name: 'architecture.md', version: 'v1.4', status: 'Review (5/6)' } }
  ];

  // Artifact edges
  const artifactEdges: DelegationEdge[] = [
    { id: 'e-sm-art1', source: 'agent-sm', target: 'art-01', label: 'Signoff', isActive: true, latencyMs: 2 },
    { id: 'e-05-art2', source: 'agent-05', target: 'art-02', label: 'DDL Update', isActive: true, latencyMs: 5 },
    { id: 'e-03-art2', source: 'agent-03', target: 'art-02', label: 'Raft Spec', isActive: true, latencyMs: 4 }
  ];

  const allEdges = [...edges, ...artifactEdges];

  // Selected neighbors calculation for Focus Mode (§5.2)
  const connectedNodeIds = new Set<string>();
  if (selectedAgent) {
    connectedNodeIds.add(selectedAgent.id);
    allEdges.forEach(e => {
      if (e.source === selectedAgent.id) connectedNodeIds.add(e.target);
      if (e.target === selectedAgent.id) connectedNodeIds.add(e.source);
    });
  }

  // Mouse pan handlers
  const handleMouseDown = (e: React.MouseEvent) => {
    if (isMini) return;
    setIsDragging(true);
    dragStartRef.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging || isMini) return;
    setPan({
      x: e.clientX - dragStartRef.current.x,
      y: e.clientY - dragStartRef.current.y
    });
  };

  const handleMouseUp = () => setIsDragging(false);

  return (
    <div
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      className={`w-full h-full relative overflow-hidden select-none bg-[#FCFCFB] ${
        isMini ? 'cursor-pointer' : isDragging ? 'cursor-grabbing' : 'cursor-grab'
      }`}
      onClick={isMini ? onExpand : undefined}
    >
      {/* Background Dot Grid + Radial Vignette */}
      <div 
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage: 'radial-gradient(#161616 1px, transparent 1px)',
          backgroundSize: '24px 24px',
          opacity: 0.08
        }}
      />
      <div 
        className="absolute inset-0 pointer-events-none"
        style={{
          background: 'radial-gradient(ellipse at center, transparent 40%, rgba(22,22,22,0.04) 100%)'
        }}
      />

      {/* SVG Edges Layer */}
      <svg
        className="absolute inset-0 w-full h-full pointer-events-none z-0"
        style={{
          transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
          transformOrigin: '0 0'
        }}
      >
        <defs>
          {/* Animated gradient for active edge transmission (§7.3) */}
          <linearGradient id="edge-active-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#161616" />
            <stop offset="50%" stopColor="#E60000" />
            <stop offset="100%" stopColor="#161616" />
          </linearGradient>

          <filter id="glow-edge" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>

        {allEdges.map(edge => {
          const sourceNode = nodes.find(n => n.id === edge.source);
          const targetNode = nodes.find(n => n.id === edge.target);
          if (!sourceNode || !targetNode) return null;

          // Node center offsets (cards are ~170w x ~75h)
          const sx = sourceNode.x + 85;
          const sy = sourceNode.y + 40;
          const tx = targetNode.x + 85;
          const ty = targetNode.y + 35;

          // Smooth bezier curve
          const dx = tx - sx;
          const dy = ty - sy;
          const cx1 = sx + dx * 0.1;
          const cy1 = sy + dy * 0.6;
          const cx2 = sx + dx * 0.8;
          const cy2 = sy + dy * 0.4;
          const pathD = `M ${sx} ${sy} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${tx} ${ty}`;

          const isEdgeSelected = selectedAgent && (edge.source === selectedAgent.id || edge.target === selectedAgent.id);
          const isDimmed = selectedAgent && !isEdgeSelected;

          return (
            <g key={edge.id} opacity={isDimmed ? 0.25 : 1} className="transition-opacity duration-300">
              {/* Resting Edge Path */}
              <path
                d={pathD}
                fill="none"
                stroke={edge.isActive ? '#C9C6BC' : '#E2E0D9'}
                strokeWidth={edge.isActive ? 2 : 1.5}
              />

              {/* Active Animated Gradient Dash Pulse */}
              {edge.isActive && (
                <path
                  d={pathD}
                  fill="none"
                  stroke="url(#edge-active-gradient)"
                  strokeWidth="2.5"
                  className="edge-pulse"
                />
              )}

              {/* Edge Latency Badge in center */}
              {!isMini && edge.isActive && (
                <g transform={`translate(${(sx + tx) / 2}, ${(sy + ty) / 2})`}>
                  <rect
                    x="-18"
                    y="-9"
                    width="36"
                    height="18"
                    rx="4"
                    fill="#FFFFFF"
                    stroke="#E2E0D9"
                    strokeWidth="1"
                  />
                  <text
                    x="0"
                    y="3"
                    textAnchor="middle"
                    fontSize="9.5"
                    fontFamily="var(--font-mono)"
                    fontWeight="600"
                    fill="#161616"
                  >
                    {edge.latencyMs}ms
                  </text>
                </g>
              )}
            </g>
          );
        })}
      </svg>

      {/* HTML Nodes Layer */}
      <div
        className="absolute inset-0 pointer-events-none z-10"
        style={{
          transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
          transformOrigin: '0 0'
        }}
      >
        {nodes.map(node => {
          const isSelected = selectedAgent?.id === node.id;
          const isConnected = !selectedAgent || connectedNodeIds.has(node.id);
          const opacity = isConnected ? 1 : 0.45;
          const isLive = node.agentRef?.isLive;

          if (node.type === 'agent') {
            const agent = node.agentRef;
            if (!agent) {
              return (
                <div
                  key={node.id}
                  style={{
                    left: `${node.x}px`,
                    top: `${node.y}px`,
                    opacity,
                  }}
                  className="absolute w-[185px] p-2.5 rounded-[12px] bg-[#F4F3EE] border border-dashed border-[#C9C6BC] pointer-events-none"
                >
                  <span className="font-bold text-[12.5px] text-[#5B5B5B] truncate">{node.label}</span>
                  <div className="text-[10px] text-[#8E8E8E] font-medium">Unavailable in snapshot</div>
                </div>
              );
            }
            return (
              <motion.div
                key={node.id}
                onClick={e => {
                  e.stopPropagation();
                  setSelectedAgent(agent);
                }}
                style={{
                  left: `${node.x}px`,
                  top: `${node.y}px`,
                  opacity
                }}
                className={`absolute w-[185px] p-2.5 rounded-[12px] bg-[#FFFFFF]/90 backdrop-blur-md border pointer-events-auto transition-all duration-200 ${
                  isLive
                    ? 'border-[#E60000] shadow-[0_0_24px_rgba(230,0,0,0.22)]'
                    : isSelected
                    ? 'border-[#161616] ring-2 ring-[#161616] shadow-md'
                    : 'border-[#E2E0D9] shadow-xs hover:border-[#C9C6BC]'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className={`w-2 h-2 rounded-full ${isLive ? 'bg-[#E60000] live-pulse' : 'bg-[#0F8A4B]'}`} />
                    <span className="font-bold text-[12.5px] text-[#161616] truncate">{node.label}</span>
                  </div>
                  {agent.subAgentsCount ? (
                    <span className="text-[9.5px] font-bold text-[#5B5B5B] bg-[#F4F3EE] px-1.5 py-0.2 rounded-full border border-[#E2E0D9]">
                      +{agent.subAgentsCount}
                    </span>
                  ) : (
                    <span className="text-[9px] mono text-[#5B5B5B]">{agent.avatarNumber}</span>
                  )}
                </div>

                <div className="text-[10px] text-[#5B5B5B] truncate font-medium mb-1.5">
                  {node.roleTitle}
                </div>

                <div className="pt-1.5 border-t border-[#EDECE7] flex items-center justify-between text-[9px] mono text-[#5B5B5B]">
                  <span>{agent.tokensVelocity} tok/s</span>
                  <span className="text-[#0F8A4B] font-semibold">{agent.confidenceScore}%</span>
                </div>
              </motion.div>
            );
          }

          if (node.type === 'sme') {
            return (
              <div
                key={node.id}
                style={{ left: `${node.x}px`, top: `${node.y}px`, opacity }}
                className="absolute w-[185px] p-2.5 rounded-[12px] bg-[#E8F0FA]/90 backdrop-blur-md border border-[#0057B8]/40 shadow-xs pointer-events-auto"
              >
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-1.5">
                    <ShieldCheck className="w-3.5 h-3.5 text-[#0057B8]" />
                    <span className="font-bold text-[12.5px] text-[#0057B8]">{node.label}</span>
                  </div>
                  <span className="text-[9px] font-bold uppercase tracking-wider text-[#0057B8] bg-[#0057B8]/10 px-1 rounded-xs">
                    GOVERNANCE
                  </span>
                </div>
                <div className="text-[10px] text-[#5B5B5B] font-medium">FINMA Circular 2026/02</div>
              </div>
            );
          }

          // Artifact Node
          return (
            <div
              key={node.id}
              style={{ left: `${node.x}px`, top: `${node.y}px`, opacity }}
              className="absolute w-[185px] p-2.5 rounded-[8px] bg-[#F4F3EE] border border-[#C9C6BC] shadow-xs pointer-events-auto"
            >
              <div className="flex items-center gap-1.5 mb-1">
                <FileText className="w-3.5 h-3.5 text-[#161616]" />
                <span className="font-mono font-bold text-[12px] text-[#161616] truncate">
                  {node.artifactRef?.name}
                </span>
                <span className="text-[9px] mono text-[#5B5B5B]">{node.artifactRef?.version}</span>
              </div>
              <div className="text-[10px] text-[#0F8A4B] font-semibold">
                {node.artifactRef?.status}
              </div>
            </div>
          );
        })}
      </div>

      {/* Floating Canvas Controls (for full canvas tab) */}
      {!isMini && (
        <div className="absolute bottom-5 right-5 z-20 flex items-center gap-1.5 bg-[#FFFFFF]/90 backdrop-blur-md p-1.5 rounded-[10px] border border-[#E2E0D9] shadow-md">
          <button
            onClick={() => setZoom(prev => Math.min(prev + 0.15, 1.8))}
            className="p-1.5 hover:bg-[#F4F3EE] rounded-[6px] text-[#161616] cursor-pointer"
            title="Zoom In"
          >
            <ZoomIn className="w-4 h-4" />
          </button>
          <button
            onClick={() => setZoom(prev => Math.max(prev - 0.15, 0.5))}
            className="p-1.5 hover:bg-[#F4F3EE] rounded-[6px] text-[#161616] cursor-pointer"
            title="Zoom Out"
          >
            <ZoomOut className="w-4 h-4" />
          </button>
          <button
            onClick={() => {
              setZoom(1);
              setPan({ x: 40, y: 30 });
            }}
            className="p-1.5 hover:bg-[#F4F3EE] rounded-[6px] text-[#161616] cursor-pointer"
            title="Reset Viewport"
          >
            <RotateCcw className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Focus Mode helper chip */}
      {!isMini && selectedAgent && (
        <div className="absolute top-4 left-4 z-20 flex items-center gap-2 bg-[#161616] text-[#FFFFFF] px-3 py-1.5 rounded-[8px] text-[11px] font-medium shadow-md">
          <span>Focus Mode: {selectedAgent.name}</span>
          <button
            onClick={() => setSelectedAgent(null)}
            className="text-[10px] text-[#C9C6BC] hover:text-[#FFFFFF] underline cursor-pointer ml-1"
          >
            Clear
          </button>
        </div>
      )}
    </div>
  );
};
