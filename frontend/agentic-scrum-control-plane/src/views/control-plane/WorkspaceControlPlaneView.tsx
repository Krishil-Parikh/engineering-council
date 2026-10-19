import { useWorkspace } from '../../state/WorkspaceProvider';
import ControlPlaneView from './ControlPlaneView';

/**
 * Control Plane view bound to the shared workspace. This is the only place
 * that injects store state into the view; the view itself stays props-driven.
 */
export function WorkspaceControlPlaneView() {
  const { snapshot, executeCommand } = useWorkspace();
  return (
    <div className="deck-shell">
      <ControlPlaneView workspaceSnapshot={snapshot} executeCommand={executeCommand} />
    </div>
  );
}
