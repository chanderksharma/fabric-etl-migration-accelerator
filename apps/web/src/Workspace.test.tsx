/// <reference types="node" />
import { useState } from "react";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { Workspace } from "./Workspace";
import { FabricDeploymentPage } from "./FabricDeploymentPage";
import type { AssessmentResult, Page } from "./App";
import type { EvidenceResponse } from "./evidence-types";
import type { CapacityEstimate } from "./use-capacity";

afterEach(() => {
  cleanup();
  localStorage.clear();
  sessionStorage.clear();
});

const assessment: AssessmentResult = {
  workflow_count: 2, failed_count: 0, failures: [],
  workflows: [{display_path: "orders.yxmd", sha256: "a"}, {display_path: "custom.yxmd", sha256: "b"}],
  assessments: [
    {path: "orders.yxmd", tool_count: 2, connection_count: 1, complexity_score: 3, complexity_band: "Low",
      recommended_target: "Dataflow Gen2", target_components: ["Dataflow Gen2"], recommendation_reason: "Reviewed tabular candidate",
      unsupported_tools: [], migration_wave: "Wave 1", estimated_effort_days: 0.6,
      dependencies: [], data_sources: ["orders.csv"], graph_schema_version: "1.1.0", tools: [{name: "Filter", count: 1, support: "dataflow"}]},
    {path: "custom.yxmd", tool_count: 1, connection_count: 0, complexity_score: 60, complexity_band: "High",
      recommended_target: "Manual rework", recommendation_reason: "Custom plugin requires redesign",
      unsupported_tools: [], migration_wave: "Redesign", estimated_effort_days: 2,
      dependencies: ["cleanse.yxmc"], data_sources: [], graph_schema_version: "1.1.0"},
  ],
};
const targetCatalogResponse = {
  ok: true,
  json: async () => ({targets: [{
    platform_id: "fabric", display_name: "Microsoft Fabric", provider_version: "1.0.0",
    supported_ir_versions: ["1.0.0"], implemented: true, status: "ready",
    capabilities: ["evaluate", "capacity", "codegen", "dry_run"], description: "Fabric",
  }]}),
};

test.each([
  ["request fails", {ok: false, json: async () => ({})}, "could not be loaded"],
  ["catalog is malformed", {ok: true, json: async () => ({targets: [{platform_id: "fabric"}]})}, "could not be loaded"],
  ["catalog is empty", {ok: true, json: async () => ({targets: []})}, "code generation is unavailable"],
  ["provider is a placeholder", {ok: true, json: async () => ({targets: [{
    platform_id: "fabric", display_name: "Microsoft Fabric", provider_version: "1.0.0",
    supported_ir_versions: ["1.0.0"], implemented: true, status: "placeholder",
    capabilities: ["codegen"], description: "Fabric",
  }]})}, "code generation is unavailable"],
])("disables generation and deployment when the %s", async (_case, response, message) => {
  const request = vi.fn().mockResolvedValue(response);
  render(<FabricDeploymentPage active assessment={assessment} runId="test-ui" candidates={[]}
    generating={false} generate={vi.fn()} request={request} onStartIntake={vi.fn()}/>);

  expect(await screen.findByText(new RegExp(message, "i"))).toBeInTheDocument();
  expect(screen.queryByRole("button", {name: "Generate Notebook code"})).not.toBeInTheDocument();
  expect(screen.queryByRole("button", {name: "Trigger GitHub Actions"})).not.toBeInTheDocument();
});

test("rechecks capabilities without exposing stale generation on return", async () => {
  let rejectCatalog!: (error: Error) => void;
  const pending = new Promise<Response>((_resolve, reject) => { rejectCatalog = reject; });
  const request = vi.fn().mockResolvedValueOnce(targetCatalogResponse).mockReturnValueOnce(pending);
  const view = (active: boolean) => <FabricDeploymentPage active={active} assessment={assessment}
    runId="test-ui" candidates={[]} generating={false} generate={vi.fn()} request={request}
    onStartIntake={vi.fn()}/>;
  const page = render(view(true));
  expect(await screen.findByRole("button", {name: "Generate Notebook code"})).toBeInTheDocument();

  page.rerender(view(false));
  page.rerender(view(true));
  expect(screen.getByText("Loading target capabilities.")).toBeInTheDocument();
  expect(screen.queryByRole("button", {name: "Generate Notebook code"})).not.toBeInTheDocument();
  await act(async () => rejectCatalog(new Error("network unavailable")));
  expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded");
  expect(screen.queryByRole("button", {name: "Trigger GitHub Actions"})).not.toBeInTheDocument();
});
test("offers only the generation kinds the provider advertises", async () => {
  const request = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({targets: [{
      platform_id: "fabric", display_name: "Microsoft Fabric", provider_version: "1.0.0",
      supported_ir_versions: ["1.0.0"], implemented: true, status: "ready",
      capabilities: ["evaluate", "codegen"], target_kinds: ["notebook"], description: "Fabric",
    }]}),
  });
  render(<FabricDeploymentPage active assessment={assessment} runId="test-ui" candidates={[]}
    generating={false} generate={vi.fn()} request={request} onStartIntake={vi.fn()}/>);

  expect(await screen.findByRole("button", {name: "Generate Notebook code"}))
    .toBeInTheDocument();
  expect(screen.getByRole("link", {name: "Download Notebook package"})).toBeInTheDocument();
  expect(screen.queryByRole("button", {name: "Generate Dataflow code"}))
    .not.toBeInTheDocument();
  expect(screen.queryByRole("button", {name: "Generate Pipeline code"}))
    .not.toBeInTheDocument();
  expect(screen.queryByRole("link", {name: "Download Pipeline package"})).not.toBeInTheDocument();
});

