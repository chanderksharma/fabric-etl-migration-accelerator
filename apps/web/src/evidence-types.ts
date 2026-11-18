export type EvidenceNode = {
  id: string;
  name: string;
  label: string;
  plugin: string;
  support: string;
  disabled: boolean;
  x: number | null;
  y: number | null;
  width: number | null;
  height: number | null;
  expressions: string[];
  issues: string[];
};

export type WorkflowEvidence = {
  workflow_index: number;
  workflow_path: string;
  source_sha256: string;
  source_version: string | null;
  purpose: string | null;
  parse_status: "parsed" | "failed";
  layout_source: "source" | "derived";
  nodes: EvidenceNode[];
  edges: Array<{source: string; target: string; source_anchor: string; target_anchor: string}>;
  findings: string[];
  node_count: number;
  edge_count: number;
  truncated: boolean;
};

export type EvidenceResponse = {
  schema_version: string;
  graph_version: string;
  run_id: string;
  snapshot_id: string;
  total_workflows: number;
  workflows: WorkflowEvidence[];
  truncated: boolean;
};
