/// <reference types="node" />
import { useState } from "react";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { Workspace } from "./Workspace";
import type { AssessmentResult, Page } from "./App";
import type { EvidenceResponse } from "./evidence-types";

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

test("provides a portfolio summary with readiness, decisions, actions, and risks", () => {
  render(<Harness initial="executive-summary"/>);
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

test("opens all six drawer views and gates GitHub Actions deployment", async () => {
  render(<Harness initial="workflows"/>);
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
  expect(within(dialog).getByRole("button", {name: "Trigger GitHub Actions"})).toBeEnabled();
  expect(within(dialog).getByText(
    /GitHub Actions and GitLab CI are dispatch-only deployment methods/
  )).toBeInTheDocument();
  expect(within(dialog).getByLabelText("GitHub repository URL")).toBeInTheDocument();
  expect(within(dialog).getByDisplayValue("Existing workflow required")).toBeInTheDocument();
  fireEvent.keyDown(dialog, {key: "Escape"});
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
  const request = vi.fn().mockResolvedValue({json: async () => evidence});
  const candidates = [{
    workflow: "orders.yxmd", target: "dataflow", validation_state: "generated_unvalidated",
    code: "display(df)", diagnostics: [], deployable: true, definition_ready: true,
    runtime_ready: true, artifact_path: "orders", definition_files: ["dataflow-mashup.pq"],
  }];
  render(<Workspace page="workflows" navigate={vi.fn()} assessment={assessment} runId="test-ui"
    run={{id: "test-ui", snapshot_id: "snapshot-ui", status: "completed", processed: 2, total: 2, cache_hits: 0, error: null, result: assessment}}
    candidates={candidates} generating={false} generate={vi.fn()} theme="light" toggleTheme={vi.fn()}
    request={request}><span>Intake</span></Workspace>);
  fireEvent.click(screen.getByRole("button", {name: "Open workflow orders"}));
  const dialog = screen.getByRole("dialog");
  fireEvent.click(within(dialog).getByRole("tab", {name: "Fabric deployment"}));
  expect(within(dialog).getByRole("link", {
    name: "Download workflow bundle",
  })).toHaveAttribute(
    "href",
    "/api/runs/test-ui/bundle?workflow=orders.yxmd",
  );
  expect(within(dialog).queryByRole("heading", {
    name: "Generated deployment manifest",
  })).not.toBeInTheDocument();
  fireEvent.change(within(dialog).getByLabelText("GitHub repository URL"), {target: {value: "owner/repository"}});
  fireEvent.click(within(dialog).getByRole("button", {name: "Validate deployment request"}));
  expect(within(dialog).getByText(/Use an HTTPS GitHub repository URL/)).toBeInTheDocument();
  fireEvent.change(within(dialog).getByLabelText("GitHub repository URL"), {
    target: {value: "https://github.com/owner/repository"},
  });
  fireEvent.click(within(dialog).getByRole("button", {name: "Validate deployment request"}));
  expect(within(dialog).getByText(/request is ready for owner\/repository/)).toBeInTheDocument();
});

test("dispatches a validated GitHub Actions deployment", async () => {
  const candidates = [{
    workflow: "orders.yxmd", target: "dataflow", validation_state: "generated_unvalidated",
    code: "display(df)", diagnostics: [], deployable: true, definition_ready: true,
    runtime_ready: true, artifact_path: "orders", definition_files: ["dataflow-mashup.pq"],
  }];
  const request = vi.fn().mockResolvedValue({
    json: async () => ({
      deployment_id: "dispatch-1", repository: "owner/repository",
      target: "dataflow", status: "dispatched",
    }),
  });
  render(<Workspace page="workflows" navigate={vi.fn()} assessment={assessment} runId="test-ui"
    run={{id: "test-ui", snapshot_id: "snapshot-ui", status: "completed", processed: 2, total: 2, cache_hits: 0, error: null, result: assessment}}
    candidates={candidates} generating={false} generate={vi.fn()} theme="light" toggleTheme={vi.fn()}
    request={request}><span>Intake</span></Workspace>);
  fireEvent.click(screen.getByRole("button", {name: "Open workflow orders"}));
  const dialog = screen.getByRole("dialog");
  fireEvent.click(within(dialog).getByRole("tab", {name: "Fabric deployment"}));
  fireEvent.change(within(dialog).getByLabelText("GitHub repository URL"), {
    target: {value: "https://github.com/owner/repository"},
  });
  fireEvent.click(within(dialog).getByRole("button", {name: "Trigger GitHub Actions"}));
  expect(await within(dialog).findByRole("status")).toHaveTextContent(
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
  });
});

test("dispatches a validated GitLab CI deployment", async () => {
  const candidates = [{
    workflow: "orders.yxmd", target: "dataflow", validation_state: "generated_unvalidated",
    code: "display(df)", diagnostics: [], deployable: true, definition_ready: true,
    runtime_ready: true, artifact_path: "orders", definition_files: ["dataflow-mashup.pq"],
  }];
  const request = vi.fn().mockResolvedValue({
    json: async () => ({
      deployment_id: "901", project: "group/project", target: "dataflow",
      status: "dispatched", pipeline_url: "https://gitlab.com/group/project/-/pipelines/901",
    }),
  });
  render(<Workspace page="workflows" navigate={vi.fn()} assessment={assessment} runId="test-ui"
    run={{id: "test-ui", snapshot_id: "snapshot-ui", status: "completed", processed: 2, total: 2, cache_hits: 0, error: null, result: assessment}}
    candidates={candidates} generating={false} generate={vi.fn()} theme="light" toggleTheme={vi.fn()}
    request={request}><span>Intake</span></Workspace>);
  fireEvent.click(screen.getByRole("button", {name: "Open workflow orders"}));
  const dialog = screen.getByRole("dialog");
  fireEvent.click(within(dialog).getByRole("tab", {name: "Fabric deployment"}));
  fireEvent.change(within(dialog).getByLabelText("Deployment method"), {
    target: {value: "gitlab"},
  });
  expect(within(dialog).getByDisplayValue(".gitlab-ci.yml")).toBeInTheDocument();
  expect(within(dialog).getByDisplayValue(
    "Server-side GitLab project access token",
  )).toBeInTheDocument();
  fireEvent.change(within(dialog).getByLabelText("GitLab project URL"), {
    target: {value: "https://gitlab.com/group/project"},
  });
  fireEvent.click(within(dialog).getByRole("button", {name: "Trigger GitLab CI"}));
  expect(await within(dialog).findByText(/GitLab CI dataflow pipeline 901 triggered/))
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
  const request = vi.fn().mockResolvedValue({
    json: async () => ({
      deployment_id: "dispatch-bundle",
      repository: "owner/repository",
      target: "bundle",
      status: "dispatched",
    }),
  });
  render(<Workspace page="workflows" navigate={vi.fn()} assessment={mixedAssessment}
    runId="test-ui" run={{id: "test-ui", snapshot_id: "snapshot-ui", status: "completed",
      processed: 1, total: 1, cache_hits: 0, error: null, result: mixedAssessment}}
    candidates={candidates} generating={false} generate={vi.fn()} theme="light"
    toggleTheme={vi.fn()} request={request}><span>Intake</span></Workspace>);

  fireEvent.click(screen.getByRole("button", {name: "Open workflow mixed"}));
  const dialog = screen.getByRole("dialog");
  fireEvent.click(within(dialog).getByRole("tab", {name: "Fabric deployment"}));
  expect(within(dialog).getByLabelText("Deployment target")).toHaveValue("bundle");
  expect(within(dialog).getByRole("option", {name: "Fabric Data Pipeline"}))
    .toBeInTheDocument();
  fireEvent.change(within(dialog).getByLabelText("GitHub repository URL"), {
    target: {value: "https://github.com/owner/repository"},
  });
  fireEvent.click(within(dialog).getByRole("button", {name: "Trigger GitHub Actions"}));
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

test("groups assessment outputs into reports, packages, and code previews with clear summary", () => {
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
  render(<Workspace page="executive-summary" navigate={vi.fn()} assessment={assessment}
    runId="test-outputs" run={{id: "test-outputs", snapshot_id: "snapshot-outputs", status: "completed",
      processed: 2, total: 2, cache_hits: 0, error: null, result: assessment}}
    candidates={candidates} generating={false} generate={vi.fn()} theme="light"
    toggleTheme={vi.fn()} request={vi.fn()}><span>Intake</span></Workspace>);

  expect(screen.getByRole("heading", {name: "1. Assessment reports"})).toBeInTheDocument();
  expect(screen.getByRole("heading", {name: "2. Download Fabric packages"})).toBeInTheDocument();
  expect(screen.getByRole("heading", {name: "3. Preview generated code"})).toBeInTheDocument();
  expect(screen.getByText("Fabric Notebook previews (2)")).toBeInTheDocument();
  expect(screen.getByText("1 deployable · 1 manual scaffold")).toBeInTheDocument();
  expect(screen.getByText("Deployable definition")).toBeInTheDocument();
  expect(screen.getByText("Scaffold / manual rework")).toBeInTheDocument();
});

test("does not show snapshot error alert on Technical Details before an assessment runs", () => {
  render(<Workspace page="technical-details" navigate={vi.fn()} assessment={null} runId={null} run={null}
    candidates={[]} generating={false} generate={vi.fn()} theme="light" toggleTheme={vi.fn()}
    request={vi.fn()}><span>Intake</span></Workspace>);

  expect(screen.getByText("No technical evidence loaded.")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("defaults orchestration assets to a pipeline deployment", () => {
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
  render(<Workspace page="workflows" navigate={vi.fn()} assessment={orchestrationAssessment}
    runId="test-ui" run={null} candidates={[]} generating={false} generate={vi.fn()}
    theme="light" toggleTheme={vi.fn()}
    request={vi.fn().mockResolvedValue({json: async () => evidence})}>
    <span>Intake</span>
  </Workspace>);

  fireEvent.click(screen.getByRole("button", {name: "Open workflow tf_orders"}));
  const dialog = screen.getByRole("dialog");
  fireEvent.click(within(dialog).getByRole("tab", {name: "Fabric deployment"}));

  expect(within(dialog).getByLabelText("Deployment target")).toHaveValue("pipeline");
  expect(within(dialog).getByRole("option", {name: "Fabric Data Pipeline"}))
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
    if (path.includes("/deploy/github")) {
      return {
        json: async () => ({
          deployment_id: "dep-nav-1",
          repository: "owner/repo",
          target: "dataflow",
          status: "dispatched",
        }),
      };
    }
    return {json: async () => evidence};
  });
  render(<Workspace page="workflows" navigate={vi.fn()} assessment={assessment} runId="test-ui-nav"
    run={{id: "test-ui-nav", snapshot_id: "snapshot-ui", status: "completed", processed: 2, total: 2, cache_hits: 0, error: null, result: assessment}}
    candidates={candidates} generating={false} generate={vi.fn()} theme="light" toggleTheme={vi.fn()}
    request={request}><span>Intake</span></Workspace>);

  expect(within(screen.getByRole("navigation", {name: "Primary"})).getByRole("link", {name: "New Assessment"})).toBeInTheDocument();
  expect(screen.queryByRole("button", {name: "New assessment"})).not.toBeInTheDocument();
  expect(within(screen.getByRole("navigation", {name: "Mobile primary navigation"})).getByRole("link", {name: "Intake"})).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", {name: "Open workflow orders"}));
  const dialog = screen.getByRole("dialog");
  fireEvent.click(within(dialog).getByRole("tab", {name: "Fabric deployment"}));
  fireEvent.change(within(dialog).getByLabelText("GitHub repository URL"), {
    target: {value: "https://github.com/owner/repo"},
  });
  fireEvent.change(within(dialog).getByLabelText("Git ref"), {
    target: {value: "main"},
  });
  fireEvent.click(within(dialog).getByRole("button", {name: "Trigger GitHub Actions"}));
  expect(await within(dialog).findByRole("link", {name: /Open GitHub Actions runs/})).toHaveAttribute(
    "href",
    "https://github.com/owner/repo/actions",
  );

  fireEvent.click(within(dialog).getByRole("button", {name: "Next workflow →"}));
  expect(within(dialog).getByRole("heading", {name: "custom"})).toBeInTheDocument();
  expect(within(dialog).getByText("Manual rework required.")).toBeInTheDocument();
  expect(within(dialog).getByRole("button", {name: "Trigger GitHub Actions"})).toBeDisabled();
  expect(within(dialog).getByLabelText("GitHub repository URL")).toHaveValue("https://github.com/owner/repo");
  expect(within(dialog).getByLabelText("Git ref")).toHaveValue("main");
});
