import type { AssessmentResult } from "./App";
import type { EvidenceNode, EvidenceResponse, WorkflowEvidence } from "./evidence-types";

export type AssessmentItem = AssessmentResult["assessments"][number];

export const evidenceTabs = [
  "Tools",
  "Expressions",
  "Inputs & outputs",
  "Dependencies",
  "Findings",
  "Connections",
] as const;

export const waveDefinitions = [
  {value: "Wave 1", label: "Wave 1"},
  {value: "Pilot", label: "Wave 2"},
  {value: "Wave 2", label: "Wave 3"},
  {value: "Redesign", label: "Wave 4"},
] as const;

const supportDetails: Record<string, {mapping: string; target: string}> = {
  dataflow: {mapping: "Rewrite in Fabric", target: "Dataflow Gen2"},
  notebook: {mapping: "Requires new implementation", target: "Fabric Notebook"},
  pipeline: {mapping: "Rewrite in Fabric", target: "Fabric Data Pipeline"},
  manual: {mapping: "Requires new implementation", target: "Manual redesign"},
  neutral: {mapping: "No equivalent needed", target: "Documentation"},
};

export const evidenceColumns = [
  ["Workflow", "Tool ID", "Tool", "Category", "Mapping", "Fabric target", "Operation", "Disabled"],
  ["Workflow", "Tool ID", "Tool", "Source expression", "Mapping guidance"],
  ["Workflow", "Direction", "Technology", "Location"],
  ["Workflow", "Type", "Reference", "Source tool", "Portable", "Sensitive"],
  ["Workflow", "Tool", "Category", "Severity", "Evidence / action"],
  ["Workflow", "From tool", "From anchor", "To tool", "To anchor", "Condition"],
] as const;

export function statusClass(value: string) {
  return value === "Low" ? "ready" : value === "Medium" ? "review" : "redesign";
}

export function platformLabel(platform?: string) {
  if (platform === "informatica_powercenter") return "PowerCenter";
  if (platform === "informatica_idmc") return "IDMC";
  return "Alteryx";
}

export function supportDetail(value: string) {
  return supportDetails[value] ?? {
    mapping: "Requires review",
    target: "Target not determined",
  };
}

export function nodeCategory(node: EvidenceNode) {
  const operation = node.name.toLowerCase();
  if (node.support === "neutral") return "Annotation";
  if (/(input|textinput|download)/.test(operation)) return "Input";
  if (/(output|browse|render)/.test(operation)) return "Output";
  if (/(join|union|append|merge|crosstab|transpose)/.test(operation)) return "Join";
  if (node.support === "pipeline" || /(container|detour|message|email)/.test(operation)) {
    return "Control";
  }
  if (node.support === "notebook") return "Advanced";
  return "Preparation";
}

export function graphShape(graph: WorkflowEvidence | undefined) {
  if (!graph || graph.parse_status === "failed") {
    return {branches: 0, depth: 0, containers: 0, cycles: false};
  }
  const outgoing = new Map(graph.nodes.map(node => [node.id, [] as string[]]));
  const indegree = new Map(graph.nodes.map(node => [node.id, 0]));
  for (const edge of graph.edges) {
    if (!outgoing.has(edge.source) || !indegree.has(edge.target)) continue;
    outgoing.get(edge.source)?.push(edge.target);
    indegree.set(edge.target, (indegree.get(edge.target) ?? 0) + 1);
  }
  const queue = graph.nodes.filter(node => indegree.get(node.id) === 0).map(node => node.id);
  const depth = new Map(graph.nodes.map(node => [node.id, 1]));
  let processed = 0;
  while (queue.length) {
    const source = queue.shift();
    if (!source) continue;
    processed += 1;
    for (const target of outgoing.get(source) ?? []) {
      depth.set(target, Math.max(depth.get(target) ?? 1, (depth.get(source) ?? 1) + 1));
      indegree.set(target, (indegree.get(target) ?? 1) - 1);
      if (indegree.get(target) === 0) queue.push(target);
    }
  }
  return {
    branches: [...outgoing.values()].filter(targets => targets.length > 1).length,
    depth: Math.max(0, ...depth.values()),
    containers: graph.nodes.filter(node => node.name.toLowerCase().includes("container")).length,
    cycles: processed < graph.nodes.length,
  };
}

