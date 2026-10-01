/**
 * The time splits the labels are cut into: train, validation and out-of-time. The out-of-time split is the holdout:
 * only the promotion gate reads it, and only a limited number of times, so a model cannot be tuned against it.
 */
import type { DefinitionVersion } from "../../api/types";
import { fmtNum, fmtPct, fmtPp } from "../../lib/format";
import { Card, DataTable, EmptyState, KindTag, type Column } from "../ui";

interface SplitRow {
  key: "train" | "validation" | "oot";
  label: string;
  range: [string, string];
  n: number | null;
  rate: number | null;
  use: string;
}

/** Months in an inclusive "YYYY-MM" range ("2024-08" to "2024-12" is 5). */
function months([from, to]: [string, string]): number {
  const [fy, fm] = from.split("-").map(Number);
  const [ty, tm] = to.split("-").map(Number);
  const n = (ty - fy) * 12 + (tm - fm) + 1;
  return Number.isFinite(n) && n > 0 ? n : 1;
}

export function SplitsSection({ def }: { def: DefinitionVersion }) {
  const split = def.split;
  if (!split) {
    return (
      <EmptyState title="No time splits have been built for this definition">
        The splits stage divides the labelled loans by origination month into train, validation and out-of-time periods when the definition is applied. Nothing has been recorded for
        this version yet.
      </EmptyState>
    );
  }
  const rows: SplitRow[] = [
    { key: "train", label: "Train", range: split.train, n: split.n.train ?? null, rate: split.default_rate.train ?? null, use: "Models are fitted on these loans." },
    {
      key: "validation",
      label: "Validation",
      range: split.validation,
      n: split.n.validation ?? null,
      rate: split.default_rate.validation ?? null,
      use: "The harness checks every candidate here. Each test makes the next one harder to pass.",
    },
    {
      key: "oot",
      label: "Out-of-time (holdout)",
      range: split.oot,
      n: split.n.oot ?? null,
      rate: split.default_rate.oot ?? null,
      use: "Read only by the promotion gate, a limited number of times.",
    },
  ];
  const columns: Column<SplitRow>[] = [
    { key: "split", header: "Split", render: (r) => <strong>{r.label}</strong> },
    {
      key: "period",
      header: "Loans originated",
      render: (r) => (
        <span className="nowrap">
          {r.range[0]} to {r.range[1]} <span className="xs muted">({months(r.range)} months)</span>
        </span>
      ),
    },
    { key: "n", header: "Loans", align: "right", render: (r) => fmtNum(r.n) },
    { key: "rate", header: "Default rate", align: "right", render: (r) => fmtPct(r.rate) },
    { key: "use", header: "What it is for", render: (r) => <span className="small muted">{r.use}</span> },
  ];
  const valRate = rows[1].rate;
  const ootRate = rows[2].rate;
  return (
    <div className="stack" style={{ gap: "var(--gap)" }}>
      <Card kind="measured">
        <div className="small muted" style={{ marginBottom: 8 }}>
          <KindTag kind="measured" /> Loans by origination month; each block is as wide as its number of months. The loans in each split are labelled under this definition.
        </div>
        <div className="definition-detail-strip" role="img" aria-label="Train, validation and out-of-time periods, each as wide as its number of months">
          {rows.map((r) => (
            <div key={r.key} className={`definition-detail-seg ${r.key}`} style={{ flexGrow: months(r.range), flexShrink: 1, flexBasis: 0 }}>
              <div className="small">
                <strong>{r.label}</strong>
              </div>
              <div className="xs muted">
                {r.range[0]} to {r.range[1]}
              </div>
            </div>
          ))}
        </div>
      </Card>
      <Card flush kind="measured">
        <DataTable rows={rows} columns={columns} rowKey={(r) => r.key} />
      </Card>
      <div className="small muted definition-detail-note">
        The out-of-time split is the holdout. No agent and no validation check reads it: only the promotion gate does, and only a limited number of times, so a model cannot be
        tuned against it. The figures above are aggregate counts for orientation; row-level holdout labels are never shown in this console.
        {valRate != null && ootRate != null && ` The out-of-time default rate is ${fmtPp(ootRate - valRate, 1)} ${ootRate >= valRate ? "above" : "below"} the validation rate, so validation results should not be read as the rate the model will see on newer loans.`}
      </div>
    </div>
  );
}
