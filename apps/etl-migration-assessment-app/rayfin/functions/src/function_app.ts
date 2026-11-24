import {
  AudienceType,
  type RayfinContext,
  UserDataFunctions,
  UserThrownError,
} from "@microsoft/fabric-user-data-functions";
import { createHmac, randomUUID, timingSafeEqual } from "node:crypto";

type ExternalContext = RayfinContext<
  Record<string, unknown>,
  AudienceType.Fabric | AudienceType.Storage
>;

interface UploadResult {
  fileName: string;
  inputPath: string;
  size: number;
}

interface StartResult {
  jobInstanceId: string;
  statusUrl: string;
}

interface StatusResult {
  status: string;
  startTimeUtc?: string;
  endTimeUtc?: string;
  exitValue?: string;
  failureReason?: unknown;
}

type DeploymentProvider = "github" | "gitlab";
type ConflictBehavior = "Fail" | "Skip" | "Update";
type DeploymentTarget = "notebook" | "dataflow" | "pipeline" | "bundle";

interface DeploymentSelectionInput {
  workflowPath: string;
  sourcePlatform: string;
  nativeId: string;
  recommendedTarget: string;
  target?: DeploymentTarget;
}

interface DeploymentSelection {
  workflowPath: string;
  artifactPath: string;
  target: DeploymentTarget;
}

interface DeploymentManifest {
  version: 1;
  provider: DeploymentProvider;
  repository: string;
  ref: string;
  conflictBehavior: ConflictBehavior;
  selections: DeploymentSelection[];
  expiresAt: string;
}

interface DeploymentPreview {
  manifest: DeploymentManifest;
  confirmationToken: string;
}

interface DeploymentDispatchItem {
  workflowPath: string;
  artifactPath: string;
  target: DeploymentTarget;
  status: "dispatched" | "failed";
  deploymentId?: string;
  runUrl?: string;
  error?: string;
}

interface DeploymentDispatchResult {
  provider: DeploymentProvider;
  repository: string;
  ref: string;
  results: DeploymentDispatchItem[];
}

interface DeploymentConfiguration {
  githubConfigured: boolean;
  gitlabConfigured: boolean;
}

const udf = new UserDataFunctions();
const maxUploadBytes = 3 * 1024 * 1024;
const allowedFileName = /^[A-Za-z0-9][A-Za-z0-9._ -]{0,199}\.(yxmd|yxmc|yxwz|yxzp|xml|zip|json)$/i;
const allowedFolder = /^[a-z0-9][a-z0-9-]{0,63}$/;
const allowedJobId = /^[0-9a-f]{8}-[0-9a-f-]{27}$/i;

udf.func(
  "uploadWorkflow",
  async (
    fileName: string,
    contentBase64: string,
    inputFolder: string,
    ctx: ExternalContext,
  ): Promise<UploadResult> => {
    if (!allowedFileName.test(fileName) || fileName.includes("..")) {
      throw new UserThrownError("Use a supported workflow file name without path segments.");
    }
    if (!allowedFolder.test(inputFolder)) {
      throw new UserThrownError("The intake folder name is invalid.");
    }
    if (!/^[A-Za-z0-9+/]*={0,2}$/.test(contentBase64)) {
      throw new UserThrownError("The uploaded file content is not valid base64.");
    }

    const bytes = Buffer.from(contentBase64, "base64");
    if (bytes.length === 0 || bytes.length > maxUploadBytes) {
      throw new UserThrownError("Each workflow file must be between 1 byte and 3 MiB.");
    }

    const workspaceId = requiredSecret(ctx, "FABRIC_WORKSPACE_ID");
    const lakehouseId = requiredSecret(ctx, "FABRIC_LAKEHOUSE_ID");
    const storageToken = ctx.Tokens.Storage;
    const inputPath = `app-intake/${inputFolder}`;
    const filePath = `Files/${inputPath}/${fileName}`;
    const baseUrl = `https://onelake.dfs.fabric.microsoft.com/${workspaceId}/${lakehouseId}`;
    const headers = {
      Authorization: `Bearer ${storageToken}`,
      "x-ms-version": "2023-11-03",
    };

    await ensureDirectory(baseUrl, "Files/app-intake", headers);
    await ensureDirectory(baseUrl, `Files/${inputPath}`, headers);
    await uploadFile(baseUrl, filePath, bytes, headers);

    return { fileName, inputPath, size: bytes.length };
  },
  [],
);

