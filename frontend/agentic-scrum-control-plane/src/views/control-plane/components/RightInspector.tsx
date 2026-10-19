import React, { useState } from 'react';
import { useScrum } from '../context/ScrumContext';
import { 
  X, 
  Terminal, 
  CheckCircle2, 
  Clock, 
  AlertTriangle, 
  ShieldCheck, 
  Send, 
  Flame, 
  Cpu, 
  Layers, 
  FileCheck2,
  Share2
} from 'lucide-react';
import { Odometer } from './common/Odometer';

export const RightInspector: React.FC = () => {
  const {
    activeTab,
    selectedAgent,
    selectedMeet,
    selectedArtifact,
    selectedSprint,
    reassignTask,
    forceConsensus,
    messages
  } = useScrum();

  const [customTask, setCustomTask] = useState('');
  const [showTaskInput, setShowTaskInput] = useState(false);

  const handleTaskSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (customTask.trim() && selectedAgent) {
      reassignTask(selectedAgent.id, customTask.trim());
      setCustomTask('');
      setShowTaskInput(false);
    }
  };

  return (
    <aside className="w-[320px] bg-[#FCFCFB]/90 backdrop-blur-xl border-l border-[#E2E0D9] flex flex-col shrink-0 select-none overflow-y-auto z-10 shadow-[0_8px_24px_rgba(22,22,22,0.04)]">
      {/* Header */}
      <div className="h-[48px] px-4 border-b border-[#E2E0D9] flex items-center justify-between bg-[#FFFFFF]/60">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-[#161616]" />
          <span className="text-[11.5px] font-bold tracking-wider uppercase text-[#161616]">
            {activeTab === 'overview' || activeTab === 'canvas' ? 'AGENT INSPECTOR' :
             activeTab === 'meet' ? 'MEET CONVERGENCE' :
             activeTab === 'artifacts' ? 'ARTIFACT AUDIT' : 'SPRINT RETRO'}
          </span>
        </div>
        <span className="text-[10px] mono text-[#5B5B5B] uppercase bg-[#F4F3EE] px-1.5 py-0.5 rounded-[3px] border border-[#E2E0D9]">
          Context
        </span>
      </div>

      <div className="p-4 flex-1 flex flex-col gap-4">
        {/* VIEW 1: Overview & Canvas -> Selected Agent Detail */}
        {(activeTab === 'overview' || activeTab === 'canvas') && selectedAgent && (
          <div className="flex flex-col gap-4">
            {/* Agent Header Card */}
            <div className="p-3.5 bg-[#FFFFFF] rounded-[10px] border border-[#E2E0D9] shadow-xs">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-[15px] text-[#161616]">
                      {selectedAgent.name}
                    </span>
                    {selectedAgent.isLive && (
                      <span className="text-[9px] font-bold text-[#E60000] bg-[#FDECEC] px-1.5 py-0.2 rounded-[2px] border border-[#F9CFCF]">
                        LIVE
                      </span>
                    )}
                  </div>
                  <div className="text-[11.5px] text-[#5B5B5B] font-medium mt-0.5">
                    {selectedAgent.roleTitle}
                  </div>
                </div>

                <div className="text-right">
                  <div className="text-[10px] text-[#5B5B5B] uppercase font-medium">Confidence</div>
                  <div className="text-[14px] font-bold mono text-[#0F8A4B]">
                    {selectedAgent.confidenceScore}%
                  </div>
                </div>
              </div>

              {/* Status Pill */}
              <div className="mt-3 flex items-center gap-2 text-[11px] text-[#161616] bg-[#F4F3EE] p-2 rounded-[6px] border border-[#EDECE7]">
                <Cpu className="w-3.5 h-3.5 text-[#5B5B5B] shrink-0" />
                <span className="truncate mono text-[10.5px] text-[#5B5B5B]">{selectedAgent.model}</span>
              </div>
            </div>

            {/* Active Sprint Task */}
            <div className="flex flex-col gap-1.5">
              <div className="text-[11px] font-bold tracking-wider uppercase text-[#5B5B5B] flex items-center justify-between">
                <span>Active Task</span>
                <button
                  onClick={() => setShowTaskInput(!showTaskInput)}
                  className="text-[10px] text-[#0057B8] hover:underline font-semibold cursor-pointer"
                >
                  {showTaskInput ? 'Cancel' : 'Reassign'}
                </button>
              </div>

              {showTaskInput ? (
                <form onSubmit={handleTaskSubmit} className="flex flex-col gap-2">
                  <textarea
                    value={customTask}
                    onChange={e => setCustomTask(e.target.value)}
                    placeholder="Enter new objective..."
                    rows={2}
                    className="w-full text-[11.5px] p-2 bg-[#FFFFFF] border border-[#C9C6BC] rounded-[6px] outline-none focus:border-[#E60000] text-[#161616]"
                  />
                  <button
                    type="submit"
                    className="self-end px-3 py-1 bg-[#161616] text-[#FFFFFF] text-[11px] font-semibold rounded-[4px] cursor-pointer"
                  >
                    Assign Objective
                  </button>
                </form>
              ) : (
                <div className="p-3 bg-[#FFFFFF] rounded-[8px] border border-[#E2E0D9] text-[12px] leading-relaxed text-[#161616]">
                  {selectedAgent.activeTask}
                </div>
              )}
            </div>

            {/* Execution Telemetry Grid */}
            <div className="grid grid-cols-2 gap-2">
              <div className="p-2.5 bg-[#FFFFFF] rounded-[8px] border border-[#E2E0D9]">
                <div className="text-[10px] uppercase font-semibold text-[#5B5B5B]">Context Tokens</div>
                <div className="text-[13px] font-bold mono text-[#161616] mt-0.5">
                  <Odometer value={selectedAgent.contextTokens.toLocaleString()} />
                </div>
              </div>
              <div className="p-2.5 bg-[#FFFFFF] rounded-[8px] border border-[#E2E0D9]">
                <div className="text-[10px] uppercase font-semibold text-[#5B5B5B]">Token Velocity</div>
                <div className="text-[13px] font-bold mono text-[#161616] mt-0.5">
                  <Odometer value={selectedAgent.tokensVelocity} /> <span className="text-[10px] font-normal text-[#5B5B5B]">tok/s</span>
                </div>
              </div>
            </div>

            {/* Skills & Tools */}
            <div className="flex flex-col gap-1.5">
              <div className="text-[11px] font-bold tracking-wider uppercase text-[#5B5B5B]">
                Allocated Capabilities
              </div>
              <div className="flex flex-wrap gap-1.5">
                {selectedAgent.skills.map((skill, idx) => (
                  <span
                    key={idx}
                    className="px-2 py-0.5 text-[10.5px] font-medium bg-[#FFFFFF] text-[#161616] border border-[#E2E0D9] rounded-[4px]"
                  >
                    {skill}
                  </span>
                ))}
              </div>
            </div>

            {/* Recent Tool Invocations */}
            <div className="flex flex-col gap-1.5">
              <div className="text-[11px] font-bold tracking-wider uppercase text-[#5B5B5B]">
                Recent Tool Calls
              </div>
              <div className="flex flex-col gap-1 bg-[#161616] p-2.5 rounded-[8px] text-[10.5px] mono text-[#F4F3EE]">
                {selectedAgent.recentTools.map((tool, idx) => (
                  <div key={idx} className="flex items-center gap-1.5 truncate">
                    <span className="text-[#0F8A4B]">›</span>
                    <span className="truncate">{tool}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Quick Actions */}
            <div className="mt-2 flex flex-col gap-2">
              <button
                onClick={forceConsensus}
                className="w-full py-2 bg-[#161616] hover:bg-[#2B2B2B] text-[#FFFFFF] text-[11.5px] font-semibold rounded-[8px] transition-all cursor-pointer flex items-center justify-center gap-2 active:scale-[0.98]"
              >
                <CheckCircle2 className="w-3.5 h-3.5 text-[#0F8A4B]" />
                <span>Force Quorum Consensus</span>
              </button>
            </div>
          </div>
        )}

        {/* VIEW 2: Meet -> Debate Heat-Strip & Sentiment */}
        {activeTab === 'meet' && (
          <div className="flex flex-col gap-4">
            {/* Consensus Progress Box */}
            <div className="p-3.5 bg-[#FFFFFF] rounded-[10px] border border-[#E2E0D9]">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-bold uppercase text-[#5B5B5B]">Consensus Rate</span>
                <span className="text-[14px] font-bold mono text-[#0F8A4B]">
                  {selectedMeet.consensusRate}%
                </span>
              </div>
              <div className="h-2 w-full bg-[#F4F3EE] rounded-full overflow-hidden border border-[#E2E0D9]">
                <div
                  className="h-full bg-[#0F8A4B] transition-all duration-500 rounded-full"
                  style={{ width: `${selectedMeet.consensusRate}%` }}
                />
              </div>
            </div>

            {/* Debate Intensity Heat-Strip */}
            <div className="p-3.5 bg-[#FFFFFF] rounded-[10px] border border-[#E2E0D9]">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-bold uppercase text-[#5B5B5B] flex items-center gap-1">
                  <Flame className="w-3.5 h-3.5 text-[#E60000]" />
                  <span>Debate Heat Map</span>
                </span>
                <span className="text-[11px] mono text-[#E60000] font-semibold">
                  {selectedMeet.debateIntensity}%
                </span>
              </div>

              {/* Heat segments */}
              <div className="flex items-center gap-1 h-8 bg-[#F4F3EE] p-1 rounded-[6px] border border-[#E2E0D9]">
                {selectedMeet.heatSegments.map((seg, idx) => (
                  <div
                    key={idx}
                    title={`Minute ${seg.minute}: ${seg.intensity}% intensity ${seg.isDebate ? '(Debate)' : ''}`}
                    className={`flex-1 h-full rounded-[2px] transition-all cursor-pointer ${
                      seg.intensity > 75
                        ? 'bg-[#E60000]'
                        : seg.intensity > 40
                        ? 'bg-[#B27000]'
                        : 'bg-[#C9C6BC]'
                    }`}
                  />
                ))}
              </div>
              <div className="flex justify-between text-[9px] mono text-[#5B5B5B] mt-1">
                <span>00:00</span>
                <span>08:00 (Peak Debate)</span>
                <span>15:00</span>
              </div>
            </div>

            {/* Active Participants in this Meet */}
            <div className="flex flex-col gap-1.5">
              <div className="text-[11px] font-bold tracking-wider uppercase text-[#5B5B5B]">
                Active In Room ({selectedMeet.participants.length})
              </div>
              <div className="flex flex-col gap-1.5">
                {selectedMeet.participants.map((name, idx) => (
                  <div
                    key={idx}
                    className="p-2 bg-[#FFFFFF] rounded-[6px] border border-[#E2E0D9] flex items-center justify-between text-[11.5px]"
                  >
                    <span className="font-semibold text-[#161616]">{name}</span>
                    <span className="text-[10px] text-[#0F8A4B] font-mono font-medium">Synced</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Meet Summary */}
            <div className="p-3 bg-[#F4F3EE] rounded-[8px] border border-[#E2E0D9] text-[11.5px] leading-relaxed text-[#5B5B5B]">
              <span className="font-bold text-[#161616] block mb-1">Executive Summary</span>
              {selectedMeet.summary}
            </div>
          </div>
        )}

        {/* VIEW 3: Artifacts -> Signoff Matrix & Audit */}
        {activeTab === 'artifacts' && (
          <div className="flex flex-col gap-4">
            {/* Status Card */}
            <div className="p-3.5 bg-[#FFFFFF] rounded-[10px] border border-[#E2E0D9]">
              <div className="text-[10px] font-bold uppercase text-[#5B5B5B]">Signoff Progress</div>
              <div className="flex items-baseline gap-2 mt-1">
                <span className="text-[28px] font-bold mono text-[#161616]">
                  {selectedArtifact.acceptedCount}/{selectedArtifact.totalRequired}
                </span>
                <span className="text-[12px] font-semibold text-[#0F8A4B]">
                  {selectedArtifact.status === 'approved' ? 'Approved & Locked' : 'Pending Verification'}
                </span>
              </div>

              {/* Progress Dots */}
              <div className="flex items-center gap-1.5 mt-3">
                {Array.from({ length: selectedArtifact.totalRequired }).map((_, idx) => (
                  <span
                    key={idx}
                    className={`w-3 h-3 rounded-full border transition-all ${
                      idx < selectedArtifact.acceptedCount
                        ? 'bg-[#0F8A4B] border-[#0F8A4B]'
                        : 'bg-[#F4F3EE] border-[#C9C6BC]'
                    }`}
                  />
                ))}
              </div>
            </div>

            {/* Signoff Roll Call */}
            <div className="flex flex-col gap-1.5">
              <div className="text-[11px] font-bold tracking-wider uppercase text-[#5B5B5B]">
                Agent Signatures
              </div>
              <div className="flex flex-col gap-1.5">
                {['Agent-01', 'Agent-02', 'Agent-03', 'Agent-04', 'Agent-05', 'Agent-06'].map(agentName => {
                  const hasSigned = selectedArtifact.acceptedBy.includes(agentName);
                  return (
                    <div
                      key={agentName}
                      className="p-2 bg-[#FFFFFF] rounded-[6px] border border-[#E2E0D9] flex items-center justify-between text-[11.5px]"
                    >
                      <span className="font-medium text-[#161616]">{agentName}</span>
                      {hasSigned ? (
                        <span className="text-[10px] font-semibold text-[#0F8A4B] flex items-center gap-1">
                          <CheckCircle2 className="w-3 h-3" /> Signed
                        </span>
                      ) : (
                        <span className="text-[10px] font-semibold text-[#B27000] flex items-center gap-1">
                          <Clock className="w-3 h-3" /> In Review
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            {/* FINMA Compliance Check */}
            <div className="p-3 bg-[#E7F5EC] rounded-[8px] border border-[#0F8A4B]/30 flex items-start gap-2.5">
              <ShieldCheck className="w-4 h-4 text-[#0F8A4B] shrink-0 mt-0.5" />
              <div className="text-[11px] text-[#161616]">
                <strong className="block font-semibold">FINMA Art. 14 Verification Passed</strong>
                Cryptographic parent lineage hashes validated across all active transaction nodes.
              </div>
            </div>
          </div>
        )}

        {/* VIEW 4: Timeline -> Selected Sprint Retro Notes */}
        {activeTab === 'timeline' && (
          <div className="flex flex-col gap-4">
            <div className="p-3.5 bg-[#FFFFFF] rounded-[10px] border border-[#E2E0D9]">
              <div className="text-[11px] font-bold uppercase text-[#5B5B5B]">Selected Sprint</div>
              <div className="text-[16px] font-bold text-[#161616] mt-0.5">
                {selectedSprint.title}
              </div>
              <div className="text-[11px] text-[#5B5B5B] mt-1">
                Goal: {selectedSprint.goal}
              </div>
            </div>

            {/* Retrospective: Went Well */}
            <div className="flex flex-col gap-1.5">
              <div className="text-[11px] font-bold tracking-wider uppercase text-[#0F8A4B]">
                What Went Well
              </div>
              <div className="p-2.5 bg-[#E7F5EC] rounded-[6px] border border-[#0F8A4B]/20 text-[11.5px] leading-relaxed text-[#161616]">
                {selectedSprint.retro.wentWell.map((item, idx) => (
                  <div key={idx} className="mb-1 flex items-start gap-1.5">
                    <span className="text-[#0F8A4B] font-bold">✓</span>
                    <span>{item}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Retrospective: To Improve */}
            <div className="flex flex-col gap-1.5">
              <div className="text-[11px] font-bold tracking-wider uppercase text-[#B27000]">
                Areas to Sharpen
              </div>
              <div className="p-2.5 bg-[#FBF1DC] rounded-[6px] border border-[#B27000]/20 text-[11.5px] leading-relaxed text-[#161616]">
                {selectedSprint.retro.toImprove.map((item, idx) => (
                  <div key={idx} className="mb-1 flex items-start gap-1.5">
                    <span className="text-[#B27000] font-bold">!</span>
                    <span>{item}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Action Items */}
            <div className="flex flex-col gap-1.5">
              <div className="text-[11px] font-bold tracking-wider uppercase text-[#5B5B5B]">
                Enforced Action Items
              </div>
              <div className="p-2.5 bg-[#FFFFFF] rounded-[6px] border border-[#E2E0D9] text-[11.5px] text-[#161616]">
                {selectedSprint.retro.actionItems.map((item, idx) => (
                  <div key={idx} className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#161616]" />
                    <span>{item}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
};
