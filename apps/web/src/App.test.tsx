import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { App } from "./App";

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  sessionStorage.setItem("accelerator-token", "test-token");
  window.location.hash = "#intake";
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

test("lets the analyst choose folder intake", () => {
  render(<App />);

  fireEvent.click(screen.getByRole("radio", { name: /select folder/i }));

  expect(screen.getByRole("radio", { name: /select folder/i })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  expect(screen.getByRole("button", { name: "Browse folder" })).toBeInTheDocument();
  expect(screen.getByLabelText("Choose folder")).toHaveAttribute("webkitdirectory");
});

test("allows only one workflow type at a time", () => {
  render(<App />);
  const workflowTypes = screen.getByRole("radiogroup", {name: "Workflow type"});

  expect(within(workflowTypes).getByRole("radio", {name: /Alteryx/}))
    .toHaveAttribute("aria-checked", "true");
  fireEvent.click(within(workflowTypes).getByRole("radio", {name: /Informatica/}));

  expect(within(workflowTypes).getByRole("radio", {name: /Informatica/}))
    .toHaveAttribute("aria-checked", "true");
  expect(screen.getByLabelText("Choose files")).toHaveAttribute("accept", ".xml,.zip");
  expect(screen.getByRole("radio", {name: /Select XML/})).toBeInTheDocument();
});

test("rejects a workflow from the other selected platform", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        snapshot_id: "snapshot",
        workflow_count: 1,
        skipped_count: 0,
        total_size_bytes: 12,
        workflows: [{
          display_path: "repository.xml",
          sha256: "abc",
          source_platform: "informatica_powercenter",
        }],
        skipped: [],
      }),
    }),
  );
  render(<App />);

  fireEvent.change(screen.getByLabelText("Choose files"), {
    target: {files: [new File(["<POWERMART/>"], "repository.xml")]},
  });

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Start a separate Informatica assessment",
  );
  expect(screen.queryByRole("heading", {name: "Ready for assessment"}))
    .not.toBeInTheDocument();
});

test("accepts Informatica input after selecting Informatica", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        snapshot_id: "snapshot",
        workflow_count: 1,
        skipped_count: 0,
        total_size_bytes: 12,
        workflows: [{
          display_path: "repository.xml",
          sha256: "abc",
          source_platform: "informatica_powercenter",
        }],
        skipped: [],
      }),
    }),
  );
  render(<App />);
  fireEvent.click(within(
    screen.getByRole("radiogroup", {name: "Workflow type"}),
  ).getByRole("radio", {name: /Informatica/}));

  fireEvent.change(screen.getByLabelText("Choose files"), {
    target: {files: [new File(["<POWERMART/>"], "repository.xml")]},
  });

  expect(await screen.findByRole("heading", {name: "Ready for assessment"}))
    .toBeInTheDocument();
});

test("rejects external-source assets on the built-in intake", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        snapshot_id: "snapshot",
        workflow_count: 1,
        skipped_count: 0,
        total_size_bytes: 12,
        workflows: [{
          display_path: "plugin.zip!package.dtsx",
          sha256: "abc",
          source_platform: "informatica_example",
        }],
        skipped: [],
      }),
    }),
  );
  render(<App />);
  fireEvent.click(within(
    screen.getByRole("radiogroup", {name: "Workflow type"}),
  ).getByRole("radio", {name: /Informatica/}));
  fireEvent.click(screen.getByRole("radio", {name: /Select ZIP/}));
  fireEvent.change(screen.getByLabelText("Choose zip"), {
    target: {files: [new File(["zip"], "plugin.zip")]},
  });

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "External source plugins cannot be assessed from this page yet",
  );
  expect(screen.queryByRole("heading", {name: "Ready for assessment"}))
    .not.toBeInTheDocument();
});

