import { AlertCircle, LoaderCircle } from "lucide-react";

import type { QueryRecord } from "@/hooks/use-query-records";
import { formatValue } from "@/lib/format-value";

export function Panel({
  title,
  subtitle,
  children,
  className = "",
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border bg-card p-5 shadow-container-2 ${className}`}>
      <h2 className="font-visual-title text-visual-title font-semibold">{title}</h2>
      {subtitle && <p className="mt-1 text-200 text-muted-foreground">{subtitle}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

export function DataState({
  isLoading,
  error,
  empty,
}: {
  isLoading: boolean;
  error?: Error;
  empty?: boolean;
}) {
  if (error) {
    return (
      <div role="alert" className="flex items-start gap-2 rounded-lg border border-destructive p-4 text-destructive">
        <AlertCircle className="icon-size-200 shrink-0" />
        <span>{error.message}</span>
      </div>
    );
  }
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 rounded-lg border p-4 text-muted-foreground">
        <LoaderCircle className="icon-size-200 animate-spin" />
        Loading live assessment data
      </div>
    );
  }
  if (empty) {
    return <p className="rounded-lg border p-4 text-200 text-muted-foreground">No matching evidence is available.</p>;
  }
  return null;
}

export interface TableColumn {
  key: string;
  label: string;
  render?: (record: QueryRecord) => React.ReactNode;
}

export function SimpleTable({
  records,
  columns,
  onSelect,
  rowLabel,
}: {
  records: QueryRecord[];
  columns: TableColumn[];
  onSelect?: (record: QueryRecord) => void;
  rowLabel?: (record: QueryRecord) => string;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-separate border-spacing-0 text-left text-200">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} className="border-b bg-muted/50 p-3 font-semibold">{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {records.map((record, index) => {
            const cells = columns.map((column) =>
              column.render ? column.render(record) : formatValue(record[column.key]),
            );
            const key = `${String(record.WorkflowPath ?? record.NodeId ?? record.FindingText ?? "row")}-${index}`;
            return (
              <tr
                key={key}
                className={onSelect ? "cursor-pointer hover:bg-hover" : ""}
                onClick={onSelect ? () => onSelect(record) : undefined}
                onKeyDown={onSelect ? (event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelect(record);
                  }
                } : undefined}
                tabIndex={onSelect ? 0 : undefined}
                aria-label={rowLabel?.(record)}
              >
                {cells.map((cell, cellIndex) => (
                  <td key={columns[cellIndex].key} className="max-w-md border-b p-3 align-top">{cell}</td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function Pill({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "success" | "warning" | "danger" }) {
  const tones = {
    neutral: "bg-muted text-foreground",
    success: "bg-success/10 text-success",
    warning: "bg-warning/10 text-warning-foreground",
    danger: "bg-destructive/10 text-destructive",
  };
  return <span className={`inline-flex rounded-full px-2.5 py-1 text-100 font-semibold ${tones[tone]}`}>{children}</span>;
}

