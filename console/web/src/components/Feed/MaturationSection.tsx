/**
 * Maturation per definition of default: how many loans have an outcome under each definition, how many of those
 * defaulted, and why the rest are excluded. Rows are separate definitions, never one comparison axis: the rates differ
 * because the definitions differ.
 */
import type { FeedData } from "../../api/types";
import { checkLabel, fmtNum, fmtPct } from "../../lib/format";
import { DefBadge } from "../Operate/definitions";
import { Card, DataTable, EmptyState, Pill, Section, type Column } from "../ui";
import "./Feed.css";

type Row = FeedData["maturation"][number];

const EXCLUSION_LABEL: Record<string, string> = {
  unseasoned: "Not yet seasoned",
  early_payoff: "Paid off early",
  fraud_confirmed: "Confirmed fraud",
  deceased: "Deceased",
};
const EXCLUSION_HINT: Record<string, string> = {
  unseasoned: "Fewer months of performance than the definition requires, so the outcome is not known yet",
  early_payoff: "Paid off within the definition's early-payoff window",
  fraud_confirmed: "Confirmed fraud is excluded from the default label",
  deceased: "Deceased borrowers are excluded from the default label",
};

function Exclusions({ excluded }: { excluded: Record<string, number> }) {
  const entries = Object.entries(excluded).sort((a, b) => b[1] - a[1]);
  if (!entries.length) return <span className="faint">none</span>;
  return (
    <span className="feed-excl">
      {entries.map(([k, n]) => (
        <span key={k} title={EXCLUSION_HINT[k]}>
          {EXCLUSION_LABEL[k] ?? checkLabel(k)} <b>{fmtNum(n)}</b>
        </span>
      ))}
    </span>
  );
}

export function MaturationSection({ rows, activeVersion }: { rows: Row[]; activeVersion: string | null | undefined }) {
  const columns: Column<Row>[] = [
    {
      key: "def",
      header: "Definition of default",
      render: (r) => (
        <span className="row" style={{ gap: 6 }}>
          <DefBadge version={r.definition_version} />
          {r.definition_version === activeVersion && <Pill tone="accent">active</Pill>}
        </span>
      ),
      sort: (r) => (r.definition_version === activeVersion ? 0 : 1),
    },
    { key: "eligible", header: "Eligible loans", align: "right", render: (r) => <span className="num">{fmtNum(r.n_eligible)}</span>, sort: (r) => r.n_eligible },
    { key: "defaults", header: "Defaults", align: "right", render: (r) => <span className="num">{fmtNum(r.n_default)}</span>, sort: (r) => r.n_default },
    { key: "rate", header: "Default rate", align: "right", render: (r) => <span className="num">{fmtPct(r.default_rate, 1)}</span>, sort: (r) => r.default_rate },
    {
      key: "excl",
      header: "Excluded loans",
      render: (r) => <Exclusions excluded={r.excluded} />,
      sort: (r) => Object.values(r.excluded).reduce((a, b) => a + b, 0),
    },
  ];
  return (
    <Section
      title="Maturation under each definition"
      note="A loan is eligible once its outcome is known under the definition: it has been observed for the full window and is not excluded. Default rates differ between definitions because the definitions differ, so read each row on its own."
    >
      {rows.length === 0 ? (
        <EmptyState title="No label statistics yet">They appear after the pipeline builds labels for a definition of default.</EmptyState>
      ) : (
        <Card flush kind="measured">
          <DataTable rows={rows} columns={columns} rowKey={(r) => r.definition_version} initialSort={{ key: "def", dir: "asc" }} />
        </Card>
      )}
    </Section>
  );
}