test("evaluates an installed target for a restored external-source run", async () => {
  sessionStorage.setItem("accelerator-run-v6", "plugin-run");
  window.location.hash = "#fabric-deployment";
  const workflow = {
    display_path: "package.dtsx",
    sha256: "abc",
    source_platform: "ssis",
  };
  const responses: Record<string, unknown> = {
    "/api/runs/plugin-run/status": {
      id: "plugin-run", status: "completed", processed: 1, total: 1,
      error: null, result: {workflow_count: 0, failed_count: 1, assessments: [],
        failures: ["Fabric assessment does not support source"], workflows: [workflow]},
    },
    "/api/runs/plugin-run": {
      id: "plugin-run", status: "completed", processed: 1, total: 1,
      error: null, result: {workflow_count: 0, failed_count: 1, assessments: [],
        failures: ["Fabric assessment does not support source"], workflows: [workflow]},
    },
    "/api/runs/plugin-run/neutral-assessment": {
      workflow_count: 1, failed_count: 0, failures: [],
      assessments: [{
        path: "package.dtsx!Package", name: "Package", source_platform: "ssis",
        source_product: "Synthetic SSIS", component_count: 2, connection_count: 0,
        complexity_score: 2, complexity_band: "Low", intrinsic_effort_days: 1,
        unknown_components: ["ssis_unverified_task"], inventory: [],
      }],
    },
    "/api/targets": {targets: [
      {platform_id: "databricks", display_name: "Synthetic Databricks",
        provider_version: "0.1.0", supported_ir_versions: ["1.1.0"], implemented: true,
        status: "ready", capabilities: ["evaluate"], description: "Manual review"},
      {platform_id: "snowflake", display_name: "Snowflake", provider_version: "1.0.0",
        supported_ir_versions: ["1.0.0"], implemented: false, status: "placeholder",
        capabilities: [], description: ""},
    ]},
    "/api/runs/plugin-run/targets/databricks/evaluate": [{
      source_path: "package.dtsx", asset_id: "1", asset_name: "Package",
      provider_version: "0.1.0",
      evaluation: {platform_id: "databricks", recommended_target: "Manual review",
        recommendation_reason: "Needs validation", diagnostics: ["Synthetic only"]},
    }],
  };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/targets/databricks/evaluate") && !init?.method) return {
      ok: false, status: 404, headers: new Headers({"content-type": "application/json"}),
      json: async () => ({detail: "No saved evaluation exists"}),
    };
    if (!(url in responses)) throw new Error(`Unexpected request: ${url}`);
    return {ok: true, json: async () => responses[url]};
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);

  expect(await screen.findByRole("heading", {name: "Target-neutral assessment"}))
    .toBeInTheDocument();
  expect(await screen.findByText("ssis_unverified_task")).toBeInTheDocument();
  expect(screen.queryByRole("link", {name: "Fabric Deployment"})).not.toBeInTheDocument();
  expect(await screen.findByRole("option", {name: "Synthetic Databricks"})).toBeInTheDocument();
  expect(screen.queryByRole("option", {name: "Snowflake"})).not.toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", {name: "Evaluate target"}));
  expect(await screen.findByRole("heading", {name: "Package: Manual review"})).toBeInTheDocument();
  expect(screen.getByText("Synthetic only")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/runs/plugin-run/targets/databricks/evaluate",
    expect.objectContaining({method: "POST"}),
  );
  expect(fetchMock).not.toHaveBeenCalledWith(
    expect.stringContaining("/previews"), expect.anything(),
  );
  fireEvent.change(screen.getByLabelText("Filter neutral assets"), {
    target: {value: "missing"},
  });
  expect(screen.queryByRole("heading", {name: "Package"})).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Filter neutral assets"), {
    target: {value: ""},
  });
  expect(await screen.findByRole("heading", {name: "Package"})).toBeInTheDocument();
});

test("restores external runs into the neutral workspace and reports target failures", async () => {
  sessionStorage.setItem("accelerator-run-v6", "saved-plugin");
  window.location.hash = "#fabric-deployment";
  const workflow = {
    display_path: "source.dtsx", sha256: "abc", source_platform: "ssis",
  };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/runs/saved-plugin" || url === "/api/runs/saved-plugin/status") {
      return {ok: true, json: async () => ({
        id: "saved-plugin", status: "completed", processed: 1, total: 1,
        result: {workflow_count: 0, failed_count: 1, assessments: [], failures: [],
          workflows: [workflow]},
      })};
    }
    if (url.endsWith("/neutral-assessment")) return {ok: true, json: async () => ({
      workflow_count: 1, failed_count: 0, failures: [], assessments: [{
        path: "source.dtsx!Package", name: "Package", source_platform: "ssis",
        source_product: "Synthetic SSIS", component_count: 1, connection_count: 0,
        complexity_score: 1, complexity_band: "Low", intrinsic_effort_days: 1,
        unknown_components: ["unknown"],
      }],
    })};
    if (url === "/api/targets") return {ok: true, json: async () => ({targets: [{
      platform_id: "fabric", display_name: "Microsoft Fabric", provider_version: "1.0.0",
      supported_ir_versions: ["1.0.0"], implemented: true, status: "ready",
      capabilities: ["evaluate"], description: "",
    }]})};
    if (url.endsWith("/targets/fabric/evaluate") && !init?.method) return {
      ok: false, status: 404, headers: new Headers({"content-type": "application/json"}),
      json: async () => ({detail: "No saved evaluation exists"}),
    };
    if (url.endsWith("/targets/fabric/evaluate") && init?.method === "POST") return {
      ok: false, status: 409, headers: new Headers({"content-type": "application/json"}),
      json: async () => ({detail: "Target platform does not support IR version 1.1.0"}),
    };
    throw new Error(`Unexpected request: ${url}`);
  }));
  render(<App />);
  expect(await screen.findByText("unknown")).toBeInTheDocument();
  expect(screen.queryByRole("link", {name: "Fabric Deployment"})).not.toBeInTheDocument();
  expect(await screen.findByRole("option", {name: "Microsoft Fabric"})).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", {name: "Evaluate target"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("does not support IR version");
  fireEvent.click(screen.getByRole("button", {name: "New assessment"}));
  expect(screen.getByRole("heading", {name: "Choose your ETL workflow type and source"}))
    .toBeInTheDocument();
  expect(sessionStorage.getItem("accelerator-run-v6")).toBeNull();
});