udf.func(
  "getDeploymentConfiguration",
  async (ctx: ExternalContext): Promise<DeploymentConfiguration> => ({
    githubConfigured: Boolean(
      ctx.getSecret("GITHUB_TOKEN") &&
        ctx.getSecret("GITHUB_ALLOWED_REPOSITORIES"),
    ),
    gitlabConfigured: Boolean(
      ctx.getSecret("GITLAB_TOKEN") &&
        ctx.getSecret("GITLAB_ALLOWED_PROJECTS"),
    ),
  }),
  [],
);

udf.func(
  "previewDeployment",
  async (
    providerValue: string,
    repositoryUrl: string,
    refValue: string,
    conflictBehaviorValue: string,
    selectionsJson: string,
    ctx: ExternalContext,
  ): Promise<DeploymentPreview> => {
    const provider = parseProvider(providerValue);
    const conflictBehavior = parseConflictBehavior(conflictBehaviorValue);
    const selections = parseDeploymentSelections(selectionsJson);
    const repository =
      provider === "github"
        ? parseGitHubRepository(repositoryUrl)
        : parseGitLabProject(repositoryUrl).project;
    const ref =
      provider === "github"
        ? await validateGitHubTarget(ctx, repository, refValue)
        : await validateGitLabTarget(ctx, repositoryUrl, refValue);
    const manifest: DeploymentManifest = {
      version: 1,
      provider,
      repository,
      ref,
      conflictBehavior,
      selections,
      expiresAt: new Date(Date.now() + 10 * 60_000).toISOString(),
    };

    return {
      manifest,
      confirmationToken: signManifest(
        manifest,
        requiredSecret(ctx, "DEPLOYMENT_CONFIRMATION_KEY"),
      ),
    };
  },
  [],
);

udf.func(
  "dispatchDeployment",
  async (
    confirmationToken: string,
    ctx: ExternalContext,
  ): Promise<DeploymentDispatchResult> => {
    const manifest = verifyManifest(
      confirmationToken,
      requiredSecret(ctx, "DEPLOYMENT_CONFIRMATION_KEY"),
    );
    if (Date.parse(manifest.expiresAt) <= Date.now()) {
      throw new UserThrownError("The deployment preview expired. Preview the manifest again.");
    }

    const workspaceId = requiredSecret(ctx, "FABRIC_WORKSPACE_ID");
    const results: DeploymentDispatchItem[] = [];
    for (const selection of manifest.selections) {
      try {
        results.push(
          manifest.provider === "github"
            ? await dispatchGitHub(ctx, manifest, selection, workspaceId)
            : await dispatchGitLab(ctx, manifest, selection, workspaceId),
        );
      } catch (reason) {
        results.push({
          ...selection,
          status: "failed",
          error: reason instanceof Error ? reason.message : String(reason),
        });
      }
    }

    return {
      provider: manifest.provider,
      repository: manifest.repository,
      ref: manifest.ref,
      results,
    };
  },
  [],
);

udf.func(
  "startAssessment",
  async (inputPath: string, ctx: ExternalContext): Promise<StartResult> => {
    return startAssessmentNotebook(inputPath, false, ctx);
  },
  [],
);

udf.func(
  "startFabricFit",
  async (inputPath: string, ctx: ExternalContext): Promise<StartResult> => {
    return startAssessmentNotebook(inputPath, true, ctx);
  },
  [],
);

