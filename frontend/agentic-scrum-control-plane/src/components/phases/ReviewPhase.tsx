import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { CheckCircle2, FileCode, Check, ShieldCheck, ArrowRight, GitCommit } from 'lucide-react';
import { Agent } from '../../types';

interface ReviewPhaseProps {
  agents: Agent[];
  onApproveAndShip: () => void;
}

export const ReviewPhase: React.FC<ReviewPhaseProps> = ({ agents, onApproveAndShip }) => {
  const [activeTab, setActiveTab] = useState<'diff' | 'contracts' | 'audit'>('diff');
  const [checklist, setChecklist] = useState<{ [key: string]: boolean }>({
    schemas: true,
    tests: true,
    latency: true,
    smeSignoff: false,
  });

  const toggleCheck = (key: string) => {
    setChecklist((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const allPassed = checklist.schemas && checklist.tests && checklist.latency;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
      className="max-w-[1040px] mx-auto py-8 px-6 flex flex-col"
    >
      {/* Header */}
      <div className="flex items-center justify-between pb-4 mb-6 border-b border-[#E7E6DF]">
        <div>
          <h2 className="text-[17px] font-semibold text-[#161616]">
            Phase 05: Verification & Architectural Review
          </h2>
          <p className="text-xs text-[#5B5B5B] mt-0.5">
            Peer review completed by 6 agents · Ready for final SME release sign-off
          </p>
        </div>

        {/* Tab switch */}
        <div className="flex items-center gap-1 p-1 bg-[#F4F3EE] rounded-lg border border-[#E7E6DF]">
          <button
            onClick={() => setActiveTab('diff')}
            className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
              activeTab === 'diff'
                ? 'bg-[#FCFCFB] text-[#161616] shadow-xs'
                : 'text-[#5B5B5B] hover:text-[#161616]'
            }`}
          >
            Unified PR Diff
          </button>
          <button
            onClick={() => setActiveTab('contracts')}
            className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
              activeTab === 'contracts'
                ? 'bg-[#FCFCFB] text-[#161616] shadow-xs'
                : 'text-[#5B5B5B] hover:text-[#161616]'
            }`}
          >
            API Contract
          </button>
          <button
            onClick={() => setActiveTab('audit')}
            className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
              activeTab === 'audit'
                ? 'bg-[#FCFCFB] text-[#161616] shadow-xs'
                : 'text-[#5B5B5B] hover:text-[#161616]'
            }`}
          >
            Test Suite & Audit
          </button>
        </div>
      </div>

      {/* Two-Pane Layout (§3.5) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        {/* Left Pane: Artifact Being Finalized */}
        <div className="lg:col-span-7 bg-[#FCFCFB] border border-[#E7E6DF] rounded-2xl p-6 shadow-xs overflow-hidden">
          <div className="flex items-center justify-between pb-3 mb-4 border-b border-[#E7E6DF] text-xs text-[#5B5B5B]">
            <span className="font-mono font-medium text-[#161616]">
              {activeTab === 'diff'
                ? 'orchestrator/session_bus.ts'
                : activeTab === 'contracts'
                ? 'contracts/sdlc_events.proto'
                : 'ci_test_run_matrix.log'}
            </span>
            <span className="text-[11px] font-mono text-[#8E8E8E]">v3.0.0-rc2</span>
          </div>

          {activeTab === 'diff' && (
            <div className="font-mono text-[12px] leading-relaxed overflow-x-auto bg-[#F4F3EE] p-4 rounded-xl border border-[#E7E6DF]">
              <div className="text-[#5B5B5B]">// Partioned session broadcaster with Redis PubSub</div>
              <div className="text-emerald-700 bg-emerald-50/70 px-1 rounded">
                + export class PartitionedSessionChannel implements ISessionSync &#123;
              </div>
              <div className="text-emerald-700 bg-emerald-50/70 px-1 rounded">
                +   constructor(private redis: RedisCluster, private partitionId: string) &#123;&#125;
              </div>
              <div className="text-emerald-700 bg-emerald-50/70 px-1 rounded">
                +   async broadcastDelta(delta: PhaseMutation): Promise&lt;SyncAck&gt; &#123;
              </div>
              <div className="text-emerald-700 bg-emerald-50/70 px-1 rounded">
                +     return this.redis.publish(`session:${'{'}this.partitionId{'}'}:phase`, delta);
              </div>
              <div className="text-emerald-700 bg-emerald-50/70 px-1 rounded">
                +   &#125;
              </div>
              <div className="text-[#5B5B5B] px-1">&#125;</div>
            </div>
          )}

          {activeTab === 'contracts' && (
            <div className="font-mono text-[12px] leading-relaxed overflow-x-auto bg-[#F4F3EE] p-4 rounded-xl border border-[#E7E6DF]">
              <div className="text-[#8E8E8E]">syntax = "proto3";</div>
              <div className="text-[#161616] mt-2">message PhaseTransitionEvent &#123;</div>
              <div className="text-[#5B5B5B] pl-4">string session_id = 1;</div>
              <div className="text-[#5B5B5B] pl-4">string active_phase = 2;</div>
              <div className="text-[#5B5B5B] pl-4">int64 epoch_timestamp = 3;</div>
              <div className="text-[#5B5B5B] pl-4">repeated AgentSignature agent_approvals = 4;</div>
              <div className="text-[#161616]">&#125;</div>
            </div>
          )}

          {activeTab === 'audit' && (
            <div className="space-y-3 font-mono text-xs">
              <div className="flex items-center justify-between p-2.5 rounded-lg bg-emerald-50/60 border border-emerald-200 text-emerald-800">
                <span>Unit & Integration Suite</span>
                <span className="font-semibold">38 / 38 passed (0 flaky)</span>
              </div>
              <div className="flex items-center justify-between p-2.5 rounded-lg bg-emerald-50/60 border border-emerald-200 text-emerald-800">
                <span>Race condition static analyzer</span>
                <span className="font-semibold">0 violations found</span>
              </div>
              <div className="flex items-center justify-between p-2.5 rounded-lg bg-emerald-50/60 border border-emerald-200 text-emerald-800">
                <span>Latency Benchmark (p99)</span>
                <span className="font-semibold">8.4ms (SLA &lt; 50ms)</span>
              </div>
            </div>
          )}

          <div className="mt-6 pt-4 border-t border-[#E7E6DF] flex items-center justify-between text-xs text-[#5B5B5B]">
            <div className="flex items-center gap-2">
              <GitCommit className="w-3.5 h-3.5 text-[#161616]" />
              <span className="font-mono">Commit 7a92c81 verified</span>
            </div>
            <span className="text-emerald-700 font-medium">Build #482 signed</span>
          </div>
        </div>

        {/* Right Pane: Review Comments & Final SME Sign-off */}
        <div className="lg:col-span-5 flex flex-col gap-6">
          {/* Peer Review Summary Card */}
          <div className="bg-[#FCFCFB] border border-[#E7E6DF] rounded-2xl p-6 shadow-xs">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[#5B5B5B] mb-3 font-mono">
              Agent Sign-offs
            </h3>
            <div className="space-y-2.5 mb-5">
              {agents.slice(0, 4).map((agent) => (
                <div key={agent.id} className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-700" />
                    <span className="font-medium text-[#161616]">{agent.name}</span>
                    <span className="text-[#8E8E8E] font-mono text-[11px]">
                      ({agent.claimedSkill})
                    </span>
                  </div>
                  <span className="text-[11px] text-[#5B5B5B] font-mono">Approved</span>
                </div>
              ))}
            </div>

            <h3 className="text-xs font-semibold uppercase tracking-wider text-[#5B5B5B] mb-2 font-mono">
              Final Release Invariants
            </h3>
            <div className="space-y-2 mb-6">
              <label className="flex items-center gap-2 text-xs text-[#161616] cursor-pointer">
                <input
                  type="checkbox"
                  checked={checklist.schemas}
                  onChange={() => toggleCheck('schemas')}
                  className="rounded border-[#D5D3CA] text-[#161616] focus:ring-0"
                />
                <span>Zero schema breaking changes</span>
              </label>
              <label className="flex items-center gap-2 text-xs text-[#161616] cursor-pointer">
                <input
                  type="checkbox"
                  checked={checklist.tests}
                  onChange={() => toggleCheck('tests')}
                  className="rounded border-[#D5D3CA] text-[#161616] focus:ring-0"
                />
                <span>All 38 hermetic integration tests passing</span>
              </label>
              <label className="flex items-center gap-2 text-xs text-[#161616] cursor-pointer">
                <input
                  type="checkbox"
                  checked={checklist.latency}
                  onChange={() => toggleCheck('latency')}
                  className="rounded border-[#D5D3CA] text-[#161616] focus:ring-0"
                />
                <span>Latency benchmarks validated under 15ms</span>
              </label>
            </div>

            {/* SME Sign-off CTA */}
            <button
              onClick={onApproveAndShip}
              disabled={!allPassed}
              className="w-full py-3 px-4 rounded-xl bg-[#161616] text-[#FCFCFB] text-xs font-medium hover:bg-black disabled:opacity-40 transition-all flex items-center justify-center gap-2 shadow-md active:scale-98 cursor-pointer"
            >
              <ShieldCheck className="w-4 h-4 text-[#E60000]" />
              <span>SME Final Sign-off → Ship to Production</span>
            </button>
          </div>
        </div>
      </div>
    </motion.div>
  );
};
