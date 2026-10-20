import { useCallback } from 'react';
import { StandupView } from '../components/StandupView';
import type { StandupLayout } from '../components/StandupView';

const PARAM = 'standup';

function initialMeeting(): string | null {
  try {
    return new URLSearchParams(window.location.search).get(PARAM);
  } catch {
    return null;
  }
}

function initialLayout(): StandupLayout {
  const ok = (v: string | null): v is StandupLayout => v === 'call' || v === 'panels' || v === 'tree' || v === 'board';
  try {
    const asked = new URLSearchParams(window.location.search).get('layout');
    if (ok(asked)) return asked;
    const kept = window.localStorage.getItem('standup.layout');
    if (ok(kept)) return kept;
  } catch {
    /* no address or storage to read: the call it is */
  }
  return 'call';
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
  return <StandupView initialMeetingId={initialMeeting()} initialLayout={initialLayout()} onMeetingChange={remember} />;
}
