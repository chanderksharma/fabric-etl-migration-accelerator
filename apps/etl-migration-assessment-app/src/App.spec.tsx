//-----------------------------------------------------------------------
// <copyright company="Microsoft Corporation">
//        Copyright (c) Microsoft Corporation.  All rights reserved.
//        Licensed under the MIT license. See LICENSE file in the project root for full license information.
// </copyright>
//-----------------------------------------------------------------------

import { type ReactNode } from "react";
import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import App from "@/App";

const selectRun = vi.hoisted(() => vi.fn());

vi.mock("@/hooks/theme.context", () => ({
    useThemeContext: () => ({ isDark: false, toggleTheme: vi.fn(), theme: {} }),
}));

vi.mock("@/hooks/assessment-run.context", () => ({
    useAssessmentRunContext: () => ({
        activeRunId: null,
        runs: [{
            runId: "8f50f18a-ae85-4be6-9224-35f4f4ce526b",
            runLabel: "Assessment 42",
            startedAtUtc: "2026-11-21T08:00:00Z",
            completedAtUtc: "2026-11-21T08:10:00Z",
            workflowCount: 42,
            failedCount: 0,
            skippedCount: 0,
            rulesVersion: "1.0.0",
        }],
        isLoading: false,
        revision: 0,
        selectRun,
        refreshRuns: vi.fn(),
    }),
}));

vi.mock("@/hooks/use-assessment-run", () => ({
    AssessmentRunProvider: ({ children }: { children: ReactNode }) => children,
}));

vi.mock("@/hooks/use-semantic-model-query", () => ({
    useSemanticModelQuery: () => ({
        data: undefined,
        isLoading: true,
        error: undefined,
        refetch: vi.fn(),
    }),
}));

describe("App", () => {
    it("renders without throwing", () => {
        expect(() => render(<App />)).not.toThrow();
    });

    it("mounts content into the document", () => {
        render(<App />);
        expect(document.body).not.toBeEmptyDOMElement();
    });

    it("allows users to scope the application to a retained assessment run", () => {
        render(<App />);

        fireEvent.change(screen.getByRole("combobox", { name: "Assessment run" }), {
            target: { value: "8f50f18a-ae85-4be6-9224-35f4f4ce526b" },
        });

        expect(selectRun).toHaveBeenCalledWith("8f50f18a-ae85-4be6-9224-35f4f4ce526b");
    });
});
