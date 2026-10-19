export interface AppConfig {
  apiBaseUrl: string;
  workspaceId: string;
  transport: 'mock' | 'http-sse' | 'http-websocket';
  enableSimulation: boolean;
}

export function readConfig(env: Record<string, string | undefined> = import.meta.env): AppConfig {
  const rawTransport = env.VITE_TRANSPORT;
  const transport: AppConfig['transport'] = rawTransport === 'http-sse' || rawTransport === 'http-websocket' ? rawTransport : 'mock';
  return {
    apiBaseUrl: env.VITE_API_BASE_URL ?? '',
    workspaceId: env.VITE_WORKSPACE_ID ?? 'workspace-demo',
    transport,
    enableSimulation: env.VITE_ENABLE_SIMULATION !== 'false',
  };
}
