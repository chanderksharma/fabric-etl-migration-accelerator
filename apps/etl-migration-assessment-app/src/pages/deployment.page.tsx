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
type DeploymentTarget = "notebook" | "dataflow" | "pipeline" | "bundle";
type DeploymentPreview = AppFunctionsSchema["previewDeployment"]["output"];
type DeploymentResult = AppFunctionsSchema["dispatchDeployment"]["output"];
type DeploymentConfiguration = AppFunctionsSchema["getDeploymentConfiguration"]["output"];

interface WorkflowOption {
  workflowKey: string;
  workflowPath: string;
  sourcePlatform: string;
  nativeId: string;
  recommendedTarget: string;
  targetComponents: string[];
  migrationWave: string;
  complexityScore: number;
}

interface DeployPrefs {
  provider?: DeploymentProvider;
  githubRepositoryUrl?: string;
  gitlabProjectUrl?: string;
  gitRef?: string;
  conflictBehavior?: ConflictBehavior;
}

const DEPLOY_PREFS_KEY = "etl-fabric-deploy-prefs";

function readDeployPrefs(): DeployPrefs {
  try {
    const raw = sessionStorage.getItem(DEPLOY_PREFS_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    return typeof parsed === "object" && parsed !== null ? (parsed as DeployPrefs) : {};
  } catch {
    return {};
  }
}

function writeDeployPrefs(prefs: DeployPrefs): void {
  try {
    sessionStorage.setItem(DEPLOY_PREFS_KEY, JSON.stringify(prefs));
  } catch {
    // ignore storage errors
  }
}

function allowedTargetsFor(workflow: WorkflowOption): DeploymentTarget[] {
  const fromComponents: ("dataflow" | "notebook" | "pipeline")[] = [];
  for (const component of workflow.targetComponents) {
    if (component === "Dataflow Gen2" && !fromComponents.includes("dataflow")) fromComponents.push("dataflow");
    if (component === "Fabric Notebook" && !fromComponents.includes("notebook")) fromComponents.push("notebook");
    if (component === "Fabric Pipeline" && !fromComponents.includes("pipeline")) fromComponents.push("pipeline");
  }
  if (workflow.recommendedTarget === "Mixed Fabric solution") {
    const components: ("dataflow" | "notebook" | "pipeline")[] =
      fromComponents.length > 0 ? fromComponents : ["dataflow", "notebook", "pipeline"];
    return ["bundle", ...components];
  }
  if (workflow.recommendedTarget === "Dataflow Gen2") return ["dataflow"];
  if (workflow.recommendedTarget === "Fabric Notebook") return ["notebook"];
  if (workflow.recommendedTarget === "Fabric Pipeline") return ["pipeline"];
  return [];
}

function targetDisplayLabel(target: DeploymentTarget, components: string[]): string {
  if (target === "bundle") {
    const names = components.length > 0
      ? components.map((value) =>
          value === "Fabric Notebook"
            ? "Notebook"
            : value === "Fabric Pipeline"
              ? "Pipeline"
              : value,
        )
      : ["Dataflow Gen2", "Notebook", "Pipeline"];
    return names.join(" + ");
  }
  if (target === "dataflow") return "Dataflow Gen2";
  if (target === "pipeline") return "Fabric Data Pipeline";
  return "Notebook";
}

function isValidGitHubRepositoryUrl(value: string): boolean {
  try {
    const url = new URL(value);
    const parts = url.pathname.replace(/\.git$/i, "").split("/").filter(Boolean);
    return (
      url.protocol === "https:" &&
      url.hostname.toLowerCase() === "github.com" &&
      parts.length === 2 &&
      parts.every((part) => /^[A-Za-z0-9_.-]+$/.test(part))
    );
  } catch {
    return false;
  }
}

function isValidGitLabProjectUrl(value: string): boolean {
  try {
    const url = new URL(value);
    const parts = url.pathname.replace(/\/$/, "").replace(/\.git$/i, "").split("/").filter(Boolean);
    return (
      url.protocol === "https:" &&
      !url.username &&
      !url.password &&
      !url.search &&
      !url.hash &&
      parts.length >= 2 &&
      parts.every((part) => part !== "-" && /^[A-Za-z0-9_.-]+$/.test(part))
    );
  } catch {
    return false;
  }
}

function isValidGitRef(value: string): boolean {
  return !value || (/^[A-Za-z0-9][A-Za-z0-9._/-]{0,119}$/.test(value) && !value.includes(".."));
}

export function DeploymentPage({
  preselectedWorkflowPath,
}: {
  preselectedWorkflowPath?: string;
}) {
  const initialPrefs = useMemo(() => readDeployPrefs(), []);
  const { activeRunId, runs, refreshRuns } = useAssessmentRunContext();
  const selectedRun = activeRunId
    ? runs.find((run) => run.runId === activeRunId)
    : runs[0];
  const { data, isLoading, error: queryError } = useSemanticModelQuery(workflows.register);
  const { data: profileData } = useSemanticModelQuery(workflows.capacityProfiles);
  const [provider, setProvider] = useState<DeploymentProvider>(
    initialPrefs.provider === "gitlab" ? "gitlab" : "github",
  );
  const [githubRepositoryUrl, setGithubRepositoryUrl] = useState(
    initialPrefs.githubRepositoryUrl ?? "",
  );
  const [gitlabProjectUrl, setGitlabProjectUrl] = useState(
    initialPrefs.gitlabProjectUrl ?? "",
  );
  const [gitRef, setGitRef] = useState(initialPrefs.gitRef ?? "");
  const [conflictBehavior, setConflictBehavior] = useState<ConflictBehavior>(
    initialPrefs.conflictBehavior ?? "Update",
  );
  const [selected, setSelected] = useState<Set<string>>(() =>
    preselectedWorkflowPath ? new Set([preselectedWorkflowPath]) : new Set(),
  );
  const [targetOverrides, setTargetOverrides] = useState<Record<string, DeploymentTarget>>({});
  const repositoryUrl = provider === "github" ? githubRepositoryUrl : gitlabProjectUrl;

  useEffect(() => {
    writeDeployPrefs({
      provider,
      githubRepositoryUrl,
      gitlabProjectUrl,
      gitRef,
      conflictBehavior,
    });
  }, [conflictBehavior, gitRef, githubRepositoryUrl, gitlabProjectUrl, provider]);
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

  const componentsByKey = useMemo(() => {
    const map = new Map<string, string[]>();
    if (profileData?.status !== "success") return map;
    const table = toDataTable(profileData.table, workflows.capacityProfiles.columnMetadata);
    const indexes = Object.fromEntries(table.columns.map((column, index) => [column.name, index]));
    if (indexes.WorkflowKey === undefined || indexes.TargetComponents === undefined) return map;
    for (const row of table.rows) {
      const key = String(row[indexes.WorkflowKey] ?? "");
      const raw = String(row[indexes.TargetComponents] ?? "");
      if (!key || !raw) continue;
      map.set(
        key,
        raw
          .split(",")
          .map((part) => part.trim())
          .filter(Boolean),
      );
    }
    return map;
  }, [profileData]);

  const allWorkflows = useMemo(() => {
    if (data?.status !== "success") return [];
    const table = toDataTable(data.table, workflows.register.columnMetadata);
    const indexes = Object.fromEntries(table.columns.map((column, index) => [column.name, index]));
    return table.rows
      .map((row): WorkflowOption => {
        const workflowKey = String(row[indexes.WorkflowKey] ?? "");
        return {
          workflowKey,
          workflowPath: String(row[indexes.WorkflowPath] ?? ""),
          sourcePlatform: String(row[indexes.SourcePlatform] ?? ""),
          nativeId: String(row[indexes.NativeId] ?? ""),
          recommendedTarget: String(row[indexes.RecommendedTarget] ?? ""),
          targetComponents: componentsByKey.get(workflowKey) ?? [],
          migrationWave: String(row[indexes.MigrationWave] ?? ""),
          complexityScore: Number(row[indexes.ComplexityScore] ?? 0),
        };
      })
      .filter((workflow) => workflow.workflowPath);
  }, [componentsByKey, data]);
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
  const providerName = provider === "github" ? "GitHub Actions" : "GitLab CI";
  const fitConfirmed = Boolean(
    selectedRun && selectedRun.routingBasis !== "static_mapping",
  );
  const previewRequirements = [
    {
      ready: fitConfirmed,
      label: "Compiler-confirmed Fabric fit",
      action: "Use Confirm Fabric fit above.",
    },
    {
      ready: providerConfigured === true,
      label: `${providerName} server-side secrets`,
      action: provider === "github"
        ? "Configure GITHUB_TOKEN and GITHUB_ALLOWED_REPOSITORIES."
        : "Configure GITLAB_TOKEN and GITLAB_ALLOWED_PROJECTS.",
    },
    {
      ready: validSelected.size > 0,
      label: "At least one ready workflow selected",
      action: "Select a workflow in Ready workflows.",
    },
    {
      ready: Boolean(repositoryUrl.trim()),
      label: "Repository or project URL entered",
      action: "Enter the approved repository URL under CI/CD target.",
    },
  ];
  const previewReady = previewRequirements.every((requirement) => requirement.ready);

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
    if (provider === "github" && !isValidGitHubRepositoryUrl(repositoryUrl.trim())) {
      setFeedback("Use an HTTPS GitHub repository URL such as https://github.com/owner/repository.");
      return;
    }
    if (provider === "gitlab" && !isValidGitLabProjectUrl(repositoryUrl.trim())) {
      setFeedback("Use an HTTPS GitLab project URL such as https://gitlab.com/group/project.");
      return;
    }
    if (!isValidGitRef(gitRef.trim())) {
      setFeedback("Git ref contains unsupported characters.");
      return;
    }
    setIsPreviewing(true);
    try {
      const selections = workflowOptions
        .filter((workflow) => validSelected.has(workflow.workflowPath))
        .map((workflow) => {
          const allowed = allowedTargetsFor(workflow);
          const requested = targetOverrides[workflow.workflowPath];
          const target = requested && allowed.includes(requested) ? requested : allowed[0];
          return {
            workflowPath: workflow.workflowPath,
            sourcePlatform: workflow.sourcePlatform,
            nativeId: workflow.nativeId,
            recommendedTarget: workflow.recommendedTarget,
            ...(target ? { target } : {}),
          };
        });
      const nextPreview = await getRayfinClient().functions.previewDeployment.invoke(
        {
          providerValue: provider,
          repositoryUrl: repositoryUrl.trim(),
          refValue: gitRef.trim(),
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
              if (provider === "github") setGithubRepositoryUrl(event.target.value);
              else setGitlabProjectUrl(event.target.value);
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
              {workflowOptions.map((workflow) => {
                const isSelected = validSelected.has(workflow.workflowPath);
                const allowedTargets = allowedTargetsFor(workflow);
                const selectedTarget =
                  targetOverrides[workflow.workflowPath] &&
                  allowedTargets.includes(targetOverrides[workflow.workflowPath])
                    ? targetOverrides[workflow.workflowPath]
                    : allowedTargets[0];
                return (
                  <div key={workflow.workflowPath} className="rounded-lg border p-3 hover:bg-hover">
                    <label className="flex cursor-pointer items-start gap-3">
                      <input
                        className="mt-1"
                        type="checkbox"
                        checked={isSelected}
                        disabled={!isSelected && validSelected.size >= 10}
                        onChange={() => toggleWorkflow(workflow.workflowPath)}
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-semibold">{workflow.workflowPath}</span>
                        <span className="mt-1 block text-200 text-muted-foreground">
                          {workflow.recommendedTarget} · {workflow.migrationWave} · complexity {workflow.complexityScore}
                        </span>
                      </span>
                    </label>
                    {isSelected && allowedTargets.length > 0 && (
                      <div className="mt-2 flex flex-wrap items-center gap-2 pl-7 text-200">
                        <span className="text-muted-foreground">Deployment target:</span>
                        {allowedTargets.length === 1 ? (
                          <span className="rounded-full bg-muted px-2.5 py-0.5 font-semibold">
                            {targetDisplayLabel(allowedTargets[0], workflow.targetComponents)}
                          </span>
                        ) : (
                          <select
                            aria-label={`Deployment target for ${workflow.workflowPath}`}
                            className="rounded border bg-background px-2 py-1 text-200 font-semibold"
                            value={selectedTarget}
                            onChange={(event) => {
                              setTargetOverrides((current) => ({
                                ...current,
                                [workflow.workflowPath]: event.target.value as DeploymentTarget,
                              }));
                              clearApproval();
                            }}
                          >
                            {allowedTargets.map((option) => (
                              <option key={option} value={option}>
                                {targetDisplayLabel(option, workflow.targetComponents)}
                              </option>
                            ))}
                          </select>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
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
            disabled={!previewReady || isPreviewing}
            onClick={() => void previewManifest()}
          >
            {isPreviewing ? <LoaderCircle className="icon-size-200 animate-spin" /> : <ShieldCheck className="icon-size-200" />}
            Preview manifest
          </button>
        </div>

        <div className="mt-5 grid gap-2 md:grid-cols-2" aria-label="Manifest prerequisites">
          {previewRequirements.map((requirement) => (
            <div
              className={`flex items-start gap-2 rounded-lg border p-3 text-200 ${
                requirement.ready ? "text-success" : "text-muted-foreground"
              }`}
              key={requirement.label}
            >
              {requirement.ready
                ? <CheckCircle2 className="icon-size-200 shrink-0" />
                : <XCircle className="icon-size-200 shrink-0" />}
              <span>
                <strong>{requirement.label}</strong>
                {!requirement.ready && <span className="block">{requirement.action}</span>}
              </span>
            </div>
          ))}
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
          </div>
        )}

        <div className="mt-5 flex flex-wrap items-center gap-3 rounded-lg border p-4">
          <button
            className="inline-flex items-center gap-2 rounded-lg bg-brand px-4 py-3 text-300 font-semibold text-on-brand focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
            type="button"
            disabled={!preview || !confirmed || isDispatching}
            onClick={() => void dispatch()}
          >
            {isDispatching
              ? <LoaderCircle className="icon-size-200 animate-spin" />
              : <Rocket className="icon-size-200" />}
            Trigger {providerName}
          </button>
          <p className="text-200 text-muted-foreground">
            {!preview
              ? "Available after all prerequisites pass and Preview manifest succeeds."
              : !confirmed
                ? "Review the manifest and select the confirmation checkbox."
                : `Ready to trigger ${providerName}.`}
          </p>
        </div>

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
