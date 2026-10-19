import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Plus, Trash2, Check, Sparkles, BookOpen, Clock, Sliders } from 'lucide-react';
import { Agent, Skill } from '../../types';
import { Odometer } from '../common/Odometer';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  agents: Agent[];
  skills: Skill[];
  onAddAgent: () => void;
  onRemoveAgent: (id: string) => void;
  onAddSkill: (name: string, instructions: string) => void;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen,
  onClose,
  agents,
  skills,
  onAddAgent,
  onRemoveAgent,
  onAddSkill,
}) => {
  const [activeTab, setActiveTab] = useState<'agents' | 'skills' | 'meets' | 'general'>('agents');
  const [confirmRemoveId, setConfirmRemoveId] = useState<string | null>(null);

  // New Skill inline form state
  const [isAddingSkill, setIsAddingSkill] = useState(false);
  const [newSkillName, setNewSkillName] = useState('');
  const [newSkillInstructions, setNewSkillInstructions] = useState('');

  // Meets config
  const [cutoffMinutes, setCutoffMinutes] = useState(15);
  const [standupTime, setStandupTime] = useState('09:30 UTC');
  const [reviewCadence, setReviewCadence] = useState('Bi-weekly (Fridays 16:00 UTC)');

  // Handle Esc key to close
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (isAddingSkill) {
          setIsAddingSkill(false);
        } else {
          onClose();
        }
      }
    };
    if (isOpen) {
      window.addEventListener('keydown', handleKeyDown);
    }
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, isAddingSkill, onClose]);

  const handleSaveSkill = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newSkillName.trim()) return;
    onAddSkill(newSkillName.trim(), newSkillInstructions.trim() || `# ${newSkillName} Guidelines\n- Generic autonomous guidelines`);
    setNewSkillName('');
    setNewSkillInstructions('');
    setIsAddingSkill(false);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6 sm:p-10 select-none">
      {/* Background Ink Scrim + Blur */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
        className="absolute inset-0 bg-[#161616]/15 backdrop-blur-md"
      />

      {/* Settings Modal Surface */}
      <motion.div
        initial={{ opacity: 0, scale: 0.98, y: 8 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.98, y: 8 }}
        transition={{ type: 'spring', stiffness: 420, damping: 36 }}
        className="relative z-10 w-full max-w-[840px] h-[580px] bg-[#FCFCFB] border border-[#E7E6DF] rounded-2xl shadow-2xl flex flex-col overflow-hidden"
      >
        {/* Header */}
        <div className="h-14 border-b border-[#E7E6DF] px-6 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-[#161616]">Settings</span>
            <span className="text-xs text-[#8E8E8E]">/</span>
            <span className="text-xs text-[#5B5B5B] font-mono">System Configuration</span>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-[#8E8E8E] hover:text-[#161616] hover:bg-[#F4F3EE] transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body Split */}
        <div className="flex-1 flex overflow-hidden">
          {/* Left Navigation Tabs */}
          <div className="w-44 border-r border-[#E7E6DF] bg-[#F4F3EE] p-3 space-y-1">
            <button
              onClick={() => setActiveTab('agents')}
              className={`w-full text-left px-3 py-2 rounded-xl text-xs font-medium transition-colors ${
                activeTab === 'agents'
                  ? 'bg-[#FCFCFB] text-[#161616] shadow-xs'
                  : 'text-[#5B5B5B] hover:text-[#161616]'
              }`}
            >
              Developer Agents
            </button>
            <button
              onClick={() => setActiveTab('skills')}
              className={`w-full text-left px-3 py-2 rounded-xl text-xs font-medium transition-colors ${
                activeTab === 'skills'
                  ? 'bg-[#FCFCFB] text-[#161616] shadow-xs'
                  : 'text-[#5B5B5B] hover:text-[#161616]'
              }`}
            >
              Skill Library
            </button>
            <button
              onClick={() => setActiveTab('meets')}
              className={`w-full text-left px-3 py-2 rounded-xl text-xs font-medium transition-colors ${
                activeTab === 'meets'
                  ? 'bg-[#FCFCFB] text-[#161616] shadow-xs'
                  : 'text-[#5B5B5B] hover:text-[#161616]'
              }`}
            >
              Meets & Cadence
            </button>
            <button
              onClick={() => setActiveTab('general')}
              className={`w-full text-left px-3 py-2 rounded-xl text-xs font-medium transition-colors ${
                activeTab === 'general'
                  ? 'bg-[#FCFCFB] text-[#161616] shadow-xs'
                  : 'text-[#5B5B5B] hover:text-[#161616]'
              }`}
            >
              General
            </button>
          </div>

          {/* Right Content Viewport */}
          <div className="flex-1 p-6 overflow-y-auto">
            {/* AGENTS PANE (§6.1) */}
            {activeTab === 'agents' && (
              <div>
                <div className="flex items-center justify-between pb-3 mb-4 border-b border-[#E7E6DF]">
                  <div>
                    <h3 className="text-sm font-semibold text-[#161616]">
                      Developer Agents Bench
                    </h3>
                    <p className="text-xs text-[#5B5B5B] mt-0.5">
                      All agents share a unified generic template
                    </p>
                  </div>
                  <span className="text-xs font-mono font-semibold text-[#161616]">
                    {agents.length} active
                  </span>
                </div>

                {/* Agents List */}
                <div className="space-y-2 mb-6">
                  {agents.map((agent) => {
                    const isConfirming = confirmRemoveId === agent.id;

                    return (
                      <motion.div
                        key={agent.id}
                        layout
                        initial={{ opacity: 0, scale: 0.95 }}
                        animate={{ opacity: 1, scale: 1 }}
                        exit={{ opacity: 0, scale: 0.95 }}
                        transition={{ duration: 0.2 }}
                        className="p-3 rounded-xl border border-[#E7E6DF] bg-[#FCFCFB] hover:border-[#D5D3CA] transition-all flex items-center justify-between group"
                      >
                        <div className="flex items-center gap-3">
                          <span
                            className={`w-2.5 h-2.5 rounded-full ${
                              agent.status === 'active'
                                ? 'bg-[#E60000]'
                                : agent.status === 'reviewing'
                                ? 'bg-[#161616]'
                                : 'bg-[#8E8E8E]'
                            }`}
                          />
                          <span className="text-xs font-semibold text-[#161616]">
                            {agent.name}
                          </span>
                          <span className="text-xs text-[#8E8E8E]">·</span>
                          <span className="text-xs text-[#5B5B5B] font-mono">
                            {agent.claimedSkill || 'Idle (unclaimed)'}
                          </span>
                        </div>

                        {/* Actions / Inline confirm */}
                        <div>
                          {isConfirming ? (
                            <div className="flex items-center gap-2 text-xs">
                              <span className="text-[#E60000] text-[11px] font-medium">
                                Remove {agent.name}?
                              </span>
                              <button
                                onClick={() => {
                                  onRemoveAgent(agent.id);
                                  setConfirmRemoveId(null);
                                }}
                                className="px-2 py-0.5 rounded bg-[#E60000] text-[#FCFCFB] text-[11px] font-medium"
                              >
                                Remove
                              </button>
                              <button
                                onClick={() => setConfirmRemoveId(null)}
                                className="px-2 py-0.5 rounded bg-[#F4F3EE] text-[#5B5B5B] text-[11px]"
                              >
                                Cancel
                              </button>
                            </div>
                          ) : (
                            <button
                              onClick={() => setConfirmRemoveId(agent.id)}
                              className="opacity-0 group-hover:opacity-100 p-1 text-[#8E8E8E] hover:text-[#E60000] transition-all rounded hover:bg-[#F4F3EE]"
                              title="Remove agent from bench"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          )}
                        </div>
                      </motion.div>
                    );
                  })}
                </div>

                {/* + Add Developer Agent button & caption (§6.1) */}
                <button
                  onClick={onAddAgent}
                  className="w-full py-2.5 rounded-xl border border-dashed border-[#161616]/30 hover:border-[#161616] text-xs font-medium text-[#161616] hover:bg-[#F4F3EE] transition-all flex items-center justify-center gap-2 active:scale-98"
                >
                  <Plus className="w-3.5 h-3.5" />
                  <span>+ Add developer agent</span>
                </button>
                <p className="text-[11.5px] text-[#8E8E8E] text-center mt-2.5">
                  Every agent uses the same template — it picks its skill once it joins a meet.
                </p>
              </div>
            )}

            {/* SKILLS PANE (§6.2) */}
            {activeTab === 'skills' && (
              <div>
                <div className="flex items-center justify-between pb-3 mb-4 border-b border-[#E7E6DF]">
                  <div>
                    <h3 className="text-sm font-semibold text-[#161616]">
                      Skill Library
                    </h3>
                    <p className="text-xs text-[#5B5B5B] mt-0.5">
                      Add and edit markdown domain skills for generic agents
                    </p>
                  </div>
                  <span className="text-xs font-mono font-semibold text-[#161616]">
                    {skills.length} skills
                  </span>
                </div>

                {/* Skills List */}
                <div className="space-y-2 mb-6">
                  {skills.map((skill) => (
                    <div
                      key={skill.id}
                      className="p-3 rounded-xl border border-[#E7E6DF] bg-[#FCFCFB] flex items-center justify-between text-xs"
                    >
                      <div className="flex items-center gap-2.5">
                        <span className="w-2 h-2 rounded-xs bg-[#161616]" />
                        <span className="font-semibold text-[#161616]">{skill.name}</span>
                        {skill.isNew && (
                          <span className="px-1.5 py-0.2 rounded text-[9.5px] font-mono uppercase bg-[#161616] text-[#FCFCFB]">
                            new
                          </span>
                        )}
                      </div>

                      <div className="flex items-center gap-2 text-[#5B5B5B] font-mono text-[11px]">
                        <span>claimed by</span>
                        <Odometer value={skill.claimedCount} className="font-semibold text-[#161616]" />
                      </div>
                    </div>
                  ))}
                </div>

                {/* Inline form to Add Skill (§6.2) */}
                <AnimatePresence>
                  {isAddingSkill ? (
                    <motion.form
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: 'auto' }}
                      exit={{ opacity: 0, height: 0 }}
                      onSubmit={handleSaveSkill}
                      className="p-4 rounded-xl border border-[#161616] bg-[#FCFCFB] space-y-3 mb-4"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-[#161616]">
                          Add New Skill Definition
                        </span>
                        <button
                          type="button"
                          onClick={() => setIsAddingSkill(false)}
                          className="text-[#8E8E8E] hover:text-[#161616]"
                        >
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </div>

                      <div>
                        <label className="block text-[11px] font-mono text-[#5B5B5B] mb-1">
                          Skill Name
                        </label>
                        <input
                          type="text"
                          required
                          value={newSkillName}
                          onChange={(e) => setNewSkillName(e.target.value)}
                          placeholder="e.g., Security, QA, Performance"
                          className="w-full px-3 py-1.5 text-xs bg-[#F4F3EE] border border-[#E7E6DF] rounded-lg focus:outline-none focus:border-[#161616]"
                        />
                      </div>

                      <div>
                        <label className="block text-[11px] font-mono text-[#5B5B5B] mb-1">
                          Skill Instructions (Markdown definition)
                        </label>
                        <textarea
                          rows={3}
                          value={newSkillInstructions}
                          onChange={(e) => setNewSkillInstructions(e.target.value)}
                          placeholder="# Skill Guidelines&#10;- Core invariants and protocols"
                          className="w-full px-3 py-1.5 text-xs bg-[#F4F3EE] border border-[#E7E6DF] rounded-lg focus:outline-none focus:border-[#161616] font-mono"
                        />
                      </div>

                      <div className="flex items-center justify-end gap-2 pt-1">
                        <button
                          type="button"
                          onClick={() => setIsAddingSkill(false)}
                          className="px-3 py-1.5 text-xs text-[#5B5B5B] hover:text-[#161616]"
                        >
                          Cancel
                        </button>
                        <button
                          type="submit"
                          className="px-4 py-1.5 rounded-lg bg-[#161616] text-[#FCFCFB] text-xs font-medium hover:bg-black transition-colors"
                        >
                          Save Skill
                        </button>
                      </div>
                    </motion.form>
                  ) : (
                    <button
                      onClick={() => setIsAddingSkill(true)}
                      className="w-full py-2.5 rounded-xl border border-dashed border-[#161616]/30 hover:border-[#161616] text-xs font-medium text-[#161616] hover:bg-[#F4F3EE] transition-all flex items-center justify-center gap-2 active:scale-98"
                    >
                      <Plus className="w-3.5 h-3.5" />
                      <span>+ Add skill</span>
                    </button>
                  )}
                </AnimatePresence>
              </div>
            )}

            {/* MEETS & CADENCE PANE (§6.3) */}
            {activeTab === 'meets' && (
              <div className="space-y-5">
                <div className="pb-3 border-b border-[#E7E6DF]">
                  <h3 className="text-sm font-semibold text-[#161616]">
                    Meeting Cadence & Cutoff Controls
                  </h3>
                  <p className="text-xs text-[#5B5B5B] mt-0.5">
                    Strict bounds prevent unbounded agent reasoning loops
                  </p>
                </div>

                <div>
                  <label className="block text-xs font-medium text-[#161616] mb-1">
                    Hard Meeting Cutoff Timer
                  </label>
                  <p className="text-[11.5px] text-[#5B5B5B] mb-2">
                    Scrum Master agent forcibly synthesizes deliverables when this timer expires.
                  </p>
                  <div className="flex items-center gap-3">
                    {[10, 15, 20].map((mins) => (
                      <button
                        key={mins}
                        onClick={() => setCutoffMinutes(mins)}
                        className={`px-3 py-1.5 rounded-lg text-xs font-mono font-medium transition-all ${
                          cutoffMinutes === mins
                            ? 'bg-[#161616] text-[#FCFCFB]'
                            : 'bg-[#F4F3EE] text-[#5B5B5B] hover:text-[#161616]'
                        }`}
                      >
                        {mins} minutes
                      </button>
                    ))}
                  </div>
                </div>

                <div className="pt-4 border-t border-[#E7E6DF]">
                  <label className="block text-xs font-medium text-[#161616] mb-1">
                    Daily Autonomous Standup
                  </label>
                  <input
                    type="text"
                    value={standupTime}
                    onChange={(e) => setStandupTime(e.target.value)}
                    className="w-full max-w-xs px-3 py-1.5 text-xs bg-[#F4F3EE] border border-[#E7E6DF] rounded-lg font-mono focus:outline-none focus:border-[#161616]"
                  />
                </div>

                <div className="pt-4 border-t border-[#E7E6DF]">
                  <label className="block text-xs font-medium text-[#161616] mb-1">
                    Business SME Review Cadence
                  </label>
                  <input
                    type="text"
                    value={reviewCadence}
                    onChange={(e) => setReviewCadence(e.target.value)}
                    className="w-full max-w-xs px-3 py-1.5 text-xs bg-[#F4F3EE] border border-[#E7E6DF] rounded-lg font-mono focus:outline-none focus:border-[#161616]"
                  />
                </div>
              </div>
            )}

            {/* GENERAL PANE (§6.3) */}
            {activeTab === 'general' && (
              <div className="space-y-4">
                <div className="pb-3 border-b border-[#E7E6DF]">
                  <h3 className="text-sm font-semibold text-[#161616]">
                    General Environment Settings
                  </h3>
                  <p className="text-xs text-[#5B5B5B] mt-0.5">
                    Platform display and telemetry behavior
                  </p>
                </div>

                <div className="space-y-3 text-xs">
                  <div className="flex items-center justify-between p-3 rounded-xl bg-[#F4F3EE] border border-[#E7E6DF]">
                    <div>
                      <span className="font-semibold text-[#161616] block">
                        Generative UI Auto-Advance
                      </span>
                      <span className="text-[#5B5B5B] text-[11.5px]">
                        Advance focus stage immediately when milestone is accepted
                      </span>
                    </div>
                    <span className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 font-mono text-[11px] font-semibold">
                      ENABLED
                    </span>
                  </div>

                  <div className="flex items-center justify-between p-3 rounded-xl bg-[#F4F3EE] border border-[#E7E6DF]">
                    <div>
                      <span className="font-semibold text-[#161616] block">
                        Kowalski-Style Checkmark Animations
                      </span>
                      <span className="text-[#5B5B5B] text-[11.5px]">
                        Draw SVG path instead of instant bounce
                      </span>
                    </div>
                    <span className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 font-mono text-[11px] font-semibold">
                      ACTIVE
                    </span>
                  </div>

                  <div className="flex items-center justify-between p-3 rounded-xl bg-[#F4F3EE] border border-[#E7E6DF]">
                    <div>
                      <span className="font-semibold text-[#161616] block">
                        Reduced Motion Support
                      </span>
                      <span className="text-[#5B5B5B] text-[11.5px]">
                        Respects OS accessibility preferences (80ms crossfades)
                      </span>
                    </div>
                    <span className="font-mono text-[#8E8E8E] text-[11px]">AUTO</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </motion.div>
    </div>
  );
};
