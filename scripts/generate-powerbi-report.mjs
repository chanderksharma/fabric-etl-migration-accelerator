import { createHash } from "node:crypto";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const reportDir = path.join(root, "powerbi", "ETL Migration Assessment.Report");
const definitionDir = path.join(reportDir, "definition");
const pagesDir = path.join(definitionDir, "pages");
const visualSchema =
  "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.9.0/schema.json";
const pageSchema =
  "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json";

const pageDefinitions = [
  {
    key: "portfolio",
    name: "Portfolio Migration Summary",
    latestOnly: true,
    visuals: [
      title("portfolio-title", "Portfolio Migration Summary", "Estate readiness and recommended Fabric targets"),
      slicer("portfolio-run", 24, 72, 280, "AssessmentRun", "RunLabel", "Assessment run"),
      slicer("portfolio-source", 320, 72, 240, "WorkflowAssessment", "SourcePlatform", "Source platform"),
      cards("portfolio-kpis", 24, 168, 1232, [
        ["WorkflowAssessment", "Assessed Assets"],
        ["WorkflowAssessment", "High Complexity Assets"],
        ["WorkflowAssessment", "Pilot Assets"],
        ["WorkflowAssessment", "Redesign Assets"],
      ]),
      chart("portfolio-complexity", "Complexity distribution", "barChart", 24, 304, 392, 216, "WorkflowAssessment", "ComplexityBand", measure("WorkflowAssessment", "Assessed Assets")),
      chart("portfolio-targets", "Recommended Fabric targets", "barChart", 432, 304, 392, 216, "WorkflowAssessment", "RecommendedTarget", measure("WorkflowAssessment", "Assessed Assets")),
      chart("portfolio-waves", "Migration wave distribution", "columnChart", 840, 304, 416, 216, "WorkflowAssessment", "MigrationWave", measure("WorkflowAssessment", "Assessed Assets")),
      table("portfolio-register", 24, 536, 1232, 160, [
        column("WorkflowAssessment", "WorkflowPath"),
        column("WorkflowAssessment", "ComplexityScore"),
        column("WorkflowAssessment", "ComplexityBand"),
        column("WorkflowAssessment", "RecommendedTarget"),
        column("WorkflowAssessment", "MigrationWave"),
      ]),
    ],
  },
  {
    key: "register",
    name: "Workflow Assessment Register",
    latestOnly: true,
    visuals: [
      title("register-title", "Workflow Assessment Register", "Filter and rank the governed workflow assessment inventory"),
      slicer("register-run", 24, 72, 280, "AssessmentRun", "RunLabel", "Assessment run"),
      slicer("register-path", 320, 72, 480, "WorkflowAssessment", "WorkflowPath", "Workflow"),
      slicer("register-source", 816, 72, 208, "WorkflowAssessment", "SourcePlatform", "Source platform"),
      slicer("register-complexity", 1040, 72, 216, "WorkflowAssessment", "ComplexityBand", "Complexity"),
      table("register-table", 24, 168, 1232, 528, [
        column("WorkflowAssessment", "WorkflowPath"),
        column("WorkflowAssessment", "SourcePlatform"),
        column("WorkflowAssessment", "AssetType"),
        column("WorkflowAssessment", "ToolCount"),
        column("WorkflowAssessment", "ConnectionCount"),
        column("WorkflowAssessment", "ComplexityScore"),
        column("WorkflowAssessment", "ComplexityBand"),
        column("WorkflowAssessment", "RecommendedTarget"),
        column("WorkflowAssessment", "MigrationWave"),
      ]),
    ],
  },
  {
    key: "plan",
    name: "Evidence-Based Migration Plan",
    latestOnly: true,
    visuals: [
      title("plan-title", "Evidence-Based Migration Plan", "Sequence migration work from deterministic complexity and compiler routing"),
      slicer("plan-run", 24, 72, 280, "AssessmentRun", "RunLabel", "Assessment run"),
      slicer("plan-source", 320, 72, 240, "WorkflowAssessment", "SourcePlatform", "Source platform"),
      cards("plan-kpis", 24, 168, 1232, [
        ["WorkflowAssessment", "Assessed Assets"],
        ["WorkflowAssessment", "Pilot Assets"],
        ["WorkflowAssessment", "Redesign Assets"],
        ["WorkflowAssessment", "Manual Review Assets"],
      ]),
      chart(
        "plan-target-wave",
        "Targets by migration wave",
        "columnChart",
        24,
        304,
        600,
        216,
        "WorkflowAssessment",
        "MigrationWave",
        measure("WorkflowAssessment", "Assessed Assets"),
        column("WorkflowAssessment", "RecommendedTarget"),
      ),
      chart("plan-wave-mix", "Migration wave mix", "barChart", 640, 304, 616, 216, "WorkflowAssessment", "MigrationWave", measure("WorkflowAssessment", "Assessed Assets")),
      table("plan-backlog", 24, 536, 1232, 160, [
        column("WorkflowAssessment", "WorkflowPath"),
        column("WorkflowAssessment", "MigrationWave"),
        column("WorkflowAssessment", "RecommendedTarget"),
        column("WorkflowAssessment", "ComplexityScore"),
        column("WorkflowAssessment", "RecommendationReason"),
      ]),
    ],
  },
  {
    key: "technical",
    name: "Technical Assessment Evidence",
    latestOnly: true,
    visuals: [
      title("technical-title", "Technical Assessment Evidence", "Inspect bounded parser evidence, mappings, findings, and source connections"),
      slicer("technical-run", 24, 72, 280, "AssessmentRun", "RunLabel", "Assessment run"),
      slicer("technical-workflow", 320, 72, 560, "WorkflowAssessment", "WorkflowPath", "Workflow"),
      cards("technical-components", 24, 168, 296, [["WorkflowAssessment", "Source Components"]]),
      cards("technical-connections-card", 336, 168, 296, [["WorkflowAssessment", "Connections"]]),
      cards("technical-dependencies", 648, 168, 296, [["Dependency", "Dependencies"]]),
      cards("technical-findings-card", 960, 168, 296, [["Finding", "Static Findings"]]),
      chart("technical-mapping", "Tool mappings by support category", "barChart", 24, 304, 560, 216, "ToolInventory", "SupportCategory", measure("ToolInventory", "Mapped Components")),
      table("technical-findings", 600, 304, 656, 216, [
        column("WorkflowAssessment", "WorkflowPath"),
        column("Finding", "FindingType"),
        column("Finding", "FindingText"),
      ]),
      table("technical-connections", 24, 536, 1232, 160, [
        column("WorkflowAssessment", "WorkflowPath"),
        column("WorkflowConnection", "SourceNodeId"),
        column("WorkflowConnection", "TargetNodeId"),
        column("WorkflowConnection", "SourceAnchor"),
        column("WorkflowConnection", "TargetAnchor"),
      ]),
    ],
  },
  {
    key: "detail",
    name: "Workflow Assessment Detail",
    latestOnly: true,
    visuals: [
      title("detail-title", "Workflow Assessment Detail", "Drill into one workflow's route, complexity, mappings, findings, and graph evidence"),
      slicer("detail-run", 24, 72, 280, "AssessmentRun", "RunLabel", "Assessment run"),
      slicer("detail-workflow", 320, 72, 704, "WorkflowAssessment", "WorkflowPath", "Workflow"),
      cards("detail-assessed", 24, 168, 296, [["WorkflowAssessment", "Assessed Assets"]]),
      cards("detail-complexity", 336, 168, 296, [["WorkflowAssessment", "Average Complexity Score"]]),
      cards("detail-components", 648, 168, 296, [["WorkflowAssessment", "Source Components"]]),
      cards("detail-connections-card", 960, 168, 296, [["WorkflowAssessment", "Connections"]]),
      table("detail-summary", 24, 304, 1232, 104, [
        column("WorkflowAssessment", "WorkflowPath"),
        column("WorkflowAssessment", "ComplexityScore"),
        column("WorkflowAssessment", "ComplexityBand"),
        column("WorkflowAssessment", "RecommendedTarget"),
        column("WorkflowAssessment", "MigrationWave"),
      ]),
      table("detail-connections", 24, 424, 600, 272, [
        column("WorkflowConnection", "SourceNodeId"),
        column("WorkflowConnection", "TargetNodeId"),
        column("WorkflowConnection", "SourceAnchor"),
        column("WorkflowConnection", "TargetAnchor"),
      ]),
      table("detail-mappings", 640, 424, 616, 272, [
        column("ToolInventory", "ToolName"),
        column("ToolInventory", "ToolCount"),
        column("ToolInventory", "SupportCategory"),
      ]),
    ],
  },
  {
    key: "history",
    name: "Assessment Run History",
    latestOnly: false,
    visuals: [
      title("history-title", "Assessment Run History", "Compare retained assessment executions across completed runs"),
      slicer("history-run", 24, 72, 320, "AssessmentRun", "RunLabel", "Assessment run"),
      slicer("history-source", 360, 72, 240, "WorkflowAssessment", "SourcePlatform", "Source platform"),
      cards("history-kpis", 24, 168, 1232, [
        ["WorkflowAssessment", "Assessed Assets"],
        ["WorkflowAssessment", "High Complexity Assets"],
        ["WorkflowAssessment", "Manual Review Assets"],
        ["WorkflowAssessment", "Average Complexity Score"],
      ]),
      chart("history-volume", "Assessed assets by run", "columnChart", 24, 304, 600, 216, "AssessmentRun", "RunLabel", measure("WorkflowAssessment", "Assessed Assets")),
      chart("history-complexity", "Average complexity by run", "columnChart", 640, 304, 616, 216, "AssessmentRun", "RunLabel", measure("WorkflowAssessment", "Average Complexity Score")),
      table("history-runs", 24, 536, 1232, 160, [
        column("AssessmentRun", "RunLabel"),
        column("AssessmentRun", "Status"),
        column("AssessmentRun", "RulesVersion"),
        column("AssessmentRun", "IsLatestCompletedRun"),
        measure("WorkflowAssessment", "Assessed Assets"),
        measure("WorkflowAssessment", "High Complexity Assets"),
        measure("WorkflowAssessment", "Manual Review Assets"),
      ]),
    ],
  },
];

