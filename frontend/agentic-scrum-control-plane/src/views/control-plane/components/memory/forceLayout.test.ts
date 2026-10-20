import { describe, expect, it } from 'vitest';
import { layoutGraph } from './forceLayout';

const dist = (a: { x: number; y: number }, b: { x: number; y: number }) => Math.hypot(a.x - b.x, a.y - b.y);

describe('layoutGraph', () => {
  const nodes = ['a', 'b', 'c', 'd', 'x', 'y'].map((id) => ({ id, r: 8 }));
  const links = [{ source: 'a', target: 'b' }, { source: 'b', target: 'c' }, { source: 'c', target: 'd' }, { source: 'x', target: 'y' }];

  it('keeps every node inside the drawing', () => {
    const placed = layoutGraph(nodes, links, new Map(), 900, 640);
    expect(placed.size).toBe(nodes.length);
    for (const p of placed.values()) {
      expect(p.x).toBeGreaterThan(0);
      expect(p.x).toBeLessThan(900);
      expect(p.y).toBeGreaterThan(0);
      expect(p.y).toBeLessThan(640);
    }
  });

  it('draws linked nodes closer together than unlinked ones', () => {
    const placed = layoutGraph(nodes, links, new Map(), 900, 640);
    const get = (id: string) => placed.get(id)!;
    expect(dist(get('a'), get('b'))).toBeLessThan(dist(get('a'), get('y')));
    expect(dist(get('x'), get('y'))).toBeLessThan(dist(get('x'), get('d')));
  });

  it('does not move what is already drawn much when a new memory arrives, and puts the newcomer beside what it is linked to', () => {
    const first = layoutGraph(nodes, links, new Map(), 900, 640);
    const more = [...nodes, { id: 'e', r: 8 }];
    const second = layoutGraph(more, [...links, { source: 'd', target: 'e' }], first, 900, 640);
    expect(dist(first.get('a')!, second.get('a')!)).toBeLessThan(120);
    expect(dist(second.get('d')!, second.get('e')!)).toBeLessThan(dist(second.get('a')!, second.get('e')!));
  });

  it('copes with nothing, one node, and links to nodes that are not shown', () => {
    expect(layoutGraph([], [], new Map()).size).toBe(0);
    expect(layoutGraph([{ id: 'only', r: 8 }], [{ source: 'only', target: 'gone' }], new Map()).size).toBe(1);
  });
});
