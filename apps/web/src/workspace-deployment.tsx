import { useEffect, useMemo, useState } from "react";
import type { AssessmentResult, Candidate } from "./App";
import { githubRepository, gitlabProject, nameOf } from "./workspace-model";

type Item = AssessmentResult["assessments"][number];
type Target = "notebook" | "dataflow" | "pipeline";
type DeploymentTarget = Target | "bundle";
type DeploymentProvider = "github" | "gitlab";

type DeployPrefs = {
  provider?: DeploymentProvider;
  repositoryUrl?: string;
  workflowFile?: string;
  gitlabProjectUrl?: string;
  gitRef?: string;
  conflictBehavior?: string;
};

type DeploymentProps = {
  item: Item;
  candidates: Candidate[];
  runId: string | null;
  request: (path: string, init?: RequestInit) => Promise<Response>;
};

const DEPLOY_PREFS_KEY = "accelerator-deploy-prefs";

function readDeployPrefs(): DeployPrefs {
  try {
    const raw = localStorage.getItem(DEPLOY_PREFS_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    return typeof parsed === "object" && parsed !== null ? (parsed as DeployPrefs) : {};
  } catch {
    return {};
  }
}

function writeDeployPrefs(prefs: DeployPrefs) {
  try {
    localStorage.setItem(DEPLOY_PREFS_KEY, JSON.stringify(prefs));
  } catch {
    // ignore storage errors
  }
}

export function Deployment({item, candidates, runId, request}: DeploymentProps) {
  const initialPrefs = useMemo(() => readDeployPrefs(), []);
  const [target, setTarget] = useState<DeploymentTarget>(
    item.recommended_target === "Mixed Fabric solution"
      ? "bundle"
      : item.recommended_target === "Fabric Pipeline"
        ? "pipeline"
      : item.recommended_target === "Dataflow Gen2"
        ? "dataflow"
        : "notebook"
  );
  const [provider, setProvider] = useState<DeploymentProvider>(initialPrefs.provider === "gitlab" ? "gitlab" : "github");
  const [repositoryUrl, setRepositoryUrl] = useState(initialPrefs.repositoryUrl ?? "");
  const [workflowFile, setWorkflowFile] = useState(initialPrefs.workflowFile ?? ".github/workflows/deploy-fabric-artifacts.yml");
  const [gitlabProjectUrl, setGitlabProjectUrl] = useState(initialPrefs.gitlabProjectUrl ?? "");
  const [gitRef, setGitRef] = useState(initialPrefs.gitRef ?? "");
  const [conflictBehavior, setConflictBehavior] = useState(initialPrefs.conflictBehavior ?? "Update");
  const [feedback, setFeedback] = useState("");
  const [runUrl, setRunUrl] = useState<string | null>(null);
  const [deploying, setDeploying] = useState(false);

  useEffect(() => {
    writeDeployPrefs({
      provider,
      repositoryUrl,
      workflowFile,
      gitlabProjectUrl,
      gitRef,
      conflictBehavior,
    });
  }, [provider, repositoryUrl, workflowFile, gitlabProjectUrl, gitRef, conflictBehavior]);

  const isManualOnly = item.recommended_target === "Manual rework";
  const candidate = target === "bundle"
    ? undefined
    : candidates.find(
        value => value.workflow === item.path && value.target === target
      );
  const bundleCandidates = candidates.filter(
    value => value.workflow === item.path
  );
  const bundleTargets = [
    ...(item.target_components?.includes("Dataflow Gen2") ? ["dataflow"] : []),
    ...(item.target_components?.includes("Fabric Notebook") ? ["notebook"] : []),
    ...(item.target_components?.includes("Fabric Pipeline") ? ["pipeline"] : []),
  ] as Target[];
  const requiredBundleCandidates = bundleTargets.includes("notebook")
    ? bundleTargets.filter(value => value !== "pipeline")
    : bundleTargets;
  const bundleReady = requiredBundleCandidates.every(bundleTarget =>
    bundleCandidates.some(value => value.target === bundleTarget && value.deployable)
  );
  const repository = githubRepository(repositoryUrl);
  const project = gitlabProject(gitlabProjectUrl);
  const providerName = provider === "github" ? "GitHub Actions" : "GitLab CI";

  function validateSetup() {
    if (isManualOnly) {
      setFeedback("Manual rework workflows have no deployable native definition.");
      return false;
    }
    if (provider === "github") {
      if (!repository) {
        setFeedback("Use an HTTPS GitHub repository URL such as https://github.com/owner/repository.");
        return false;
      }
      if (!/^\.github\/workflows\/[^/]+\.(yml|yaml)$/i.test(workflowFile)) {
        setFeedback("Workflow file must be a .yml or .yaml file directly under .github/workflows.");
        return false;
      }
    } else if (!project) {
      setFeedback("Use an HTTPS GitLab project URL such as https://gitlab.com/group/project.");
      return false;
    }
    if (gitRef && (!/^[A-Za-z0-9][A-Za-z0-9._/-]*$/.test(gitRef) || gitRef.includes(".."))) {
      setFeedback("Git ref contains unsupported characters.");
      return false;
    }
    setRunUrl(null);
    setFeedback(
      `${providerName} request is ready for ${provider === "github" ? repository : project}. `
      + "The backend will generate and validate the selected definition before dispatch."
    );
    return true;
  }

  async function deploy() {
    if (!runId || !validateSetup()) return;
    setDeploying(true);
    setRunUrl(null);
    try {
      const endpoint = provider === "github" ? "github" : "gitlab";
      const body = provider === "github"
        ? {
            repository_url: repositoryUrl,
            source_workflow: item.path,
            target,
            workflow_file: workflowFile,
            ref: gitRef || null,
            conflict_behavior: conflictBehavior,
          }
        : {
            project_url: gitlabProjectUrl,
            source_workflow: item.path,
            target,
            ci_file: ".gitlab-ci.yml",
            ref: gitRef || null,
            conflict_behavior: conflictBehavior,
          };
      const response = await request(`/api/runs/${runId}/deploy/${endpoint}`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body),
      });
      const result: {
        deployment_id: string;
        repository?: string;
        project?: string;
        target: DeploymentTarget;
        pipeline_url?: string;
        status: string;
      } = await response.json();
      if (provider === "github") {
        setRunUrl(result.repository ? `https://github.com/${result.repository}/actions` : null);
        setFeedback(
          `GitHub Actions ${result.target} deployment ${result.deployment_id} `
          + `triggered for ${result.repository}.`
        );
      } else {
        setRunUrl(result.pipeline_url ?? null);
        setFeedback(
          `GitLab CI ${result.target} pipeline ${result.deployment_id} `
          + `triggered for ${result.project}.`
        );
      }
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : `${providerName} dispatch failed`);
    } finally {
      setDeploying(false);
    }
  }

  return <section className="detail-section active">
    <div className="notice">GitHub Actions and GitLab CI are dispatch-only deployment methods. The app never accepts repository tokens, SPN secrets or Fabric tokens. Source bindings, independent parity and an approved team deployment profile are still required.</div>
    {isManualOnly && <div className="notice" role="status"><strong>Manual rework required.</strong> This workflow has no deployable native definition. Download the manual deployment package below to inspect diagnostics and redesign notes.</div>}
    <div className="summary-box">
      <h3>Deployment method</h3>
      <div className="deploy-field">
        <label htmlFor="deploymentProvider">Deployment method</label>
        <select id="deploymentProvider" value={provider} onChange={e => {
          setProvider(e.target.value as DeploymentProvider);
          setFeedback("");
          setRunUrl(null);
        }}>
          <option value="github">GitHub Actions</option>
          <option value="gitlab">GitLab CI</option>
        </select>
      </div>
    </div>
    <div className="summary-box">
      <h3>{providerName} target</h3>
      <div className="deploy-grid">
        {provider === "github"
          ? <div className="deploy-field full">
              <label htmlFor="repositoryUrl">GitHub repository URL</label>
              <input id="repositoryUrl" type="url" placeholder="https://github.com/owner/repository" value={repositoryUrl} onChange={e => setRepositoryUrl(e.target.value)} maxLength={240}/>
            </div>
          : <div className="deploy-field full">
              <label htmlFor="gitlabProjectUrl">GitLab project URL</label>
              <input id="gitlabProjectUrl" type="url" placeholder="https://gitlab.com/group/project" value={gitlabProjectUrl} onChange={e => setGitlabProjectUrl(e.target.value)} maxLength={500}/>
            </div>}
        <div className="deploy-field"><label htmlFor="itemName">Generated item name</label><input id="itemName" value={nameOf(item.path)} readOnly/></div>
        <div className="deploy-field"><label htmlFor="gitRef">Git ref</label><input id="gitRef" placeholder="Repository default branch" value={gitRef} onChange={e => setGitRef(e.target.value)} maxLength={120}/></div>
        {provider === "github"
          ? <div className="deploy-field full"><label htmlFor="workflowFile">Existing workflow file</label><input id="workflowFile" value={workflowFile} onChange={e => setWorkflowFile(e.target.value)} maxLength={180}/></div>
          : <div className="deploy-field full"><label htmlFor="gitlabCiFile">Existing CI file</label><input id="gitlabCiFile" value=".gitlab-ci.yml" readOnly/></div>}
        <div className="deploy-field"><label htmlFor="conflictBehavior">Existing item behavior</label><select id="conflictBehavior" value={conflictBehavior} onChange={e => setConflictBehavior(e.target.value)}><option value="Fail">Fail</option><option value="Skip">Skip</option><option value="Update">Update</option></select></div>
        <div className="deploy-field"><label htmlFor="workflowRequirement">CI requirement</label><input id="workflowRequirement" value={provider === "github" ? "Existing workflow required" : "Existing CI definition required"} readOnly/></div>
        <div className="deploy-field full"><label htmlFor="providerIdentity">{providerName} authentication</label><input id="providerIdentity" value={provider === "github" ? "Server-side GitHub App installation" : "Server-side GitLab project access token"} readOnly/></div>
      </div>
    </div>
    <div className="summary-box"><h3>Deployment bundle</h3><div className="deploy-field"><label htmlFor="bundleTarget">Deployment target</label><select id="bundleTarget" value={target} onChange={e => setTarget(e.target.value as DeploymentTarget)}>{item.recommended_target === "Mixed Fabric solution" && <option value="bundle">{bundleTargets.map(value => value === "dataflow" ? "Dataflow Gen2" : value === "notebook" ? "Notebook" : "Pipeline").join(" + ")}</option>}<option value="notebook">Notebook</option><option value="dataflow">Dataflow Gen2</option><option value="pipeline">Fabric Data Pipeline</option></select></div><div className="bundle-grid">{target === "bundle" ? <>{bundleTargets.map(value => <div className="bundle-card" key={value}><strong>{value === "dataflow" ? "Dataflow Gen2" : value === "notebook" ? "Fabric Notebook" : "Fabric Data Pipeline"}</strong><p>{value === "pipeline" ? "Binds and orchestrates the generated compute items." : "Generated compute item in the deployment bundle."}</p></div>)}</> : <div className="bundle-card"><strong>{target === "notebook" ? "Fabric Notebook" : target === "pipeline" ? "Fabric Data Pipeline" : "Dataflow Gen2"}</strong><p>Guarded, unbound and unvalidated.</p></div>}<div className="bundle-card"><strong>{providerName}</strong><p>Dev only; workspace and SPN resolve from the team profile.</p></div></div></div>
    <div className="summary-box"><h3>Manual deployment package</h3><p>Download this workflow's generated Dataflow, Notebook, Pipeline, manifests, diagnostics, and a README with manual installation steps.</p><div className="deploy-actions">{runId ? <a className="secondary-button" href={`/api/runs/${runId}/bundle?workflow=${encodeURIComponent(item.path)}`}>Download workflow bundle</a> : <button className="secondary-button" disabled>Download workflow bundle</button>}</div></div>
    <div className="summary-box"><h3>Deployment behavior</h3><p>The backend sends one dispatch request to the existing {providerName} definition. The provider accepts and runs the pipeline; this application does not create repository content, monitor runs, or read logs.</p><div className="deploy-actions"><button className="secondary-button" disabled={deploying || isManualOnly} onClick={validateSetup}>Validate deployment request</button><button className="primary-button" disabled={deploying || !runId || isManualOnly} onClick={deploy}>{deploying ? "Triggering..." : `Trigger ${providerName}`}</button></div><p className={target === "bundle" ? bundleReady ? "good" : "review" : candidate?.deployable ? "good" : candidate ? "bad" : "review"}>{target === "bundle" ? bundleReady ? `${bundleTargets.length}-item Fabric bundle ready. Validate bindings and parity before running it.` : "Bundle deployment generates and validates all required definitions before dispatch." : candidate?.deployable ? "Fabric definition package ready. Validate bindings and parity before running it." : candidate ? "The selected definition is blocked; triggering will return its diagnostics." : "The backend will generate and validate this definition before dispatch."}</p>{feedback && <p role="status">{feedback}</p>}{runUrl && <a className="deploy-link" href={runUrl} target="_blank" rel="noreferrer">{provider === "github" ? "Open GitHub Actions runs ↗" : "Open GitLab pipeline ↗"}</a>}</div>
  </section>;
}
