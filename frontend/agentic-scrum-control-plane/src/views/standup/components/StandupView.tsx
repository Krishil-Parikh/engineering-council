import { useEffect, useMemo, useState } from 'react';
import { useWorkspace } from '../../../state/WorkspaceProvider';
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

export function StandupView({ initialMeetingId, onMeetingChange }: { initialMeetingId?: string | null; onMeetingChange?: (id: string | null) => void }) {
  const { repository, snapshot, executeCommand } = useWorkspace();
  const api = repository.standup;
  const workspaceId = snapshot.workspaceId;
  const [record, setRecord] = useState<string | undefined>();
  const { listing, loading: listLoading, error: listError, refresh } = useStandupMeetings(api, workspaceId, record);
  const [selectedId, setSelectedId] = useState<string | null>(initialMeetingId ?? null);
  const [mode, setMode] = useState<'live' | 'replay'>('live');
  const [transcript, setTranscript] = useState<string | null>(null);
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

  const openTranscript = async () => {
    if (!api || !selectedId) return;
    try {
      setTranscript(await api.getTranscript(workspaceId, selectedId, record));
    } catch (caught) {
      setTranscript(`The transcript could not be loaded: ${caught instanceof Error ? caught.message : String(caught)}`);
    }
  };

  if (!api) {
    return <main className="mx-auto max-w-2xl p-8 pt-20"><Notice kind="info">Meetings need a backend that records them. Start the gateway and open the app in live mode.</Notice></main>;
  }

  return (
    <main className="flex min-h-screen flex-col bg-[#F4F3EE] pt-11 text-[#161616]" data-testid="standup-view">
      {listError && <div className="px-4 pt-3"><Notice kind="error" action={<button type="button" onClick={() => void refresh()} className="rounded-md border border-current px-3 py-1 text-[12px] font-semibold">Retry</button>}>The meeting list could not be loaded: {listError}</Notice></div>}
      <div className="grid flex-1 grid-cols-1 gap-4 p-4 lg:grid-cols-[17rem_minmax(0,1fr)] xl:grid-cols-[17rem_minmax(0,1fr)_21rem]">
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
          {shown && <ParticipantGrid participants={participants} />}
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
              <div className="flex min-h-0 flex-1 flex-col gap-3 p-4">
                <MeetingTimeline entries={shown.recent} highlight={mode === 'replay' ? replay.position : undefined} onOpenTranscript={() => void openTranscript()} />
                <InterventionBar disabled={readOnly} onSend={(text) => meeting.direct(text)} />
                {meeting.actionError && <p role="alert" className="text-[12px] text-[#8F0000]">{meeting.actionError}</p>}
              </div>
              {mode === 'replay' ? (
                <ReplayControls replay={replay} elapsedAt={shown.elapsed_seconds} onBackToLive={() => setMode('live')} />
              ) : (
                <div className="flex items-center justify-between border-t border-[#E2E0D9] px-4 py-2">
                  <span className="text-[11px] text-[#8E8E8E]">{live.last_sequence} events recorded</span>
                  <button type="button" onClick={() => setMode('replay')} className="rounded-md border border-[#161616] px-3 py-1 text-[12px] font-semibold hover:bg-[#161616] hover:text-white">Replay this meeting</button>
                </div>
              )}
            </>
          )}
        </section>

        {shown && (
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