export function reviewPriority(value: number, medium: number, high: number) {
  return value >= high ? "High" : value >= medium ? "Medium" : "Low";
}

export function waveLabel(value: string) {
  return waveDefinitions.find(wave => wave.value === value)?.label ?? value;
}

export function nameOf(path: string) {
  return (path.split(/[\\/!]/).at(-1) ?? path).replace(/\.(yxmd|yxmc|yxwz|xml)$/i, "");
}

export function githubRepository(value: string) {
  try {
    const url = new URL(value);
    const parts = url.pathname.replace(/\.git$/i, "").split("/").filter(Boolean);
    if (
      url.protocol !== "https:"
      || url.hostname.toLowerCase() !== "github.com"
      || parts.length !== 2
    ) {
      return null;
    }
    return `${parts[0]}/${parts[1]}`;
  } catch {
    return null;
  }
}

export function gitlabProject(value: string) {
  try {
    const url = new URL(value);
    const parts = url.pathname.replace(/\/$/, "").replace(/\.git$/i, "")
      .split("/").filter(Boolean);
    if (
      url.protocol !== "https:"
      || url.username
      || url.password
      || url.search
      || url.hash
      || parts.length < 2
      || parts.some(part => !/^[A-Za-z0-9_.-]+$/.test(part))
    ) {
      return null;
    }
    return parts.join("/");
  } catch {
    return null;
  }
}

export function toolMappingRows(items: AssessmentItem[]) {
  const counts = {
    rewrite: 0,
    implementation: 0,
    neutral: 0,
  };
  for (const tool of items.flatMap(item => item.tools ?? [])) {
    if (["dataflow", "pipeline"].includes(tool.support)) counts.rewrite += tool.count;
    else if (["notebook", "manual"].includes(tool.support)) counts.implementation += tool.count;
    else if (tool.support === "neutral") counts.neutral += tool.count;
  }
  return [
    {name: "Rewrite in Fabric", value: counts.rewrite},
    {name: "Requires new implementation", value: counts.implementation},
    {name: "No equivalent needed", value: counts.neutral},
  ];
}

export function summarizeWaves(items: AssessmentItem[], targets: string[]) {
  const byWave = new Map<string, {
    count: number;
    effort: number;
    targets: Map<string, number>;
  }>(waveDefinitions.map(wave => [
    wave.value,
    {count: 0, effort: 0, targets: new Map(targets.map(target => [target, 0]))},
  ]));
  for (const item of items) {
    const summary = byWave.get(item.migration_wave);
    if (!summary) continue;
    summary.count += 1;
    summary.effort += item.estimated_effort_days;
    summary.targets.set(
      item.recommended_target,
      (summary.targets.get(item.recommended_target) ?? 0) + 1,
    );
  }
  return waveDefinitions.map(wave => {
    const summary = byWave.get(wave.value);
    return {
      ...wave,
      count: summary?.count ?? 0,
      effort: summary?.effort ?? 0,
      targetSummary: targets.map(target => `${summary?.targets.get(target) ?? 0} ${target}`).join(" · "),
    };
  });
}