udf.func(
  "cancelAssessment",
  async (jobInstanceId: string, ctx: ExternalContext): Promise<{ status: string }> => {
    if (!allowedJobId.test(jobInstanceId)) {
      throw new UserThrownError("The notebook job instance ID is invalid.");
    }

    const workspaceId = requiredSecret(ctx, "FABRIC_WORKSPACE_ID");
    const notebookId = requiredSecret(ctx, "FABRIC_NOTEBOOK_ID");
    const response = await fetch(
      `https://api.fabric.microsoft.com/v1/workspaces/${workspaceId}/items/${notebookId}/jobs/instances/${jobInstanceId}/cancel`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${ctx.Tokens.Fabric}`,
          "Content-Type": "application/json",
          "x-ms-fabric-skill": "spark-cli",
        },
        body: "{}",
      },
    );
    if (!response.ok) {
      throw await responseError("Fabric could not cancel the notebook run", response);
    }
    return { status: "Cancelling" };
  },
  [],
);

udf.func(
  "getAssessmentStatus",
  async (jobInstanceId: string, ctx: ExternalContext): Promise<StatusResult> => {
    if (!allowedJobId.test(jobInstanceId)) {
      throw new UserThrownError("The notebook job instance ID is invalid.");
    }

    const workspaceId = requiredSecret(ctx, "FABRIC_WORKSPACE_ID");
    const notebookId = requiredSecret(ctx, "FABRIC_NOTEBOOK_ID");
    const response = await fetch(
      `https://api.fabric.microsoft.com/v1/workspaces/${workspaceId}/notebooks/${notebookId}/jobs/execute/instances/${jobInstanceId}?beta=true`,
      {
        headers: {
          Authorization: `Bearer ${ctx.Tokens.Fabric}`,
          "x-ms-fabric-skill": "spark-cli",
        },
      },
    );
    if (!response.ok) {
      throw await responseError("Fabric could not read the notebook run", response);
    }

    const result = (await response.json()) as StatusResult;
    return {
      status: result.status,
      startTimeUtc: result.startTimeUtc,
      endTimeUtc: result.endTimeUtc,
      exitValue: result.exitValue,
      failureReason: result.failureReason,
    };
  },
  [],
);

