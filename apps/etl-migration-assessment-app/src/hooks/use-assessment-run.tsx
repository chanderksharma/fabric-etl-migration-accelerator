import { useCallback, useMemo, useState, type ReactNode } from "react";

import { AssessmentRunContext, type AssessmentRunOption } from "@/hooks/assessment-run.context";
import { useQueryRecords } from "@/hooks/use-query-records";
import { clearQueryCache } from "@/hooks/use-semantic-model-query";
import { isAssessmentRunId } from "@/lib/assessment-run-scope";
import { assessmentRuns } from "@/queries";

const selectedRunStorageKey = "etl-migration-assessment-run";

function storedRunId(): string | null {
  const value = sessionStorage.getItem(selectedRunStorageKey);
  return value && isAssessmentRunId(value) ? value : null;
}

export function AssessmentRunProvider({ children }: { children: ReactNode }) {
  const {
    records,
    isLoading,
    error,
    refetch,
  } = useQueryRecords(assessmentRuns);
  const [activeRunId, setActiveRunId] = useState<string | null>(storedRunId);
  const [revision, setRevision] = useState(0);
  const runs = useMemo<AssessmentRunOption[]>(
    () => records.map((record) => ({
      runId: String(record.RunId ?? ""),
      runLabel: String(record.RunLabel ?? "Assessment run"),
      startedAtUtc: String(record.StartedAtUtc ?? ""),
      completedAtUtc: String(record.CompletedAtUtc ?? ""),
      workflowCount: Number(record.WorkflowCount ?? 0),
      failedCount: Number(record.FailedCount ?? 0),
      skippedCount: Number(record.SkippedCount ?? 0),
      rulesVersion: String(record.RulesVersion ?? ""),
      inputPath: String(record.InputPath ?? ""),
      routingBasis: (
        record.RoutingBasis === "static_mapping"
          ? "static_mapping"
          : "compiler_confirmed"
      ) as AssessmentRunOption["routingBasis"],
    })).filter((run) => isAssessmentRunId(run.runId)),
    [records],
  );

  const selectRun = useCallback((runId: string | null) => {
    if (runId && !isAssessmentRunId(runId)) {
      throw new Error("Invalid assessment run ID.");
    }
    setActiveRunId(runId);
    if (runId) {
      sessionStorage.setItem(selectedRunStorageKey, runId);
    } else {
      sessionStorage.removeItem(selectedRunStorageKey);
    }
  }, []);

  const resolvedActiveRunId = activeRunId
    && (isLoading || error || runs.some((run) => run.runId === activeRunId))
    ? activeRunId
    : null;

  const refreshRuns = useCallback(async (options?: { selectLatest?: boolean }) => {
    if (options?.selectLatest) {
      selectRun(null);
    }
    clearQueryCache("assessmentmodel");
    setRevision((value) => value + 1);
    await refetch();
  }, [refetch, selectRun]);

  const value = useMemo(
    () => ({
      activeRunId: resolvedActiveRunId,
      runs,
      isLoading,
      error,
      revision,
      selectRun,
      refreshRuns,
    }),
    [error, isLoading, refreshRuns, resolvedActiveRunId, revision, runs, selectRun],
  );

  return <AssessmentRunContext.Provider value={value}>{children}</AssessmentRunContext.Provider>;
}