function id(value) {
  return createHash("sha1").update(value).digest("hex").slice(0, 20);
}

function literal(value) {
  return { expr: { Literal: { Value: value } } };
}

function column(tableName, property) {
  return {
    field: {
      Column: {
        Expression: { SourceRef: { Entity: tableName } },
        Property: property,
      },
    },
    queryRef: `${tableName}.${property}`,
    nativeQueryRef: property,
  };
}

function measure(tableName, property) {
  return {
    field: {
      Measure: {
        Expression: { SourceRef: { Entity: tableName } },
        Property: property,
      },
    },
    queryRef: `${tableName}.${property}`,
    nativeQueryRef: property,
  };
}

function aggregation(tableName, property, functionId) {
  const functionNames = ["Sum", "Average", "Count", "Min", "Max", "Count non-null", "Median"];
  return {
    field: {
      Aggregation: {
        Expression: {
          Column: {
            Expression: { SourceRef: { Entity: tableName } },
            Property: property,
          },
        },
        Function: functionId,
      },
    },
    queryRef: `${functionNames[functionId]}(${tableName}.${property})`,
    nativeQueryRef: `${functionNames[functionId]} of ${property}`,
  };
}

function baseVisual(key, x, y, width, height, visual) {
  return {
    $schema: visualSchema,
    name: id(key),
    position: { x, y, z: 1000, height, width, tabOrder: 1000 },
    visual,
  };
}

