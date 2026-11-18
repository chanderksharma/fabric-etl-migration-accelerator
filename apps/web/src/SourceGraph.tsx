import { useMemo, useRef, useState } from "react";

import type { EvidenceNode, WorkflowEvidence } from "./evidence-types";
import { sourceGraphLayout } from "./workspace-model";

type NodeLayout = {
  x: number;
  y: number;
  width: number;
  height: number;
  isContainer: boolean;
};

function anchorRatio(anchor: string, side: "source" | "target") {
  const normalized = anchor.toLowerCase();
  if (normalized === "left") return side === "source" ? 0.25 : 0.35;
  if (normalized === "right") return side === "source" ? 0.75 : 0.65;
  if (normalized === "true") return 0.35;
  if (normalized === "false") return 0.65;
  if (normalized === "control") return 0.2;
  return 0.5;
}

function anchorPoint(
  layout: NodeLayout,
  anchor: string,
  side: "source" | "target",
) {
  return {
    x: side === "source" ? layout.x + layout.width : layout.x,
    y: layout.y + layout.height * anchorRatio(anchor, side),
  };
}

function edgePath(
  source: NodeLayout,
  target: NodeLayout,
  sourceAnchor: string,
  targetAnchor: string,
) {
  const start = anchorPoint(source, sourceAnchor, "source");
  const end = anchorPoint(target, targetAnchor, "target");
  if (end.x >= start.x) {
    const control = Math.max(24, (end.x - start.x) * 0.45);
    return `M${start.x} ${start.y} C${start.x + control} ${start.y} ${end.x - control} ${end.y} ${end.x} ${end.y}`;
  }
  const detour = Math.max(start.x, end.x) + 48;
  return `M${start.x} ${start.y} C${detour} ${start.y} ${detour} ${end.y} ${end.x} ${end.y}`;
}

function compactLabel(value: string, limit = 12) {
  return value.length > limit ? `${value.slice(0, limit - 1)}…` : value;
}

