import { type ChangeEvent, type DragEvent, useEffect, useRef, useState } from "react";
import { Workspace } from "./Workspace";
import "./styles.css";
import "./prototype.css";
import "./workspace.css";

type BrowseMode = "files" | "zip" | "folder";
type SourceType = "alteryx" | "informatica";
const RUN_STORAGE_KEY = "accelerator-run-v6";
export type Page =
  | "intake"
  | "executive-summary"
  | "workflows"
  | "migration-plan"
  | "technical-details";

type SourceMetadata = {
  source_platform?: string;
  source_product?: string;
  asset_type?: string;
};

type PreviewSummary = {
  snapshot_id: string;
  workflow_count: number;
  skipped_count: number;
  total_size_bytes: number;
  workflows: Array<{ display_path: string; sha256: string } & SourceMetadata>;
  skipped: Array<{ path: string; reason: string; detail: string }>;
};

export type RunResult = {
  id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  processed: number;
  total: number;
  cache_hits: number;
  error: string | null;
  result: AssessmentResult | null;
  snapshot_id?: string;
};

export type Candidate = {
  workflow: string;
  target: string;
  validation_state: string;
  code: string;
  diagnostics: string[];
  deployable: boolean;
  definition_ready: boolean;
  runtime_ready: boolean;
  artifact_path: string | null;
  definition_files: string[];
};

export type AssessmentResult = {
  workflow_count: number;
  failed_count: number;
  assessments: Array<{
    path: string;
    tool_count: number;
    connection_count: number;
    complexity_score: number;
    complexity_band: string;
    recommended_target: string;
    target_components?: string[];
    recommendation_reason: string;
    unsupported_tools: string[];
    migration_wave: string;
    estimated_effort_days: number;
    registry_version?: string;
    rules_version?: string;
    dependencies: string[];
    data_sources: string[];
    graph_schema_version: string;
    tools?: Array<{ name: string; count: number; support: string }>;
  } & SourceMetadata>;
  failures: string[];
  workflows?: Array<{display_path: string; sha256: string} & SourceMetadata>;
};

const sourceTypes: Array<{ id: SourceType; title: string; detail: string }> = [
  { id: "alteryx", title: "Alteryx", detail: "Designer workflows, macros, apps, and packages" },
  { id: "informatica", title: "Informatica", detail: "PowerCenter XML and IDMC export packages" },
];

const modes: Record<SourceType, Array<{ id: BrowseMode; title: string; detail: string }>> = {
  alteryx: [
    { id: "files", title: "Select file(s)", detail: ".yxmd, .yxmc, .yxwz, or .yxzp" },
    { id: "zip", title: "Select ZIP", detail: "Alteryx packages are scanned securely" },
    { id: "folder", title: "Select folder", detail: "Scan an Alteryx estate recursively" },
  ],
  informatica: [
    { id: "files", title: "Select XML", detail: "PowerCenter repository exports" },
    { id: "zip", title: "Select ZIP", detail: "PowerCenter or IDMC export packages" },
    { id: "folder", title: "Select folder", detail: "Scan Informatica exports recursively" },
  ],
};

const pages: Array<{ id: Page; label: string }> = [
  { id: "intake", label: "Intake" },
  { id: "executive-summary", label: "Portfolio" },
  { id: "workflows", label: "Workflows" },
  { id: "migration-plan", label: "Migration Plan" },
  { id: "technical-details", label: "Technical Details" },
];

