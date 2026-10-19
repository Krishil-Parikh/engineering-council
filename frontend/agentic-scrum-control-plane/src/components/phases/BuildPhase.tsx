import React, { useState, useMemo, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ReactFlow,
  Background,
  Controls,
  Node,
  Edge,
  NodeProps,
  Handle,
  Position,
  useNodesState,
  useEdgesState,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { ArrowRight, GitPullRequest, CheckCircle, Code, Cpu, ExternalLink, X } from 'lucide-react';
import { Agent } from '../../types';

interface ScrumMasterData {
  label?: string;
}

interface AgentNodeData {
  name: string;
  skill?: string;
  status: string;
  task: string;
  branch: string;
  coverage?: string;
}

interface TaskNodeData {
  label: string;
  prNumber: string;
  status: string;
}

// Custom Scrum Master Node
const ScrumMasterNode: React.FC<NodeProps> = ({ data }) => {
  const d = data as unknown as ScrumMasterData;
  return (
    <div className="px-4 py-3 rounded-xl border-2 border-[#161616] bg-[#FCFCFB] shadow-md min-w-[200px] text-center select-none">
      <div className="flex items-center justify-center gap-1.5 mb-1">
        <span className="w-2 h-2 rounded-full bg-[#E60000] animate-ping" />
        <span className="text-xs font-semibold uppercase tracking-wider text-[#161616]">
          {d.label || 'Scrum Master'}
        </span>
      </div>
      <p className="text-[11px] text-[#5B5B5B] font-mono">
        Orchestration Root · Continuous Sync
      </p>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-[#161616] !w-2.5 !h-2.5 !border-2 !border-[#FCFCFB]"
      />
    </div>
  );
};

// Custom Developer Agent Node
const AgentNode: React.FC<NodeProps> = ({ data, selected }) => {
  const d = data as unknown as AgentNodeData;
  const isReviewing = d.status === 'reviewing';

  return (
    <div
      className={`px-4 py-3 rounded-xl bg-[#FCFCFB] border transition-all duration-200 min-w-[220px] shadow-sm select-none cursor-pointer ${
        selected
          ? 'border-[#E60000] ring-2 ring-[#E60000]/20 shadow-md'
          : 'border-[#E7E6DF] hover:border-[#161616]'
      }`}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-[#161616] !w-2.5 !h-2.5 !border-2 !border-[#FCFCFB]"
      />
      
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1.5">
          <span
            className={`w-2 h-2 rounded-full ${
              isReviewing ? 'bg-[#161616] animate-pulse' : 'bg-[#E60000]'
            }`}
          />
          <span className="text-xs font-semibold text-[#161616]">{d.name}</span>
        </div>
        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[#F4F3EE] text-[#5B5B5B]">
          {d.skill || 'Standby'}
        </span>
      </div>

      <p className="text-[11px] text-[#5B5B5B] line-clamp-2 leading-relaxed mb-2">
        {d.task}
      </p>

      <div className="flex items-center justify-between pt-1.5 border-t border-[#E7E6DF] text-[10px] font-mono text-[#8E8E8E]">
        <span>{d.branch}</span>
        <span className="text-[#161616] font-medium">{d.coverage || '100% tests'}</span>
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-[#161616] !w-2.5 !h-2.5 !border-2 !border-[#FCFCFB]"
      />
    </div>
  );
};

// Custom Task Node
const TaskNode: React.FC<NodeProps> = ({ data }) => {
  const d = data as unknown as TaskNodeData;
  return (
    <div className="px-3 py-2 rounded-lg bg-[#F4F3EE] border border-[#E7E6DF] min-w-[180px] shadow-xs select-none">
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-[#161616] !w-2 !h-2 !border-2 !border-[#FCFCFB]"
      />
      <div className="flex items-center gap-1.5 mb-0.5">
        <GitPullRequest className="w-3 h-3 text-[#E60000]" />
        <span className="text-[11px] font-medium text-[#161616] truncate">
          {d.label}
        </span>
      </div>
      <div className="flex items-center justify-between text-[10px] font-mono text-[#5B5B5B]">
        <span>{d.prNumber}</span>
        <span className="text-emerald-700 font-semibold">{d.status}</span>
      </div>
    </div>
  );
};

interface BuildPhaseProps {
  agents: Agent[];
  onFinishBuild: () => void;
}

export const BuildPhase: React.FC<BuildPhaseProps> = ({ agents, onFinishBuild }) => {
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);

  // Compute status summary
  const buildingCount = agents.filter((a) => a.status === 'active').length;
  const reviewCount = agents.filter((a) => a.status === 'reviewing').length;
  const blockedCount = agents.filter((a) => a.status === 'blocked').length;

  // React Flow initial nodes
  const initialNodes: Node[] = useMemo(
    () => [
      {
        id: 'scrum-master',
        type: 'scrumMaster',
        position: { x: 380, y: 30 },
        data: { label: 'Scrum Master Orchestrator' },
      },
      // Frontend cluster
      {
        id: 'agent-01',
        type: 'agent',
        position: { x: 60, y: 150 },
        data: {
          name: 'Agent-01',
          skill: 'Frontend',
          status: 'active',
          task: 'Spine timeline navigation with SVG stroke animations',
          branch: 'feat/spine-nav',
          coverage: '38/38 tests pass',
        },
      },
      {
        id: 'agent-02',
        type: 'agent',
        position: { x: 310, y: 150 },
        data: {
          name: 'Agent-02',
          skill: 'Frontend',
          status: 'active',
          task: 'Recharts sparkline area gradient & Odometer counter',
          branch: 'feat/pr-sparkline',
          coverage: '24/24 tests pass',
        },
      },
      // Backend cluster
      {
        id: 'agent-03',
        type: 'agent',
        position: { x: 560, y: 150 },
        data: {
          name: 'Agent-03',
          skill: 'Backend',
          status: 'active',
          task: 'Redis pub/sub partitioned session broadcaster',
          branch: 'feat/redis-sync',
          coverage: '52/52 tests pass',
        },
      },
      {
        id: 'agent-04',
        type: 'agent',
        position: { x: 810, y: 150 },
        data: {
          name: 'Agent-04',
          skill: 'Backend',
          status: 'active',
          task: 'Postgres migrations with Timescale telemetry audit',
          branch: 'perf/db-timescale',
          coverage: '41/41 tests pass',
        },
      },
      // Review node
      {
        id: 'agent-05',
        type: 'agent',
        position: { x: 430, y: 340 },
        data: {
          name: 'Agent-05',
          skill: 'Backend',
          status: 'reviewing',
          task: 'GraphQL schema verification and idempotency contracts',
          branch: 'chore/idempotency',
          coverage: '19/19 tests pass',
        },
      },
      // PR Tasks
      {
        id: 'task-pr-104',
        type: 'task',
        position: { x: 60, y: 340 },
        data: { label: 'PR #104: Spine UI', prNumber: '#104', status: 'Ready to Merge' },
      },
      {
        id: 'task-pr-105',
        type: 'task',
        position: { x: 810, y: 340 },
        data: { label: 'PR #105: Redis Channel', prNumber: '#105', status: 'CI Passed' },
      },
    ],
    []
  );

  const initialEdges: Edge[] = useMemo(
    () => [
      {
        id: 'e-sm-a1',
        source: 'scrum-master',
        target: 'agent-01',
        animated: true,
        style: { stroke: '#161616', strokeWidth: 1.5 },
      },
      {
        id: 'e-sm-a2',
        source: 'scrum-master',
        target: 'agent-02',
        animated: true,
        style: { stroke: '#161616', strokeWidth: 1.5 },
      },
      {
        id: 'e-sm-a3',
        source: 'scrum-master',
        target: 'agent-03',
        animated: true,
        style: { stroke: '#161616', strokeWidth: 1.5 },
      },
      {
        id: 'e-sm-a4',
        source: 'scrum-master',
        target: 'agent-04',
        animated: true,
        style: { stroke: '#161616', strokeWidth: 1.5 },
      },
      {
        id: 'e-sm-a5',
        source: 'scrum-master',
        target: 'agent-05',
        style: { stroke: '#8E8E8E', strokeDasharray: '4 4' },
      },
      {
        id: 'e-a1-pr1',
        source: 'agent-01',
        target: 'task-pr-104',
        animated: true,
        style: { stroke: '#E60000', strokeWidth: 1.5 },
      },
      {
        id: 'e-a4-pr2',
        source: 'agent-04',
        target: 'task-pr-105',
        animated: true,
        style: { stroke: '#E60000', strokeWidth: 1.5 },
      },
    ],
    []
  );

  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [edges, , onEdgesChange] = useEdgesState(initialEdges);

  const nodeTypes = useMemo(
    () => ({
      scrumMaster: ScrumMasterNode,
      agent: AgentNode,
      task: TaskNode,
    }),
    []
  );

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      const match = agents.find((a) => a.id === node.id);
      if (match) {
        setSelectedAgent(match);
      }
    },
    [agents]
  );

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.35 }}
      className="w-full h-[calc(100vh-140px)] flex flex-col relative"
    >
      {/* Top Status Line (§3.4: "4 agents building · 2 in review · 0 blocked") */}
      <div className="w-full px-8 py-3.5 border-b border-[#E7E6DF] bg-[#FCFCFB] flex items-center justify-between z-10 select-none">
        <div className="flex items-center gap-3">
          <span className="text-xs font-semibold text-[#161616]">
            {buildingCount} agents building · {reviewCount} in review · {blockedCount} blocked
          </span>
          <span className="text-xs text-[#8E8E8E]">·</span>
          <span className="text-xs text-[#5B5B5B] font-mono">
            38 commits synced to main
          </span>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={onFinishBuild}
            className="flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-[#161616] text-[#FCFCFB] text-xs font-medium hover:bg-black transition-all shadow-xs active:scale-98"
          >
            <span>All PRs Passed CI → Advance to Review</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Full-bleed React Flow Canvas */}
      <div className="flex-1 w-full h-full relative bg-[#FCFCFB]">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          onNodeClick={handleNodeClick}
          fitView
          fitViewOptions={{ padding: 0.25 }}
          minZoom={0.6}
          maxZoom={1.5}
        >
          <Background color="#E7E6DF" gap={20} size={1} />
          <Controls position="bottom-right" showInteractive={false} />
        </ReactFlow>

        {/* Selected Agent Inspector Slide-over */}
        <AnimatePresence>
          {selectedAgent && (
            <motion.div
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 20 }}
              className="absolute top-4 right-4 z-20 w-80 bg-[#FCFCFB] border border-[#E7E6DF] rounded-2xl p-5 shadow-xl"
            >
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[#E60000]" />
                  <span className="text-xs font-semibold text-[#161616]">
                    {selectedAgent.name}
                  </span>
                  <span className="text-[10px] font-mono text-[#5B5B5B] px-1.5 py-0.5 rounded bg-[#F4F3EE]">
                    {selectedAgent.claimedSkill}
                  </span>
                </div>
                <button
                  onClick={() => setSelectedAgent(null)}
                  className="p-1 text-[#8E8E8E] hover:text-[#161616] rounded-md hover:bg-[#F4F3EE]"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>

              <div className="space-y-3 text-xs">
                <div>
                  <span className="text-[10px] uppercase font-mono text-[#8E8E8E] block mb-1">
                    Active Assignment
                  </span>
                  <p className="text-[#161616] leading-relaxed">
                    {selectedAgent.currentTask}
                  </p>
                </div>

                <div className="pt-2 border-t border-[#E7E6DF] flex items-center justify-between font-mono text-[11px]">
                  <span className="text-[#5B5B5B]">Branch:</span>
                  <span className="text-[#161616] font-medium">{selectedAgent.activeBranch}</span>
                </div>

                <div className="flex items-center justify-between font-mono text-[11px]">
                  <span className="text-[#5B5B5B]">Context window:</span>
                  <span className="text-[#161616]">{selectedAgent.contextUsagePercent}% utilized</span>
                </div>

                <div className="pt-2 border-t border-[#E7E6DF] flex items-center gap-2 text-emerald-700">
                  <CheckCircle className="w-3.5 h-3.5" />
                  <span className="font-mono text-[11px]">Static types & unit tests passing</span>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Skill-lane summary beneath the graph (§3.4) */}
      <div className="px-8 py-3 border-t border-[#E7E6DF] bg-[#FCFCFB] flex items-center justify-center gap-8 text-xs text-[#5B5B5B] select-none font-mono">
        <div className="flex items-center gap-3">
          <span>Frontend</span>
          <div className="flex items-center gap-1">
            <span className="w-6 h-[1px] bg-[#161616]" />
            <span className="w-2 h-2 rounded-full bg-[#161616]" />
            <span className="w-2 h-2 rounded-full bg-[#161616]" />
            <span className="w-6 h-[1px] bg-[#161616]" />
          </div>
          <span className="text-[#161616] font-semibold">2 active</span>
        </div>

        <span className="text-[#D5D3CA]">·</span>

        <div className="flex items-center gap-3">
          <span>Backend</span>
          <div className="flex items-center gap-1">
            <span className="w-6 h-[1px] bg-[#161616]" />
            <span className="w-2 h-2 rounded-full bg-[#161616]" />
            <span className="w-2 h-2 rounded-full bg-[#161616]" />
            <span className="w-2 h-2 rounded-full bg-[#161616]" />
            <span className="w-6 h-[1px] bg-[#161616]" />
          </div>
          <span className="text-[#161616] font-semibold">3 active</span>
        </div>

        <span className="text-[#D5D3CA]">·</span>

        <div className="flex items-center gap-3">
          <span>Standby</span>
          <span className="w-2 h-2 rounded-full bg-[#8E8E8E]" />
          <span className="text-[#8E8E8E]">1 idle</span>
        </div>
      </div>
    </motion.div>
  );
};
