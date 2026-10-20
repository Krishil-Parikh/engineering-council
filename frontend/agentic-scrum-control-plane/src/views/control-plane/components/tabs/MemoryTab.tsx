import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Brain, Search, Network, List, Sparkles, X } from 'lucide-react';
import { useScrum } from '../../context/ScrumContext';
import { EMPTY_MEMORY } from '../../../../domain/memory';
import type { MemoryGraphData, MemoryHit, MemoryNode, MemorySignals } from '../../../../domain/memory';
import { layoutGraph } from '../memory/forceLayout';
import type { Point } from '../memory/forceLayout';

const REFRESH_MS = 4000;
const WIDTH = 900;
const HEIGHT = 640;

export const KIND_COLOR: Record<string, string> = {
  file: '#6B7280', task: '#161616', feature: '#0057B8', decision: '#E60000', convention: '#0F8A4B', api: '#B27000', pitfall: '#A30000',
  'how-to': '#6D28D9', note: '#8E8E8E', insight: '#C2410C', agent: '#0891B2', preference: '#DB2777',
};
const colorOf = (kind: string) => KIND_COLOR[kind] ?? '#8E8E8E';
const radiusOf = (n: MemoryNode) => 5 + Math.min(10, n.importance) * 0.9 + Math.min(n.degree ?? 0, 10) * 0.4;
const when = (seconds: number) => new Date(seconds * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

function SignalChips({ signals }: { signals: MemorySignals }) {
  const chips: string[] = [];
  if (signals.bm25) chips.push(`words #${signals.bm25}`);
  if (signals.dense) chips.push(`meaning #${signals.dense}${signals.cosine ? ` (${signals.cosine.toFixed(2)})` : ''}`);
  if (signals.entity) chips.push('named in the question');
  if (signals.via === 'link') chips.push('found through a link');
  else if (signals.graph && signals.graph > 0.5) chips.push('close in the graph');
  if (signals.rerank) chips.push(`reranked #${signals.rerank}`);
  if (signals.importance) chips.push(`importance ${signals.importance}`);
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {chips.map((chip) => (
        <span key={chip} className="rounded-[3px] border border-[#E2E0D9] bg-[#F4F3EE] px-1.5 py-0.5 text-[9.5px] font-mono text-[#5B5B5B]">{chip}</span>
      ))}
    </div>
  );
}

