/** Access checks, config versions, benchmark definitions and reports on the Settings screen. */
import { Link } from "react-router-dom";
import { useCycles } from "../../api/hooks";
import type { SettingsData, Unavailable } from "../../api/types";
import { fmtAgo, fmtDateTime, titleCase } from "../../lib/format";
import { Banner, Card, DataTable, EmptyState, Pill, TimeAgo, UnavailableState, links } from "../ui";
import { DefBadge, cycleStatus, roleLabel, useDefinitionRefs } from "../Agents/shared";

type Check = SettingsData["access_checks"][number];
type Version = SettingsData["config_versions"][number];

// ---------------------------------------------------------------------------------------------- access checks
export function accessFacts(checks: Check[]) {
  const failed = checks.filter((c) => !c.ok);
  const last = checks.map((c) => c.checked_at).sort().pop() ?? null;
  return { total: checks.length, failed, passed: checks.length - failed.length, last };
}

function problem(c: Check): string {
  if (c.expected === "deny" && c.observed === "allow") return "Access was allowed where it must be denied: the isolation is broken.";
  if (c.expected === "allow" && c.observed === "deny") return "Access was denied where it must be allowed: a needed grant is missing.";
  return `The probe could not tell (observed: ${c.observed || "nothing"}).`;
}

export function AccessChecks({ checks }: { checks: Check[] }) {
  const f = accessFacts(checks);
  if (!checks.length) {
    return (
      <EmptyState title="No access checks have been recorded">
        Run <code>lau check-access</code> to probe what each identity can and cannot read. Until it has run, isolation between the agents and protected data is not proven.
      </EmptyState>
    );
  }
  return (
    <div className="stack" style={{ gap: "var(--gap)" }}>
      {f.failed.length ? (
        <Banner tone="crit" title={`${f.failed.length} of ${f.total} access checks failed: isolation is not proven`}>
          <ul style={{ margin: "4px 0 0", paddingLeft: 18 }} className="small">
            {f.failed.map((c) => (
              <li key={`${c.role}-${c.object}`}>
                <strong>{c.role}</strong> on <span className="mono">{c.object}</span>: {problem(c)}
              </li>
            ))}
          </ul>
        </Banner>
      ) : (
        <Banner tone="good" title={`All ${f.total} access checks passed`}>
          <span className="small">
            Every probe behaved as expected when it ran <span title={fmtDateTime(f.last)}>{fmtAgo(f.last)}</span> ({fmtDateTime(f.last)}). Run <code>lau check-access</code> again after any change to grants or identities.
          </span>
        </Banner>
      )}
      <Card flush>
        <DataTable
          rows={checks}
          rowKey={(c) => `${c.role}-${c.object}`}
          initialSort={{ key: "result", dir: "asc" }}
          columns={[
            { key: "role", header: "Identity", render: (c) => <strong>{c.role}</strong>, sort: (c) => c.role },
            { key: "object", header: "Object", render: (c) => <span className="mono">{c.object}</span>, sort: (c) => c.object },
            { key: "expected", header: "Expected", render: (c) => (c.expected === "allow" ? "May read" : "Must be denied"), sort: (c) => c.expected },
            { key: "observed", header: "Observed", render: (c) => <span className="mono">{c.observed || "—"}</span>, sort: (c) => c.observed },
            {
              key: "result",
              header: "Result",
              render: (c) => (c.ok ? <Pill tone="good">As expected</Pill> : <Pill tone="crit">Failed</Pill>),
              sort: (c) => (c.ok ? 1 : 0),
            },
            {
              key: "at",
              header: "Checked",
              render: (c) => (
                <span title={fmtDateTime(c.checked_at)}>
                  <TimeAgo iso={c.checked_at} />
                </span>
              ),
              sort: (c) => c.checked_at,
            },
          ]}
        />
      </Card>
    </div>
  );
}

// ----------------------------------------------------------------------------------------------- versions
const COMPONENT_INFO: Record<string, string> = {
  thresholds: "config/thresholds.yaml",
  budgets: "config/budgets.yaml",
  models: "config/models.yaml",
  protected_classes: "config/protected_classes.yaml",
  benchmarks: "config/benchmarks.yaml",
  grants: "Database access grants for each identity, defined in code",
  code: "Git commit of the code a cycle runs (src, pyproject.toml, uv.lock)",
};

const componentLabel = (c: string) => (c.startsWith("prompt:") ? `Prompt: ${roleLabel(c.slice(7)).toLowerCase()}` : titleCase(c));
const componentInfo = (c: string) => (c.startsWith("prompt:") ? `Prompt for the ${roleLabel(c.slice(7)).toLowerCase()} agent (common instructions plus its own)` : COMPONENT_INFO[c] ?? "");

export const isDirty = (v: Version) => v.component === "code" && v.version.includes("dirty");