test("supports keyboard selection of input modes", () => {
  render(<App />);
  fireEvent.keyDown(screen.getByRole("radio", { name: /Select file/ }), { key: "ArrowRight" });
  const zip = screen.getByRole("radio", { name: /Select ZIP/ });
  expect(zip).toHaveAttribute("aria-checked", "true");
  expect(zip).toHaveFocus();
});

test("polls the lightweight run status and loads the full result once", async () => {
  const requests: string[] = [];
  let statusPolls = 0;
  const full = completedRun();
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    requests.push(`${init?.method ?? "GET"} ${url}`);
    if (url === "/api/snapshots/upload") return {ok: true, json: async () => ({
      snapshot_id: "snapshot", workflow_count: 1, skipped_count: 0, total_size_bytes: 12,
      workflows: [{display_path: "orders.yxmd", sha256: "abc"}], skipped: [],
    })};
    if (url === "/api/runs") return {ok: true, json: async () => ({
      id: "saved-run", status: "queued", processed: 0, total: 1, cache_hits: 0,
      error: null, result: null,
    })};
    if (url === "/api/runs/saved-run/status") {
      statusPolls += 1;
      return {ok: true, json: async () => ({
        id: "saved-run", snapshot_id: "snapshot", processed: 1, total: 1, cache_hits: 0,
        error: null, status: statusPolls < 2 ? "running" : "completed",
      })};
    }
    if (url === "/api/runs/saved-run") return {ok: true, json: async () => full};
    return {
      ok: false, status: 404, headers: new Headers({"content-type": "application/json"}),
      json: async () => ({detail: "Not mocked"}),
    };
  }));
  render(<App />);
  fireEvent.change(screen.getByLabelText("Choose files"), {
    target: {files: [new File(["<Workflow />"], "orders.yxmd")]},
  });
  fireEvent.click(await screen.findByRole("button", {name: "Confirm and assess"}));

  expect(await screen.findByRole(
    "heading", {name: "Portfolio Migration Summary"}, {timeout: 4000},
  )).toBeInTheDocument();
  expect(statusPolls).toBe(2);
  expect(requests.filter(request => request === "GET /api/runs/saved-run")).toHaveLength(1);
});

test("offers only the Alteryx and Informatica workflow types", () => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);

  const types = within(screen.getByRole("radiogroup", {name: "Workflow type"}))
    .getAllByRole("radio");
  expect(types).toHaveLength(2);
  expect(screen.queryByRole("radio", {name: /Installed plugins/})).not.toBeInTheDocument();
  expect(fetchMock).not.toHaveBeenCalled();
});

