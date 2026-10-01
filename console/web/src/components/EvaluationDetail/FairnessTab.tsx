/**
 * Fairness for this evaluation: adverse impact ratio (AIR) per protected group, per class, against the threshold,
 * with the approval rates behind each ratio. Protected attributes are used only to test results.
 */
import { Link } from "react-router-dom";
import type { EvaluationDetail, Tile } from "../../api/types";
import { fmtAuc, fmtPct } from "../../lib/format";
import { classLabel, comparison, groupLabel } from "../Fairness/labels";
import { HBars, type HBarRow } from "../shared";
import type { Limits } from "../Performance/thresholds";
import { Card, Section, Tiles, links } from "../ui";
import "./evaluation.css";

export function FairnessTab({ e, limits }: { e: EvaluationDetail; limits: Limits }) {
  const f = e.fairness;
  const classes = Object.entries(f.classes);
  const threshold = limits.minAir;

  // where the lowest ratio comes from
  let lowest: { cls: string; group: string; ref: string; air: number } | null = null;
  for (const [cls, d] of classes) {
    for (const [g, air] of Object.entries(d.air)) if (!lowest || air < lowest.air) lowest = { cls, group: g, ref: d.reference_group, air };
  }

  const tiles: Tile[] = [];
  if (f.min_air != null) {
    const below = threshold != null && f.min_air < threshold;
    tiles.push({
      key: "air",
      label: "Lowest adverse impact ratio",
      value: fmtAuc(f.min_air, 3),
      sub: `${lowest ? `${comparison(lowest.cls, lowest.group, lowest.ref)}; ` : ""}${threshold != null ? `threshold ${fmtAuc(threshold, 2)}: ${below ? "below it" : "at or above it"}` : ""}`,
      tone: below ? "crit" : "good",
    });
  }
  if (f.cutoff_pd != null) {
    tiles.push({ key: "cutoff", label: "Approval cutoff used for the test", value: fmtPct(f.cutoff_pd, 1), sub: "applicants at or below this predicted default rate are treated as approved" });
  }

  return (
    <div className="evaluation-panel">
      {tiles.length > 0 && <Tiles tiles={tiles} />}
      <div className="small muted">
        Adverse impact ratio: a group’s approval rate divided by the reference group’s, when the model approves applicants at or below the cutoff above.
        {threshold != null ? ` The threshold is ${fmtAuc(threshold, 2)} (the four-fifths rule); below it the check fails.` : ""} Protected attributes are used only to test results, never as
        model inputs. The test covers every application in the validation period, approved or declined. Ratios are point estimates: group sizes and intervals are not reported, so a ratio a few
        points from 1.0 may be sampling noise.
      </div>

      <Section title="Adverse impact by group">
        {classes.length === 0 ? (
          <Card>
            <span className="muted small">No fairness results were recorded for this evaluation.</span>
          </Card>
        ) : (
          <div className="evaluation-class-grid">
            {classes.map(([cls, d]) => {
              const rows: HBarRow[] = [
                {
                  key: d.reference_group,
                  label: `${groupLabel(cls, d.reference_group)} (reference)`,
                  value: 1,
                  display: <span className="num">1.000</span>,
                  note: d.approval_rates[d.reference_group] != null ? `${fmtPct(d.approval_rates[d.reference_group], 1)} approved` : undefined,
                  tone: "muted",
                },
                ...Object.entries(d.air).map(([g, air]) => {
                  const below = threshold != null && air < threshold;
                  return {
                    key: g,
                    label: groupLabel(cls, g),
                    value: air,
                    display: <span className="num">{fmtAuc(air, 3)}</span>,
                    note: `${d.approval_rates[g] != null ? `${fmtPct(d.approval_rates[g], 1)} approved; ` : ""}${threshold != null ? (below ? "below the threshold" : "at or above the threshold") : ""}`,
                    tone: below ? ("crit" as const) : ("accent" as const),
                  };
                }),
              ];
              const max = Math.max(1.2, ...Object.values(d.air).map((v) => v * 1.05));
              return (
                <Card key={cls} title={classLabel(cls)} kind="measured">
                  <HBars
                    title={`Adverse impact ratio by ${classLabel(cls).toLowerCase()} group`}
                    rows={rows}
                    format={(v) => fmtAuc(v, 2)}
                    min={0}
                    max={max}
                    markers={[{ value: 1, label: "Parity with the reference group" }, ...(threshold != null ? [{ value: threshold, label: "Threshold" }] : [])]}
                  />
                </Card>
              );
            })}
          </div>
        )}
      </Section>

      <Section title="Proxies among the model’s features">
        <Card kind="measured">
          {e.proxies_flagged.length === 0 ? (
            <span className="small">
              No feature this model uses is flagged as a proxy for a protected class{limits.proxyAucFlag != null ? ` (a feature is flagged when it alone predicts group membership with AUC above ${fmtAuc(limits.proxyAucFlag, 2)})` : ""}. The full
              scan is on <Link to="/fairness">Fairness and compliance</Link>.
            </span>
          ) : (
            <div className="stack">
              <span className="small">These model features are flagged as proxies for a protected class, which fails the “No proxy features” check:</span>
              <ul className="models-chips">
                {e.proxies_flagged.map((p) => (
                  <li key={p}>
                    <Link className="models-chip" to={links.variable(p)}>
                      {p}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      </Section>
    </div>
  );
}
