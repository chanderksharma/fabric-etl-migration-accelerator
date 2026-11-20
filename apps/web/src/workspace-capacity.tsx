import { useState } from "react";
import type { CapacityEstimate, CapacitySettings, CapacityWorkflow } from "./use-capacity";

const SPARK_PRESETS = [
  {vcores: 4, label: "Small (4 vCores · 2 CU)"},
  {vcores: 8, label: "Medium (8 vCores · 4 CU)"},
  {vcores: 16, label: "Large (16 vCores · 8 CU)"},
  {vcores: 32, label: "2x Large (32 vCores · 16 CU)"},
  {vcores: 64, label: "4x Large (64 vCores · 32 CU)"},
];

function compactNumber(value: number): string {
  return Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

function componentSummary(
  item: CapacityWorkflow,
  billingMode: "capacity" | "autoscale",
): string {
  const parts: string[] = [];
  if (item.dataflow_cu_seconds_per_run) {
    parts.push(`DF ${item.dataflow_cu_seconds_per_run.toFixed(0)}`);
  }
  if (item.notebook_cu_seconds_per_run) {
    parts.push(
      `NB ${item.notebook_cu_seconds_per_run.toFixed(0)}${billingMode === "autoscale" ? " (Autoscale)" : ""}`
    );
  }
  if (item.pipeline_cu_seconds_per_run) {
    parts.push(`PL ${item.pipeline_cu_seconds_per_run.toFixed(0)}`);
  }
  return parts.join(" · ");
}

function withInteractiveUsers(settings: CapacitySettings, users: number): CapacitySettings {
  const normalized = Math.max(0, Math.floor(Number.isFinite(users) ? users : 0));
  return {
    ...settings,
    active_users_per_day: normalized,
    peak_concurrent_users: normalized,
  };
}

export function CapacityPlanning({
  estimate,
  loading,
  saving,
  error,
  runId,
  save,
}: {
  estimate: CapacityEstimate | null;
  loading: boolean;
  saving: boolean;
  error: string | null;
  runId: string | null;
  save: (inputs: CapacityWorkflow[], nextSettings?: CapacitySettings) => Promise<void>;
}) {
  const [draft, setDraft] = useState<{
    source: CapacityEstimate | null;
    inputs: CapacityWorkflow[];
    interactiveUsers: number;
  }>(() => ({
    source: estimate,
    inputs: estimate?.workflows ?? [],
    interactiveUsers: estimate?.settings.peak_concurrent_users ?? 1,
  }));
  const inputs = draft.source === estimate ? draft.inputs : estimate?.workflows ?? [];
  const interactiveUsers = draft.source === estimate
    ? draft.interactiveUsers
    : estimate?.settings.peak_concurrent_users ?? 1;

  function update(path: string, patch: Partial<CapacityWorkflow>) {
    setDraft({
      source: estimate,
      inputs: inputs.map(item =>
        item.workflow_path === path ? {...item, ...patch} : item
      ),
      interactiveUsers,
    });
  }

  function setInteractiveUsers(users: number) {
    setDraft({
      source: estimate,
      inputs,
      interactiveUsers: Math.max(0, Math.floor(Number.isFinite(users) ? users : 0)),
    });
  }

  function switchSparkBilling(mode: "capacity" | "autoscale") {
    if (!estimate || saving) return;
    void save(
      inputs,
      withInteractiveUsers({...estimate.settings, spark_billing_mode: mode}, interactiveUsers),
    );
  }

  function applySettings() {
    if (!estimate || saving) return;
    void save(inputs, withInteractiveUsers(estimate.settings, interactiveUsers));
  }

  const optimized = estimate?.scenarios.find(item => item.name === "Optimized");
  const billingMode = estimate?.settings.spark_billing_mode ?? "capacity";
  const hasNotebookWorkloads = inputs.some(
    item => item.status !== "excluded" && item.target_components?.includes("Fabric Notebook")
  );
  const autoscaleHours = estimate?.autoscale_spark_monthly_cu_hours ?? 0;
  const interactivePeakCu = interactiveUsers
    * (estimate?.settings.cu_per_active_user ?? 0.3)
    * (estimate?.settings.interactive_peak_factor ?? 2);

  return <section className="page active" id="capacity-planning">
    <div className="page-header">
      <div>
        <div className="eyebrow">Capacity planning</div>
        <h1>Fabric Capacity Estimate</h1>
        <p>
          Convert assessed Alteryx and Informatica workloads (Dataflow Gen2, Fabric Notebook,
          Fabric Pipeline, and Mixed solutions) into a preliminary portfolio capacity estimate.
        </p>
      </div>
      {runId && <div className="quick-actions">
        <a className="secondary-button" href={`/api/runs/${runId}/capacity/export?format=json`}>
          Export JSON
        </a>
        <a className="secondary-button" href={`/api/runs/${runId}/capacity/export?format=csv`}>
          Export CSV
        </a>
      </div>}
    </div>
    {loading && <div className="notice">Loading capacity estimate…</div>}
    {error && <div className="errorMessage" role="alert">{error}</div>}
    {!loading && !estimate && <div className="notice">
      Complete an assessment to create a capacity estimate.
    </div>}
    {estimate && <>
      <div className="recommendation-banner">
        <div>
          <h2>
            {estimate.status === "not_available"
              ? "No workflows are eligible for this model"
              : `Preliminary recommendation: ${optimized?.recommended_sku ?? "Not available"}`}
          </h2>
          <p>
            {estimate.status === "inputs_required"
              ? `${estimate.unconfirmed_count} modeled workflows use initial defaults (Daily, 1,000 rows). Update and save to refine.`
              : "Validate representative workloads with Fabric Capacity Metrics before purchase."}
          </p>
        </div>
        <span className="recommendation-status">
          {estimate.status === "planning_estimate"
            ? "Preliminary"
            : estimate.status === "inputs_required"
              ? "Default assumptions"
              : "Not available"}
        </span>
      </div>
      <div className="panel spark-billing-bar">
        <div>
          <strong>Spark Notebook billing mode</strong>
          <span className="cell-note">
            {billingMode === "autoscale"
              ? "Autoscale Billing for Spark offloads Fabric Notebook compute from the base F-SKU."
              : "Standard capacity billing includes Fabric Notebook CUs inside the base F-SKU."}
          </span>
        </div>
        <div className="mode-toggle" role="radiogroup" aria-label="Spark Notebook billing mode">
          <button
            type="button"
            role="radio"
            aria-checked={billingMode === "capacity"}
            className={billingMode === "capacity" ? "active" : "secondary-button"}
            disabled={saving || !estimate.eligible_count}
            onClick={() => switchSparkBilling("capacity")}
          >
            Include in F-SKU (Default)
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={billingMode === "autoscale"}
            className={billingMode === "autoscale" ? "active" : "secondary-button"}
            disabled={saving || !estimate.eligible_count}
            onClick={() => switchSparkBilling("autoscale")}
          >
            Autoscale Billing for Spark
          </button>
        </div>
        <div className="interactive-users-control">
          <div>
            <label htmlFor="capacity-interactive-users"><strong>Interactive users</strong></label>
            <span className="cell-note">
              Default 1 ({interactivePeakCu.toFixed(2)} peak CUs). Set 0 for ETL-only sizing.
            </span>
          </div>
          <div className="interactive-users-actions">
            <input
              id="capacity-interactive-users"
              aria-label="Interactive users"
              type="number"
              min="0"
              value={interactiveUsers}
              onChange={event => setInteractiveUsers(Number(event.target.value))}
              onKeyDown={event => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  applySettings();
                }
              }}
            />
            <button
              type="button"
              className="secondary-button"
              disabled={saving || !estimate.eligible_count}
              onClick={applySettings}
            >
              Update
            </button>
          </div>
        </div>
      </div>
      <div className={`metric-grid capacity-metrics ${billingMode === "autoscale" ? "five-up" : ""}`}>
        {estimate.scenarios.map(scenario => <div className="metric-card" key={scenario.name}>
          <div className="metric-label">{scenario.name}</div>
          <div className="metric-value">{scenario.recommended_sku}</div>
          <div className="metric-context">{scenario.required_cu.toFixed(2)} required CUs</div>
        </div>)}
        <div className="metric-card">
          <div className="metric-label">Base F-SKU monthly demand</div>
          <div className="metric-value">{estimate.monthly_cu_hours.toFixed(1)}</div>
          <div className="metric-context">
            {billingMode === "autoscale"
              ? "CU-hours (Dataflow + Pipeline)"
              : "CU-hours across modeled workflows"}
          </div>
        </div>
        {billingMode === "autoscale" && <div className="metric-card">
          <div className="metric-label">Autoscale Spark demand</div>
          <div className="metric-value">{autoscaleHours.toFixed(1)}</div>
          <div className="metric-context">Spark CU-hours/month billed separately</div>
        </div>}
      </div>
      <div className="panel section-gap">
        <div className="panel-header">
          <div>
            <h2>Workflow operational inputs</h2>
            <p>
              Review run frequency, source rows{hasNotebookWorkloads ? ", and Spark settings" : ""}.
              Saving recalculates and confirms the current values.
            </p>
          </div>
          <button
            type="button"
            disabled={saving || !estimate.eligible_count}
            onClick={() => void save(inputs, withInteractiveUsers(estimate.settings, interactiveUsers))}
          >
            {saving ? "Saving…" : "Save and recalculate"}
          </button>
        </div>
        <div className="table-wrap capacity-table-wrap">
          <table className="capacity-table">
            <thead>
              <tr>
                <th>Workflow</th>
                <th>Refresh</th>
                <th>Rows/run</th>
                <th>Spark / Runtime</th>
                <th>Components (CU-s)</th>
                <th>CU-sec/run</th>
                <th>Monthly CU-hours</th>
              </tr>
            </thead>
            <tbody>
              {inputs.map(item => {
                const usesNotebook = item.status !== "excluded"
                  && Boolean(item.target_components?.includes("Fabric Notebook"));
                const parts = componentSummary(item, billingMode);
                return <tr key={item.workflow_path} className={item.status === "excluded" ? "muted-row" : ""}>
                  <td>
                    <strong>{item.workflow_path}</strong>
                    {item.recommended_target && <span className="cell-note">
                      {item.recommended_target === "Manual rework"
                        ? "Manual rework (Indicative Dataflow basis)"
                        : item.target_components?.length
                          ? item.target_components.join(" + ")
                          : item.recommended_target}
                      {item.model_basis ? ` · ${item.model_basis === "calibrated" ? "Calibrated" : "Heuristic"}` : ""}
                    </span>}
                    {item.exclusion_reason && <span className="cell-note">{item.exclusion_reason}</span>}
                  </td>
                  <td>
                    {item.status === "excluded" ? "—" : <select
                      aria-label={`Refresh interval for ${item.workflow_path}`}
                      value={item.refresh_interval_minutes}
                      onChange={event => update(item.workflow_path, {
                        refresh_interval_minutes: Number(event.target.value),
                        confirmed: false,
                      })}
                    >
                      {[15, 30, 60, 120, 240, 360, 720, 1440].map(value =>
                        <option key={value} value={value}>{value === 1440 ? "Daily" : `${value} min`}</option>
                      )}
                    </select>}
                  </td>
                  <td>{item.status === "excluded" ? "—" : <>
                    <input
                      aria-label={`Source rows for ${item.workflow_path}`}
                      type="number"
                      min="1"
                      value={item.source_rows_per_run}
                      onChange={event => update(item.workflow_path, {
                        source_rows_per_run: Number(event.target.value),
                        confirmed: false,
                      })}
                    />
                    {item.duration_driver && item.row_volume_threshold && <span className="cell-note">
                      {item.duration_driver === "row_volume"
                        ? "Row volume drives Dataflow duration."
                        : `${item.heavy_steps
                          ? `Rows scale ${item.heavy_steps} heavy step${item.heavy_steps === 1 ? "" : "s"} directly; `
                          : ""}${item.duration_driver === "complexity"
                          ? "Complexity"
                          : "Minimum duration"} drives Dataflow base until ~${compactNumber(item.row_volume_threshold)} rows.`}
                    </span>}
                  </>}</td>
                  <td>
                    {!usesNotebook ? "—" : <div className="spark-controls">
                      <select
                        aria-label={`Spark vCores for ${item.workflow_path}`}
                        value={item.spark_vcores ?? 8}
                        onChange={event => update(item.workflow_path, {
                          spark_vcores: Number(event.target.value),
                          confirmed: false,
                        })}
                      >
                        {SPARK_PRESETS.map(preset =>
                          <option key={preset.vcores} value={preset.vcores}>{preset.label}</option>
                        )}
                      </select>
                      <input
                        aria-label={`Notebook runtime seconds for ${item.workflow_path}`}
                        type="number"
                        min="1"
                        placeholder={item.effective_notebook_runtime_seconds
                          ? `Auto (${item.effective_notebook_runtime_seconds.toFixed(0)}s)`
                          : "Auto (sec)"}
                        value={item.notebook_runtime_seconds ?? ""}
                        onChange={event => update(item.workflow_path, {
                          notebook_runtime_seconds: event.target.value
                            ? Number(event.target.value)
                            : null,
                          confirmed: false,
                        })}
                      />
                    </div>}
                  </td>
                  <td>
                    {item.status === "excluded" ? "—" : <>
                      <span>{parts || "—"}</span>
                      {billingMode === "autoscale" && (item.autoscale_spark_monthly_cu_hours ?? 0) > 0 && <span className="cell-note">
                        Autoscale Spark: {(item.autoscale_spark_monthly_cu_hours ?? 0).toFixed(2)} CU-h/mo
                      </span>}
                    </>}
                  </td>
                  <td>{item.cu_seconds_per_run?.toFixed(1) ?? "—"}</td>
                  <td>{item.monthly_cu_hours?.toFixed(2) ?? "—"}</td>
                </tr>;
              })}
            </tbody>
          </table>
        </div>
      </div>
      <div className="two-column section-gap">
        <div className="panel">
          <div className="panel-header"><div><h2>Coverage</h2><p>Scope represented by this model.</p></div></div>
          <div className="fact-grid">
            <div className="fact"><span>Modeled</span><strong>{estimate.modeled_count}</strong></div>
            <div className="fact"><span>Calibrated (Dataflow)</span><strong>{estimate.calibrated_count ?? estimate.modeled_count}</strong></div>
            <div className="fact"><span>Heuristic (Notebook/Mixed)</span><strong>{estimate.heuristic_count ?? 0}</strong></div>
            <div className="fact"><span>Excluded</span><strong>{estimate.excluded_count}</strong></div>
            <div className="fact"><span>Coverage</span><strong>{estimate.coverage_percent.toFixed(0)}%</strong></div>
            <div className="fact"><span>Model version</span><strong>{estimate.model_version}</strong></div>
          </div>
        </div>
        <div className="panel">
          <div className="panel-header"><div><h2>Assumptions and limitations</h2><p>Interpretation boundary for leadership use.</p></div></div>
          <ul className="assumption-list">
            {estimate.assumptions.map(item => <li key={item}>{item}</li>)}
          </ul>
        </div>
      </div>
    </>}
  </section>;
}
