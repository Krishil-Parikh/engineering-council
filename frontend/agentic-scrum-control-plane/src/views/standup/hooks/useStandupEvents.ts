import { useEffect, useRef, useState } from 'react';
import type { MeetingEventWire } from '../models/meeting-events';
import type { StandupApi, StreamState } from '../models/standup';

/** Follows one meeting live. Calls `onEvent` for every event after `after` (an event seen twice is passed on twice: the caller stores by sequence number), reports the health of the stream, and
 *  stops by itself when the meeting is over. A stream is only opened when `enabled`. */
export function useStandupEvents(
  api: StandupApi | undefined, workspaceId: string, meetingId: string | null, after: number | null, enabled: boolean,
  onEvent: (event: MeetingEventWire) => void, onReconnected?: () => void,
): StreamState {
  const [state, setState] = useState<StreamState>('closed');
  const handler = useRef(onEvent);
  const reconnected = useRef(onReconnected);
  handler.current = onEvent;
  reconnected.current = onReconnected;

  useEffect(() => {
    if (!api || !meetingId || after === null || !enabled) {
      setState('closed');
      return undefined;
    }
    let previous: StreamState = 'connecting';
    const stop = api.stream(workspaceId, meetingId, after, {
      onEvent: (event) => handler.current(event),
      onState: (next) => {
        if (next === 'connected' && previous === 'reconnecting') reconnected.current?.(); // the browser reconnected: fetch what the drop may have hidden
        previous = next;
        setState(next);
      },
    });
    return stop;
    // `after` is only where a new stream starts: moving it while a stream is open must not restart the stream
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, workspaceId, meetingId, enabled, after === null]);

  return state;
}