const evidence: EvidenceResponse = {
  schema_version: "1.1.0", graph_version: "1.1.0", run_id: "test-ui", snapshot_id: "snapshot-ui",
  total_workflows: 2, truncated: false,
  workflows: [{workflow_index: 0, workflow_path: "orders.yxmd", source_sha256: "a", purpose: "Validate orders",
    source_version: "2020.4", parse_status: "parsed", layout_source: "derived", node_count: 2, edge_count: 1,
    nodes: [
      {id: "1", name: "InputData", label: "Orders", plugin: "InputData", support: "dataflow", disabled: false, x: null, y: null, width: null, height: null, expressions: [], issues: []},
      {id: "2", name: "Filter", label: "Positive amount", plugin: "Filter", support: "dataflow", disabled: false, x: null, y: null, width: null, height: null, expressions: ["[Amount] > 0"], issues: []},
    ], edges: [{source: "1", target: "2", source_anchor: "Output", target_anchor: "Input"}], findings: [], truncated: false}],
};
const capacityEstimate: CapacityEstimate = {
  model_version: "1.0.0",
  status: "inputs_required",
  settings: {
    model_version: "1.0.0", days_per_month: 31, target_utilization: 0.8,
    capacity_floor_cu: 0, burst_window_minutes: 5, balance_weight: 0.5,
    active_users_per_day: 1, average_active_hours_per_user: 2,
    peak_concurrent_users: 1, cu_per_active_user: 0.3, interactive_peak_factor: 2,
    seconds_per_complexity_element: 5.2, minimum_seconds_per_output: 39.2,
    initial_cu_rate: 12, subsequent_cu_rate: 1.5, cu_rate_threshold_seconds: 600,
    extra_output_overlap: 0, projection_variation: 0.01,
    seconds_per_heavy_step_per_thousand_rows: 1.26,
    seconds_per_hundred_rows: 0.000189, calibration_multiplier: 1,
  },
  workflow_count: 2, eligible_count: 1, modeled_count: 1, excluded_count: 1,
  unconfirmed_count: 1, coverage_percent: 50, monthly_cu_hours: 4.1,
  daily_cu_seconds: 475, background_cu: 0.0055,
  scenarios: [
    {name: "Optimized", required_cu: 2.2, recommended_sku: "F4"},
    {name: "Balance", required_cu: 3.1, recommended_sku: "F4"},
    {name: "Peak", required_cu: 4.1, recommended_sku: "F8"},
  ],
  workflows: [
    {
      workflow_path: "orders.yxmd", recommended_target: "Dataflow Gen2",
      target_components: ["Dataflow Gen2"], model_basis: "calibrated",
      status: "unconfirmed", exclusion_reason: null,
      refresh_interval_minutes: 1440, source_rows_per_run: 1000,
      spark_vcores: 8, notebook_runtime_seconds: null, effective_notebook_runtime_seconds: null,
      confirmed: false, runs_per_day: 1,
      complexity_units: 1, duration_driver: "complexity",
      row_volume_threshold: 34_700_000, query_seconds: 39.2,
      dataflow_cu_seconds_per_run: 470.2, notebook_cu_seconds_per_run: 0,
      pipeline_cu_seconds_per_run: 0, cu_seconds_per_run: 470.2,
      projected_cu_seconds_per_run: 474.9, monthly_cu_hours: 4.1,
      autoscale_spark_monthly_cu_hours: 0,
    },
    {
      workflow_path: "custom.yxmd", recommended_target: "Manual rework",
      target_components: [], model_basis: "heuristic",
      status: "unconfirmed",
      exclusion_reason: null,
      refresh_interval_minutes: 1440, source_rows_per_run: 1000,
      confirmed: false, runs_per_day: 1,
      complexity_units: 0.06, duration_driver: "minimum", row_volume_threshold: 20_731_198,
      query_seconds: 39.2, dataflow_cu_seconds_per_run: 470.2,
      notebook_cu_seconds_per_run: 0, pipeline_cu_seconds_per_run: 0,
      cu_seconds_per_run: 470.2,
      projected_cu_seconds_per_run: 474.9, monthly_cu_hours: 4.1,
    },
  ],
  assumptions: ["Validate representative workloads in Fabric Capacity Metrics."],
};

function Harness({initial = "executive-summary"}: {initial?: Page}) {
  const [page, navigate] = useState<Page>(initial);
  return <Workspace page={page} navigate={navigate} assessment={assessment} runId="test-ui"
    run={{id: "test-ui", snapshot_id: "snapshot-ui", status: "completed", processed: 2, total: 2, cache_hits: 0, error: null, result: assessment}}
    candidates={[]} generating={false} generate={vi.fn()} theme="light" toggleTheme={vi.fn()}
    request={vi.fn().mockResolvedValue({json: async () => evidence})}>
    <h1>Intake remains available</h1>
  </Workspace>;
}

test("includes detailed portfolio analysis in the executive page", () => {
  render(<Harness/>);
  expect(screen.getByRole("heading", {name: "Detailed Portfolio Assessment"})).toBeInTheDocument();
  expect(screen.getByRole("heading", {name: "Recommended delivery approach"})).toBeInTheDocument();
  expect(screen.getByRole("heading", {name: "Migration wave distribution"})).toBeInTheDocument();
  expect(screen.queryByRole("heading", {name: "Programme decisions required"})).not.toBeInTheDocument();
  expect(screen.queryByText("153.6d")).not.toBeInTheDocument();
  fireEvent.click(within(screen.getByRole("navigation", {name: "Primary"})).getByRole("link", {name: "New Assessment"}));
  expect(screen.getByRole("heading", {name: "Intake remains available"})).toBeInTheDocument();
});