export const MemoryTab: React.FC = () => {
  const { memoryApi, workspaceKey } = useScrum();
  const [scope, setScope] = useState('project');
  const [data, setData] = useState<MemoryGraphData>(EMPTY_MEMORY);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [deep, setDeep] = useState(true);
  const [hits, setHits] = useState<MemoryHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [view, setView] = useState<'graph' | 'list'>('graph');
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [allFiles, setAllFiles] = useState(false);
  const [zoom, setZoom] = useState({ scale: 1, x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number } | null>(null);
  const positions = useRef<Map<string, Point>>(new Map());

  // the memory keeps growing while the team works: look again every few seconds
  useEffect(() => {
    if (!memoryApi) return undefined;
    let stopped = false;
    const load = async () => {
      try {
        const next = await memoryApi.graph(workspaceKey, scope, 400);
        if (stopped) return;
        setData(next);
        setError(null);
      } catch (e) {
        if (!stopped) setError(e instanceof Error ? e.message : 'Could not read the memory');
      }
    };
    void load();
    const timer = setInterval(() => { void load(); }, REFRESH_MS);
    return () => { stopped = true; clearInterval(timer); };
  }, [memoryApi, workspaceKey, scope]);

  useEffect(() => { positions.current = new Map(); setSelectedId(null); setHits(null); setZoom({ scale: 1, x: 0, y: 0 }); }, [scope]);

  // A project's code files can outnumber everything it knows. By default the graph is about knowledge (decisions, conventions, APIs, pitfalls, insights, tasks) and
  // shows a code file only when something the team knows is linked to it; "show every file" brings them all back.
  const crowded = data.nodes.length > 80 && data.nodes.filter((n) => n.kind === 'file').length > 20;
  const filesHidden = crowded && !allFiles;
  const visibleNodes = useMemo(() => {
    const linkedFiles = new Set<string>();
    if (filesHidden) {
      const knowledge = new Set(data.nodes.filter((n) => n.kind !== 'file').map((n) => n.id));
      for (const e of data.edges) {
        if (knowledge.has(e.source)) linkedFiles.add(e.target);
        if (knowledge.has(e.target)) linkedFiles.add(e.source);
      }
    }
    return data.nodes.filter((n) => !hidden.has(n.kind) && (!filesHidden || n.kind !== 'file' || linkedFiles.has(n.id)));
  }, [data.nodes, data.edges, hidden, filesHidden]);
  const visibleIds = useMemo(() => new Set(visibleNodes.map((n) => n.id)), [visibleNodes]);
  const visibleEdges = useMemo(() => data.edges.filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target)), [data.edges, visibleIds]);
  const structure = `${scope}|${visibleNodes.map((n) => n.id).join(',')}|${visibleEdges.length}`;
  const placed = useMemo(() => {
    const next = layoutGraph(visibleNodes.map((n) => ({ id: n.id, r: radiusOf(n) })), visibleEdges.map((e) => ({ source: e.source, target: e.target, weight: e.weight })), positions.current, WIDTH, HEIGHT);
    positions.current = next;
    return next;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [structure]);

  const byId = useMemo(() => new Map(data.nodes.map((n) => [n.id, n])), [data.nodes]);
  const selected = selectedId ? byId.get(selectedId) ?? null : null;
  const hitIds = useMemo(() => new Set((hits ?? []).map((h) => h.id)), [hits]);
  const linked = useMemo(() => {
    if (!selectedId) return new Set<string>();
    const ids = new Set<string>([selectedId]);
    for (const e of data.edges) {
      if (e.source === selectedId) ids.add(e.target);
      if (e.target === selectedId) ids.add(e.source);
    }
    return ids;
  }, [data.edges, selectedId]);
  const links = useMemo(() => {
    if (!selectedId) return [];
    return data.edges
      .filter((e) => e.source === selectedId || e.target === selectedId)
      .map((e) => ({ relation: e.relation, outgoing: e.source === selectedId, other: byId.get(e.source === selectedId ? e.target : e.source) }))
      .filter((l): l is { relation: string; outgoing: boolean; other: MemoryNode } => Boolean(l.other));
  }, [data.edges, selectedId, byId]);

  const kinds = useMemo(() => {
    const counts = new Map<string, number>();
    data.nodes.forEach((n) => counts.set(n.kind, (counts.get(n.kind) ?? 0) + 1));
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [data.nodes]);

  const runSearch = async () => {
    if (!memoryApi || !query.trim()) { setHits(null); return; }
    setSearching(true);
    try {
      setHits(await memoryApi.search(workspaceKey, scope, query.trim(), deep));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The search failed');
    } finally {
      setSearching(false);
    }
  };

  if (!memoryApi) {
    return (
      <div className="flex flex-1 items-center justify-center bg-[#FCFCFB] p-10 text-center text-[13px] text-[#5B5B5B]">
        The team's memory belongs to a real run. Connect the gateway (<code className="mx-1 font-mono">npm run dev:live</code>) to see it here.
      </div>
    );
  }

  const agentScopes = ['project', ...data.agents];
  const countFor = (name: string) => (name === 'project' ? data.overview.project?.nodes : data.overview.agents?.[name]?.nodes) ?? 0;

  return (
    <div className="flex h-full flex-1 flex-col overflow-hidden bg-[#FCFCFB] select-none">
      {/* scope, search, filters */}
      <div className="flex shrink-0 flex-col gap-2 border-b border-[#E2E0D9] bg-[#FFFFFF] px-5 py-3">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <Brain className="h-4 w-4 text-[#161616]" />
            <h2 className="text-[13px] font-bold uppercase tracking-wider text-[#161616]">Team memory</h2>
            <div role="tablist" aria-label="Memory scope" className="ml-3 flex flex-wrap items-center gap-1.5">
              {agentScopes.map((name) => (
                <button
                  key={name}
                  role="tab"
                  aria-selected={scope === name}
                  onClick={() => setScope(name)}
                  className={`rounded-[8px] border px-2.5 py-1 text-[11.5px] font-semibold transition-colors ${scope === name ? 'border-[#161616] bg-[#161616] text-[#FFFFFF]' : 'border-[#E2E0D9] bg-[#F4F3EE] text-[#5B5B5B] hover:text-[#161616]'}`}
                >
                  {name === 'project' ? 'Project (shared)' : `${name} (own)`} <span className="ml-1 font-mono text-[10px] opacity-70">{countFor(name)}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-1 rounded-[8px] border border-[#E2E0D9] bg-[#F4F3EE] p-0.5">
            <button aria-label="Graph view" onClick={() => setView('graph')} className={`rounded-[6px] p-1.5 ${view === 'graph' ? 'bg-[#FFFFFF] shadow-xs' : ''}`}><Network className="h-3.5 w-3.5" /></button>
            <button aria-label="List view" onClick={() => setView('list')} className={`rounded-[6px] p-1.5 ${view === 'list' ? 'bg-[#FFFFFF] shadow-xs' : ''}`}><List className="h-3.5 w-3.5" /></button>
          </div>
        </div>
        <form className="flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); void runSearch(); }}>
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-[#5B5B5B]" />
            <input
              aria-label="Ask the memory"
              value={query}
              onChange={(e) => { setQuery(e.target.value); if (!e.target.value) setHits(null); }}
              placeholder="Ask the memory: how do we handle time in tests? who touched the router? why did we decide that?"
              className="w-full rounded-[8px] border border-[#E2E0D9] bg-[#F4F3EE] py-1.5 pl-8 pr-3 text-[12px] text-[#161616] outline-none focus:border-[#161616]"
            />
          </div>
          <label className="flex items-center gap-1.5 text-[11px] text-[#5B5B5B]" title="Rewrites the question, imagines an answer, and has a model rerank the results (slower, finds more)">
            <input type="checkbox" checked={deep} onChange={(e) => setDeep(e.target.checked)} /> deep search
          </label>
          <button type="submit" className="rounded-[8px] bg-[#161616] px-3 py-1.5 text-[11.5px] font-semibold text-[#FFFFFF] disabled:opacity-50" disabled={searching || !query.trim()}>
            {searching ? 'Searching...' : 'Search'}
          </button>
          {hits !== null && <button type="button" aria-label="Clear search" onClick={() => { setHits(null); setQuery(''); }} className="rounded-[6px] p-1.5 text-[#5B5B5B] hover:bg-[#F4F3EE]"><X className="h-3.5 w-3.5" /></button>}
        </form>
        <div className="flex flex-wrap items-center gap-1.5 text-[10.5px]">
          {kinds.map(([kind, count]) => (
            <button
              key={kind}
              aria-pressed={!hidden.has(kind)}
              onClick={() => setHidden((prev) => { const next = new Set(prev); if (next.has(kind)) next.delete(kind); else next.add(kind); return next; })}
              className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 ${hidden.has(kind) ? 'border-[#E2E0D9] opacity-40' : 'border-[#C9C6BC]'}`}
            >
              <span className="h-2 w-2 rounded-full" style={{ background: colorOf(kind) }} />{kind}<span className="font-mono text-[#8E8E8E]">{count}</span>
            </button>
          ))}
          {crowded && (
            <button aria-pressed={allFiles} onClick={() => setAllFiles((v) => !v)} className="ml-1 rounded-full border border-dashed border-[#C9C6BC] px-2 py-0.5 text-[#5B5B5B] hover:text-[#161616]">
              {allFiles ? 'Only files linked to knowledge' : `Show every file (${data.nodes.filter((n) => n.kind === 'file').length})`}
            </button>
          )}
          {error && <span role="alert" className="ml-2 text-[#A30000]">{error}</span>}
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        {/* the graph or the list */}
        <div className="relative min-w-0 flex-1 overflow-hidden bg-[#FCFCFB]">
          {!data.available ? (
            <div className="flex h-full items-center justify-center p-10 text-center text-[13px] text-[#5B5B5B]">The team's memory appears as soon as the build starts: what it builds, decides and learns.</div>
          ) : data.nodes.length === 0 ? (
            <div className="flex h-full items-center justify-center p-10 text-center text-[13px] text-[#5B5B5B]">{scope === 'project' ? 'Nothing has been remembered yet.' : `${scope} has not remembered anything of its own yet.`}</div>
          ) : view === 'graph' ? (
            <svg
              aria-label="Memory graph"
              viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
              className="h-full w-full cursor-grab active:cursor-grabbing"
              onWheel={(e) => { e.preventDefault(); setZoom((z) => ({ ...z, scale: Math.max(0.4, Math.min(3, z.scale * (e.deltaY < 0 ? 1.1 : 0.9))) })); }}
              onMouseDown={(e) => { drag.current = { x: e.clientX - zoom.x, y: e.clientY - zoom.y }; }}
              onMouseMove={(e) => { if (drag.current) setZoom((z) => ({ ...z, x: e.clientX - drag.current!.x, y: e.clientY - drag.current!.y })); }}
              onMouseUp={() => { drag.current = null; }}
              onMouseLeave={() => { drag.current = null; }}
            >
              <g transform={`translate(${zoom.x} ${zoom.y}) scale(${zoom.scale})`}>
                {visibleEdges.map((e) => {
                  const a = placed.get(e.source);
                  const b = placed.get(e.target);
                  if (!a || !b) return null;
                  const focus = !selectedId || (linked.has(e.source) && linked.has(e.target));
                  return <line key={`${e.source}|${e.relation}|${e.target}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#B8B5AA" strokeWidth={Math.min(2.5, 0.6 + e.weight * 0.5)} opacity={focus ? 0.7 : 0.1} />;
                })}
                {visibleNodes.map((n) => {
                  const p = placed.get(n.id);
                  if (!p) return null;
                  const r = radiusOf(n);
                  const dim = (selectedId && !linked.has(n.id)) || (hits !== null && !hitIds.has(n.id));
                  const showLabel = n.id === selectedId || n.id === hoverId || hitIds.has(n.id) || (n.kind !== 'file' && visibleNodes.length < 120) || visibleNodes.length < 30;
                  return (
                    <g
                      key={n.id}
                      role="button"
                      tabIndex={0}
                      aria-label={`${n.kind}: ${n.name}`}
                      transform={`translate(${p.x} ${p.y})`}
                      opacity={dim ? 0.2 : 1}
                      onClick={(e) => { e.stopPropagation(); setSelectedId(n.id); }}
                      onKeyDown={(e) => { if (e.key === 'Enter') setSelectedId(n.id); }}
                      onMouseEnter={() => setHoverId(n.id)}
                      onMouseLeave={() => setHoverId(null)}
                      className="cursor-pointer"
                    >
                      <circle r={r} fill={colorOf(n.kind)} stroke={n.id === selectedId ? '#161616' : hitIds.has(n.id) ? '#E60000' : '#FFFFFF'} strokeWidth={n.id === selectedId || hitIds.has(n.id) ? 3 : 1.5} />
                      {showLabel && (
                        <text
                          x={p.x < 170 ? r + 5 : p.x > WIDTH - 170 ? -(r + 5) : 0}
                          y={p.x < 170 || p.x > WIDTH - 170 ? 3 : r + 11}
                          textAnchor={p.x < 170 ? 'start' : p.x > WIDTH - 170 ? 'end' : 'middle'}
                          fontSize="10" fill="#161616" stroke="#FCFCFB" strokeWidth="3" paintOrder="stroke"
                        >
                          {n.name.length > 34 ? `${n.name.slice(0, 33)}…` : n.name}
                        </text>
                      )}
                    </g>
                  );
                })}
              </g>
            </svg>
          ) : (
            <div className="h-full overflow-y-auto p-4">
              <table className="w-full text-left text-[12px]">
                <thead><tr className="border-b border-[#E2E0D9] text-[10.5px] uppercase tracking-wider text-[#5B5B5B]"><th className="py-1.5">Memory</th><th>Kind</th><th>Importance</th><th>Owner</th><th>Updated</th></tr></thead>
                <tbody>
                  {[...visibleNodes].sort((a, b) => b.updated - a.updated).map((n) => (
                    <tr key={n.id} onClick={() => setSelectedId(n.id)} className={`cursor-pointer border-b border-[#EDECE7] hover:bg-[#F4F3EE] ${n.id === selectedId ? 'bg-[#F4F3EE]' : ''}`}>
                      <td className="py-1.5 pr-3 font-medium text-[#161616]">{n.name}</td>
                      <td><span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ background: colorOf(n.kind) }} />{n.kind}</span></td>
                      <td className="font-mono">{n.importance}</td><td>{n.owner ?? 'system'}</td><td className="font-mono text-[#5B5B5B]">{when(n.updated)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* what is selected, what a search found, or an overview */}
        <aside className="w-[340px] shrink-0 overflow-y-auto border-l border-[#E2E0D9] bg-[#FFFFFF] p-4" aria-label="Memory details">
          {hits !== null ? (
            <div>
              <div className="mb-2 text-[11px] font-bold uppercase tracking-wider text-[#5B5B5B]">{hits.length} result{hits.length === 1 ? '' : 's'}</div>
              {hits.length === 0 && <p className="text-[12px] text-[#5B5B5B]">Nothing in this memory matches that yet.</p>}
              {hits.map((h) => (
                <button key={h.id} onClick={() => setSelectedId(h.id)} className="mb-2 block w-full rounded-[10px] border border-[#E2E0D9] bg-[#FCFCFB] p-2.5 text-left hover:border-[#161616]">
                  <div className="flex items-center justify-between gap-2"><span className="text-[12px] font-semibold text-[#161616]">{h.name}</span><span className="font-mono text-[10px] text-[#5B5B5B]">{h.score.toFixed(2)}</span></div>
                  <div className="mt-0.5 flex items-center gap-1.5 text-[10.5px] text-[#5B5B5B]"><span className="h-2 w-2 rounded-full" style={{ background: colorOf(h.kind) }} />{h.kind}{h.owner ? ` · ${h.owner}` : ''}</div>
                  {h.text && <p className="mt-1 line-clamp-3 text-[11.5px] leading-relaxed text-[#161616]">{h.text}</p>}
                  <SignalChips signals={h.signals} />
                </button>
              ))}
            </div>
          ) : selected ? (
            <div>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="flex items-center gap-1.5 text-[10.5px] uppercase tracking-wider text-[#5B5B5B]"><span className="h-2.5 w-2.5 rounded-full" style={{ background: colorOf(selected.kind) }} />{selected.kind}</div>
                  <h3 className="mt-0.5 text-[15px] font-bold leading-snug text-[#161616]">{selected.name}</h3>
                </div>
                <button aria-label="Close details" onClick={() => setSelectedId(null)} className="rounded-[6px] p-1 text-[#8E8E8E] hover:bg-[#F4F3EE]"><X className="h-3.5 w-3.5" /></button>
              </div>
              {selected.validTo && <div className="mt-2 rounded-[6px] border border-[#B27000]/30 bg-[#FBF1DC] p-2 text-[11px] text-[#7A4D00]">No longer true since {when(selected.validTo)}{selected.supersededBy ? `; replaced by ${selected.supersededBy.split(':').slice(1).join(':')}` : ''}.</div>}
              {selected.text && <p className="mt-2 whitespace-pre-wrap text-[12.5px] leading-relaxed text-[#161616] select-text">{selected.text}</p>}
              <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5 text-[11px]">
                <dt className="text-[#5B5B5B]">Importance</dt><dd className="font-mono">{selected.importance} / 10</dd>
                <dt className="text-[#5B5B5B]">Mentioned</dt><dd className="font-mono">{selected.mentions}×</dd>
                <dt className="text-[#5B5B5B]">Written by</dt><dd>{selected.owner ?? 'noticed by the system'}</dd>
                <dt className="text-[#5B5B5B]">Last updated</dt><dd className="font-mono">{when(selected.updated)}</dd>
              </dl>
              {selected.tags.length > 0 && <div className="mt-2 flex flex-wrap gap-1">{selected.tags.map((t) => <span key={t} className="rounded-[3px] bg-[#F4F3EE] px-1.5 py-0.5 text-[10px] font-mono text-[#5B5B5B]">{t}</span>)}</div>}
              <div className="mt-4 text-[11px] font-bold uppercase tracking-wider text-[#5B5B5B]">Connected to ({links.length})</div>
              <ul className="mt-1.5 space-y-1">
                {links.map((l, i) => (
                  <li key={`${l.other.id}-${i}`}>
                    <button onClick={() => setSelectedId(l.other.id)} className="flex w-full items-center gap-2 rounded-[6px] px-1.5 py-1 text-left text-[11.5px] hover:bg-[#F4F3EE]">
                      <span className="font-mono text-[10px] text-[#8E8E8E]">{l.outgoing ? '→' : '←'} {l.relation}</span>
                      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: colorOf(l.other.kind) }} />
                      <span className="truncate text-[#161616]">{l.other.name}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <div>
              <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-[#5B5B5B]"><Sparkles className="h-3.5 w-3.5" />{scope === 'project' ? 'What the whole team knows' : `What ${scope} knows`}</div>
              <p className="mt-2 text-[11.5px] leading-relaxed text-[#5B5B5B]">
                {scope === 'project'
                  ? 'Every agent writes here, and reads from it before starting new work. Click a memory to see how it connects.'
                  : `${scope}'s own memory: its tasks, the files it touched, what it struggled with. Only ${scope} reads it.`}
              </p>
              <dl className="mt-3 grid grid-cols-2 gap-1.5 text-[11.5px]">
                <dt className="text-[#5B5B5B]">Memories</dt><dd className="font-mono">{data.stats.nodes ?? 0}</dd>
                <dt className="text-[#5B5B5B]">Links</dt><dd className="font-mono">{data.stats.edges ?? 0}</dd>
                <dt className="text-[#5B5B5B]">Replaced facts</dt><dd className="font-mono">{data.stats.replaced ?? 0}</dd>
              </dl>
              <div className="mt-4 text-[11px] font-bold uppercase tracking-wider text-[#5B5B5B]">Latest</div>
              <ul className="mt-1.5 space-y-1">
                {[...data.nodes].filter((n) => n.kind !== 'agent').sort((a, b) => b.updated - a.updated).slice(0, 8).map((n) => (
                  <li key={n.id}><button onClick={() => setSelectedId(n.id)} className="flex w-full items-center gap-2 rounded-[6px] px-1.5 py-1 text-left text-[11.5px] hover:bg-[#F4F3EE]"><span className="h-2 w-2 shrink-0 rounded-full" style={{ background: colorOf(n.kind) }} /><span className="truncate">{n.name}</span></button></li>
                ))}
              </ul>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
};
