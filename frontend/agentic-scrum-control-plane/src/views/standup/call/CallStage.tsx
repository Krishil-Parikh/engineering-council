import { ChevronLeft, ChevronRight, Pin } from 'lucide-react';
import { ActionItemsPanel } from '../components/ActionItemsPanel';
import { DecisionPanel } from '../components/DecisionPanel';
import { DocumentReviewPanel } from '../components/DocumentReviewPanel';
import { QuestionPanel } from '../components/QuestionPanel';
import { RiskDependencyPanel } from '../components/RiskDependencyPanel';
import type { StandupApproval, StandupParticipant, StandupView } from '../models/standup';
import { meetingTypeLabel } from '../models/meeting-status';
import { CharacterAvatar } from './CharacterAvatar';
import { STAGE_LABEL, isSpoken, stageChoices } from './script';
import type { StageKind } from './script';
import './call.css';

export interface StageActions {
  disabled: boolean;
  autopilot: boolean;
  onAnswer: (questionId: string, answer: string) => Promise<void> | void;
  onDecide: (approval: StandupApproval, approve: boolean, feedback: string) => Promise<void> | void;
}

const SETUP = new Set(['meeting_created', 'meeting_started', 'participant_joined', 'participant_left', 'skill_selected', 'role_assigned']);

/** What the meeting is on right now, when nothing needs a decision: the topic, how far it has got, and the latest few things that happened. */
function NowBoard({ view }: { view: StandupView }) {
  const latest = view.recent.filter((e) => !SETUP.has(e.event_type) && !isSpoken(e)).slice(-4).reverse();
  const stats: [string, number][] = [['Decisions', view.decisions.length], ['Action items', view.action_items.length], ['Risks', view.risks.length], ['People', view.participants.filter((p) => p.status !== 'left').length]];
  return (
    <div data-testid="stage-now" className="flex flex-col gap-3">
      <div>
        <div className="text-[10.5px] uppercase tracking-[0.12em] text-[#8E8E8E]">{meetingTypeLabel(view.meeting_type)}</div>
        <h3 className="text-[18px] font-semibold text-[#161616]">{view.current_topic ?? view.title}</h3>
      </div>
      <div className="flex flex-wrap gap-2">
        {stats.map(([label, n]) => <span key={label} className="rounded-full border border-[#E2E0D9] bg-[#F4F3EE] px-3 py-1 text-[12px] text-[#5B5B5B]"><b className="text-[#161616]">{n}</b> {label}</span>)}
      </div>
      {view.summary && <p className="rounded-lg bg-[#F4F3EE] p-3 text-[13px] text-[#161616]">{view.summary}</p>}
      {latest.length > 0 && (
        <ul className="space-y-1" aria-label="Latest">
          {latest.map((e) => <li key={e.sequence} className="flex gap-2 text-[12.5px] text-[#5B5B5B]"><span className="font-mono text-[11px] text-[#8E8E8E]">{e.elapsed}</span><span>{e.text}</span></li>)}
        </ul>
      )}
    </div>
  );
}

function StageBody({ kind, view, participants, actions }: { kind: StageKind; view: StandupView; participants: StandupParticipant[]; actions: StageActions }) {
  switch (kind) {
    case 'question': return <QuestionPanel questions={view.open_questions} participants={participants} autopilot={actions.autopilot} disabled={actions.disabled} onAnswer={actions.onAnswer} />;
    case 'documents': return <DocumentReviewPanel reviews={view.reviews} approvals={view.approvals_open} disabled={actions.disabled} onDecide={actions.onDecide} />;
    case 'decision': return <DecisionPanel decisions={view.decisions} participants={participants} />;
    case 'actions': return <ActionItemsPanel items={view.action_items} participants={participants} />;
    case 'risks': return <RiskDependencyPanel risks={view.risks} dependencies={view.dependencies} participants={participants} />;
    default: return <NowBoard view={view} />;
  }
}

