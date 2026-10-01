/**
 * Adverse impact on actual decisions: approval and decline rates by group over the recent window of decisions, with
 * the adverse impact ratio against the reference group. Race and ethnicity are ESTIMATED (surname-based) and shown next
 * to the synthetic truth, so the estimate's error is visible; age 62+ comes from the application.
 */
import type { DecisionFairness } from "../../api/types";
import { fmtAuc, fmtNum, fmtPct } from "../../lib/format";
import { Card, DataTable, Pill } from "../ui";
import { classLabel } from "./labels";

type Row = { group: string; est?: DecisionFairness["rows"][number]; truth?: DecisionFairness["rows"][number] };

function air(r: DecisionFairness["rows"][number] | undefined, threshold: number) {
  if (!r || r.air == null) return <span className="muted">—</span>;
  return <Pill tone={r.below_threshold ? "crit" : r.air < threshold + 0.05 ? "warn" : "good"}>{fmtAuc(r.air, 2)}</Pill>;
}

export function DecisionFairnessView({ d, threshold }: { d: DecisionFairness; threshold: number }) {
  const race: Row[] = [];
  for (const r of d.rows.filter((x) => x.attribute === "race_ethnicity")) {
    let row = race.find((x) => x.group === r.group);
    if (!row) race.push((row = { group: r.group }));
    if (r.method === "surname_estimate") row.est = r;
    if (r.method === "synthetic_truth") row.truth = r;
  }
  const age = d.rows.filter((x) => x.attribute === "age_62_plus");
  const flagged = d.rows.filter((r) => r.below_threshold && r.method !== "synthetic_truth");
  return (
    <div className="stack">
      <p className="small" style={{ margin: 0 }}>
        {fmtNum(d.n_decisions)} decisions over the last {d.window_days} days.{" "}
        {flagged.length
          ? `${flagged.length} group${flagged.length === 1 ? " is" : "s are"} below the ${fmtAuc(threshold, 2)} adverse impact ratio on the measures used in production.`
          : `No group is below the ${fmtAuc(threshold, 2)} adverse impact ratio on the measures used in production.`}
      </p>
      <Card flush title={`${classLabel("race_ethnicity")}: estimated, next to the synthetic truth`}>
        <DataTable
          rows={race}
          rowKey={(r) => r.group}
          columns={[
            { key: "group", header: "Group", render: (r) => r.group + (r.est?.reference_group === r.group ? " (reference)" : "") },
            { key: "n", header: "Estimated count", align: "right", render: (r) => fmtNum(r.est?.n ?? null), sort: (r) => r.est?.n },
            { key: "ar", header: "Approved (estimated)", align: "right", render: (r) => fmtPct(r.est?.approval_rate, 1), sort: (r) => r.est?.approval_rate },
            { key: "air", header: "AIR (estimated)", align: "right", render: (r) => air(r.est, threshold), sort: (r) => r.est?.air },
            { key: "tar", header: "Approved (truth)", align: "right", render: (r) => fmtPct(r.truth?.approval_rate, 1), sort: (r) => r.truth?.approval_rate },
            { key: "tair", header: "AIR (truth)", align: "right", render: (r) => air(r.truth, threshold), sort: (r) => r.truth?.air },
          ]}
        />
      </Card>
      <Card flush title={classLabel("age_62_plus")}>
        <DataTable
          rows={age}
          rowKey={(r) => r.group}
          columns={[
            { key: "group", header: "Group", render: (r) => (r.group === "true" ? "62 or older" : "under 62") + (r.reference_group === r.group ? " (reference)" : "") },
            { key: "n", header: "Decisions", align: "right", render: (r) => fmtNum(r.n), sort: (r) => r.n },
            { key: "ar", header: "Approved", align: "right", render: (r) => fmtPct(r.approval_rate, 1), sort: (r) => r.approval_rate },
            { key: "dr", header: "Declined", align: "right", render: (r) => fmtPct(r.decline_rate, 1), sort: (r) => r.decline_rate },
            { key: "air", header: "AIR", align: "right", render: (r) => air(r, threshold), sort: (r) => r.air },
          ]}
        />
      </Card>
      <div className="xs muted">{d.method_note}</div>
    </div>
  );
}
