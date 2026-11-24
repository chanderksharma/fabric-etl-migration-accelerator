import { useEffect, useMemo, useRef, useState } from "react";
import type { RunResult } from "./App";
import { isStringArray, type NeutralAssessment } from "./neutral-assessment";
import { parseTargetCatalog, type TargetPlatformInfo } from "./target-platform";

type Evaluation = {
  source_path: string;
  asset_id: string;
  asset_name: string;
  provider_version: string;
  evaluation: {
    platform_id: string;
    recommended_target: string;
    recommendation_reason: string;
    diagnostics: string[];
  };
};

type TargetCapacityOutput = {
  platform_id: string;
  provider_version: string;
  model_version: string;
  status: string;
  asset_count: number;
  modeled_count: number;
  recommendations: Array<{
    scenario: string;
    required_units: number;
    unit_label: string;
    recommended_tier: string;
  }>;
};

type TargetArtifactOutput = {
  workflow: string;
  target_kind: string;
  validation_state: string;
  translation_mode: string;
  deployable: boolean;
  files: Record<string, string>;
  diagnostics: string[];
  required_bindings: string[];
};

type TargetGenerationOutput = {
  platform_id: string;
  provider_version: string;
  target_kind: string;
  artifacts: TargetArtifactOutput[];
};

function parseEvaluations(value: unknown): Evaluation[] {
  if (!Array.isArray(value) || !value.every((item: unknown) => {
    if (typeof item !== "object" || item === null) return false;
    const record = item as Record<string, unknown>;
    if (typeof record.evaluation !== "object" || record.evaluation === null) return false;
    const result = record.evaluation as Record<string, unknown>;
    return typeof record.source_path === "string" && typeof record.asset_id === "string" &&
      typeof record.asset_name === "string" && typeof record.provider_version === "string" &&
      typeof result.platform_id === "string" && typeof result.recommended_target === "string" &&
      typeof result.recommendation_reason === "string" && isStringArray(result.diagnostics);
  })) throw new Error("Invalid target evaluation");
  return value;
}

type Props = {
  run: RunResult | null;
  runId: string | null;
  assessment: NeutralAssessment | null;
  error: string | null;
  request: (path: string, init?: RequestInit) => Promise<Response>;
  cancel: () => Promise<void>;
  startNew: () => void;
};

