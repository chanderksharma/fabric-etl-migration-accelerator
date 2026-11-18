import { useEffect, useState } from "react";
import type { EvidenceResponse } from "./evidence-types";

type Request = (path: string, init?: RequestInit) => Promise<Response>;

const evidenceCache = new Map<string, EvidenceResponse>();

export function useEvidence(
  enabled: boolean,
  runId: string | null,
  snapshotId: string | undefined,
  index: number | null,
  request: Request,
) {
  const key = `${runId}:${snapshotId}:${index ?? "all"}`;
  const [state, setState] = useState<{
    key: string;
    data: EvidenceResponse | null;
    error: string | null;
    loading: boolean;
  }>({
    key: "", data: null, error: null, loading: false,
  });

  useEffect(() => {
    if (!enabled) return;
    if (!runId || !snapshotId || (index !== null && index < 0)) return;
    const controller = new AbortController();
    const cached = evidenceCache.get(key);
    if (cached) {
      evidenceCache.delete(key);
      evidenceCache.set(key, cached);
      return;
    }
    void request(`/api/runs/${runId}/evidence${index === null ? "" : `?workflow_index=${index}`}`, {
      signal: controller.signal,
    }).then(async response => {
      const data: EvidenceResponse = await response.json();
      if (controller.signal.aborted) return;
      if (data.schema_version !== "1.1.0" || data.run_id !== runId || data.snapshot_id !== snapshotId) {
        throw new Error("Evidence does not match the selected run and snapshot.");
      }
      if (index !== null && (!data.workflows.length || data.workflows.some(item => item.workflow_index !== index))) {
        throw new Error("Evidence does not match the selected workflow index.");
      }
      evidenceCache.set(key, data);
      while (evidenceCache.size > 20) {
        const oldest = evidenceCache.keys().next().value;
        if (oldest !== undefined) evidenceCache.delete(oldest);
      }
      setState({key, data, error: null, loading: false});
    }).catch((error: unknown) => {
      if (error instanceof Error && "status" in error && error.status === 409) {
        for (const cachedKey of evidenceCache.keys()) {
          if (cachedKey.startsWith(`${runId}:`)) evidenceCache.delete(cachedKey);
        }
      }
      if (!controller.signal.aborted) {
        setState({
          key,
          data: null,
          error: error instanceof Error ? error.message : "Could not load workflow evidence",
          loading: false,
        });
      }
    });
    return () => controller.abort();
  }, [enabled, runId, snapshotId, index, request, key]);

  if (enabled && (!runId || !snapshotId)) return {
    data: null, error: "Snapshot evidence is unavailable. Reload a completed assessment.", loading: false,
  };
  if (enabled && index !== null && index < 0) return {
    data: null, error: "No snapshot descriptor matches this workflow. Reload the completed run.", loading: false,
  };
  const cached = evidenceCache.get(key);
  return cached ? {data: cached, error: null, loading: false}
    : state.key === key ? state : {data: null, error: null, loading: enabled};
}
