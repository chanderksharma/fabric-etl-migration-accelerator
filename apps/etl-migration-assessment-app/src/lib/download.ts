export function downloadJson(fileName: string, value: unknown): void {
  downloadText(fileName, JSON.stringify(value, null, 2), "application/json");
}

export function downloadCsv(
  fileName: string,
  columns: readonly string[],
  records: readonly Record<string, unknown>[],
): void {
  const rows = [
    columns,
    ...records.map((record) => columns.map((column) => record[column])),
  ];
  downloadText(
    fileName,
    rows.map((row) => row.map(csvCell).join(",")).join("\r\n"),
    "text/csv;charset=utf-8",
  );
}

export function formulaSafe(value: unknown): string {
  const text = value == null ? "" : String(value);
  return text.startsWith("\t") ||
    text.startsWith("\r") ||
    text.startsWith("\n") ||
    /^[=+\-@]/.test(text.trimStart())
    ? `'${text}`
    : text;
}

function csvCell(value: unknown): string {
  const text = formulaSafe(value).replaceAll('"', '""');
  return `"${text}"`;
}

function downloadText(fileName: string, content: string, type: string): void {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}