export function NeutralWorkspace({run, runId, assessment, error, request, cancel, startNew}: Props) {
  const [targets, setTargets] = useState<TargetPlatformInfo[]>([]);
  const [selected, setSelected] = useState("");
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [evaluations, setEvaluations] = useState<Evaluation[] | null>(null);
  const [evaluationError, setEvaluationError] = useState<string | null>(null);
  const [evaluating, setEvaluating] = useState(false);
  const [loadingSaved, setLoadingSaved] = useState(false);
  const [capacityResults, setCapacityResults] = useState<TargetCapacityOutput[] | null>(null);
  const [capacityError, setCapacityError] = useState<string | null>(null);
  const [estimatingCapacity, setEstimatingCapacity] = useState(false);
  const [selectedKind, setSelectedKind] = useState("");
  const [generationResults, setGenerationResults] = useState<TargetGenerationOutput[] | null>(null);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [generatingPreview, setGeneratingPreview] = useState(false);
  const [search, setSearch] = useState("");
  const [onlyManual, setOnlyManual] = useState(false);
  const evaluationEpoch = useRef(0);

  useEffect(() => {
    document.title = "Target-neutral assessment | ETL Modernization";
  }, []);

  useEffect(() => {
    if (run?.status !== "completed" || !assessment) return;
    let active = true;
    void request("/api/targets")
      .then(async response => {
        const available = parseTargetCatalog(await response.json()).filter(
          target => target.implemented && target.status === "ready" && (
            target.capabilities.includes("evaluate") ||
            target.capabilities.includes("codegen") ||
            target.capabilities.includes("capacity")
          ),
        );
        if (active) {
          setTargets(available);
          const first = available[0];
          setSelected(first?.platform_id ?? "");
          setSelectedKind(first?.target_kinds?.[0] ?? "");
          setLoadingSaved(Boolean(first?.capabilities.includes("evaluate")));
          setCatalogError(null);
          setCatalogLoading(false);
        }
      })
      .catch(caught => {
        if (active) {
          setTargets([]);
          setCatalogError(caught instanceof Error ? caught.message : "Target catalog unavailable");
          setCatalogLoading(false);
        }
      });
    return () => { active = false; };
  }, [assessment, request, run?.status]);

  useEffect(() => {
    if (!runId || !selected || !assessment) return;
    const epoch = ++evaluationEpoch.current;
    void request(`/api/runs/${runId}/targets/${encodeURIComponent(selected)}/evaluate`)
      .then(async response => {
        const result = parseEvaluations(await response.json());
        if (epoch === evaluationEpoch.current) setEvaluations(result);
      })
      .catch(caught => {
        if (epoch === evaluationEpoch.current &&
          !(caught instanceof Error && "status" in caught && caught.status === 404)) {
          setEvaluationError(caught instanceof Error ? caught.message : "Saved evaluation unavailable");
        }
      })
      .finally(() => {
        if (epoch === evaluationEpoch.current) setLoadingSaved(false);
      });
    return () => { evaluationEpoch.current += 1; };
  }, [assessment, request, runId, selected]);

  const selectedTargetInfo = targets.find(item => item.platform_id === selected);
  const supportsEvaluate = Boolean(selectedTargetInfo?.capabilities.includes("evaluate"));
  const supportsCapacity = Boolean(selectedTargetInfo?.capabilities.includes("capacity"));
  const targetKinds = selectedTargetInfo?.target_kinds ?? [];
  const supportsCodegen = Boolean(
    selectedTargetInfo?.capabilities.includes("codegen") && targetKinds.length > 0,
  );
  const effectiveKind = targetKinds.includes(selectedKind) ? selectedKind : (targetKinds[0] ?? "");

  const portfolioMetrics = useMemo(() => {
    const items = assessment?.assessments ?? [];
    return {
      totalComponents: items.reduce((sum, item) => sum + item.component_count, 0),
      totalConnections: items.reduce((sum, item) => sum + item.connection_count, 0),
      totalEffort: items.reduce((sum, item) => sum + item.intrinsic_effort_days, 0),
      manualReviewAssets: items.filter(item => item.unknown_components.length > 0).length,
    };
  }, [assessment]);

  const filteredAssets = useMemo(() => {
    const items = assessment?.assessments ?? [];
    const term = search.trim().toLowerCase();
    return items.filter(asset => {
      if (onlyManual && asset.unknown_components.length === 0) return false;
      if (!term) return true;
      return asset.name.toLowerCase().includes(term) ||
        asset.path.toLowerCase().includes(term) ||
        asset.unknown_components.some(component => component.toLowerCase().includes(term));
    });
  }, [assessment, onlyManual, search]);

  async function evaluate() {
    if (!runId || !selected || evaluating) return;
    const epoch = ++evaluationEpoch.current;
    setEvaluating(true);
    setEvaluationError(null);
    setEvaluations(null);
    try {
      const response = await request(
        `/api/runs/${runId}/targets/${encodeURIComponent(selected)}/evaluate`,
        {method: "POST"},
      );
      const result = parseEvaluations(await response.json());
      if (epoch === evaluationEpoch.current) setEvaluations(result);
    } catch (caught) {
      if (epoch === evaluationEpoch.current) {
        setEvaluationError(caught instanceof Error ? caught.message : "Target evaluation failed");
      }
    } finally {
      if (epoch === evaluationEpoch.current) setEvaluating(false);
    }
  }

  async function estimateCapacity() {
    if (!runId || !selected || !supportsCapacity || estimatingCapacity) return;
    setEstimatingCapacity(true);
    setCapacityError(null);
    setCapacityResults(null);
    try {
      const response = await request(
        `/api/runs/${runId}/targets/${encodeURIComponent(selected)}/capacity`,
      );
      const payload: unknown = await response.json();
      if (!Array.isArray(payload)) throw new Error("Invalid target capacity response");
      setCapacityResults(payload as TargetCapacityOutput[]);
    } catch (caught) {
      setCapacityError(caught instanceof Error ? caught.message : "Target capacity failed");
    } finally {
      setEstimatingCapacity(false);
    }
  }

  async function generatePreview() {
    if (!runId || !selected || !supportsCodegen || !effectiveKind || generatingPreview) return;
    setGeneratingPreview(true);
    setGenerationError(null);
    setGenerationResults(null);
    try {
      const response = await request(
        `/api/runs/${runId}/targets/${encodeURIComponent(selected)}/generate` +
        `?target_kind=${encodeURIComponent(effectiveKind)}`,
        {method: "POST"},
      );
      const payload: unknown = await response.json();
      if (!Array.isArray(payload)) throw new Error("Invalid target generation response");
      setGenerationResults(payload as TargetGenerationOutput[]);
    } catch (caught) {
      setGenerationError(caught instanceof Error ? caught.message : "Target generation failed");
    } finally {
      setGeneratingPreview(false);
    }
  }

  return <div className="shell reference-workspace">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">E</div><div>
        <strong>ETL Modernization</strong><span>Target-neutral assessment</span>
      </div></div>
      <nav className="nav" aria-label="Primary">
        <button type="button" className="secondary-button" onClick={startNew}>New assessment</button>
      </nav>
      <div className="sidebar-note"><strong>Assessment boundary</strong>
        <p>Source analysis and target evaluation do not generate or deploy artifacts.</p>
      </div>
    </aside>
    <main className="main"><div className="content">
      <div className="page-header"><div>
        <div className="eyebrow">Installed source plugins</div>
        <h1>Target-neutral assessment</h1>
        <p>Static source facts are separate from target recommendations and require validation.</p>
      </div></div>
      {error && <div className="errorMessage" role="alert">{error}</div>}
      {run && (run.status === "queued" || run.status === "running") && <section>
        <p role="status">{run.status}: {run.processed} / {run.total} workflows</p>
        <button type="button" onClick={() => void cancel()}>Cancel assessment</button>
      </section>}
      {run?.status === "completed" && !assessment && !error &&
        <p role="status">Loading target-neutral assessment...</p>}
      {assessment && <>
        <div className="notice">{assessment.workflow_count} asset{assessment.workflow_count === 1 ? "" : "s"} assessed;{" "}
          {assessment.failed_count} source parsing failures.
          Intrinsic effort is an estimate, not target-specific delivery effort.</div>
        <div className="fact-grid section-gap">
          <div className="fact"><span>Total assets</span><strong>{assessment.workflow_count}</strong></div>
          <div className="fact"><span>Components / connections</span><strong>{portfolioMetrics.totalComponents} / {portfolioMetrics.totalConnections}</strong></div>
          <div className="fact"><span>Manual review assets</span><strong>{portfolioMetrics.manualReviewAssets}</strong></div>
          <div className="fact"><span>Intrinsic effort total</span><strong>{portfolioMetrics.totalEffort.toFixed(1)} days</strong></div>
        </div>
        <div className="toolbar section-gap">
          <input
            type="search"
            aria-label="Filter neutral assets"
            placeholder="Filter assets or unknown components..."
            value={search}
            onChange={event => setSearch(event.target.value)}
          />
          <label className="deploy-checkbox">
            <input
              type="checkbox"
              checked={onlyManual}
              onChange={event => setOnlyManual(event.target.checked)}
            />
            <span>Manual review only</span>
          </label>
        </div>
        {assessment.failures.map(failure => <p className="errorMessage" key={failure}>{failure}</p>)}
        {filteredAssets.map(asset => <article className="panel section-gap" key={asset.path}>
          <div className="panel-header"><div><h2>{asset.name}</h2><p>{asset.path}</p></div></div>
          <div className="fact-grid">
            <div className="fact"><span>Source</span><strong>{asset.source_product} ({asset.source_platform})</strong></div>
            <div className="fact"><span>Components / connections</span><strong>{asset.component_count} / {asset.connection_count}</strong></div>
            <div className="fact"><span>Complexity</span><strong>{asset.complexity_band} ({asset.complexity_score})</strong></div>
            <div className="fact"><span>Intrinsic effort estimate</span><strong>{asset.intrinsic_effort_days} days</strong></div>
          </div>
          {asset.inventory && asset.inventory.length > 0 && <div className="tableWrap section-gap">
            <table>
              <thead><tr><th>Operation</th><th>Category</th><th>Count</th></tr></thead>
              <tbody>{asset.inventory.map(item => <tr key={`${item.operation}:${item.classification}`}>
                <td>{item.operation}</td>
                <td>{item.classification}</td>
                <td>{item.count}</td>
              </tr>)}</tbody>
            </table>
          </div>}
          {asset.unknown_components.length > 0 && <p>Requires manual review:{" "}
            <span>{asset.unknown_components.join(", ")}</span></p>}
        </article>)}
        <section className="panel section-gap" aria-labelledby="target-evaluation">
          <div className="panel-header"><div><h2 id="target-evaluation">Target evaluation</h2>
            <p>Only installed evaluate-capable providers are available. Compatibility is checked by the service.</p>
          </div></div>
          {catalogError && <p className="errorMessage" role="alert">{catalogError}</p>}
          {catalogLoading && <p role="status">Loading target catalog...</p>}
          {!catalogLoading && !catalogError && targets.length === 0 &&
            <p>No evaluate-capable targets are available.</p>}
          {targets.length > 0 && <>
            <label htmlFor="neutral-target">Target platform</label>{" "}
            <select id="neutral-target" value={selected} disabled={evaluating} onChange={event => {
              const nextId = event.target.value;
              const nextTarget = targets.find(item => item.platform_id === nextId);
              setSelected(nextId);
              setSelectedKind(nextTarget?.target_kinds?.[0] ?? "");
              setLoadingSaved(Boolean(nextTarget?.capabilities.includes("evaluate")));
              setEvaluations(null);
              setEvaluationError(null);
              setCapacityResults(null);
              setCapacityError(null);
              setGenerationResults(null);
              setGenerationError(null);
            }}>{targets.map(target => <option key={target.platform_id} value={target.platform_id}>
              {target.display_name}
            </option>)}</select>{" "}
            {supportsEvaluate && <button type="button" className="primary-button" onClick={() => void evaluate()}
              disabled={!selected || evaluating || loadingSaved || assessment.assessments.length === 0}>
              {evaluating ? "Evaluating..." : loadingSaved ? "Loading evaluation..." : "Evaluate target"}
            </button>}{" "}
            {supportsCapacity && <button type="button" className="secondary-button" onClick={() => void estimateCapacity()}
              disabled={estimatingCapacity || assessment.assessments.length === 0}>
              {estimatingCapacity ? "Estimating..." : "Estimate target capacity"}
            </button>}{" "}
            {supportsCodegen && <>
              <label htmlFor="neutral-target-kind">Target kind</label>{" "}
              <select
                id="neutral-target-kind"
                value={effectiveKind}
                disabled={generatingPreview}
                onChange={event => {
                  setSelectedKind(event.target.value);
                  setGenerationResults(null);
                  setGenerationError(null);
                }}
              >
                {targetKinds.map(kind => <option key={kind} value={kind}>{kind}</option>)}
              </select>{" "}
              <button type="button" className="secondary-button" onClick={() => void generatePreview()}
                disabled={generatingPreview || !effectiveKind || assessment.assessments.length === 0}>
                {generatingPreview ? "Generating..." : "Generate target preview"}
              </button>
            </>}
          </>}
          {evaluationError && <p className="errorMessage" role="alert">{evaluationError}</p>}
          {capacityError && <p className="errorMessage" role="alert">{capacityError}</p>}
          {generationError && <p className="errorMessage" role="alert">{generationError}</p>}
          {evaluations?.length === 0 && <p>No target evaluations were returned.</p>}
          {evaluations?.map(item => <article key={`${item.source_path}:${item.asset_id}`}>
            <h3>{item.asset_name}: {item.evaluation.recommended_target}</h3>
            <p>{item.evaluation.recommendation_reason}</p>
            <p>Provider version: {item.provider_version}</p>
            {item.evaluation.diagnostics.map(diagnostic => <p key={diagnostic}>{diagnostic}</p>)}
          </article>)}
          {capacityResults?.map((estimate, index) => <article key={`${estimate.platform_id}:${index}`}>
            <h3>Target capacity ({estimate.platform_id})</h3>
            <p>Status: {estimate.status} · Modeled {estimate.modeled_count}/{estimate.asset_count}</p>
            {estimate.recommendations.map(rec => <p key={rec.scenario}>
              {rec.scenario}: {rec.recommended_tier} ({rec.required_units} {rec.unit_label})
            </p>)}
          </article>)}
          {generationResults?.flatMap((batch, batchIndex) =>
            batch.artifacts.map(artifact => <article key={`${batchIndex}:${artifact.workflow}:${artifact.target_kind}`}>
              <h3>{artifact.workflow} ({artifact.target_kind})</h3>
              <p>State: {artifact.validation_state} · Mode: {artifact.translation_mode} · Deployable: {artifact.deployable ? "Yes" : "No"}</p>
              {artifact.diagnostics.map(diag => <p key={diag}>{diag}</p>)}
              {artifact.required_bindings.length > 0 && <p>Required bindings: {artifact.required_bindings.join(", ")}</p>}
              {Object.entries(artifact.files).map(([name, content]) => <pre key={name}><code>{content}</code></pre>)}
            </article>)
          )}
        </section>
      </>}
    </div></main>
  </div>;
}
