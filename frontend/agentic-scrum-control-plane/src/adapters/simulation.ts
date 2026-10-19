import type { WorkspaceEvent } from '../domain/types';

export interface SimulationOptions {
  intervalMs?: number;
  meetId?: string;
}

const SCRIPT = [
  { agentId: 'agent-04', senderName: 'Agent-04', text: 'Benchmarking partition rebalance under simulated link-loss. Latency impact bounded to 3.4ms with local fallback.' },
  { agentId: 'agent-06', senderName: 'Agent-06', text: 'Jepsen suite injected 30% packet loss during leader re-election. Commit round-trip spiked to 19.8ms.' },
  { agentId: 'agent-03', senderName: 'Agent-03', text: 'Mitigating jitter by enabling TCP nodelay on multiplex channels and pinning heartbeat to 15ms.' },
  { agentId: 'agent-05', senderName: 'Agent-05', text: 'Partition pruning confirms zero scanned blocks on yesterday partitions. Plan cost dropped 84%.' },
];

/**
 * Single centralized demo simulation loop. Views must not own timers;
 * the host composition root starts at most one of these per workspace.
 */
export function startWorkspaceSimulation(
  emit: (event: WorkspaceEvent) => void,
  workspaceId: string,
  options: SimulationOptions = {},
): () => void {
  const intervalMs = options.intervalMs ?? 7000;
  const meetId = options.meetId ?? 'meet-04';
  let index = 0;
  let version = 1000;
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const tick = () => {
    if (stopped) return;
    const item = SCRIPT[index % SCRIPT.length];
    index += 1;
    version += 1;
    const timestamp = new Date().toISOString().slice(11, 19);
    emit({
      eventId: `simulation-${version}-${index}`,
      workspaceId,
      occurredAt: new Date().toISOString(),
      version,
      type: 'message.created',
      payload: {
        id: `simulation-msg-${version}`,
        meetId,
        senderId: item.agentId,
        senderName: item.senderName,
        text: item.text,
        timestamp,
      },
    });
    timer = setTimeout(tick, intervalMs);
  };

  timer = setTimeout(tick, intervalMs);
  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
  };
}
