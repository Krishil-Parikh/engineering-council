/** A small force-directed layout for the memory graph: linked nodes pull together, every pair pushes apart, a weak pull to the centre keeps it in view.
 *  Positions of nodes already drawn are kept, so the graph does not jump when new memories arrive. */

export interface LayoutInput {
  id: string;
  r: number;
}

export interface LayoutLink {
  source: string;
  target: string;
  weight?: number;
}

export interface Point {
  x: number;
  y: number;
}

function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 4294967295;
}

export function layoutGraph(
  nodes: LayoutInput[],
  links: LayoutLink[],
  previous: ReadonlyMap<string, Point> = new Map(),
  width = 900,
  height = 640,
  iterations = 140,
  padding = 64,
): Map<string, Point> {
  const cx = width / 2;
  const cy = height / 2;
  const index = new Map(nodes.map((n, i) => [n.id, i]));
  const px = new Float64Array(nodes.length);
  const py = new Float64Array(nodes.length);
  const fixedStart: boolean[] = [];

  // a node already placed stays where it was; a new one starts beside a neighbour that is placed (else on a ring, by a hash of its name)
  const neighbour = new Map<string, string>();
  for (const l of links) {
    if (!neighbour.has(l.source)) neighbour.set(l.source, l.target);
    if (!neighbour.has(l.target)) neighbour.set(l.target, l.source);
  }
  nodes.forEach((n, i) => {
    const known = previous.get(n.id);
    if (known) {
      px[i] = known.x;
      py[i] = known.y;
      fixedStart[i] = true;
      return;
    }
    const near = neighbour.get(n.id);
    const nearPoint = near ? previous.get(near) : undefined;
    const angle = hash(n.id) * Math.PI * 2;
    if (nearPoint) {
      px[i] = nearPoint.x + Math.cos(angle) * 40;
      py[i] = nearPoint.y + Math.sin(angle) * 40;
    } else {
      const radius = 80 + hash(`${n.id}#`) * Math.min(width, height) * 0.38;
      px[i] = cx + Math.cos(angle) * radius;
      py[i] = cy + Math.sin(angle) * radius;
    }
  });

  const edges = links
    .map((l) => ({ a: index.get(l.source), b: index.get(l.target), w: l.weight ?? 1 }))
    .filter((e): e is { a: number; b: number; w: number } => e.a !== undefined && e.b !== undefined && e.a !== e.b);

  const k = Math.sqrt(((width - padding * 2) * (height - padding * 2)) / Math.max(1, nodes.length)) * 0.55; // the distance linked nodes settle at
  const fresh = fixedStart.filter(Boolean).length < nodes.length * 0.5; // most nodes are new: let it move a lot, else just settle the newcomers
  let temperature = fresh ? width / 8 : width / 40;

  for (let step = 0; step < iterations; step += 1) {
    const dx = new Float64Array(nodes.length);
    const dy = new Float64Array(nodes.length);
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        let ox = px[i] - px[j];
        let oy = py[i] - py[j];
        let dist2 = ox * ox + oy * oy;
        if (dist2 < 0.01) {
          ox = hash(nodes[i].id) - 0.5;
          oy = hash(nodes[j].id) - 0.5;
          dist2 = ox * ox + oy * oy + 0.01;
        }
        const dist = Math.sqrt(dist2);
        const force = (k * k) / dist; // repulsion
        const fx = (ox / dist) * force;
        const fy = (oy / dist) * force;
        dx[i] += fx;
        dy[i] += fy;
        dx[j] -= fx;
        dy[j] -= fy;
      }
    }
    for (const e of edges) {
      const ox = px[e.a] - px[e.b];
      const oy = py[e.a] - py[e.b];
      const dist = Math.sqrt(ox * ox + oy * oy) || 0.01;
      const force = ((dist * dist) / k) * Math.min(2, 0.6 + e.w * 0.4); // attraction
      const fx = (ox / dist) * force;
      const fy = (oy / dist) * force;
      dx[e.a] -= fx;
      dy[e.a] -= fy;
      dx[e.b] += fx;
      dy[e.b] += fy;
    }
    for (let i = 0; i < nodes.length; i += 1) {
      dx[i] += (cx - px[i]) * 0.09; // gravity
      dy[i] += (cy - py[i]) * 0.09;
      const move = Math.sqrt(dx[i] * dx[i] + dy[i] * dy[i]) || 0.01;
      const limited = Math.min(move, temperature);
      px[i] += (dx[i] / move) * limited;
      py[i] += (dy[i] / move) * limited;
      px[i] = Math.max(nodes[i].r + padding, Math.min(width - nodes[i].r - padding, px[i]));
      py[i] = Math.max(nodes[i].r + padding * 0.6, Math.min(height - nodes[i].r - padding * 0.6, py[i]));
    }
    temperature *= 0.97;
  }

  return new Map(nodes.map((n, i) => [n.id, { x: px[i], y: py[i] }]));
}
