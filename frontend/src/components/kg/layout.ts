/** Deterministic, dependency-free layout for the knowledge-graph node-link view. */
import type { KgEdge, KgNode } from '../../api/client';
import { kgEdgeEndpoints } from '../../api/client';

/** Hard cap on nodes drawn; the rest are reported, never silently dropped. */
export const MAX_DRAWN_NODES = 60;
export const VIEW_SIZE = 640;
const RING_CAPACITY = 24;

export interface LaidNode {
  node: KgNode;
  x: number;
  y: number;
}
export interface LaidEdge {
  key: string;
  src: LaidNode;
  dst: LaidNode;
  relation: string;
}
export interface GraphLayout {
  nodes: LaidNode[];
  edges: LaidEdge[];
  hiddenNodes: number;
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

/**
 * Centre node in the middle, remaining nodes (sorted by id, so identical input
 * always yields identical output) on concentric rings.  Edges with an endpoint
 * outside the drawn set are skipped.
 */
export function layoutGraph(
  nodes: KgNode[],
  edges: KgEdge[],
  centre?: string,
  cap: number = MAX_DRAWN_NODES,
): GraphLayout {
  const sorted = [...nodes].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const centreNode = sorted.find((n) => n.id === centre);
  const rest = sorted.filter((n) => n !== centreNode);
  const keep = (centreNode ? [centreNode] : []).concat(rest).slice(0, Math.max(0, cap));
  const mid = VIEW_SIZE / 2;
  const ringNodes = centreNode ? keep.slice(1) : keep;
  const laid: LaidNode[] = [];
  if (centreNode && keep.length > 0) laid.push({ node: centreNode, x: mid, y: mid });
  ringNodes.forEach((node, placed) => {
    const ring = Math.floor(placed / RING_CAPACITY);
    const inRing = Math.min(RING_CAPACITY, ringNodes.length - ring * RING_CAPACITY);
    const radius = (mid - 70) * Math.min(1, 0.55 + 0.4 * ring + (centreNode ? 0 : 0.2));
    const angle = (2 * Math.PI * (placed % RING_CAPACITY)) / Math.max(1, inRing) - Math.PI / 2;
    laid.push({ node, x: round2(mid + radius * Math.cos(angle)), y: round2(mid + radius * Math.sin(angle)) });
  });
  const byId = new Map(laid.map((l) => [l.node.id, l]));
  const laidEdges: LaidEdge[] = [];
  edges.forEach((edge, i) => {
    const { src, dst } = kgEdgeEndpoints(edge);
    const a = byId.get(src);
    const b = byId.get(dst);
    if (a && b) {
      laidEdges.push({ key: `${i}:${src}>${dst}:${edge.relation}`, src: a, dst: b, relation: edge.relation });
    }
  });
  return { nodes: laid, edges: laidEdges, hiddenNodes: Math.max(0, sorted.length - keep.length) };
}

/** Group ids by kind (looked up, else the `kind:` prefix of the id), for the grouped impact list. */
export function groupByKind(ids: string[], kindOf?: (id: string) => string | undefined): [string, string[]][] {
  const groups = new Map<string, string[]>();
  for (const id of ids) {
    const colon = id.indexOf(':');
    const kind = kindOf?.(id) ?? (colon > 0 ? id.slice(0, colon) : 'other');
    groups.set(kind, [...(groups.get(kind) ?? []), id]);
  }
  return [...groups.entries()]
    .sort((a, b) => (a[0] < b[0] ? -1 : 1))
    .map(([kind, list]): [string, string[]] => [kind, [...list].sort()]);
}

/** Shorten a label for drawing; the full id stays in the accessible name and title. */
export function shortLabel(id: string, max = 22): string {
  return id.length <= max ? id : `${id.slice(0, max - 1)}…`;
}

/** `file:line:column` (line/column optional) for source traceability; '' when there is no file. */
export function formatSource(edge: Pick<KgEdge, 'file' | 'line' | 'column'>): string {
  if (!edge.file) return '';
  const parts = [edge.file];
  if (edge.line !== undefined && edge.line !== null) {
    parts.push(String(edge.line));
    if (edge.column !== undefined && edge.column !== null) parts.push(String(edge.column));
  }
  return parts.join(':');
}
