/** Every other alert: acknowledged ones, and ones raised by earlier monitoring runs that nobody acknowledged. */
import type { AlertItem } from "../../api/types";
import { fmtDateTime } from "../../lib/format";
import { DefBadge } from "../Operate/definitions";
import type { Thresholds } from "../Operate/thresholds";
import { Card, DataTable, EmptyState, Pill, TimeAgo, type Column } from "../ui";
import { AlertTitle } from "./AlertTitle";
import { AlertSummaryLine } from "./OpenAlerts";
import { SEVERITY_LABEL, alertTitle } from "./logic";

const TONE = { high: "crit", medium: "warn", low: "neutral" } as const;

export function AlertHistory({ alerts, th }: { alerts: AlertItem[]; th: Thresholds }) {
  const columns: Column<AlertItem>[] = [
    {
      key: "ts",
      header: "Raised",
      render: (a) => (
        <span className="nowrap" title={fmtDateTime(a.ts)}>
          <TimeAgo iso={a.ts} />
        </span>
      ),
      sort: (a) => a.ts,
    },
    { key: "sev", header: "Severity", render: (a) => <Pill tone={TONE[a.severity]}>{SEVERITY_LABEL[a.severity]}</Pill>, sort: (a) => ({ high: 0, medium: 1, low: 2 })[a.severity] },
    { key: "alert", header: "Alert", render: (a) => <strong className="small"><AlertTitle a={a} /></strong>, sort: (a) => alertTitle(a) },
    { key: "measure", header: "Measured", render: (a) => <AlertSummaryLine a={a} th={th} /> },
    { key: "def", header: "Definition of default", render: (a) => <DefBadge version={a.definition_version} /> },
    {
      key: "status",
      header: "Acknowledged by",
      render: (a) => (a.acknowledged ? <span>{a.ack_by ?? "someone (name not recorded)"}</span> : <span className="muted">nobody: a newer monitoring run has replaced it</span>),
      sort: (a) => (a.acknowledged ? 1 : 0),
    },
  ];
  return (
    <Card flush kind="measured">
      <DataTable
        rows={alerts}
        columns={columns}
        rowKey={(a) => a.id}
        initialSort={{ key: "ts", dir: "desc" }}
        maxHeight={460}
        empty={<EmptyState title="No earlier alerts">Acknowledged alerts and alerts from older monitoring runs are kept here.</EmptyState>}
      />
    </Card>
  );
}