test("recursively reads a dropped folder and preserves upload paths", async () => {
  const workflow = new File(["<AlteryxDocument/>"], "orders.yxmd");
  const entry = {
    isFile: true, isDirectory: false, fullPath: "/estate/nested/orders.yxmd",
    file: (success: (file: File) => void) => success(workflow),
  };
  let reads = 0;
  const directory = {
    isDirectory: true, isFile: false,
    createReader: () => ({
      readEntries: (success: (entries: object[]) => void) => success(reads++ ? [] : [entry]),
    }),
  };
  const fetchMock = vi.fn(async (path: string, init: RequestInit) => {
    expect(path).toBe("/api/snapshots/upload");
    expect(init.method).toBe("POST");
    return {
    ok: true,
    json: async () => ({
      snapshot_id: "snapshot", workflow_count: 1, skipped_count: 0,
      total_size_bytes: 18,
      workflows: [{
        display_path: "estate/nested/orders.yxmd",
        sha256: "abc",
        source_platform: "alteryx",
      }],
      skipped: [],
    }),
    };
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);
  await act(async () => {
    fireEvent.drop(screen.getByText("Browse or drag and drop").parentElement!, {
      dataTransfer: { files: [], items: [{ webkitGetAsEntry: () => directory }] },
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  await screen.findByText("1 item selected");
  expect(screen.getByRole("radio", { name: /Select folder/ })).toHaveAttribute("aria-checked", "true");
  await screen.findByRole("heading", { name: "Ready for assessment" });
  const body = fetchMock.mock.calls[0][1].body;
  if (!(body instanceof FormData)) throw new Error("Expected multipart upload");
  const file = body.get("files");
  if (!(file instanceof File)) throw new Error("Expected workflow file");
  expect(file.name).toBe("estate/nested/orders.yxmd");
});

test("opens the active browser selector and automatically reviews selected files", () => {
  const click = vi.spyOn(HTMLInputElement.prototype, "click").mockImplementation(() => undefined);
  render(<App />);

  fireEvent.click(screen.getByRole("button", { name: "Browse files" }));
  expect(click).toHaveBeenCalledOnce();

  const workflow = new File(["<Workflow />"], "sample.yxmd", { type: "application/xml" });
  fireEvent.change(screen.getByLabelText("Choose files"), {
    target: { files: [workflow] },
  });

  expect(screen.getByRole("status")).toHaveTextContent("Reviewing selection");
  expect(screen.getByText("sample.yxmd")).toBeInTheDocument();
});

test("keeps and automatically reviews dropped files", () => {
  render(<App />);
  const workflow = new File(["<Workflow />"], "sample.yxmd");
  const notes = new File(["notes"], "notes.txt");

  fireEvent.drop(screen.getByText("Browse or drag and drop").parentElement!, {
    dataTransfer: { files: [workflow, notes] },
  });

  expect(screen.getByRole("status")).toHaveTextContent("Reviewing selection");
  expect(screen.getByText("sample.yxmd")).toBeInTheDocument();
  expect(screen.getByText("notes.txt")).toBeInTheDocument();
});

test("reviews selected files and shows the pre-run summary", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        snapshot_id: "snapshot",
        workflow_count: 1,
        skipped_count: 0,
        total_size_bytes: 12,
        workflows: [{ display_path: "sample.yxmd", sha256: "abc" }],
        skipped: [],
      }),
    }),
  );
  render(<App />);
  const workflow = new File(["<Workflow />"], "sample.yxmd");
  fireEvent.change(screen.getByLabelText("Choose files"), {
    target: { files: [workflow] },
  });

  expect(await screen.findByRole("heading", { name: "Ready for assessment" })).toBeInTheDocument();
  expect(screen.getByText("1", { selector: "strong" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Confirm and assess" })).toBeInTheDocument();
});

test("shows an actionable error when the processing service is unavailable", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      headers: new Headers({ "content-type": "text/plain" }),
      text: async () => "",
    }),
  );
  render(<App />);
  fireEvent.change(screen.getByLabelText("Choose files"), {
    target: { files: [new File(["<Workflow />"], "sample.yxmd")] },
  });

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The local processing service is unavailable",
  );
});

test("confirms and displays deterministic assessment results", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        snapshot_id: "snapshot",
        workflow_count: 1,
        skipped_count: 0,
        total_size_bytes: 12,
        workflows: [{ display_path: "sample.yxmd", sha256: "abc" }],
        skipped: [],
      }),
    })
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        id: "run-1", status: "queued", processed: 0, total: 1, cache_hits: 0,
        error: null, result: null,
      }),
    })
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        id: "run-1", status: "completed", processed: 1, total: 1, cache_hits: 0,
        error: null,
        result: {
        workflow_count: 1,
        failed_count: 0,
        assessments: [
          {
            path: "sample.yxmd",
            tool_count: 2,
            connection_count: 1,
            complexity_score: 3,
            complexity_band: "Low",
            recommended_target: "Dataflow Gen2",
            target_components: ["Dataflow Gen2"],
            recommendation_reason: "All detected tools have deterministic Power Query mappings",
            unsupported_tools: [],
            migration_wave: "Wave 1",
            estimated_effort_days: 0.6,
            registry_version: "2026.11.1",
            rules_version: "1.1.0",
            dependencies: [], data_sources: [], graph_schema_version: "1.1.0",
            tools: [{ name: "Filter", count: 2, support: "dataflow" }],
          },
        ],
        failures: [],
        },
      }),
    });

  vi.stubGlobal("fetch", fetchMock);
  render(<App />);
  fireEvent.change(screen.getByLabelText("Choose files"), {
    target: { files: [new File(["<Workflow />"], "sample.yxmd")] },
  });
  await screen.findByRole("heading", { name: "Ready for assessment" });

  fireEvent.click(screen.getByRole("button", { name: "Confirm and assess" }));

  expect(
    await screen.findByRole("heading", { name: "Portfolio Migration Summary" }),
  ).toBeInTheDocument();
  expect(screen.getAllByText("Dataflow Gen2").length).toBeGreaterThan(0);

  fireEvent.click(within(screen.getByRole("navigation", {name: "Primary"})).getByRole("link", { name: "Workflows" }));
  expect(screen.getByRole("heading", { name: "Workflow Assessment Register" })).toBeInTheDocument();

  fireEvent.click(screen.getByRole("link", { name: "Migration Plan" }));
  expect(screen.getByRole("heading", { name: "Evidence-Based Migration Plan" })).toBeInTheDocument();

  fireEvent.click(screen.getByRole("link", { name: "Technical Details" }));
  expect(screen.getByRole("heading", { name: "Technical Assessment Evidence" })).toBeInTheDocument();
});

