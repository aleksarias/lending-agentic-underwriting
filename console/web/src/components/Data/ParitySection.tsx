/**
 * Training and serving parity: for each input of the serving model (and the cash-flow features), the population
 * stability index between the applications models were trained on and the last 30 days of decisions, with null rates
 * and means. Exact parity of the feature code itself is a release check (Decisions screen).
 */
import { useParity } from "../../api/hooks";
import { isUnavailable } from "../../api/types";
import type { ParityData } from "../../api/types";
import { fmtNum, fmtPct } from "../../lib/format";
import { Card, DataTable, Pill, QueryView, Section, UnavailableState } from "../ui";

const TONE = { ok: "good", warn: "warn", alert: "crit", missing: "crit" } as const;

function sentence(p: ParityData): string {
  const alerts = p.rows.filter((r) => r.status === "alert").length;
  const warns = p.rows.filter((r) => r.status === "warn").length;
  const missing = p.rows.filter((r) => r.status === "missing").length;
  const parts = [`${p.rows.length} variables compared over ${fmtNum(p.n_served)} decisions in the last ${p.window_days} days`];
  parts.push(alerts || warns || missing ? `${alerts} shifted beyond the alert level, ${warns} beyond the warning level${missing ? `, ${missing} missing from requests` : ""}` : "none has shifted beyond the warning level");
  return parts.join(": ") + ".";
}

export function ParitySection() {
  const q = useParity();
  return (
    <Section id="parity" title="Training and serving parity" note="Whether the data a model sees in production looks like the data it was trained on, variable by variable.">
      <QueryView query={q} loadingHeight={200}>
        {(p) =>
          isUnavailable(p) ? (
            <UnavailableState u={p} title="No decisions to compare yet" />
          ) : (
            <div className="stack">
              <p className="small" style={{ margin: 0 }}>{sentence(p)}</p>
              <Card flush>
                <DataTable
                  rows={p.rows}
                  rowKey={(r) => r.feature}
                  initialSort={{ key: "psi", dir: "desc" }}
                  maxHeight={420}
                  columns={[
                    { key: "feature", header: "Variable", render: (r) => <span className="mono">{r.feature}</span>, sort: (r) => r.feature },
                    { key: "model", header: "Serving model input", render: (r) => (r.in_serving_model ? "yes" : "—"), sort: (r) => (r.in_serving_model ? 1 : 0) },
                    { key: "psi", header: "PSI", align: "right", render: (r) => (r.psi != null ? r.psi.toFixed(3) : "—"), sort: (r) => r.psi },
                    { key: "status", header: "Shift", render: (r) => <Pill tone={TONE[r.status]}>{r.status}</Pill>, sort: (r) => r.status },
                    { key: "nulls", header: "Missing: train → served", align: "right", render: (r) => `${fmtPct(r.null_rate_train, 1)} → ${fmtPct(r.null_rate_served, 1)}` },
                    { key: "mean", header: "Mean: train → served", align: "right", render: (r) => (r.mean_train != null ? `${fmtNum(r.mean_train, 3)} → ${fmtNum(r.mean_served, 3)}` : "—") },
                  ]}
                />
              </Card>
            </div>
          )
        }
      </QueryView>
    </Section>
  );
}