function title(key, heading, subtitle) {
  return baseVisual(key, 24, 16, 1232, 48, {
    visualType: "textbox",
    objects: {
      general: [
        {
          properties: {
            paragraphs: [
              {
                textRuns: [
                  {
                    value: heading,
                    textStyle: {
                      fontFamily: "Aptos Display",
                      fontSize: "22px",
                      fontWeight: "bold",
                      color: "#202020",
                    },
                  },
                  {
                    value: `  ${subtitle}`,
                    textStyle: {
                      fontFamily: "Aptos",
                      fontSize: "11px",
                      color: "#5B5B5B",
                    },
                  },
                ],
                horizontalTextAlignment: "left",
              },
            ],
          },
        },
      ],
    },
    visualContainerObjects: {
      background: [{ properties: { show: literal("false") } }],
      border: [{ properties: { show: literal("false") } }],
      padding: [
        {
          properties: {
            top: literal("0D"),
            bottom: literal("0D"),
            left: literal("0D"),
            right: literal("0D"),
          },
        },
      ],
    },
  });
}

function slicer(key, x, y, width, tableName, property, displayName) {
  return baseVisual(key, x, y, width, 80, {
    visualType: "slicer",
    query: {
      queryState: {
        Values: { projections: [column(tableName, property)] },
      },
    },
    objects: {
      data: [{ properties: { mode: literal("'Dropdown'") } }],
      header: [
        {
          properties: {
            show: literal("true"),
            text: literal(`'${displayName}'`),
          },
        },
      ],
    },
    visualContainerObjects: {
      padding: [
        {
          properties: {
            top: literal("8D"),
            bottom: literal("8D"),
            left: literal("8D"),
            right: literal("8D"),
          },
        },
      ],
    },
  });
}

