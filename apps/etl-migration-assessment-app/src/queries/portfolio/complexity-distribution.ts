import type { VisualizationSpec } from "@microsoft/fabric-visuals";
import type { ColumnMetadataMap } from "@/lib/to-data-table";
import query from "./complexity-distribution.dax?raw";

export const connection = "assessmentmodel";

export { query };

export const columnMetadata: ColumnMetadataMap = {
  "WorkflowAssessment[ComplexityBand]": { name: "ComplexityBand", displayName: "Complexity" },
  "[Assets]": { name: "Assets", displayName: "Assets", format: "#,##0" },
};

export const vegaLiteSpec: VisualizationSpec = {
  $schema: "https://vega.github.io/schema/vega-lite/v6.json",
  mark: { type: "bar", cornerRadiusEnd: 4 },
  encoding: {
    y: { field: "ComplexityBand", type: "nominal", sort: "-x", title: null },
    x: { field: "Assets", type: "quantitative", title: "Assets" },
    color: {
      field: "ComplexityBand",
      type: "nominal",
      legend: null,
      scale: { range: ["#107c10", "#ffb900", "#d13438"] },
    },
    tooltip: [
      { field: "ComplexityBand", type: "nominal", title: "Complexity" },
      { field: "Assets", type: "quantitative", title: "Assets", format: ",.0f" },
    ],
  },
};

export function createComplexityDistribution() {
  return { connection, query, columnMetadata, vegaLiteSpec };
}
