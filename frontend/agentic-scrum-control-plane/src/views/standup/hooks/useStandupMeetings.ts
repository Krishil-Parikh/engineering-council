import { useCallback, useEffect, useRef, useState } from 'react';
import type { StandupApi, StandupListing } from '../models/standup';

const EMPTY: StandupListing = { record: '', records: [], autopilot: false, meetings: [] };

/** The list of formal meetings, kept fresh. `record` picks an earlier project's record (read only). */
export function useStandupMeetings(api: StandupApi | undefined, workspaceId: string, record?: string, refreshMs = 4000) {
  const [listing, setListing] = useState<StandupListing>(EMPTY);
  const [loading, setLoading] = useState(Boolean(api));
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);

  const refresh = useCallback(async () => {
    if (!api) return;
    try {
      const next = await api.listMeetings(workspaceId, record);
      if (!alive.current) return;
      setListing(next);
      setError(null);
    } catch (caught) {
      if (alive.current) setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [api, workspaceId, record]);

  useEffect(() => {
    alive.current = true;
    setLoading(Boolean(api));
    void refresh();
    const timer = refreshMs > 0 ? setInterval(() => void refresh(), refreshMs) : null;
    return () => {
      alive.current = false;
      if (timer) clearInterval(timer);
    };
  }, [api, refresh, refreshMs]);

  return { listing, loading, error, refresh };
}
