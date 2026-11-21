import { readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const sourceDir = path.join(root, "powerbi", "ETL Migration Assessment.Report");
const guidPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const options = parseOptions(process.argv.slice(2));
assertGuid("semantic model ID", options.semanticModelId);
if (!options.out) {
  throw new Error("Provide --out <path> for the generated deployment payload.");
}

const parts = [];
for (const filePath of await listFiles(sourceDir)) {
  const relativePath = path.relative(sourceDir, filePath).replaceAll("\\", "/");
  if (relativePath === ".pbi" || relativePath.startsWith(".pbi/")) {
    continue;
  }

  let payloadBuffer;
  if (relativePath === "definition.pbir") {
    const pbir = JSON.parse(await readFile(filePath, "utf8"));
    pbir.datasetReference = {
      byConnection: {
        connectionString: `semanticmodelid=${options.semanticModelId}`,
      },
    };
    payloadBuffer = Buffer.from(`${JSON.stringify(pbir, null, 2)}\n`, "utf8");
  } else {
    payloadBuffer = await readFile(filePath);
  }

  parts.push({
    path: relativePath,
    payload: payloadBuffer.toString("base64"),
    payloadType: "InlineBase64",
  });
}

const payload = {
  displayName: options.displayName || "ETL Migration Assessment",
  description:
    "Direct Lake analytical report for governed ETL migration assessment portfolios.",
  definition: {
    format: "PBIR",
    parts,
  },
};

await writeFile(path.resolve(options.out), `${JSON.stringify(payload, null, 2)}\n`, {
  encoding: "utf8",
  flag: options.force ? "w" : "wx",
});
console.log(`Created Power BI report payload with ${parts.length} parts.`);

function parseOptions(args) {
  const result = { force: false };
  for (let index = 0; index < args.length; index += 1) {
    const name = args[index];
    if (name === "--force") {
      result.force = true;
      continue;
    }
    const value = args[index + 1];
    if (!name?.startsWith("--") || value === undefined) {
      throw new Error(`Invalid argument sequence near ${name ?? "<end>"}`);
    }
    index += 1;
    if (name === "--semantic-model-id") {
      result.semanticModelId = value;
    } else if (name === "--display-name") {
      result.displayName = value;
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
