/** Monitoring runs: how far the score and the features had moved at each run, and how many alerts it raised. */
import type { AlertItem, AlertsData } from "../../api/types";
import { fmtAuc, fmtDateTime } from "../../lib/format";
import { DefBadge } from "../Operate/definitions";
import type { Thresholds } from "../Operate/thresholds";
import { Card, DataTable, EmptyState, Pill, TimeAgo, type Column } from "../ui";
import { psiState, subjectLabel } from "./logic";

type Run = AlertsData["monitoring_runs"][number];

function PsiCell({ value, th, subject }: { value: number | null; th: Thresholds; subject?: string | null }) {
  if (value == null) return <span className="faint">—</span>;
  const state = psiState(value, th);
  return (
    <span className="row" style={{ gap: 6, justifyContent: "flex-end" }}>
      <span className="num">{fmtAuc(value, 3)}</span>
      {subject && <span className="xs muted">({subject})</span>}
      {state && <Pill tone={state === "alert" ? "crit" : state === "warning" ? "warn" : "neutral"}>{state}</Pill>}
    </span>
  );
}

/** The feature behind a run's largest feature PSI, when an alert of that run carries the same value. */
function worstFeature(run: Run, alerts: AlertItem[]): string | null {
  const t = Date.parse(run.ts);
  const hit = alerts.find((a) => a.kind === "psi" && a.subject !== "score" && Math.abs(Date.parse(a.ts) - t) < 2000 && run.max_feature_psi != null && Math.abs(a.value - run.max_feature_psi) < 1e-9);
  return hit ? subjectLabel(hit.subject) : null;
}

export function RunsTable({ runs, alerts, th }: { runs: Run[]; alerts: AlertItem[]; th: Thresholds }) {
  const columns: Column<Run>[] = [
    {
      key: "ts",
      header: "Run",
      render: (r) => (
        <span className="nowrap" title={fmtDateTime(r.ts)}>
          <TimeAgo iso={r.ts} />
        </span>
      ),
      sort: (r) => r.ts,
    },
    { key: "def", header: "Definition of default", render: (r) => <DefBadge version={r.definition_version} /> },
    { key: "score", header: "Score PSI", align: "right", render: (r) => <PsiCell value={r.score_psi} th={th} />, sort: (r) => r.score_psi },
    {
      key: "feature",
      header: "Largest feature PSI",
      align: "right",
      render: (r) => <PsiCell value={r.max_feature_psi} th={th} subject={worstFeature(r, alerts)} />,
      sort: (r) => r.max_feature_psi,
    },
    { key: "alerts", header: "Alerts raised", align: "right", render: (r) => <span className="num">{r.alerts}</span>, sort: (r) => r.alerts },
  ];
  return (
    <Card flush kind="measured">
      <DataTable
        rows={runs}
        columns={columns}
        rowKey={(r) => r.ts}
        initialSort={{ key: "ts", dir: "desc" }}
        empty={<EmptyState title="Monitoring has not run yet">Each run of the monitoring job adds a row here.</EmptyState>}
      />
    </Card>
  );
}
