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
    key: "executive",
    name: "Executive Summary",
    visuals: [
      title(
        "exec-title",
        "Executive Portfolio Summary",
        "Automation readiness, wave composition, and priority migration candidates across retained assessments",
      ),
      slicer("exec-run", 696, 12, 316, "AssessmentRun", "RunLabel", "Assessment run"),
      slicer("exec-source", 1028, 12, 228, "WorkflowAssessment", "SourcePlatform", "Source platform"),
      cards("exec-kpis", 24, 96, 1232, [
        ["WorkflowAssessment", "Assessed Assets KPI", "Assessed Workflows"],
        ["WorkflowAssessment", "Native-Ready % KPI", "Native-Ready %"],
        ["WorkflowAssessment", "Quick-Win % KPI", "Quick-Win %"],
        ["WorkflowAssessment", "High Complexity KPI", "High Complexity"],
        ["CapacityProfile", "Total Complexity Units KPI", "Complexity Units"],
      ]),
      chart(
        "exec-wave-target",
        "Migration waves (Wave 1–4) by recommended target",
        "barChart",
        24,
        228,
        604,
        232,
        "WorkflowAssessment",
        "RecommendedTarget",
        [
          measure("WorkflowAssessment", "Wave 1 Assets", "Wave 1"),
          measure("WorkflowAssessment", "Wave 2 Assets", "Wave 2"),
          measure("WorkflowAssessment", "Wave 3 Assets", "Wave 3"),
          measure("WorkflowAssessment", "Wave 4 Assets", "Wave 4"),
        ],
        undefined,
      ),
      chart(
        "exec-platform-band",
        "Estate complexity by source platform",
        "barChart",
        652,
        228,
        604,
        232,
        "WorkflowAssessment",
        "SourcePlatform",
        measure("WorkflowAssessment", "Assessed Assets"),
        column("WorkflowAssessment", "ComplexityBand"),
      ),
      table(
        "exec-priority-table",
        24,
        476,
        1232,
        224,
        "Priority & high-complexity workflows",
        [
          column("WorkflowAssessment", "WorkflowPath", "Workflow", 290),
          column("WorkflowAssessment", "ComplexityBand", "Band", 90),
          column("WorkflowAssessment", "ComplexityScore", "Score", 70),
          column("WorkflowAssessment", "RecommendedTarget", "Fabric Target", 165),
          measure("WorkflowAssessment", "Migration Stage Label", "Wave", 90),
          column("WorkflowAssessment", "RecommendationReason", "Rationale", 495),
        ],
        undefined,
        descendingColumnSort("WorkflowAssessment", "ComplexityScore"),
      ),
    ],
  },
  {
    key: "waves",
    name: "Wave Plan",
    visuals: [
      title(
        "wave-title",
        "Wave & Delivery Plan",
        "Mobilization sequencing normalized to Wave 1 (Foundation), Wave 2 (Pilot), Wave 3 (Scale-out), and Wave 4 (Redesign)",
      ),
      slicer("wave-run", 696, 12, 316, "AssessmentRun", "RunLabel", "Assessment run"),
      slicer("wave-filter", 1028, 12, 228, "WorkflowAssessment", "RecommendedTarget", "Fabric target"),
      cards("wave-kpis", 24, 96, 1232, [
        ["WorkflowAssessment", "Wave 1 KPI", "Wave 1 (Foundation)"],
        ["WorkflowAssessment", "Wave 2 KPI", "Wave 2 (Pilot)"],
        ["WorkflowAssessment", "Wave 3 KPI", "Wave 3 (Scale-out)"],
        ["WorkflowAssessment", "Wave 4 KPI", "Wave 4 (Redesign)"],
      ]),
      matrix(
        "wave-matrix",
        "Wave 1–4 breakdown by target & platform",
        24,
        228,
        604,
        224,
        [column("WorkflowAssessment", "RecommendedTarget"), column("WorkflowAssessment", "SourcePlatform")],
        [],
        [
          measure("WorkflowAssessment", "Wave 1 Assets", "Wave 1"),
          measure("WorkflowAssessment", "Wave 2 Assets", "Wave 2"),
          measure("WorkflowAssessment", "Wave 3 Assets", "Wave 3"),
          measure("WorkflowAssessment", "Wave 4 Assets", "Wave 4"),
          measure("WorkflowAssessment", "Assessed Assets", "Total"),
        ],
      ),
      chart(
        "wave-support",
        "Component automation coverage",
        "barChart",
        652,
        228,
        604,
        224,
        "ToolInventory",
        "SupportCategory",
        measure("ToolInventory", "Mapped Components"),
        undefined,
        undefined,
        descendingMeasureSort("ToolInventory", "Mapped Components"),
      ),
      table(
        "wave-backlog",
        24,
        468,
        1232,
        232,
        "Sequenced migration backlog",
        [
          column("WorkflowAssessment", "WorkflowPath", "Workflow", 300),
          measure("WorkflowAssessment", "Migration Stage Label", "Wave", 95),
          column("WorkflowAssessment", "RecommendedTarget", "Fabric Target", 170),
          column("WorkflowAssessment", "ComplexityScore", "Score", 75),
          column("WorkflowAssessment", "RecommendationReason", "Rationale", 560),
        ],
        undefined,
        descendingColumnSort("WorkflowAssessment", "ComplexityScore"),
      ),
    ],
  },
  {
    key: "blockers",
    name: "Blockers & Risks",
    visuals: [
      title(
        "risk-title",
        "Portfolio Blockers & Risks",
        "Unsupported legacy tools, manual engineering effort drivers, and parser findings",
      ),
      slicer("risk-run", 696, 12, 316, "AssessmentRun", "RunLabel", "Assessment run"),
      slicer("risk-source", 1028, 12, 228, "WorkflowAssessment", "SourcePlatform", "Source platform"),
      cards("risk-kpis", 24, 96, 1232, [
        ["WorkflowAssessment", "Manual Review KPI", "Manual Review Workflows"],
        ["ToolInventory", "Manual Tool Components KPI", "Manual Tool Components"],
        ["Dependency", "Dependencies KPI", "Dependencies"],
        ["Finding", "Static Findings KPI", "Static Findings"],
      ]),
      chart(
        "risk-manual-tools",
        "Source tools requiring manual engineering",
        "barChart",
        24,
        228,
        460,
        232,
        "ToolInventory",
        "ToolName",
        measure("ToolInventory", "Manual Tool Components"),
        undefined,
        [categoricalFilter("ToolInventory", "SupportCategory", ["manual", "unsupported"], "risk-support-cat")],
        descendingMeasureSort("ToolInventory", "Manual Tool Components"),
      ),
      table(
        "risk-workflow-summary",
        500,
        228,
        756,
        232,
        "Workflows with blockers & findings",
        [
          column("WorkflowAssessment", "WorkflowPath", "Workflow", 310),
          column("WorkflowAssessment", "RecommendedTarget", "Fabric Target", 165),
          measure("ToolInventory", "Manual Tool Components", "Manual Tools", 120),
          measure("Finding", "Static Findings", "Findings", 110),
        ],
        undefined,
        descendingMeasureSort("Finding", "Static Findings"),
      ),
      table(
        "risk-findings",
        24,
        476,
        1232,
        224,
        "Parser & unsupported-tool findings",
        [
          column("WorkflowAssessment", "WorkflowPath", "Workflow", 310),
          column("Finding", "FindingType", "Type", 145),
          column("Finding", "FindingText", "Finding Detail", 745),
        ],
        [categoricalFilter("Finding", "FindingType", ["UnsupportedTool", "Parser"], "risk-finding-types")],
      ),
    ],
  },
  {
    key: "capacity",
    name: "Fabric Capacity",
    visuals: [
      title(
        "cap-title",
        "Fabric Capacity & F-SKU Sizing",
        "Recommended Fabric F-SKU, balanced CUs needed, and monthly CU-hours (daily baseline: 1k rows/run, 80% utilization)",
      ),
      slicer("cap-run", 696, 12, 316, "AssessmentRun", "RunLabel", "Assessment run"),
      slicer("cap-target", 1028, 12, 228, "WorkflowAssessment", "RecommendedTarget", "Fabric target"),
      cards("cap-kpis", 24, 96, 1232, [
        ["CapacityProfile", "Recommended Fabric SKU KPI", "Recommended SKU"],
        ["CapacityProfile", "Required CUs (Balanced) KPI", "Balanced CUs Needed"],
        ["CapacityProfile", "Est Monthly CU-Hours KPI", "Est. Monthly CU-Hours"],
        ["CapacityProfile", "Est CU-Seconds / Run KPI", "Est. CU-Sec / Run"],
        ["CapacityProfile", "Total Complexity Units KPI", "Complexity Units"],
      ]),
      scatter(
        "cap-scatter",
        "Workflow compute footprint (Active Steps vs. Est. CU-Seconds / Run)",
        24,
        228,
        604,
        236,
        column("WorkflowAssessment", "WorkflowPath"),
        measure("CapacityProfile", "Total Active Steps"),
        measure("CapacityProfile", "Est CU-Seconds / Run"),
        column("WorkflowAssessment", "RecommendedTarget"),
      ),
      chart(
        "cap-target-units",
        "Est. CU-Seconds / Run by Fabric target",
        "barChart",
        652,
        228,
        604,
        236,
        "WorkflowAssessment",
        "RecommendedTarget",
        measure("CapacityProfile", "Est CU-Seconds / Run"),
        undefined,
        undefined,
        descendingMeasureSort("CapacityProfile", "Est CU-Seconds / Run"),
      ),
      table(
        "cap-table",
        24,
        480,
        1232,
        220,
        "Workflow Fabric capacity & CU sizing",
        [
          column("WorkflowAssessment", "WorkflowPath", "Workflow", 280),
          column("CapacityProfile", "TargetComponents", "Fabric Components", 230),
          measure("CapacityProfile", "Est CU-Seconds / Run", "Est. CU-Sec / Run", 125),
          measure("CapacityProfile", "Est Monthly CU-Hours", "Monthly CU-Hours", 125),
          column("CapacityProfile", "ComplexityUnits", "Complexity Units", 120),
          column("CapacityProfile", "TotalSteps", "Active Steps", 100),
          column("CapacityProfile", "HeavySteps", "Heavy Steps", 100),
          column("CapacityProfile", "DestCount", "Outputs", 90),
        ],
        undefined,
        descendingMeasureSort("CapacityProfile", "Est CU-Seconds / Run"),
      ),
    ],
  },
  {
    key: "history",
    name: "Run History",
    visuals: [
      title(
        "hist-title",
        "Assessment Run History",
        "Compare volume, native automation readiness, and complexity across retained runs",
      ),
      slicer("hist-run", 696, 12, 316, "AssessmentRun", "RunLabel", "Assessment run"),
      slicer("hist-source", 1028, 12, 228, "WorkflowAssessment", "SourcePlatform", "Source platform"),
      cards("hist-kpis", 24, 96, 1232, [
        ["WorkflowAssessment", "Assessed Assets KPI", "Assessed Workflows"],
        ["WorkflowAssessment", "Native-Ready % KPI", "Native-Ready %"],
        ["WorkflowAssessment", "High Complexity KPI", "High Complexity"],
        ["WorkflowAssessment", "Average Complexity Score", "Avg Complexity"],
      ]),
      chart(
        "hist-volume",
        "Assessed workflows by run",
        "columnChart",
        24,
        228,
        604,
        232,
        "AssessmentRun",
        "RunLabel",
        measure("WorkflowAssessment", "Assessed Assets"),
      ),
      lineWithSecondary(
        "hist-trend",
        "Native-ready % & average complexity by run",
        652,
        228,
        604,
        232,
        column("AssessmentRun", "RunLabel"),
        measure("WorkflowAssessment", "Native-Ready %"),
        measure("WorkflowAssessment", "Average Complexity Score"),
      ),
      table("hist-ledger", 24, 476, 1232, 224, "Assessment execution ledger", [
        column("AssessmentRun", "RunLabel"),
        column("AssessmentRun", "Status"),
        column("AssessmentRun", "RulesVersion"),
        column("AssessmentRun", "IsLatestCompletedRun"),
        measure("WorkflowAssessment", "Assessed Assets"),
        measure("WorkflowAssessment", "Native-Ready %"),
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

function column(tableName, property, displayName, width) {
  return {
    field: {
      Column: {
        Expression: { SourceRef: { Entity: tableName } },
        Property: property,
      },
    },
    queryRef: `${tableName}.${property}`,
    nativeQueryRef: property,
    ...(displayName ? { displayName } : {}),
    ...(width ? { _width: width } : {}),
  };
}

function measure(tableName, property, displayName, width) {
  return {
    field: {
      Measure: {
        Expression: { SourceRef: { Entity: tableName } },
        Property: property,
      },
    },
    queryRef: `${tableName}.${property}`,
    nativeQueryRef: property,
    ...(displayName ? { displayName } : {}),
    ...(width ? { _width: width } : {}),
  };
}

function cleanProjections(projections) {
  return projections.map((p) => {
    const copy = { ...p };
    delete copy._width;
    return copy;
  });
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

function baseVisual(key, x, y, width, height, visual, filters) {
  return {
    $schema: visualSchema,
    name: id(key),
    position: { x, y, z: 1000, height, width, tabOrder: 1000 },
    visual,
    ...(filters ? { filterConfig: { filters } } : {}),
  };
}

function title(key, heading, subtitle) {
  return baseVisual(key, 24, 12, 656, 68, {
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
                      fontSize: "20px",
                      fontWeight: "bold",
                      color: "#1F1F1F",
                    },
                  },
                ],
                horizontalTextAlignment: "left",
              },
              {
                textRuns: [
                  {
                    value: subtitle,
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
  return baseVisual(key, x, y, width, 76, {
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
            top: literal("4D"),
            bottom: literal("4D"),
            left: literal("8D"),
            right: literal("8D"),
          },
        },
      ],
    },
  });
}

function cards(key, x, y, width, fields) {
  return baseVisual(key, x, y, width, 116, {
    visualType: "cardVisual",
    query: {
      queryState: {
        Data: {
          projections: fields.map(([tableName, property, displayName]) =>
            measure(tableName, property, displayName),
          ),
        },
      },
    },
    objects: {
      value: [{ properties: { fontSize: literal("22D") }, selector: { id: "default" } }],
      label: [{ properties: { fontSize: literal("10D") }, selector: { id: "default" } }],
      padding: [{ properties: { paddingUniform: literal("8D") }, selector: { id: "default" } }],
      layout: [
        {
          properties: {
            columnCount: literal(`${fields.length}D`),
            rowCount: literal("1D"),
            maxTiles: literal(`${fields.length}D`),
            autoGrid: literal("true"),
            paddingUniform: literal("0D"),
          },
          selector: { id: "default" },
        },
      ],
    },
  });
}

function chartTitle(titleText) {
  return {
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
    subTitle: [
      {
        properties: {
          show: literal("false"),
        },
      },
    ],
  };
}

function descendingMeasureSort(tableName, property) {
  return {
    sort: [
      {
        field: {
          Measure: {
            Expression: { SourceRef: { Entity: tableName } },
            Property: property,
          },
        },
        direction: "Descending",
      },
    ],
  };
}

function descendingColumnSort(tableName, property) {
  return {
    sort: [
      {
        field: {
          Column: {
            Expression: { SourceRef: { Entity: tableName } },
            Property: property,
          },
        },
        direction: "Descending",
      },
    ],
  };
}

function chart(key, titleText, visualType, x, y, width, height, categoryTable, categoryProperty, value, series, filters, sortDefinition) {
  const yProjections = Array.isArray(value) ? value : [value];
  const queryState = {
    Category: { projections: [{ ...column(categoryTable, categoryProperty), active: true }] },
    Y: { projections: yProjections },
  };
  if (series) {
    queryState.Series = { projections: [series] };
  }
  const objects = {
    categoryAxis: [
      {
        properties: {
          maxMarginFactor: literal("45D"),
          fontSize: literal("10D"),
        },
      },
    ],
    labels: [
      {
        properties: {
          show: literal("true"),
        },
      },
    ],
  };
  if (series || yProjections.length > 1) {
    objects.legend = [
      {
        properties: {
          show: literal("true"),
          position: literal("'Top'"),
        },
      },
    ];
  }
  return baseVisual(
    key,
    x,
    y,
    width,
    height,
    {
      visualType,
      query: {
        queryState,
        ...(sortDefinition ? { sortDefinition } : {}),
      },
      objects,
      visualContainerObjects: chartTitle(titleText),
    },
    filters,
  );
}

function lineWithSecondary(key, titleText, x, y, width, height, categoryField, primaryMeasure, secondaryMeasure) {
  return baseVisual(key, x, y, width, height, {
    visualType: "lineChart",
    query: {
      queryState: {
        Category: { projections: [{ ...categoryField, active: true }] },
        Y: { projections: [primaryMeasure] },
        Y2: { projections: [secondaryMeasure] },
      },
    },
    objects: {
      categoryAxis: [
        {
          properties: {
            maxMarginFactor: literal("40D"),
            fontSize: literal("10D"),
          },
        },
      ],
      legend: [
        {
          properties: {
            show: literal("true"),
            position: literal("'Top'"),
          },
        },
      ],
      labels: [
        {
          properties: {
            show: literal("true"),
          },
        },
      ],
    },
    visualContainerObjects: chartTitle(titleText),
  });
}

function scatter(key, titleText, x, y, width, height, categoryField, xMeasure, yMeasure, seriesField) {
  return baseVisual(key, x, y, width, height, {
    visualType: "scatterChart",
    query: {
      queryState: {
        Category: { projections: [{ ...categoryField, active: true }] },
        Series: { projections: [seriesField] },
        X: { projections: [xMeasure] },
        Y: { projections: [yMeasure] },
      },
    },
    objects: {
      bubbles: [
        {
          properties: {
            bubbleSize: literal("12D"),
          },
        },
      ],
      legend: [
        {
          properties: {
            show: literal("true"),
            position: literal("'Top'"),
          },
        },
      ],
    },
    visualContainerObjects: chartTitle(titleText),
  });
}

function matrix(key, titleText, x, y, width, height, rows, columns, values) {
  const queryState = {
    Rows: { projections: rows },
    Values: { projections: values },
  };
  if (columns.length > 0) {
    queryState.Columns = { projections: columns };
  }
  return baseVisual(key, x, y, width, height, {
    visualType: "pivotTable",
    query: { queryState },
    objects: {
      columnHeaders: [
        {
          properties: {
            columnAdjustment: literal("'growToFit'"),
            autoSizeColumnWidth: literal("true"),
          },
        },
      ],
      values: [
        {
          properties: {
            wordWrap: literal("true"),
          },
        },
      ],
    },
    visualContainerObjects: chartTitle(titleText),
  });
}

function table(key, x, y, width, height, titleText, projections, filters, sortDefinition) {
  const hasWidths = projections.some((p) => typeof p._width === "number");
  const columnWidth = projections
    .filter((p) => typeof p._width === "number")
    .map((p) => ({
      properties: { value: { expr: { Literal: { Value: `${p._width}D` } } } },
      selector: { metadata: p.queryRef },
    }));
  return baseVisual(
    key,
    x,
    y,
    width,
    height,
    {
      visualType: "tableEx",
      query: {
        queryState: {
          Values: { projections: cleanProjections(projections) },
        },
        ...(sortDefinition ? { sortDefinition } : {}),
      },
      objects: {
        columnHeaders: [
          {
            properties: {
              columnAdjustment: literal(hasWidths ? "'fixedWidth'" : "'growToFit'"),
              autoSizeColumnWidth: literal(hasWidths ? "false" : "true"),
            },
          },
        ],
        ...(columnWidth.length > 0 ? { columnWidth } : {}),
        values: [
          {
            properties: {
              wordWrap: literal("true"),
            },
          },
        ],
      },
      visualContainerObjects: chartTitle(titleText),
    },
    filters,
  );
}

function categoricalFilter(tableName, property, allowedValues, scopeKey) {
  return {
    name: `Filter${id(scopeKey)}`,
    field: {
      Column: {
        Expression: { SourceRef: { Entity: tableName } },
        Property: property,
      },
    },
    type: "Categorical",
    filter: {
      Version: 2,
      From: [{ Name: "t", Entity: tableName, Type: 0 }],
      Where: [
        {
          Condition: {
            In: {
              Expressions: [
                {
                  Column: {
                    Expression: { SourceRef: { Source: "t" } },
                    Property: property,
                  },
                },
              ],
              Values: allowedValues.map((v) => [{ Literal: { Value: `'${v}'` } }]),
            },
          },
        },
      ],
    },
    howCreated: "User",
    isHiddenInViewMode: false,
    isLockedInViewMode: false,
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
