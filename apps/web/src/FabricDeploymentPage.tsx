import { useEffect, useMemo, useState } from "react";
import type { AssessmentResult, Candidate } from "./App";
import { Deployment } from "./workspace-deployment";
import { nameOf, waveLabel } from "./workspace-model";
import { parseTargetCatalog, type TargetPlatformInfo } from "./target-platform";

type Item = AssessmentResult["assessments"][number];
type Target = "notebook" | "dataflow" | "pipeline";

function canGenerateFabric(platform: TargetPlatformInfo): boolean {
  return platform.platform_id === "fabric" && platform.implemented &&
    platform.status === "ready" && platform.capabilities.includes("codegen");
}

type FabricDeploymentPageProps = {
  active: boolean;
  assessment: AssessmentResult | null;
  runId: string | null;
  candidates: Candidate[];
  generating: boolean;
  generate: (target: Target) => Promise<void>;
  confirmingFit?: boolean;
  request: (path: string, init?: RequestInit) => Promise<Response>;
  preselectedWorkflowPath?: string;
  onStartIntake: () => void;
};

export function FabricDeploymentPage({
  active,
  assessment,
  runId,
  candidates,
  generating,
  generate,
  confirmingFit = false,
  request,
  preselectedWorkflowPath,
  onStartIntake,
}: FabricDeploymentPageProps) {
  const items = useMemo(() => assessment?.assessments ?? [], [assessment]);
  const [targetPlatforms, setTargetPlatforms] = useState<TargetPlatformInfo[]>([]);
  const [catalogStatus, setCatalogStatus] = useState<"loading" | "ready" | "error">("loading");
  const [previousActive, setPreviousActive] = useState(active);
  if (previousActive !== active) {
    setPreviousActive(active);
    if (active) {
      setTargetPlatforms([]);
      setCatalogStatus("loading");
    }
  }
  const [selectedTargetPlatform, setSelectedTargetPlatform] = useState("fabric");
  const fabricPlatform = targetPlatforms.find(canGenerateFabric);
  const fabricCodegenAvailable = fabricPlatform !== undefined;
  // Providers that do not advertise target kinds keep every generation option.
  const offers = (kind: Target) =>
    !fabricPlatform?.target_kinds?.length || fabricPlatform.target_kinds.includes(kind);
  const [previewFilter, setPreviewFilter] = useState<"all" | "deployable" | "scaffold">("all");
  const [selectedWorkflowPath, setSelectedWorkflowPath] = useState<string>(
    () => preselectedWorkflowPath ?? "",
  );

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    void Promise.resolve(request("/api/targets"))
      .then(async (response) => {
        if (!response?.ok) throw new Error("Target catalog request failed");
        const platforms = parseTargetCatalog(await response.json());
        if (!cancelled) {
          setTargetPlatforms(platforms);
          setCatalogStatus("ready");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setTargetPlatforms([]);
          setCatalogStatus("error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [active, request]);

  const effectiveWorkflowPath = useMemo(() => {
    if (selectedWorkflowPath && items.some((item) => item.path === selectedWorkflowPath)) {
      return selectedWorkflowPath;
    }
    if (preselectedWorkflowPath && items.some((item) => item.path === preselectedWorkflowPath)) {
      return preselectedWorkflowPath;
    }
    return items.find((item) => item.recommended_target !== "Manual rework")?.path ?? items[0]?.path ?? "";
  }, [items, preselectedWorkflowPath, selectedWorkflowPath]);

  const selectedItem: Item | undefined = useMemo(
    () => items.find((item) => item.path === effectiveWorkflowPath),
    [effectiveWorkflowPath, items],
  );

  const filteredCandidates = useMemo(() => {
    if (previewFilter === "deployable") return candidates.filter((item) => item.deployable);
    if (previewFilter === "scaffold") return candidates.filter((item) => !item.deployable);
    return candidates;
  }, [candidates, previewFilter]);

  const deployableCount = candidates.filter((item) => item.deployable).length;
  const scaffoldCount = candidates.length - deployableCount;
  const targetNames = [...new Set(
    candidates.map((item) =>
      item.target === "dataflow"
        ? "Dataflow Gen2"
        : item.target === "pipeline"
          ? "Fabric Data Pipeline"
          : "Fabric Notebook"
    ),
  )];

  return (
    <section
      className={`page ${active ? "active" : ""}`}
      hidden={!active}
      id="fabric-deployment"
    >
      <div className="page-header">
        <div>
          <div className="eyebrow">Code generation &amp; CI/CD</div>
          <h1>Fabric Code Generation &amp; Deployment</h1>
          <p>
            Select a destination platform, generate compiler-grounded Fabric definitions, inspect
            scaffolds, download ZIP bundles, and dispatch CI/CD deployments.
          </p>
        </div>
      </div>

      {!assessment && (
        <div className="notice">
          <strong>No completed assessment.</strong>{" "}
          <button className="link-button" onClick={onStartIntake}>
            Start an assessment
          </button>{" "}
          to generate Fabric definitions and dispatch deployments.
        </div>
      )}

      {confirmingFit && (
        <div className="notice" role="status">
          Confirming Fabric routing with the compiler. Targets, waves, and effort update when it
          finishes.
        </div>
      )}

      <div className="panel">
        <div className="panel-header">
          <div>
            <h2>1. Target platform</h2>
            <p>
              This page supports Fabric generation and deployment. Other providers require
              integration with the application before they can be selected here.
            </p>
          </div>
        </div>
        <div className="target-platform-grid" role="radiogroup" aria-label="Target migration platform">
          {targetPlatforms.map((platform) => {
            const selectable = canGenerateFabric(platform);
            const isSelected = selectable && selectedTargetPlatform === platform.platform_id;
            return (
              <button
                key={platform.platform_id}
                type="button"
                role="radio"
                aria-checked={isSelected}
                disabled={!selectable}
                className={`target-platform-card ${isSelected ? "selected" : ""} ${
                  selectable ? "" : "placeholder"
                }`}
                onClick={() => {
                  if (selectable) setSelectedTargetPlatform(platform.platform_id);
                }}
              >
                <div className="target-platform-head">
                  <strong>{platform.display_name}</strong>
                  <span className={`chip ${selectable ? "ready" : ""}`}>
                    {selectable
                      ? "Ready"
                      : platform.implemented
                        ? "Not integrated for generation"
                        : "Roadmap placeholder"}
                  </span>
                </div>
                <p>{platform.description}</p>
              </button>
            );
          })}
        </div>
      </div>

      {catalogStatus === "loading" && (
        <div className="notice" role="status">Loading target capabilities.</div>
      )}
      {catalogStatus === "error" && (
        <div className="notice" role="alert">
          Target capabilities could not be loaded. Fabric generation and deployment are unavailable.
        </div>
      )}
      {catalogStatus === "ready" && !fabricCodegenAvailable && (
        <div className="notice" role="status">Fabric code generation is unavailable.</div>
      )}

      {fabricCodegenAvailable && assessment && runId && (
        <div className="panel section-gap">
          <div className="panel-header">
            <div>
              <h2>2. Generate &amp; download Fabric definitions</h2>
              <p>
                Previews are unbound and unvalidated; nothing is executed or deployed until you
                explicitly dispatch.
              </p>
            </div>
          </div>
          <div className="outputs-grid">
            <div className="output-group">
              <h3>Preview generated code</h3>
              <p>Compile definitions and inspect diagnostics, required bindings, and generated code.</p>
              <div className="deploy-actions">
                {offers("notebook") && (
                  <button
                    className="secondary-button"
                    disabled={generating}
                    onClick={() => void generate("notebook")}
                  >
                    Generate Notebook previews
                  </button>
                )}
                {offers("dataflow") && (
                  <button
                    className="secondary-button"
                    disabled={generating}
                    onClick={() => void generate("dataflow")}
                  >
                    Generate Dataflow previews
                  </button>
                )}
                {offers("pipeline") && (
                  <button
                    className="secondary-button"
                    disabled={generating}
                    onClick={() => void generate("pipeline")}
                  >
                    Generate Pipeline previews
                  </button>
                )}
              </div>
            </div>
            <div className="output-group">
              <h3>Download Fabric packages</h3>
              <p>Build and download a ZIP of generated artifacts for each Fabric item type.</p>
              <div className="deploy-actions">
                {offers("notebook") && (
                  <a className="secondary-button" href={`/api/runs/${runId}/candidates?target=notebook`}>
                    Download Notebook package
                  </a>
                )}
                {offers("dataflow") && (
                  <a className="secondary-button" href={`/api/runs/${runId}/candidates?target=dataflow`}>
                    Download Dataflow package
                  </a>
                )}
                {offers("pipeline") && (
                  <a className="secondary-button" href={`/api/runs/${runId}/candidates?target=pipeline`}>
                    Download Pipeline package
                  </a>
                )}
              </div>
            </div>
          </div>

          {generating && (
            <p className="output-status" role="status">
              Generating Fabric definitions for preview…
            </p>
          )}

          {candidates.length > 0 && (
            <div className="outputs-preview-list">
              <div className="outputs-preview-header">
                <strong>
                  {targetNames.join(" / ")} previews ({candidates.length})
                </strong>
                <div className="deploy-actions">
                  <span>
                    {deployableCount} deployable · {scaffoldCount} manual scaffold
                    {scaffoldCount === 1 ? "" : "s"}
                  </span>
                  <select
                    aria-label="Filter generated previews"
                    value={previewFilter}
                    onChange={(event) =>
                      setPreviewFilter(event.target.value as "all" | "deployable" | "scaffold")
                    }
                  >
                    <option value="all">All ({candidates.length})</option>
                    <option value="deployable">Deployable ({deployableCount})</option>
                    <option value="scaffold">Scaffold ({scaffoldCount})</option>
                  </select>
                </div>
              </div>
              {filteredCandidates.map((candidate) => {
                const targetLabel =
                  candidate.target === "dataflow"
                    ? "Dataflow Gen2"
                    : candidate.target === "pipeline"
                      ? "Fabric Data Pipeline"
                      : "Fabric Notebook";
                const validationSummary =
                  candidate.validation_state === "generated_unvalidated"
                    ? "Unvalidated preview (bind sources and test parity before deploy)"
                    : candidate.validation_state === "scaffold_only" ||
                        candidate.validation_state === "scaffold"
                      ? "Scaffold only (manual redesign required)"
                      : candidate.validation_state;
                return (
                  <div
                    className="summary-box output-card"
                    key={`${candidate.workflow}-${candidate.target}`}
                  >
                    <div className="output-card-meta">
                      <span className="chip">{targetLabel}</span>
                      <span className={`status ${candidate.deployable ? "ready" : "redesign"}`}>
                        <span className="dot" />
                        {candidate.deployable ? "Deployable definition" : "Scaffold / manual rework"}
                      </span>
                      {candidate.definition_files.map((file) => (
                        <span className="chip" key={file}>
                          {file}
                        </span>
                      ))}
                    </div>
                    <h2
                      className="output-card-title"
                      aria-label={`${candidate.workflow}: ${candidate.validation_state}`}
                    >
                      {nameOf(candidate.workflow)}
                    </h2>
                    <p className="output-card-source">
                      <code>{candidate.workflow}</code> · {validationSummary}
                    </p>
                    {candidate.artifact_path && (
                      <p>
                        Download folder: <code>{candidate.artifact_path}</code>
                      </p>
                    )}
                    {candidate.diagnostics.map((value) => (
                      <p key={value}>{value}</p>
                    ))}
                    {candidate.code && (
                      <details className="code-details">
                        <summary>View generated code ({candidate.code.split("\n").length} lines)</summary>
                        <pre className="deploy-code">{candidate.code}</pre>
                      </details>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {fabricCodegenAvailable && assessment && items.length > 0 && (
        <div className="panel section-gap">
          <div className="panel-header">
            <div>
              <h2>3. Select workflow &amp; dispatch deployment</h2>
              <p>
                Choose a workflow to configure GitHub Actions or GitLab CI dispatch, validate the
                request, or download its manual deployment bundle.
              </p>
            </div>
          </div>

          <div className="workflow-deploy-picker">
            <label htmlFor="deployWorkflowSelect">Workflow to deploy</label>
            <select
              id="deployWorkflowSelect"
              value={effectiveWorkflowPath}
              onChange={(event) => setSelectedWorkflowPath(event.target.value)}
            >
              {items.map((item) => (
                <option key={item.path} value={item.path}>
                  {nameOf(item.path)} — {item.recommended_target} ({waveLabel(item.migration_wave)})
                </option>
              ))}
            </select>
          </div>

          {selectedItem && (
            <Deployment
              key={`${selectedItem.path}:${selectedItem.recommended_target}`}
              item={selectedItem}
              candidates={candidates}
              runId={runId}
              request={request}
            />
          )}
        </div>
      )}
    </section>
  );
}