test("starts a new browser session at Intake with no active portfolio", () => {
  window.location.hash = "";
  render(<App />);

  const portfolio = document.getElementById("portfolio-analysis");
  if (!portfolio) throw new Error("Missing portfolio analysis");
  expect(portfolio).not.toHaveClass("active");
  expect(screen.getByRole("heading", {
    name: "Choose your ETL workflow type and source",
  })).toBeInTheDocument();
  expect(window.location.hash).toBe("#intake");
  expect(within(screen.getByRole("navigation", {name: "Primary"})).getByRole(
    "link", {name: "New Assessment"},
  )).toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("switches and persists the color theme", () => {
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Switch color theme" }));
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(localStorage.getItem("accelerator-theme")).toBe("dark");
});

test("does not expose server-local path controls", () => {
  render(<App />);
  expect(screen.queryByText("Large estate on this machine")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", {name: "Review local path"})).not.toBeInTheDocument();
  expect(screen.queryByText("Untrusted input protection")).not.toBeInTheDocument();
});

function completedRun() {
  return {
    id: "saved-run", status: "completed", processed: 1, total: 1,
    cache_hits: 0, error: null,
    result: {
      workflow_count: 1, failed_count: 0, failures: [],
      assessments: [{
        path: "orders.yxmd", tool_count: 2, connection_count: 1,
        complexity_score: 3, complexity_band: "Low",
        recommended_target: "Dataflow Gen2", target_components: ["Dataflow Gen2"],
        recommendation_reason: "Static recommendation", unsupported_tools: [],
        migration_wave: "Wave 1", estimated_effort_days: 0.6,
        registry_version: "2026.11.2", rules_version: "1.2.0",
        dependencies: [], data_sources: [], graph_schema_version: "1.1.0",
      }],
    },
  };
}

function targetCatalog() {
  return {targets: [{
    platform_id: "fabric", display_name: "Microsoft Fabric", provider_version: "1.0.0",
    supported_ir_versions: ["1.0.0"], implemented: true, status: "ready",
    capabilities: ["evaluate", "capacity", "codegen", "dry_run"], description: "Fabric",
  }]};
}

test("does not restore a run saved in persistent browser storage", () => {
  localStorage.setItem("accelerator-run-v6", "persistent-run");
  localStorage.setItem("accelerator-run-v5", "stale-run");
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);

  render(<App />);

  expect(fetchMock).not.toHaveBeenCalled();
  expect(localStorage.getItem("accelerator-run-v6")).toBeNull();
  expect(screen.getByRole("heading", {
    name: "Choose your ETL workflow type and source",
  })).toBeInTheDocument();
});

test("restores a run within the same browser session and offers real exports", async () => {
  sessionStorage.setItem("accelerator-run-v6", "saved-run");
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => ({
    ok: true, json: async () => String(input).includes("/api/targets") ? targetCatalog() : completedRun(),
  })));
  render(<App />);
  await screen.findByRole("heading", { name: "Portfolio Migration Summary" });
  await screen.findByText(
    "1 ETL assets are in scope. Static recommendations require validation.",
  );
  const portfolio = document.getElementById("portfolio-analysis");
  if (!portfolio) throw new Error("Missing portfolio analysis");
  expect(within(portfolio).getByRole("link", {
    name: "Export CSV",
    hidden: true,
  })).toHaveAttribute(
    "href", "/api/runs/saved-run/export?format=csv",
  );
  expect(within(portfolio).getByRole("button", {
    name: "Open Fabric Deployment →",
    hidden: true,
  })).toBeInTheDocument();
  const deploySection = document.getElementById("fabric-deployment");
  if (!deploySection) throw new Error("Missing fabric deployment section");
  fireEvent.click(within(screen.getByRole("navigation", {name: "Primary"})).getByRole(
    "link", {name: "Fabric Deployment"},
  ));
  expect(await within(deploySection).findByRole("link", {
    name: "Download Notebook package",
    hidden: true,
  })).toHaveAttribute(
    "href", "/api/runs/saved-run/candidates?target=notebook",
  );
});

test("preserves the requested workspace page while restoring a completed run", async () => {
  window.location.hash = "#workflows";
  sessionStorage.setItem("accelerator-run-v6", "saved-run");
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: true, json: async () => completedRun(),
  }));

  render(<App />);

  await screen.findByRole("heading", {name: "Workflow Assessment Register"});
  expect(window.location.hash).toBe("#workflows");
  expect(within(screen.getByRole("navigation", {name: "Primary"})).getByRole(
    "link", {name: "Workflows"},
  )).toHaveAttribute(
    "aria-current", "page",
  );
});