export function SourceGraph({graph}: {graph: WorkflowEvidence}) {
  const [zoom, setZoom] = useState(
    graph.layout_source === "source" ? 0.75 : 1,
  );
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<EvidenceNode | null>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const [cursor, setCursor] = useState(-1);
  const drag = useRef<{x: number; y: number; left: number; top: number} | null>(null);
  const {positions, minX, minY, width, height} = useMemo(
    () => sourceGraphLayout(graph),
    [graph],
  );
  const matches = useMemo(() => {
    const normalized = query.toLowerCase();
    return graph.nodes.filter(node =>
      `${node.id} ${node.name} ${node.label} ${node.support}`
        .toLowerCase()
        .includes(normalized)
    );
  }, [graph.nodes, query]);

  if (graph.parse_status === "failed") {
    return (
      <div role="alert" className="notice">
        Source graph unavailable: {graph.findings.join(" · ")}
      </div>
    );
  }

  function find() {
    if (!query || !matches.length) return;
    const next = (cursor + 1) % matches.length;
    setCursor(next);
    setSelected(matches[next]);
    document.getElementById(`source-tool-${matches[next].id}`)?.scrollIntoView({
      block: "nearest",
      inline: "nearest",
    });
  }

  return <>
    <div className="source-graph-toolbar">
      <div className="source-graph-search">
        <input
          aria-label="Find source workflow tool"
          placeholder="Find tool ID, name or mapping"
          value={query}
          onChange={event => {
            setQuery(event.target.value);
            setCursor(-1);
          }}
        />
      </div>
      <button onClick={find}>Find / next</button>
      <button
        aria-label="Zoom out source workflow graph"
        onClick={() => setZoom(Math.max(0.2, zoom - 0.2))}
      >
        −
      </button>
      <button
        aria-label="Zoom in source workflow graph"
        onClick={() => setZoom(Math.min(3, zoom + 0.2))}
      >
        +
      </button>
      <button onClick={() => setZoom(1)}>100%</button>
      <button onClick={() => setZoom(Math.max(
        0.2,
        Math.min(
          3,
          (viewport.current?.clientWidth ?? 760) / width,
          (viewport.current?.clientHeight ?? 420) / height,
        ),
      ))}>
        Fit to view
      </button>
      <span>{Math.round(zoom * 100)}%</span>
    </div>
    <p>
      {graph.node_count} tools · {graph.edge_count} connections ·{" "}
      {graph.layout_source === "source"
        ? "Source coordinates"
        : "Derived layout; source coordinates unavailable"}
    </p>
    {query && !matches.length && <p role="status">No matching source tools.</p>}
    <div
      className="source-graph-viewport"
      ref={viewport}
      onPointerDown={event => {
        if (
          event.button !== 0
          || !(event.target instanceof Element)
          || event.target.closest('[role="button"]')
        ) {
          return;
        }
        drag.current = {
          x: event.clientX,
          y: event.clientY,
          left: event.currentTarget.scrollLeft,
          top: event.currentTarget.scrollTop,
        };
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={event => {
        if (!drag.current) return;
        event.currentTarget.scrollLeft =
          drag.current.left - (event.clientX - drag.current.x);
        event.currentTarget.scrollTop =
          drag.current.top - (event.clientY - drag.current.y);
      }}
      onPointerUp={event => {
        drag.current = null;
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
          event.currentTarget.releasePointerCapture(event.pointerId);
        }
      }}
      onPointerCancel={() => {
        drag.current = null;
      }}
    >
      <svg
        width={width * zoom}
        height={height * zoom}
        viewBox={`${minX} ${minY} ${width} ${height}`}
        role="img"
        aria-label="Source workflow graph"
      >
        <defs>
          <marker
            id="sourceArrow"
            markerWidth="6"
            markerHeight="6"
            refX="5"
            refY="2.5"
            orient="auto"
          >
            <path d="M0,0 L0,5 L5,2.5 z" fill="var(--cp-border-strong)"/>
          </marker>
        </defs>
        {graph.nodes.map(node => {
          const position = positions.get(node.id);
          return position?.isContainer ? (
            <g
              key={`container-${node.id}`}
              id={`source-tool-${node.id}`}
              role="button"
              tabIndex={0}
              aria-label={`Tool ${node.id}: ${node.label || node.name}`}
              onClick={() => setSelected(node)}
              onKeyDown={event => {
                if (["Enter", " "].includes(event.key)) {
                  event.preventDefault();
                  setSelected(node);
                }
              }}
            >
              <rect
                className={
                  selected?.id === node.id
                    ? "source-container source-node-selected"
                    : "source-container"
                }
                x={position.x}
                y={position.y}
                width={position.width}
                height={position.height}
                rx="8"
              />
              <text
                className="source-container-label"
                x={position.x + 10}
                y={position.y + 18}
              >
                {compactLabel(node.label || node.name, 32)}
              </text>
            </g>
          ) : null;
        })}
        {graph.edges.map((edge, index) => {
          const source = positions.get(edge.source);
          const target = positions.get(edge.target);
          return source && target ? (
            <path
              key={index}
              className="graph-edge"
              markerEnd="url(#sourceArrow)"
              d={edgePath(
                source,
                target,
                edge.source_anchor,
                edge.target_anchor,
              )}
            />
          ) : null;
        })}
        {graph.nodes.map(node => {
          const position = positions.get(node.id);
          return position && !position.isContainer ? (
            <g
              key={node.id}
              id={`source-tool-${node.id}`}
              role="button"
              tabIndex={0}
              aria-label={`Tool ${node.id}: ${node.name}`}
              onClick={() => setSelected(node)}
              onKeyDown={event => {
                if (["Enter", " "].includes(event.key)) {
                  event.preventDefault();
                  setSelected(node);
                }
              }}
            >
              <rect
                className={`source-node-${node.support} ${
                  node.disabled ? "source-node-disabled " : ""
                }${
                  node.support === "manual"
                    ? "graph-node-risk"
                    : selected?.id === node.id
                      ? "graph-node-accent"
                      : "graph-node"
                }`}
                x={position.x}
                y={position.y}
                width={position.width}
                height={position.height}
                rx="6"
              />
              <title>
                Tool {node.id}: {node.label || node.name} · {node.plugin} · {node.support}
              </title>
              <text
                className="graph-label"
                x={position.x + position.width / 2}
                y={position.y + 17}
                textAnchor="middle"
              >
                {compactLabel(node.name)}
              </text>
              <text
                className="graph-sublabel"
                x={position.x + position.width / 2}
                y={position.y + 31}
                textAnchor="middle"
              >
                #{node.id}
              </text>
              {node.label && node.label !== node.name && (
                <text
                  className="graph-annotation"
                  x={position.x + position.width / 2}
                  y={position.y + position.height + 13}
                  textAnchor="middle"
                >
                  {compactLabel(node.label, 18)}
                </text>
              )}
            </g>
          ) : null;
        })}
      </svg>
    </div>
    <div className="source-graph-selection">
      {selected
        ? `Tool ${selected.id} · ${selected.label || selected.name} · ${selected.name} · ${selected.plugin} · ${selected.support}${selected.disabled ? " · disabled" : ""}`
        : "Select a tool to view its source metadata and mapping status."}
    </div>
    {graph.truncated && (
      <div className="notice">
        Graph view is capped at 500 tools and 1,000 connections. Counts describe the full graph.
      </div>
    )}
    <details>
      <summary>Text alternative: source tool register</summary>
      <ul>
        {graph.nodes.map(node => (
          <li key={node.id}>Tool {node.id}: {node.name} ({node.support})</li>
        ))}
      </ul>
    </details>
  </>;
}
