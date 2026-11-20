import { useEffect, useState } from "react";

export type CapacitySettings = {
  model_version: string;
  days_per_month: number;
  target_utilization: number;
  capacity_floor_cu: number;
  burst_window_minutes: number;
  balance_weight: number;
  active_users_per_day: number;
  average_active_hours_per_user: number;
  peak_concurrent_users: number;
  cu_per_active_user: number;
  interactive_peak_factor: number;
  seconds_per_complexity_element: number;
  minimum_seconds_per_output: number;
  initial_cu_rate: number;
  subsequent_cu_rate: number;
  cu_rate_threshold_seconds: number;
  extra_output_overlap: number;
  projection_variation: number;
  seconds_per_heavy_step_per_thousand_rows: number;
  seconds_per_hundred_rows: number;
  calibration_multiplier: number;
  spark_billing_mode?: "capacity" | "autoscale";
  pipeline_orchestration_cu_seconds_per_activity?: number;
  pipeline_copy_base_seconds?: number;
  pipeline_copy_cu_per_second?: number;
};

export type CapacityWorkflow = {
  workflow_path: string;
  recommended_target?: string;
  target_components?: string[];
  model_basis?: "calibrated" | "heuristic" | null;
  status: "estimated" | "unconfirmed" | "excluded";
  exclusion_reason: string | null;
  refresh_interval_minutes: number;
  source_rows_per_run: number;
  spark_vcores?: number;
  notebook_runtime_seconds?: number | null;
  effective_notebook_runtime_seconds?: number | null;
  confirmed: boolean;
  runs_per_day: number | null;
  complexity_units: number | null;
  heavy_steps?: number;
  duration_driver: "minimum" | "complexity" | "row_volume" | null;
  row_volume_threshold: number | null;
  query_seconds: number | null;
  dataflow_cu_seconds_per_run?: number | null;
  notebook_cu_seconds_per_run?: number | null;
  pipeline_cu_seconds_per_run?: number | null;
  cu_seconds_per_run: number | null;
  projected_cu_seconds_per_run: number | null;
  monthly_cu_hours: number | null;
  autoscale_spark_monthly_cu_hours?: number | null;
};

export type CapacityEstimate = {
  model_version: string;
  status: "inputs_required" | "planning_estimate" | "not_available";
  settings: CapacitySettings;
  workflow_count: number;
  eligible_count: number;
  modeled_count: number;
  excluded_count: number;
  unconfirmed_count: number;
  calibrated_count?: number;
  heuristic_count?: number;
  coverage_percent: number;
  monthly_cu_hours: number;
  daily_cu_seconds: number;
  background_cu: number;
  autoscale_spark_daily_cu_seconds?: number;
  autoscale_spark_monthly_cu_hours?: number;
  target_counts?: Record<string, number>;
  scenarios: Array<{
    name: "Optimized" | "Balance" | "Peak";
    required_cu: number;
    recommended_sku: string;
  }>;
  workflows: CapacityWorkflow[];
  assumptions: string[];
};

type Request = (path: string, init?: RequestInit) => Promise<Response>;
type CapacityState = {
  key: string | null;
  estimate: CapacityEstimate | null;
  error: string | null;
};

function isCapacityEstimate(value: unknown): value is CapacityEstimate {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<CapacityEstimate>;
  return Array.isArray(candidate.scenarios)
    && Array.isArray(candidate.workflows)
    && Array.isArray(candidate.assumptions)
    && typeof candidate.coverage_percent === "number"
    && typeof candidate.status === "string"
    && typeof candidate.monthly_cu_hours === "number";
}

export function useCapacity(
  runId: string | null,
  snapshotId: string | undefined,
  request: Request,
) {
  const key = runId ? `${runId}:${snapshotId ?? ""}` : null;
  const [state, setState] = useState<CapacityState>({
    key: null,
    estimate: null,
    error: null,
  });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let disposed = false;
    if (!runId || !key) return;
    Promise.resolve(request(`/api/runs/${runId}/capacity`))
      .then(response => {
        if (!response) throw new Error("Capacity endpoint did not return a response");
        return response.json() as Promise<unknown>;
      })
      .then(value => {
        if (!isCapacityEstimate(value)) {
          throw new Error("Capacity endpoint returned an invalid response");
        }
        if (!disposed) setState({key, estimate: value, error: null});
      })
      .catch(caught => {
        if (!disposed) {
          setState({
            key,
            estimate: null,
            error: caught instanceof Error
              ? caught.message
              : "Capacity estimate could not be loaded",
          });
        }
      });
    return () => {
      disposed = true;
    };
  }, [key, request, runId]);

  async function save(
    inputs: CapacityWorkflow[],
    nextSettings?: CapacitySettings,
  ) {
    if (!runId || !key) return;
    setSaving(true);
    try {
      const response = await request(`/api/runs/${runId}/capacity`, {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          inputs: inputs
            .filter(item => item.status !== "excluded")
            .map(item => ({
              workflow_path: item.workflow_path,
              refresh_interval_minutes: item.refresh_interval_minutes,
              source_rows_per_run: item.source_rows_per_run,
              spark_vcores: item.spark_vcores ?? 8,
              notebook_runtime_seconds: item.notebook_runtime_seconds ?? null,
              confirmed: true,
            })),
          ...(nextSettings ? {settings: nextSettings} : {}),
        }),
      });
      const value: unknown = await response.json();
      if (!isCapacityEstimate(value)) {
        throw new Error("Capacity endpoint returned an invalid response");
      }
      setState({key, estimate: value, error: null});
    } catch (caught) {
      setState(current => ({
        ...current,
        key,
        error: caught instanceof Error ? caught.message : "Capacity inputs could not be saved",
      }));
    } finally {
      setSaving(false);
    }
  }

  return {
    estimate: state.key === key ? state.estimate : null,
    loading: Boolean(key) && state.key !== key,
    saving,
    error: state.key === key ? state.error : null,
    save,
  };
}
