import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { AssessmentResult, Candidate, Page, RunResult } from "./App";
import type { WorkflowEvidence } from "./evidence-types";
import { SourceGraph } from "./SourceGraph";
import { Deployment } from "./workspace-deployment";
import { CapacityPlanning } from "./workspace-capacity";
import { useCapacity } from "./use-capacity";
import { useEvidence } from "./workspace-evidence";
import {
  evidenceTabs,
  graphShape,
  nameOf,
  platformLabel,
  reviewPriority,
  statusClass,
  summarizeWaves,
  supportDetail,
  toolMappingRows,
  waveDefinitions,
  waveLabel,
} from "./workspace-model";
import {
  EvidenceRegister,
  Filters,
  Tabs,
  WorkflowTable,
} from "./workspace-registers";

type Item = AssessmentResult["assessments"][number];
type Target = "notebook" | "dataflow" | "pipeline";
type Props = {
  page: Page;
  navigate: (page: Page) => void;
  assessment: AssessmentResult | null;
  run: RunResult | null;
  runId: string | null;
  candidates: Candidate[];
  generating: boolean;
  generate: (target: Target) => Promise<void>;
  theme: string;
  toggleTheme: () => void;
  request: (path: string, init?: RequestInit) => Promise<Response>;
  children: ReactNode;
  status?: ReactNode;
};

const pages: Array<{id: Page; label: string; icon: string}> = [
  {id: "intake", label: "New Assessment", icon: "intake"},
  {id: "executive-summary", label: "Portfolio", icon: "portfolio"},
  {id: "workflows", label: "Workflows", icon: "flow"},
  {id: "migration-plan", label: "Migration Plan", icon: "plan"},
  {id: "capacity-planning", label: "Capacity Planning", icon: "capacity"},
  {id: "technical-details", label: "Technical Details", icon: "gear"},
];
const detailTabs = [
  ["summary", "Summary"], ["flow", "Source Workflow"], ["design", "Fabric design"],
  ["findings", "Risk assessment"], ["validation", "Validation"], ["deploy", "Fabric deployment"],
] as const;

function Icon({name}: {name: string}) {
  return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    {name === "intake" ? <><path d="M12 4v12"/><path d="m7 9 5-5 5 5"/><path d="M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2"/></>
      : name === "portfolio" ? <><path d="M4 20V8l8-5 8 5v12"/><path d="M8 20v-6h8v6M7 10h10"/></>
      : name === "grid" ? <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>
      : name === "flow" ? <><path d="M4 6h7M4 12h16M13 18h7"/><circle cx="14" cy="6" r="2"/><circle cx="10" cy="18" r="2"/></>
      : name === "plan" ? <><path d="M5 19V9m7 10V5m7 14v-7"/><path d="m4 7 6-4 5 5 5-4"/></>
      : name === "capacity" ? <><path d="M4 19h16M6 16l3-4 3 2 5-7"/><circle cx="17" cy="7" r="2"/></>
      : name === "moon" ? <path d="M12 3a9 9 0 1 0 9 9c0-.5 0-1-.1-1.5A7 7 0 0 1 12 3Z"/>
      : <><circle cx="12" cy="12" r="3"/><path d="M4 12h3m10 0h3M12 4v3m0 10v3"/><circle cx="12" cy="12" r="9"/></>}
  </svg>;
}

function Panel({title, note, action, children}: {title: string; note?: string; action?: ReactNode; children: ReactNode}) {
  return <div className="panel"><div className="panel-header"><div><h2>{title}</h2>{note && <p>{note}</p>}</div>{action}</div>{children}</div>;
}

function Bars({rows, total}: {rows: Array<{name: string; value: number; color?: string}>; total: number}) {
  return <div className="readiness">{rows.map(row => <div className="bar-row" key={row.name}>
    <div className="bar-label">{row.color && <span className={`dot ${row.color}`}/>} {row.name}</div>
    <div className="bar-track"><div className={`bar-fill ${row.color ?? ""}`} style={{width: `${total ? row.value / total * 100 : 0}%`}}/></div>
    <strong>{row.value}</strong>
  </div>)}</div>;
}

