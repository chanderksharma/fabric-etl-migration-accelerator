import { readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const sourceDir = path.join(
  root,
  "powerbi",
  "ETL Migration Assessment Model.SemanticModel",
);
const workspaceToken = "__FABRIC_WORKSPACE_ID__";
const lakehouseToken = "__FABRIC_LAKEHOUSE_ID__";
const guidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const options = parseOptions(process.argv.slice(2));
assertGuid("workspace ID", options.workspaceId);
assertGuid("Lakehouse ID", options.lakehouseId);
if (!options.out) {
  throw new Error("Provide --out <path> for the generated deployment payload.");
}

const parts = [];
for (const filePath of await listFiles(sourceDir)) {
  const relativePath = path.relative(sourceDir, filePath).replaceAll("\\", "/");
  let content = await readFile(filePath, "utf8");
  content = content
    .replaceAll(workspaceToken, options.workspaceId)
    .replaceAll(lakehouseToken, options.lakehouseId);
  if (content.includes(workspaceToken) || content.includes(lakehouseToken)) {
    throw new Error(`Unresolved deployment token in ${relativePath}`);
  }
  parts.push({
    path: relativePath,
    payload: Buffer.from(content, "utf8").toString("base64"),
    payloadType: "InlineBase64",
  });
}

const payload = {
  displayName: "ETL Migration Assessment Model",
  description:
    "Direct Lake semantic model for governed ETL migration assessment analytics.",
  definition: {
    format: "TMDL",
    parts,
  },
};

await writeFile(path.resolve(options.out), `${JSON.stringify(payload, null, 2)}\n`, {
  encoding: "utf8",
  flag: "wx",
});
console.log(`Created semantic model payload with ${parts.length} parts.`);

function parseOptions(args) {
  const result = {};
  for (let index = 0; index < args.length; index += 2) {
    const name = args[index];
    const value = args[index + 1];
    if (!name?.startsWith("--") || value === undefined) {
      throw new Error(`Invalid argument sequence near ${name ?? "<end>"}`);
    }
    if (name === "--workspace-id") {
      result.workspaceId = value;
    } else if (name === "--lakehouse-id") {
      result.lakehouseId = value;
    } else if (name === "--out") {
      result.out = value;
    } else {
      throw new Error(`Unsupported option: ${name}`);
    }
  }
  return result;
}

function assertGuid(label, value) {
  if (!guidPattern.test(value ?? "")) {
    throw new Error(`Provide a valid ${label}.`);
  }
}

async function listFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await listFiles(entryPath)));
    } else if (entry.isFile()) {
      files.push(entryPath);
    }
  }
  return files;
}
