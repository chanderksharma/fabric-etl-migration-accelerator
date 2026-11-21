import type { VisualizationSpec } from "@microsoft/fabric-visuals";
import type { ColumnMetadataMap } from "@/lib/to-data-table";
import query from "./target-distribution.dax?raw";

export const connection = "assessmentmodel";

export { query };

export const columnMetadata: ColumnMetadataMap = {
  "WorkflowAssessment[RecommendedTarget]": { name: "RecommendedTarget", displayName: "Fabric target" },
  "[Assets]": { name: "Assets", displayName: "Assets", format: "#,##0" },
};

export const vegaLiteSpec: VisualizationSpec = {
  $schema: "https://vega.github.io/schema/vega-lite/v6.json",
  mark: { type: "bar", cornerRadiusEnd: 4 },
  encoding: {
    y: { field: "RecommendedTarget", type: "nominal", sort: "-x", title: null },
    x: { field: "Assets", type: "quantitative", title: "Assets" },
    color: { field: "RecommendedTarget", type: "nominal", legend: null },
    tooltip: [
      { field: "RecommendedTarget", type: "nominal", title: "Fabric target" },
      { field: "Assets", type: "quantitative", title: "Assets", format: ",.0f" },
    ],
  },
};

export function createTargetDistribution() {
  return { connection, query, columnMetadata, vegaLiteSpec };
}