test("provides a portfolio summary with readiness, decisions, actions, and risks", async () => {
  const navigate = vi.fn();
  const request = vi.fn().mockResolvedValue({json: async () => capacityEstimate});
  render(<Workspace page="executive-summary" navigate={navigate} assessment={assessment} runId="test-ui"
    run={{id: "test-ui", snapshot_id: "snapshot-ui", status: "completed", processed: 2, total: 2, cache_hits: 0, error: null, result: assessment}}
    candidates={[]} generating={false} generate={vi.fn()} theme="light" toggleTheme={vi.fn()} request={request}>
    <h1>Intake remains available</h1>
  </Workspace>);
  const summary = document.getElementById("executive-summary");
  if (!summary) throw new Error("Missing executive summary");
  expect(within(summary).getByRole("heading", {name: "Portfolio Migration Summary"})).toBeInTheDocument();
  expect(within(summary).getByRole("heading", {name: "Leadership recommendation"})).toBeInTheDocument();
  expect(within(summary).getByRole("heading", {name: "Decision brief"})).toBeInTheDocument();
  expect(within(summary).getByRole("heading", {name: "Leadership scorecard"})).toBeInTheDocument();
  expect(within(summary).getByRole("heading", {name: "Immediate leadership actions"})).toBeInTheDocument();
  expect(within(summary).getByRole("heading", {name: "Escalations"})).toBeInTheDocument();
  expect(within(summary).getByText("Conditional proceed")).toBeInTheDocument();
  expect(within(summary).getByText("Native-ready", {
    selector: ".metric-label",
  }).parentElement).toHaveTextContent("1");
  expect(await screen.findByRole("heading", {name: "Fabric capacity summary"})).toBeInTheDocument();
  const projectedCard = within(summary).getByText("Projected F-SKU", {
    selector: ".metric-label",
  }).parentElement;
  expect(projectedCard).toHaveTextContent("F4");
  expect(projectedCard).not.toHaveTextContent("Balance");
  expect(projectedCard).not.toHaveTextContent("Peak");
  fireEvent.click(within(summary).getByRole("button", {name: /Go to Capacity Planning for more details/}));
  expect(navigate).toHaveBeenCalledWith("capacity-planning");
  expect(within(summary).queryByText("Modeled coverage")).not.toBeInTheDocument();
  expect(within(summary).queryByText("Capacity confidence")).not.toBeInTheDocument();
  expect(screen.getByText("F4 (2.20 CUs)")).toBeInTheDocument();
});

test("refetches capacity when Fabric routing is confirmed instead of keeping the static estimate", async () => {
  const confirmed = {
    ...capacityEstimate,
    monthly_cu_hours: 3.3,
    scenarios: [
      {name: "Optimized" as const, required_cu: 1.9, recommended_sku: "F2"},
      {name: "Balance" as const, required_cu: 2.4, recommended_sku: "F4"},
      {name: "Peak" as const, required_cu: 3.0, recommended_sku: "F4"},
    ],
  };
  const request = vi.fn()
    .mockResolvedValueOnce({json: async () => capacityEstimate})
    .mockResolvedValueOnce({json: async () => confirmed});
  const view = (basis: "static_mapping" | "compiler_confirmed") =>
    <Workspace page="executive-summary" navigate={vi.fn()} assessment={assessment} runId="test-ui"
      run={{id: "test-ui", snapshot_id: "snapshot-ui", status: "completed", processed: 2, total: 2,
        cache_hits: 0, error: null, routing_basis: basis, result: assessment}}
      candidates={[]} generating={false} generate={vi.fn()} theme="light" toggleTheme={vi.fn()}
      request={request}>
      <h1>Intake</h1>
    </Workspace>;
  const rendered = render(view("static_mapping"));
  const summary = document.getElementById("executive-summary");
  if (!summary) throw new Error("Missing executive summary");
  const projected = () => within(summary).getByText("Projected F-SKU", {
    selector: ".metric-label",
  }).parentElement;
  expect(await screen.findByText("F4 (2.20 CUs)")).toBeInTheDocument();
  expect(projected()).toHaveTextContent("4.1 CU-h/mo");
  expect(request).toHaveBeenCalledTimes(1);

  rendered.rerender(view("compiler_confirmed"));

  expect(await screen.findByText("F2 (1.90 CUs)")).toBeInTheDocument();
  expect(projected()).toHaveTextContent("3.3 CU-h/mo");
  expect(request).toHaveBeenCalledTimes(2);
});

test("edits and persists capacity inputs before presenting a preliminary SKU", async () => {
  const updated = {
    ...capacityEstimate,
    status: "planning_estimate" as const,
    unconfirmed_count: 0,
    workflows: capacityEstimate.workflows.map(item =>
      item.workflow_path === "orders.yxmd"
        ? {...item, confirmed: true, source_rows_per_run: 50000, status: "estimated" as const}
        : item
    ),
  };
  const request = vi.fn()
    .mockResolvedValueOnce({json: async () => capacityEstimate})
    .mockResolvedValueOnce({json: async () => updated});
  render(<Workspace page="capacity-planning" navigate={vi.fn()} assessment={assessment}
    runId="test-ui" candidates={[]} generating={false} generate={vi.fn()}
    run={{id: "test-ui", snapshot_id: "snapshot-ui", status: "completed", processed: 2,
      total: 2, cache_hits: 0, error: null, result: assessment}}
    theme="light" toggleTheme={vi.fn()} request={request}>
    <h1>Intake</h1>
  </Workspace>);

  expect(await screen.findByRole("heading", {name: "Fabric Capacity Estimate"}))
    .toBeInTheDocument();
  expect(screen.getByRole("heading", {name: "Preliminary recommendation: F4"}))
    .toBeInTheDocument();
  expect(screen.getByText("Default assumptions")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Source rows for orders.yxmd"), {
    target: {value: "50000"},
  });
  fireEvent.click(screen.getByRole("button", {name: "Save and recalculate"}));

  await act(async () => {
    expect(request).toHaveBeenCalledTimes(2);
  });
  const [, updateRequest] = request.mock.calls[1] as [string, RequestInit];
  expect(JSON.parse(String(updateRequest.body))).toMatchObject({
    inputs: [
      {workflow_path: "orders.yxmd", source_rows_per_run: 50000, confirmed: true},
      {workflow_path: "custom.yxmd", source_rows_per_run: 1000, confirmed: true},
    ],
  });
});

