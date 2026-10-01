/** Fairness result per evaluated candidate: the lowest adverse impact ratio, with per-class detail that expands in place. */
import { Fragment, useState } from "react";
import { Link } from "react-router-dom";
import type { FairnessData, ModelRef } from "../../api/types";
import { fmtAuc, fmtDateTime, fmtPct, refLabel } from "../../lib/format";
import { isBaselineRef } from "../Models/shared";
import { ModelBadge, Pill, links } from "../ui";
import { classLabel, comparison, groupLabel } from "./labels";
import "./fairness.css";

type Candidate = FairnessData["candidates"][number];

/** The protected group behind a candidate's lowest ratio. */
export function lowestOf(c: Candidate): { cls: string; group: string; ref: string; air: number } | null {
  let best: { cls: string; group: string; ref: string; air: number } | null = null;
  for (const [cls, d] of Object.entries(c.classes)) {
    for (const [g, air] of Object.entries(d.air)) if (!best || air < best.air) best = { cls, group: g, ref: d.reference_group, air };
  }
  return best;
}

export function CandidatesTable({ candidates, threshold, modelOf }: { candidates: Candidate[]; threshold: number; modelOf: (ref: string) => ModelRef | undefined }) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Candidate</th>
            <th>Evaluated (UTC)</th>
            <th className="r">Lowest ratio</th>
            <th>Where it comes from</th>
            <th>Against {fmtAuc(threshold, 2)}</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((c) => {
            const low = lowestOf(c);
            const m = modelOf(c.candidate_ref);
            const isOpen = open.has(c.eval_id);
            const panel = `fairness-detail-${c.eval_id}`;
            const below = c.min_air != null && c.min_air < threshold;
            return (
              <Fragment key={c.eval_id}>
                <tr>
                  <td>
                    <span className="row" style={{ gap: 6 }}>
                      {m ? <ModelBadge model={m} /> : <span>{refLabel(c.candidate_ref)}</span>}
                      {isBaselineRef(c.candidate_ref) && <span className="xs muted">baseline</span>}
                    </span>
                  </td>
                  <td>
                    <span className="small">{fmtDateTime(c.ts)}</span>
                  </td>
                  <td className="r">
                    <Link className="num" to={`${links.evaluation(c.eval_id)}?tab=fairness`} title="Open the evaluation's fairness results">
                      {c.min_air == null ? "—" : fmtAuc(c.min_air, 3)}
                    </Link>
                  </td>
                  <td>{low ? <span className="small">{comparison(low.cls, low.group, low.ref)}</span> : <span className="muted">—</span>}</td>
                  <td>{c.min_air == null ? <Pill>not measured</Pill> : <Pill tone={below ? "crit" : "good"}>{below ? "below threshold" : "at or above threshold"}</Pill>}</td>
                  <td>
                    <button className="fairness-toggle" type="button" aria-expanded={isOpen} aria-controls={panel} onClick={() => toggle(c.eval_id)}>
                      {isOpen ? "Hide classes" : "Show classes"}
                    </button>
                  </td>
                </tr>
                {isOpen && (
                  <tr className="fairness-detail-row" id={panel}>
                    <td colSpan={6}>
                      <div className="fairness-detail-grid">
                        {Object.entries(c.classes).map(([cls, d]) => (
                          <div key={cls} className="stack">
                            <strong className="small">
                              {classLabel(cls)}
                              <span className="muted"> · lowest {d.min_air == null ? "—" : fmtAuc(d.min_air, 3)}</span>
                            </strong>
                            <table className="data">
                              <thead>
                                <tr>
                                  <th>Group</th>
                                  <th className="r">Approval rate</th>
                                  <th className="r">Ratio</th>
                                </tr>
                              </thead>
                              <tbody>
                                <tr>
                                  <td>{groupLabel(cls, d.reference_group)} (reference)</td>
                                  <td className="r">{fmtPct(d.approval_rates[d.reference_group], 1)}</td>
                                  <td className="r">1.000</td>
                                </tr>
                                {Object.entries(d.air).map(([g, air]) => (
                                  <tr key={g}>
                                    <td>{groupLabel(cls, g)}</td>
                                    <td className="r">{fmtPct(d.approval_rates[g], 1)}</td>
                                    <td className="r">
                                      {fmtAuc(air, 3)}
                                      {air < threshold && <span className="models-cell-sub">below threshold</span>}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        ))}
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
