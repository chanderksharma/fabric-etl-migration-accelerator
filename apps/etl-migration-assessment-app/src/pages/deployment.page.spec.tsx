import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DeploymentPage } from "@/pages/deployment.page";

const mocks = vi.hoisted(() => ({
  configuration: vi.fn(),
  preview: vi.fn(),
  dispatch: vi.fn(),
}));

vi.mock("@/hooks/assessment-run.context", () => ({
  useAssessmentRunContext: () => ({
    activeRunId: "11111111-1111-4111-8111-111111111111",
    runs: [{
      runId: "11111111-1111-4111-8111-111111111111",
      runLabel: "Confirmed",
      startedAtUtc: "2026-11-23T00:00:00Z",
      completedAtUtc: "2026-11-23T00:01:00Z",
      workflowCount: 1,
      failedCount: 0,
      skippedCount: 0,
      rulesVersion: "1.4.0",
      inputPath: "app-intake/run-1",
      routingBasis: "compiler_confirmed",
    }],
    refreshRuns: vi.fn(),
  }),
}));

vi.mock("@/hooks/use-semantic-model-query", () => ({
  useSemanticModelQuery: () => ({
    data: { status: "success", table: {} },
    isLoading: false,
    error: undefined,
  }),
}));

vi.mock("@/lib/to-data-table", () => ({
  toDataTable: () => ({
    columns: [
      { name: "WorkflowPath" },
      { name: "SourcePlatform" },
      { name: "NativeId" },
      { name: "RecommendedTarget" },
      { name: "MigrationWave" },
      { name: "ComplexityScore" },
    ],
    rows: [["orders.yxmd", "alteryx", "", "Dataflow Gen2", "Wave 1", 9]],
  }),
}));

vi.mock("@/lib/rayfin-client", () => ({
  getRayfinClient: () => ({
    functions: {
      getDeploymentConfiguration: { invoke: mocks.configuration },
      previewDeployment: { invoke: mocks.preview },
      dispatchDeployment: { invoke: mocks.dispatch },
      startFabricFit: { invoke: vi.fn() },
      getAssessmentStatus: { invoke: vi.fn() },
    },
  }),
}));

describe("DeploymentPage", () => {
  beforeEach(() => {
    sessionStorage.clear();
    mocks.configuration.mockReset();
    mocks.preview.mockReset();
    mocks.dispatch.mockReset();
  });

  it("always shows the trigger and explains why preview is blocked", async () => {
    mocks.configuration.mockResolvedValue({
      githubConfigured: false,
      gitlabConfigured: false,
    });

    render(<DeploymentPage preselectedWorkflowPath="orders.yxmd" />);

    expect(screen.getByRole("button", { name: "Trigger GitHub Actions" }))
      .toBeDisabled();
    expect(await screen.findByText("GitHub Actions server-side secrets"))
      .toBeInTheDocument();
    expect(screen.getByText("Configure GITHUB_TOKEN and GITHUB_ALLOWED_REPOSITORIES."))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview manifest" })).toBeDisabled();
  });

  it("enables the provider trigger only after preview review and confirmation", async () => {
    mocks.configuration.mockResolvedValue({
      githubConfigured: true,
      gitlabConfigured: false,
    });
    mocks.preview.mockResolvedValue({
      manifest: {
        version: 1,
        provider: "github",
        repository: "owner/repository",
        ref: "main",
        conflictBehavior: "Update",
        selections: [{
          workflowPath: "orders.yxmd",
          artifactPath: "orders",
          target: "dataflow",
        }],
        expiresAt: "2026-11-23T01:00:00Z",
      },
      confirmationToken: "token",
    });

    render(<DeploymentPage preselectedWorkflowPath="orders.yxmd" />);
    fireEvent.change(screen.getByRole("textbox", { name: "GitHub repository URL" }), {
      target: { value: "https://github.com/owner/repository" },
    });

    const preview = await screen.findByRole("button", { name: "Preview manifest" });
    await waitFor(() => expect(preview).toBeEnabled());
    fireEvent.click(preview);
    fireEvent.click(await screen.findByRole("checkbox", {
      name: /I reviewed the provider/,
    }));

    await waitFor(() => expect(
      screen.getByRole("button", { name: "Trigger GitHub Actions" }),
    ).toBeEnabled());
  });

  it("shows only the applicable Dataflow Gen2 target, validates URLs client-side, and isolates provider URLs", async () => {
    mocks.configuration.mockResolvedValue({
      githubConfigured: true,
      gitlabConfigured: true,
    });

    render(<DeploymentPage preselectedWorkflowPath="orders.yxmd" />);

    expect(screen.getByText("Deployment target:")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /Deployment target for orders\.yxmd/ }))
      .not.toBeInTheDocument();

    const urlInput = screen.getByRole("textbox", { name: "GitHub repository URL" });
    fireEvent.change(urlInput, { target: { value: "not-a-valid-url" } });
    const preview = await screen.findByRole("button", { name: "Preview manifest" });
    await waitFor(() => expect(preview).toBeEnabled());
    fireEvent.click(preview);

    expect(await screen.findByRole("status")).toHaveTextContent(
      /Use an HTTPS GitHub repository URL/,
    );
    expect(mocks.preview).not.toHaveBeenCalled();

    fireEvent.change(urlInput, { target: { value: "https://github.com/owner/repository" } });
    fireEvent.change(screen.getByRole("combobox", { name: "CI/CD provider" }), {
      target: { value: "gitlab" },
    });
    expect(screen.getByRole("textbox", { name: "GitLab project URL" })).toHaveValue("");
    fireEvent.change(screen.getByRole("textbox", { name: "GitLab project URL" }), {
      target: { value: "https://gitlab.com/group/project" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "CI/CD provider" }), {
      target: { value: "github" },
    });
    expect(screen.getByRole("textbox", { name: "GitHub repository URL" }))
      .toHaveValue("https://github.com/owner/repository");
  });
});
