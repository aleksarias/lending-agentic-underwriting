/** Every recorded approval or rejection, promotions and definition changes together, newest first. */
import { Link } from "react-router-dom";
import type { ApprovalRecord } from "../../api/types";
import { fmtDateTime, refLabel } from "../../lib/format";
import { DefBadge } from "../Operate/definitions";
import { Card, DataTable, EmptyState, Pill, TimeAgo, links, type Column } from "../ui";
import { Rationale } from "./Rationale";

const KIND_LABEL: Record<ApprovalRecord["kind"], string> = { promotion: "Promotion", definition: "Definition change" };

function DecisionPill({ decision }: { decision: string }) {
  if (decision === "approve") return <Pill tone="good">Approved</Pill>;
  if (decision === "reject") return <Pill tone="crit">Rejected</Pill>;
  return <Pill>{decision || "unknown"}</Pill>;
}

function Reference({ r }: { r: ApprovalRecord }) {
  if (r.kind === "promotion") {
    return (
      <span className="stack" style={{ gap: 4 }}>
        <Link to={links.approval(r.ref)}>{refLabel(r.ref)} evidence</Link>
        <span className="xs muted row" style={{ gap: 6 }}>
          evaluated under <DefBadge version={r.definition_version} />
        </span>
      </span>
    );
  }
  return <DefBadge version={r.ref} />;
}

export function HistoryTable({ rows }: { rows: ApprovalRecord[] }) {
  const columns: Column<ApprovalRecord>[] = [
    {
      key: "ts",
      header: "When",
      render: (r) => (
        <span className="nowrap" title={fmtDateTime(r.ts)}>
          <TimeAgo iso={r.ts} />
        </span>
      ),
      sort: (r) => r.ts,
    },
    { key: "kind", header: "Kind", render: (r) => <span className="nowrap">{KIND_LABEL[r.kind] ?? r.kind}</span>, sort: (r) => r.kind },
    { key: "ref", header: "Reference", render: (r) => <Reference r={r} /> },
    { key: "decision", header: "Decision", render: (r) => <DecisionPill decision={r.decision} />, sort: (r) => r.decision },
    { key: "approver", header: "Approver", render: (r) => r.approver || "—", sort: (r) => r.approver },
    { key: "rationale", header: "Rationale", render: (r) => <Rationale text={r.rationale} /> },
  ];
  return (
    <Card flush>
      <DataTable
        rows={rows}
        columns={columns}
        rowKey={(r) => r.approval_id}
        initialSort={{ key: "ts", dir: "desc" }}
        empty={
          <EmptyState title="No decisions recorded yet">
            Each approval or rejection of a promotion or a definition change is listed here with who decided, when, and why.
          </EmptyState>
        }
      />
    </Card>
  );
}