export function App() {
  const [activePage, setActivePage] = useState<Page>(() => pageFromHash());
  const [sourceType, setSourceType] = useState<SourceType>("alteryx");
  const [selectedMode, setSelectedMode] = useState<BrowseMode>("files");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [preview, setPreview] = useState<PreviewSummary | null>(null);
  const [processing, setProcessing] = useState(false);
  const [assessing, setAssessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [assessment, setAssessment] = useState<AssessmentResult | null>(null);
  const [runId, setRunId] = useState(() => localStorage.getItem(RUN_STORAGE_KEY));
  const [run, setRun] = useState<RunResult | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [generating, setGenerating] = useState(false);
  const [theme, setTheme] = useState(() => localStorage.getItem("accelerator-theme") ?? "light");
  const selectionEpoch = useRef(0);
  const activeRunId = useRef(runId);
  const pendingDrop = useRef<File[] | null>(null);
  const droppedPaths = useRef(new Map<File, string>());
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const input = inputRef.current;
    if (!input) {
      return;
    }
    if (selectedMode === "folder") {
      input.setAttribute("webkitdirectory", "");
    } else {
      input.removeAttribute("webkitdirectory");
    }
    input.value = "";
    setSelectedFiles(pendingDrop.current ?? []);
    pendingDrop.current = null;
    setPreview(null);
    setError(null);
    setAssessment(null);
    selectionEpoch.current += 1;
  }, [selectedMode]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("accelerator-theme", theme);
  }, [theme]);

  useEffect(() => {
    if (!runId) return;
    const epoch = selectionEpoch.current;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function poll() {
      try {
        const response = await apiRequest(`/api/runs/${runId}`);
        const current: RunResult = await response.json();
        if (disposed || epoch !== selectionEpoch.current || activeRunId.current !== runId) return;
        setRun(current);
        if (current.status === "completed" && current.result) {
          setAssessment(current.result);
          setAssessing(false);
          if (pageFromHash() === "intake") {
            setActivePage("executive-summary");
            window.location.hash = "executive-summary";
          }
        } else if (current.status === "failed" || current.status === "cancelled") {
          setAssessing(false);
          setError(current.error ?? `Assessment ${current.status}`);
        } else {
          setAssessing(true);
          timer = setTimeout(poll, 500);
        }
      } catch (caught) {
        if (!disposed && epoch === selectionEpoch.current && activeRunId.current === runId) {
          setAssessing(false);
          setError(caught instanceof Error ? caught.message : "Could not restore the saved run");
        }
      }
    }
    void poll();
    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
    };
  }, [runId]);

  useEffect(() => {
    const updatePage = () => setActivePage(pageFromHash());
    window.addEventListener("hashchange", updatePage);
    return () => window.removeEventListener("hashchange", updatePage);
  }, []);

  const inputModes = modes[sourceType];
  const accept = sourceType === "alteryx"
    ? selectedMode === "zip" ? ".zip,.yxzp" : ".yxmd,.yxmc,.yxwz,.yxzp"
    : selectedMode === "zip" ? ".zip" : ".xml,.zip";
  const browseLabel = selectedMode === "folder" ? "folder" : selectedMode;

  function clearSelection() {
    selectionEpoch.current += 1;
    activeRunId.current = null;
    setRunId(null);
    setRun(null);
    setCandidates([]);
    setSelectedFiles([]);
    pendingDrop.current = null;
    droppedPaths.current.clear();
    setPreview(null);
    setError(null);
    setAssessment(null);
    setProcessing(false);
    setAssessing(false);
    setGenerating(false);
    if (inputRef.current) inputRef.current.value = "";
  }

  function isCurrent(epoch: number, identity: string | null) {
    return epoch === selectionEpoch.current && identity === activeRunId.current;
  }

  function changeMode(mode: BrowseMode) {
    if (mode === selectedMode) return;
    clearSelection();
    setSelectedMode(mode);
  }

  function changeSourceType(value: SourceType) {
    if (value === sourceType) return;
    clearSelection();
    setSourceType(value);
    setSelectedMode("files");
  }

  function chooseFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    clearSelection();
    setSelectedFiles(files);
    if (files.length) void reviewFiles(files, selectedMode);
  }

  async function receiveDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    const files = Array.from(event.dataTransfer.files);
    const entries = Array.from(event.dataTransfer.items ?? [])
      .map((item) => item.webkitGetAsEntry?.())
      .filter((entry): entry is FileSystemEntry => entry != null);
    clearSelection();
    const epoch = selectionEpoch.current;
    const identity = activeRunId.current;
    setProcessing(true);
    try {
      const collected = entries.length
        ? (await Promise.all(entries.map(readDroppedEntry))).flat()
        : files.map((file) => ({ file, path: file.name }));
      if (!isCurrent(epoch, identity)) return;
      const selected = collected.map((item) => item.file);
      droppedPaths.current = new Map(collected.map((item) => [item.file, item.path]));
      const mode: BrowseMode = entries.some((entry) => entry.isDirectory) ? "folder"
        : selected.length === 1 && selected[0].name.toLowerCase().endsWith(".zip") ? "zip" : "files";
      if (mode !== selectedMode) {
        pendingDrop.current = selected;
        setSelectedMode(mode);
        setTimeout(() => void reviewFiles(selected, mode), 0);
      } else {
        setSelectedFiles(selected);
        if (selected.length) await reviewFiles(selected, mode);
      }
      if (!selected.length) setError("No readable files were dropped. Use Browse to select a folder.");
    } catch (caught) {
      if (isCurrent(epoch, identity)) {
        setError(caught instanceof Error ? caught.message : "The dropped folder could not be read");
      }
    } finally {
      if (isCurrent(epoch, identity)) setProcessing(false);
    }
  }

  async function reviewFiles(files: File[], mode: BrowseMode) {
    if (files.length === 0) return;
    setProcessing(true);
    setError(null);
    setPreview(null);
    const epoch = selectionEpoch.current;
    const identity = activeRunId.current;
    try {
      const response = await apiRequest("/api/snapshots/upload", {
        method: "POST",
        body: uploadBody(files, mode),
      });
      if (!response.ok) {
        const contentType = response.headers.get("content-type") ?? "";
        const failure = contentType.includes("application/json")
          ? ((await response.json()) as { detail?: unknown })
          : { detail: await response.text() };
        throw new Error(
          typeof failure.detail === "string" && failure.detail.trim()
            ? failure.detail
            : response.status >= 500
              ? "The local processing service is unavailable. Start the API and try again."
              : "The selected input could not be processed",
        );
      }
      const summary: PreviewSummary = await response.json();
      const wrongType = summary.workflows.some((workflow) => {
        const platform = workflow.source_platform ?? "alteryx";
        return sourceType === "alteryx"
          ? platform !== "alteryx"
          : !platform.startsWith("informatica_");
      });
      if (wrongType) {
        throw new Error(
          `The selection contains ${sourceType === "alteryx" ? "Informatica" : "Alteryx"} `
          + `assets. Start a separate ${sourceType === "alteryx" ? "Informatica" : "Alteryx"} assessment.`,
        );
      }
      if (isCurrent(epoch, identity)) setPreview(summary);
    } catch (caught) {
      if (isCurrent(epoch, identity)) {
        setError(caught instanceof Error ? caught.message : "The selected input could not be processed");
      }
    } finally {
      if (isCurrent(epoch, identity)) setProcessing(false);
    }
  }

  function uploadBody(files: File[], mode: BrowseMode) {
    const body = new FormData();
    body.append("mode", mode);
    files.forEach((file) => {
      const relativePath =
        droppedPaths.current.get(file) ?? (mode === "folder" && file.webkitRelativePath
          ? file.webkitRelativePath
          : file.name);
      body.append("files", file, relativePath);
    });
    return body;
  }

  async function confirmAssessment() {
    if (!preview || preview.workflow_count === 0) return;
    setAssessing(true);
    setError(null);
    const epoch = selectionEpoch.current;
    const identity = activeRunId.current;
    try {
      const response = await apiRequest("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ snapshot_id: preview.snapshot_id }),
      });
      if (!response.ok) {
        throw new Error("The assessment could not be completed");
      }
      const current: RunResult = await response.json();
      if (!isCurrent(epoch, identity)) return;
      setRun(current);
      localStorage.setItem(RUN_STORAGE_KEY, current.id);
      activeRunId.current = current.id;
      setRunId(current.id);
    } catch (caught) {
      if (isCurrent(epoch, identity)) {
        setError(caught instanceof Error ? caught.message : "The assessment could not be completed");
        setAssessing(false);
      }
    }
  }

  async function generate(target: "notebook" | "dataflow" | "pipeline") {
    if (!runId) return;
    setGenerating(true);
    setError(null);
    const epoch = selectionEpoch.current;
    const identity = activeRunId.current;
    try {
      const response = await apiRequest(`/api/runs/${runId}/generate?target=${target}`, {
        method: "POST",
      });
      const generated: Candidate[] = await response.json();
      if (isCurrent(epoch, identity)) setCandidates(generated);
    } catch (caught) {
      if (isCurrent(epoch, identity)) {
        setError(caught instanceof Error ? caught.message : "Candidate generation failed");
      }
    } finally {
      if (isCurrent(epoch, identity)) setGenerating(false);
    }
  }

  async function cancelAssessment() {
    if (!runId) return;
    const epoch = selectionEpoch.current;
    const identity = activeRunId.current;
    try {
      const response = await apiRequest(`/api/runs/${runId}/cancel`, { method: "POST" });
      const current: RunResult = await response.json();
      if (!isCurrent(epoch, identity)) return;
      setRun(current);
      setAssessing(false);
    } catch (caught) {
      if (isCurrent(epoch, identity)) {
        setError(caught instanceof Error ? caught.message : "Cancellation failed");
      }
    }
  }

  return <Workspace
    page={activePage} navigate={destination => {
      setActivePage(destination);
      window.location.hash = destination;
      document.documentElement.scrollTop = 0;
    }}
    assessment={assessment} run={run} runId={runId} candidates={candidates}
    generating={generating} generate={generate} request={apiRequest}
    theme={theme} toggleTheme={() => setTheme(theme === "light" ? "dark" : "light")}
    status={<>
      {error && activePage !== "intake" && <div className="errorMessage" role="alert">{error}</div>}
      {run && (run.status === "queued" || run.status === "running") && <section className="runProgress" aria-label="Assessment progress">
        <p role="status">{run.status}: {run.processed} / {run.total} workflows</p>
        <button type="button" onClick={cancelAssessment}>Cancel assessment</button>
      </section>}
    </>}>
    <section className="content" id="intake" hidden={activePage !== "intake"}>
          <p className="eyebrow">NEW ASSESSMENT</p>
          <h1>Choose your ETL workflow type and source</h1>
          <p className="lede">
            Select local workflows for a secure pre-run inventory. You will review discovered,
            skipped, and duplicate items before assessment begins.
          </p>

          <div className="modeGrid twoColumn" role="radiogroup" aria-label="Workflow type">
            {sourceTypes.map((source, index) => (
              <button
                type="button"
                role="radio"
                id={`source-${source.id}`}
                tabIndex={sourceType === source.id ? 0 : -1}
                aria-checked={sourceType === source.id}
                className={`modeCard ${sourceType === source.id ? "selected" : ""}`}
                key={source.id}
                onClick={() => changeSourceType(source.id)}
                onKeyDown={(event) => {
                  const delta = ["ArrowRight", "ArrowDown"].includes(event.key) ? 1
                    : ["ArrowLeft", "ArrowUp"].includes(event.key) ? -1 : 0;
                  if (!delta) return;
                  event.preventDefault();
                  const next = sourceTypes[(index + delta + sourceTypes.length) % sourceTypes.length];
                  changeSourceType(next.id);
                  document.getElementById(`source-${next.id}`)?.focus();
                }}
              >
                <span className="modeIcon" aria-hidden="true">{source.id === "alteryx" ? "A" : "I"}</span>
                <strong>{source.title}</strong>
                <small>{source.detail}</small>
              </button>
            ))}
          </div>

          <div className="modeGrid" role="radiogroup" aria-label="Input mode">
            {inputModes.map((mode) => (
              <button
                type="button"
                role="radio"
                id={`mode-${mode.id}`}
                tabIndex={selectedMode === mode.id ? 0 : -1}
                aria-checked={selectedMode === mode.id}
                className={`modeCard ${selectedMode === mode.id ? "selected" : ""}`}
                key={mode.id}
                onClick={() => changeMode(mode.id)}
                onKeyDown={(event) => {
                  const delta = ["ArrowRight", "ArrowDown"].includes(event.key) ? 1
                    : ["ArrowLeft", "ArrowUp"].includes(event.key) ? -1 : 0;
                  if (!delta) return;
                  event.preventDefault();
                  const next = inputModes[(inputModes.findIndex((item) => item.id === mode.id) + delta + inputModes.length) % inputModes.length];
                  changeMode(next.id);
                  document.getElementById(`mode-${next.id}`)?.focus();
                }}
              >
                <span className="modeIcon" aria-hidden="true">
                  {mode.id === "folder" ? "▰" : mode.id === "zip" ? "ZIP" : "＋"}
                </span>
                <strong>{mode.title}</strong>
                <small>{mode.detail}</small>
              </button>
            ))}
          </div>

          <div
            className="dropZone"
            onDragOver={(event) => event.preventDefault()}
            onDrop={receiveDrop}
          >
            <strong>Browse or drag and drop</strong>
            <span>Inputs stay on this machine.</span>
            <input
              ref={inputRef}
              className="visuallyHidden"
              type="file"
              tabIndex={-1}
              accept={accept}
              multiple={selectedMode !== "zip"}
              onChange={chooseFiles}
              aria-label={`Choose ${browseLabel}`}
            />
            <button type="button" onClick={() => inputRef.current?.click()}>
              Browse {browseLabel}
            </button>
            <div className="selectionSummary" role="status" aria-live="polite">
              {processing
                ? "Reviewing selection…"
                : selectedFiles.length === 0
                ? "No items selected"
                : `${selectedFiles.length} item${selectedFiles.length === 1 ? "" : "s"} selected`}
            </div>
            {selectedFiles.length > 0 && (
              <ul className="selectedFiles" aria-label="Selected items">
                {selectedFiles.map((file) => (
                  <li key={`${file.name}-${file.size}-${file.lastModified}`}>{file.name}</li>
                ))}
              </ul>
            )}
          </div>

          {error && <div className="errorMessage" role="alert">{error}</div>}

          {preview && (
            <section className="previewCard" aria-labelledby="preview-title">
              <div>
                <p className="eyebrow">PRE-RUN SUMMARY</p>
                <h2 id="preview-title">Ready for assessment</h2>
              </div>
              <div className="previewMetrics">
                <div><strong>{preview.workflow_count}</strong><span>Workflows found</span></div>
                <div><strong>{preview.skipped_count}</strong><span>Items skipped</span></div>
                <div>
                  <strong>{(preview.total_size_bytes / 1024).toFixed(1)} KB</strong>
                  <span>Total workflow size</span>
                </div>
              </div>
              {preview.skipped.length > 0 && (
                <details>
                  <summary>Review skipped items</summary>
                  <ul>
                    {preview.skipped.map((item) => (
                      <li key={`${item.path}-${item.reason}`}>
                        {item.path}: {item.reason}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              <button
                type="button"
                className="confirmButton"
                disabled={assessing || preview.workflow_count === 0}
                onClick={confirmAssessment}
              >
                {assessing ? "Assessing…" : "Confirm and assess"}
              </button>
            </section>
          )}

          {assessment && selectedFiles.length === 0 && !preview && (
            <div className="notice">
              <strong>Active assessment loaded ({assessment.workflow_count} workflow{assessment.workflow_count === 1 ? "" : "s"}).</strong>{" "}
              Select new files above to start a fresh run, or{" "}
              <button
                type="button"
                className="link-button"
                onClick={() => {
                  setActivePage("executive-summary");
                  window.location.hash = "executive-summary";
                  document.documentElement.scrollTop = 0;
                }}
              >
                return to Portfolio →
              </button>
            </div>
          )}

          {assessment && (selectedFiles.length > 0 || Boolean(preview)) && (
            <section className="assessmentResults" aria-labelledby="assessment-title">
              <p className="eyebrow">ASSESSMENT COMPLETE</p>
              <h2 id="assessment-title">
                {assessment.workflow_count} workflow
                {assessment.workflow_count === 1 ? "" : "s"} assessed
              </h2>
              {assessment.assessments.map((item) => (
                <article className="workflowResult" key={item.path}>
                  <div>
                    <h3>{item.path}</h3>
                    <p>{item.recommendation_reason}</p>
                  </div>
                  <dl>
                    <div><dt>Tools</dt><dd>{item.tool_count}</dd></div>
                    <div><dt>Connections</dt><dd>{item.connection_count}</dd></div>
                    <div><dt>Complexity</dt><dd>{item.complexity_band} ({item.complexity_score})</dd></div>
                    <div><dt>Target</dt><dd>{item.recommended_target}</dd></div>
                  </dl>
                  {(item.target_components?.length ?? 0) > 1 && (
                    <p className="targetComponents">
                      Components: {item.target_components?.join(", ")}
                    </p>
                  )}
                </article>
              ))}
              {assessment.failures.map((failure) => (
                <p className="errorMessage" key={failure}>{failure}</p>
              ))}
            </section>
          )}

        </section>
  </Workspace>;
}

function pageFromHash(): Page {
  const aliases: Record<string, Page> = {
    portfolio: "executive-summary",
    plan: "migration-plan",
    technical: "technical-details",
  };
  const candidate = window.location.hash.slice(1);
  return aliases[candidate] ?? pages.find(page => page.id === candidate)?.id
    ?? "executive-summary";
}

async function apiRequest(
  path: string, init: RequestInit = {}, refreshed = false,
): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.method && init.method !== "GET") {
    let token = sessionStorage.getItem("accelerator-token");
    if (!token) {
      const session = await fetch("/api/session");
      if (!session.ok) throw new Error("The local processing service is unavailable");
      const body: { token: string } = await session.json();
      token = body.token;
      sessionStorage.setItem("accelerator-token", token);
    }
    headers.set("x-accelerator-token", token);
  }
  const response = await fetch(path, { ...init, headers });
  if (response.status === 403 && init.method && init.method !== "GET" && !refreshed) {
    sessionStorage.removeItem("accelerator-token");
    return apiRequest(path, init, true);
  }
  if (!response.ok) {
    const contentType = response.headers.get("content-type") ?? "";
    const body: { detail?: string | { message?: string } } = contentType.includes("application/json")
      ? await response.json()
      : { detail: await response.text() };
    const detail = typeof body.detail === "string" ? body.detail : body.detail?.message;
    throw Object.assign(
      new Error(detail || "The local processing service is unavailable. Start the API and try again."),
      {status: response.status},
    );
  }
  return response;
}

function directoryEntry(entry: FileSystemEntry): entry is FileSystemDirectoryEntry {
  return entry.isDirectory;
}

function fileEntry(entry: FileSystemEntry): entry is FileSystemFileEntry {
  return entry.isFile;
}

async function readDroppedEntry(entry: FileSystemEntry): Promise<Array<{file: File; path: string}>> {
  if (fileEntry(entry)) {
    const file = await new Promise<File>((resolve, reject) => entry.file(resolve, reject));
    return [{file, path: entry.fullPath.replace(/^\/+/, "")}];
  }
  if (directoryEntry(entry)) {
    const reader = entry.createReader();
    const files: Array<{file: File; path: string}> = [];
    while (true) {
      const children = await new Promise<FileSystemEntry[]>((resolve, reject) => {
        reader.readEntries(resolve, reject);
      });
      if (!children.length) return files;
      for (const child of children) files.push(...await readDroppedEntry(child));
    }
  }
  throw new Error("Unsupported dropped item; use Browse to select workflows");
}
