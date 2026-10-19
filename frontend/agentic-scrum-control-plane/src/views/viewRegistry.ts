import { lazy } from 'react';
import { GenUIView } from './GenUIView/GenUIView';

export type WorkspaceMode = 'genui' | 'control-plane';

type ViewComponent = React.ComponentType | React.LazyExoticComponent<React.ComponentType>;

// Control Plane loads on demand so the default GenUI view paints without
// the delegation-graph code. The boundary already guarantees GenUI never
// imports control-plane modules, so the split is clean by construction.
const LazyControlPlaneView = lazy(() =>
  import('./control-plane/WorkspaceControlPlaneView').then((module) => ({ default: module.WorkspaceControlPlaneView })),
);

export const VIEW_REGISTRY: Record<WorkspaceMode, { id: WorkspaceMode; label: string; Component: ViewComponent }> = {
  genui: { id: 'genui', label: 'GenUI', Component: GenUIView },
  'control-plane': { id: 'control-plane', label: 'Control Plane', Component: LazyControlPlaneView },
};

export const VIEW_ORDER: WorkspaceMode[] = ['genui', 'control-plane'];
