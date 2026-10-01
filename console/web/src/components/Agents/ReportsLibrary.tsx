/** Library of agent reports with filters that live in the query string. Everything here is an agent's claim. */
import { useMemo } from "react";
import { Link } from "react-router-dom";
import type { ReportMeta } from "../../api/types";
import { fmtDateTime, refLabel } from "../../lib/format";
import { Card, DataTable, EmptyState, TimeAgo, links } from "../ui";
import { DefChip, FilterSelect, VerdictPill, kindLabel, roleLabel, useUrlFilters, type FilterOption } from "./shared";

const KEYS = ["author", "kind", "cycle", "verdict"] as const;

/** "All (n)" followed by one option per distinct value, in first-seen order (the list is newest first). */
function options(reports: ReportMeta[], pick: (r: ReportMeta) => string | null, label: (v: string) => string, allLabel: string, missing?: { value: string; label: string }): FilterOption[] {
  const counts = new Map<string, number>();
  let none = 0;
  for (const r of reports) {
    const v = pick(r);
    if (v == null || v === "") none += 1;
    else counts.set(v, (counts.get(v) ?? 0) + 1);
  }
  const out: FilterOption[] = [{ value: "", label: `${allLabel} (${reports.length})` }];
  counts.forEach((n, v) => out.push({ value: v, label: `${label(v)} (${n})` }));
  if (missing && none) out.push({ value: missing.value, label: `${missing.label} (${none})` });
  return out;
}

export function ReportsLibrary({ reports }: { reports: ReportMeta[] }) {
  const f = useUrlFilters(KEYS);
  const opts = useMemo(
    () => ({
      author: options(reports, (r) => r.author, roleLabel, "All authors"),
      kind: options(reports, (r) => r.kind, kindLabel, "All kinds"),
      cycle: options(reports, (r) => r.cycle_id, (v) => v, "All cycles"),
      verdict: options(reports, (r) => r.verdict, (v) => v, "Any verdict", { value: "none", label: "No verdict" }),
    }),
    [reports],
  );
  const rows = reports.filter(
    (r) =>
      (!f.values.author || r.author === f.values.author) &&
      (!f.values.kind || r.kind === f.values.kind) &&
      (!f.values.cycle || r.cycle_id === f.values.cycle) &&
      (!f.values.verdict || (f.values.verdict === "none" ? !r.verdict : r.verdict === f.values.verdict)),
  );
  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="row" style={{ alignItems: "flex-end", gap: 12 }}>
        <FilterSelect label="Author" value={f.values.author} onChange={(v) => f.set("author", v)} options={opts.author} />
        <FilterSelect label="Kind" value={f.values.kind} onChange={(v) => f.set("kind", v)} options={opts.kind} />
        <FilterSelect label="Cycle" value={f.values.cycle} onChange={(v) => f.set("cycle", v)} options={opts.cycle} />
        <FilterSelect label="Verdict" value={f.values.verdict} onChange={(v) => f.set("verdict", v)} options={opts.verdict} />
        {f.active && (
          <button type="button" className="btn small" onClick={f.clear}>
            Clear filters
          </button>
        )}
        <span className="small muted" style={{ marginLeft: "auto" }}>
          {rows.length} of {reports.length} reports
        </span>
      </div>
      <Card flush kind="proposed">
        <DataTable
          rows={rows}
          rowKey={(r) => r.report_id}
          initialSort={{ key: "created", dir: "desc" }}
          empty={
            <EmptyState
              title={reports.length ? "No reports match these filters" : "No reports yet"}
              action={
                reports.length ? (
                  <button type="button" className="btn small" onClick={f.clear}>
                    Clear filters
                  </button>
                ) : undefined
              }
            >
              {reports.length ? "Change or clear a filter to see more." : "Agents write reports during each improvement cycle; they are listed here as soon as a cycle has run."}
            </EmptyState>
          }
          columns={[
            {
              key: "title",
              header: "Report",
              render: (r) => (
                <div className="stack" style={{ gap: 2, minWidth: 180 }}>
                  <Link to={links.report(r.report_id)}>{r.title || r.report_id}</Link>
                  <span className="xs muted mono">{r.report_id}</span>
                </div>
              ),
              sort: (r) => r.title,
            },
            { key: "author", header: "Author", render: (r) => roleLabel(r.author), sort: (r) => r.author },
            { key: "kind", header: "Kind", render: (r) => kindLabel(r.kind), sort: (r) => r.kind },
            {
              key: "candidate",
              header: "Candidate",
              render: (r) =>
                r.candidate_ref ? (
                  <Link to={links.approval(r.candidate_ref)} title={r.candidate_ref}>
                    {refLabel(r.candidate_ref)}
                  </Link>
                ) : (
                  <span className="muted">—</span>
                ),
              sort: (r) => r.candidate_ref,
            },
            {
              key: "cycle",
              header: "Cycle",
              render: (r) => (r.cycle_id ? <Link className="mono nowrap" to={links.cycle(r.cycle_id)}>{r.cycle_id}</Link> : "—"),
              sort: (r) => r.cycle_id,
            },
            { key: "definition", header: "Definition", render: (r) => <DefChip version={r.definition_version} />, sort: (r) => r.definition_version },
            { key: "verdict", header: <span title="The agent's own opinion of the candidate, not a measurement">Verdict</span>, render: (r) => <VerdictPill verdict={r.verdict} />, sort: (r) => r.verdict },
            {
              key: "created",
              header: "Written",
              render: (r) => (
                <span title={fmtDateTime(r.created_at)}>
                  <TimeAgo iso={r.created_at} />
                </span>
              ),
              sort: (r) => r.created_at,
            },
          ]}
        />
      </Card>
    </div>
  );
}
