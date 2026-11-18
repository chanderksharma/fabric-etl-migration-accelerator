import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { App } from "./App";

beforeEach(() => {
  localStorage.clear();
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

test("supports keyboard selection of input modes", () => {
  render(<App />);
  fireEvent.keyDown(screen.getByRole("radio", { name: /Select file/ }), { key: "ArrowRight" });
  const zip = screen.getByRole("radio", { name: /Select ZIP/ });
  expect(zip).toHaveAttribute("aria-checked", "true");
  expect(zip).toHaveFocus();
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

test("opens the merged executive portfolio and provides an empty state", () => {
  window.location.hash = "";
  render(<App />);

  const portfolio = document.getElementById("portfolio-analysis");
  if (!portfolio) throw new Error("Missing portfolio analysis");
  expect(
    within(portfolio).getByRole("heading", { name: "Detailed Portfolio Assessment" }),
  ).toBeInTheDocument();
  expect(within(portfolio).getByText("No completed assessment.")).toBeInTheDocument();
  expect(within(screen.getByRole("navigation", {name: "Primary"})).getByRole(
    "link", {name: "Portfolio"},
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

test("does not restore a run saved by an older compiler generation", () => {
  localStorage.setItem("accelerator-run-v5", "stale-run");
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);

  render(<App />);

  expect(fetchMock).not.toHaveBeenCalled();
  expect(screen.getByRole("heading", {
    name: "Choose your ETL workflow type and source",
  })).toBeInTheDocument();
});

test("restores a saved run and offers real exports", async () => {
  localStorage.setItem("accelerator-run-v6", "saved-run");
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: true, json: async () => completedRun(),
  }));
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
  expect(within(portfolio).getByRole("link", {
    name: "Download Notebook package",
    hidden: true,
  })).toHaveAttribute(
    "href", "/api/runs/saved-run/candidates?target=notebook",
  );
});

test("preserves the requested workspace page while restoring a completed run", async () => {
  window.location.hash = "#workflows";
  localStorage.setItem("accelerator-run-v6", "saved-run");
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

test("generates and displays explicit unvalidated review candidates", async () => {
  localStorage.setItem("accelerator-run-v6", "saved-run");
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => completedRun() })
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
  fireEvent.click(await screen.findByRole("button", { name: "Generate Notebook previews" }));
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
  localStorage.setItem("accelerator-run-v6", "saved-run");
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => completedRun() })
    .mockReturnValueOnce(pending));
  render(<App />);
  await screen.findByRole("heading", {name: "Portfolio Migration Summary"});
  fireEvent.click(await screen.findByRole("button", { name: "Generate Notebook previews" }));
  fireEvent.click(within(screen.getByRole("navigation", { name: "Primary" })).getByRole("link", { name: "New Assessment" }));
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
