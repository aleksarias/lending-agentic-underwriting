/**
 * Table of engineered features with expandable rows. Numbers are the feature's univariate screen under the ACTIVE
 * definition of default (training loans only; it does not use validation data and does not count as a test). The
 * expansion shows the SQL, the agent's rationale and hypothesis (proposed) and the screen under every definition.
 */
import "./features.css";
import { Fragment, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { FeatureRow } from "../../api/types";
import { fmtAuc, fmtDateTime, fmtPct } from "../../lib/format";
import { Card, CodeBlock, EmptyState, KindTag, Pill, links } from "../ui";
import { DefBadge, ModelKeyBadge, roleLabel } from "../Agents/shared";
import { FeatureDecision } from "./PeopleInput";

type Perf = FeatureRow["performance"][string];

const LEAK_TONE = { low: "good", medium: "warn", high: "crit" } as const;

export function LeakagePill({ risk }: { risk: string | null | undefined }) {
  if (!risk) return <Pill tone="neutral">not screened</Pill>;
  return <Pill tone={LEAK_TONE[risk as keyof typeof LEAK_TONE] ?? "neutral"}>{risk}</Pill>;
}

export function ProxyPill({ risk }: { risk: string | null | undefined }) {
  if (!risk) return <Pill tone="neutral">not screened</Pill>;
  return <Pill tone={risk === "high" ? "crit" : risk === "low" ? "good" : "neutral"}>{risk}</Pill>;
}

export function StatusPill({ status }: { status: string }) {
  const tone = status === "rejected" ? "crit" : ["accepted", "approved", "active"].includes(status) ? "good" : "accent";
  return <Pill tone={tone}>{status || "unknown"}</Pill>;
}

interface Col {
  key: string;
  header: ReactNode;
  align?: "r";
  sort?: (f: FeatureRow, p: Perf | undefined) => number | string | null;
  render: (f: FeatureRow, p: Perf | undefined) => ReactNode;
}

function Detail({ f, activeVersion }: { f: FeatureRow; activeVersion: string }) {
  const versions = Object.keys(f.performance);
  return (
    <div className="features-detail-grid">
      <div className="stack" style={{ gap: 12, alignContent: "start" }}>
        <div className="stack" style={{ gap: 4 }}>
          <span className="small muted">
            SQL expression, written by the agent <KindTag kind="proposed" />
          </span>
          <CodeBlock>{f.expression || "No expression recorded"}</CodeBlock>
        </div>
        <div className="row" style={{ gap: 6 }}>
          <span className="small muted">Used in:</span>
          {f.used_in.length ? f.used_in.map((k) => <ModelKeyBadge key={k} modelKey={k} />) : <span className="small">no evaluated model yet</span>}
        </div>
        <div className="small muted">
          Proposed {fmtDateTime(f.created_at)} by the {roleLabel(f.author).toLowerCase()} agent in cycle{" "}
          {f.cycle_id ? (
            <Link className="mono" to={links.cycle(f.cycle_id)}>
              {f.cycle_id}
            </Link>
          ) : (
            "unknown"
          )}
          , under <DefBadge version={f.created_under_definition} />.
        </div>
      </div>
      <div className="stack" style={{ gap: "var(--gap)", alignContent: "start" }}>
        <Card kind="proposed">
          <div className="row between" style={{ marginBottom: 6 }}>
            <strong className="small">Agent's reasoning</strong>
            <KindTag kind="proposed" />
          </div>
          <div className="stack" style={{ gap: 10 }}>
            <div>
              <div className="small muted">Hypothesis</div>
              <div>{f.hypothesis || <span className="muted">none recorded</span>}</div>
            </div>
            <div>
              <div className="small muted">Rationale</div>
              <div>{f.rationale || <span className="muted">none recorded</span>}</div>
            </div>
          </div>
        </Card>
        <Card kind="measured">
          <div className="row between" style={{ marginBottom: 6 }}>
            <strong className="small">Screen under each definition</strong>
            <KindTag kind="measured" />
          </div>
          {versions.length === 0 ? (
            <div className="small muted">Not screened yet. The pipeline screens every registered feature when a definition is applied.</div>
          ) : (
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Table (scrolls sideways when narrow)" style={{ border: 0 }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>Definition of default</th>
                    <th className="r">AUC</th>
                    <th className="r">Missing</th>
                    <th>Leakage</th>
                    <th>Proxy</th>
                  </tr>
                </thead>
                <tbody>
                  {versions.map((v) => {
                    const p = f.performance[v];
                    return (
                      <tr key={v}>
                        <td>
                          <DefBadge version={v} /> {v === activeVersion && <span className="xs muted">active</span>}
                        </td>
                        <td className="r">{fmtAuc(p.auc, 3)}</td>
                        <td className="r">{fmtPct(p.missing_rate, 1)}</td>
                        <td>
                          <LeakagePill risk={p.leakage_risk} />
                        </td>
                        <td>
                          <ProxyPill risk={p.proxy_risk} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <div className="xs muted" style={{ marginTop: 8 }}>
            Univariate AUC uses training loans only. It is a screen for signal, not validation evidence, and it is not counted as a test.
          </div>
        </Card>
      </div>
    </div>
  );
}

export function FeatureTable({ rows, activeVersion, initiallyOpen }: { rows: FeatureRow[]; activeVersion: string; initiallyOpen: string[] }) {
  const [open, setOpen] = useState<Set<string>>(() => new Set(initiallyOpen));
  const [sort, setSort] = useState<{ key: string; dir: "asc" | "desc" } | null>(null);
  const toggle = (name: string) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(name)) n.delete(name);
      else n.add(name);
      return n;
    });

  const cols: Col[] = [
    {
      key: "name",
      header: "Feature",
      sort: (f) => f.name,
      render: (f) => {
        const isOpen = open.has(f.name);
        return (
          <div className="stack" style={{ gap: 2 }}>
            <button type="button" className="features-toggle" aria-expanded={isOpen} aria-controls={`feature-${f.name}`} onClick={() => toggle(f.name)}>
              <span className="features-chevron" aria-hidden>
                {isOpen ? "▾" : "▸"}
              </span>
              <span className="mono features-name">{f.name}</span>
            </button>
            <span className="features-by" style={{ paddingLeft: 16 }}>
              {roleLabel(f.author)} agent ·{" "}
              {f.cycle_id ? (
                <Link className="mono nowrap" to={links.cycle(f.cycle_id)}>
                  {f.cycle_id}
                </Link>
              ) : (
                "no cycle"
              )}
            </span>
          </div>
        );
      },
    },
    { key: "def", header: "Created under", sort: (f) => f.created_under_definition, render: (f) => <DefBadge version={f.created_under_definition} /> },
    { key: "status", header: "Status", sort: (f) => f.status, render: (f) => <StatusPill status={f.status} /> },
    {
      key: "auc",
      header: <span title="AUC of the feature alone on training loans under the active definition. A screen, not validation evidence.">AUC, alone</span>,
      align: "r",
      sort: (_f, p) => p?.auc ?? null,
      render: (_f, p) => (p ? fmtAuc(p.auc, 3) : "—"),
    },
    { key: "missing", header: "Missing", align: "r", sort: (_f, p) => p?.missing_rate ?? null, render: (_f, p) => (p ? fmtPct(p.missing_rate, 1) : "—") },
    { key: "leak", header: "Leakage", sort: (_f, p) => ({ low: 0, medium: 1, high: 2 })[p?.leakage_risk as "low"] ?? null, render: (_f, p) => <LeakagePill risk={p?.leakage_risk} /> },
    { key: "proxy", header: "Proxy", sort: (_f, p) => (p?.proxy_risk === "high" ? 1 : p?.proxy_risk === "low" ? 0 : null), render: (_f, p) => <ProxyPill risk={p?.proxy_risk} /> },
    { key: "person", header: "A person's decision", sort: (f) => (f.rejected ? 1 : 0), render: (f) => <FeatureDecision f={f} /> },
    {
      key: "used",
      header: "Used in",
      sort: (f) => f.used_in.length,
      render: (f) =>
        f.used_in.length ? (
          <span className="row" style={{ gap: 4 }}>
            {f.used_in.map((k) => (
              <ModelKeyBadge key={k} modelKey={k} />
            ))}
          </span>
        ) : (
          <span className="muted">—</span>
        ),
    },
  ];

  const perfOf = (f: FeatureRow) => f.performance[activeVersion];
  const sorted = (() => {
    const col = cols.find((c) => c.key === sort?.key);
    if (!sort || !col?.sort) return rows;
    const get = col.sort;
    return [...rows].sort((a, b) => {
      const x = get(a, perfOf(a));
      const y = get(b, perfOf(b));
      if (x === y) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      const c = x < y ? -1 : 1;
      return sort.dir === "asc" ? c : -c;
    });
  })();

  if (!rows.length) return <EmptyState title="No features match these filters">Clear a filter to see the rest.</EmptyState>;
  return (
    <div className="table-wrap features-wrap" tabIndex={0} role="region" aria-label="Table (scrolls sideways when narrow)">
      <table className="data">
        <thead>
          <tr>
            {cols.map((c) => (
              <th
                key={c.key}
                className={[c.align === "r" ? "r" : "", c.sort ? "sortable" : ""].join(" ")}
                aria-sort={sort?.key === c.key ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}
                onClick={c.sort ? () => setSort((s) => (s?.key === c.key ? { key: c.key, dir: s.dir === "asc" ? "desc" : "asc" } : { key: c.key, dir: "desc" })) : undefined}
              >
                {c.header}
                {sort?.key === c.key ? (sort.dir === "asc" ? " ▲" : " ▼") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((f) => {
            const isOpen = open.has(f.name);
            return (
              <Fragment key={f.name}>
                <tr className={`features-row ${isOpen ? "open" : ""}`}>
                  {cols.map((c) => (
                    <td key={c.key} className={c.align === "r" ? "r" : ""}>
                      {c.render(f, perfOf(f))}
                    </td>
                  ))}
                </tr>
                {isOpen && (
                  <tr className="features-detail" id={`feature-${f.name}`}>
                    <td colSpan={cols.length}>
                      <div className="features-detail-inner">
                        <Detail f={f} activeVersion={activeVersion} />
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
