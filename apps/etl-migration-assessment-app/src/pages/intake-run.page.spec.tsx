import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { IntakeRunPage } from "@/pages/intake-run.page";

const mocks = vi.hoisted(() => ({
  uploadWorkflow: vi.fn(),
  startAssessment: vi.fn(),
  getAssessmentStatus: vi.fn(),
  cancelAssessment: vi.fn(),
  refreshRuns: vi.fn(),
}));

vi.mock("@/lib/rayfin-client", () => ({
  getRayfinClient: () => ({
    functions: {
      uploadWorkflow: { invoke: mocks.uploadWorkflow },
      startAssessment: { invoke: mocks.startAssessment },
      getAssessmentStatus: { invoke: mocks.getAssessmentStatus },
      cancelAssessment: { invoke: mocks.cancelAssessment },
    },
  }),
}));

vi.mock("@/hooks/assessment-run.context", () => ({
  useAssessmentRunContext: () => ({
    refreshRuns: mocks.refreshRuns,
  }),
}));

describe("IntakeRunPage", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mocks.uploadWorkflow.mockReset();
    mocks.startAssessment.mockReset();
    mocks.getAssessmentStatus.mockReset();
    mocks.cancelAssessment.mockReset();
    mocks.refreshRuns.mockReset().mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("uses a fresh intake folder per upload batch and selects the latest completed run", async () => {
    mocks.uploadWorkflow
      .mockRejectedValueOnce(new Error("Transient upload failure"))
      .mockResolvedValueOnce({ fileName: "flow.yxmd", inputPath: "app-intake/run-2", size: 12 });
    mocks.startAssessment.mockResolvedValue({
      jobInstanceId: "11111111-1111-1111-1111-111111111111",
      statusUrl: "https://api.fabric.microsoft.com/status",
    });
    mocks.getAssessmentStatus.mockResolvedValue({ status: "Completed" });

    render(<IntakeRunPage />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["<AlteryxDocument/>"], "flow.yxmd", { type: "text/xml" });
    Object.defineProperty(file, "arrayBuffer", {
      value: async () => new TextEncoder().encode("<AlteryxDocument/>").buffer,
    });
    fireEvent.change(input, { target: { files: [file] } });

    fireEvent.click(screen.getByRole("button", { name: "Stage files" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Transient upload failure"));

    fireEvent.click(screen.getByRole("button", { name: "Stage files" }));
    fireEvent.click(await screen.findByRole("checkbox"));
    expect(screen.getByRole("button", { name: "Run assessment" })).toBeEnabled();

    const firstFolder = mocks.uploadWorkflow.mock.calls[0][0].inputFolder;
    const secondFolder = mocks.uploadWorkflow.mock.calls[1][0].inputFolder;
    expect(secondFolder).not.toBe(firstFolder);

    fireEvent.click(screen.getByRole("button", { name: "Run assessment" }));
    await waitFor(() => expect(mocks.startAssessment).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(3_100);
    await waitFor(() => expect(mocks.refreshRuns).toHaveBeenCalledWith({ selectLatest: true }));
    expect(screen.getByText("Completed")).toBeInTheDocument();
  });

  it("surfaces notebook failureReason when an assessment run fails", async () => {
    mocks.uploadWorkflow.mockResolvedValue({
      fileName: "flow.yxmd",
      inputPath: "app-intake/run-1",
      size: 12,
    });
    mocks.startAssessment.mockResolvedValue({
      jobInstanceId: "22222222-2222-2222-2222-222222222222",
      statusUrl: "https://api.fabric.microsoft.com/status",
    });
    mocks.getAssessmentStatus.mockResolvedValue({
      status: "Failed",
      failureReason: { errorCode: "SparkError", message: "Statement failed" },
    });

    render(<IntakeRunPage />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["<AlteryxDocument/>"], "flow.yxmd", { type: "text/xml" });
    Object.defineProperty(file, "arrayBuffer", {
      value: async () => new TextEncoder().encode("<AlteryxDocument/>").buffer,
    });
    fireEvent.change(input, { target: { files: [file] } });

    fireEvent.click(screen.getByRole("button", { name: "Stage files" }));
    fireEvent.click(await screen.findByRole("checkbox"));
    expect(screen.getByRole("button", { name: "Run assessment" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Run assessment" }));
    await waitFor(() => expect(mocks.startAssessment).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(3_100);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("SparkError: Statement failed"));
  });

  it("cancels an active notebook assessment", async () => {
    mocks.uploadWorkflow.mockResolvedValue({
      fileName: "flow.yxmd",
      inputPath: "app-intake/run-1",
      size: 12,
    });
    mocks.startAssessment.mockResolvedValue({
      jobInstanceId: "33333333-3333-4333-8333-333333333333",
      statusUrl: "https://api.fabric.microsoft.com/status",
    });
    mocks.cancelAssessment.mockResolvedValue({ status: "Cancelling" });

    render(<IntakeRunPage />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["<AlteryxDocument/>"], "flow.yxmd", { type: "text/xml" });
    Object.defineProperty(file, "arrayBuffer", {
      value: async () => new TextEncoder().encode("<AlteryxDocument/>").buffer,
    });
    fireEvent.change(input, { target: { files: [file] } });

    fireEvent.click(screen.getByRole("button", { name: "Stage files" }));
    fireEvent.click(await screen.findByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Run assessment" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel assessment" }));

    await waitFor(() => expect(mocks.cancelAssessment).toHaveBeenCalledWith(
      { jobInstanceId: "33333333-3333-4333-8333-333333333333" },
      { timeoutMs: 120_000 },
    ));
    expect(screen.getByText("Cancelling")).toBeInTheDocument();
  });
});
