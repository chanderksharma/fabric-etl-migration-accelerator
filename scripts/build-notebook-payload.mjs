import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const defaultSource = path.join(
  root,
  "notebooks",
  "fabric-portfolio-assessment.ipynb",
);
const guidPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const options = parseOptions(process.argv.slice(2));
assertGuid("workspace ID", options.workspaceId);
assertGuid("Lakehouse ID", options.lakehouseId);
if (!options.lakehouseName) {
  throw new Error("Provide --lakehouse-name <name> for Lakehouse metadata binding.");
}
if (options.environmentId !== undefined) {
  assertGuid("environment ID", options.environmentId);
}
if (!options.out) {
  throw new Error("Provide --out <path> for the generated deployment payload.");
}

const notebookPath = options.source ? path.resolve(options.source) : defaultSource;
const notebook = JSON.parse(await readFile(notebookPath, "utf8"));
notebook.metadata = notebook.metadata && typeof notebook.metadata === "object" ? notebook.metadata : {};
const dependencies = {
  lakehouse: {
    default_lakehouse: options.lakehouseId,
    default_lakehouse_name: options.lakehouseName,
    default_lakehouse_workspace_id: options.workspaceId,
    known_lakehouses: [{ id: options.lakehouseId }],
  },
};
if (options.environmentId) {
  dependencies.environment = {
    environmentId: options.environmentId,
    workspaceId: options.workspaceId,
  };
}
notebook.metadata.dependencies = dependencies;

const displayName = options.displayName || "ETL Migration Assessment";
const platform = {
  $schema:
    "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
  metadata: {
    type: "Notebook",
    displayName,
    description:
      "Deterministic portfolio assessment and normalized Lakehouse persistence for Alteryx, PowerCenter, and IDMC estates.",
  },
  config: {
    version: "2.0",
    logicalId: "00000000-0000-0000-0000-000000000000",
  },
};

const payload = {
  displayName,
  description:
    "Deterministic portfolio assessment and normalized Lakehouse persistence for Alteryx, PowerCenter, and IDMC estates.",
  definition: {
    format: "ipynb",
    parts: [
      {
        path: "notebook-content.ipynb",
        payload: Buffer.from(`${JSON.stringify(notebook, null, 1)}\n`, "utf8").toString(
          "base64",
        ),
        payloadType: "InlineBase64",
      },
      {
        path: ".platform",
        payload: Buffer.from(`${JSON.stringify(platform, null, 2)}\n`, "utf8").toString(
          "base64",
        ),
        payloadType: "InlineBase64",
      },
    ],
  },
};

await writeFile(path.resolve(options.out), `${JSON.stringify(payload, null, 2)}\n`, {
  encoding: "utf8",
  flag: options.force ? "w" : "wx",
});
console.log(`Created notebook payload '${displayName}' with Lakehouse binding.`);

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
    if (name === "--workspace-id") {
      result.workspaceId = value;
    } else if (name === "--lakehouse-id") {
      result.lakehouseId = value;
    } else if (name === "--lakehouse-name") {
      result.lakehouseName = value;
    } else if (name === "--environment-id") {
      result.environmentId = value;
    } else if (name === "--display-name") {
      result.displayName = value;
    } else if (name === "--source") {
      result.source = value;
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
