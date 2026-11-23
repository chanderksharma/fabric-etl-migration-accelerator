import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, ExternalLink, LoaderCircle, RefreshCw, Rocket, ShieldCheck, XCircle } from "lucide-react";

import { useAssessmentRunContext } from "@/hooks/assessment-run.context";
import { useSemanticModelQuery } from "@/hooks/use-semantic-model-query";
import { getRayfinClient } from "@/lib/rayfin-client";
import { toDataTable } from "@/lib/to-data-table";
import { PageFrame } from "@/pages/portfolio.page";
import { workflows } from "@/queries";
import type { AppFunctionsSchema } from "../../rayfin/functions/src/types";

type DeploymentProvider = "github" | "gitlab";
type ConflictBehavior = "Fail" | "Skip" | "Update";
type DeploymentPreview = AppFunctionsSchema["previewDeployment"]["output"];
type DeploymentResult = AppFunctionsSchema["dispatchDeployment"]["output"];
type DeploymentConfiguration = AppFunctionsSchema["getDeploymentConfiguration"]["output"];

interface WorkflowOption {
  workflowPath: string;
  sourcePlatform: string;
  nativeId: string;
  recommendedTarget: string;
  migrationWave: string;
  complexityScore: number;
}

export function DeploymentPage({
  preselectedWorkflowPath,
}: {
  preselectedWorkflowPath?: string;
}) {
  const { activeRunId, runs, refreshRuns } = useAssessmentRunContext();
  const selectedRun = activeRunId
    ? runs.find((run) => run.runId === activeRunId)
    : runs[0];
  const { data, isLoading, error: queryError } = useSemanticModelQuery(workflows.register);
  const [provider, setProvider] = useState<DeploymentProvider>("github");
  const [repositoryUrl, setRepositoryUrl] = useState("");
  const [gitRef, setGitRef] = useState("");
  const [conflictBehavior, setConflictBehavior] = useState<ConflictBehavior>("Update");
  const [selected, setSelected] = useState<Set<string>>(() =>
    preselectedWorkflowPath ? new Set([preselectedWorkflowPath]) : new Set(),
  );
  const [preview, setPreview] = useState<DeploymentPreview>();
  const [confirmed, setConfirmed] = useState(false);
  const [result, setResult] = useState<DeploymentResult>();
  const [feedback, setFeedback] = useState("");
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isDispatching, setIsDispatching] = useState(false);
  const [configuration, setConfiguration] = useState<DeploymentConfiguration>();
  const [configurationError, setConfigurationError] = useState("");
  const [fitJobInstanceId, setFitJobInstanceId] = useState("");
  const [fitStatus, setFitStatus] = useState("");
  const [isStartingFit, setIsStartingFit] = useState(false);

  useEffect(() => {
    if (!fitJobInstanceId || ["Completed", "Failed", "Cancelled", "Deduped"].includes(fitStatus)) {
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const status = await getRayfinClient().functions.getAssessmentStatus.invoke(
          { jobInstanceId: fitJobInstanceId },
          { timeoutMs: 120_000 },
        );
        if (cancelled) return;
        setFitStatus(status.status);
        if (status.status === "Completed") {
          await refreshRuns({ selectLatest: true });
        } else if (status.status === "Failed" || status.status === "Cancelled") {
          setFeedback(formatFailureReason(status.failureReason) || `Fabric fit ${status.status.toLowerCase()}.`);
        } else {
          timer = setTimeout(poll, 5_000);
        }
      } catch (reason) {
        if (!cancelled) {
          setFeedback(reason instanceof Error ? reason.message : String(reason));
        }
      }
    };
    timer = setTimeout(poll, 3_000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [fitJobInstanceId, fitStatus, refreshRuns]);

  useEffect(() => {
    let cancelled = false;
    void getRayfinClient().functions.getDeploymentConfiguration
      .invoke(undefined, { timeoutMs: 120_000 })
      .then((value) => {
        if (!cancelled) setConfiguration(value);
      })
      .catch((reason) => {
        if (!cancelled) {
          setConfigurationError(reason instanceof Error ? reason.message : String(reason));
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const allWorkflows = useMemo(() => {
    if (data?.status !== "success") return [];
    const table = toDataTable(data.table, workflows.register.columnMetadata);
    const indexes = Object.fromEntries(table.columns.map((column, index) => [column.name, index]));
    return table.rows
      .map((row): WorkflowOption => ({
        workflowPath: String(row[indexes.WorkflowPath] ?? ""),
        sourcePlatform: String(row[indexes.SourcePlatform] ?? ""),
        nativeId: String(row[indexes.NativeId] ?? ""),
        recommendedTarget: String(row[indexes.RecommendedTarget] ?? ""),
        migrationWave: String(row[indexes.MigrationWave] ?? ""),
        complexityScore: Number(row[indexes.ComplexityScore] ?? 0),
      }))
      .filter((workflow) => workflow.workflowPath);
  }, [data]);
  const workflowOptions = useMemo(
    () => allWorkflows.filter((workflow) => workflow.recommendedTarget !== "Manual rework"),
    [allWorkflows],
  );
  const preselectionNotice = useMemo(() => {
    if (!preselectedWorkflowPath) return "";
    const matched = allWorkflows.find((item) => item.workflowPath === preselectedWorkflowPath);
    if (matched && matched.recommendedTarget === "Manual rework") {
      return `${preselectedWorkflowPath} requires manual rework and is not dispatchable.`;
    }
    return "";
  }, [allWorkflows, preselectedWorkflowPath]);

  const validSelected = useMemo(() => {
    const readyPaths = new Set(workflowOptions.map((item) => item.workflowPath));
    return new Set([...selected].filter((path) => readyPaths.has(path)));
  }, [selected, workflowOptions]);
  const providerConfigured =
    provider === "github"
      ? configuration?.githubConfigured
      : configuration?.gitlabConfigured;
  const fitConfirmed = Boolean(
    selectedRun && selectedRun.routingBasis !== "static_mapping",
  );

  const clearApproval = () => {
    setPreview(undefined);
    setConfirmed(false);
    setResult(undefined);
    setFeedback("");
  };

  const updateProvider = (value: DeploymentProvider) => {
    setProvider(value);
    clearApproval();
  };

  const toggleWorkflow = (workflowPath: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(workflowPath)) next.delete(workflowPath);
      else if (next.size < 10) next.add(workflowPath);
      return next;
    });
    clearApproval();
  };

  const previewManifest = async () => {
    setFeedback("");
    setResult(undefined);
    setIsPreviewing(true);
    try {
      const selections = workflowOptions
        .filter((workflow) => validSelected.has(workflow.workflowPath))
        .map(({ workflowPath, sourcePlatform, nativeId, recommendedTarget }) => ({
          workflowPath,
          sourcePlatform,
          nativeId,
          recommendedTarget,
        }));
      const nextPreview = await getRayfinClient().functions.previewDeployment.invoke(
        {
          providerValue: provider,
          repositoryUrl,
          refValue: gitRef,
          conflictBehaviorValue: conflictBehavior,
          selectionsJson: JSON.stringify(selections),
        },
        { timeoutMs: 120_000 },
      );
      setPreview(nextPreview);
      setConfirmed(false);
      setFeedback("Manifest validated. Review every selection before confirming dispatch.");
    } catch (reason) {
      setFeedback(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setIsPreviewing(false);
    }
  };

  const dispatch = async () => {
    if (!preview || !confirmed) return;
    setFeedback("");
    setIsDispatching(true);
    try {
      const dispatchResult = await getRayfinClient().functions.dispatchDeployment.invoke(
        { confirmationToken: preview.confirmationToken },
        { timeoutMs: 250_000 },
      );
      setResult(dispatchResult);
      const failures = dispatchResult.results.filter((item) => item.status === "failed").length;
      setFeedback(
        failures
          ? `${failures} deployment dispatch${failures === 1 ? "" : "es"} failed. Review the item results.`
          : `${dispatchResult.results.length} deployment dispatch${dispatchResult.results.length === 1 ? "" : "es"} accepted.`,
      );
    } catch (reason) {
      setFeedback(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setIsDispatching(false);
    }
  };

  const confirmFabricFit = async () => {
    if (!selectedRun?.inputPath) {
      setFeedback("This assessment run does not retain an input path. Run a new static assessment first.");
      return;
    }
    setFeedback("");
    setIsStartingFit(true);
    try {
      const result = await getRayfinClient().functions.startFabricFit.invoke(
        { inputPath: selectedRun.inputPath },
        { timeoutMs: 120_000 },
      );
      setFitJobInstanceId(result.jobInstanceId);
      setFitStatus("Submitted");
      setFeedback("Compiler-confirmed Fabric fit submitted. Dispatch remains disabled until it completes.");
    } catch (reason) {
      setFeedback(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setIsStartingFit(false);
    }
  };

  return (
    <PageFrame
      title="CI/CD dispatch"
      subtitle="Dispatch existing generated-fabric-workflows definitions through approved GitHub Actions or GitLab CI controls."
    >
      <div className="flex items-start gap-3 rounded-xl border border-brand bg-card p-4">
        <ShieldCheck className="icon-size-300 shrink-0 text-brand-foreground" aria-hidden="true" />
        <div>
          <p className="font-semibold">Dispatch-only security boundary</p>
          <p className="mt-1 text-200 text-muted-foreground">
            The app validates an existing CI definition and sends one dispatch per confirmed workflow. It never accepts provider tokens in the browser or calls Fabric item deployment APIs directly.
          </p>
        </div>

        <div className="rounded-xl border bg-card p-5" role="note">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <strong>
                Routing basis: {fitConfirmed
                  ? "compiler-confirmed Fabric fit"
                  : "static mapping"}.
              </strong>
              <p className="mt-1 text-200 text-muted-foreground">
                {fitConfirmed
                  ? "This run can proceed to manifest validation. Generated artifacts must already exist in the selected repository and ref."
                  : "Confirm Fabric fit before dispatch. This runs the compilers in a separate notebook job and stores a new confirmed run; it does not generate repository artifacts."}
              </p>
              {fitStatus && (
                <p className="mt-2 text-200">
                  Fabric fit status: <strong>{fitStatus}</strong>
                </p>
              )}
            </div>
            {!fitConfirmed && (
              <button
                className="inline-flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-300 font-semibold text-on-brand disabled:cursor-not-allowed disabled:opacity-50"
                type="button"
                disabled={isStartingFit || Boolean(fitJobInstanceId && !["Completed", "Failed", "Cancelled", "Deduped"].includes(fitStatus))}
                onClick={() => void confirmFabricFit()}
              >
                {isStartingFit || (fitJobInstanceId && !["Completed", "Failed", "Cancelled", "Deduped"].includes(fitStatus))
                  ? <RefreshCw className="icon-size-200 animate-spin" />
                  : <ShieldCheck className="icon-size-200" />}
                Confirm Fabric fit
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="grid gap-(--grid-gap) xl:grid-cols-5">
        <section className="space-y-5 rounded-xl border bg-card p-6 shadow-container-2 xl:col-span-2">
          <h2 className="font-visual-title text-visual-title font-semibold">CI/CD target</h2>
          <label className="block text-200 font-semibold" htmlFor="deployment-provider">
            CI/CD provider
          </label>
          <select
            id="deployment-provider"
            className="w-full rounded-lg border bg-background p-3 text-300 focus:outline-none focus:ring-2 focus:ring-ring"
            value={provider}
            onChange={(event) => updateProvider(event.target.value as DeploymentProvider)}
          >
            <option value="github">GitHub Actions</option>
            <option value="gitlab">GitLab CI</option>
          </select>

          {configurationError && (
            <p role="alert" className="rounded-lg border border-destructive p-3 text-200 text-destructive">
              Deployment configuration could not be checked: {configurationError}
            </p>
          )}
          {configuration && !providerConfigured && (
            <p role="status" className="rounded-lg border border-brand p-3 text-200 text-muted-foreground">
              {provider === "github"
                ? "Configure GITHUB_TOKEN and GITHUB_ALLOWED_REPOSITORIES as Fabric App secrets before previewing."
                : "Configure GITLAB_TOKEN and GITLAB_ALLOWED_PROJECTS as Fabric App secrets before previewing."}
            </p>
          )}

          <label className="block text-200 font-semibold" htmlFor="repository-url">
            {provider === "github" ? "GitHub repository URL" : "GitLab project URL"}
          </label>
          <input
            id="repository-url"
            className="w-full rounded-lg border bg-background p-3 text-300 focus:outline-none focus:ring-2 focus:ring-ring"
            type="url"
            placeholder={provider === "github" ? "https://github.com/owner/repository" : "https://gitlab.com/group/project"}
            value={repositoryUrl}
            onChange={(event) => {
              setRepositoryUrl(event.target.value);
              clearApproval();
            }}
          />

          <label className="block text-200 font-semibold" htmlFor="git-ref">
            Git ref
          </label>
          <input
            id="git-ref"
            className="w-full rounded-lg border bg-background p-3 text-300 focus:outline-none focus:ring-2 focus:ring-ring"
            placeholder="Repository default branch"
            value={gitRef}
            onChange={(event) => {
              setGitRef(event.target.value);
              clearApproval();
            }}
          />

          <label className="block text-200 font-semibold" htmlFor="conflict-behavior">
            Existing item behavior
          </label>
          <select
            id="conflict-behavior"
            className="w-full rounded-lg border bg-background p-3 text-300 focus:outline-none focus:ring-2 focus:ring-ring"
            value={conflictBehavior}
            onChange={(event) => {
              setConflictBehavior(event.target.value as ConflictBehavior);
              clearApproval();
            }}
          >
            <option value="Fail">Fail</option>
            <option value="Skip">Skip</option>
            <option value="Update">Update</option>
          </select>
        </section>

        <section className="rounded-xl border bg-card p-6 shadow-container-2 xl:col-span-3">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="font-visual-title text-visual-title font-semibold">Ready workflows</h2>
              <p className="mt-1 text-200 text-muted-foreground">Select up to ten compiler-confirmed workflows whose generated artifacts already exist in the repository.</p>
            </div>
            <span className="rounded-full bg-muted px-3 py-1 text-200 font-semibold">{validSelected.size} selected</span>
          </div>
          {queryError ? (
            <p role="alert" className="mt-5 text-destructive">{queryError.message}</p>
          ) : isLoading || !data ? (
            <div className="mt-5 flex items-center gap-2 text-muted-foreground">
              <LoaderCircle className="icon-size-200 animate-spin" />
              Loading ready workflows
            </div>
          ) : (
            <div className="mt-5 max-h-96 space-y-2 overflow-auto pr-2">
              {workflowOptions.map((workflow) => (
                <label key={workflow.workflowPath} className="flex cursor-pointer items-start gap-3 rounded-lg border p-3 hover:bg-hover">
                  <input
                    className="mt-1"
                    type="checkbox"
                    checked={validSelected.has(workflow.workflowPath)}
                    disabled={!validSelected.has(workflow.workflowPath) && validSelected.size >= 10}
                    onChange={() => toggleWorkflow(workflow.workflowPath)}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-semibold">{workflow.workflowPath}</span>
                    <span className="mt-1 block text-200 text-muted-foreground">
                      {workflow.recommendedTarget} · {workflow.migrationWave} · complexity {workflow.complexityScore}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          )}
        </section>
      </div>

      <section className="rounded-xl border bg-card p-6 shadow-container-2">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="font-visual-title text-visual-title font-semibold">Manifest approval</h2>
            <p className="mt-1 text-200 text-muted-foreground">Preview validates the provider, repository allow-list, CI definition, ref, and artifact paths without dispatching.</p>
          </div>
          <button
            className="inline-flex items-center gap-2 rounded-lg border bg-background px-4 py-2 text-300 font-semibold hover:bg-hover focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
            type="button"
            disabled={!fitConfirmed || isPreviewing || validSelected.size === 0 || !repositoryUrl || !providerConfigured}
            onClick={() => void previewManifest()}
          >
            {isPreviewing ? <LoaderCircle className="icon-size-200 animate-spin" /> : <ShieldCheck className="icon-size-200" />}
            Preview manifest
          </button>
        </div>

        {preview && (
          <div className="mt-6 space-y-4">
            <dl className="grid gap-3 rounded-lg bg-muted p-4 sm:grid-cols-2 lg:grid-cols-4">
              <div><dt className="text-100 uppercase text-muted-foreground">Provider</dt><dd className="font-semibold">{preview.manifest.provider}</dd></div>
              <div><dt className="text-100 uppercase text-muted-foreground">Repository</dt><dd className="break-all font-semibold">{preview.manifest.repository}</dd></div>
              <div><dt className="text-100 uppercase text-muted-foreground">Ref</dt><dd className="font-semibold">{preview.manifest.ref}</dd></div>
              <div><dt className="text-100 uppercase text-muted-foreground">Expires</dt><dd className="font-semibold">{new Date(preview.manifest.expiresAt).toLocaleTimeString()}</dd></div>
            </dl>
            <div className="overflow-x-auto">
              <table className="w-full border-separate border-spacing-0 text-left text-200">
                <thead><tr><th className="border-b p-3">Workflow</th><th className="border-b p-3">Artifact path</th><th className="border-b p-3">Target</th></tr></thead>
                <tbody>
                  {preview.manifest.selections.map((selection) => (
                    <tr key={selection.workflowPath}>
                      <td className="border-b p-3">{selection.workflowPath}</td>
                      <td className="border-b p-3 font-monospace">{selection.artifactPath}</td>
                      <td className="border-b p-3">{selection.target}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <label className="flex items-start gap-3 rounded-lg border border-brand p-4">
              <input className="mt-1" type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
              <span>I reviewed the provider, ref, conflict behavior, workflow selections, artifact paths, and targets above.</span>
            </label>
            <button
              className="inline-flex items-center gap-2 rounded-lg bg-brand px-4 py-3 text-300 font-semibold text-on-brand focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              type="button"
              disabled={!confirmed || isDispatching}
              onClick={() => void dispatch()}
            >
              {isDispatching ? <LoaderCircle className="icon-size-200 animate-spin" /> : <Rocket className="icon-size-200" />}
              Confirm and dispatch
            </button>
          </div>
        )}

        {(feedback || preselectionNotice) && <p className="mt-4 text-200" role="status">{feedback || preselectionNotice}</p>}
        {result && (
          <ul className="mt-5 space-y-2">
            {result.results.map((item) => (
              <li key={item.workflowPath} className="flex items-start gap-3 rounded-lg border p-3">
                {item.status === "dispatched" ? (
                  <CheckCircle2 className="icon-size-200 shrink-0 text-success" />
                ) : (
                  <XCircle className="icon-size-200 shrink-0 text-destructive" />
                )}
                <div className="min-w-0 flex-1">
                  <p className="font-semibold">{item.workflowPath}</p>
                  <p className="text-200 text-muted-foreground">{item.status === "dispatched" ? `Dispatch ${item.deploymentId}` : item.error}</p>
                </div>
                {item.runUrl && (
                  <a className="inline-flex items-center gap-1 text-brand-foreground underline" href={item.runUrl} target="_blank" rel="noreferrer">
                    Open <ExternalLink className="icon-size-100" />
                  </a>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </PageFrame>
  );
}

function formatFailureReason(reason: unknown): string {
  if (!reason) return "";
  if (typeof reason === "string") return reason;
  if (typeof reason === "object") {
    const record = reason as Record<string, unknown>;
    if (typeof record.message === "string") {
      return typeof record.errorCode === "string"
        ? `${record.errorCode}: ${record.message}`
        : record.message;
    }
  }
  return String(reason);
}