export function buildEvidenceRows(
  tab: number,
  data: EvidenceResponse | null,
  items: AssessmentItem[],
) {
  if (tab === 0) {
    return data?.workflows.flatMap(workflow => workflow.nodes.map(node => {
      const support = supportDetail(node.support);
      return [
        workflow.workflow_path,
        node.id,
        node.name,
        nodeCategory(node),
        support.mapping,
        support.target,
        node.name,
        node.disabled ? "Yes" : "No",
      ];
    })) ?? [];
  }
  if (tab === 1) {
    return data?.workflows.flatMap(workflow => workflow.nodes.flatMap(node =>
      node.expressions.map(value => [
        workflow.workflow_path,
        node.id,
        node.name,
        value,
        supportDetail(node.support).mapping,
      ])
    )) ?? [];
  }
  if (tab === 2) {
    return items.flatMap(item => item.data_sources.map(value => {
      const extension = /\.[a-z0-9]{1,8}$/i.test(value) ? value.split(".").at(-1)?.toUpperCase() : null;
      return [
        item.path,
        "Referenced endpoint",
        extension ?? (item.source_platform?.startsWith("informatica_") ? "Table / Endpoint" : "Endpoint"),
        value,
      ];
    }));
  }
  if (tab === 3) {
    return items.flatMap(item => item.dependencies.map(value => [
      item.path,
      /\.yxmc$/i.test(value) ? "Macro reference" : "Dependency reference",
      value,
      "Not captured",
      /^[a-z]:[\\/]|^\\\\/i.test(value) ? "Review required" : "Unverified",
      /(password|pwd|token|secret|accountkey|bearer)/i.test(value)
        ? "Review required"
        : "No static indicator",
    ]));
  }
  if (tab === 4) {
    return items.flatMap(item => item.unsupported_tools.map(value => [
      item.path,
      value,
      "Compatibility",
      "High",
      `${value}: explicit redesign required`,
    ])).concat(data?.workflows.flatMap(workflow => workflow.findings.map(value => [
      workflow.workflow_path,
      "Workflow",
      "Static finding",
      "Medium",
      value,
    ])) ?? []);
  }
  if (tab === 5) {
    return data?.workflows.flatMap(workflow => workflow.edges.map(edge => [
      workflow.workflow_path,
      edge.source,
      edge.source_anchor,
      edge.target,
      edge.target_anchor,
      "Not captured",
    ])) ?? [];
  }
  return [];
}

export function sourceGraphLayout(graph: WorkflowEvidence) {
  const nodeWidth = 72;
  const nodeHeight = 42;
  const padding = 32;
  const hasSourceLayout = graph.layout_source === "source";
  if (hasSourceLayout) {
    const raw = graph.nodes.map(node => {
      const isContainer = node.name.toLowerCase().includes("toolcontainer")
        && node.width !== null
        && node.height !== null;
      const width = isContainer ? node.width ?? nodeWidth : nodeWidth;
      const height = isContainer ? node.height ?? nodeHeight : nodeHeight;
      return {
        id: node.id,
        x: isContainer ? node.x ?? 0 : (node.x ?? 0) - width / 2,
        y: isContainer ? node.y ?? 0 : (node.y ?? 0) - height / 2,
        width,
        height,
        isContainer,
      };
    });
    const rawMinX = Math.min(...raw.map(position => position.x));
    const rawMinY = Math.min(...raw.map(position => position.y));
    const offsetX = padding - rawMinX;
    const offsetY = padding - rawMinY;
    const positions = new Map(raw.map(position => [
      position.id,
      {
        ...position,
        x: position.x + offsetX,
        y: position.y + offsetY,
      },
    ] as const));
    return {
      positions,
      minX: 0,
      minY: 0,
      width: Math.max(
        760,
        ...[...positions.values()].map(position =>
          position.x + position.width + padding
        ),
      ),
      height: Math.max(
        330,
        ...[...positions.values()].map(position =>
          position.y + position.height + padding
        ),
      ),
    };
  }

  const level = new Map(graph.nodes.map(node => [node.id, 0]));
  for (let pass = 0; pass < graph.nodes.length; pass += 1) {
    let changed = false;
    for (const edge of graph.edges) {
      const value = (level.get(edge.source) ?? 0) + 1;
      if (value > (level.get(edge.target) ?? 0)) {
        level.set(edge.target, value);
        changed = true;
      }
    }
    if (!changed) break;
  }
  const columns = new Map<number, number>();
  const positions = new Map(graph.nodes.map(node => {
    const depth = level.get(node.id) ?? 0;
    const row = columns.get(depth) ?? 0;
    columns.set(depth, row + 1);
    return [
      node.id,
      {
        x: padding + depth * 140,
        y: padding + row * 86,
        width: nodeWidth,
        height: nodeHeight,
        isContainer: false,
      },
    ] as const;
  }));
  return {
    positions,
    minX: 0,
    minY: 0,
    width: Math.max(
      760,
      ...[...positions.values()].map(position =>
        position.x + position.width + padding
      ),
    ),
    height: Math.max(
      330,
      ...[...positions.values()].map(position =>
        position.y + position.height + padding
      ),
    ),
  };
}