test("generates and displays explicit unvalidated review candidates on Fabric Deployment tab", async () => {
  sessionStorage.setItem("accelerator-run-v6", "saved-run");
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => completedRun() })
    .mockResolvedValueOnce({
      ok: true, json: async () => ({
        scenarios: [], workflows: [], assumptions: [],
      }),
    })
    .mockResolvedValueOnce({
      ok: true, json: async () => ({
        targets: [
          {
            platform_id: "fabric",
            display_name: "Microsoft Fabric",
            provider_version: "1.0.0",
            supported_ir_versions: ["1.0.0"],
            implemented: true,
            status: "ready",
            capabilities: ["evaluate", "capacity", "codegen", "dry_run"],
            description: "Microsoft Fabric provider",
          },
          {
            platform_id: "databricks",
            display_name: "Azure Databricks",
            provider_version: "1.0.0",
            supported_ir_versions: ["1.0.0"],
            implemented: true,
            status: "ready",
            capabilities: ["evaluate"],
            description: "Evaluate-only provider",
          },
        ],
      }),
    })
    .mockResolvedValueOnce({
      ok: true, json: async () => [{
        workflow: "orders.yxmd", target: "notebook",
        validation_state: "generated_unvalidated", code: "display(df)", diagnostics: [],
        deployable: true, definition_ready: true, runtime_ready: true,
        artifact_path: "orders-abc", definition_files: ["notebook-content.ipynb"],
      }],
    }));
  render(<App />);
  await screen.findByRole("heading", {name: "Portfolio Migration Summary"});
  expect(screen.queryByRole("button", { name: "Generate Notebook code" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Open Fabric Deployment →" })).toBeInTheDocument();

  fireEvent.click(within(screen.getByRole("navigation", { name: "Primary" })).getByRole("link", { name: "Fabric Deployment" }));
  expect(await screen.findByRole("heading", { name: "Fabric Code Generation & Deployment" })).toBeInTheDocument();
  expect(screen.getByRole("radio", { name: /Azure Databricks/ })).toBeDisabled();
  expect(screen.getByText("Not integrated for generation")).toBeInTheDocument();

  fireEvent.click(await screen.findByRole("button", { name: "Generate Notebook code" }));
  expect(await screen.findByRole("heading", {
    name: "orders.yxmd: generated_unvalidated",
  })).toBeInTheDocument();
  expect(screen.getByText("display(df)")).toBeInTheDocument();
});

test("discards a late generation response after the analyst changes selection", async () => {
  type PreviewResponse = {
    ok: boolean;
    json: () => Promise<Array<{
      workflow: string; target: string; validation_state: string; code: string; diagnostics: string[];
      deployable: boolean; definition_ready: boolean; runtime_ready: boolean;
      artifact_path: string | null; definition_files: string[];
    }>>;
  };
  let resolveResponse!: (response: PreviewResponse) => void;
  const pending = new Promise<PreviewResponse>((resolve) => { resolveResponse = resolve; });
  sessionStorage.setItem("accelerator-run-v6", "saved-run");
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/runs/saved-run/previews")) {
      return pending as unknown as Response;
    }
    if (url.includes("/api/targets")) {
      return { ok: true, json: async () => targetCatalog() } as unknown as Response;
    }
    if (url.includes("/capacity")) {
      return { ok: true, json: async () => ({ scenarios: [], workflows: [], assumptions: [] }) } as unknown as Response;
    }
    return { ok: true, json: async () => completedRun() } as unknown as Response;
  }));
  render(<App />);
  await screen.findByRole("heading", {name: "Portfolio Migration Summary"});
  fireEvent.click(within(screen.getByRole("navigation", { name: "Primary" })).getByRole("link", { name: "Fabric Deployment" }));
  fireEvent.click(await screen.findByRole("button", { name: "Generate Notebook code" }));
  fireEvent.click(within(screen.getByRole("navigation", { name: "Primary" })).getByRole("link", { name: "New Assessment" }));
  expect(sessionStorage.getItem("accelerator-run-v6")).toBeNull();
  fireEvent.click(screen.getByRole("radio", { name: /Select folder/ }));
  await act(async () => {
    resolveResponse({
      ok: true, json: async () => [{
        workflow: "stale-workflow", target: "notebook",
        validation_state: "generated_unvalidated", code: "stale code", diagnostics: [],
        deployable: true, definition_ready: true, runtime_ready: true,
        artifact_path: "stale", definition_files: ["notebook-content.ipynb"],
      }],
    });
  });
  expect(screen.queryByText("stale code")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Browse folder" })).toBeInTheDocument();
});