export interface CallStageProps {
  view: StandupView;
  participants: StandupParticipant[];
  shown: StageKind;
  pinned: StageKind | null;
  onPin: (kind: StageKind | null) => void;
  presenter: StandupParticipant | null;
  presenting: boolean;
  actions: StageActions;
  /** Large: the shared screen takes the room the people gave up. */
  large: boolean;
  caption: React.ReactNode;
}

export function CallStage({ view, participants, shown, pinned, onPin, presenter, presenting, actions, large, caption }: CallStageProps) {
  const choices = stageChoices(view);
  const index = Math.max(0, choices.indexOf(shown));
  const step = (delta: number) => onPin(choices[(index + delta + choices.length) % choices.length]);
  return (
    <section aria-label="Shared screen" data-testid="call-stage" data-shown={shown} className="relative flex flex-col gap-2 rounded-xl bg-[radial-gradient(ellipse_at_50%_0,#1B2033,#0B0D14)] p-3">
      <div className="mx-auto flex w-full max-w-[1060px] items-start gap-3">
      <div className={`relative flex min-w-0 flex-1 flex-col overflow-hidden rounded-[10px] bg-white shadow-[0_18px_50px_rgba(0,0,0,0.6),0_0_0_2px_rgba(240,160,32,0.55)] ${large ? 'min-h-[320px]' : 'min-h-[220px]'}`}>
        <div className="flex items-center gap-1.5 bg-[#1C1F2B] px-2.5 py-1.5 text-[11.5px] text-[#9AA0B4]">
          <i aria-hidden className="inline-block h-2.5 w-2.5 rounded-full bg-[#FF5F57]" /><i aria-hidden className="inline-block h-2.5 w-2.5 rounded-full bg-[#FEBC2E]" /><i aria-hidden className="inline-block h-2.5 w-2.5 rounded-full bg-[#28C840]" />
          <span data-testid="stage-title" className="ml-3 min-w-0 flex-1 truncate">{STAGE_LABEL[shown]}</span>
          {choices.length > 1 && (
            <span className="flex items-center gap-0.5" role="group" aria-label="Choose what is on the shared screen">
              <button type="button" onClick={() => step(-1)} aria-label="Previous on the shared screen" className="rounded p-0.5 hover:bg-white/10"><ChevronLeft size={14} aria-hidden /></button>
              <button type="button" onClick={() => step(1)} aria-label="Next on the shared screen" className="rounded p-0.5 hover:bg-white/10"><ChevronRight size={14} aria-hidden /></button>
              <button type="button" onClick={() => onPin(pinned ? null : shown)} aria-pressed={pinned !== null} aria-label={pinned ? 'Let the meeting choose what is shown' : 'Keep this on the shared screen'} title={pinned ? 'Pinned: click to follow the meeting again' : 'Pin this'} className={`rounded p-0.5 hover:bg-white/10 ${pinned ? 'text-[#FFD24A]' : ''}`}><Pin size={13} aria-hidden /></button>
            </span>
          )}
          {presenting && presenter && <span data-testid="sharing-badge" className="ml-1 shrink-0 rounded-full bg-[rgba(240,160,32,0.94)] px-2.5 py-px text-[11px] font-semibold text-[#201400]">{presenter.display_name} is sharing</span>}
        </div>
        <div className="flex-1 overflow-y-auto p-4" data-testid="stage-body"><StageBody kind={shown} view={view} participants={participants} actions={actions} /></div>
      </div>
      {presenter && (
        <div data-testid="presenter-camera" data-speaking={presenting ? 'true' : 'false'} className="su-tile relative h-[92px] w-[124px] shrink-0 self-end overflow-hidden rounded-[10px] border border-white/20 bg-[#222] shadow-[0_8px_24px_rgba(0,0,0,0.6)] max-md:hidden">
          <CharacterAvatar id={presenter.participant_id} type={presenter.participant_type} className="h-full w-full" />
          <span className="pointer-events-none absolute inset-x-1 bottom-1 truncate rounded-full bg-[#0E0F18]/80 px-1.5 py-px text-[10.5px] text-white">{presenter.display_name}</span>
        </div>
      )}
      </div>
      <div className="mx-auto w-full max-w-[1060px]">{caption}</div>
    </section>
  );
}
