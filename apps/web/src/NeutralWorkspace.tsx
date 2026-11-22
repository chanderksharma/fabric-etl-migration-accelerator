import { useEffect, useRef, useState } from "react";
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
          target => target.implemented && target.status === "ready" &&
            target.capabilities.includes("evaluate"),
        );
        if (active) {
          setTargets(available);
          setSelected(available[0]?.platform_id ?? "");
          setLoadingSaved(available.length > 0);
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
        {assessment.failures.map(failure => <p className="errorMessage" key={failure}>{failure}</p>)}
        {assessment.assessments.map(asset => <article className="panel section-gap" key={asset.path}>
          <div className="panel-header"><div><h2>{asset.name}</h2><p>{asset.path}</p></div></div>
          <div className="fact-grid">
            <div className="fact"><span>Source</span><strong>{asset.source_product} ({asset.source_platform})</strong></div>
            <div className="fact"><span>Components / connections</span><strong>{asset.component_count} / {asset.connection_count}</strong></div>
            <div className="fact"><span>Complexity</span><strong>{asset.complexity_band} ({asset.complexity_score})</strong></div>
            <div className="fact"><span>Intrinsic effort estimate</span><strong>{asset.intrinsic_effort_days} days</strong></div>
          </div>
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
              setSelected(event.target.value);
              setLoadingSaved(true);
              setEvaluations(null);
              setEvaluationError(null);
            }}>{targets.map(target => <option key={target.platform_id} value={target.platform_id}>
              {target.display_name}
            </option>)}</select>{" "}
            <button type="button" className="primary-button" onClick={() => void evaluate()}
              disabled={!selected || evaluating || loadingSaved || assessment.assessments.length === 0}>
              {evaluating ? "Evaluating..." : loadingSaved ? "Loading evaluation..." : "Evaluate target"}
            </button>
          </>}
          {evaluationError && <p className="errorMessage" role="alert">{evaluationError}</p>}
          {evaluations?.length === 0 && <p>No target evaluations were returned.</p>}
          {evaluations?.map(item => <article key={`${item.source_path}:${item.asset_id}`}>
            <h3>{item.asset_name}: {item.evaluation.recommended_target}</h3>
            <p>{item.evaluation.recommendation_reason}</p>
            <p>Provider version: {item.provider_version}</p>
            {item.evaluation.diagnostics.map(diagnostic => <p key={diagnostic}>{diagnostic}</p>)}
          </article>)}
        </section>
      </>}
    </div></main>
  </div>;
}