function routedRun(basis: "static_mapping" | "compiler_confirmed") {
  const run = completedRun();
  const confirmed = basis === "compiler_confirmed";
  return {
    ...run,
    routing_basis: basis,
    result: {
      ...run.result,
      assessments: [{
        ...run.result.assessments[0],
        recommended_target: confirmed ? "Fabric Notebook" : "Dataflow Gen2",
        target_components: confirmed ? ["Fabric Notebook"] : ["Dataflow Gen2"],
        recommendation_reason: confirmed ? "Confirmed by the compiler" : "Static recommendation",
        estimated_effort_days: confirmed ? 1.4 : 0.6,
      }],
    },
  };
}

// Serves the run as static until the Fabric evaluation is requested, as the API does.
function stubFitApi(options: { failEvaluate?: () => boolean } = {}) {
  let confirmed = false;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/targets/fabric/evaluate") && init?.method === "POST") {
      if (options.failEvaluate?.()) {
        return {
          ok: false, status: 409, headers: new Headers({"content-type": "application/json"}),
          json: async () => ({detail: "Fabric fit failed"}),
        };
      }
      confirmed = true;
      return {ok: true, json: async () => []};
    }
    if (url.includes("/api/targets")) return {ok: true, json: async () => targetCatalog()};
    if (url.includes("/capacity")) {
      return {ok: true, json: async () => ({scenarios: [], workflows: [], assumptions: []})};
    }
    return {ok: true, json: async () => routedRun(confirmed ? "compiler_confirmed" : "static_mapping")};
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    fetchMock,
    evaluations: () => fetchMock.mock.calls.filter(([url, init]) =>
      String(url).endsWith("/targets/fabric/evaluate") && init?.method === "POST"),
  };
}

function openPage(name: string) {
  fireEvent.click(within(screen.getByRole("navigation", {name: "Primary"})).getByRole(
    "link", {name},
  ));
}

// jsdom queues fragment navigations. Without this, ones left by an earlier test can arrive
// after this app changes the hash and send it back to the previous page.
async function settleNavigation() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

test("keeps portfolio assessment static until the analyst opens the Fabric step", async () => {
  await settleNavigation();
  sessionStorage.setItem("accelerator-run-v6", "saved-run");
  const api = stubFitApi();
  render(<App />);

  await screen.findByRole("heading", {name: "Portfolio Migration Summary"});
  expect(screen.getByTestId("routing-basis")).toHaveTextContent("Routing basis: static mapping");
  expect(screen.getByTestId("routing-basis")).toHaveTextContent("does not generate code");
  expect(api.evaluations()).toHaveLength(0);

  openPage("Workflows");
  await screen.findByRole("heading", {name: "Workflow Assessment Register"});
  expect(api.evaluations()).toHaveLength(0);
});

test("confirms Fabric routing once when the Fabric step opens and updates the portfolio", async () => {
  await settleNavigation();
  sessionStorage.setItem("accelerator-run-v6", "saved-run");
  const api = stubFitApi();
  render(<App />);
  await screen.findByRole("heading", {name: "Portfolio Migration Summary"});

  openPage("Fabric Deployment");
  await waitFor(() => expect(api.evaluations()).toHaveLength(1));

  openPage("Portfolio");
  expect(await screen.findByText("Routing basis: compiler-confirmed Fabric fit."))
    .toBeInTheDocument();
  expect(screen.getAllByText("Fabric Notebook").length).toBeGreaterThan(0);

  openPage("Fabric Deployment");
  openPage("Portfolio");
  expect(api.evaluations()).toHaveLength(1);
});

test("does not confirm routing for a run that has no recorded routing basis", async () => {
  await settleNavigation();
  sessionStorage.setItem("accelerator-run-v6", "saved-run");
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => ({
    ok: true, json: async () => String(input).includes("/api/targets") ? targetCatalog() : completedRun(),
  }));
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);
  await screen.findByRole("heading", {name: "Portfolio Migration Summary"});
  expect(screen.queryByTestId("routing-basis")).not.toBeInTheDocument();

  openPage("Fabric Deployment");
  await screen.findByRole("heading", {name: "Fabric Code Generation & Deployment"});

  expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/targets/fabric/evaluate")))
    .toBe(false);
});

test("reports a failed Fabric confirmation and retries on the next visit", async () => {
  await settleNavigation();
  sessionStorage.setItem("accelerator-run-v6", "saved-run");
  let failing = true;
  const api = stubFitApi({failEvaluate: () => failing});
  render(<App />);
  await screen.findByRole("heading", {name: "Portfolio Migration Summary"});

  openPage("Fabric Deployment");
  expect((await screen.findAllByText("Fabric fit failed")).length).toBeGreaterThan(0);
  expect(api.evaluations()).toHaveLength(1);

  failing = false;
  openPage("Portfolio");
  openPage("Fabric Deployment");
  await waitFor(() => expect(api.evaluations()).toHaveLength(2));
  openPage("Portfolio");
  expect(await screen.findByText("Routing basis: compiler-confirmed Fabric fit."))
    .toBeInTheDocument();
});

