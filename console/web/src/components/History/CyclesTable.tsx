/** Improvement cycles, one row each: what started it, what it produced, and what the agents and harness said. */
import { Link, useNavigate } from "react-router-dom";
import type { CycleSummary, DefinitionVersion, ModelVersion, Tone } from "../../api/types";
import { fmtDateTime, fmtUsd, reviewTone, titleCase } from "../../lib/format";
import { definitionRefOf } from "../Definitions/labels";
import { DataTable, DefinitionBadge, KindTag, ModelBadge, Pill, links, type Column } from "../ui";

/** Status written by the orchestrator: running, completed, stopped_by_user, stopped_budget, failed_agent_api, failed. */
export function cycleStatus(status: string): { label: string; tone: Tone } {
  switch (status) {
    case "completed":
      return { label: "Completed", tone: "good" };
    case "running":
      return { label: "Running", tone: "accent" };
    case "stopped_by_user":
      return { label: "Stopped by a person", tone: "warn" };
    case "stopped_budget":
      return { label: "Stopped at a budget cap", tone: "warn" };
    case "failed_agent_api":
      return { label: "Failed: agent API error", tone: "crit" };
    case "failed":
      return { label: "Failed", tone: "crit" };
    default:
      return { label: titleCase(status), tone: "neutral" };
  }
}

/** Red-team and compliance verdicts are written by agents, so they read as proposed, never as measured. */
export function VerdictPill({ verdict }: { verdict: string | null }) {
  return verdict ? <Pill tone={reviewTone(verdict)}>{verdict}</Pill> : <span className="faint">none</span>;
}

export function CyclesTable({ cycles, defs, models }: { cycles: CycleSummary[]; defs: DefinitionVersion[]; models: ModelVersion[] }) {
  const navigate = useNavigate();
  const columns: Column<CycleSummary>[] = [
    { key: "started", header: "Started (UTC)", render: (c) => fmtDateTime(c.started_at), sort: (c) => c.started_at },
    {
      key: "cycle",
      header: "Cycle, reason and definition",
      render: (c) => {
        const d = defs.find((x) => x.version === c.definition_version);
        return (
          <div className="stack" style={{ gap: 3 }}>
            <Link to={links.cycle(c.cycle_id)} onClick={(e) => e.stopPropagation()}>
              {c.reason || "No reason recorded"}
            </Link>
            <span className="xs muted mono">{c.cycle_id}</span>
            <span className="history-badge-wrap">
              <DefinitionBadge def={d ? definitionRefOf(d) : null} version={c.definition_version} />
            </span>
          </div>
        );
      },
      sort: (c) => c.reason,
    },
    {
      key: "status",
      header: "Status",
      render: (c) => {
        const s = cycleStatus(c.status);
        return (
          <div>
            <Pill tone={s.tone} dot={c.status === "running"}>
              {s.label}
            </Pill>
            {c.stop_reason && <div className="xs muted">{c.stop_reason}</div>}
          </div>
        );
      },
      sort: (c) => c.status,
    },
    {
      key: "challenger",
      header: "Challenger",
      render: (c) => {
        if (!c.challenger) return <span className="faint">none proposed</span>;
        const m = models.find((x) => x.model.version === c.challenger);
        return m ? <ModelBadge model={m.model} /> : <span>v{c.challenger}</span>;
      },
      sort: (c) => (c.challenger ? Number(c.challenger) : null),
    },
    {
      key: "validation",
      header: (
        <span>
          Validation
          <br />
          <KindTag kind="measured" />
        </span>
      ),
      render: (c) =>
        c.challenger_passed_validation == null ? (
          <span className="faint">none</span>
        ) : c.challenger_passed_validation ? (
          <Pill tone="good">passed</Pill>
        ) : (
          <Pill tone="warn">did not pass</Pill>
        ),
      sort: (c) => (c.challenger_passed_validation == null ? null : c.challenger_passed_validation ? 1 : 0),
    },
    {
      key: "redteam",
      header: (
        <span>
          Red team
          <br />
          <KindTag kind="proposed" />
        </span>
      ),
      render: (c) => <VerdictPill verdict={c.redteam_verdict} />,
      sort: (c) => c.redteam_verdict,
    },
    {
      key: "compliance",
      header: (
        <span>
          Compliance
          <br />
          <KindTag kind="proposed" />
        </span>
      ),
      render: (c) => <VerdictPill verdict={c.compliance_verdict} />,
      sort: (c) => c.compliance_verdict,
    },
    { key: "spend", header: "Agent spend", align: "right", render: (c) => fmtUsd(c.anthropic_usd), sort: (c) => c.anthropic_usd },
  ];
  return (
    <DataTable
      rows={cycles}
      columns={columns}
      rowKey={(c) => c.cycle_id}
      initialSort={{ key: "started", dir: "desc" }}
      onRowClick={(c) => navigate(links.cycle(c.cycle_id))}
    />
  );
}
