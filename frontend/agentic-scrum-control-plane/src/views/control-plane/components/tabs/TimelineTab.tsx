import React from 'react';
import { useScrum } from '../../context/ScrumContext';
import { Activity, CheckCircle2, Clock, AlertTriangle, ShieldCheck, Calendar, ChevronRight } from 'lucide-react';
import { Sprint } from '../../types';

export const TimelineTab: React.FC = () => {
  const { sprints, selectedSprint, setSelectedSprintId, setSelectedMeetId, setActiveTab } = useScrum();

  return (
    <div className="flex-1 flex flex-col h-full bg-[#FCFCFB] p-6 overflow-y-auto gap-6 select-none">
      {/* Top Section: Horizontal Sprint Swimlane */}
      <div className="bg-[#FFFFFF] p-5 rounded-[16px] border border-[#E2E0D9] shadow-xs flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-[#161616]" />
            <h2 className="text-[14px] font-bold uppercase tracking-wider text-[#161616]">
              SPRINT CADENCE & MILESTONE SWIMLANES
            </h2>
          </div>

          <div className="flex items-center gap-4 text-[11px] text-[#5B5B5B]">
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-[#0F8A4B]" /> Consensus Meet
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-[#B27000]" /> Pivot / Debate Meet
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rotate-45 bg-[#0057B8]" /> SME Regulatory Gate
            </span>
          </div>
        </div>

        {/* Swimlane Rows */}
        <div className="flex flex-col gap-3">
          {sprints.map(sprint => {
            const isSelected = selectedSprint.id === sprint.id;
            const isCurrent = sprint.status === 'active';

            return (
              <div
                key={sprint.id}
                onClick={() => setSelectedSprintId(sprint.id)}
                className={`p-4 rounded-[12px] border transition-all cursor-pointer ${
                  isSelected
                    ? 'bg-[#FCFCFB] border-[#161616] shadow-sm'
                    : 'bg-[#FFFFFF] hover:bg-[#F4F3EE]/50 border-[#E2E0D9]'
                }`}
              >
                {/* Sprint Row Header */}
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2.5">
                    <span className="text-[12px] font-bold text-[#161616]">
                      {sprint.number}: {sprint.title}
                    </span>
                    {isCurrent && (
                      <span className="text-[9.5px] font-bold tracking-wider uppercase px-2 py-0.5 rounded-[4px] bg-[#FDECEC] text-[#E60000] border border-[#F9CFCF]">
                        ACTIVE SPRINT
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-3 text-[11px] mono text-[#5B5B5B]">
                    <span>{sprint.startDate} → {sprint.targetDate}</span>
                    <span className="font-semibold text-[#161616]">{sprint.progress}%</span>
                  </div>
                </div>

                {/* Progress track with embedded Meet & SME nodes */}
                <div className="relative h-12 bg-[#F4F3EE] rounded-[8px] border border-[#E2E0D9] flex items-center px-6">
                  {/* Progress Fill Line */}
                  <div
                    className="absolute left-0 top-0 bottom-0 bg-[#EDECE7] rounded-l-[8px]"
                    style={{ width: `${sprint.progress}%` }}
                  />

                  {/* Connected line */}
                  <div className="w-full h-0.5 bg-[#C9C6BC] relative z-0" />

                  {/* Meets nodes along the line */}
                  <div className="absolute inset-x-8 flex items-center justify-between z-10">
                    {sprint.meets.map(meet => {
                      const isConsensus = meet.outcome === 'consensus';

                      return (
                        <button
                          key={meet.id}
                          onClick={e => {
                            e.stopPropagation();
                            setSelectedMeetId(meet.id);
                            setActiveTab('meet');
                          }}
                          className="group relative flex flex-col items-center cursor-pointer"
                        >
                          <div
                            className={`w-4 h-4 rounded-full border-2 border-[#FFFFFF] shadow-sm flex items-center justify-center transition-transform group-hover:scale-125 ${
                              isConsensus ? 'bg-[#0F8A4B]' : 'bg-[#B27000]'
                            }`}
                          />
                          <span className="text-[9.5px] font-semibold text-[#161616] mt-1 group-hover:underline">
                            {meet.label}
                          </span>
                        </button>
                      );
                    })}

                    {/* SME Gates (Diamond marker) */}
                    {sprint.smeReviewPoints.map((gate, gIdx) => (
                      <div key={gIdx} className="flex flex-col items-center group relative">
                        <div
                          className={`w-3.5 h-3.5 rotate-45 border-2 border-[#FFFFFF] shadow-sm ${
                            gate.approved ? 'bg-[#0057B8]' : 'bg-[#5B5B5B]'
                          }`}
                        />
                        <span className="text-[9px] mono font-medium text-[#0057B8] mt-1.5 whitespace-nowrap">
                          {gate.label}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Bottom Section: Scrum Master Standup Log (Yesterday / Today / Blockers) */}
      <div className="bg-[#FFFFFF] p-6 rounded-[16px] border border-[#E2E0D9] shadow-xs flex flex-col gap-4">
        <div className="flex items-center justify-between border-b border-[#E2E0D9] pb-3">
          <div>
            <h3 className="text-[14px] font-bold text-[#161616] uppercase tracking-wider">
              DAILY AGENT STANDUP LOG — {selectedSprint.number}
            </h3>
            <p className="text-[12px] text-[#5B5B5B]">
              Authored autonomously by ScrumMaster Agent · Synthesized from sub-agent telemetry
            </p>
          </div>
          <span className="text-[11px] mono text-[#5B5B5B] bg-[#F4F3EE] px-2 py-1 rounded-[4px] border border-[#E2E0D9]">
            Synced 14:00 Zurich Time
          </span>
        </div>

        {/* 3-Column Standup Layout */}
        <div className="grid grid-cols-3 gap-5">
          {/* Yesterday Column */}
          <div className="flex flex-col gap-2">
            <div className="text-[11.5px] font-bold uppercase tracking-wider text-[#5B5B5B] flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-[#0F8A4B]" />
              <span>Yesterday Completed</span>
            </div>
            <div className="p-3.5 bg-[#F4F3EE] rounded-[10px] border border-[#E2E0D9] flex flex-col gap-2 min-h-[140px]">
              {selectedSprint.standup.yesterday.map((item, idx) => (
                <div key={idx} className="text-[12px] text-[#161616] leading-relaxed flex items-start gap-1.5">
                  <span className="text-[#0F8A4B] font-bold">›</span>
                  <span>{item}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Today In Flight Column */}
          <div className="flex flex-col gap-2">
            <div className="text-[11.5px] font-bold uppercase tracking-wider text-[#161616] flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5 text-[#161616]" />
              <span>Today In Flight</span>
            </div>
            <div className="p-3.5 bg-[#FCFCFB] rounded-[10px] border border-[#C9C6BC] flex flex-col gap-2 min-h-[140px]">
              {selectedSprint.standup.today.map((item, idx) => (
                <div key={idx} className="text-[12px] text-[#161616] leading-relaxed flex items-start gap-1.5">
                  <span className="text-[#161616] font-bold">›</span>
                  <span>{item}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Blockers & Invariants Column */}
          <div className="flex flex-col gap-2">
            <div className="text-[11.5px] font-bold uppercase tracking-wider text-[#B27000] flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5 text-[#B27000]" />
              <span>Blockers & Gate Invariants</span>
            </div>
            <div className="p-3.5 bg-[#FBF1DC]/40 rounded-[10px] border border-[#B27000]/30 flex flex-col gap-2 min-h-[140px]">
              {selectedSprint.standup.blockers.length === 0 ? (
                <div className="text-[12px] text-[#0F8A4B] font-semibold flex items-center gap-1 mt-2">
                  <CheckCircle2 className="w-4 h-4" /> No active blockers
                </div>
              ) : (
                selectedSprint.standup.blockers.map((item, idx) => (
                  <div key={idx} className="text-[12px] text-[#161616] leading-relaxed flex items-start gap-1.5">
                    <span className="text-[#B27000] font-bold">!</span>
                    <span>{item}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
