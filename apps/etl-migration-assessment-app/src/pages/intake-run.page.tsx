import { useEffect, useState } from "react";
import { CheckCircle2, FileUp, LoaderCircle, Play, RefreshCw, XCircle } from "lucide-react";

import { useAssessmentRunContext } from "@/hooks/assessment-run.context";
import { getRayfinClient } from "@/lib/rayfin-client";
import { PageFrame } from "@/pages/portfolio.page";

interface UploadedFile {
  fileName: string;
  size: number;
}

const terminalStatuses = new Set(["Completed", "Failed", "Cancelled", "Deduped"]);

export function IntakeRunPage({
  onOpenPortfolio,
}: {
  onOpenPortfolio?: () => void;
} = {}) {
  const { refreshRuns } = useAssessmentRunContext();
  const [files, setFiles] = useState<File[]>([]);
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([]);
  const [inputPath, setInputPath] = useState("");
  const [jobInstanceId, setJobInstanceId] = useState("");
  const [jobStatus, setJobStatus] = useState("");
  const [error, setError] = useState("");
  const [duplicateFiles, setDuplicateFiles] = useState<string[]>([]);
  const [scopeConfirmed, setScopeConfirmed] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);

  useEffect(() => {
    if (!jobInstanceId || terminalStatuses.has(jobStatus)) {
      return;
    }

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    let consecutiveErrors = 0;
    const poll = async () => {
      try {
        const status = await getRayfinClient().functions.getAssessmentStatus.invoke(
          { jobInstanceId },
          { timeoutMs: 120_000 },
        );
        if (cancelled) return;
        consecutiveErrors = 0;
        setJobStatus(status.status);
        if (status.status === "Completed") {
          await refreshRuns({ selectLatest: true });
        } else if (status.status === "Failed" || status.status === "Cancelled") {
          const reason = formatFailureReason(status.failureReason);
          if (reason) setError(reason);
        }
        if (!terminalStatuses.has(status.status)) {
          timer = setTimeout(poll, 5_000);
        }
      } catch (reason) {
        if (cancelled) return;
        consecutiveErrors += 1;
        if (consecutiveErrors < 3) {
          timer = setTimeout(poll, 5_000);
        } else {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      }
    };
    timer = setTimeout(poll, 3_000);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [jobInstanceId, jobStatus, refreshRuns]);

  const upload = async () => {
    setError("");
    setIsUploading(true);
    setUploadedFiles([]);
    setDuplicateFiles([]);
    setScopeConfirmed(false);
    setInputPath("");
    const batchFolder = `run-${Date.now().toString(36)}-${crypto.randomUUID().slice(0, 8)}`;
    try {
      if (files.length > 100) {
        throw new Error("Select no more than 100 files per assessment batch.");
      }
      const totalBytes = files.reduce((total, file) => total + file.size, 0);
      if (totalBytes > 100 * 1024 * 1024) {
        throw new Error("The assessment batch exceeds the 100 MiB staging limit.");
      }
      const families = new Set(
        files.map(fileFamily).filter((family): family is string => family !== null),
      );
      if (families.size > 1) {
        throw new Error("Stage one source family at a time: Alteryx, PowerCenter, or IDMC.");
      }

      const results: UploadedFile[] = [];
      const seenHashes = new Set<string>();
      const duplicates: string[] = [];
      let stagedPath = "";
      for (const file of files) {
        if (file.size > 3 * 1024 * 1024) {
          throw new Error(`${file.name} exceeds the 3 MiB upload limit.`);
        }
        const content = await file.arrayBuffer();
        const digest = bytesToHex(await crypto.subtle.digest("SHA-256", content));
        if (seenHashes.has(digest)) {
          duplicates.push(file.name);
          continue;
        }
        seenHashes.add(digest);
        const result = await getRayfinClient().functions.uploadWorkflow.invoke(
          {
            fileName: file.name,
            contentBase64: bytesToBase64(new Uint8Array(content)),
            inputFolder: batchFolder,
          },
          { timeoutMs: 250_000 },
        );
        stagedPath = result.inputPath;
        results.push({ fileName: result.fileName, size: result.size });
      }
      setUploadedFiles(results);
      setDuplicateFiles(duplicates);
      setInputPath(stagedPath);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setIsUploading(false);
    }
  };

  const cancel = async () => {
    if (!jobInstanceId) return;
    setError("");
    setIsCancelling(true);
    try {
      const result = await getRayfinClient().functions.cancelAssessment.invoke(
        { jobInstanceId },
        { timeoutMs: 120_000 },
      );
      setJobStatus(result.status);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setIsCancelling(false);
    }
  };

  const start = async () => {
    setError("");
    setIsStarting(true);
    try {
      const result = await getRayfinClient().functions.startAssessment.invoke(
        { inputPath },
        { timeoutMs: 120_000 },
      );
      setJobInstanceId(result.jobInstanceId);
      setJobStatus("Submitted");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setIsStarting(false);
    }
  };

  return (
    <PageFrame
      title="Intake and run"
      subtitle="Stage approved workflow exports in OneLake and start the governed assessment notebook."
    >
      <div className="grid gap-(--grid-gap) xl:grid-cols-5">
        <section className="rounded-xl border bg-card p-6 shadow-container-2 xl:col-span-3">
          <div className="flex items-start gap-3">
            <FileUp className="icon-size-400 text-brand-foreground" aria-hidden="true" />
            <div>
              <h2 className="font-visual-title text-visual-title font-semibold">Upload workflow exports</h2>
              <p className="mt-1 text-300 text-muted-foreground">
                Supported files: Alteryx (YXMD, YXMC, YXWZ, YXZP), PowerCenter XML, IDMC JSON, and ZIP packages. Maximum 3 MiB per file.
              </p>
            </div>
          </div>
          <input
            className="mt-6 block w-full rounded-lg border bg-background p-3 text-300 focus:outline-none focus:ring-2 focus:ring-ring"
            type="file"
            multiple
            accept=".yxmd,.yxmc,.yxwz,.yxzp,.xml,.json,.zip"
            onChange={(event) => {
              setFiles(Array.from(event.target.files ?? []));
              setUploadedFiles([]);
              setDuplicateFiles([]);
              setInputPath("");
              setScopeConfirmed(false);
              setJobInstanceId("");
              setJobStatus("");
              setError("");
            }}
          />
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              className="inline-flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-300 font-semibold text-on-brand focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              type="button"
              disabled={files.length === 0 || isUploading}
              onClick={() => void upload()}
            >
              {isUploading ? <LoaderCircle className="icon-size-200 animate-spin" /> : <FileUp className="icon-size-200" />}
              Stage files
            </button>
            <span className="text-200 text-muted-foreground">
              {files.length ? `${files.length} file${files.length === 1 ? "" : "s"} selected` : "No files selected"}
            </span>
          </div>
          {uploadedFiles.length > 0 && (
            <>
              <div className="mt-5 rounded-lg border p-4">
                <h3 className="font-semibold">Staged scope preview</h3>
                <p className="mt-1 text-200 text-muted-foreground">
                  {uploadedFiles.length} unique file{uploadedFiles.length === 1 ? "" : "s"} staged
                  {duplicateFiles.length
                    ? `; ${duplicateFiles.length} duplicate${duplicateFiles.length === 1 ? "" : "s"} skipped`
                    : "; no duplicate content detected"}.
                </p>
                <ul className="mt-3 space-y-2" aria-label="Staged files">
                  {uploadedFiles.map((file) => (
                    <li key={file.fileName} className="flex items-center justify-between rounded-lg bg-muted px-3 py-2 text-200">
                      <span>{file.fileName}</span>
                      <span className="text-muted-foreground">{formatBytes(file.size)}</span>
                    </li>
                  ))}
                </ul>
                {duplicateFiles.length > 0 && (
                  <p className="mt-3 text-200 text-muted-foreground">
                    Skipped duplicates: {duplicateFiles.join(", ")}
                  </p>
                )}
              </div>
              <label className="mt-4 flex items-start gap-3 rounded-lg border border-brand p-4 text-200">
                <input
                  className="mt-1"
                  type="checkbox"
                  checked={scopeConfirmed}
                  onChange={(event) => setScopeConfirmed(event.target.checked)}
                />
                <span>
                  I reviewed the staged file scope. The notebook will perform bounded discovery,
                  fingerprint verification, and static assessment without generating code.
                </span>
              </label>
            </>
          )}
        </section>

        <section className="rounded-xl border bg-card p-6 shadow-container-2 xl:col-span-2">
          <h2 className="font-visual-title text-visual-title font-semibold">Assessment run</h2>
          <p className="mt-1 text-300 text-muted-foreground">
            The notebook validates fingerprints, assesses the staged folder, and persists a new latest-completed run.
          </p>
          <button
            className="mt-6 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-brand px-4 py-3 text-300 font-semibold text-on-brand focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
            type="button"
            disabled={!inputPath || !scopeConfirmed || isStarting || Boolean(jobInstanceId && !terminalStatuses.has(jobStatus))}
            onClick={() => void start()}
          >
            {isStarting ? <LoaderCircle className="icon-size-200 animate-spin" /> : <Play className="icon-size-200" />}
            Run assessment
          </button>
          {jobInstanceId && !terminalStatuses.has(jobStatus) && (
            <button
              className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-lg border px-4 py-3 text-300 font-semibold hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50"
              type="button"
              disabled={isCancelling}
              onClick={() => void cancel()}
            >
              {isCancelling ? <LoaderCircle className="icon-size-200 animate-spin" /> : <XCircle className="icon-size-200" />}
              Cancel assessment
            </button>
          )}
          <div className="mt-6 rounded-lg bg-muted p-4">
            <p className="text-200 text-muted-foreground">Status</p>
            <div className="mt-2 flex items-center gap-2 font-semibold">
              {jobStatus === "Completed" ? (
                <CheckCircle2 className="icon-size-200 text-success" />
              ) : jobStatus === "Failed" || jobStatus === "Cancelled" ? (
                <XCircle className="icon-size-200 text-destructive" />
              ) : jobStatus ? (
                <RefreshCw className="icon-size-200 animate-spin text-brand-foreground" />
              ) : null}
              <span>{jobStatus || "Waiting for staged files"}</span>
            </div>
            {jobInstanceId && <p className="mt-2 break-all font-monospace text-100 text-muted-foreground">{jobInstanceId}</p>}
            {jobStatus === "Completed" && onOpenPortfolio && (
              <button
                type="button"
                className="mt-4 inline-flex w-full items-center justify-center rounded-lg border bg-background px-4 py-2 text-200 font-semibold hover:bg-hover"
                onClick={onOpenPortfolio}
              >
                View Portfolio →
              </button>
            )}
          </div>
        </section>
      </div>
      {error && (
        <div role="alert" className="rounded-xl border border-destructive bg-card p-4 text-destructive">
          {error}
        </div>
      )}
    </PageFrame>
  );
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunkSize = 32_768;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

function bytesToHex(buffer: ArrayBuffer): string {
  return [...new Uint8Array(buffer)]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

function fileFamily(file: File): string | null {
  const extension = file.name.toLowerCase().split(".").at(-1);
  if (["yxmd", "yxmc", "yxwz", "yxzp"].includes(extension ?? "")) return "alteryx";
  if (extension === "xml") return "powercenter";
  if (extension === "json") return "idmc";
  return null;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

function formatFailureReason(reason: unknown): string {
  if (!reason) return "";
  if (typeof reason === "string") return reason;
  if (typeof reason === "object") {
    const record = reason as Record<string, unknown>;
    if (typeof record.message === "string" && record.message) {
      return typeof record.errorCode === "string" && record.errorCode
        ? `${record.errorCode}: ${record.message}`
        : record.message;
    }
    return JSON.stringify(reason);
  }
  return String(reason);
}
