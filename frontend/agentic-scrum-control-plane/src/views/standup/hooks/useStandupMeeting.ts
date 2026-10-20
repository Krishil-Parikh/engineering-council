import { useCallback, useEffect, useRef, useState } from 'react';
import { lastSequence, mergeEvents } from '../models/meeting-events';
import type { MeetingEventWire } from '../models/meeting-events';
import { isOver } from '../models/meeting-status';
import type { ControlMode } from '../models/meeting-status';
import type { StandupApi, StandupView, StreamState } from '../models/standup';
import { useStandupEvents } from './useStandupEvents';

const THROTTLE_MS = 250;

export interface StandupMeetingState {
  view: StandupView | null;
  /** When the view reached this screen (the meeting clock counts on from there). */
  receivedAt: number;
  events: MeetingEventWire[];
  loading: boolean;
  error: string | null;
  stream: StreamState;
  refresh: () => Promise<void>;
  answer: (questionId: string, text: string) => Promise<void>;
  direct: (text: string) => Promise<string | undefined>;
  setControl: (mode: ControlMode) => Promise<void>;
  actionError: string | null;
}

/** One meeting, live: its view, its events (stored once each, in order) and the stream that keeps both current. A meeting of an earlier record is read once and not streamed. */
export function useStandupMeeting(api: StandupApi | undefined, workspaceId: string, meetingId: string | null, record?: string): StandupMeetingState {
  const [view, setView] = useState<StandupView | null>(null);
  const [receivedAt, setReceivedAt] = useState(() => Date.now());
  const [events, setEvents] = useState<MeetingEventWire[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [startAfter, setStartAfter] = useState<number | null>(null);
  const viewSequence = useRef(0);
  const eventsRef = useRef<MeetingEventWire[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pending = useRef(false);
  const alive = useRef(true);

  const loadView = useCallback(async () => {
    if (!api || !meetingId) return;
    try {
      const response = await api.getMeeting(workspaceId, meetingId, { record });
      if (!alive.current || response.lastSequence < viewSequence.current) return; // an older answer that arrived late must not undo a newer one
      viewSequence.current = response.lastSequence;
      setView(response.view);
      setReceivedAt(Date.now());
      setError(null);
    } catch (caught) {
      if (alive.current) setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, [api, workspaceId, meetingId, record]);

  const loadEvents = useCallback(async (after: number) => {
    if (!api || !meetingId) return;
    let cursor = after;
    for (let page = 0; page < 50; page += 1) {
      const response = await api.getEvents(workspaceId, meetingId, cursor, record);
      if (!alive.current) return;
      eventsRef.current = mergeEvents(eventsRef.current, response.events);
      setEvents(eventsRef.current);
      if (!response.more || response.events.length === 0) break;
      cursor = response.lastSequence;
    }
  }, [api, workspaceId, meetingId, record]);

  // a new event: the view is fetched again, but not more than a few times a second however fast the meeting talks
  const scheduleView = useCallback(() => {
    if (timer.current) {
      pending.current = true;
      return;
    }
    void loadView();
    timer.current = setTimeout(() => {
      timer.current = null;
      if (pending.current) {
        pending.current = false;
        scheduleView();
      }
    }, THROTTLE_MS);
  }, [loadView]);

  useEffect(() => {
    alive.current = true;
    viewSequence.current = 0;
    eventsRef.current = [];
    setView(null);
    setEvents([]);
    setError(null);
    setStartAfter(null);
    if (!api || !meetingId) {
      setLoading(false);
      return undefined;
    }
    setLoading(true);
    void (async () => {
      try {
        await Promise.all([loadView(), loadEvents(0)]);
        if (alive.current) setStartAfter(lastSequence(eventsRef.current));
      } catch (caught) {
        if (alive.current) setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        if (alive.current) setLoading(false);
      }
    })();
    return () => {
      alive.current = false;
      if (timer.current) clearTimeout(timer.current);
      timer.current = null;
      pending.current = false;
    };
  }, [api, meetingId, record, loadView, loadEvents]);

  const live = Boolean(view) && !isOver(view!.status) && !record;
  const stream = useStandupEvents(
    api, workspaceId, meetingId, startAfter, live,
    (event) => {
      const before = eventsRef.current;
      eventsRef.current = mergeEvents(before, [event]);
      if (eventsRef.current !== before) {
        setEvents(eventsRef.current);
        scheduleView();
      }
    },
    () => void loadEvents(lastSequence(eventsRef.current)).then(scheduleView),
  );

  useEffect(() => {
    if (stream === 'ended') void loadView(); // the last word on a meeting that just finished
  }, [stream, loadView]);

  const act = useCallback(async <T,>(work: () => Promise<T>): Promise<T | undefined> => {
    setActionError(null);
    try {
      const result = await work();
      scheduleView();
      return result;
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : String(caught));
      return undefined;
    }
  }, [scheduleView]);

  return {
    view, receivedAt, events, loading, error, stream, actionError,
    refresh: async () => { await Promise.all([loadView(), loadEvents(lastSequence(eventsRef.current))]); },
    answer: async (questionId, text) => { if (api && meetingId) await act(() => api.answer(workspaceId, meetingId, questionId, text)); },
    direct: async (text) => (api && meetingId ? (await act(() => api.direct(workspaceId, meetingId, text)))?.note : undefined),
    setControl: async (mode) => { if (api) await act(() => api.setControl(workspaceId, mode)); },
  };
}