async function startAssessmentNotebook(
  inputPath: string,
  confirmFabricFit: boolean,
  ctx: ExternalContext,
): Promise<StartResult> {
  if (!/^app-intake\/[a-z0-9][a-z0-9-]{0,63}$/.test(inputPath)) {
    throw new UserThrownError("The assessment input path is invalid.");
  }

  const workspaceId = requiredSecret(ctx, "FABRIC_WORKSPACE_ID");
  const notebookId = requiredSecret(ctx, "FABRIC_NOTEBOOK_ID");
  const response = await fetch(
    `https://api.fabric.microsoft.com/v1/workspaces/${workspaceId}/notebooks/${notebookId}/jobs/execute/instances?beta=false`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${ctx.Tokens.Fabric}`,
        "Content-Type": "application/json",
        "x-ms-fabric-skill": "spark-cli",
      },
      body: JSON.stringify({
        parameters: [
          { name: "INPUT_PATH", value: inputPath, type: "Text" },
          { name: "CONFIRM_ASSESSMENT", value: true, type: "Boolean" },
          { name: "CONFIRM_FABRIC_FIT", value: confirmFabricFit, type: "Boolean" },
          { name: "PERSIST_DELTA_TABLES", value: true, type: "Boolean" },
          { name: "WRITE_REPORTS", value: false, type: "Boolean" },
        ],
      }),
    },
  );
  if (response.status !== 202) {
    throw await responseError("Fabric rejected the notebook run", response);
  }

  const statusUrl = response.headers.get("Location");
  if (!statusUrl) {
    throw new UserThrownError("Fabric accepted the run without returning a status URL.");
  }
  const jobInstanceId = new URL(statusUrl).pathname.split("/").filter(Boolean).at(-1);
  if (!jobInstanceId || !allowedJobId.test(jobInstanceId)) {
    throw new UserThrownError("Fabric returned an invalid notebook job instance ID.");
  }

  return { jobInstanceId, statusUrl };
}

function requiredSecret(ctx: ExternalContext, name: string): string {
  const value = ctx.getSecret(name);
  if (!value) {
    throw new UserThrownError(`The deployed app is missing the ${name} configuration.`);
  }
  return value;
}

async function ensureDirectory(
  baseUrl: string,
  directoryPath: string,
  headers: Record<string, string>,
): Promise<void> {
  const response = await fetch(`${baseUrl}/${encodePath(directoryPath)}?resource=directory`, {
    method: "PUT",
    headers,
  });
  if (!response.ok && response.status !== 409) {
    throw await responseError("OneLake could not create the intake directory", response);
  }
}

async function uploadFile(
  baseUrl: string,
  filePath: string,
  bytes: Buffer,
  headers: Record<string, string>,
): Promise<void> {
  const url = `${baseUrl}/${encodePath(filePath)}`;
  const uploadBody = new Uint8Array(bytes.length);
  uploadBody.set(bytes);
  const create = await fetch(`${url}?resource=file`, {
    method: "PUT",
    headers: { ...headers, "If-None-Match": "*" },
  });
  if (!create.ok) {
    throw await responseError("OneLake could not create the workflow file", create);
  }

  const append = await fetch(`${url}?action=append&position=0`, {
    method: "PATCH",
    headers: { ...headers, "Content-Type": "application/octet-stream" },
    body: uploadBody.buffer,
  });
  if (!append.ok) {
    throw await responseError("OneLake could not upload the workflow file", append);
  }

  const flush = await fetch(`${url}?action=flush&position=${bytes.length}`, {
    method: "PATCH",
    headers,
  });
  if (!flush.ok) {
    throw await responseError("OneLake could not finalize the workflow file", flush);
  }
}

function encodePath(value: string): string {
  return value.split("/").map(encodeURIComponent).join("/");
}

async function responseError(prefix: string, response: Response): Promise<Error> {
  const detail = (await response.text())
    .replace(/\bBearer\s+[A-Za-z0-9._~-]+/gi, "Bearer [redacted]")
    .slice(0, 300);
  return new UserThrownError(`${prefix} (${response.status}): ${detail || response.statusText}`);
}

function parseProvider(value: string): DeploymentProvider {
  if (value !== "github" && value !== "gitlab") {
    throw new UserThrownError("Choose GitHub Actions or GitLab CI.");
  }
  return value;
}

function parseConflictBehavior(value: string): ConflictBehavior {
  if (value !== "Fail" && value !== "Skip" && value !== "Update") {
    throw new UserThrownError("Choose a supported conflict behavior.");
  }
  return value;
}

function parseDeploymentSelections(value: string): DeploymentSelection[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new UserThrownError("The selected workflow manifest is not valid JSON.");
  }
  if (!Array.isArray(parsed) || parsed.length === 0 || parsed.length > 10) {
    throw new UserThrownError("Select between one and ten ready workflows.");
  }

  return parsed.map((item): DeploymentSelection => {
    if (!isDeploymentSelectionInput(item)) {
      throw new UserThrownError("A selected workflow has invalid deployment metadata.");
    }
    const target = resolveSelectionTarget(item.recommendedTarget, item.target);
    return {
      workflowPath: item.workflowPath,
      artifactPath: artifactPathFor(
        item.sourcePlatform,
        item.workflowPath,
        item.nativeId,
      ),
      target,
    };
  });
}

function isDeploymentSelectionInput(value: unknown): value is DeploymentSelectionInput {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  const validOptionalTarget =
    item.target === undefined ||
    item.target === "notebook" ||
    item.target === "dataflow" ||
    item.target === "pipeline" ||
    item.target === "bundle";
  return (
    typeof item.workflowPath === "string" &&
    typeof item.sourcePlatform === "string" &&
    typeof item.nativeId === "string" &&
    typeof item.recommendedTarget === "string" &&
    validOptionalTarget
  );
}

function resolveSelectionTarget(
  recommendedTarget: string,
  requestedTarget?: DeploymentTarget,
): DeploymentTarget {
  const allowedByRecommendation: Record<string, readonly DeploymentTarget[]> = {
    "Dataflow Gen2": ["dataflow"],
    "Fabric Notebook": ["notebook"],
    "Fabric Pipeline": ["pipeline"],
    "Mixed Fabric solution": ["bundle", "dataflow", "notebook", "pipeline"],
  };
  const allowed = allowedByRecommendation[recommendedTarget];
  if (!allowed) {
    throw new UserThrownError(`Workflow target ${recommendedTarget || "<empty>"} is not dispatchable.`);
  }
  if (requestedTarget === undefined) {
    return allowed[0];
  }
  if (!allowed.includes(requestedTarget)) {
    throw new UserThrownError(
      `Deployment target ${requestedTarget} is not allowed for ${recommendedTarget}.`,
    );
  }
  return requestedTarget;
}

export function artifactPathFor(
  sourcePlatform: string,
  workflowPath: string,
  nativeId: string,
): string {
  const roots: Record<string, string> = {
    alteryx: "",
    informatica_powercenter: "informatica-powercenter",
    informatica_idmc: "informatica-idmc",
  };
  const root = roots[sourcePlatform];
  if (root === undefined) {
    throw new UserThrownError(`Source platform ${sourcePlatform || "<empty>"} is not dispatchable.`);
  }
  const normalized = workflowPath.replaceAll("\\", "/");
  if (
    normalized.startsWith("/") ||
    normalized.includes("../") ||
    normalized.includes("/./") ||
    !/^[A-Za-z0-9][A-Za-z0-9._ !/-]{0,499}$/.test(normalized)
  ) {
    throw new UserThrownError("A selected workflow path is unsafe.");
  }
  const segments = normalized.split("/").filter(Boolean);
  if (segments.length === 0) {
    throw new UserThrownError("A selected workflow path is empty.");
  }
  const sourceValue =
    sourcePlatform === "alteryx"
      ? normalized
      : nativeId.trim() || normalized.split("!").at(-1) || "";
  const artifactSegments = sourceValue
    .split(/[\\/!]+/)
    .filter(Boolean)
    .map((segment, index, values) => {
      const value =
        index === values.length - 1
          ? segment.replace(/\.[^.]+$/, "")
          : segment;
      return value
        .replace(/[^A-Za-z0-9_-]+/g, "-")
        .replace(/^-+|-+$/g, "")
        .slice(0, 80) || "workflow";
    });
  if (artifactSegments.length === 0) {
    throw new UserThrownError("A selected workflow does not resolve to an artifact path.");
  }
  return [...(root ? [root] : []), ...artifactSegments].join("/");
}

function parseGitHubRepository(repositoryUrl: string): string {
  const url = new URL(repositoryUrl);
  const parts = url.pathname.replace(/\.git$/i, "").split("/").filter(Boolean);
  if (
    url.protocol !== "https:" ||
    url.hostname !== "github.com" ||
    parts.length !== 2 ||
    !parts.every((part) => /^[A-Za-z0-9_.-]+$/.test(part))
  ) {
    throw new UserThrownError("Use an HTTPS GitHub repository URL.");
  }
  return parts.join("/");
}

function parseGitLabProject(projectUrl: string): { origin: string; project: string } {
  const url = new URL(projectUrl);
  const parts = url.pathname
    .replace(/\/$/, "")
    .replace(/\.git$/i, "")
    .split("/")
    .filter(Boolean);
  if (
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    parts.length < 2 ||
    !parts.every((part) => part !== "-" && /^[A-Za-z0-9_.-]+$/.test(part))
  ) {
    throw new UserThrownError("Use an HTTPS GitLab project URL.");
  }
  return { origin: url.origin, project: parts.join("/") };
}

function validateRef(value: string): string {
  if (!/^[A-Za-z0-9][A-Za-z0-9._/-]{0,119}$/.test(value) || value.includes("..")) {
    throw new UserThrownError("The Git ref contains unsupported characters.");
  }
  return value;
}

async function validateGitHubTarget(
  ctx: ExternalContext,
  repository: string,
  requestedRef: string,
): Promise<string> {
  const allowed = parseAllowedList(requiredSecret(ctx, "GITHUB_ALLOWED_REPOSITORIES"));
  if (!allowed.has(repository.toLowerCase())) {
    throw new UserThrownError("The GitHub repository is not in the server allow-list.");
  }
  const token = requiredSecret(ctx, "GITHUB_TOKEN");
  const metadata = await githubRequest(ctx, repository, "", token);
  const defaultBranch = metadata.default_branch;
  if (typeof defaultBranch !== "string" || !defaultBranch) {
    throw new UserThrownError("GitHub did not return the repository default branch.");
  }
  const ref = validateRef(requestedRef || defaultBranch);
  await githubRequest(
    ctx,
    repository,
    `/actions/workflows/${encodeURIComponent("deploy-fabric-artifacts.yml")}`,
    token,
  );
  return ref;
}

async function validateGitLabTarget(
  ctx: ExternalContext,
  projectUrl: string,
  requestedRef: string,
): Promise<string> {
  const { origin, project } = parseGitLabProject(projectUrl);
  const configuredOrigin = ctx.getSecret("GITLAB_BASE_URL") || "https://gitlab.com";
  if (new URL(configuredOrigin).origin.toLowerCase() !== origin.toLowerCase()) {
    throw new UserThrownError("The GitLab project origin does not match the configured server.");
  }
  const allowed = parseAllowedList(requiredSecret(ctx, "GITLAB_ALLOWED_PROJECTS"));
  if (!allowed.has(project.toLowerCase())) {
    throw new UserThrownError("The GitLab project is not in the server allow-list.");
  }
  const token = requiredSecret(ctx, "GITLAB_TOKEN");
  const metadata = await gitlabRequest(origin, project, "", token);
  const defaultBranch = metadata.default_branch;
  const projectId = metadata.id;
  if (typeof defaultBranch !== "string" || !defaultBranch || !projectId) {
    throw new UserThrownError("GitLab did not return the project deployment metadata.");
  }
  const ref = validateRef(requestedRef || defaultBranch);
  const encodedFile = encodeURIComponent(".gitlab-ci.yml");
  await gitlabRequest(origin, String(projectId), `/repository/files/${encodedFile}?ref=${encodeURIComponent(ref)}`, token);
  return ref;
}

async function dispatchGitHub(
  ctx: ExternalContext,
  manifest: DeploymentManifest,
  selection: DeploymentSelection,
  workspaceId: string,
): Promise<DeploymentDispatchItem> {
  const token = requiredSecret(ctx, "GITHUB_TOKEN");
  const deploymentId = randomUUID().replaceAll("-", "");
  await githubRequest(
    ctx,
    manifest.repository,
    `/actions/workflows/${encodeURIComponent("deploy-fabric-artifacts.yml")}/dispatches`,
    token,
    {
      method: "POST",
      body: JSON.stringify({
        ref: manifest.ref,
        inputs: {
          deployment_id: deploymentId,
          FABRIC_WORKSPACE_ID: workspaceId,
          artifact_root: "generated-fabric-workflows",
          target: ciTarget(selection.target),
          workflow_filter: selection.artifactPath,
          conflict_behavior: manifest.conflictBehavior,
          dry_run: false,
        },
      }),
    },
  );
  return {
    ...selection,
    status: "dispatched",
    deploymentId,
    runUrl: `https://github.com/${manifest.repository}/actions/workflows/deploy-fabric-artifacts.yml`,
  };
}

