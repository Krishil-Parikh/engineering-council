import { lazy } from 'react';
import { GenUIView } from './GenUIView/GenUIView';

export type WorkspaceMode = 'genui' | 'control-plane' | 'standup';

type ViewComponent = React.ComponentType | React.LazyExoticComponent<React.ComponentType>;

// Control Plane loads on demand so the default GenUI view paints without
// the delegation-graph code. The boundary already guarantees GenUI never
// imports control-plane modules, so the split is clean by construction.
const LazyControlPlaneView = lazy(() =>
  import('./control-plane/WorkspaceControlPlaneView').then((module) => ({ default: module.WorkspaceControlPlaneView })),
);

// The formal Scrum meetings (live and replayable) load on demand too.
const LazyStandupView = lazy(() => import('./standup/routes/StandupRoute').then((module) => ({ default: module.StandupRoute })));

export const VIEW_REGISTRY: Record<WorkspaceMode, { id: WorkspaceMode; label: string; Component: ViewComponent }> = {
  genui: { id: 'genui', label: 'GenUI', Component: GenUIView },
  'control-plane': { id: 'control-plane', label: 'Control Plane', Component: LazyControlPlaneView },
  standup: { id: 'standup', label: 'Standup', Component: LazyStandupView },
};

export const VIEW_ORDER: WorkspaceMode[] = ['genui', 'control-plane', 'standup'];
