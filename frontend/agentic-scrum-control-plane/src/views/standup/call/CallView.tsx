import { useEffect, useMemo, useRef } from 'react';
import type { StandupParticipant, StandupView } from '../models/standup';
import { CallStage } from './CallStage';
import type { StageActions } from './CallStage';
import { CallTile } from './CallTile';
import { SubtitleBar } from './SubtitleBar';
import { isSpoken, spokenText, stageFor } from './script';
import type { StageKind } from './script';
import { useCallScript } from './useCallScript';
import { useContainerWidth } from './useContainerWidth';
import type { useVoice } from './useVoice';

export type CallLayout = 'grid' | 'focus';

const SETUP = new Set(['meeting_created', 'meeting_started', 'participant_joined', 'participant_left', 'skill_selected', 'role_assigned', 'topic_started', 'topic_completed']);
const SHORT: Record<string, string> = {
  challenge: 'challenged', counterargument: 'replied', proposal: 'proposed', brainstorm: 'brainstormed', statement: 'said', question: 'asked', clarification_requested: 'asked the SME',
  clarification_answered: 'answered', risk_raised: 'raised a risk', decision_proposed: 'proposed a decision', action_item_created: 'took an action', participant_blocked: 'got blocked',
};
const RANK: Record<string, number> = { business_sme: 0, scrum_master: 1 };

/** A steady order, so people do not jump around while they talk: the Business SME, the Scrum Master, then everyone else by name (numbers in order). */
export function tileOrder(people: readonly StandupParticipant[]): StandupParticipant[] {
  return [...people].sort((a, b) => (RANK[a.participant_type] ?? 2) - (RANK[b.participant_type] ?? 2) || a.participant_id.localeCompare(b.participant_id, undefined, { numeric: true }));
}

function lastAction(view: StandupView, id: string): string | undefined {
  const e = [...view.recent].reverse().find((x) => x.actor_id === id && !SETUP.has(x.event_type));
  if (!e) return undefined;
  const text = e.text.replace(/^to [^:]{1,40}:\s*/, '');
  return `${SHORT[e.event_type] ?? e.event_type.replace(/_/g, ' ')}: ${text.length > 34 ? `${text.slice(0, 33)}…` : text}`;
}

export interface CallViewProps {
  view: StandupView;
  playing: boolean;
  speed: number;
  layout: CallLayout;
  pinned: StageKind | null;
  onPin: (kind: StageKind | null) => void;
  actions: StageActions;
  voice: ReturnType<typeof useVoice>;
  /** Changes when another meeting (or record) is opened, so the subtitles start again. */
  resetKey: string;
  selectedId: string | null;
  onSelectPerson: (id: string) => void;
}

/** The meeting as a call: the shared screen on top (with the camera of whoever is speaking in its corner and the line being said underneath), the people below at their desks. */
export function CallView({ view, playing, speed, layout, pinned, onPin, actions, voice, resetKey, selectedId, onSelectPerson }: CallViewProps) {
  const box = useRef<HTMLDivElement>(null);
  const width = useContainerWidth(box);
  const compact = width > 0 && width < 480;
  const spoken = useMemo(() => view.recent.filter(isSpoken), [view.recent]);
  const { active, queued } = useCallScript(spoken, playing, speed, resetKey);
  const people = useMemo(() => tileOrder(view.participants), [view.participants]);
  const speakingId = active?.animating ? active.entry.actor_id : null;
  const spotlightId = speakingId ?? (view.active_speaker && view.participants.find((p) => p.participant_id === view.active_speaker)?.status === 'speaking' ? view.active_speaker : null);
  const scrum = people.find((p) => p.participant_type === 'scrum_master') ?? people[0] ?? null;
  const presenter = (speakingId ? people.find((p) => p.participant_id === speakingId) : null) ?? (spotlightId ? people.find((p) => p.participant_id === spotlightId) : null) ?? scrum;
  const shown = pinned ?? stageFor(view);

  // a line begins to be said: say it out loud, when the voice is on
  const lineKey = active?.animating ? active.entry.sequence : null;
  useEffect(() => {
    if (lineKey !== null && active) voice.speak(spokenText(active.entry), speed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lineKey]);
  useEffect(() => {
    if (!playing) voice.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing]);

  const size = compact ? 'row' : layout === 'focus' ? 'small' : 'normal';
  const grid = compact ? 'flex flex-col gap-1.5' : layout === 'focus' ? 'grid grid-cols-[repeat(auto-fill,minmax(112px,1fr))] gap-2' : 'grid grid-cols-[repeat(auto-fill,minmax(176px,1fr))] gap-3';

  return (
    <div ref={box} data-testid="call-view" data-layout={compact ? 'compact' : layout} className="flex flex-col gap-3 rounded-xl bg-[#12131A] p-3 text-[#E9EAF0]">
      <CallStage
        view={view}
        participants={view.participants}
        shown={shown}
        pinned={pinned}
        onPin={onPin}
        presenter={presenter}
        presenting={speakingId !== null}
        actions={actions}
        large={layout === 'focus'}
        caption={<SubtitleBar active={active} participants={view.participants} queued={queued} />}
      />
      <section aria-label="Participants" data-testid="call-tiles">
        {people.length === 0 ? (
          <p className="rounded-lg border border-dashed border-white/15 p-4 text-[13px] text-[#9AA0B6]">Nobody has joined this meeting yet.</p>
        ) : (
          <ul className={grid} role="list">
            {people.map((p) => (
              <CallTile
                key={p.participant_id}
                person={p}
                spotlight={spotlightId === p.participant_id}
                talking={speakingId === p.participant_id}
                saying={speakingId === p.participant_id && active ? spokenText(active.entry) : undefined}
                lastAction={lastAction(view, p.participant_id)}
                size={size}
                selected={selectedId === p.participant_id}
                onSelect={onSelectPerson}
              />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