async function dispatchGitLab(
  ctx: ExternalContext,
  manifest: DeploymentManifest,
  selection: DeploymentSelection,
  workspaceId: string,
): Promise<DeploymentDispatchItem> {
  const origin = ctx.getSecret("GITLAB_BASE_URL") || "https://gitlab.com";
  const token = requiredSecret(ctx, "GITLAB_TOKEN");
  const metadata = await gitlabRequest(origin, manifest.repository, "", token);
  const projectId = metadata.id;
  if (!projectId) {
    throw new Error("GitLab did not return the project ID.");
  }
  const deploymentId = randomUUID().replaceAll("-", "");
  const response = await gitlabRequest(
    origin,
    String(projectId),
    "/pipeline",
    token,
    {
      method: "POST",
      body: JSON.stringify({
        ref: manifest.ref,
        variables: [
          { key: "FABRIC_OPERATION", value: "Deploy" },
          { key: "DEPLOYMENT_ID", value: deploymentId },
          { key: "FABRIC_WORKSPACE_ID", value: workspaceId },
          { key: "ARTIFACT_ROOT", value: "generated-fabric-workflows" },
          { key: "TARGET", value: ciTarget(selection.target) },
          { key: "WORKFLOW_FILTER", value: selection.artifactPath },
          { key: "CONFLICT_BEHAVIOR", value: manifest.conflictBehavior },
          { key: "DRY_RUN", value: "false" },
        ],
      }),
    },
  );
  const pipelineId = response.id;
  const pipelineUrl = response.web_url;
  if ((!pipelineId && pipelineId !== 0) || typeof pipelineUrl !== "string") {
    throw new Error("GitLab did not return pipeline details.");
  }
  return {
    ...selection,
    status: "dispatched",
    deploymentId: String(pipelineId),
    runUrl: pipelineUrl,
  };
}

