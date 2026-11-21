import { useMemo } from "react";

import type { QueryDefinition } from "@/components/semantic-visuals";
import { useSemanticModelQuery } from "@/hooks/use-semantic-model-query";
import { toDataTable } from "@/lib/to-data-table";

export type QueryRecord = Record<string, unknown>;

export function useQueryRecords(definition: QueryDefinition) {
  const result = useSemanticModelQuery(definition);
  const records = useMemo(() => {
    if (result.data?.status !== "success") return [];
    const table = toDataTable(result.data.table, definition.columnMetadata);
    return table.rows.map((row) =>
      Object.fromEntries(table.columns.map((column, index) => [column.name, row[index]])),
    );
  }, [definition, result.data]);

  return { ...result, records };
}
