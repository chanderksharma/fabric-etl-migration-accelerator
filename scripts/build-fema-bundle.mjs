import { spawnSync } from "node:child_process";
import { cp, mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const defaultOut = path.join(root, "dist", "fema-deployment-bundle");
const options = parseOptions(process.argv.slice(2));
const outDir = path.resolve(options.out || defaultOut);

if (options.buildWheels) {
  const build = spawnSync("uv", ["build", "--all-packages", "--wheel"], {
    cwd: root,
    stdio: "inherit",
  });
  if (build.error) {
    throw build.error;
  }
  if (build.status !== 0) {
    throw new Error("uv build --all-packages --wheel failed.");
  }
}

const resolvedOut = path.resolve(outDir);
if (!resolvedOut.startsWith(root + path.sep)) {
  throw new Error(`Output directory must remain inside repository root: ${resolvedOut}`);
}

await rm(resolvedOut, { recursive: true, force: true });
await mkdir(resolvedOut, { recursive: true });

const copies = [
  ["scripts/deployment_order.json", "scripts/deployment_order.json"],
  ["scripts/Deploy-AcceleratorWorkspace.ps1", "scripts/Deploy-AcceleratorWorkspace.ps1"],
  ["scripts/FabricApi.psm1", "scripts/FabricApi.psm1"],
  ["scripts/fabric-environment.yml", "scripts/fabric-environment.yml"],
  ["scripts/build-notebook-payload.mjs", "scripts/build-notebook-payload.mjs"],
  ["scripts/build-powerbi-semantic-model-payload.mjs", "scripts/build-powerbi-semantic-model-payload.mjs"],
  ["scripts/build-powerbi-report-payload.mjs", "scripts/build-powerbi-report-payload.mjs"],
  ["notebooks/Deploy_FEMA.ipynb", "notebooks/Deploy_FEMA.ipynb"],
  ["notebooks/fabric-portfolio-assessment.ipynb", "notebooks/fabric-portfolio-assessment.ipynb"],
  [
    "powerbi/ETL Migration Assessment Model.SemanticModel",
    "powerbi/ETL Migration Assessment Model.SemanticModel",
  ],
  ["powerbi/ETL Migration Assessment.Report", "powerbi/ETL Migration Assessment.Report"],
];

for (const [srcRel, destRel] of copies) {
  const srcPath = path.join(root, srcRel);
  const destPath = path.join(resolvedOut, destRel);
  await mkdir(path.dirname(destPath), { recursive: true });
  await cp(srcPath, destPath, {
    recursive: true,
    filter: (entryPath) => {
      const normalized = entryPath.replaceAll("\\", "/");
      return !normalized.endsWith("/.pbi") && !normalized.includes("/.pbi/");
    },
  });
}

// Copy built workspace wheel(s) if available
const distDir = path.join(root, "dist");
let wheelCount = 0;
try {
  const distEntries = await readdir(distDir, { withFileTypes: true });
  const wheelPattern =
    /^(etl_migration_core|etl_portfolio_assessment|etl_target_fabric)-.*\.whl$/i;
  const wheels = distEntries
    .filter((entry) => entry.isFile() && wheelPattern.test(entry.name))
    .map((entry) => entry.name)
    .sort();
  if (wheels.length > 0) {
    const wheelsOut = path.join(resolvedOut, "dist");
    await mkdir(wheelsOut, { recursive: true });
    for (const wheel of wheels) {
      await cp(path.join(distDir, wheel), path.join(wheelsOut, wheel));
      wheelCount += 1;
    }
  }
} catch {
  // dist/ may not exist yet before `uv build --all-packages`
}

if (options.requireWheel && wheelCount === 0) {
  throw new Error(
    "No accelerator/library wheels found in dist/. Run 'uv build --all-packages' first.",
  );
}

// Verify zero leftover local/secret files or unresolved tenant GUID leaks in bundle metadata
const forbiddenFiles = await findForbiddenEntries(resolvedOut);
if (forbiddenFiles.length > 0) {
  throw new Error(`Bundle contains unexpected local files: ${forbiddenFiles.join(", ")}`);
}

const manifest = {
  bundleFormat: "fema-workspace-accelerator-v1",
  filesIncluded: (await listAllFiles(resolvedOut)).map((file) =>
    path.relative(resolvedOut, file).replaceAll("\\", "/"),
  ),
  wheelCount,
};
await writeFile(
  path.join(resolvedOut, "bundle-manifest.json"),
  `${JSON.stringify(manifest, null, 2)}\n`,
  "utf8",
);

console.log(
  `Created FEMA deployment bundle at ${resolvedOut} (${manifest.filesIncluded.length} files, ${wheelCount} wheel(s)).`,
);

function parseOptions(args) {
  const result = { requireWheel: false, buildWheels: false };
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === "--require-wheel") {
      result.requireWheel = true;
      continue;
    }
    if (arg === "--build-wheels") {
      result.buildWheels = true;
      continue;
    }
    const value = args[index + 1];
    if (!arg?.startsWith("--") || value === undefined) {
      throw new Error(`Invalid argument sequence near ${arg ?? "<end>"}`);
    }
    index += 1;
    if (arg === "--out") {
      result.out = value;
    } else {
      throw new Error(`Unsupported option: ${arg}`);
    }
  }
  return result;
}

async function listAllFiles(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await listAllFiles(full)));
    } else if (entry.isFile()) {
      files.push(full);
    }
  }
  return files;
}

async function findForbiddenEntries(dir) {
  const forbidden = [];
  for (const file of await listAllFiles(dir)) {
    const rel = path.relative(dir, file).replaceAll("\\", "/");
    const base = path.basename(file);
    if (
      rel.includes(".pbi/") ||
      base.startsWith(".env") ||
      base === ".deployments.json" ||
      base.endsWith(".pem") ||
      base.endsWith(".key")
    ) {
      forbidden.push(rel);
    }
    if (rel === "powerbi/ETL Migration Assessment Model.SemanticModel/definition/model.tmdl") {
      const content = await readFile(file, "utf8");
      if (!content.includes("__FABRIC_WORKSPACE_ID__") || !content.includes("__FABRIC_LAKEHOUSE_ID__")) {
        forbidden.push(`${rel} (missing template tokens)`);
      }
    }
  }
  return forbidden;
}