async function githubRequest(
  _ctx: ExternalContext,
  repository: string,
  path: string,
  token: string,
  init: RequestInit = {},
): Promise<Record<string, unknown>> {
  const response = await fetch(`https://api.github.com/repos/${repository}${path}`, {
    ...init,
    signal: AbortSignal.timeout(20_000),
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      "User-Agent": "fabric-etl-migration-accelerator",
      "X-GitHub-Api-Version": "2022-11-28",
    },
  });
  if (!response.ok) {
    throw await responseError("GitHub rejected the deployment request", response);
  }
  if (response.status === 204) return {};
  return (await response.json()) as Record<string, unknown>;
}

async function gitlabRequest(
  origin: string,
  project: string,
  path: string,
  token: string,
  init: RequestInit = {},
): Promise<Record<string, unknown>> {
  const response = await fetch(
    `${new URL(origin).origin}/api/v4/projects/${encodeURIComponent(project)}${path}`,
    {
      ...init,
      signal: AbortSignal.timeout(20_000),
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "PRIVATE-TOKEN": token,
        "User-Agent": "fabric-etl-migration-accelerator",
      },
    },
  );
  if (!response.ok) {
    throw await responseError("GitLab rejected the deployment request", response);
  }
  return (await response.json()) as Record<string, unknown>;
}

