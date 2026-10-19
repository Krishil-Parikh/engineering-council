import React, { useEffect, useState } from 'react';
import { useWorkspace } from '../state/WorkspaceProvider';
import { VIEW_ORDER, VIEW_REGISTRY, type WorkspaceMode } from '../views/viewRegistry';
import { selectIsEmptyWorkspace } from '../domain/selectors';
import { readConfig } from './config';
import { MockWorkspaceRepository } from '../repositories/MockWorkspaceRepository';
import { startWorkspaceSimulation } from '../adapters/simulation';

const appConfig = readConfig();

function WorkspaceSwitcher({ mode, onChange }: { mode: WorkspaceMode; onChange: (mode: WorkspaceMode) => void }) {
  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    const index = VIEW_ORDER.indexOf(mode);
    const next = event.key === 'ArrowRight'
      ? VIEW_ORDER[(index + 1) % VIEW_ORDER.length]
      : VIEW_ORDER[(index - 1 + VIEW_ORDER.length) % VIEW_ORDER.length];
    onChange(next);
  };

  return (
    <nav className="fixed inset-x-0 top-0 z-[100] flex h-11 items-center justify-center border-b border-[#E7E6DF] bg-[#FFFFFF]/95 px-4 shadow-[0_1px_8px_rgba(22,22,22,0.06)] backdrop-blur-md">
      <div className="flex items-center gap-1 rounded-lg border border-[#E2E0D9] bg-[#F4F3EE] p-1" role="tablist" aria-label="Workspace view" onKeyDown={handleKeyDown}>
        {VIEW_ORDER.map((viewId) => {
          const entry = VIEW_REGISTRY[viewId];
          const selected = mode === viewId;
          return (
            <button
              key={viewId}
              type="button"
              role="tab"
              aria-selected={selected}
              onClick={() => onChange(viewId)}
              className={`rounded-md px-5 py-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] transition-colors ${
                selected ? 'bg-[#161616] text-white shadow-sm' : 'text-[#5B5B5B] hover:text-[#161616]'
              }`}
            >
              {entry.label}
            </button>
          );
        })}
      </div>
    </nav>
  );
}

function StatusBanner({ kind, message, actionLabel, onAction }: { kind: 'error' | 'warning' | 'info'; message: string; actionLabel?: string; onAction?: () => void }) {
  const palette = kind === 'error'
    ? 'border-[#E60000]/30 bg-[#E60000]/5 text-[#8F0000]'
    : kind === 'warning'
      ? 'border-[#B8860B]/40 bg-[#FFF7E0] text-[#6B4E00]'
      : 'border-[#E2E0D9] bg-[#F4F3EE] text-[#5B5B5B]';
  return (
    <div role={kind === 'error' ? 'alert' : 'status'} className={`mx-auto mt-2 flex max-w-3xl items-center justify-between gap-4 rounded-lg border px-4 py-2 text-[13px] ${palette}`}>
      <span>{message}</span>
      {actionLabel && onAction && (
        <button type="button" onClick={onAction} className="shrink-0 rounded-md border border-current px-3 py-1 text-[12px] font-semibold">
          {actionLabel}
        </button>
      )}
    </div>
  );
}

export function WorkspaceShell() {
  const [mode, setMode] = useState<WorkspaceMode>('genui');
  const { snapshot, repository, status, error, commandError, retry, refresh } = useWorkspace();
  const ActiveView = VIEW_REGISTRY[mode].Component;
  const isEmpty = status === 'ready' && selectIsEmptyWorkspace(snapshot);

  useEffect(() => {
    if (!appConfig.enableSimulation) return;
    if (!(repository instanceof MockWorkspaceRepository)) return;
    const stop = startWorkspaceSimulation(repository.emit.bind(repository), appConfig.workspaceId);
    return stop;
  }, [repository]);

  return (
    <>
      <WorkspaceSwitcher mode={mode} onChange={setMode} />
      <div className="pt-11">
        {status === 'loading' && (
          <div role="status" aria-live="polite" className="mx-auto max-w-3xl px-4 py-16 text-center text-[14px] text-[#5B5B5B]">
            Loading workspace…
          </div>
        )}
        {status === 'error' && (
          <StatusBanner kind="error" message={error?.message ?? 'Workspace failed to load.'} actionLabel="Retry" onAction={retry} />
        )}
        {status === 'permission-denied' && (
          <StatusBanner kind="error" message={error?.message ?? 'You do not have access to this workspace.'} actionLabel="Retry" onAction={retry} />
        )}
        {status === 'disconnected' && (
          <StatusBanner kind="warning" message="Event stream disconnected — showing cached state." actionLabel="Reconnect" onAction={retry} />
        )}
        {status === 'stale' && (
          <StatusBanner kind="warning" message={error?.message ?? 'Data may be stale — refresh to reconcile.'} actionLabel="Refresh" onAction={refresh} />
        )}
        {commandError && (
          <StatusBanner kind="error" message={`Command failed: ${commandError.message}`} />
        )}
        {isEmpty && (
          <div role="status" className="mx-auto max-w-3xl px-4 py-16 text-center">
            <p className="text-[16px] font-semibold text-[#161616]">This workspace is empty</p>
            <p className="mt-1 text-[13px] text-[#5B5B5B]">Start a sprint from either view to seed agents, meets, and artifacts.</p>
          </div>
        )}
        {status !== 'loading' && (status === 'ready' || status === 'disconnected' || status === 'stale') && !isEmpty && (
          <React.Suspense
            fallback={(
              <div role="status" aria-live="polite" className="mx-auto max-w-3xl px-4 py-16 text-center text-[14px] text-[#5B5B5B]">
                Loading view…
              </div>
            )}
          >
            <ActiveView />
          </React.Suspense>
        )}
        {status !== 'loading' && (status === 'error' || status === 'permission-denied') && (
          <div className="mx-auto max-w-3xl px-4 py-8 text-center text-[13px] text-[#5B5B5B]">
            The workspace could not be loaded. Resolve the issue above to continue.
          </div>
        )}
      </div>
    </>
  );
}
