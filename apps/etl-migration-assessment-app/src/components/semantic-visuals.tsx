import { DataGrid } from "@microsoft/fabric-datagrid";
import { KpiCard, VegaVisual } from "@microsoft/fabric-visuals";
import type { DataTable } from "@microsoft/fabric-visuals-core";
import type { VisualizationSpec } from "@microsoft/fabric-visuals";
import { AlertCircle, LoaderCircle } from "lucide-react";

import { useSemanticModelQuery } from "@/hooks/use-semantic-model-query";
import { useThemeContext } from "@/hooks/theme.context";
import { toDataTable, type ColumnMetadataMap } from "@/lib/to-data-table";

export interface QueryDefinition {
  connection: string;
  query: string;
  columnMetadata: ColumnMetadataMap;
}

interface ChartDefinition extends QueryDefinition {
  vegaLiteSpec: VisualizationSpec;
}

interface MetricDefinition {
  rawName: string;
  title: string;
  subtitle: string;
}

export function MetricCards({
  definition,
  metrics,
}: {
  definition: QueryDefinition;
  metrics: readonly MetricDefinition[];
}) {
  const { theme } = useThemeContext();
  const { data, isLoading, error } = useSemanticModelQuery(definition);

  if (error) {
    return <QueryError message={error.message} />;
  }
  if (isLoading || !data) {
    return <LoadingGrid count={metrics.length} />;
  }
  if (data.status !== "success") {
    return <QueryError message={data.error.message} />;
  }

  const table = toDataTable(data.table, definition.columnMetadata);
  return (
    <div className="grid gap-(--grid-gap) sm:grid-cols-2 xl:grid-cols-4">
      {metrics.map((metric) => {
        const cell = getCell(table, definition.columnMetadata[metric.rawName]?.name);
        return (
          <KpiCard
            key={metric.rawName}
            theme={theme}
            header={{ title: metric.title, subtitle: metric.subtitle }}
            callout={{ metric: { value: cell.value, format: cell.format } }}
          />
        );
      })}
    </div>
  );
}

export function SemanticChart({
  definition,
  title,
  subtitle,
}: {
  definition: ChartDefinition;
  title: string;
  subtitle: string;
}) {
  const { theme } = useThemeContext();
  const { data, isLoading, error } = useSemanticModelQuery(definition);

  if (error) {
    return <QueryError message={error.message} />;
  }
  if (isLoading || !data) {
    return <LoadingPanel />;
  }
  if (data.status !== "success") {
    return <QueryError message={data.error.message} />;
  }

  return (
    <VegaVisual
      className="h-72"
      theme={theme}
      header={{ title, subtitle }}
      spec={definition.vegaLiteSpec}
      data={toDataTable(data.table, definition.columnMetadata)}
    />
  );
}

export function SemanticGrid({
  definition,
  title,
  subtitle,
}: {
  definition: QueryDefinition;
  title: string;
  subtitle: string;
}) {
  const { theme } = useThemeContext();
  const { data, isLoading, error } = useSemanticModelQuery(definition);

  if (error) {
    return <QueryError message={error.message} />;
  }
  if (isLoading || !data) {
    return <LoadingPanel />;
  }
  if (data.status !== "success") {
    return <QueryError message={data.error.message} />;
  }

  return (
    <div className="h-96">
      <DataGrid
        theme={theme}
        header={{ title, subtitle }}
        data={toDataTable(data.table, definition.columnMetadata)}
      />
    </div>
  );
}

function getCell(table: DataTable, columnName: string | undefined) {
  if (!columnName || table.rows.length === 0) {
    return { value: null, format: undefined };
  }
  const columnIndex = table.columns.findIndex((column) => column.name === columnName);
  if (columnIndex < 0) {
    return { value: null, format: undefined };
  }
  const value = table.rows[0][columnIndex];
  return {
    value: typeof value === "number" || typeof value === "string" ? value : null,
    format: table.columns[columnIndex].format,
  };
}

function LoadingGrid({ count }: { count: number }) {
  return (
    <div className="grid gap-(--grid-gap) sm:grid-cols-2 xl:grid-cols-4" aria-label="Loading metrics">
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="h-32 animate-pulse rounded-xl border bg-muted" />
      ))}
    </div>
  );
}

function LoadingPanel() {
  return (
    <div className="flex h-72 items-center justify-center rounded-xl border bg-card text-muted-foreground">
      <LoaderCircle className="icon-size-300 animate-spin" aria-hidden="true" />
      <span className="ml-2 text-300">Loading live assessment data</span>
    </div>
  );
}

function QueryError({ message }: { message: string }) {
  return (
    <div role="alert" className="flex min-h-32 items-start gap-3 rounded-xl border border-destructive bg-card p-4 text-destructive">
      <AlertCircle className="icon-size-300 shrink-0" aria-hidden="true" />
      <div>
        <p className="font-semibold">The assessment data could not be loaded</p>
        <p className="mt-1 text-200">{message}</p>
      </div>
    </div>
  );
}