function parseAllowedList(value: string): Set<string> {
  const entries = value
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
  if (entries.length === 0) {
    throw new Error("The deployment provider allow-list is empty.");
  }
  return new Set(entries);
}

function ciTarget(target: DeploymentTarget): string {
  if (target === "pipeline") return "DataPipeline";
  return target.charAt(0).toUpperCase() + target.slice(1);
}

function signManifest(manifest: DeploymentManifest, key: string): string {
  const payload = Buffer.from(JSON.stringify(manifest), "utf8").toString("base64url");
  const signature = createHmac("sha256", key).update(payload).digest("base64url");
  return `${payload}.${signature}`;
}

function verifyManifest(token: string, key: string): DeploymentManifest {
  const [payload, signature, extra] = token.split(".");
  if (!payload || !signature || extra) {
    throw new UserThrownError("The deployment confirmation token is malformed.");
  }
  const expected = createHmac("sha256", key).update(payload).digest();
  const received = Buffer.from(signature, "base64url");
  if (expected.length !== received.length || !timingSafeEqual(expected, received)) {
    throw new UserThrownError("The deployment confirmation token is invalid.");
  }
  const parsed = JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as DeploymentManifest;
  if (
    parsed.version !== 1 ||
    (parsed.provider !== "github" && parsed.provider !== "gitlab") ||
    !Array.isArray(parsed.selections)
  ) {
    throw new UserThrownError("The deployment confirmation manifest is invalid.");
  }
  return parsed;
}
