import React from 'react';
import { tokens } from '../../theme/tokens';
import type { KgEdge, KgNode } from '../../api/client';
import { VIEW_SIZE, layoutGraph, shortLabel } from './layout';

interface GraphViewProps {
  nodes: KgNode[];
  edges: KgEdge[];
  centre?: string;
  selected?: string;
  highlight?: string[];
  onSelect?: (id: string) => void;
  title: string;
}

/**
 * Plain SVG node-link view.  Every label is rendered through React text nodes
 * (never innerHTML), nodes are focusable buttons, and the layout is a pure
 * function of the input so the picture is reproducible.
 */
export function GraphView({ nodes, edges, centre, selected, highlight, onSelect, title }: GraphViewProps) {
  const layout = layoutGraph(nodes, edges, centre);
  const marked = new Set(highlight ?? []);
  if (layout.nodes.length === 0) return null;
  return (
    <div data-testid="kg-graph-view">
      <svg
        role="group"
        aria-label={title}
        viewBox={`0 0 ${VIEW_SIZE} ${VIEW_SIZE}`}
        style={{ width: '100%', maxHeight: 520, background: tokens.colors.surfaceAlt, borderRadius: tokens.radii.sm }}
      >
        <defs>
          <marker id="kg-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill={tokens.colors.textMuted} />
          </marker>
        </defs>
        {layout.edges.map((e) => (
          <line
            key={e.key}
            x1={e.src.x}
            y1={e.src.y}
            x2={e.dst.x}
            y2={e.dst.y}
            stroke={tokens.colors.textMuted}
            strokeWidth={1}
            markerEnd="url(#kg-arrow)"
          >
            <title>{`${e.src.node.id} -[${e.relation}]-> ${e.dst.node.id}`}</title>
          </line>
        ))}
        {layout.nodes.map((l) => {
          const isSel = l.node.id === selected;
          const isMarked = marked.has(l.node.id);
          const activate = () => onSelect?.(l.node.id);
          return (
            <g
              key={l.node.id}
              role="button"
              tabIndex={0}
              aria-label={`${l.node.kind} ${l.node.id}`}
              aria-pressed={isSel}
              data-node-id={l.node.id}
              style={{ cursor: onSelect ? 'pointer' : 'default' }}
              onClick={activate}
              onKeyDown={(ev) => {
                if (ev.key === 'Enter' || ev.key === ' ') {
                  ev.preventDefault();
                  activate();
                }
              }}
            >
              <title>{l.node.id}</title>
              <circle
                cx={l.x}
                cy={l.y}
                r={isSel ? 10 : 7}
                fill={isSel ? tokens.colors.primary : isMarked ? tokens.colors.warning : tokens.colors.cardBg}
                stroke={isSel || isMarked ? tokens.colors.primaryHover : tokens.colors.accent}
                strokeWidth={2}
              />
              <text x={l.x} y={l.y + 22} textAnchor="middle" fontSize={10} fill={tokens.colors.textPrimary}>
                {shortLabel(l.node.id)}
              </text>
            </g>
          );
        })}
      </svg>
      {layout.hiddenNodes > 0 && (
        <div role="note" style={{ fontSize: tokens.font.sizes.xs, color: tokens.colors.textSecondary, marginTop: 4 }}>
          Showing {layout.nodes.length} nodes; {layout.hiddenNodes} more not drawn (view capped). Use the lists for the full set.
        </div>
      )}
    </div>
  );
}
