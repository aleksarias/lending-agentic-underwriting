/**
 * Production evidence: how the loans the decision API approved actually performed, once matured under the active
 * definition of default. Predicted (the PD each was approved at) against realized, by deciding model, risk band and
 * vintage. Declined applications have no outcome, so ranking quality here is among approved loans only.
 */
import type { ProductionEvidence, ProductionRow } from "../../api/types";
import { fmtAuc, fmtNum, fmtPct } from "../../lib/format";
import { Card, DataTable, KeyValue, Pill, type Column } from "../ui";

function calibrationTone(r: ProductionRow): "good" | "warn" | "crit" | "neutral" {
  const c = r.calibration_ratio;
  if (c == null || r.n_matured < 50) return "neutral";
  if (c >= 0.8 && c <= 1.25) return "good";
  return c >= 0.6 && c <= 1.5 ? "warn" : "crit";
}

export function productionSentence(p: ProductionEvidence): string {
  const o = p.overall;
  if (!o || o.n_matured === 0) return `${fmtNum(o?.n_booked ?? 0)} loans booked; none has matured under the active definition yet.`;
  const cal = o.predicted_pd ? ` against ${fmtPct(o.predicted_pd, 1)} predicted at approval` : "";
  const auc = o.auc != null ? `; ranking among matured loans AUC ${fmtAuc(o.auc, 3)}` : "";
  return `${fmtNum(o.n_matured)} of ${fmtNum(o.n_booked)} booked loans have matured (performance through ${p.as_of_month}): ${fmtPct(o.realized_rate, 1)} defaulted${cal}${auc}.`;
}

const columns = (label: string, render: (r: ProductionRow) => string): Column<ProductionRow>[] => [
  { key: "key", header: label, render: (r) => render(r), sort: (r) => r.key },
  { key: "booked", header: "Booked", align: "right", render: (r) => fmtNum(r.n_booked), sort: (r) => r.n_booked },
  { key: "matured", header: "Matured", align: "right", render: (r) => fmtNum(r.n_matured), sort: (r) => r.n_matured },
  { key: "pred", header: "Predicted", align: "right", render: (r) => fmtPct(r.predicted_pd, 1), sort: (r) => r.predicted_pd },
  { key: "real", header: "Realized", align: "right", render: (r) => fmtPct(r.realized_rate, 1), sort: (r) => r.realized_rate },
  {
    key: "cal",
    header: "Realized ÷ predicted",
    align: "right",
    render: (r) => (r.calibration_ratio != null ? <Pill tone={calibrationTone(r)}>{r.calibration_ratio.toFixed(2)}</Pill> : "—"),
    sort: (r) => r.calibration_ratio,
  },
  { key: "auc", header: "AUC", align: "right", render: (r) => (r.auc != null ? fmtAuc(r.auc, 3) : "—"), sort: (r) => r.auc },
];

export function ProductionEvidenceView({ p }: { p: ProductionEvidence }) {
  const o = p.overall;
  return (
    <div className="stack">
      <Card kind="measured">
        <p style={{ marginTop: 0 }}>{productionSentence(p)}</p>
        {o && (
          <KeyValue
            items={[
              ["Defaults among matured loans", `${fmtNum(o.n_defaults)} of ${fmtNum(o.n_matured)}`],
              ["Brier score", o.brier != null ? o.brier.toFixed(4) : "—"],
              ["Definition", <span key="d" className="mono">{p.definition_version.slice(0, 8)}</span>],
            ]}
          />
        )}
        <div className="xs muted">
          Approved loans only: declined applications have no outcome, so these numbers say how well approvals were priced and ranked, not how good the declines were.
        </div>
      </Card>
      <Card flush title="By deciding model">
        <DataTable rows={p.models} rowKey={(r) => r.key} columns={columns("Model", (r) => (r.key === "legacy" ? "legacy policy" : `production v${r.key}`))} />
      </Card>
      <Card flush title="By risk band at approval">
        <DataTable rows={p.bands} rowKey={(r) => r.key} initialSort={{ key: "key", dir: "asc" }} columns={columns("Band", (r) => `Band ${r.key}`)} />
      </Card>
      <Card flush title="By vintage (booking month)">
        <DataTable rows={p.vintages} rowKey={(r) => r.key} initialSort={{ key: "key", dir: "asc" }} columns={columns("Vintage", (r) => r.key)} maxHeight={360} />
      </Card>
    </div>
  );
}