test("uses local folder picker without browser upload input when available and falls back on 501", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({"content-type": "application/json"}),
      json: async () => ({path: "C:\\workflows\\alteryx"}),
    })
    .mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({"content-type": "application/json"}),
      json: async () => ({
        snapshot_id: "b".repeat(64),
        workflow_count: 2,
        skipped_count: 0,
        total_size_bytes: 2048,
        workflows: [
          {display_path: "a.yxmd", sha256: "1", source_platform: "alteryx"},
          {display_path: "b.yxmd", sha256: "2", source_platform: "alteryx"},
        ],
        skipped: [],
      }),
    });
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);
  const fileInput = screen.getByLabelText("Choose files") as HTMLInputElement;
  const inputClickSpy = vi.spyOn(fileInput, "click");

  fireEvent.click(screen.getByRole("radio", { name: /Select folder/i }));
  fireEvent.click(screen.getByRole("button", { name: "Browse folder" }));

  expect(await screen.findByText("Ready for assessment")).toBeInTheDocument();
  expect(screen.getByText("1 folder selected")).toBeInTheDocument();
  expect(screen.getByText("C:\\workflows\\alteryx")).toBeInTheDocument();
  expect(inputClickSpy).not.toHaveBeenCalled();

  fetchMock.mockResolvedValueOnce({
    ok: false,
    status: 501,
    headers: new Headers({"content-type": "application/json"}),
    json: async () => ({detail: "Native folder picker is unavailable"}),
  });
  fireEvent.click(screen.getByRole("button", { name: "Browse folder" }));
  await act(async () => {
    await Promise.resolve();
  });
  expect(inputClickSpy).toHaveBeenCalledTimes(1);
});

test("NeutralWorkspace renders capability-driven codegen previews for codegen-capable targets", async () => {
  const { NeutralWorkspace } = await import("./NeutralWorkspace");
  const request = vi.fn(async (path: string) => {
    if (path === "/api/targets") {
      return {
        ok: true,
        json: async () => ({
          targets: [
            {
              platform_id: "databricks",
              display_name: "Databricks Plugin",
              provider_version: "1.0.0",
              supported_ir_versions: ["1.0.0", "1.1.0"],
              implemented: true,
              status: "ready",
              capabilities: ["evaluate", "codegen"],
              target_kinds: ["lakeflow", "notebook"],
              description: "Plugin target",
            },
          ],
        }),
      } as Response;
    }
    if (path.endsWith("/evaluate")) {
      const err = Object.assign(new Error("Not found"), { status: 404 });
      throw err;
    }
    if (path.includes("/generate?target_kind=lakeflow")) {
      return {
        ok: true,
        json: async () => [
          {
            platform_id: "databricks",
            provider_version: "1.0.0",
            target_kind: "lakeflow",
            artifacts: [
              {
                workflow: "pkg.dtsx!Orders",
                target_kind: "lakeflow",
                validation_state: "scaffold",
                translation_mode: "scaffold",
                deployable: false,
                files: { "lakeflow-source": "# synthetic scaffold" },
                diagnostics: ["Manual review required"],
                required_bindings: ["source_table"],
              },
            ],
          },
        ],
      } as Response;
    }
    throw new Error(`Unexpected path: ${path}`);
  });

  render(
    <NeutralWorkspace
      run={{
        id: "r1",
        status: "completed",
        processed: 1,
        total: 1,
        cache_hits: 0,
        error: null,
        result: null,
      }}
      runId="r1"
      assessment={{
        workflow_count: 1,
        failed_count: 0,
        assessments: [
          {
            path: "pkg.dtsx!Orders",
            name: "Orders",
            source_platform: "ssis",
            source_product: "Synthetic SSIS",
            component_count: 1,
            connection_count: 0,
            inventory: [{ operation: "ssis_task", count: 1, classification: "manual" }],
            complexity_score: 6,
            complexity_band: "Low",
            intrinsic_effort_days: 1.5,
            unknown_components: ["ssis_task"],
          },
        ],
        failures: [],
      }}
      error={null}
      request={request}
      cancel={async () => {}}
      startNew={() => {}}
    />,
  );

  const generateButton = await screen.findByRole("button", { name: "Generate target preview" });
  fireEvent.click(generateButton);
  expect(await screen.findByText("# synthetic scaffold")).toBeInTheDocument();
  expect(screen.getByText("Manual review required")).toBeInTheDocument();
});

