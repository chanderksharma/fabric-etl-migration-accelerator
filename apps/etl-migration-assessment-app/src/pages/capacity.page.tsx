import { useMemo, useState } from "react";

import { DataState, Panel, Pill } from "@/components/assessment-ui";
import { useAssessmentRunContext } from "@/hooks/assessment-run.context";
import { useQueryRecords } from "@/hooks/use-query-records";
import {
  defaultCapacitySettings,
  estimateCapacity,
  type CapacityProfileMetrics,
  type CapacitySettings,
  type SparkBillingMode,
} from "@/lib/capacity-estimate";
import { downloadCsv, downloadJson } from "@/lib/download";
import { PageFrame } from "@/pages/portfolio.page";
import { workflows } from "@/queries";

type CapacityOverrides = Record<string, {
  refreshIntervalMinutes: number;
  sourceRowsPerRun: number;
  sparkVcores: number;
}>;

interface SavedCapacityScenario {
  settings: CapacitySettings;
  overrides: CapacityOverrides;
}

export function CapacityPage() {
  const { activeRunId, runs, revision } = useAssessmentRunContext();
  const runId = activeRunId ?? runs[0]?.runId ?? "latest";
  return <CapacityPageForRun key={`${runId}:${revision}`} runId={runId} />;
}

function CapacityPageForRun({ runId }: { runId: string }) {
  const workflowQuery = useQueryRecords(workflows.register);
  const profileQuery = useQueryRecords(workflows.capacityProfiles);
  const storageKey = `etl-capacity-scenario:${runId}`;
  const saved = loadCapacityScenario(storageKey);
  const [settings, setSettings] = useState<CapacitySettings>(
    saved?.settings ?? defaultCapacitySettings,
  );
  const [overrides, setOverrides] = useState<CapacityOverrides>(saved?.overrides ?? {});
  const [savedNotice, setSavedNotice] = useState("");

  const profileByKey = useMemo(() => {
    const map = new Map<unknown, CapacityProfileMetrics>();
    for (const record of profileQuery.records) {
      map.set(record.WorkflowKey, {
        profileKind: String(record.ProfileKind ?? "alteryx"),
        targetComponents: String(record.TargetComponents ?? ""),
        complexityUnits: Number(record.ComplexityUnits ?? 0),
        destCount: Number(record.DestCount ?? 0),
        heavySteps: Number(record.HeavySteps ?? 0),
        notebookSteps: Number(record.NotebookSteps ?? 0),
        pipelineSteps: Number(record.PipelineSteps ?? 0),
        totalSteps: Number(record.TotalSteps ?? 0),
        coveredByLinkedMapping: Boolean(record.CoveredByLinkedMapping),
      });
    }
    return map;
  }, [profileQuery.records]);

  const estimate = useMemo(
    () =>
      estimateCapacity(
        workflowQuery.records.map((record) => ({
          workflowPath: String(record.WorkflowPath ?? ""),
          recommendedTarget: String(record.RecommendedTarget ?? ""),
          toolCount: Number(record.ToolCount ?? 0),
          complexityScore: Number(record.ComplexityScore ?? 0),
          profile: profileByKey.get(record.WorkflowKey),
          ...overrides[String(record.WorkflowPath ?? "")],
        })),
        settings,
      ),
    [overrides, profileByKey, settings, workflowQuery.records],
  );

  const rows = estimate.workflows.map((item) => ({
    WorkflowPath: item.workflowPath,
    RecommendedTarget: item.recommendedTarget,
    Basis: item.basis,
    DataflowCu: item.dataflowCuSecondsPerRun,
    NotebookCu: item.notebookCuSecondsPerRun,
    PipelineCu: item.pipelineCuSecondsPerRun,
    CuSeconds: item.cuSecondsPerRun,
    MonthlyCuHours: item.monthlyCuHours,
    RefreshIntervalMinutes: item.refreshIntervalMinutes,
    SourceRowsPerRun: item.sourceRowsPerRun,
    SparkVcores: item.sparkVcores,
  }));

  const hasStaticProfiles = profileByKey.size > 0;

  return (
    <PageFrame
      title="Capacity planning"
      subtitle="Calibrated Fabric Dataflow Gen2, Notebook, and Pipeline sizing from static workflow profiles."
    >
      <div className="flex flex-wrap justify-end gap-2">
        <button
          type="button"
          className="rounded-lg border bg-background px-3 py-2 text-200 font-semibold hover:bg-hover"
          disabled={!rows.length}
          onClick={() => downloadCsv(
            "capacity-estimate.csv",
            [
              "WorkflowPath",
              "RecommendedTarget",
              "Basis",
              "RefreshIntervalMinutes",
              "SourceRowsPerRun",
              "SparkVcores",
              "DataflowCu",
              "NotebookCu",
              "PipelineCu",
              "CuSeconds",
              "MonthlyCuHours",
            ],
            rows,
          )}
        >
          Export CSV
        </button>
        <button
          type="button"
          className="rounded-lg border bg-background px-3 py-2 text-200 font-semibold hover:bg-hover"
          disabled={!rows.length}
          onClick={() => downloadJson("capacity-estimate.json", {
            runId,
            settings,
            overrides,
            estimate,
          })}
        >
          Export JSON
        </button>
        <button
          type="button"
          className="rounded-lg bg-brand px-3 py-2 text-200 font-semibold text-on-brand"
          onClick={() => {
            localStorage.setItem(storageKey, JSON.stringify({ settings, overrides }));
            setSavedNotice("Capacity assumptions saved in this browser for the selected run.");
          }}
        >
          Save assumptions
        </button>
      </div>
      {savedNotice && <p className="text-right text-200 text-muted-foreground" role="status">{savedNotice}</p>}
      <div className="rounded-xl border border-brand bg-card p-5">
        <strong>{hasStaticProfiles ? "Calibrated + heuristic planning estimate" : "Preliminary planning estimate"}</strong>
        <p className="mt-1 text-200 text-muted-foreground">
          {hasStaticProfiles
            ? "Dataflow Gen2 estimates use persisted static complexity and heavy-step profiles (model v3.1.0). Notebook, Pipeline, and Manual rework routes use heuristic assumptions."
            : "Persisted static capacity profiles were not found for this run; falling back to normalized workflow counts. Run an assessment with the updated notebook to enable calibrated profile sizing."}
        </p>
      </div>

      <Panel title="Operational assumptions" subtitle="Adjust schedule, volume, Spark sizing, and capacity utilization for interactive F-SKU scenarios">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
          <label className="text-200 font-semibold">
            Refresh schedule
            <select
              className="mt-1 w-full rounded-lg border bg-background p-2.5 font-normal"
              value={settings.refreshIntervalMinutes}
              onChange={(event) =>
                setSettings((prev) => ({ ...prev, refreshIntervalMinutes: Number(event.target.value) }))
              }
            >
              <option value={1440}>Daily (1,440 min)</option>
              <option value={720}>Twice daily (720 min)</option>
              <option value={360}>Every 6 hours</option>
              <option value={60}>Hourly (60 min)</option>
            </select>
          </label>
          <label className="text-200 font-semibold">
            Source rows / run
            <input
              type="number"
              min={1}
              step={1000}
              className="mt-1 w-full rounded-lg border bg-background p-2.5 font-normal"
              value={settings.sourceRowsPerRun}
              onChange={(event) =>
                setSettings((prev) => ({ ...prev, sourceRowsPerRun: Number(event.target.value) || 1 }))
              }
            />
          </label>
          <label className="text-200 font-semibold">
            Spark vCores
            <select
              className="mt-1 w-full rounded-lg border bg-background p-2.5 font-normal"
              value={settings.sparkVcores}
              onChange={(event) =>
                setSettings((prev) => ({ ...prev, sparkVcores: Number(event.target.value) }))
              }
            >
              {[4, 8, 16, 32, 64].map((vcores) => (
                <option key={vcores} value={vcores}>
                  {vcores} vCores
                </option>
              ))}
            </select>
          </label>
          <label className="text-200 font-semibold">
            Spark billing
            <select
              className="mt-1 w-full rounded-lg border bg-background p-2.5 font-normal"
              value={settings.sparkBillingMode}
              onChange={(event) =>
                setSettings((prev) => ({ ...prev, sparkBillingMode: event.target.value as SparkBillingMode }))
              }
            >
              <option value="capacity">Capacity F-SKU</option>
              <option value="autoscale">Autoscale Spark</option>
            </select>
          </label>
          <label className="text-200 font-semibold">
            Days / month
            <input
              type="number"
              min={1}
              max={366}
              className="mt-1 w-full rounded-lg border bg-background p-2.5 font-normal"
              value={settings.daysPerMonth}
              onChange={(event) =>
                setSettings((prev) => ({ ...prev, daysPerMonth: Number(event.target.value) || 31 }))
              }
            />
          </label>
          <label className="text-200 font-semibold">
            Utilization (%)
            <input
              type="number"
              min={10}
              max={100}
              className="mt-1 w-full rounded-lg border bg-background p-2.5 font-normal"
              value={Math.round(settings.targetUtilization * 100)}
              onChange={(event) =>
                setSettings((prev) => ({
                  ...prev,
                  targetUtilization: Math.min(Math.max(Number(event.target.value) || 80, 10), 100) / 100,
                }))
              }
            />
          </label>
          <label className="text-200 font-semibold">
            Interactive users
            <input
              type="number"
              min={0}
              max={10_000}
              className="mt-1 w-full rounded-lg border bg-background p-2.5 font-normal"
              value={settings.interactiveUsers}
              onChange={(event) =>
                setSettings((prev) => ({ ...prev, interactiveUsers: Number(event.target.value) || 0 }))
              }
            />
          </label>
          <label className="text-200 font-semibold">
            Burst window (min)
            <input
              type="number"
              min={1}
              max={1440}
              className="mt-1 w-full rounded-lg border bg-background p-2.5 font-normal"
              value={settings.burstWindowMinutes}
              onChange={(event) =>
                setSettings((prev) => ({ ...prev, burstWindowMinutes: Number(event.target.value) || 5 }))
              }
            />
          </label>
        </div>
      </Panel>

      <DataState isLoading={workflowQuery.isLoading} error={workflowQuery.error} empty={!workflowQuery.records.length} />
      {!!workflowQuery.records.length && (
        <>
          <div className="grid gap-(--grid-gap) md:grid-cols-3">
            {estimate.scenarios.map((scenario) => (
              <Panel
                key={scenario.name}
                title={scenario.name}
                subtitle={`Every ${settings.refreshIntervalMinutes} min · ${settings.sourceRowsPerRun.toLocaleString()} rows/run`}
              >
                <div className="flex items-end justify-between gap-3">
                  <div>
                    <span className="text-page-title font-semibold">{scenario.recommendedSku}</span>
                    <p className="text-200 text-muted-foreground">{scenario.requiredCu.toFixed(2)} required CUs</p>
                  </div>
                  <Pill tone={scenario.name === "Optimized" ? "success" : "warning"}>{scenario.name}</Pill>
                </div>
              </Panel>
            ))}
          </div>
          <div className="grid gap-(--grid-gap) xl:grid-cols-3">
            <Panel title="Monthly base demand" subtitle={`${settings.daysPerMonth} days/month (${settings.sparkBillingMode} Spark)`}>
              <p className="text-page-title font-semibold">{estimate.monthlyCuHours.toFixed(1)}</p>
              <p className="text-200 text-muted-foreground">
                CU-hours across modeled workflows
                {settings.sparkBillingMode === "autoscale"
                  ? ` (+ ${estimate.autoscaleSparkMonthlyCuHours.toFixed(1)} Autoscale Spark CU-h)`
                  : ""}
              </p>
            </Panel>
            <Panel title="Coverage" subtitle="Persisted static profile match">
              <p className="text-page-title font-semibold">{estimate.workflows.length}</p>
              <p className="text-200 text-muted-foreground">
                {estimate.calibratedCount} calibrated · {estimate.heuristicCount} heuristic
              </p>
            </Panel>
            <Panel title="Model basis" subtitle="Capacity model v3.1.0">
              <p className="text-page-title font-semibold">{hasStaticProfiles ? "Calibrated" : "Heuristic"}</p>
              <p className="text-200 text-muted-foreground">Calibrate with measured pilot evidence</p>
            </Panel>
          </div>
          <Panel
            title="Workflow capacity contributions"
            subtitle="Per-workflow overrides are saved locally for this browser and selected run"
          >
            <div className="overflow-x-auto">
              <table className="w-full border-separate border-spacing-0 text-left text-200">
                <thead>
                  <tr>
                    {["Workflow", "Refresh (min)", "Rows/run", "Spark vCores", "Basis", "CU-s/run", "Monthly CU-h"].map((label) => (
                      <th className="border-b p-3" key={label}>{label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {estimate.workflows.map((item) => (
                    <tr key={item.workflowPath}>
                      <td className="border-b p-3"><strong>{item.workflowPath}</strong><span className="block text-muted-foreground">{item.recommendedTarget}</span></td>
                      <td className="border-b p-3">
                        <input
                          aria-label={`Refresh interval for ${item.workflowPath}`}
                          type="number"
                          min={1}
                          max={1440}
                          className="w-24 rounded border bg-background p-2"
                          value={item.refreshIntervalMinutes}
                          onChange={(event) => updateOverride(item.workflowPath, { refreshIntervalMinutes: Number(event.target.value) || 1 })}
                        />
                      </td>
                      <td className="border-b p-3">
                        <input
                          aria-label={`Source rows for ${item.workflowPath}`}
                          type="number"
                          min={1}
                          className="w-32 rounded border bg-background p-2"
                          value={item.sourceRowsPerRun}
                          onChange={(event) => updateOverride(item.workflowPath, { sourceRowsPerRun: Number(event.target.value) || 1 })}
                        />
                      </td>
                      <td className="border-b p-3">
                        <select
                          aria-label={`Spark vCores for ${item.workflowPath}`}
                          className="rounded border bg-background p-2"
                          value={item.sparkVcores}
                          onChange={(event) => updateOverride(item.workflowPath, { sparkVcores: Number(event.target.value) })}
                        >
                          {[4, 8, 16, 32, 64].map((value) => <option key={value}>{value}</option>)}
                        </select>
                      </td>
                      <td className="border-b p-3">{item.basis}</td>
                      <td className="border-b p-3">{item.cuSecondsPerRun.toFixed(1)}</td>
                      <td className="border-b p-3">{item.monthlyCuHours.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
          <Panel title="Assumptions and limitations">
            <ul className="space-y-2 text-200 text-muted-foreground">
              <li>Calibrated Dataflow Gen2 curve uses persisted static complexity units, heavy steps, and output counts</li>
              <li>Notebook ({settings.sparkVcores / 2} Spark CUs), Pipeline, and Manual rework routes use heuristic assumptions</li>
              <li>Optimized assumes staggered execution; Peak assumes concurrent starts within the {settings.burstWindowMinutes}-minute burst window</li>
              <li>Storage, network egress, and Microsoft Fabric pricing remain excluded</li>
            </ul>
          </Panel>
        </>
      )}
    </PageFrame>
  );

  function updateOverride(
    workflowPath: string,
    patch: Partial<CapacityOverrides[string]>,
  ) {
    setOverrides((current) => ({
      ...current,
      [workflowPath]: {
        refreshIntervalMinutes:
          current[workflowPath]?.refreshIntervalMinutes ?? settings.refreshIntervalMinutes,
        sourceRowsPerRun:
          current[workflowPath]?.sourceRowsPerRun ?? settings.sourceRowsPerRun,
        sparkVcores: current[workflowPath]?.sparkVcores ?? settings.sparkVcores,
        ...patch,
      },
    }));
    setSavedNotice("");
  }
}

function loadCapacityScenario(storageKey: string): SavedCapacityScenario | null {
  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<SavedCapacityScenario>;
    if (!parsed.settings || !parsed.overrides) return null;
    return {
      settings: { ...defaultCapacitySettings, ...parsed.settings },
      overrides: parsed.overrides,
    };
  } catch {
    return null;
  }
}
