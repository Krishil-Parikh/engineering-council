import { useCallback, useEffect, useMemo, useState } from 'react';
import { HelpCircle, Mic, MicOff, FileText } from 'lucide-react';
import { useWorkspace } from '../../../state/WorkspaceProvider';
import { CallView } from '../call/CallView';
import type { CallLayout } from '../call/CallView';
import { HighlightsBar } from '../call/HighlightsBar';
import { MeetingsBoard } from '../call/MeetingsBoard';
import { NeedsYouLine } from '../call/NeedsYouLine';
import type { WaitingItem } from '../call/NeedsYouLine';
import { RecapDialog } from '../call/RecapDialog';
import { ShortcutsHelp } from '../call/ShortcutsHelp';
import { TreeView } from '../call/TreeView';
import { computeHighlights, waitedSeconds } from '../call/script';
import type { StageKind } from '../call/script';
import { useVoice } from '../call/useVoice';
import { useMeetingReplay } from '../hooks/useMeetingReplay';
import { useMeetingTimer } from '../hooks/useMeetingTimer';
import { useStandupMeeting } from '../hooks/useStandupMeeting';
import { useStandupMeetings } from '../hooks/useStandupMeetings';
import { isOver } from '../models/meeting-status';
import type { StandupApproval, StandupMeetingRow, StandupView as View } from '../models/standup';
import { ActionItemsPanel } from './ActionItemsPanel';
import { DecisionPanel } from './DecisionPanel';
import { DocumentReviewPanel } from './DocumentReviewPanel';
import { InterventionBar } from './InterventionBar';
import { MeetingControls } from './MeetingControls';
import { MeetingHeader } from './MeetingHeader';
import { MeetingPicker } from './MeetingPicker';
import { MeetingTimeline } from './MeetingTimeline';
import { ParticipantGrid } from './ParticipantGrid';
import { QuestionPanel } from './QuestionPanel';
import { ReplayControls } from './ReplayControls';
import { RiskDependencyPanel } from './RiskDependencyPanel';

export type StandupLayout = 'call' | 'panels' | 'tree' | 'board';

const LAYOUTS: { id: StandupLayout; label: string; key: string }[] = [
  { id: 'call', label: 'Call', key: '' }, { id: 'panels', label: 'Panels', key: '' }, { id: 'tree', label: 'Tree', key: 'T' }, { id: 'board', label: 'Meetings', key: 'B' },
];

/** Which meeting to open first: one that is waiting for the Business SME, else one still running, else the latest. */
export function chooseMeeting(rows: StandupMeetingRow[]): string | null {
  if (rows.length === 0) return null;
  return (rows.find((r) => r.open_questions > 0 && !isOver(r.status)) ?? [...rows].reverse().find((r) => !isOver(r.status)) ?? rows[rows.length - 1]).meeting_id;
}

function Notice({ kind, children, action }: { kind: 'error' | 'info'; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div role={kind === 'error' ? 'alert' : 'status'} className={`flex items-center justify-between gap-3 rounded-lg border px-4 py-2 text-[13px] ${kind === 'error' ? 'border-[#E60000]/30 bg-[#E60000]/5 text-[#8F0000]' : 'border-[#E2E0D9] bg-[#F4F3EE] text-[#5B5B5B]'}`}>
      <span>{children}</span>
      {action}
    </div>
  );
}

function typing(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || !el.tagName) return false;
  return ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) || el.isContentEditable;
}