export function ConfigVersions({ rows }: { rows: Version[] }) {
  return (
    <Card flush>
      <DataTable
        rows={rows}
        rowKey={(v) => v.component}
        empty={<EmptyState title="No versions recorded yet">A version is recorded when a cycle starts, a definition is applied, or <code>lau versions record</code> runs.</EmptyState>}
        columns={[
          {
            key: "component",
            header: "Component",
            render: (v) => (
              <div>
                <strong>{componentLabel(v.component)}</strong>
                <div className="xs muted">{componentInfo(v.component)}</div>
              </div>
            ),
            sort: (v) => v.component,
          },
          {
            key: "version",
            header: "Version",
            render: (v) => (
              <span className="row" style={{ gap: 6 }}>
                <span className="mono">{v.version}</span>
                {isDirty(v) && (
                  <span title="The code a cycle runs had uncommitted changes when this version was recorded, so the hash does not match a git commit exactly.">
                    <Pill tone="warn">uncommitted changes</Pill>
                  </span>
                )}
              </span>
            ),
          },
          {
            key: "at",
            header: "Recorded",
            render: (v) => (
              <div title={fmtDateTime(v.recorded_at)}>
                <div className="nowrap">{fmtDateTime(v.recorded_at)}</div>
                <div className="xs muted">
                  <TimeAgo iso={v.recorded_at} />
                </div>
              </div>
            ),
            sort: (v) => v.recorded_at,
          },
          {
            key: "git",
            header: "Git commit",
            render: (v) => (v.git_sha ? <span className="mono" title={v.git_sha}>{v.git_sha.slice(0, 10)}</span> : <span className="muted">not recorded</span>),
          },
        ]}
      />
    </Card>
  );
}

// -------------------------------------------------------------------------------------------- benchmarks
export function BenchmarkDefinitions({ rows }: { rows: SettingsData["benchmarks"] }) {
  const { find } = useDefinitionRefs();
  return (
    <Card flush>
      <DataTable
        rows={rows}
        rowKey={(b) => b.key}
        empty={<EmptyState title="No benchmark definitions configured">They are listed in config/benchmarks.yaml.</EmptyState>}
        columns={[
          { key: "key", header: "Key", render: (b) => <span className="mono">{b.key}</span>, sort: (b) => b.key },
          { key: "dpd", header: "Days past due", align: "right", render: (b) => b.dpd, sort: (b) => b.dpd },
          {
            key: "version",
            header: "Frozen definition version",
            render: (b) =>
              !b.version ? (
                <span className="muted" title="The benchmark has not been computed yet">not computed yet</span>
              ) : find(b.version) ? (
                <DefBadge version={b.version} />
              ) : (
                <span className="mono" title="A frozen benchmark definition; it is not one of the definitions ever made active">{b.version.slice(0, 8)}</span>
              ),
          },
        ]}
      />
    </Card>
  );
}

// ----------------------------------------------------------------------------------------------- reports
const NOT_BUILT: Unavailable = {
  available: false,
  reason: "The monthly improvement report, the model documentation pack and exports are not generated yet.",
  requires: ["A monthly job that renders the improvement ledger into a report", "Model documentation built from the model card and its evidence"],
};

export function ReportsSection() {
  const cycles = useCycles();
  const recent = (cycles.data ?? []).slice(0, 5);
  return (
    <div className="grid cols-3">
      <Card title="Cycle reports">
        <p className="small" style={{ margin: "0 0 8px" }}>
          Every improvement cycle writes a report with its plan, outcome, agent runs and artifacts. Open a cycle to read it.
        </p>
        {cycles.isError ? (
          <div className="small muted">The cycle list could not be loaded.</div>
        ) : recent.length === 0 ? (
          <div className="small muted">{cycles.data ? "No cycle has run yet." : "Loading…"}</div>
        ) : (
          <ul className="list">
            {recent.map((c) => (
              <li key={c.cycle_id} className="item row between">
                <Link className="mono nowrap small" to={links.cycle(c.cycle_id)}>
                  {c.cycle_id}
                </Link>
                <Pill tone={cycleStatus(c.status).tone}>{cycleStatus(c.status).label}</Pill>
              </li>
            ))}
          </ul>
        )}
        <div className="small" style={{ marginTop: 8 }}>
          <Link to="/history">All cycles in History</Link>
        </div>
      </Card>
      <Card title="Agent reports" kind="proposed">
        <p className="small" style={{ margin: "0 0 8px" }}>
          Red-team, compliance, modeling, feature and data-profile reports written by the agents. They are claims to check against the evidence.
        </p>
        <Link className="small" to="/agents">
          Open the reports library
        </Link>
      </Card>
      <UnavailableState u={NOT_BUILT} title="Other reports are not available" />
    </div>
  );
}
