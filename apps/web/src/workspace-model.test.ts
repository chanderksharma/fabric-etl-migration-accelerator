import { expect, test } from "vitest";

import type { EvidenceResponse, WorkflowEvidence } from "./evidence-types";
import {
  buildEvidenceRows,
  gitlabProject,
  graphShape,
  nameOf,
  sourceGraphLayout,
  summarizeWaves,
  toolMappingRows,
  type AssessmentItem,
} from "./workspace-model";

test("parses nested GitLab project URLs", () => {
  expect(gitlabProject("https://gitlab.com/group/subgroup/project.git")).toBe(
    "group/subgroup/project",
  );
  expect(gitlabProject("https://gitlab.example.com/group/project")).toBe(
    "group/project",
  );
  expect(gitlabProject("group/project")).toBeNull();
  expect(gitlabProject("https://gitlab.com/project")).toBeNull();
});

function item(overrides: Partial<AssessmentItem> = {}): AssessmentItem {
  return {
    path: "orders.yxmd",
    tool_count: 2,
    connection_count: 1,
    complexity_score: 3,
    complexity_band: "Low",
    recommended_target: "Dataflow Gen2",
    recommendation_reason: "Reviewed candidate",
    unsupported_tools: [],
    migration_wave: "Wave 1",
    estimated_effort_days: 1,
    dependencies: [],
    data_sources: ["orders.csv"],
    graph_schema_version: "1.2.0",
    tools: [
      {name: "Filter", count: 2, support: "dataflow"},
      {name: "Comment", count: 1, support: "neutral"},
    ],
    ...overrides,
  };
}

const graph: WorkflowEvidence = {
  workflow_index: 0,
  workflow_path: "orders.yxmd",
  source_sha256: "a",
  source_version: "2024.1",
  purpose: "Validate orders",
  parse_status: "parsed",
  layout_source: "derived",
  nodes: [
    {
      id: "1",
      name: "TextInput",
      label: "Orders",
      plugin: "TextInput",
      support: "dataflow",
      disabled: false,
      x: null,
      y: null,
      width: null,
      height: null,
      expressions: [],
      issues: [],
    },
    {
      id: "2",
      name: "Filter",
      label: "Positive amount",
      plugin: "Filter",
      support: "dataflow",
      disabled: false,
      x: null,
      y: null,
      width: null,
      height: null,
      expressions: ["[Amount] > 0"],
      issues: [],
    },
  ],
  edges: [{source: "1", target: "2", source_anchor: "Output", target_anchor: "Input"}],
  findings: ["Review expression parity"],
  node_count: 2,
  edge_count: 1,
  truncated: false,
};

const evidence: EvidenceResponse = {
  schema_version: "1.1.0",
  graph_version: "1.2.0",
  run_id: "run",
  snapshot_id: "snapshot",
  total_workflows: 1,
  workflows: [graph],
  truncated: false,
};

test("summarizes internal wave values into four presentation waves", () => {
  const summaries = summarizeWaves([
    item(),
    item({
      path: "pilot.yxmd",
      migration_wave: "Pilot",
      recommended_target: "Fabric Notebook",
      estimated_effort_days: 2,
    }),
  ], ["Dataflow Gen2", "Fabric Notebook"]);

  expect(summaries.map(summary => summary.label)).toEqual([
    "Wave 1",
    "Wave 2",
    "Wave 3",
    "Wave 4",
  ]);
  expect(summaries[0]).toMatchObject({count: 1, effort: 1});
  expect(summaries[1]).toMatchObject({count: 1, effort: 2});
});

test("aggregates tool mappings once for portfolio and workflow views", () => {
  expect(toolMappingRows([item()])).toEqual([
    {name: "Rewrite in Fabric", value: 2},
    {name: "Requires new implementation", value: 0},
    {name: "No equivalent needed", value: 1},
  ]);
});

test("builds each evidence register from one shared row model", () => {
  expect(buildEvidenceRows(0, evidence, [item()])[0]).toEqual([
    "orders.yxmd",
    "1",
    "TextInput",
    "Input",
    "Rewrite in Fabric",
    "Dataflow Gen2",
    "TextInput",
    "No",
  ]);
  expect(buildEvidenceRows(1, evidence, [item()])).toHaveLength(1);
  expect(buildEvidenceRows(2, evidence, [item()])).toHaveLength(1);
  expect(buildEvidenceRows(4, evidence, [item()])).toHaveLength(1);
  expect(buildEvidenceRows(5, evidence, [item()])).toHaveLength(1);
});

test("derives graph shape and layout without React render state", () => {
  expect(graphShape(graph)).toEqual({
    branches: 0,
    depth: 2,
    containers: 0,
    cycles: false,
  });
  const layout = sourceGraphLayout(graph);
  expect(layout.positions.get("1")).toEqual({
    x: 32,
    y: 32,
    width: 72,
    height: 42,
    isContainer: false,
  });
  expect(layout.positions.get("2")).toEqual({
    x: 172,
    y: 32,
    width: 72,
    height: 42,
    isContainer: false,
  });
  expect(layout.width).toBeGreaterThanOrEqual(760);
});

test("normalizes source centers and preserves container bounds", () => {
  const sourceGraph: WorkflowEvidence = {
    ...graph,
    layout_source: "source",
    nodes: [
      {
        ...graph.nodes[0],
        x: 48,
        y: 54,
      },
      {
        ...graph.nodes[1],
        id: "container",
        name: "ToolContainer",
        label: "Input preparation",
        x: 20,
        y: 20,
        width: 300,
        height: 160,
      },
    ],
  };
  const layout = sourceGraphLayout(sourceGraph);
  expect(layout.positions.get("1")).toMatchObject({
    x: 32,
    y: 45,
    width: 72,
    height: 42,
    isContainer: false,
  });
  expect(layout.positions.get("container")).toMatchObject({
    x: 40,
    y: 32,
    width: 300,
    height: 160,
    isContainer: true,
  });
});

test("formats Informatica table endpoints and strips XML extensions cleanly", () => {
  expect(nameOf("folder/wf_sample.XML")).toBe("wf_sample");
  const rows = buildEvidenceRows(2, evidence, [
    item({
      path: "export.xml!Folder/wf_sample",
      source_platform: "informatica_powercenter",
      data_sources: ["STG_FX_TRADE_CONF_INSTRUCTIONS", "Tgt_TF_BUSINESS_DATE"],
    }),
  ]);
  expect(rows[0]).toEqual([
    "export.xml!Folder/wf_sample",
    "Referenced endpoint",
    "Table / Endpoint",
    "STG_FX_TRADE_CONF_INSTRUCTIONS",
  ]);
});
