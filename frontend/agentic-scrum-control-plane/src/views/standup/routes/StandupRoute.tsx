import { useCallback } from 'react';
import { StandupView } from '../components/StandupView';

const PARAM = 'standup';

function initialMeeting(): string | null {
  try {
    return new URLSearchParams(window.location.search).get(PARAM);
  } catch {
    return null;
  }
}

/** The Standup screen as a view of the workspace shell. The open meeting is kept in the address (`?standup=<meeting>`), so a link or a reload opens the same one. */
export function StandupRoute() {
  const remember = useCallback((id: string | null) => {
    try {
      const url = new URL(window.location.href);
      if (id) url.searchParams.set(PARAM, id);
      else url.searchParams.delete(PARAM);
      window.history.replaceState(null, '', url);
    } catch {
      /* an address that cannot be changed (a sandboxed frame) just means no deep link */
    }
  }, []);
  return <StandupView initialMeetingId={initialMeeting()} onMeetingChange={remember} />;
}
