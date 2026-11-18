import { useId, useMemo, useState } from "react";
import type { AssessmentResult } from "./App";
import type { EvidenceResponse } from "./evidence-types";
import {
  buildEvidenceRows,
  evidenceColumns,
  evidenceTabs,
  nameOf,
  platformLabel,
  statusClass,
  waveDefinitions,
  waveLabel,
} from "./workspace-model";

type Item = AssessmentResult["assessments"][number];

export function Filters(props: {
  search: string; setSearch: (v: string) => void; complexity: string; setComplexity: (v: string) => void;
  target: string; setTarget: (v: string) => void; stage: string; setStage: (v: string) => void;
  platform: string; setPlatform: (v: string) => void; platforms: string[];
  targets: string[]; bands: string[]; clear: () => void;
}) {
  const searchId = useId();
  return <div className="toolbar workflow-filters" role="search" aria-label="Workflow filters"><div className="field"><label className="sr-only" htmlFor={searchId}>Search workflows</label><input id={searchId} type="search" placeholder="Search workflows" value={props.search} onChange={e => props.setSearch(e.target.value)}/></div>
    <select aria-label="Complexity filter" value={props.complexity} onChange={e => props.setComplexity(e.target.value)}><option value="">All complexity</option>{props.bands.map(value => <option key={value}>{value}</option>)}</select>
    <select aria-label="Fabric target filter" value={props.target} onChange={e => props.setTarget(e.target.value)}><option value="">All Fabric targets</option>{props.targets.map(value => <option key={value}>{value}</option>)}</select>
    <select aria-label="Source platform filter" value={props.platform} onChange={e => props.setPlatform(e.target.value)}><option value="">All source platforms</option>{props.platforms.map(value => <option key={value} value={value}>{platformLabel(value)}</option>)}</select>
    <select aria-label="Migration wave filter" value={props.stage} onChange={e => props.setStage(e.target.value)}><option value="">All waves</option>{waveDefinitions.map(wave => <option key={wave.value} value={wave.value}>{wave.label}</option>)}</select>
    <button className="secondary-button" onClick={props.clear}>Clear filters</button></div>;
}

export function WorkflowTable({items, open}: {
  items: Item[];
  open: (item: Item, trigger: HTMLElement) => void;
}) {
  const [page, setPage] = useState(0);
  return <><div className="table-wrap"><table><thead><tr>{["Workflow", "Source", "Complexity", "Fabric target", "Approach", "Remaining effort", "Stage", "Key issue"].map(value => <th key={value}>{value}</th>)}</tr></thead>
    <tbody>{items.slice(page * 50, page * 50 + 50).map(item => <tr key={item.path}>
      <td><button className="workflow-open-button" aria-label={`Open workflow ${nameOf(item.path)}`} onClick={e => open(item, e.currentTarget)}><span className="workflow-name">{nameOf(item.path)}</span><span className="workflow-purpose">{item.path}</span></button></td><td><span className="target-chip">{platformLabel(item.source_platform)}</span></td><td><span className={`status ${statusClass(item.complexity_band)}`}><span className="status-dot"/>{item.complexity_band}</span></td><td><span className="target-chip">{item.recommended_target}</span></td><td>{item.recommended_target === "Manual rework" || item.unsupported_tools.length ? "Requires redesign" : "Rewrite in Fabric"}</td><td>{item.estimated_effort_days.toFixed(1)} days</td><td>{waveLabel(item.migration_wave)}</td><td>{item.recommendation_reason}</td></tr>)}</tbody></table></div>
    <div className="evidence-summary"><span>Showing {items.length ? page * 50 + 1 : 0}-{Math.min(items.length, (page + 1) * 50)} of {items.length} matching workflows.</span><div className="pagination"><button disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button><span>Page {page + 1}</span><button disabled={(page + 1) * 50 >= items.length} onClick={() => setPage(page + 1)}>Next</button></div></div></>;
}

export function Tabs({labels, active, setActive, label}: {
  labels: readonly string[];
  active: number;
  setActive: (index: number) => void;
  label: string;
}) {
  return <nav className="detail-tabs" role="tablist" aria-label={label}>{labels.map((value, index) => <button key={value} role="tab" aria-selected={active === index} tabIndex={active === index ? 0 : -1} className={active === index ? "active" : ""} onClick={() => setActive(index)} onKeyDown={e => {
    const delta = ["ArrowRight", "ArrowDown"].includes(e.key) ? 1 : ["ArrowLeft", "ArrowUp"].includes(e.key) ? -1 : 0;
    if (delta) {e.preventDefault(); const next = (index + delta + labels.length) % labels.length; setActive(next); e.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("button")[next].focus();}
  }}>{value}</button>)}</nav>;
}

export function EvidenceRegister({tab, data, items, search, workflow, page, setPage, exportRows}: {
  tab: number; data: EvidenceResponse | null; items: Item[]; search: string; workflow: string; page: number;
  setPage: (v: number) => void; exportRows: (name: string, headings: string[], rows: string[][]) => void;
}) {
  const columns = useMemo(() => [...(evidenceColumns[tab] ?? [])], [tab]);
  const rows = useMemo(() => buildEvidenceRows(tab, data, items), [tab, data, items]);
  const filtered = useMemo(() => {
    const query = search.toLowerCase();
    return rows.filter(row =>
      (!workflow || row[0] === workflow)
      && (!query || row.join(" ").toLowerCase().includes(query))
    );
  }, [rows, workflow, search]);
  return <><button className="secondary-button register-export" disabled={!filtered.length} onClick={() => exportRows("evidence.csv", columns, filtered)}>Export current register</button>
    <div className="table-wrap"><table><thead><tr>{columns.map(value => <th key={value}>{value}</th>)}</tr></thead><tbody>{filtered.slice(page * 50, page * 50 + 50).map((row, index) => <tr key={`${page}-${index}`}>{row.map((cell, col) => <td key={col}>{col === 0 ? nameOf(cell) : cell}</td>)}</tr>)}</tbody></table></div>
    <div className="evidence-summary"><span>{evidenceTabs[tab]}: showing {filtered.length ? page * 50 + 1 : 0}-{Math.min((page + 1) * 50, filtered.length)} of {filtered.length} matching records.</span><div className="pagination"><button disabled={!page} onClick={() => setPage(page - 1)}>Previous</button><span>Page {page + 1}</span><button disabled={(page + 1) * 50 >= filtered.length} onClick={() => setPage(page + 1)}>Next</button></div></div>
    {data && (data.truncated || data.workflows.some(item => item.truncated)) && <div className="notice">
      Counts refer to captured records: {data.workflows.length} of {data.total_workflows} workflows,
      and {data.workflows.reduce((sum, item) => sum + item.nodes.length, 0)} of {data.workflows.reduce((sum, item) => sum + item.node_count, 0)} nodes within those workflows.
      Inspect an individual workflow for detailed evidence.
    </div>}
  </>;
}