function cards(key, x, y, width, fields) {
  return baseVisual(key, x, y, width, 120, {
    visualType: "cardVisual",
    query: {
      queryState: {
        Data: {
          projections: fields.map(([tableName, property]) => measure(tableName, property)),
        },
      },
    },
    objects: {
      value: [{ properties: { fontSize: literal("22D") }, selector: { id: "default" } }],
      label: [{ properties: { fontSize: literal("10D") }, selector: { id: "default" } }],
      padding: [{ properties: { paddingUniform: literal("8D") }, selector: { id: "default" } }],
      layout: [{ properties: { paddingUniform: literal("0D") }, selector: { id: "default" } }],
    },
  });
}

function chart(key, titleText, visualType, x, y, width, height, categoryTable, categoryProperty, value, series) {
  const queryState = {
    Category: { projections: [{ ...column(categoryTable, categoryProperty), active: true }] },
    Y: { projections: [value] },
  };
  if (series) {
    queryState.Series = { projections: [series] };
  }
  return baseVisual(key, x, y, width, height, {
    visualType,
    query: { queryState },
    visualContainerObjects: {
      title: [
        {
          properties: {
            show: literal("true"),
            text: literal(`'${titleText}'`),
            heading: literal("'Heading3'"),
            titleWrap: literal("true"),
            fontSize: literal("12D"),
            bold: literal("true"),
          },
        },
      ],
    },
  });
}

function table(key, x, y, width, height, projections) {
  return baseVisual(key, x, y, width, height, {
    visualType: "tableEx",
    query: {
      queryState: {
        Values: { projections },
      },
    },
    objects: {
      columnHeaders: [
        {
          properties: {
            columnAdjustment: literal("'growToFit'"),
            autoSizeColumnWidth: literal("true"),
          },
        },
      ],
    },
  });
}

function latestCompletedFilter(scopeKey) {
  return {
    name: `Filter${id(`latest-completed-run-${scopeKey}`)}`,
    field: {
      Column: {
        Expression: { SourceRef: { Entity: "AssessmentRun" } },
        Property: "IsLatestCompletedRun",
      },
    },
    type: "Categorical",
    filter: {
      Version: 2,
      From: [{ Name: "a", Entity: "AssessmentRun", Type: 0 }],
      Where: [
        {
          Condition: {
            In: {
              Expressions: [
                {
                  Column: {
                    Expression: { SourceRef: { Source: "a" } },
                    Property: "IsLatestCompletedRun",
                  },
                },
              ],
              Values: [[{ Literal: { Value: "true" } }]],
            },
          },
        },
      ],
    },
    howCreated: "User",
    isHiddenInViewMode: true,
    isLockedInViewMode: true,
  };
}

async function writeJson(filePath, value) {
  await mkdir(path.dirname(filePath), { recursive: true });
  await writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

const existingPages = JSON.parse(await readFile(path.join(pagesDir, "pages.json"), "utf8"));
for (const oldPageId of existingPages.pageOrder ?? []) {
  await rm(path.join(pagesDir, oldPageId), { recursive: true, force: true });
}

const pageOrder = [];
for (const pageDefinition of pageDefinitions) {
  const pageId = id(`page-${pageDefinition.key}`);
  pageOrder.push(pageId);
  const pageDir = path.join(pagesDir, pageId);
  await rm(pageDir, { recursive: true, force: true });
  await writeJson(path.join(pageDir, "page.json"), {
    $schema: pageSchema,
    name: pageId,
    displayName: pageDefinition.name,
    displayOption: "FitToPage",
    height: 720,
    width: 1280,
    ...(pageDefinition.latestOnly ? { filterConfig: { filters: [latestCompletedFilter(pageDefinition.key)] } } : {}),
  });
  const seenVisuals = new Set();
  for (const visual of pageDefinition.visuals) {
    if (seenVisuals.has(visual.name)) {
      throw new Error(`Duplicate visual id '${visual.name}' on page '${pageDefinition.key}'.`);
    }
    seenVisuals.add(visual.name);
    await writeJson(path.join(pageDir, "visuals", visual.name, "visual.json"), visual);
  }
}

await writeJson(path.join(pagesDir, "pages.json"), {
  $schema:
    "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json",
  pageOrder,
  activePageName: pageOrder[0],
});

const reportPath = path.join(definitionDir, "report.json");
const report = JSON.parse(await readFile(reportPath, "utf8"));
delete report.filterConfig;
await writeJson(reportPath, report);

console.log(`Generated ${pageDefinitions.length} PBIR pages in ${reportDir}`);