test("toggles Spark Notebook billing between F-SKU and Autoscale Billing for Spark", async () => {
  const mixedEstimate: CapacityEstimate = {
    ...capacityEstimate,
    settings: {...capacityEstimate.settings, spark_billing_mode: "capacity"},
    workflows: [
      {
        ...capacityEstimate.workflows[0],
        workflow_path: "mixed.yxmd",
        recommended_target: "Mixed Fabric solution",
        target_components: ["Dataflow Gen2", "Fabric Notebook", "Fabric Pipeline"],
        model_basis: "heuristic",
        spark_vcores: 8,
        notebook_runtime_seconds: null,
        effective_notebook_runtime_seconds: 60,
        dataflow_cu_seconds_per_run: 470.2,
        notebook_cu_seconds_per_run: 240.0,
        pipeline_cu_seconds_per_run: 40.0,
        cu_seconds_per_run: 750.2,
        projected_cu_seconds_per_run: 757.7,
        monthly_cu_hours: 6.5,
        autoscale_spark_monthly_cu_hours: 0,
      },
    ],
  };
  const autoscaleEstimate: CapacityEstimate = {
    ...mixedEstimate,
    status: "planning_estimate",
    unconfirmed_count: 0,
    settings: {...mixedEstimate.settings, spark_billing_mode: "autoscale"},
    monthly_cu_hours: 4.4,
    autoscale_spark_monthly_cu_hours: 2.1,
  };
  const request = vi.fn()
    .mockResolvedValueOnce({json: async () => mixedEstimate})
    .mockResolvedValueOnce({json: async () => autoscaleEstimate});
  render(<Workspace page="capacity-planning" navigate={vi.fn()} assessment={assessment}
    runId="test-ui" candidates={[]} generating={false} generate={vi.fn()}
    run={{id: "test-ui", snapshot_id: "snapshot-ui", status: "completed", processed: 2,
      total: 2, cache_hits: 0, error: null, result: assessment}}
    theme="light" toggleTheme={vi.fn()} request={request}>
    <h1>Intake</h1>
  </Workspace>);

  expect(await screen.findByText(/DF 470 · NB 240 · PL 40/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("radio", {name: "Autoscale Billing for Spark"}));

  expect(await screen.findByText("Autoscale Spark demand")).toBeInTheDocument();
  expect(screen.getByText(/DF 470 · NB 240 \(Autoscale\) · PL 40/)).toBeInTheDocument();
  const [, toggleRequest] = request.mock.calls[1] as [string, RequestInit];
  expect(JSON.parse(String(toggleRequest.body))).toMatchObject({
    settings: {spark_billing_mode: "autoscale"},
  });
});

test("defaults interactive users to 1 and recalculates when updated to 0", async () => {
  const etlOnly = {
    ...capacityEstimate,
    status: "planning_estimate" as const,
    unconfirmed_count: 0,
    settings: {...capacityEstimate.settings, active_users_per_day: 0, peak_concurrent_users: 0},
    scenarios: [{name: "Optimized" as const, required_cu: 1.58, recommended_sku: "F2"}],
  };
  const request = vi.fn()
    .mockResolvedValueOnce({json: async () => capacityEstimate})
    .mockResolvedValueOnce({json: async () => etlOnly});
  render(<Workspace page="capacity-planning" navigate={vi.fn()} assessment={assessment}
    runId="test-ui" candidates={[]} generating={false} generate={vi.fn()}
    run={{id: "test-ui", snapshot_id: "snapshot-ui", status: "completed", processed: 2,
      total: 2, cache_hits: 0, error: null, result: assessment}}
    theme="light" toggleTheme={vi.fn()} request={request}>
    <h1>Intake</h1>
  </Workspace>);

  const usersInput = await screen.findByLabelText("Interactive users");
  expect(usersInput).toHaveValue(1);
  fireEvent.change(usersInput, {target: {value: "0"}});
  fireEvent.click(screen.getByRole("button", {name: "Update"}));

  expect(await screen.findByRole("heading", {name: "Preliminary recommendation: F2"}))
    .toBeInTheDocument();
  const [, updateRequest] = request.mock.calls[1] as [string, RequestInit];
  expect(JSON.parse(String(updateRequest.body))).toMatchObject({
    settings: {active_users_per_day: 0, peak_concurrent_users: 0},
  });
});

test("filters the workflow register and restores it with clear filters", () => {
  render(<Harness initial="workflows"/>);
  const region = document.getElementById("workflows");
  if (!region) throw new Error("Missing workflow register");
  const filters = within(region).getByRole("search", {name: "Workflow filters"});
  expect(within(filters).getByPlaceholderText("Search workflows")).toBeInTheDocument();
  fireEvent.change(within(region).getByLabelText("Search workflows"), {target: {value: "custom"}});
  expect(within(region).queryByRole("button", {name: "Open workflow orders"})).not.toBeInTheDocument();
  expect(within(region).getByRole("button", {name: "Open workflow custom"})).toBeInTheDocument();
  expect(within(region).getByRole("row", {name: /custom.*Requires redesign/}))
    .toBeInTheDocument();
  fireEvent.click(within(region).getByRole("button", {name: "Clear filters"}));
  expect(within(region).getByRole("button", {name: "Open workflow orders"})).toBeInTheDocument();
});

test("exports the workflow register through a disposable CSV download", () => {
  const createObjectUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:workflows");
  const revokeObjectUrl = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  render(<Harness initial="workflows"/>);

  fireEvent.click(screen.getByRole("button", {name: "Export register"}));

  expect(createObjectUrl).toHaveBeenCalledOnce();
  expect(click).toHaveBeenCalledOnce();
  expect(revokeObjectUrl).toHaveBeenCalledWith("blob:workflows");
});

test("presents migration stages as Wave 1 through Wave 4", () => {
  render(<Harness initial="migration-plan"/>);
  for (const wave of ["Wave 1", "Wave 2", "Wave 3", "Wave 4"]) {
    expect(screen.getByRole("heading", {name: wave})).toBeInTheDocument();
  }
  expect(screen.queryByRole("heading", {name: "Pilot"})).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", {name: "Redesign"})).not.toBeInTheDocument();
});

test("opens all six drawer views and hands off to Fabric Deployment", async () => {
  const navigate = vi.fn();
  render(<Workspace page="workflows" navigate={navigate} assessment={assessment} runId="test-ui"
    run={{id: "test-ui", snapshot_id: "snapshot-ui", status: "completed", processed: 2, total: 2, cache_hits: 0, error: null, result: assessment}}
    candidates={[]} generating={false} generate={vi.fn()} theme="light" toggleTheme={vi.fn()}
    request={vi.fn().mockResolvedValue({json: async () => evidence})}><span>Intake</span></Workspace>);
  fireEvent.click(screen.getByRole("button", {name: "Open workflow orders"}));
  const dialog = screen.getByRole("dialog");
  expect((await within(dialog).findAllByText("Validate orders")).length).toBeGreaterThan(0);
  expect(within(dialog).getByText(/0 branches · depth 2 · 0 containers · no cycles/)).toBeInTheDocument();
  expect(within(dialog).getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
    "Summary",
    "Source Workflow",
    "Fabric design",
    "Risk assessment",
    "Validation",
    "Fabric deployment",
  ]);
  for (const name of ["Fabric design", "Source Workflow"]) {
    fireEvent.click(within(dialog).getByRole("tab", {name}));
    expect(within(dialog).getByRole("tab", {name})).toHaveAttribute("aria-selected", "true");
  }
  expect(within(dialog).getByRole("heading", {name: "Material workflow components"})).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("tab", {name: "Risk assessment"}));
  expect(within(dialog).getByText("Operational review")).toBeInTheDocument();
  for (const name of ["Validation", "Fabric deployment"]) {
    fireEvent.click(within(dialog).getByRole("tab", {name}));
    expect(within(dialog).getByRole("tab", {name})).toHaveAttribute("aria-selected", "true");
  }
  expect(within(dialog).getByRole("heading", {name: "Deployment readiness"})).toBeInTheDocument();
  expect(within(dialog).getByRole("link", {name: "Download workflow bundle"})).toHaveAttribute(
    "href",
    "/api/runs/test-ui/bundle?workflow=orders.yxmd",
  );
  fireEvent.click(within(dialog).getByRole("button", {name: "Continue to Fabric Deployment →"}));
  expect(navigate).toHaveBeenCalledWith("fabric-deployment");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("exposes the prototype technical evidence columns across every register", async () => {
  render(<Harness initial="technical-details"/>);
  expect(await screen.findByRole("columnheader", {name: "Category"})).toBeInTheDocument();
  expect(screen.getByRole("columnheader", {name: "Fabric target"})).toBeInTheDocument();
  const expectedColumns = [
    ["Expressions", "Mapping guidance"],
    ["Inputs & outputs", "Direction"],
    ["Dependencies", "Sensitive"],
    ["Findings", "Severity"],
    ["Connections", "Condition"],
  ];
  for (const [tab, column] of expectedColumns) {
    fireEvent.click(screen.getByRole("tab", {name: new RegExp(`^${tab}`)}));
    expect(screen.getByRole("columnheader", {name: column})).toBeInTheDocument();
  }
});

test("validates the GitHub repository URL before deployment dispatch", async () => {
  const request = vi.fn().mockResolvedValue(targetCatalogResponse);
  const candidates = [{
    workflow: "orders.yxmd", target: "dataflow", validation_state: "generated_unvalidated",
    code: "display(df)", diagnostics: [], deployable: true, definition_ready: true,
    runtime_ready: true, artifact_path: "orders", definition_files: ["dataflow-mashup.pq"],
  }];
  render(<Workspace page="fabric-deployment" navigate={vi.fn()} assessment={assessment} runId="test-ui"
    run={{id: "test-ui", snapshot_id: "snapshot-ui", status: "completed", processed: 2, total: 2, cache_hits: 0, error: null, result: assessment}}
    candidates={candidates} generating={false} generate={vi.fn()} theme="light" toggleTheme={vi.fn()}
    request={request}><span>Intake</span></Workspace>);
  const section = document.getElementById("fabric-deployment")!;
  expect(await within(section).findByRole("link", {
    name: "Download workflow bundle",
  })).toHaveAttribute(
    "href",
    "/api/runs/test-ui/bundle?workflow=orders.yxmd",
  );
  expect(within(section).queryByRole("heading", {
    name: "Generated deployment manifest",
  })).not.toBeInTheDocument();
  fireEvent.change(within(section).getByLabelText("GitHub repository URL"), {target: {value: "owner/repository"}});
  fireEvent.click(within(section).getByRole("button", {name: "Validate deployment request"}));
  expect(within(section).getByText(/Use an HTTPS GitHub repository URL/)).toBeInTheDocument();
  fireEvent.change(within(section).getByLabelText("GitHub repository URL"), {
    target: {value: "https://github.com/owner/repository"},
  });
  fireEvent.change(within(section).getByLabelText("Publication digest (optional)"), {
    target: {value: "c".repeat(64)},
  });
  fireEvent.click(within(section).getByRole("button", {name: "Validate deployment request"}));
  expect(within(section).getByText(/publication digest requires an expected commit/i)).toBeInTheDocument();
  fireEvent.change(within(section).getByLabelText("Publication digest (optional)"), {
    target: {value: ""},
  });
  fireEvent.change(within(section).getByLabelText("Expected commit SHA (optional)"), {
    target: {value: "main"},
  });
  fireEvent.click(within(section).getByRole("button", {name: "Validate deployment request"}));
  expect(within(section).getByText(/Expected commit must be a full lowercase/)).toBeInTheDocument();
  fireEvent.change(within(section).getByLabelText("Expected commit SHA (optional)"), {
    target: {value: ""},
  });
  fireEvent.click(within(section).getByRole("button", {name: "Validate deployment request"}));
  expect(within(section).getByText(/request is ready for owner\/repository/)).toBeInTheDocument();
});

test("dispatches a validated GitHub Actions deployment", async () => {
  const candidates = [{
    workflow: "orders.yxmd", target: "dataflow", validation_state: "generated_unvalidated",
    code: "display(df)", diagnostics: [], deployable: true, definition_ready: true,
    runtime_ready: true, artifact_path: "orders", definition_files: ["dataflow-mashup.pq"],
  }];
  const request = vi.fn().mockImplementation(async (path: string) => {
    if (path === "/api/targets") return targetCatalogResponse;
    return {
      ok: true,
      json: async () => ({
        deployment_id: "dispatch-1", repository: "owner/repository",
        target: "dataflow", status: "dispatched",
      }),
    };
  });
  render(<Workspace page="fabric-deployment" navigate={vi.fn()} assessment={assessment} runId="test-ui"
    run={{id: "test-ui", snapshot_id: "snapshot-ui", status: "completed", processed: 2, total: 2, cache_hits: 0, error: null, result: assessment}}
    candidates={candidates} generating={false} generate={vi.fn()} theme="light" toggleTheme={vi.fn()}
    request={request}><span>Intake</span></Workspace>);
  const section = document.getElementById("fabric-deployment")!;
  fireEvent.change(await within(section).findByLabelText("GitHub repository URL"), {
    target: {value: "https://github.com/owner/repository"},
  });
  fireEvent.change(within(section).getByLabelText("Expected commit SHA (optional)"), {
    target: {value: "a".repeat(40)},
  });
  fireEvent.change(within(section).getByLabelText("Publication digest (optional)"), {
    target: {value: "c".repeat(64)},
  });
  fireEvent.click(within(section).getByRole("checkbox", {name: "Isolate local deployment planning"}));
  fireEvent.click(within(section).getByRole("button", {name: "Trigger GitHub Actions"}));
  expect(await within(section).findByRole("status")).toHaveTextContent(
    "deployment dispatch-1 triggered"
  );
  expect(request).toHaveBeenCalledWith(
    "/api/runs/test-ui/deploy/github",
    expect.objectContaining({method: "POST"}),
  );
  const deploymentCall = request.mock.calls.find(
    ([path, init]) => path.endsWith("/deploy/github") && init?.method === "POST"
  );
  if (!deploymentCall) throw new Error("Missing deployment request");
  const body = JSON.parse(deploymentCall[1].body);
  expect(body).toMatchObject({
    repository_url: "https://github.com/owner/repository",
    source_workflow: "orders.yxmd",
    target: "dataflow",
    conflict_behavior: "Update",
    expected_commit: "a".repeat(40),
    isolate_local_artifacts: true,
    publication_digest: "c".repeat(64),
  });
});

test("dispatches a validated GitLab CI deployment", async () => {
  const candidates = [{
    workflow: "orders.yxmd", target: "dataflow", validation_state: "generated_unvalidated",
    code: "display(df)", diagnostics: [], deployable: true, definition_ready: true,
    runtime_ready: true, artifact_path: "orders", definition_files: ["dataflow-mashup.pq"],
  }];
  const request = vi.fn().mockImplementation(async (path: string) => {
    if (path === "/api/targets") return targetCatalogResponse;
    return {
      ok: true,
      json: async () => ({
        deployment_id: "901", project: "group/project", target: "dataflow",
        status: "dispatched", pipeline_url: "https://gitlab.com/group/project/-/pipelines/901",
      }),
    };
  });
  render(<Workspace page="fabric-deployment" navigate={vi.fn()} assessment={assessment} runId="test-ui"
    run={{id: "test-ui", snapshot_id: "snapshot-ui", status: "completed", processed: 2, total: 2, cache_hits: 0, error: null, result: assessment}}
    candidates={candidates} generating={false} generate={vi.fn()} theme="light" toggleTheme={vi.fn()}
    request={request}><span>Intake</span></Workspace>);
  const section = document.getElementById("fabric-deployment")!;
  fireEvent.change(await within(section).findByLabelText("Deployment method"), {
    target: {value: "gitlab"},
  });
  expect(within(section).getByDisplayValue(".gitlab-ci.yml")).toBeInTheDocument();
  expect(within(section).getByDisplayValue(
    "Server-side GitLab project access token",
  )).toBeInTheDocument();
  fireEvent.change(within(section).getByLabelText("GitLab project URL"), {
    target: {value: "https://gitlab.com/group/project"},
  });
  fireEvent.change(within(section).getByLabelText("Expected commit SHA (optional)"), {
    target: {value: "b".repeat(40)},
  });
  fireEvent.change(within(section).getByLabelText("Publication digest (optional)"), {
    target: {value: "d".repeat(64)},
  });
  fireEvent.click(within(section).getByRole("checkbox", {name: "Isolate local deployment planning"}));
  fireEvent.click(within(section).getByRole("button", {name: "Trigger GitLab CI"}));
  expect(await within(section).findByText(/GitLab CI dataflow pipeline 901 triggered/))
    .toBeInTheDocument();

  const deploymentCall = request.mock.calls.find(
    ([path, init]) => path.endsWith("/deploy/gitlab") && init?.method === "POST"
  );
  if (!deploymentCall) throw new Error("Missing GitLab deployment request");
  const body = JSON.parse(deploymentCall[1].body);
  expect(body).toMatchObject({
    project_url: "https://gitlab.com/group/project",
    source_workflow: "orders.yxmd",
    target: "dataflow",
    ci_file: ".gitlab-ci.yml",
    conflict_behavior: "Update",
    expected_commit: "b".repeat(40),
    isolate_local_artifacts: true,
    publication_digest: "d".repeat(64),
  });
});

test("dispatches a mixed redesign workflow as a three-item bundle", async () => {
  const mixedAssessment: AssessmentResult = {
    ...assessment,
    workflow_count: 1,
    assessments: [{
      ...assessment.assessments[1],
      path: "mixed.yxmd",
      recommended_target: "Mixed Fabric solution",
      target_components: ["Dataflow Gen2", "Fabric Notebook", "Fabric Pipeline"],
    }],
    workflows: [{display_path: "mixed.yxmd", sha256: "mixed"}],
  };
  const candidates = [
    {
      workflow: "mixed.yxmd", target: "dataflow", validation_state: "generated_unvalidated",
      code: "section Section1;", diagnostics: [], deployable: true, definition_ready: true,
      runtime_ready: false, artifact_path: "mixed", definition_files: ["dataflow-mashup.pq"],
    },
    {
      workflow: "mixed.yxmd", target: "notebook", validation_state: "generated_unvalidated",
      code: "display(df)", diagnostics: [], deployable: true, definition_ready: true,
      runtime_ready: false, artifact_path: "mixed", definition_files: ["notebook-content.ipynb"],
    },
  ];
  const request = vi.fn().mockImplementation(async (path: string) => {
    if (path === "/api/targets") return targetCatalogResponse;
    return {
      ok: true,
      json: async () => ({
        deployment_id: "dispatch-bundle",
        repository: "owner/repository",
        target: "bundle",
        status: "dispatched",
      }),
    };
  });
  render(<Workspace page="fabric-deployment" navigate={vi.fn()} assessment={mixedAssessment}
    runId="test-ui" run={{id: "test-ui", snapshot_id: "snapshot-ui", status: "completed",
      processed: 1, total: 1, cache_hits: 0, error: null, result: mixedAssessment}}
    candidates={candidates} generating={false} generate={vi.fn()} theme="light"
    toggleTheme={vi.fn()} request={request}><span>Intake</span></Workspace>);

  const section = document.getElementById("fabric-deployment")!;
  expect(await within(section).findByLabelText("Deployment target")).toHaveValue("bundle");
  expect(within(section).getByRole("option", {name: "Fabric Data Pipeline"}))
    .toBeInTheDocument();
  fireEvent.change(within(section).getByLabelText("GitHub repository URL"), {
    target: {value: "https://github.com/owner/repository"},
  });
  fireEvent.click(within(section).getByRole("button", {name: "Trigger GitHub Actions"}));
  await act(async () => undefined);

  const bundleCall = request.mock.calls.find(
    ([path, init]) => path.endsWith("/deploy/github") && init?.method === "POST"
  );
  if (!bundleCall) throw new Error("Missing bundle deployment request");
  const body = JSON.parse(bundleCall[1].body);
  expect(body).toMatchObject({
    source_workflow: "mixed.yxmd",
    target: "bundle",
  });
});

test("groups fabric deployment outputs into packages and code previews with clear summary", async () => {
  const candidates = [
    {
      workflow: "orders.yxmd", target: "notebook", validation_state: "generated_unvalidated",
      code: "display(df)", diagnostics: [], deployable: true, definition_ready: true,
      runtime_ready: true, artifact_path: "orders-abc", definition_files: ["notebook-content.ipynb"],
    },
    {
      workflow: "legacy.yxmd", target: "notebook", validation_state: "scaffold_only",
      code: "", diagnostics: ["Manual redesign needed."], deployable: false, definition_ready: false,
      runtime_ready: false, artifact_path: "legacy-def", definition_files: ["diagnostics.json"],
    },
  ];
  render(<Workspace page="fabric-deployment" navigate={vi.fn()} assessment={assessment}
    runId="test-outputs" run={{id: "test-outputs", snapshot_id: "snapshot-outputs", status: "completed",
      processed: 2, total: 2, cache_hits: 0, error: null, result: assessment}}
    candidates={candidates} generating={false} generate={vi.fn()} theme="light"
    toggleTheme={vi.fn()} request={vi.fn().mockResolvedValue(targetCatalogResponse)}><span>Intake</span></Workspace>);

  expect(screen.getByRole("heading", {name: "1. Target platform"})).toBeInTheDocument();
  expect(await screen.findByRole("heading", {name: "2. Generate & download Fabric definitions"})).toBeInTheDocument();
  expect(screen.getByRole("heading", {name: "Download Fabric packages"})).toBeInTheDocument();
  expect(screen.getByRole("heading", {name: "Generate and review code (not saved)"})).toBeInTheDocument();
  expect(screen.getByRole("heading", {name: "3. Select workflow & dispatch deployment"})).toBeInTheDocument();
  expect(screen.getByText("Fabric Notebook generated code (2)")).toBeInTheDocument();
  expect(screen.getByText("1 deployable · 1 manual scaffold")).toBeInTheDocument();
  expect(screen.getByText("Deployable definition")).toBeInTheDocument();
  expect(screen.getByText("Scaffold / manual rework")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Filter generated code"), {target: {value: "scaffold"}});
  expect(screen.queryByText("Deployable definition")).not.toBeInTheDocument();
  expect(screen.getByText("Scaffold / manual rework")).toBeInTheDocument();
});

test("does not show snapshot error alert on Technical Details before an assessment runs", () => {
  render(<Workspace page="technical-details" navigate={vi.fn()} assessment={null} runId={null} run={null}
    candidates={[]} generating={false} generate={vi.fn()} theme="light" toggleTheme={vi.fn()}
    request={vi.fn()}><span>Intake</span></Workspace>);

  expect(screen.getByText("No technical evidence loaded.")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("defaults orchestration assets to a pipeline deployment", async () => {
  const orchestrationAssessment: AssessmentResult = {
    ...assessment,
    workflow_count: 1,
    workflows: [{display_path: "tf_orders", sha256: "taskflow"}],
    assessments: [{
      ...assessment.assessments[0],
      path: "tf_orders",
      recommended_target: "Fabric Pipeline",
      target_components: ["Fabric Pipeline"],
    }],
  };
  render(<Workspace page="fabric-deployment" navigate={vi.fn()} assessment={orchestrationAssessment}
    runId="test-ui" run={null} candidates={[]} generating={false} generate={vi.fn()}
    theme="light" toggleTheme={vi.fn()}
    request={vi.fn().mockResolvedValue(targetCatalogResponse)}>
    <span>Intake</span>
  </Workspace>);

  const section = document.getElementById("fabric-deployment")!;
  expect(await within(section).findByLabelText("Deployment target")).toHaveValue("pipeline");
  expect(within(section).getByRole("option", {name: "Fabric Data Pipeline"}))
    .toBeInTheDocument();
});

test("loads multi-asset package evidence in the workflow drawer", async () => {
  const packageAssessment: AssessmentResult = {
    ...assessment,
    workflow_count: 2,
    workflows: [{display_path: "pkg.zip!export.xml", sha256: "pkg"}],
    assessments: [
      {
        ...assessment.assessments[0],
        path: "pkg.zip!export.xml!Folder/m_one",
        source_platform: "informatica_powercenter",
      },
      {
        ...assessment.assessments[0],
        path: "pkg.zip!export.xml!Folder/wf_one",
        source_platform: "informatica_powercenter",
      },
    ],
  };
  const packageEvidence: EvidenceResponse = {
    ...evidence,
    run_id: "test-ui-package",
    total_workflows: 1,
    workflows: [
      {...evidence.workflows[0], workflow_index: 0, workflow_path: "pkg.zip!export.xml!Folder/m_one", purpose: "Mapping one"},
      {...evidence.workflows[0], workflow_index: 0, workflow_path: "pkg.zip!export.xml!Folder/wf_one", purpose: "Workflow one"},
    ],
  };
  const request = vi.fn().mockResolvedValue({json: async () => packageEvidence});
  render(<Workspace page="workflows" navigate={vi.fn()} assessment={packageAssessment}
    runId="test-ui-package" run={{id: "test-ui-package", snapshot_id: "snapshot-ui", status: "completed",
      processed: 1, total: 1, cache_hits: 0, error: null, result: packageAssessment}}
    candidates={[]} generating={false} generate={vi.fn()} theme="light"
    toggleTheme={vi.fn()} request={request}><span>Intake</span></Workspace>);

  fireEvent.click(screen.getByRole("button", {name: "Open workflow wf_one"}));
  const dialog = screen.getByRole("dialog");
  expect((await within(dialog).findAllByText("Workflow one")).length).toBeGreaterThan(0);
  expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
});

test("reference styles and components cannot import remote code or deployment scripts", () => {
  const css = readFileSync(join(process.cwd(), "src", "prototype.css"), "utf8");
  const component = [
    "Workspace.tsx",
    "FabricDeploymentPage.tsx",
    "workspace-deployment.tsx",
    "workspace-evidence.ts",
    "workspace-registers.tsx",
  ].map(file => readFileSync(join(process.cwd(), "src", file), "utf8")).join("\n");
  expect(css).not.toMatch(/@import|expression\s*\(|javascript:|url\(\s*["']?https?:/i);
  expect(component).not.toMatch(/dangerouslySetInnerHTML|<iframe|XMLHttpRequest|WebSocket/);
  expect(component).not.toMatch(/fetch\(["'`]https?:/);
  expect(css).toContain("Reference prototype SHA-256:");
});

test("discards evidence when the snapshot changes inside the same run", async () => {
  let resolveEvidence!: (response: {json: () => Promise<EvidenceResponse>}) => void;
  const pending = new Promise<{json: () => Promise<EvidenceResponse>}>((resolve) => {
    resolveEvidence = resolve;
  });
  const request = vi.fn().mockReturnValue(pending);
  function view(snapshotId: string) {
    return <Workspace page="workflows" navigate={vi.fn()} assessment={assessment} runId="stale-ui"
      run={{id: "stale-ui", snapshot_id: snapshotId, status: "completed", processed: 2, total: 2, cache_hits: 0, error: null, result: assessment}}
      candidates={[]} generating={false} generate={vi.fn()} theme="light" toggleTheme={vi.fn()}
      request={request}><span>Intake</span></Workspace>;
  }
  const app = render(view("first-snapshot"));
  fireEvent.click(screen.getByRole("button", {name: "Open workflow orders"}));
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  app.rerender(view("second-snapshot"));
  await act(async () => {
    resolveEvidence({json: async () => ({...evidence, run_id: "stale-ui", snapshot_id: "first-snapshot"})});
  });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("supports drawer prev/next navigation, manual-rework guard, and remembered deploy preferences", async () => {
  const candidates = [{
    workflow: "orders.yxmd", target: "dataflow", validation_state: "generated_unvalidated",
    code: "display(df)", diagnostics: [], deployable: true, definition_ready: true,
    runtime_ready: true, artifact_path: "orders", definition_files: ["dataflow-mashup.pq"],
  }];
  const request = vi.fn().mockImplementation(async (path: string) => {
    if (path === "/api/targets") return targetCatalogResponse;
    if (path.includes("/deploy/github")) {
      return {
        ok: true,
        json: async () => ({
          deployment_id: "dep-nav-1",
          repository: "owner/repo",
          target: "dataflow",
          status: "dispatched",
        }),
      };
    }
    return {ok: true, json: async () => evidence};
  });
  const app = render(<Workspace page="workflows" navigate={vi.fn()} assessment={assessment} runId="test-ui-nav"
    run={{id: "test-ui-nav", snapshot_id: "snapshot-ui", status: "completed", processed: 2, total: 2, cache_hits: 0, error: null, result: assessment}}
    candidates={candidates} generating={false} generate={vi.fn()} theme="light" toggleTheme={vi.fn()}
    request={request}><span>Intake</span></Workspace>);

  expect(within(screen.getByRole("navigation", {name: "Primary"})).getByRole("link", {name: "New Assessment"})).toBeInTheDocument();
  expect(within(screen.getByRole("navigation", {name: "Primary"})).getByRole("link", {name: "Fabric Deployment"})).toBeInTheDocument();
  expect(screen.queryByRole("button", {name: "New assessment"})).not.toBeInTheDocument();
  expect(within(screen.getByRole("navigation", {name: "Mobile primary navigation"})).getByRole("link", {name: "Intake"})).toBeInTheDocument();
  expect(within(screen.getByRole("navigation", {name: "Mobile primary navigation"})).getByRole("link", {name: "Deploy"})).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", {name: "Open workflow orders"}));
  const dialog = screen.getByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", {name: "Next workflow →"}));
  expect(within(dialog).getByRole("heading", {name: "custom"})).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("tab", {name: "Fabric deployment"}));
  expect(within(dialog).getByText("Manual rework required.")).toBeInTheDocument();
  fireEvent.keyDown(dialog, {key: "Escape"});

  app.rerender(<Workspace page="fabric-deployment" navigate={vi.fn()} assessment={assessment} runId="test-ui-nav"
    run={{id: "test-ui-nav", snapshot_id: "snapshot-ui", status: "completed", processed: 2, total: 2, cache_hits: 0, error: null, result: assessment}}
    candidates={candidates} generating={false} generate={vi.fn()} theme="light" toggleTheme={vi.fn()}
    request={request}><span>Intake</span></Workspace>);
  const section = document.getElementById("fabric-deployment")!;
  fireEvent.change(await within(section).findByLabelText("GitHub repository URL"), {
    target: {value: "https://github.com/owner/repo"},
  });
  fireEvent.change(within(section).getByLabelText("Git ref"), {
    target: {value: "main"},
  });
  fireEvent.click(within(section).getByRole("button", {name: "Trigger GitHub Actions"}));
  expect(await within(section).findByRole("link", {name: /Open GitHub Actions runs/})).toHaveAttribute(
    "href",
    "https://github.com/owner/repo/actions",
  );

  fireEvent.change(within(section).getByLabelText("Workflow to deploy"), {
    target: {value: "custom.yxmd"},
  });
  expect(within(section).getByText("Manual rework required.")).toBeInTheDocument();
  expect(within(section).getByRole("button", {name: "Trigger GitHub Actions"})).toBeDisabled();
  expect(within(section).getByLabelText("GitHub repository URL")).toHaveValue("https://github.com/owner/repo");
  expect(within(section).getByLabelText("Git ref")).toHaveValue("main");
});
