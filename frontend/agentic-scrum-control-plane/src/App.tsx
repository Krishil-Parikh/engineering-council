import { useState } from 'react';
import { WorkspaceProvider } from './state/WorkspaceProvider';
import { WorkspaceShell } from './app/WorkspaceShell';
import { createRepositoryFromConfig } from './repositories/createRepositoryFromConfig';
import type { WorkspaceRepository } from './repositories/WorkspaceRepository';
import { readConfig } from './app/config';

const appConfig = readConfig();

export default function App() {
  const [repository] = useState<WorkspaceRepository>(() => createRepositoryFromConfig(appConfig));

  return (
    <WorkspaceProvider workspaceId={appConfig.workspaceId} repository={repository}>
      <WorkspaceShell />
    </WorkspaceProvider>
  );
}
