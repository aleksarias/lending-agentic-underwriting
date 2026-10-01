/**
 * What-if for the policy's cut-off: approval rate and bad rates at any PD cut-off on the active definition's validation
 * window, with the active policy's approve and refer cut-offs marked. Changing the policy itself needs approval
 * (config/policy.yaml, `lau policy approve`); this only shows the trade-off.
 */
import { useState } from "react";
import type { DecisionsData } from "../../api/types";
import { fmtNum, fmtPct } from "../../lib/format";
import { LineSeriesChart, useChartColors } from "../charts";
import { Card, KeyValue, Section } from "../ui";

type Tradeoff = NonNullable<DecisionsData["tradeoff"]>;

export function WhatIfSection({ t }: { t: Tradeoff }) {
  const c = useChartColors();
  const current = t.points.find((p) => p.is_policy_approve) ?? t.points[Math.floor(t.points.length / 2)];
  const [cutoff, setCutoff] = useState(current?.cutoff ?? 0.12);
  const at = t.points.reduce((best, p) => (Math.abs(p.cutoff - cutoff) < Math.abs(best.cutoff - cutoff) ? p : best), t.points[0]);
  const data = t.points.map((p) => ({
    cutoff: fmtPct(p.cutoff, 0),
    approval: p.approval_rate,
    expected: p.expected_bad_rate,
    known: p.known_bad_rate,
  }));
  const refs = t.points.filter((p) => p.is_policy_approve || p.is_policy_refer);
  const delta = current && at.approval_rate != null && current.approval_rate != null ? at.approval_rate - current.approval_rate : null;
  return (
    <Section
      title="What-if: the approval cut-off"
      note={`From ${t.model_label} on ${fmtNum(t.n_applications)} applications of the validation window (${t.window}). Changing the policy needs its own approval; this only shows the trade-off.`}
    >
      <div className="grid cols-2">
        <Card>
          <LineSeriesChart
            title="Approval rate and bad rate by PD cut-off"
            data={data}
            xKey="cutoff"
            yFormat={(v) => fmtPct(v, 0)}
            height={260}
            series={[
              { key: "approval", label: "Approved (all applications)", color: c.accent },
              { key: "expected", label: "Bad rate expected by the model", color: c.warn },
              { key: "known", label: "Bad rate known (legacy-funded loans)", color: c.crit, dashed: true },
            ]}
          />
          <div className="xs muted">
            Policy cut-offs: {refs.map((r) => `${r.is_policy_approve ? "approve" : "refer"} up to ${fmtPct(r.cutoff, 0)}`).join(", ") || "no active policy"}.
          </div>
        </Card>
        <Card title="Try a cut-off">
          <label className="field">
            <span className="small">
              Approve when PD is at most <strong>{fmtPct(cutoff, 0)}</strong>
            </span>
            <input type="range" min={t.points[0].cutoff} max={t.points[t.points.length - 1].cutoff} step={0.01} value={cutoff} onChange={(e) => setCutoff(Number(e.target.value))} aria-label="PD cut-off" />
          </label>
          <KeyValue
            items={[
              ["Approved", `${fmtPct(at.approval_rate, 1)}${delta != null ? ` (${delta >= 0 ? "+" : ""}${(delta * 100).toFixed(1)} points against the policy)` : ""}`],
              ["Bad rate the model expects among approvals", fmtPct(at.expected_bad_rate, 1)],
              ["Bad rate known among approvals with an outcome", `${fmtPct(at.known_bad_rate, 1)} of ${fmtNum(at.known_n)} loans`],
            ]}
          />
          <div className="xs muted">
            The known bad rate covers only applicants the legacy policy funded (the others have no outcome), so it flatters looser cut-offs: no reject inference is applied.
          </div>
        </Card>
      </div>
    </Section>
  );
}
