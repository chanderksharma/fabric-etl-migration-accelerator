import { useEffect, useMemo, useState } from "react";
import type { AssessmentResult, Candidate } from "./App";
import { Deployment } from "./workspace-deployment";
import { nameOf, waveLabel } from "./workspace-model";

type Item = AssessmentResult["assessments"][number];
type Target = "notebook" | "dataflow" | "pipeline";

export type TargetPlatformInfo = {
  platform_id: string;
  display_name: string;
  provider_version: string;
  supported_ir_versions: string[];
  implemented: boolean;
  status: "ready" | "placeholder";
  capabilities: string[];
  description: string;
};

const FALLBACK_TARGETS: TargetPlatformInfo[] = [
  {
    platform_id: "fabric",
    display_name: "Microsoft Fabric",
    provider_version: "1.0.0",
    supported_ir_versions: ["1.0.0"],
    implemented: true,
    status: "ready",
    capabilities: ["evaluate", "capacity", "codegen", "dry_run"],
    description:
      "Compiler-grounded evaluation, F-SKU capacity sizing, Dataflow Gen2 / PySpark Notebook / Data Pipeline generation, and dry-run planning.",
  },
  {
    platform_id: "databricks",
    display_name: "Azure Databricks",
    provider_version: "0.0.0-placeholder",
    supported_ir_versions: ["1.0.0"],
    implemented: false,
    status: "placeholder",
    capabilities: [],
    description: "Roadmap placeholder for Databricks target-fit evaluation and Asset Bundles.",
  },
  {
    platform_id: "synapse",
    display_name: "Azure Synapse Analytics",
    provider_version: "0.0.0-placeholder",
    supported_ir_versions: ["1.0.0"],
    implemented: false,
    status: "placeholder",
    capabilities: [],
    description: "Roadmap placeholder for optional Synapse DWU and Spark pipeline targets.",
  },
  {
    platform_id: "snowflake",
    display_name: "Snowflake",
    provider_version: "0.0.0-placeholder",
    supported_ir_versions: ["1.0.0"],
    implemented: false,
    status: "placeholder",
    capabilities: [],
    description: "Roadmap placeholder for Snowflake Snowpark and SQL compilation.",
  },
];

type FabricDeploymentPageProps = {
  active: boolean;
  assessment: AssessmentResult | null;
  runId: string | null;
  candidates: Candidate[];
  generating: boolean;
  generate: (target: Target) => Promise<void>;
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
  request,
  preselectedWorkflowPath,
  onStartIntake,
}: FabricDeploymentPageProps) {
  const items = useMemo(() => assessment?.assessments ?? [], [assessment]);
  const [targetPlatforms, setTargetPlatforms] = useState<TargetPlatformInfo[]>(FALLBACK_TARGETS);
  const [selectedTargetPlatform, setSelectedTargetPlatform] = useState("fabric");
  const [previewFilter, setPreviewFilter] = useState<"all" | "deployable" | "scaffold">("all");
  const [selectedWorkflowPath, setSelectedWorkflowPath] = useState<string>(
    () => preselectedWorkflowPath ?? "",
  );

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    void Promise.resolve(request("/api/targets"))
      .then(async (response) => {
        if (!response?.ok) return;
        const payload = (await response.json()) as { targets?: TargetPlatformInfo[] };
        if (!cancelled && Array.isArray(payload.targets) && payload.targets.length > 0) {
          setTargetPlatforms(payload.targets);
        }
      })
      .catch(() => {
        // Keep fallback target platform metadata when endpoint is mocked or unavailable.
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

      <div className="panel">
        <div className="panel-header">
          <div>
            <h2>1. Target platform</h2>
            <p>
              Select an implemented destination platform. Roadmap targets fail closed until their
              provider plugin is installed.
            </p>
          </div>
        </div>
        <div className="target-platform-grid" role="radiogroup" aria-label="Target migration platform">
          {targetPlatforms.map((platform) => {
            const isSelected = selectedTargetPlatform === platform.platform_id;
            return (
              <button
                key={platform.platform_id}
                type="button"
                role="radio"
                aria-checked={isSelected}
                disabled={!platform.implemented}
                className={`target-platform-card ${isSelected ? "selected" : ""} ${
                  platform.implemented ? "" : "placeholder"
                }`}
                onClick={() => {
                  if (platform.implemented) setSelectedTargetPlatform(platform.platform_id);
                }}
              >
                <div className="target-platform-head">
                  <strong>{platform.display_name}</strong>
                  <span className={`chip ${platform.implemented ? "ready" : ""}`}>
                    {platform.implemented ? "Ready" : "Roadmap placeholder"}
                  </span>
                </div>
                <p>{platform.description}</p>
              </button>
            );
          })}
        </div>
      </div>

      {assessment && runId && (
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
                <button
                  className="secondary-button"
                  disabled={generating}
                  onClick={() => void generate("notebook")}
                >
                  Generate Notebook previews
                </button>
                <button
                  className="secondary-button"
                  disabled={generating}
                  onClick={() => void generate("dataflow")}
                >
                  Generate Dataflow previews
                </button>
                <button
                  className="secondary-button"
                  disabled={generating}
                  onClick={() => void generate("pipeline")}
                >
                  Generate Pipeline previews
                </button>
              </div>
            </div>
            <div className="output-group">
              <h3>Download Fabric packages</h3>
              <p>Build and download a ZIP of generated artifacts for each Fabric item type.</p>
              <div className="deploy-actions">
                <a className="secondary-button" href={`/api/runs/${runId}/candidates?target=notebook`}>
                  Download Notebook package
                </a>
                <a className="secondary-button" href={`/api/runs/${runId}/candidates?target=dataflow`}>
                  Download Dataflow package
                </a>
                <a className="secondary-button" href={`/api/runs/${runId}/candidates?target=pipeline`}>
                  Download Pipeline package
                </a>
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
                        Saved in <code>generated-fabric-workflows/{candidate.artifact_path}</code>
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

      {assessment && items.length > 0 && (
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
              key={selectedItem.path}
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
