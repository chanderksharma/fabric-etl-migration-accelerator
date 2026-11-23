import { describe, expect, it, vi } from "vitest";

import { downloadCsv, formulaSafe } from "@/lib/download";

describe("download helpers", () => {
  it("defuses spreadsheet formulas", () => {
    expect(formulaSafe("=SUM(A1:A2)")).toBe("'=SUM(A1:A2)");
    expect(formulaSafe(" @command")).toBe("' @command");
    expect(formulaSafe("normal")).toBe("normal");
  });

  it("creates a quoted CSV download", () => {
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    downloadCsv("workflows.csv", ["Name", "Value"], [
      { Name: "Orders", Value: "=danger" },
    ]);

    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:test");
  });
});
