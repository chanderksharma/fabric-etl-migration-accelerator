// @vitest-environment node
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";
import { afterAll, describe, expect, it } from "vitest";

const html = readFileSync(new URL("../../portable/alteryx-portfolio.html", import.meta.url), "utf8");
const { window } = new JSDOM(html, { runScripts: "outside-only" });
const script = window.document.querySelector("script").textContent;
const { assess, assessPowerCenter, assessIdmc, classifyExportFolder, comparePythonReport, csvCell, workflowDiagram, showPlanningFor, targetWithReport } = window.eval(
  `${script}\n({ assess, assessPowerCenter, assessIdmc, classifyExportFolder, comparePythonReport, csvCell, workflowDiagram,
    showPlanningFor(rows) { results = rows; renderPlanningViews(); },
    targetWithReport(row, matches) {
      pythonMatches = matches;
      try { return recommendedTarget(row); } finally { pythonMatches = new Map(); }
    } });`,
);
const fixtures = new URL("../../../tests/fixtures/", import.meta.url);

afterAll(() => window.close());

describe("offline Alteryx portfolio", () => {
  it("omits Capacity Planning from navigation while keeping Migration Plan available", () => {
    const doc = window.document;
    expect(doc.querySelector(".nav").textContent).not.toContain("Capacity Planning");
    const plan = doc.querySelector(".nav [data-page=migration-plan]");
    plan.click();
    expect(doc.querySelector("#migration-plan").hidden).toBe(false);
  });

  it("shows portfolio and workflow empty states before returning to intake", () => {
    const doc = window.document;
    for (const [page, label] of [["portfolio", "Portfolio"], ["workflows", "Workflows"], ["intake", "New Assessment"]]) {
      const button = doc.querySelector(`.nav [data-page="${page}"]`);
      button.click();
      expect(button.getAttribute("aria-current")).toBe("page");
      expect(doc.querySelector("#current-page").textContent).toBe(label);
      expect(doc.activeElement.id).toBe(`${page}-title`);
      expect([...doc.querySelectorAll(".content > section:not([hidden])")].map(node => node.id)).toEqual([page]);
    }
    expect(doc.querySelector("#portfolio-empty").hidden).toBe(false);
    expect(doc.querySelector("#workflow-results").hidden).toBe(true);
  });

  it("uses the selected intake mode to open the corresponding picker", () => {
    const doc = window.document;
    const browse = doc.querySelector("#browse");
    const picked = [];
    for (const id of ["files", "idmc-folder"]) {
      doc.getElementById(id).addEventListener("click", () => picked.push(id), { once: true });
    }
    browse.click();
    doc.querySelector("#intake-informatica").click();
    doc.querySelector("#mode-folder").click();
    expect(doc.querySelector("#intake-hint").textContent).toContain("manifest.json");
    expect(browse.textContent).toBe("Browse folder");
    browse.click();
    expect(picked).toEqual(["files", "idmc-folder"]);
    doc.querySelector("#intake-alteryx").click();
    doc.querySelector("#mode-files").click();
  });

  it("filters migration backlog by wave and toggles back to all assets", () => {
    const doc = window.document;
    showPlanningFor([
      assess("simple.yxmd", '<AlteryxDocument><Node ToolID="1"><GuiSettings Plugin="AlteryxBasePluginsGui.Filter.Filter"/></Node></AlteryxDocument>'),
      assess("redesign.yxmd", '<AlteryxDocument><Node ToolID="2"/></AlteryxDocument>'),
    ]);
    const redesign = doc.querySelector("#plan-waves [data-wave=Redesign]");
    redesign.click();
    expect(doc.querySelector("#plan-backlog tbody").textContent).toContain("redesign.yxmd");
    expect(doc.querySelector("#plan-backlog tbody").textContent).not.toContain("simple.yxmd");
    redesign.click();
    expect(doc.querySelector("#plan-backlog tbody").textContent).toContain("simple.yxmd");
  });

  it("resets evidence pagination when the active register changes", () => {
    const doc = window.document;
    showPlanningFor(Array.from({ length: 26 }, (_, index) =>
      assess(`workflow-${index}.yxmd`, '<AlteryxDocument><Node ToolID="1"><GuiSettings Plugin="AlteryxBasePluginsGui.Filter.Filter"/></Node></AlteryxDocument>')));
    doc.querySelector("#evidence-next").click();
    expect(doc.querySelector("#evidence-register tbody").textContent).toContain("workflow-25.yxmd");
    expect(doc.querySelector("#evidence-register tbody").textContent).not.toContain("workflow-0.yxmd");
    [...doc.querySelectorAll("#register-controls button")].find(button => button.textContent === "Expressions").click();
    expect(doc.querySelector("#evidence-register tbody").textContent).toContain("workflow-0.yxmd");
  });

  it("counts active tools and links, excluding disabled subtrees and config metadata", () => {
    const xml = `<AlteryxDocument><Nodes>
      <Node ToolID="1"><GuiSettings Plugin="AlteryxBasePluginsGui.Filter.Filter"/></Node>
      <Node ToolID="2"><GuiSettings Plugin="Custom.Transform.Transform"/></Node>
      <Node ToolID="3">
        <Properties><Configuration><Disabled value="True"/><Node/></Configuration></Properties>
        <ChildNodes><Node ToolID="4"/></ChildNodes>
      </Node>
    </Nodes><Connections>
      <Connection><Origin ToolID="1"/><Destination ToolID="2"/></Connection>
      <Connection><Origin ToolID="2"/><Destination ToolID="4"/></Connection>
    </Connections></AlteryxDocument>`;
    expect(assess("sample.yxmd", xml)).toMatchObject({
      tools: 2, connections: 1, score: 8, band: "Low", target: "Dataflow Gen2",
      wave: "Wave 1", manual: ["Transform"],
    });
  });

  it("rejects unsafe declarations and links to nonexistent tools", () => {
    expect(() => assess("sample.yxmd", "<!DOCTYPE AlteryxDocument><AlteryxDocument/>"))
      .toThrow("DTD and entity declarations");
    const xml = `<AlteryxDocument><Node ToolID="1"/><Connection>
      <Origin ToolID="1"/><Destination ToolID="2"/>
    </Connection></AlteryxDocument>`;
    expect(() => assess("sample.yxmd", xml)).toThrow("unknown ToolID");
  });

  it("counts source evidence without including raw references or expressions", () => {
    const row = assess("evidence.yxmd", `<AlteryxDocument>
      <Node ToolID="1"><EngineSettings Macro="private-macro.yxmc"/>
        <Properties><Configuration><File>private-source.csv</File>
          <Expression>private-expression</Expression></Configuration></Properties>
      </Node>
      <Events><Enabled value="unknown"/></Events>
    </AlteryxDocument>`);
    expect(row.evidence).toMatchObject({ macros: 1, fileRefs: 1, expressions: 1 });
    expect(row.evidence.findings).toContain("Workflow events are configured or ambiguous. Review side effects before any pilot.");
    expect(JSON.stringify(row)).not.toContain("private-");
  });

  it("draws the assessed branches and identifies steps requiring manual review", () => {
    const row = assess("fork.yxmd", `<AlteryxDocument>
      <Node ToolID="1"><GuiSettings Plugin="AlteryxBasePluginsGui.Filter.Filter"/></Node>
      <Node ToolID="2"><GuiSettings Plugin="AlteryxBasePluginsGui.Sort.Sort"/></Node>
      <Node ToolID="3"><GuiSettings Plugin="Custom.Manual.Manual"/></Node>
      <Connection><Origin ToolID="1"/><Destination ToolID="2"/></Connection>
      <Connection><Origin ToolID="1"/><Destination ToolID="3"/></Connection>
    </AlteryxDocument>`);
    const source = workflowDiagram(row);
    const design = workflowDiagram(row, true);
    const routes = figure => [...figure.querySelectorAll("path.connector")].map(path => path.getAttribute("d"));
    expect(source.querySelectorAll("svg g")).toHaveLength(3);
    expect(new Set(routes(source)).size).toBe(2);
    expect(routes(design)).toEqual(routes(source));
    expect(design.querySelectorAll("g.manual")).toHaveLength(1);
    expect(design.querySelector("g.manual .graph-note").textContent).toBe("Manual review");
    expect(design.querySelector("figcaption").textContent).toContain("not an executable Fabric design");
  });

  it("explains when a source graph has no active tools", () => {
    const row = assess("empty.yxmd", "<AlteryxDocument/>");
    expect(workflowDiagram(row).textContent).toBe("No active tools to draw.");
  });

  it("exports workflow names as data rather than spreadsheet formulas", () => {
    expect(csvCell(' =Example "copy".yxmd')).toBe(`"' =Example ""copy"".yxmd"`);
  });

  it("explains manual review without replacing the offline target or wave", () => {
    const row = assess("manual.yxmd", '<AlteryxDocument><Node ToolID="1"/></AlteryxDocument>');
    expect(row).toMatchObject({
      target: "Manual rework", wave: "Redesign",
      readiness: { label: "Review required", reasons: ["1 component type(s) need manual mapping review."] },
    });
    expect(row).not.toHaveProperty("effort");
  });

  it("uses Notebook for Append Fields and recognizes Dataflow-compatible regex in an XML attribute", () => {
    const xml = (tool, configuration) => `<AlteryxDocument><Node ToolID="1">
      <GuiSettings Plugin="AlteryxBasePluginsGui.${tool}.${tool}"/>
      <Properties><Configuration>${configuration}</Configuration></Properties>
      </Node></AlteryxDocument>`;
    expect(assess("append.yxmd", xml("AppendFields", "")).offlineRouting.target).toBe("Fabric Notebook");
    const regex = '<RegExExpression value="([A-Z]+)-([0-9]+)"/><ParseComplex><Field/><Field/></ParseComplex>';
    expect(assess("regex.yxmd", xml("RegEx", regex)).offlineRouting.target).toBe("Dataflow Gen2");
  });

  it("requires matching fingerprints, asset identity, and baseline metrics before importing a comparison", () => {
    const xml = readFileSync(new URL("powercenter/basic_repository.xml", fixtures), "utf8");
    const [row] = assessPowerCenter("locally-renamed.xml", xml);
    row.sourceHash = "ab".repeat(32);
    const workflow = { display_path: "repository.xml", sha256: row.sourceHash };
    const assessment = {
      path: "repository.xml!Sales/wf_orders", source_platform: "informatica_powercenter",
      asset_type: "workflow", native_id: "wf_orders", folder: "Sales",
      tool_count: 6, connection_count: 4, complexity_score: 12, complexity_band: "Low",
      rules_version: "1.4.0", registry_version: "2026.11.3", recommended_target: "Dataflow Gen2",
      migration_wave: "Pilot", estimated_effort_days: 0.5,
    };
    const report = { workflows: [workflow], assessments: [assessment] };
    expect(comparePythonReport(report, [row]).matches.get(row))
      .toEqual({ target: "Dataflow Gen2", wave: "Pilot" });
    const { estimated_effort_days: _ignored, ...withoutEffort } = assessment;
    expect(comparePythonReport({ ...report, assessments: [withoutEffort] }, [row]).matches.size).toBe(1);
    const override = { ...report, assessments: [{ ...assessment, recommended_target: "Fabric Notebook" }] };
    expect(targetWithReport(row, comparePythonReport(override, [row]).matches)).toEqual({
      target: "Fabric Notebook", source: "Imported Python report",
    });
    expect(targetWithReport(row, new Map())).toEqual({
      target: "Dataflow Gen2", source: "Offline routing rules",
    });
    expect(row.target).toBe("Mixed Fabric solution");
    for (const change of [{ native_id: "other" }, { complexity_score: 19 }, { rules_version: "1.0.0" }]) {
      expect(comparePythonReport({ ...report, assessments: [{ ...assessment, ...change }] }, [row]).matches.size).toBe(0);
    }
    expect(comparePythonReport(report, [{ ...row, sourceHash: "cd".repeat(32) }]).matches.size).toBe(0);
    expect(comparePythonReport({ ...report, assessments: [assessment, assessment] }, [row]).matches.size).toBe(0);
  });

  it("assesses a standard PowerCenter export and its linked session mapping without loading the DTD", () => {
    const xml = readFileSync(new URL("powercenter/basic_repository.xml", fixtures), "utf8");
    const rows = assessPowerCenter("repository.xml", xml);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      platform: "PowerCenter", assetType: "Workflow", tools: 6, connections: 4, score: 12,
      offlineRouting: { target: "Dataflow Gen2" },
      target: "Mixed Fabric solution", evidence: { dependencies: 1, expressions: 1 },
    });
    expect(JSON.stringify(rows)).not.toContain("Amount");
    expect(() => assessPowerCenter("repository.xml", xml.replace('"powrmart.dtd"', '"other.dtd"')))
      .toThrow("DTD and entity declarations");
  });

  it("uses nested PowerCenter XML from a folder without an IDMC manifest", () => {
    const repository = { name: "workflow.XML", webkitRelativePath: "Exports/PowerCenter/workflow.XML" };
    const archive = { name: "workflow.zip", webkitRelativePath: "Exports/workflow.zip" };
    expect(classifyExportFolder([repository, archive])).toEqual({
      idmcFiles: [], workflowFiles: [repository], issue: "",
    });
  });

  it("keeps IDMC folder import and explains when its manifest is nested", () => {
    const file = webkitRelativePath => ({ name: "manifest.json", webkitRelativePath });
    const root = file("Exports/manifest.json");
    expect(classifyExportFolder([root]).idmcFiles).toEqual([root]);
    expect(classifyExportFolder([file("Exports/IDMC/manifest.json")]).issue)
      .toContain("subfolder that directly contains manifest.json");
  });

  it("assesses the extracted IDMC package and reports an invalid manifest entry without losing valid assets", async () => {
    const folder = fileURLToPath(new URL("idmc/basic_export/", fixtures));
    const files = readdirSync(folder, { recursive: true, withFileTypes: true })
      .filter(entry => entry.isFile())
      .map(entry => {
        const path = join(entry.parentPath, entry.name);
        const relative = path.slice(folder.length).replaceAll("\\", "/");
        const original = readFileSync(path, "utf8");
        const manifest = entry.name === "manifest.json" ? JSON.parse(original) : null;
        if (manifest) manifest.assets.push({ path: "../outside" });
        return {
          name: entry.name, size: Buffer.byteLength(original), webkitRelativePath: `export/${relative}`,
          arrayBuffer: async () => new TextEncoder().encode(manifest ? JSON.stringify(manifest) : original).buffer,
        };
      });
    window.TextDecoder = TextDecoder;
    const issues = [];
    const rows = await assessIdmc(files, issue => issues.push(issue));
    expect(rows.map(row => [row.platform, row.assetType, row.evidence.dependencies])).toEqual([
      ["IDMC", "Mapping", 0], ["IDMC", "Mapping task", 1], ["IDMC", "Taskflow", 0],
    ]);
    expect(rows[0].connections).toBeGreaterThan(0);
    expect(issues).toEqual(["IDMC manifest asset 4: Invalid asset path in manifest."]);
  });
});
