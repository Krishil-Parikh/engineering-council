/** The Standup API against the gateway: plain fetch for reading and acting, and a server-sent-event stream per meeting that resumes where it stopped. */
import type { ControlMode } from '../models/meeting-status';
import { parseListing, parseMeetingEvent, parseStandupView } from '../models/standup';
import type {
  StandupApi, StandupEventsResponse, StandupListing, StandupStreamHandlers, StandupViewResponse, ViewOptions,
} from '../models/standup';
import type { MeetingEventWire } from '../models/meeting-events';

export type StandupEventSourceFactory = (url: string) => EventSource;

export class StandupHttpError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'StandupHttpError';
  }
}

export class HttpStandupApi implements StandupApi {
  constructor(
    private readonly baseUrl: string,
    private readonly fetcher: typeof fetch = (input, init) => fetch(input, init), // a bare `fetch` property throws "Illegal invocation" when called as a method
    private readonly eventSourceFactory: StandupEventSourceFactory = (url) => new EventSource(url),
  ) {}

  private url(workspaceId: string, path: string, params: Record<string, string | number | undefined> = {}): string {
    const query = Object.entries(params).filter(([, v]) => v !== undefined && v !== '').map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&');
    return `${this.baseUrl}/workspace/${encodeURIComponent(workspaceId)}/standup${path}${query ? `?${query}` : ''}`;
  }

  private async request(url: string, init?: RequestInit): Promise<Response> {
    let response: Response;
    try {
      response = await this.fetcher(url, init);
    } catch (error) {
      throw new StandupHttpError(`The backend could not be reached: ${error instanceof Error ? error.message : String(error)}`, 0);
    }
    if (!response.ok) {
      let message = `The backend answered ${response.status}`;
      try {
        const body = (await response.json()) as { error?: { message?: string }; detail?: string };
        message = body.error?.message ?? body.detail ?? message;
      } catch {
        /* not JSON: keep the status line */
      }
      throw new StandupHttpError(message, response.status);
    }
    return response;
  }

  private async json(url: string, init?: RequestInit): Promise<unknown> {
    return (await this.request(url, init)).json();
  }

  async listMeetings(workspaceId: string, record?: string): Promise<StandupListing> {
    return parseListing(await this.json(this.url(workspaceId, '/meetings', { record })));
  }

  async getMeeting(workspaceId: string, meetingId: string, options: ViewOptions = {}): Promise<StandupViewResponse> {
    const body = (await this.json(this.url(workspaceId, `/meetings/${encodeURIComponent(meetingId)}`, { at: options.at, record: options.record }))) as Record<string, unknown>;
    return { view: parseStandupView(body.view), lastSequence: Number(body.lastSequence ?? 0), record: String(body.record ?? '') };
  }

  async getEvents(workspaceId: string, meetingId: string, after = 0, record?: string): Promise<StandupEventsResponse> {
    const body = (await this.json(this.url(workspaceId, `/meetings/${encodeURIComponent(meetingId)}/events`, { after, limit: 1000, record }))) as Record<string, unknown>;
    if (!Array.isArray(body.events)) throw new Error('Unexpected event list from the backend: events is not a list');
    return { meetingId, events: body.events.map(parseMeetingEvent), more: body.more === true, lastSequence: Number(body.lastSequence ?? after) };
  }

  async getTranscript(workspaceId: string, meetingId: string, record?: string): Promise<string> {
    return (await this.request(this.url(workspaceId, `/meetings/${encodeURIComponent(meetingId)}/transcript`, { record }))).text();
  }

  async answer(workspaceId: string, meetingId: string, questionId: string, answer: string): Promise<void> {
    await this.request(this.url(workspaceId, `/meetings/${encodeURIComponent(meetingId)}/answer`), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ questionId, answer }),
    });
  }

  async direct(workspaceId: string, meetingId: string, text: string): Promise<{ accepted: boolean; note?: string }> {
    const body = (await this.json(this.url(workspaceId, `/meetings/${encodeURIComponent(meetingId)}/direct`), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }),
    })) as { accepted?: boolean; note?: string };
    return { accepted: body.accepted === true, note: body.note };
  }

  async setControl(workspaceId: string, mode: ControlMode): Promise<{ mode: ControlMode; meetingsTold: number }> {
    const body = (await this.json(this.url(workspaceId, '/control'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode }),
    })) as { mode: ControlMode; meetingsTold: number };
    return { mode: body.mode, meetingsTold: Number(body.meetingsTold ?? 0) };
  }

  stream(workspaceId: string, meetingId: string, after: number, handlers: StandupStreamHandlers): () => void {
    let source: EventSource | null = null;
    let stopped = false;
    handlers.onState('connecting');
    const open = () => {
      source = this.eventSourceFactory(this.url(workspaceId, `/meetings/${encodeURIComponent(meetingId)}/stream`, { after }));
      source.onopen = () => handlers.onState('connected');
      source.onmessage = (message: MessageEvent) => {
        try {
          const event: MeetingEventWire = parseMeetingEvent(JSON.parse(message.data));
          after = Math.max(after, event.sequence_number);
          handlers.onState('connected');
          handlers.onEvent(event);
        } catch {
          /* a frame this screen cannot read is skipped; the next catch-up fetches it again */
        }
      };
      source.addEventListener('end', () => {
        stopped = true;
        source?.close();
        handlers.onState('ended');
      });
      // the browser reconnects by itself and sends Last-Event-ID, so the server resumes after the last frame it saw
      source.onerror = () => {
        if (!stopped) handlers.onState('reconnecting');
      };
    };
    open();
    return () => {
      stopped = true;
      source?.close();
      handlers.onState('closed');
    };
  }
}
