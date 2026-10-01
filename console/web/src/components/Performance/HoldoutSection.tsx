/** Holdout budget (how many times the promotion gate may read the holdout) and the gates that have been run. */
import { Link } from "react-router-dom";
import type { GateSummary, ModelRef, PerformanceData } from "../../api/types";
import { fmtAuc, fmtDateTime, fmtDiff, refLabel } from "../../lib/format";
import { DataTable, EmptyState, ModelBadge, Meter, Pill, Section, links, Card, type Column } from "../ui";
import { checkName, plural } from "../shared";

export function HoldoutSection({ holdout, modelOf }: { holdout: PerformanceData["holdout"]; modelOf?: (ref: string) => ModelRef | undefined }) {
  const { used, budget, gates } = holdout;
  const left = Math.max(0, budget - used);
  const columns: Column<GateSummary>[] = [
    {
      key: "candidate",
      header: "Candidate",
      render: (g) => {
        const m = modelOf?.(g.candidate_ref);
        return m ? <ModelBadge model={m} /> : <Link to={links.approval(g.candidate_ref)}>{refLabel(g.candidate_ref)}</Link>;
      },
      sort: (g) => g.candidate_ref,
    },
    { key: "ts", header: "Run (UTC)", render: (g) => <span className="small">{fmtDateTime(g.ts)}</span>, sort: (g) => g.ts },
    {
      key: "auc",
      header: "Holdout AUC",
      align: "right",
      render: (g) => (
        <Link className="num" to={links.approval(g.candidate_ref)} title="Open the approval evidence">
          {fmtAuc(g.holdout_auc)}
        </Link>
      ),
      sort: (g) => g.holdout_auc,
    },
    { key: "ref", header: "Reference holdout AUC", align: "right", render: (g) => <span className="num">{fmtAuc(g.reference_holdout_auc)}</span>, sort: (g) => g.reference_holdout_auc },
    {
      key: "diff",
      header: "Difference",
      align: "right",
      render: (g) => <span className="num">{fmtDiff(g.holdout_auc - g.reference_holdout_auc)}</span>,
      sort: (g) => g.holdout_auc - g.reference_holdout_auc,
    },
    {
      key: "checks",
      header: "Checks",
      render: (g) => {
        const all = Object.entries(g.checks);
        const failed = all.filter(([, ok]) => !ok).map(([k]) => checkName(k));
        return <span className="small">{failed.length ? `${failed.length} of ${all.length} failed: ${failed.join(", ")}` : `${all.length} of ${all.length} passed`}</span>;
      },
    },
    { key: "passed", header: "Result", render: (g) => <Pill tone={g.passed ? "good" : "crit"}>{g.passed ? "passed" : "failed"}</Pill>, sort: (g) => (g.passed ? 1 : 0) },
  ];
  return (
    <Section
      title="Holdout budget and gates"
      note="The holdout is read only by the promotion gate, and only a limited number of times per definition: every look at it makes the next result less trustworthy."
    >
      <div className="grid split">
        <Card kind="measured">
          <Meter used={used} cap={budget} label="Holdout gates used under this definition" />
          <div className="small muted" style={{ marginTop: 8 }}>
            {left === 0 ? "The budget is spent: no further gate can run under this definition." : `${plural(left, "gate")} left to run.`} The gate also re-runs the validation checks without counting a new
            validation test.
          </div>
        </Card>
        <div>
          {gates.length === 0 ? (
            <EmptyState title="No holdout gate has been run under this definition" action={<Link to="/approvals">Go to approvals</Link>}>
              The gate is run from Approvals, after a candidate passes validation and has red-team and compliance reports. It reads the holdout once and spends one of
              the {budget} budgeted reads. Nothing has been spent here.
            </EmptyState>
          ) : (
            <Card flush kind="measured">
              <DataTable rows={gates} columns={columns} rowKey={(g) => g.gate_id} initialSort={{ key: "ts", dir: "desc" }} />
            </Card>
          )}
        </div>
      </div>
    </Section>
  );
}
