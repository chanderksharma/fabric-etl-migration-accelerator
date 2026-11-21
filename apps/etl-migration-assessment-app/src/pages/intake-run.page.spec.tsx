import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { IntakeRunPage } from "@/pages/intake-run.page";

const mocks = vi.hoisted(() => ({
  uploadWorkflow: vi.fn(),
  startAssessment: vi.fn(),
  getAssessmentStatus: vi.fn(),
  clearQueryCache: vi.fn(),
}));

vi.mock("@/lib/rayfin-client", () => ({
  getRayfinClient: () => ({
    functions: {
      uploadWorkflow: { invoke: mocks.uploadWorkflow },
      startAssessment: { invoke: mocks.startAssessment },
      getAssessmentStatus: { invoke: mocks.getAssessmentStatus },
    },
  }),
}));

vi.mock("@/hooks/use-semantic-model-query", () => ({
  clearQueryCache: mocks.clearQueryCache,
}));

describe("IntakeRunPage", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mocks.uploadWorkflow.mockReset();
    mocks.startAssessment.mockReset();
    mocks.getAssessmentStatus.mockReset();
    mocks.clearQueryCache.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("uses a fresh intake folder per upload batch and invalidates cached queries when a run completes", async () => {
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
    await waitFor(() => expect(screen.getByRole("button", { name: "Run assessment" })).toBeEnabled());

    const firstFolder = mocks.uploadWorkflow.mock.calls[0][0].inputFolder;
    const secondFolder = mocks.uploadWorkflow.mock.calls[1][0].inputFolder;
    expect(secondFolder).not.toBe(firstFolder);

    fireEvent.click(screen.getByRole("button", { name: "Run assessment" }));
    await waitFor(() => expect(mocks.startAssessment).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(3_100);
    await waitFor(() => expect(mocks.clearQueryCache).toHaveBeenCalledWith("assessmentmodel"));
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
    await waitFor(() => expect(screen.getByRole("button", { name: "Run assessment" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Run assessment" }));
    await waitFor(() => expect(mocks.startAssessment).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(3_100);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("SparkError: Statement failed"));
  });
});