export function StandupView({ initialMeetingId, onMeetingChange, initialLayout = 'call' }: { initialMeetingId?: string | null; onMeetingChange?: (id: string | null) => void; initialLayout?: StandupLayout }) {
  const { repository, snapshot, executeCommand } = useWorkspace();
  const api = repository.standup;
  const workspaceId = snapshot.workspaceId;
  const [record, setRecord] = useState<string | undefined>();
  const { listing, loading: listLoading, error: listError, refresh } = useStandupMeetings(api, workspaceId, record);
  const [selectedId, setSelectedId] = useState<string | null>(initialMeetingId ?? null);
  const [mode, setMode] = useState<'live' | 'replay'>('live');
  const [layout, setLayout] = useState<StandupLayout>(initialLayout);
  const [callLayout, setCallLayout] = useState<CallLayout>('grid');
  const [pinned, setPinned] = useState<StageKind | null>(null);
  const [linesPlaying, setLinesPlaying] = useState(true);
  const [transcript, setTranscript] = useState<string | null>(null);
  const [recap, setRecap] = useState(false);
  const [transcriptOpen, setTranscriptOpen] = useState(true);
  const [help, setHelp] = useState(false);
  const [person, setPerson] = useState<string | null>(null);
  const [waitingAt, setWaitingAt] = useState(0);
  const voice = useVoice();
  const meeting = useStandupMeeting(api, workspaceId, selectedId, record);
  const replay = useMeetingReplay(api, workspaceId, selectedId, meeting.events, mode === 'replay', record);

  useEffect(() => {
    if (listLoading) return; // the list is not here yet: a meeting asked for in the address must not be replaced by the default one
    if (selectedId && listing.meetings.some((r) => r.meeting_id === selectedId)) return;
    const chosen = chooseMeeting(listing.meetings);
    if (chosen !== selectedId) setSelectedId(chosen);
  }, [listing.meetings, selectedId, listLoading]);

  useEffect(() => {
    onMeetingChange?.(selectedId);
    setMode('live');
    setTranscript(null);
    setPinned(null);
    setPerson(null);
  }, [selectedId, record, onMeetingChange]);

  const live = meeting.view;
  const shown: View | null = mode === 'replay' ? replay.view ?? live : live;
  const ticking = useMeetingTimer(mode === 'replay' ? null : live, meeting.receivedAt);
  const timer = mode === 'replay' && shown
    ? { elapsed: shown.elapsed_seconds, remaining: shown.remaining_seconds, overtime: false }
    : { elapsed: ticking.elapsed, remaining: ticking.remaining, overtime: ticking.overtime };
  const over = live ? isOver(live.status) : false;
  const readOnly = mode === 'replay' || over || Boolean(record);
  const autopilot = (live?.control_mode ?? (listing.autopilot ? 'autopilot' : 'human')) === 'autopilot';
  const participants = useMemo(() => shown?.participants ?? [], [shown]);
  const highlights = useMemo(() => computeHighlights(meeting.events), [meeting.events]);

  // what waits for the Business SME, in this meeting and in the others
  const waiting: WaitingItem[] = useMemo(() => {
    const now = Date.now();
    return listing.meetings.filter((r) => !isOver(r.status) && r.open_questions > 0).map((r) => {
      const here = r.meeting_id === selectedId && live ? live : null;
      const q = here?.open_questions[0];
      return {
        meetingId: r.meeting_id, title: r.title, count: r.open_questions, text: q?.text ?? here?.approvals_open[0]?.subject ?? '',
        waitedSeconds: q ? waitedSeconds(q.asked_at, now) : null,
      };
    });
  }, [listing.meetings, selectedId, live]);

  const open = useCallback((id: string) => {
    setSelectedId(id);
    setRecord(undefined);
    setLayout((l) => (l === 'tree' || l === 'board' ? 'call' : l));
  }, []);

  const goWaiting = useCallback((direction: 1 | -1 = 1) => {
    if (waiting.length === 0) return;
    const index = (waitingAt + direction + waiting.length) % waiting.length;
    setWaitingAt(index);
    open(waiting[index].meetingId);
  }, [waiting, waitingAt, open]);

  const decide = async (approval: StandupApproval, approve: boolean, feedback: string) => {
    try {
      if (approval.extra.kind === 'documents' && approve) {
        await executeCommand({ type: 'prd.accept', workspaceId, artifactId: 'art-prd' });
      } else {
        await executeCommand({ type: 'sme.directive.submit', workspaceId, meetId: selectedId ?? 'standup', directive: approve ? 'Approve' : `Decline: ${feedback}`, questionId: approval.request_id });
      }
      await meeting.refresh();
    } catch {
      /* the shell shows command errors; the panel stays as it was so the person can try again */
    }
  };

  const openTranscript = useCallback(async () => {
    if (!api || !selectedId) return;
    try {
      setTranscript(await api.getTranscript(workspaceId, selectedId, record));
    } catch (caught) {
      setTranscript(`The transcript could not be loaded: ${caught instanceof Error ? caught.message : String(caught)}`);
    }
  }, [api, workspaceId, selectedId, record]);

  // keyboard shortcuts (off while typing in a box)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setHelp(false);
        setRecap(false);
        setTranscript(null);
        return;
      }
      if (typing(e.target) || e.metaKey || e.ctrlKey || e.altKey || help || recap || transcript !== null) return;
      const k = e.key;
      const lower = k.toLowerCase();
      if (k === ' ') {
        e.preventDefault();
        if (mode === 'replay') replay.toggle();
        else setLinesPlaying((p) => !p);
      } else if (k === 'ArrowRight' && mode === 'replay') {
        e.preventDefault();
        replay.step(1);
      } else if (k === 'ArrowLeft' && mode === 'replay') {
        e.preventDefault();
        replay.step(-1);
      } else if (lower === 'n' && mode === 'replay') {
        const target = k === 'N' ? [...highlights].reverse().find((h) => h.sequence < replay.position) : highlights.find((h) => h.sequence > replay.position);
        if (target) replay.seek(target.sequence);
      } else if (lower === 'g' || lower === 'j') goWaiting(1);
      else if (lower === 'k') goWaiting(-1);
      else if (lower === 'm' && voice.supported) voice.setEnabled(!voice.enabled);
      else if (lower === 't') setLayout((l) => (l === 'tree' ? 'call' : 'tree'));
      else if (lower === 'b') setLayout((l) => (l === 'board' ? 'call' : 'board'));
      else if (lower === 'f') setCallLayout((l) => (l === 'focus' ? 'grid' : 'focus'));
      else if (lower === 'r' && shown) setRecap(true);
      else if (lower === 'l') setTranscriptOpen((o) => !o);
      else if (k === '?') setHelp(true);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [mode, replay, highlights, goWaiting, voice, shown, help, recap, transcript, openTranscript]);

  if (!api) {
    return <main className="mx-auto max-w-2xl p-8 pt-20"><Notice kind="info">Meetings need a backend that records them. Start the gateway and open the app in live mode.</Notice></main>;
  }

  const stageActions = { disabled: readOnly, autopilot: (shown?.control_mode ?? 'human') === 'autopilot', onAnswer: (id: string, text: string) => meeting.answer(id, text), onDecide: decide };
  const replayBar = mode === 'replay' && shown ? (
    <div className="border-t border-[#E2E0D9] bg-white">
      <div className="px-4 pt-2"><HighlightsBar highlights={highlights} position={replay.position} onSeek={replay.seek} /></div>
      <ReplayControls replay={replay} elapsedAt={shown.elapsed_seconds} onBackToLive={() => setMode('live')} />
    </div>
  ) : null;

  return (
    <main className="flex min-h-screen flex-col bg-[#F4F3EE] pt-11 text-[#161616]" data-testid="standup-view" data-layout={layout}>
      <NeedsYouLine items={waiting} onGo={open} />
      {listError && <div className="px-4 pt-3"><Notice kind="error" action={<button type="button" onClick={() => void refresh()} className="rounded-md border border-current px-3 py-1 text-[12px] font-semibold">Retry</button>}>The meeting list could not be loaded: {listError}</Notice></div>}
      <div className={`grid flex-1 grid-cols-1 gap-4 p-4 lg:grid-cols-[17rem_minmax(0,1fr)] ${layout === 'panels' ? 'xl:grid-cols-[17rem_minmax(0,1fr)_21rem]' : ''}`}>
        <aside className="flex flex-col gap-5">
          <MeetingPicker
            rows={listing.meetings}
            selectedId={selectedId}
            onSelect={setSelectedId}
            records={listing.records}
            record={record}
            current={listing.record}
            onRecord={(r) => { setRecord(r); setSelectedId(null); }}
          />
          <MeetingControls mode={autopilot ? 'autopilot' : 'human'} disabled={Boolean(record)} onChange={(m) => void meeting.setControl(m).then(refresh)} />
          {shown && layout !== 'call' && <ParticipantGrid participants={participants} />}
        </aside>

        <section className="flex min-w-0 flex-col overflow-hidden rounded-xl border border-[#E2E0D9] bg-white" aria-label="Meeting">
          {listLoading && !shown && <div className="p-6 text-[13px] text-[#8E8E8E]" role="status">Loading meetings…</div>}
          {!listLoading && !selectedId && <div className="p-6 text-[13px] text-[#5B5B5B]" data-testid="no-meeting">No meeting to show yet. Formal meetings (the kickoff, planning, standups, review, retrospective) appear here as the team holds them.</div>}
          {selectedId && meeting.loading && !shown && <div className="p-6 text-[13px] text-[#8E8E8E]" role="status">Loading the meeting…</div>}
          {selectedId && meeting.error && !shown && (
            <div className="p-4"><Notice kind="error" action={<button type="button" onClick={() => void meeting.refresh()} className="rounded-md border border-current px-3 py-1 text-[12px] font-semibold">Retry</button>}>This meeting could not be loaded: {meeting.error}</Notice></div>
          )}
          {shown && live && (
            <>
              <MeetingHeader view={shown} stream={meeting.stream} replaying={mode === 'replay'} timer={timer} />
              {meeting.stream === 'reconnecting' && mode === 'live' && !over && <div className="px-4 pt-3"><Notice kind="error">The connection to the meeting was lost. Reconnecting; nothing said meanwhile will be missed.</Notice></div>}
              <div className="flex flex-wrap items-center gap-2 border-b border-[#E2E0D9] px-4 py-2" role="toolbar" aria-label="View">
                <div role="tablist" aria-label="Standup view" className="flex rounded-lg border border-[#E2E0D9] bg-[#F4F3EE] p-0.5">
                  {LAYOUTS.map((l) => (
                    <button
                      key={l.id}
                      type="button"
                      role="tab"
                      aria-selected={layout === l.id}
                      onClick={() => setLayout(l.id)}
                      title={l.key ? `${l.label} (${l.key})` : l.label}
                      className={`rounded-md px-3 py-1 text-[12px] font-semibold ${layout === l.id ? 'bg-[#161616] text-white' : 'text-[#5B5B5B] hover:text-[#161616]'}`}
                    >
                      {l.label}
                    </button>
                  ))}
                </div>
                {layout === 'call' && (
                  <div role="group" aria-label="Call layout" className="flex rounded-lg border border-[#E2E0D9] bg-[#F4F3EE] p-0.5">
                    {(['grid', 'focus'] as const).map((l) => (
                      <button
                        key={l}
                        type="button"
                        aria-pressed={callLayout === l}
                        onClick={() => setCallLayout(l)}
                        title={l === 'focus' ? 'Focus: a bigger shared screen (F)' : 'Grid: bigger people'}
                        className={`rounded-md px-2.5 py-1 text-[12px] ${callLayout === l ? 'bg-white shadow-sm' : 'text-[#5B5B5B]'}`}
                      >
                        {l === 'focus' ? 'Focus' : 'Grid'}
                      </button>
                    ))}
                  </div>
                )}
                <div className="ml-auto flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => voice.setEnabled(!voice.enabled)}
                    disabled={!voice.supported}
                    aria-pressed={voice.enabled}
                    aria-label={voice.enabled ? 'Voice on: click to turn off' : 'Voice off: click to turn on'}
                    title={voice.supported ? 'Read the lines aloud (M)' : 'This browser cannot speak'}
                    className="flex items-center gap-1 rounded-md border border-[#E2E0D9] px-2 py-1 text-[12px] disabled:opacity-40"
                  >
                    {voice.enabled ? <Mic size={14} aria-hidden /> : <MicOff size={14} aria-hidden />} Voice
                  </button>
                  {layout === 'call' && <button type="button" onClick={() => setTranscriptOpen((o) => !o)} aria-pressed={transcriptOpen} title="Live transcript (L)" className="rounded-md border border-[#E2E0D9] px-2 py-1 text-[12px] aria-pressed:bg-[#161616] aria-pressed:text-white">Live transcript</button>}
                  <button type="button" onClick={() => setRecap(true)} title="Recap (R)" className="flex items-center gap-1 rounded-md border border-[#E2E0D9] px-2 py-1 text-[12px]"><FileText size={14} aria-hidden /> Recap</button>
                  <button type="button" onClick={() => void openTranscript()} title="The whole transcript as text" className="rounded-md border border-[#E2E0D9] px-2 py-1 text-[12px]">Transcript</button>
                  <button type="button" onClick={() => setHelp(true)} aria-label="Keyboard shortcuts" title="Shortcuts (?)" className="rounded-md border border-[#E2E0D9] p-1.5"><HelpCircle size={14} aria-hidden /></button>
                </div>
              </div>
              <div className="flex min-h-0 flex-1 flex-col gap-3 p-4">
                {layout === 'call' && (
                  <CallView
                    view={shown}
                    events={meeting.events.filter((e) => mode !== 'replay' || e.sequence_number <= replay.position)}
                    transcriptOpen={transcriptOpen}
                    replaying={mode === 'replay'}
                    onSeek={replay.seek}
                    playing={mode === 'replay' ? replay.playing : linesPlaying}
                    speed={mode === 'replay' ? replay.speed : 1}
                    layout={callLayout}
                    pinned={pinned}
                    onPin={setPinned}
                    actions={stageActions}
                    voice={voice}
                    resetKey={`${selectedId}|${record ?? ''}|${mode}`}
                    selectedId={person}
                    onSelectPerson={(id) => setPerson((p) => (p === id ? null : id))}
                  />
                )}
                {layout === 'panels' && <MeetingTimeline entries={shown.recent} highlight={mode === 'replay' ? replay.position : undefined} onOpenTranscript={() => void openTranscript()} />}
                {layout === 'tree' && <TreeView participants={participants} />}
                {layout === 'board' && <MeetingsBoard rows={listing.meetings} selectedId={selectedId} onOpen={(id) => { setSelectedId(id); setLayout('call'); }} />}
                {(layout === 'call' || layout === 'panels') && <InterventionBar disabled={readOnly} onSend={(text) => meeting.direct(text)} />}
                {meeting.actionError && <p role="alert" className="text-[12px] text-[#8F0000]">{meeting.actionError}</p>}
              </div>
              {replayBar ?? (
                <div className="flex items-center justify-between border-t border-[#E2E0D9] px-4 py-2">
                  <span className="text-[11px] text-[#8E8E8E]">{live.last_sequence} events recorded</span>
                  <div className="flex items-center gap-2">
                    {mode === 'live' && !over && <button type="button" onClick={() => setLinesPlaying((p) => !p)} aria-pressed={!linesPlaying} className="rounded-md border border-[#E2E0D9] px-2.5 py-1 text-[12px]">{linesPlaying ? 'Pause lines' : 'Resume lines'}</button>}
                    <button type="button" onClick={() => setMode('replay')} className="rounded-md border border-[#161616] px-3 py-1 text-[12px] font-semibold hover:bg-[#161616] hover:text-white">Replay this meeting</button>
                  </div>
                </div>
              )}
            </>
          )}
        </section>

        {shown && layout === 'panels' && (
          <aside className="flex flex-col gap-5 lg:col-span-2 xl:col-span-1" aria-label="Meeting outcomes">
            <QuestionPanel questions={shown.open_questions} participants={participants} autopilot={shown.control_mode === 'autopilot'} disabled={readOnly} onAnswer={(id, text) => meeting.answer(id, text)} />
            <DocumentReviewPanel reviews={shown.reviews} approvals={shown.approvals_open} disabled={readOnly} onDecide={decide} />
            <DecisionPanel decisions={shown.decisions} participants={participants} />
            <ActionItemsPanel items={shown.action_items} participants={participants} />
            <RiskDependencyPanel risks={shown.risks} dependencies={shown.dependencies} participants={participants} />
            {shown.summary && (
              <section aria-label="Summary" className="rounded-lg border border-[#E2E0D9] bg-white p-3" data-testid="summary">
                <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5B5B5B]">Summary</h2>
                <p className="mt-1 text-[12.5px] text-[#161616]">{shown.summary}</p>
              </section>
            )}
          </aside>
        )}
      </div>

      {recap && shown && <RecapDialog view={shown} events={meeting.events} onClose={() => setRecap(false)} />}
      {help && <ShortcutsHelp onClose={() => setHelp(false)} />}
      {transcript !== null && (
        <div role="dialog" aria-modal="true" aria-label="Transcript" className="fixed inset-0 z-[120] flex items-center justify-center bg-black/40 p-4">
          <div className="flex max-h-[85vh] w-full max-w-3xl flex-col rounded-xl bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-[#E2E0D9] px-4 py-2">
              <h2 className="text-[13px] font-semibold">Transcript</h2>
              <button type="button" onClick={() => setTranscript(null)} autoFocus className="rounded-md border border-[#E2E0D9] px-2.5 py-1 text-[12px]">Close</button>
            </div>
            <pre data-testid="transcript-text" className="flex-1 overflow-auto whitespace-pre-wrap p-4 font-mono text-[12px] text-[#161616]">{transcript || 'The transcript is empty.'}</pre>
          </div>
        </div>
      )}
    </main>
  );
}