export function Workspace(props: Props) {
  const {assessment, page, navigate} = props;
  const items = useMemo(() => assessment?.assessments ?? [], [assessment]);
  const capacity = useCapacity(
    props.run?.status === "completed" ? props.runId : null,
    props.run?.snapshot_id,
    props.request,
  );
  const [search, setSearch] = useState("");
  const [complexity, setComplexity] = useState("");
  const [target, setTarget] = useState("");
  const [stage, setStage] = useState("");
  const [platform, setPlatform] = useState("");
  const [selection, updateSelection] = useState<{item: Item; runId: string | null; snapshotId: string | undefined} | null>(null);
  const selected = selection && selection.runId === props.runId
    && selection.snapshotId === props.run?.snapshot_id
    && items.some(item => item.path === selection.item.path) ? selection.item : null;
  const [detail, setDetail] = useState<(typeof detailTabs)[number][0]>("summary");
  const [evidenceTab, setEvidenceTab] = useState(0);
  const [technicalSearch, setTechnicalSearch] = useState("");
  const [technicalWorkflow, setTechnicalWorkflow] = useState("");
  const [registerPage, setRegisterPage] = useState(0);
  const [team, setTeam] = useState(7);
  const [allocation, setAllocation] = useState(77);
  const dialog = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const scope = assessment ? assessment.workflow_count + assessment.failed_count : null;
  const summary = useMemo(() => {
    let toolCount = 0;
    let connectionCount = 0;
    let effort = 0;
    let findings = assessment?.failed_count ?? 0;
    let dependencies = 0;
    let endpoints = 0;
    let nativeReady = 0;
    let manualRework = 0;
    let highComplexity = 0;
    const targets = new Set<string>();
    const bands = new Set<string>();
    const platforms = new Set<string>();
    const targetCounts = new Map<string, number>();
    const complexityCounts = new Map<string, number>();
    for (const item of items) {
      toolCount += item.tool_count;
      connectionCount += item.connection_count;
      effort += item.estimated_effort_days;
      findings += item.unsupported_tools.length;
      dependencies += item.dependencies.length;
      endpoints += item.data_sources.length;
      if (item.recommended_target === "Manual rework") manualRework += 1;
      else nativeReady += 1;
      if (["High", "Critical"].includes(item.complexity_band)) highComplexity += 1;
      targets.add(item.recommended_target);
      bands.add(item.complexity_band);
      platforms.add(item.source_platform ?? "alteryx");
      targetCounts.set(item.recommended_target, (targetCounts.get(item.recommended_target) ?? 0) + 1);
      const complexity = item.complexity_band === "Critical" ? "High" : item.complexity_band;
      complexityCounts.set(complexity, (complexityCounts.get(complexity) ?? 0) + 1);
    }
    const targetList = [...targets];
    return {
      toolCount,
      connectionCount,
      effort,
      findings,
      dependencies,
      endpoints,
      nativeReady,
      manualRework,
      highComplexity,
      targets: targetList,
      bands: [...bands],
      platforms: [...platforms],
      complexityRows: ["Low", "Medium", "High"].map((name, index) => ({
        name,
        value: complexityCounts.get(name) ?? 0,
        color: ["good", "warn", "bad"][index],
      })),
      targetRows: targetList.map(name => ({name, value: targetCounts.get(name) ?? 0})),
      top: [...items].sort((a, b) => b.complexity_score - a.complexity_score).slice(0, 6),
    };
  }, [assessment?.failed_count, items]);
  const {
    toolCount,
    connectionCount,
    effort,
    findings,
    dependencies,
    endpoints,
    nativeReady,
    manualRework,
    highComplexity,
    targets,
    bands,
    platforms,
    complexityRows,
    targetRows,
    top,
  } = summary;
  const waveSummaries = useMemo(() => summarizeWaves(items, targets), [items, targets]);
  const mappingRows = useMemo(() => toolMappingRows(items), [items]);
  const index = selected && assessment?.workflows
    ? assessment.workflows.findIndex(
        item => selected.path === item.display_path || selected.path.startsWith(`${item.display_path}!`)
      ) : -1;
  const evidence = useEvidence(Boolean(assessment) && (page === "technical-details" || selected !== null), props.runId,
    props.run?.snapshot_id, selected ? index : null, props.request);
  const graph = selected ? evidence.data?.workflows.find(item => item.workflow_path === selected.path) : undefined;
  const filtered = useMemo(() => items.filter(item =>
    (!search || `${item.path} ${item.recommendation_reason}`.toLowerCase().includes(search.toLowerCase()))
    && (!complexity || item.complexity_band === complexity)
    && (!target || item.recommended_target === target)
    && (!stage || item.migration_wave === stage)
    && (!platform || (item.source_platform ?? "alteryx") === platform)
  ), [items, search, complexity, target, stage, platform]);
  const currentLabel = pages.find(item => item.id === page)?.label ?? "New assessment";

  useEffect(() => {
    document.title = `${currentLabel} | ETL Fabric Accelerator`;
  }, [currentLabel]);
  useEffect(() => {
    if (!selected) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialog.current?.querySelector<HTMLButtonElement>("button")?.focus();
    return () => {
      document.body.style.overflow = previous;
      trigger.current?.focus();
    };
  }, [selected]);
  function setSelected(item: Item | null) {
    updateSelection(item ? {item, runId: props.runId, snapshotId: props.run?.snapshot_id} : null);
  }

  function jump(destination: Page, wave = "", tab = 0) {
    setSearch(""); setTarget(""); setComplexity(""); setStage(wave);
    setRegisterPage(0); setEvidenceTab(tab); setTechnicalSearch(""); setTechnicalWorkflow("");
    setSelected(null); navigate(destination);
  }
  function open(item: Item, element: HTMLElement) {
    trigger.current = element; setDetail("summary"); setSelected(item);
  }
  function exportRows(filename: string, headings: string[], rows: string[][]) {
    const csv = [headings, ...rows].map(row => row.map(cell => {
      const safe = /^\s*[=+\-@]/.test(cell) || /^[\t\r]/.test(cell) ? `'${cell}` : cell;
      return `"${safe.replaceAll('"', '""')}"`;
    }).join(",")).join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], {type: "text/csv;charset=utf-8"}));
    const link = document.createElement("a"); link.href = url; link.download = filename; link.click();
    URL.revokeObjectURL(url);
  }
  const workflowRows = (rows: Item[]) => rows.map(item => [
    nameOf(item.path), item.path, item.complexity_band, item.recommended_target,
    item.estimated_effort_days.toFixed(1), waveLabel(item.migration_wave), item.recommendation_reason,
  ]);
  const metrics = [
    ["Workflows in scope", scope, "Included in migration planning"],
    ["Source tools and connections", assessment ? toolCount : null, `${connectionCount} tool-to-tool connections`],
    ["Source assessment findings", assessment ? findings : null, "Unmapped tool types and parsing failures"],
    ["Estimated remaining effort", assessment ? `${effort.toFixed(1)}d` : null, "Practical completion estimate"],
  ];
  const optimizedCapacity = capacity.estimate?.scenarios.find(
    scenario => scenario.name === "Optimized"
  );
  const balanceCapacity = capacity.estimate?.scenarios.find(
    scenario => scenario.name === "Balance"
  );
  const peakCapacity = capacity.estimate?.scenarios.find(
    scenario => scenario.name === "Peak"
  );
  const capacityLeadershipValue = capacity.estimate && capacity.estimate.status !== "not_available"
    ? optimizedCapacity?.recommended_sku ?? "Not available"
    : "Not available";
  const capacityContext = capacity.estimate
    ? `${capacity.estimate.monthly_cu_hours.toFixed(1)} CU-h/mo${capacity.estimate.status === "inputs_required" ? " · Default schedule/rows" : ""}${capacity.estimate.settings.spark_billing_mode === "autoscale" ? " (Spark offloaded to Autoscale)" : ""}`
    : "Optimized concurrency scenario";

  return <div className="shell reference-workspace">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">F</div><div><strong>ETL Fabric Accelerator</strong><span>Alteryx and Informatica to Microsoft Fabric</span></div></div>
      <nav className="nav" aria-label="Primary">{pages.map(item => <a key={item.id} className={page === item.id ? "active" : ""}
        href={`#${item.id}`} aria-current={page === item.id ? "page" : undefined}
        onClick={() => {setSelected(null); navigate(item.id);}}><Icon name={item.icon}/>{item.label}</a>)}</nav>
      <div className="sidebar-note"><strong>Assessment scope</strong><p>{assessment
        ? `${scope} ETL assets are in scope. Static recommendations require validation.`
        : "No assessment has been loaded. Choose an input to populate the migration portfolio."}</p>
      </div>
    </aside>
    <main className="main">
      <header className="topbar">
        <div className="breadcrumb"><button onClick={() => jump(assessment ? "executive-summary" : "intake")}>Migration assessment</button> / <strong>{currentLabel}</strong></div>
        <div className="top-actions"><button className="secondary-button" onClick={() => {
          jump("executive-summary");
          requestAnimationFrame(() => document.getElementById("assessmentNavigation")?.scrollIntoView({behavior: "smooth"}));
        }}>Assessment guide</button><button className="icon-button" onClick={props.toggleTheme} aria-label="Switch color theme"><Icon name="moon"/></button></div>
      </header>
      {props.status}
      <div hidden={page !== "intake"}>{props.children}</div>
      <div className="content" hidden={page === "intake"}>
        <section
          className={`page ${page === "executive-summary" ? "active" : ""}`}
          hidden={page !== "executive-summary"}
          id="executive-summary"
        >
          <div className="page-header">
            <div>
              <div className="eyebrow">Leadership view</div>
              <h1>Portfolio Migration Summary</h1>
              <p>
                Portfolio readiness, delivery sequencing, material risks and decisions required
                to mobilize the ETL-to-Fabric migration.
              </p>
            </div>
          </div>
          <div className="recommendation-banner">
            <div>
              <h2>Leadership recommendation</h2>
              <p>
                {assessment
                  ? `Proceed conditionally with ${nativeReady} native-ready workflows. Resolve ${manualRework} manual-rework items, assign business ownership and calibrate effort through the initial migration waves before scaling.`
                  : "Complete the portfolio assessment before making a migration funding or sequencing decision."}
              </p>
            </div>
            <span className="recommendation-status">
              {assessment
                ? manualRework || highComplexity ? "Conditional proceed" : "Proceed"
                : "Assessment required"}
            </span>
          </div>
          <div className="metric-grid leadership-metrics">
            {[
              ["Portfolio scope", scope, "ETL assets assessed"],
              ["Native-ready", assessment ? nativeReady : null, "Deployable Dataflow, Notebook or Pipeline route"],
              ["Manual rework", assessment ? manualRework : null, "No native deployable implementation"],
              ["Estimated remaining effort", assessment ? `${effort.toFixed(1)}d` : null, "Maximum 21 days per workflow"],
              [
                "Projected F-SKU",
                capacityLeadershipValue,
                <>
                  <span>{capacityContext}</span>
                  <button
                    type="button"
                    className="link-button metric-link-button"
                    onClick={() => jump("capacity-planning")}
                  >
                    Go to Capacity Planning for more details →
                  </button>
                </>,
              ],
            ].map(([label, value, context]) => <div className="metric-card" key={String(label)}>
              <div className="metric-label">{label}</div>
              <div className="metric-value">{value ?? "—"}</div>
              <div className="metric-context">{context}</div>
            </div>)}
          </div>
          <div className="two-column">
            <Panel
              title="Decision brief"
              note="The specific approval boundary for this assessment."
            >
              <div className="fact-grid">
                <div className="fact">
                  <span>Decision requested</span>
                  <strong>Approve conditional mobilization</strong>
                </div>
                <div className="fact">
                  <span>Funding boundary</span>
                  <strong>Wave 1 prerequisites and controlled pilot only</strong>
                </div>
                <div className="fact">
                  <span>Conditions</span>
                  <strong>Owners, parity thresholds, capacity and business case</strong>
                </div>
                <div className="fact">
                  <span>Next approval gate</span>
                  <strong>Pilot exit review before scale-out</strong>
                </div>
              </div>
              <button className="link-button" onClick={() => jump("migration-plan")}>
                Review approval gates →
              </button>
            </Panel>
            <Panel
              title="Leadership scorecard"
              note="Decision readiness by evidence dimension."
            >
              <div className="focus-list">
                <div className="focus-item">
                  <div>
                    <strong>Technology readiness · Amber</strong>
                    <span>{nativeReady} of {scope ?? 0} workflows have a native route.</span>
                  </div>
                </div>
                <div className="focus-item">
                  <div>
                    <strong>Business ownership · Red</strong>
                    <span>Owner, criticality and SLA evidence were not supplied.</span>
                  </div>
                </div>
                <div className="focus-item">
                  <div>
                    <strong>Business case · Red</strong>
                    <span>
                      {capacity.estimate
                        ? "Preliminary capacity evidence exists; cost, savings and pilot validation remain open."
                        : "Cost, capacity, savings and benefit evidence are missing."}
                    </span>
                  </div>
                </div>
                <div className="focus-item">
                  <div>
                    <strong>Delivery governance · Amber</strong>
                    <span>Wave gates exist; accountable owners remain unassigned.</span>
                  </div>
                </div>
              </div>
            </Panel>
          </div>
          <div className="two-column section-gap">
            <Panel
              title="Immediate leadership actions"
              note="Actions required before approving broader delivery."
            >
              <div className="decision-list">
                {[
                  ["Name the sponsor and workflow owners", "Assign business accountability, criticality and service expectations.", "Review workflows", "workflows"],
                  ["Commission the business case", "Validate Fabric capacity, migration cost, legacy ETL savings and expected benefits.", "View evidence gaps", "technical-details"],
                  ["Authorize the controlled pilot", "Approve entry criteria and require a measured exit review.", "Open plan", "migration-plan"],
                ].map(([title, text, label, destination], index) => <div className="decision-item" key={title}>
                  <span className="decision-number">{index + 1}</span>
                  <div><strong>{title}</strong><span>{text}</span></div>
                  <button className="link-button" onClick={() => jump(destination as Page)}>
                    {label}
                  </button>
                </div>)}
              </div>
            </Panel>
            <Panel
              title="Escalations"
              note="Items requiring explicit leadership ownership."
            >
              <div className="focus-list">
                <div className="focus-item">
                  <div><strong>{manualRework} manual-rework workflows</strong><span>No native deployable route; disposition or redesign decision required.</span></div>
                  <button className="link-button" onClick={() => jump("workflows")}>Review</button>
                </div>
                <div className="focus-item">
                  <div><strong>{highComplexity} high-complexity workflows</strong><span>Require enhanced validation, contingency and oversight.</span></div>
                  <button className="link-button" onClick={() => jump("workflows")}>Inspect</button>
                </div>
                <div className="focus-item">
                  <div><strong>Business case incomplete</strong><span>No approved cost, benefit, capacity or savings baseline.</span></div>
                  <button className="link-button" onClick={() => jump("capacity-planning")}>Capacity</button>
                </div>
              </div>
            </Panel>
          </div>
          <div className="section-gap">
            <Panel title="Assessment confidence and evidence gaps">
              <p>
                Recommendations use static workflow evidence. Business criticality, ownership,
                run frequency, SLA, production volumes, operating cost, Fabric capacity,
                licensing savings and benefit realization were not supplied. These inputs are
                required before approving a committed business case or production cutover.
              </p>
            </Panel>
          </div>
        </section>

        <div hidden={page !== "capacity-planning"}>
          <CapacityPlanning
            estimate={capacity.estimate}
            loading={capacity.loading}
            saving={capacity.saving}
            error={capacity.error}
            runId={props.runId}
            save={capacity.save}
          />
        </div>

        <section className={`page ${page === "executive-summary" ? "active" : ""}`} hidden={page !== "executive-summary"} id="portfolio-analysis">
          <div className="page-header"><div><div className="eyebrow">Portfolio analysis</div><h1>Detailed Portfolio Assessment</h1><p>Workflow complexity, target architecture, delivery sequencing and technical evidence supporting the portfolio decision memo.</p></div></div>
          <div className="question-card" id="assessmentNavigation"><div><h2>Assessment navigation</h2><p>Select an assessment area to review the supporting portfolio, workflow, planning or technical evidence.</p></div>
            <div className="quick-actions"><button onClick={() => jump("workflows")}>Review workflow register</button><button onClick={() => jump("migration-plan")}>Review migration plan</button><button onClick={() => jump("capacity-planning")}>Review capacity estimate</button><button onClick={() => jump("technical-details")}>Review technical evidence</button></div></div>
          {!assessment && <div className="notice"><strong>No completed assessment.</strong> <button className="link-button" onClick={() => jump("intake")}>Start an assessment</button> to populate these registers. Reference sample counts are not used as real results.</div>}
          <div className="recommendation-banner"><div><h2>Recommended delivery approach</h2><p>Resolve shared dependencies and connection prerequisites before a representative pilot. Validate functional parity, deployment controls and effort assumptions before broader migration.</p></div><span className="recommendation-status">{assessment ? (manualRework || highComplexity ? "Conditional proceed" : "Proceed") : "Assessment required"}</span></div>
          <div className="metric-grid">{metrics.map(([label, value, context]) => <div className="metric-card" key={String(label)}><div className="metric-label">{label}</div><div className="metric-value">{value ?? "—"}</div><div className="metric-context">{context}</div></div>)}</div>
          <div className="two-column"><Panel title="Technical complexity" note="Static complexity grouping; it does not represent business priority." action={<button className="link-button" onClick={() => jump("workflows")}>View all workflows →</button>}>
            <Bars total={items.length} rows={complexityRows}/></Panel>
            <Panel title="Immediate migration priorities" note="Items with the greatest impact on mobilisation and delivery sequencing."><div className="focus-list">
              <div className="focus-item"><div><strong>Shared connections</strong><span>Resolve reusable access patterns</span></div><button className="link-button" onClick={() => jump("migration-plan", waveDefinitions[0].value)}>View Wave 1</button></div>
              <div className="focus-item"><div><strong>{top[0] ? nameOf(top[0].path) : "Highest-complexity workflow"}</strong><span>Highest technical complexity</span></div><button disabled={!top.length} className="link-button" onClick={e => open(top[0], e.currentTarget)}>Open workflow</button></div>
              <div className="focus-item"><div><strong>Compatibility findings</strong><span>Review unmapped and redesign requirements</span></div><button className="link-button" onClick={() => jump("technical-details", "", 4)}>View findings</button></div>
            </div></Panel></div>
          <div className="two-column section-gap"><Panel title="Recommended primary Fabric targets" note="Primary implementation technology recommended for each workflow."><Bars total={items.length} rows={targetRows}/></Panel>
            <Panel title="Assessment evidence inventory" note="Evidence available to support engineering analysis and migration sequencing."><div className="assumption-grid"><div className="assumption"><span>Dependencies</span><strong>{assessment ? dependencies : "—"}</strong></div><div className="assumption"><span>File endpoints</span><strong>{assessment ? endpoints : "—"}</strong></div><div className="assumption"><span>Parse failures</span><strong>{assessment?.failed_count ?? "—"}</strong></div></div></Panel></div>
          <div className="section-gap">
            <Panel
              title="Fabric capacity summary"
              note={capacity.estimate?.status === "planning_estimate"
                ? "Preliminary capacity sizing across modeled Alteryx and Informatica workloads."
                : "Estimated from assessment tool counts and default schedule/rows (Daily, 1,000 rows)."}
              action={<button className="link-button" onClick={() => jump("capacity-planning")}>Open Capacity Planning →</button>}
            >
              {capacity.estimate ? <div className="fact-grid">
                <div className="fact">
                  <span>Optimized (staggered)</span>
                  <strong>{optimizedCapacity ? `${optimizedCapacity.recommended_sku} (${optimizedCapacity.required_cu.toFixed(2)} CUs)` : "—"}</strong>
                </div>
                <div className="fact">
                  <span>Balance / Peak</span>
                  <strong>{balanceCapacity && peakCapacity ? `${balanceCapacity.recommended_sku} / ${peakCapacity.recommended_sku}` : "—"}</strong>
                </div>
                <div className="fact">
                  <span>Monthly demand</span>
                  <strong>
                    {capacity.estimate.monthly_cu_hours.toFixed(1)} CU-h
                    {capacity.estimate.settings.spark_billing_mode === "autoscale" && (capacity.estimate.autoscale_spark_monthly_cu_hours ?? 0) > 0
                      ? ` (+${(capacity.estimate.autoscale_spark_monthly_cu_hours ?? 0).toFixed(1)} Autoscale Spark CU-h)`
                      : ""}
                  </strong>
                </div>
                <div className="fact">
                  <span>Basis &amp; status</span>
                  <strong>
                    {capacity.estimate.status === "planning_estimate" ? "Preliminary" : capacity.estimate.status === "inputs_required" ? "Default assumptions" : "Not available"}
                    {` · ${capacity.estimate.calibrated_count ?? capacity.estimate.modeled_count} calibrated / ${capacity.estimate.heuristic_count ?? 0} heuristic`}
                  </strong>
                </div>
              </div> : <p>Complete an assessment to view Fabric capacity sizing.</p>}
            </Panel>
          </div>
          <div className="section-gap"><Panel title="Migration wave distribution" note="Engine wave allocation and remaining effort; no business priority is inferred." action={<button className="link-button" onClick={() => jump("migration-plan")}>View migration plan →</button>}>
            <div className="portfolio-segments">{waveSummaries.map(wave => <button key={wave.value} className="portfolio-segment" onClick={() => jump("migration-plan", wave.value)}><span>{wave.label} · {wave.effort.toFixed(1)} days</span><strong>{wave.count} workflows</strong></button>)}</div></Panel></div>
          <div className="section-gap"><Panel title="Workflows with highest technical complexity" note="Prioritised by static raw complexity score; this ranking does not represent business criticality." action={<button className="link-button" onClick={() => jump("workflows")}>View workflow register →</button>}>
            <div className="table-wrap"><table><thead><tr>{["Workflow", "Score", "Complexity", "Stage", "Fabric target", "Remaining effort", "Why it matters"].map(value => <th key={value}>{value}</th>)}</tr></thead><tbody>{top.map(item => <tr key={item.path}>
              <td><button className="workflow-open-button workflow-name" aria-label={`Open workflow ${nameOf(item.path)}`} onClick={e => open(item, e.currentTarget)}>{nameOf(item.path)}</button></td><td>{item.complexity_score}</td><td><span className={`status ${statusClass(item.complexity_band)}`}>{item.complexity_band}</span></td><td>{waveLabel(item.migration_wave)}</td><td>{item.recommended_target}</td><td>{item.estimated_effort_days.toFixed(1)}d</td><td>{item.recommendation_reason}</td></tr>)}</tbody></table></div></Panel></div>
          <div className="two-column section-gap"><Panel title="Principal technical risks" note="Technical evidence requiring remediation or validation before cutover."><div className="focus-list"><div className="focus-item"><div><strong>Unmapped tools and expressions</strong><span>Explicit redesign and parity evidence required.</span></div><button className="link-button" onClick={() => jump("technical-details", "", 4)}>Inspect</button></div><div className="focus-item"><div><strong>Environment-specific references</strong><span>Validate portable connections and file bindings.</span></div><button className="link-button" onClick={() => jump("technical-details", "", 3)}>Review dependencies</button></div></div></Panel>
            <Panel title="Assessment confidence and limitations"><p>Static evidence is not runtime, throughput, memory, business criticality, measured effort, or production readiness. Unknown values are not Low risk. No workflow content is executed.</p></Panel></div>
          {assessment && props.runId && <div className="section-gap"><Panel title="Assessment outputs" note="Export assessment data, download Fabric ZIP packages, or generate code previews below. Previews are unbound and unvalidated; nothing is executed or deployed.">
            <div className="outputs-grid">
              <div className="output-group">
                <h3>1. Assessment reports</h3>
                <p>Download the portfolio metrics, wave plan, and workflow findings.</p>
                <div className="deploy-actions">
                  <a className="secondary-button" href={`/api/runs/${props.runId}/export?format=json`}>Export JSON</a>
                  <a className="secondary-button" href={`/api/runs/${props.runId}/export?format=csv`}>Export CSV</a>
                </div>
              </div>
              <div className="output-group">
                <h3>2. Download Fabric packages</h3>
                <p>Build and download a ZIP of generated artifacts for each Fabric target.</p>
                <div className="deploy-actions">
                  <a className="secondary-button" href={`/api/runs/${props.runId}/candidates?target=notebook`}>Download Notebook package</a>
                  <a className="secondary-button" href={`/api/runs/${props.runId}/candidates?target=dataflow`}>Download Dataflow package</a>
                  <a className="secondary-button" href={`/api/runs/${props.runId}/candidates?target=pipeline`}>Download Pipeline package</a>
                </div>
              </div>
              <div className="output-group">
                <h3>3. Preview generated code</h3>
                <p>Inspect generated Fabric definitions, paths, and diagnostics on this page.</p>
                <div className="deploy-actions">
                  <button className="secondary-button" disabled={props.generating} onClick={() => props.generate("notebook")}>Generate Notebook previews</button>
                  <button className="secondary-button" disabled={props.generating} onClick={() => props.generate("dataflow")}>Generate Dataflow previews</button>
                  <button className="secondary-button" disabled={props.generating} onClick={() => props.generate("pipeline")}>Generate Pipeline previews</button>
                </div>
              </div>
            </div>
            {props.generating && <p className="output-status" role="status">Generating Fabric definitions for preview…</p>}
            {props.candidates.length > 0 && (() => {
              const targetNames = new Set(props.candidates.map(item =>
                item.target === "dataflow" ? "Dataflow Gen2" : item.target === "pipeline" ? "Fabric Data Pipeline" : "Fabric Notebook"
              ));
              const deployableCount = props.candidates.filter(item => item.deployable).length;
              const scaffoldCount = props.candidates.length - deployableCount;
              return <div className="outputs-preview-list">
                <div className="outputs-preview-header">
                  <strong>{Array.from(targetNames).join(" / ")} previews ({props.candidates.length})</strong>
                  <span>{deployableCount} deployable · {scaffoldCount} manual scaffold{scaffoldCount === 1 ? "" : "s"}</span>
                </div>
                {props.candidates.map(candidate => {
                  const targetLabel = candidate.target === "dataflow"
                    ? "Dataflow Gen2"
                    : candidate.target === "pipeline"
                      ? "Fabric Data Pipeline"
                      : "Fabric Notebook";
                  const validationSummary = candidate.validation_state === "generated_unvalidated"
                    ? "Unvalidated preview (bind sources and test parity before deploy)"
                    : candidate.validation_state === "scaffold_only"
                      ? "Scaffold only (manual redesign required)"
                      : candidate.validation_state;
                  return <div className="summary-box output-card" key={`${candidate.workflow}-${candidate.target}`}>
                    <div className="output-card-meta">
                      <span className="chip">{targetLabel}</span>
                      <span className={`status ${candidate.deployable ? "ready" : "redesign"}`}>
                        <span className="dot"/>
                        {candidate.deployable ? "Deployable definition" : "Scaffold / manual rework"}
                      </span>
                      {candidate.definition_files.map(file => <span className="chip" key={file}>{file}</span>)}
                    </div>
                    <h2 className="output-card-title" aria-label={`${candidate.workflow}: ${candidate.validation_state}`}>
                      {nameOf(candidate.workflow)}
                    </h2>
                    <p className="output-card-source"><code>{candidate.workflow}</code> · {validationSummary}</p>
                    {candidate.artifact_path && <p>Saved in <code>generated-fabric-workflows/{candidate.artifact_path}</code></p>}
                    {candidate.diagnostics.map(value => <p key={value}>{value}</p>)}
                    {candidate.code && <details className="code-details">
                      <summary>View generated code ({candidate.code.split("\n").length} lines)</summary>
                      <pre className="deploy-code">{candidate.code}</pre>
                    </details>}
                  </div>;
                })}
              </div>;
            })()}
          </Panel></div>}
        </section>

        <section className={`page ${page === "workflows" ? "active" : ""}`} hidden={page !== "workflows"} id="workflows">
          <div className="page-header"><div><div className="eyebrow">Workflow assessment</div><h1>Workflow Assessment Register</h1><p>Search and filter the workflow-level assessment, then open supporting source, design and validation evidence.</p></div><div className="quick-actions"><button className="secondary-button" disabled={!assessment} onClick={() => exportRows("workflows.csv", ["Workflow", "Path", "Complexity", "Target", "Remaining effort", "Wave", "Evidence"], workflowRows(filtered))}>Export register</button><button className="primary-button" onClick={() => jump("migration-plan")}>Migration Plan →</button></div></div>
          {!assessment && <div className="notice"><strong>No workflows assessed yet.</strong> <button className="link-button" onClick={() => jump("intake")}>Start an assessment</button> to inspect and deploy workflows.</div>}
          <Filters search={search} setSearch={setSearch} complexity={complexity} setComplexity={setComplexity} target={target} setTarget={setTarget} stage={stage} setStage={setStage} platform={platform} setPlatform={setPlatform} platforms={platforms} targets={targets} bands={bands} clear={() => {setSearch(""); setComplexity(""); setTarget(""); setStage(""); setPlatform("");}}/>
          <WorkflowTable key={JSON.stringify([search, complexity, target, stage, platform, props.runId])} items={filtered} open={open}/>
        </section>

        <section className={`page ${page === "migration-plan" ? "active" : ""}`} hidden={page !== "migration-plan"} id="migration-plan">
          <div className="page-header"><div><div className="eyebrow">Delivery sequencing</div><h1>Evidence-Based Migration Plan</h1><p>Engine allocations and practical remaining person-day estimates support planning, not delivery approval.</p></div><div className="quick-actions"><button className="secondary-button" disabled={!assessment} onClick={() => exportRows("migration-plan.csv", ["Workflow", "Path", "Complexity", "Target", "Remaining effort", "Wave", "Rationale"], workflowRows(filtered))}>Create planning export</button><button className="primary-button" onClick={() => jump("technical-details")}>Technical Details →</button></div></div>
          <div className="technical-kpis">{waveSummaries.map(wave => <div className="technical-kpi" key={wave.value}><span>{wave.label}</span><strong>{wave.count}</strong><small>Engine allocation retained</small></div>)}</div>
          <div className="stages">{waveSummaries.map((wave, i) => <button className="stage" key={wave.value} onClick={() => {setStage(wave.value); setSearch(""); document.getElementById("planningBacklog")?.scrollIntoView({behavior: "smooth"});}}><div className="stage-number">{i + 1}</div><h3>{wave.label}</h3><p>{["Resolve shared prerequisites and agree source bindings.", "Prove representative transformations and operational controls.", "Apply reviewed patterns to the remaining backlog.", "Redesign unsupported or specialist workflow semantics."][i]}</p><div className="stage-meta"><div><span>Workflows</span><strong>{wave.count}</strong></div><div><span>Effort</span><strong>{wave.effort.toFixed(1)}d</strong></div></div></button>)}</div>
          <div className="notice">Wave allocations come from the assessment engine; titles are normalized to Wave 1 through Wave 4.</div>
          <div className="two-column"><Panel title="Remaining effort allocation" note="Practical person-day estimate assigned to each migration wave; each workflow is capped at 21 days."><Bars total={effort} rows={waveSummaries.map(wave => ({name: wave.label, value: Number(wave.effort.toFixed(1))}))}/></Panel>
            <Panel title="Fabric target distribution by wave"><div className="fact-grid">{waveSummaries.map(wave => <div className="fact" key={wave.value}><span>{wave.label}</span><strong>{wave.targetSummary || "Not available"}</strong></div>)}</div></Panel></div>
          <div className="two-column section-gap"><Panel title="Delivery capacity sensitivity" note="Illustrative duration; not a measured schedule or an exported commitment."><div className="capacity-controls"><div className="capacity-control"><label htmlFor="teamSize"><span>Team size</span><strong>{team} people</strong></label><input id="teamSize" type="range" min="1" max="15" value={team} onChange={e => setTeam(Number(e.target.value))}/></div><div className="capacity-control"><label htmlFor="allocation"><span>Productive allocation</span><strong>{allocation}%</strong></label><input id="allocation" type="range" min="40" max="100" value={allocation} onChange={e => setAllocation(Number(e.target.value))}/></div></div><div className="assumption-grid"><div className="assumption"><span>Effective capacity</span><strong>{Number.isFinite(team * allocation) && team > 0 && allocation > 0 ? (team * allocation / 100).toFixed(1) : 'n/a'} FTE</strong></div><div className="assumption"><span>Indicative duration</span><strong>{assessment && Number.isFinite(team * allocation) && team > 0 && allocation > 0 ? (effort / (team * allocation / 100) / 5).toFixed(1) : 'n/a'} weeks</strong></div><div className="assumption"><span>Effort basis</span><strong>{assessment ? effort.toFixed(1) : "—"} days</strong></div></div></Panel>
            <Panel title="Planning basis and assumptions"><div className="focus-list"><div className="focus-item"><div><strong>Sequencing evidence</strong><span>Complexity, targets, macros and dependency references.</span></div></div><div className="focus-item"><div><strong>Not included</strong><span>Business criticality, runtime, schedules and failure history.</span></div></div><div className="focus-item"><div><strong>Calibration required</strong><span>Update estimates using accepted pilot outcomes.</span></div></div></div></Panel></div>
          <div className="gate-grid" id="planGates">{["Connections and identities tested; shared components versioned; source bindings reviewed", "Functional parity accepted; effort recalibrated; deployment and monitoring proven", "Reusable patterns applied consistently; capacity and support agreed", "Advanced semantics validated; representative performance tested; rollback and owner approval"].map((text, i) => <article className="gate-card" key={text}><h3>Wave {i + 1} exit gate</h3><p>Required evidence, not an approval recorded by this app.</p><ul>{text.split("; ").map(value => <li key={value}>{value}</li>)}</ul></article>)}</div>
          <div id="planningBacklog"><Panel title="Migration backlog and sequencing rationale"><Filters search={search} setSearch={setSearch} complexity={complexity} setComplexity={setComplexity} target={target} setTarget={setTarget} stage={stage} setStage={setStage} platform={platform} setPlatform={setPlatform} platforms={platforms} targets={targets} bands={bands} clear={() => {setSearch(""); setComplexity(""); setTarget(""); setStage(""); setPlatform("");}}/><WorkflowTable key={JSON.stringify([search, complexity, target, stage, platform, props.runId])} items={filtered} open={open}/></Panel></div>
        </section>

        <section className={`page ${page === "technical-details" ? "active" : ""}`} hidden={page !== "technical-details"} id="technical-details">
          <div className="page-header"><div><div className="eyebrow">Source evidence</div><h1>Technical Assessment Evidence</h1><p>Inspect the parsed inventory, expressions, endpoints, dependencies, findings and canvas connections.</p></div><div className="quick-actions"><button className="secondary-button" disabled={!assessment} onClick={() => exportRows("technical-summary.csv", ["Evidence", "Count"], [["Tools", String(toolCount)], ["Connections", String(connectionCount)], ["Dependencies", String(dependencies)], ["File endpoints", String(endpoints)]] )}>Export technical summary</button><button className="primary-button" onClick={() => jump("workflows")}>Workflows →</button></div></div>
          {!assessment && <div className="notice"><strong>No technical evidence loaded.</strong> <button className="link-button" onClick={() => jump("intake")}>Start an assessment</button> to populate the source registers.</div>}
          <div className="technical-kpis">{[
            ["Workflows", assessment?.workflow_count ?? 0],
            ["Source tools", toolCount],
            ["Connections", connectionCount],
            ["Dependencies", dependencies],
            ["File endpoints", endpoints],
            ["Findings", findings],
          ].map(([label, value]) => <div className="technical-kpi" key={String(label)}><span>{label}</span><strong>{assessment ? value : "—"}</strong><small>Static assessment evidence</small></div>)}</div>
          <div className="two-column"><Panel title="Fabric tool-mapping distribution"><Bars total={toolCount} rows={mappingRows}/></Panel><Panel title="Assessment scope and coverage"><p>Parser and registry versions are retained per workflow. Unknown mappings remain explicit redesign requirements; previews do not establish semantic parity.</p><a href="/api/registry" target="_blank" rel="noreferrer">View versioned registry</a></Panel></div>
          <Tabs labels={evidenceTabs} active={evidenceTab} setActive={value => {setEvidenceTab(value); setRegisterPage(0);}} label="Technical evidence registers"/>
          <div className="technical-controls"><div className="field"><label className="sr-only" htmlFor="evidenceSearch">Search technical evidence</label><input id="evidenceSearch" type="search" value={technicalSearch} placeholder="Search the current evidence register" onChange={e => {setTechnicalSearch(e.target.value); setRegisterPage(0);}}/></div><select aria-label="Filter by workflow" value={technicalWorkflow} onChange={e => {setTechnicalWorkflow(e.target.value); setRegisterPage(0);}}><option value="">All workflows</option>{items.map(item => <option key={item.path} value={item.path}>{nameOf(item.path)}</option>)}</select><button className="secondary-button" onClick={() => {setTechnicalSearch(""); setTechnicalWorkflow(""); setRegisterPage(0);}}>Clear filters</button></div>
          {evidence.loading && <p role="status">Loading verified snapshot evidence…</p>}{evidence.error && <div role="alert" className="notice">{evidence.error}</div>}
          <EvidenceRegister tab={evidenceTab} data={evidence.data} items={items} search={technicalSearch} workflow={technicalWorkflow} page={registerPage} setPage={setRegisterPage} exportRows={exportRows}/>
          <p className="technical-note">Static evidence does not prove runtime performance, connector availability, semantic parity, credential safety or production readiness.</p>
        </section>
      </div>
    </main>
    <nav className="mobile-nav" aria-label="Mobile primary navigation">{pages.map(item => <a key={item.id} className={page === item.id ? "active" : ""} href={`#${item.id}`} onClick={() => {setSelected(null); navigate(item.id);}}><Icon name={item.icon}/>{item.id === "intake" ? "Intake" : item.id === "migration-plan" ? "Plan" : item.id === "capacity-planning" ? "Capacity" : item.id === "technical-details" ? "Technical" : item.label}</a>)}</nav>
    {selected && (() => {
      const list = filtered.some(item => item.path === selected.path) ? filtered : items;
      const selectedPos = list.findIndex(item => item.path === selected.path);
      return <div className="drawer-backdrop open" onMouseDown={e => {if (e.target === e.currentTarget) setSelected(null);}}>
      <div className="drawer" ref={dialog} role="dialog" aria-modal="true" aria-labelledby="drawerTitle" onKeyDown={e => {
        if (e.key === "Escape") setSelected(null);
        if (e.key === "Tab") {
          const controls = [...e.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),[tabindex="0"]')].filter(item => item.offsetParent !== null);
          const first = controls[0], last = controls.at(-1);
          if (e.shiftKey && document.activeElement === first) {e.preventDefault(); last?.focus();}
          if (!e.shiftKey && document.activeElement === last) {e.preventDefault(); first?.focus();}
        }
      }}>
        <div className="drawer-top">
          <div>
            <div className="eyebrow">Workflow details</div>
            <h2 id="drawerTitle">{nameOf(selected.path)}</h2>
            <p className="drawer-subtitle">{graph?.purpose ?? "Business purpose is not documented in the available assessment metadata."}</p>
            {list.length > 1 && selectedPos >= 0 && <div className="drawer-nav">
              <button type="button" className="secondary-button" disabled={selectedPos <= 0} onClick={() => setSelected(list[selectedPos - 1])}>← Previous workflow</button>
              <span>{selectedPos + 1} of {list.length}</span>
              <button type="button" className="secondary-button" disabled={selectedPos >= list.length - 1} onClick={() => setSelected(list[selectedPos + 1])}>Next workflow →</button>
            </div>}
          </div>
          <button className="icon-button" onClick={() => setSelected(null)} aria-label="Close workflow details">×</button>
        </div>
        <Tabs labels={detailTabs.map(item => item[1])} active={detailTabs.findIndex(item => item[0] === detail)} setActive={value => setDetail(detailTabs[value][0])} label="Workflow detail sections"/>
        {evidence.loading && <p role="status">Loading workflow evidence…</p>}{evidence.error && <div role="alert" className="notice">{evidence.error}</div>}
        {graph?.parse_status === "failed" && <div role="alert" className="notice">
          Source graph parsing failed. {graph.findings.join(" · ")}
        </div>}
        <DrawerContent detail={detail} item={selected} graph={graph} props={props} openTechnical={() => {setTechnicalWorkflow(selected.path); setEvidenceTab(0); setSelected(null); navigate("technical-details");}}/>
      </div>
    </div>;
    })()}
  </div>;
}

