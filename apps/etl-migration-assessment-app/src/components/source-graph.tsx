import { useMemo, useRef, useState } from "react";

import type { QueryRecord } from "@/hooks/use-query-records";

type GraphNode = {
  id: string;
  name: string;
  label: string;
  plugin: string;
  support: string;
  disabled: boolean;
  x: number | null;
  y: number | null;
};

type GraphConnection = {
  source: string;
  target: string;
  sourceAnchor: string;
  targetAnchor: string;
};

type NodeLayout = {
  x: number;
  y: number;
  width: number;
  height: number;
};

const nodeWidth = 72;
const nodeHeight = 42;
const padding = 32;

function text(value: unknown): string {
  return value == null ? "" : String(value);
}

function number(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function normalizeNodes(records: QueryRecord[]): GraphNode[] {
  return records.map((record) => ({
    id: text(record.NodeId),
    name: text(record.NodeName) || "Unknown tool",
    label: text(record.NodeLabel),
    plugin: text(record.Plugin),
    support: text(record.SupportCategory).toLowerCase() || "manual",
    disabled: record.Disabled === true || text(record.Disabled).toLowerCase() === "true",
    x: number(record.X),
    y: number(record.Y),
  })).filter((node) => node.id);
}

function normalizeConnections(records: QueryRecord[]): GraphConnection[] {
  return records.map((record) => ({
    source: text(record.SourceNodeId),
    target: text(record.TargetNodeId),
    sourceAnchor: text(record.SourceAnchor),
    targetAnchor: text(record.TargetAnchor),
  })).filter((edge) => edge.source && edge.target);
}

function graphLayout(nodes: GraphNode[], edges: GraphConnection[]) {
  const hasSourceLayout = nodes.length > 0 && nodes.every(
    (node) => node.x !== null && node.y !== null,
  );
  if (hasSourceLayout) {
    const raw = nodes.map((node) => ({
      id: node.id,
      x: (node.x ?? 0) - nodeWidth / 2,
      y: (node.y ?? 0) - nodeHeight / 2,
      width: nodeWidth,
      height: nodeHeight,
    }));
    const minRawX = Math.min(...raw.map((position) => position.x));
    const minRawY = Math.min(...raw.map((position) => position.y));
    const positions = new Map(raw.map((position) => [
      position.id,
      {
        ...position,
        x: position.x + padding - minRawX,
        y: position.y + padding - minRawY,
      },
    ] as const));
    return graphBounds(positions, "source");
  }

  const level = new Map(nodes.map((node) => [node.id, 0]));
  for (let pass = 0; pass < nodes.length; pass += 1) {
    let changed = false;
    for (const edge of edges) {
      if (!level.has(edge.source) || !level.has(edge.target)) continue;
      const next = (level.get(edge.source) ?? 0) + 1;
      if (next > (level.get(edge.target) ?? 0)) {
        level.set(edge.target, next);
        changed = true;
      }
    }
    if (!changed) break;
  }
  const columns = new Map<number, number>();
  const positions = new Map(nodes.map((node) => {
    const depth = level.get(node.id) ?? 0;
    const row = columns.get(depth) ?? 0;
    columns.set(depth, row + 1);
    return [
      node.id,
      {
        x: padding + depth * 190,
        y: padding + row * 104,
        width: nodeWidth,
        height: nodeHeight,
      },
    ] as const;
  }));
  return graphBounds(positions, "derived");
}

function graphBounds(
  positions: Map<string, NodeLayout>,
  source: "source" | "derived",
) {
  return {
    positions,
    source,
    width: Math.max(
      760,
      ...[...positions.values()].map((position) =>
        position.x + position.width + padding
      ),
    ),
    height: Math.max(
      360,
      ...[...positions.values()].map((position) =>
        position.y + position.height + padding
      ),
    ),
  };
}

function anchorRatio(anchor: string, side: "source" | "target") {
  const normalized = anchor.toLowerCase();
  if (normalized === "left") return side === "source" ? 0.25 : 0.35;
  if (normalized === "right") return side === "source" ? 0.75 : 0.65;
  if (normalized === "true") return 0.35;
  if (normalized === "false") return 0.65;
  if (normalized === "control") return 0.2;
  return 0.5;
}

function edgePath(
  source: NodeLayout,
  target: NodeLayout,
  sourceAnchor: string,
  targetAnchor: string,
) {
  const startX = source.x + source.width;
  const startY = source.y + source.height * anchorRatio(sourceAnchor, "source");
  const endX = target.x;
  const endY = target.y + target.height * anchorRatio(targetAnchor, "target");
  if (endX >= startX) {
    const control = Math.max(28, (endX - startX) * 0.45);
    return `M${startX} ${startY} C${startX + control} ${startY} ${
      endX - control
    } ${endY} ${endX} ${endY}`;
  }
  const detour = Math.max(startX, endX) + 58;
  return `M${startX} ${startY} C${detour} ${startY} ${detour} ${endY} ${endX} ${endY}`;
}

function compact(value: string, limit: number) {
  return value.length > limit ? `${value.slice(0, limit - 1)}…` : value;
}

function supportLabel(value: string) {
  const labels: Record<string, string> = {
    dataflow: "Dataflow",
    notebook: "Notebook",
    pipeline: "Pipeline",
    manual: "Manual redesign",
    unsupported: "Unsupported",
    neutral: "Annotation",
  };
  return labels[value] ?? (value || "Needs review");
}

export function SourceGraph({
  nodes: nodeRecords,
  connections: connectionRecords,
}: {
  nodes: QueryRecord[];
  connections: QueryRecord[];
}) {
  const nodes = useMemo(() => normalizeNodes(nodeRecords), [nodeRecords]);
  const connections = useMemo(
    () => normalizeConnections(connectionRecords),
    [connectionRecords],
  );
  const containerNodes = useMemo(
    () => nodes.filter((node) => node.name.toLowerCase().includes("toolcontainer")),
    [nodes],
  );
  const visualNodes = useMemo(
    () => nodes.filter((node) => !node.name.toLowerCase().includes("toolcontainer")),
    [nodes],
  );
  const visualNodeIds = useMemo(
    () => new Set(visualNodes.map((node) => node.id)),
    [visualNodes],
  );
  const visibleConnections = useMemo(
    () => connections.filter(
      (connection) =>
        visualNodeIds.has(connection.source) && visualNodeIds.has(connection.target),
    ),
    [connections, visualNodeIds],
  );
  const { positions, width, height, source } = useMemo(
    () => graphLayout(visualNodes, visibleConnections),
    [visibleConnections, visualNodes],
  );
  const [zoom, setZoom] = useState(source === "source" ? 0.75 : 1);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(-1);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const matches = useMemo(() => {
    const normalized = query.toLowerCase();
    return visualNodes.filter((node) =>
      `${node.id} ${node.name} ${node.label} ${node.plugin} ${node.support}`
        .toLowerCase()
        .includes(normalized)
    );
  }, [query, visualNodes]);

  if (!visualNodes.length) {
    return <p className="text-200 text-muted-foreground">No source tools to draw.</p>;
  }

  function findNext() {
    if (!query || !matches.length) return;
    const next = (cursor + 1) % matches.length;
    setCursor(next);
    setSelected(matches[next]);
    const element = document.getElementById(`fabric-source-tool-${matches[next].id}`);
    element?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          aria-label="Find source workflow tool"
          className="min-w-60 flex-1 rounded-lg border bg-background px-3 py-2 text-200"
          placeholder="Find tool ID, name, label, plugin, or mapping"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setCursor(-1);
          }}
        />
        <button type="button" className="source-graph-button" onClick={findNext}>
          Find / next
        </button>
        <button
          type="button"
          className="source-graph-button"
          aria-label="Zoom out source workflow graph"
          onClick={() => setZoom(Math.max(0.2, zoom - 0.2))}
        >
          −
        </button>
        <button
          type="button"
          className="source-graph-button"
          aria-label="Zoom in source workflow graph"
          onClick={() => setZoom(Math.min(3, zoom + 0.2))}
        >
          +
        </button>
        <button type="button" className="source-graph-button" onClick={() => setZoom(1)}>
          100%
        </button>
        <button
          type="button"
          className="source-graph-button"
          onClick={() => setZoom(Math.max(
            0.2,
            Math.min(
              3,
              (viewport.current?.clientWidth ?? 760) / width,
              (viewport.current?.clientHeight ?? 420) / height,
            ),
          ))}
        >
          Fit to view
        </button>
        <span className="text-200 text-muted-foreground">{Math.round(zoom * 100)}%</span>
      </div>
      <p className="text-200 text-muted-foreground">
        {nodes.length} tools · {connections.length} connections ·{" "}
        {source === "source" ? "source coordinates" : "derived layout"}
      </p>
      {containerNodes.length > 0 && (
        <p className="text-200 text-muted-foreground">
          {containerNodes.length} container{containerNodes.length === 1 ? "" : "s"} listed in the
          tool register but omitted from the canvas because boundary dimensions are not persisted.
        </p>
      )}
      {query && !matches.length && (
        <p className="text-200 text-muted-foreground" role="status">
          No matching source tools.
        </p>
      )}
      <div
        className="source-graph-viewport"
        ref={viewport}
        onPointerDown={(event) => {
          if (
            event.button !== 0 ||
            !(event.target instanceof Element) ||
            event.target.closest('[role="button"]')
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
        onPointerMove={(event) => {
          if (!drag.current) return;
          event.currentTarget.scrollLeft =
            drag.current.left - (event.clientX - drag.current.x);
          event.currentTarget.scrollTop =
            drag.current.top - (event.clientY - drag.current.y);
        }}
        onPointerUp={(event) => {
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
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label="Source workflow graph"
        >
          <defs>
            <marker
              id="fabricSourceArrow"
              markerWidth="7"
              markerHeight="7"
              refX="6"
              refY="3"
              orient="auto"
            >
              <path d="M0,0 L0,6 L6,3 z" className="source-graph-arrow" />
            </marker>
          </defs>
          {visibleConnections.map((connection, index) => {
            const from = positions.get(connection.source);
            const to = positions.get(connection.target);
            return from && to ? (
              <path
                key={`${connection.source}-${connection.target}-${index}`}
                className="source-graph-edge"
                markerEnd="url(#fabricSourceArrow)"
                d={edgePath(
                  from,
                  to,
                  connection.sourceAnchor,
                  connection.targetAnchor,
                )}
              />
            ) : null;
          })}
          {visualNodes.map((node) => {
            const position = positions.get(node.id);
            if (!position) return null;
            const selectedClass = selected?.id === node.id ? " is-selected" : "";
            return (
              <g
                key={node.id}
                id={`fabric-source-tool-${node.id}`}
                role="button"
                tabIndex={0}
                aria-label={`Tool ${node.id}: ${node.label || node.name}`}
                className={`source-graph-node support-${node.support}${
                  node.disabled ? " is-disabled" : ""
                }${selectedClass}`}
                onClick={() => setSelected(node)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setSelected(node);
                  }
                }}
              >
                <rect
                  x={position.x}
                  y={position.y}
                  width={position.width}
                  height={position.height}
                  rx="8"
                />
                <title>
                  Tool {node.id}: {node.label || node.name} · {node.plugin} ·{" "}
                  {supportLabel(node.support)}
                </title>
                <text
                  className="source-graph-label"
                  x={position.x + position.width / 2}
                  y={position.y + 17}
                  textAnchor="middle"
                >
                  {compact(node.name, 12)}
                </text>
                <text
                  className="source-graph-sublabel"
                  x={position.x + position.width / 2}
                  y={position.y + 31}
                  textAnchor="middle"
                >
                  #{compact(node.id, 8)} · {compact(supportLabel(node.support), 12)}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <div className="rounded-lg border bg-muted/40 p-3 text-200">
        {selected ? (
          <>
            <strong>{selected.label || selected.name}</strong>
            <span className="text-muted-foreground">
              {" "}· Tool {selected.id} · {selected.name} ·{" "}
              {selected.plugin || "plugin not recorded"} · {supportLabel(selected.support)}
              {selected.disabled ? " · disabled" : ""}
            </span>
          </>
        ) : (
          <span className="text-muted-foreground">
            Select a tool to inspect its source metadata and mapping status.
          </span>
        )}
      </div>
      <details className="text-200">
        <summary className="cursor-pointer font-semibold">
          Text alternative: source tool register
        </summary>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
          {nodes.map((node) => (
            <li key={node.id}>
              Tool {node.id}: {node.label || node.name} ({supportLabel(node.support)})
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