function DrawerContent({detail, item, graph, props, openTechnical}: {
  detail: string; item: Item; graph: WorkflowEvidence | undefined; props: Props; openTechnical: () => void;
}) {
  const shape = useMemo(() => graphShape(graph), [graph]);
  const itemMappingRows = useMemo(() => toolMappingRows([item]), [item]);
  if (detail === "summary") return <section className="detail-section active">
    <div className="mini-grid"><div className="mini"><span>Complexity</span><strong>{item.complexity_band} complexity</strong></div><div className="mini"><span>Recommended target</span><strong>{item.recommended_target}</strong></div><div className="mini"><span>Remaining effort</span><strong>{item.estimated_effort_days.toFixed(1)} days</strong></div></div>
    <div className="summary-box"><h3>Functional purpose</h3><p>{graph?.purpose ?? "Business purpose is not documented in the available source metadata."}</p></div>
    <div className="summary-box"><h3>Source metadata</h3><div className="fact-grid"><div className="fact"><span>Source path</span><code>{item.path}</code></div><div className="fact"><span>Platform</span><strong>{platformLabel(item.source_platform)}</strong></div><div className="fact"><span>Product</span><strong>{item.source_product ?? "Alteryx Designer"}</strong></div><div className="fact"><span>Asset type</span><strong>{item.asset_type ?? (/\.yxmc$/i.test(item.path) ? "Macro" : /\.yxwz$/i.test(item.path) ? "Analytic app" : "Workflow")}</strong></div><div className="fact"><span>Source version</span><strong>{graph?.source_version ?? "Not available"}</strong></div><div className="fact"><span>Parse status</span><strong className="good">{graph?.parse_status === "failed" ? "Failed" : "Parsed"}</strong></div><div className="fact"><span>Tools / connections</span><strong>{item.tool_count} / {item.connection_count}</strong></div><div className="fact"><span>Graph evidence</span><strong>{shape.branches} branches · depth {shape.depth} · {shape.containers} containers · {shape.cycles ? "cycles detected" : "no cycles"}</strong></div><div className="fact"><span>Graph schema</span><strong>{item.graph_schema_version}</strong></div></div></div>
    <div className="summary-box"><div className="score-row"><div><h3>Complexity assessment</h3><p>Raw engine score; not a calibrated probability or business priority.</p></div><strong>{item.complexity_score} points</strong></div><Bars total={Math.max(item.tool_count, item.connection_count, item.unsupported_tools.length, 1)} rows={[{name: "Tools", value: item.tool_count}, {name: "Connections", value: item.connection_count}, {name: "Unmapped tool types", value: item.unsupported_tools.length}]}/></div>
    <div className="notice">Static XML assessment only. Runtime, throughput, data volume and failure history are not measured.</div></section>;
  const isInformatica = (item.source_platform ?? "").startsWith("informatica_");
  const dependencyTerm = isInformatica ? "dependency references" : "macro references";
  const executableNodes = (graph?.nodes ?? []).filter(node => node.support !== "neutral");
  if (detail === "design") return <section className="detail-section active"><div className="summary-box"><h3>Recommended Fabric design</h3><p>{item.recommendation_reason}</p></div><div className="summary-box"><h3>Target architecture interpretation</h3><div className="architecture-flow">{["Files & connections", "OneLake", item.recommended_target, "Reviewed orchestration"].map((value, index) => <Fragment key={index}><div className={`architecture-node ${index === 2 ? "primary" : ""}`}><span>{["Source", "Landing", "Primary compute", "Orchestration"][index]}</span><strong>{value}</strong></div>{index < 3 && <div className="architecture-arrow">→</div>}</Fragment>)}</div></div><div className="summary-box"><h3>Supporting components</h3><div className="chip-list">{item.target_components?.map(value => <span className="chip" key={value}>{value}</span>)}</div></div><Steps title="Implementation approach" values={[`Resolve source schemas, ${dependencyTerm} and environment-specific dependencies.`, "Rebuild only explicitly supported transformations in the reviewed target.", "Validate semantics and operational controls before deployment."]}/><div className="notice">This is a target design interpretation, not a deployed architecture or automatic conversion.</div></section>;
  if (detail === "flow") return <section className="detail-section active"><div className="summary-box"><h3>Source workflow graph</h3>{graph ? <SourceGraph graph={graph}/> : <p>No source graph has been loaded.</p>}</div><div className="summary-box"><h3>Migration interpretation graph</h3><div className="architecture-flow">{executableNodes.slice(0, 8).map(node => <div className={`architecture-node ${node.support === "manual" ? "primary" : ""}`} key={node.id}><span>Tool {node.id}</span><strong>{node.name}</strong><small>{supportDetail(node.support).target}</small></div>)}</div><p>{executableNodes.length > 8 ? `Showing first 8 of ${executableNodes.length} executable stages; inspect Source workflow graph above or Technical Details for the full graph.` : "Interpretation of the visible source tools, not an alternative executable graph."}</p></div><div className="summary-box"><h3>Tool mapping</h3><Bars total={item.tool_count} rows={itemMappingRows}/></div><div className="summary-box"><h3>Dependency graph</h3>{item.dependencies.length ? item.dependencies.map(value => <p key={value}><code>{value}</code></p>) : <p>{isInformatica ? "No workflow dependencies recorded." : "No macro references recorded."}</p>}</div><div className="summary-box"><h3>Material workflow components</h3><div className="chip-list">{[...new Set([
    ...(item.target_components ?? []),
    ...(item.data_sources.length ? ["Fabric Connections", "OneLake"] : []),
    ...(item.dependencies.length ? ["Reusable components"] : []),
  ])].map(value => <span className="chip" key={value}>{value}</span>)}</div></div><button className="secondary-button" onClick={openTechnical}>Open full technical registers</button></section>;
  if (detail === "findings") {
    const performancePriority = reviewPriority(Math.max(item.tool_count, shape.depth), 20, 50);
    const operationalPriority = reviewPriority(item.dependencies.length + shape.branches + shape.containers, 1, 8);
    const compatibilityPriority = reviewPriority(item.unsupported_tools.length, 1, 5);
    return <section className="detail-section active"><div className="summary-box"><h3>Risk profile</h3><p>Static review priorities; no runtime or credential risk rating is inferred.</p><div className="mini-grid"><div className="mini"><span>Performance review</span><strong>{performancePriority}</strong></div><div className="mini"><span>Operational review</span><strong>{operationalPriority}</strong></div><div className="mini"><span>Compatibility review</span><strong>{compatibilityPriority}</strong></div><div className="mini"><span>Credential pattern</span><strong>No static rating</strong></div></div></div><div className="summary-box"><h3>Assessment dimensions</h3><div className="dimension"><strong>Performance review priority · {performancePriority}</strong><p>{item.tool_count} tools, graph depth {shape.depth} and {shape.branches} branches require validation with representative production volumes.</p></div><div className="dimension"><strong>Operational review · {operationalPriority}</strong><p>{item.dependencies.length} dependency references and {shape.containers} containers require environment, restart and monitoring validation.</p></div><div className="dimension"><strong>Compatibility review · {compatibilityPriority}</strong><p>{item.recommendation_reason}</p></div><div className="dimension"><strong>Credential-pattern review · No static rating</strong><p>Common secret patterns are redacted. This is not a complete secret audit.</p></div></div><div className="summary-box"><h3>Priority findings</h3>{[...item.unsupported_tools.map(value => `${value}: requires explicit redesign`), ...(graph?.findings ?? [])].map((value, index) => <p key={index}>{value}</p>)}</div><div className="notice">Unknown is not Low risk. Static priorities are not measured operational outcomes.</div></section>;
  }
  if (detail === "validation") return <section className="detail-section active"><Steps title="Functional parity" values={["Compare schemas, types, row counts and record-level reconciliation.", "Test nulls, expressions, joins and rejected-row behavior using edge cases.", "Validate every parameter combination and conditional route."]}/><Steps title="Operational acceptance" values={["Confirm identities, bindings, permissions and configuration.", "Test retries, restart, idempotency, logging and alerting.", "Measure runtime and capacity with authorized representative volumes."]}/><Steps title="Cutover and rollback" values={["Agree acceptance thresholds and owner sign-off.", "Run source and target in parallel where authorized.", "Retain a tested rollback route until parity is accepted."]}/></section>;
  return <Deployment
    key={item.path}
    item={item}
    candidates={props.candidates}
    runId={props.runId}
    request={props.request}
  />;
}

function Steps({title, values}: {title: string; values: string[]}) {
  return <div className="summary-box"><h3>{title}</h3><div className="step-list">{values.map((value, index) => <div className="step-row" key={value}><span className="check">{index + 1}</span><span>{value}</span></div>)}</div></div>;
}
