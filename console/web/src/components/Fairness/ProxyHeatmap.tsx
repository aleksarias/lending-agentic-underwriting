/**
 * Proxy scan heat map: how well each feature alone predicts membership of a protected group (AUC; 0.5 means no
 * signal). Rows are the features with the strongest proxy signal; columns are each protected class pooled and then
 * group by group. Flagged cells (above the scan threshold) are outlined AND labeled, never color alone.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import type { FairnessData } from "../../api/types";
import { fmtAuc, fmtNum } from "../../lib/format";
import { heat } from "../charts";
import { EmptyState, links } from "../ui";
import { classLabel, groupLabel } from "./labels";
import "./fairness.css";

type Cell = FairnessData["proxy_heatmap"][number];

const CLASS_ORDER = ["race_ethnicity", "sex", "age_62_plus"];
const LO = 0.5;
const HI = 0.8;
const INITIAL_ROWS = 12;

export function ProxyHeatmap({ cells, threshold }: { cells: Cell[]; threshold: number }) {
  const [all, setAll] = useState(false);
  if (cells.length === 0) {
    return (
      <EmptyState title="No proxy scan for this definition">
        The evidence job scans every catalog feature for how well it predicts protected-group membership, pooled and group by group. Run it with <code>lau evidence run</code>; the
        results appear here as a heat map.
      </EmptyState>
    );
  }
  // columns: class by class, pooled first, then groups alphabetically
  const classes = Array.from(new Set(cells.map((c) => c.protected_class))).sort((a, b) => {
    const ia = CLASS_ORDER.indexOf(a);
    const ib = CLASS_ORDER.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b);
  });
  const columns = classes.flatMap((cls) => {
    const groups = Array.from(new Set(cells.filter((c) => c.protected_class === cls).map((c) => c.protected_group)));
    groups.sort((a, b) => (a === null ? -1 : b === null ? 1 : String(a).localeCompare(String(b))));
    return groups.map((g) => ({ cls, group: g }));
  });
  const byKey = new Map<string, Cell>();
  for (const c of cells) byKey.set(`${c.feature}|${c.protected_class}|${c.protected_group ?? ""}`, c);
  // features by their strongest signal
  const strongest = new Map<string, number>();
  for (const c of cells) strongest.set(c.feature, Math.max(strongest.get(c.feature) ?? 0, c.proxy_auc));
  const features = [...strongest.entries()].sort((a, b) => b[1] - a[1]).map(([f]) => f);
  const shown = all ? features : features.slice(0, INITIAL_ROWS);
  const flaggedFeatures = new Set(cells.filter((c) => c.flagged).map((c) => c.feature));

  return (
    <div className="stack">
      <div className="fairness-legend" aria-label="Color scale and flag">
        <span>Proxy AUC:</span>
        <span className="ramp">
          {[0.5, 0.6, 0.7, 0.8].map((v) => (
            <span key={v} className="step" style={{ background: heat(v, LO, HI, "crit") }}>
              {v === 0.8 ? "0.80 and up" : fmtAuc(v, 2)}
            </span>
          ))}
        </span>
        <span>0.50 means the feature says nothing about group membership.</span>
        <span>
          <span className="outlined">0.752</span> Outlined and labeled “flagged”: above {fmtAuc(threshold, 2)}.
        </span>
      </div>
      <div className="small muted">
        Each class has a pooled column (any protected group against everyone else) and one column per group (that group against the reference group). A feature that tracks one group can fall
        below the threshold when groups are pooled, so both are scanned.
      </div>
      <div className="table-wrap">
        <table className="fairness-heat">
          <caption className="sr-only">Proxy AUC by feature and protected group. Flagged cells are labeled.</caption>
          <thead>
            <tr>
              <th className="feature" rowSpan={2} scope="col">
                Feature
              </th>
              {classes.map((cls) => (
                <th key={cls} scope="colgroup" className="class" colSpan={columns.filter((c) => c.cls === cls).length}>
                  {classLabel(cls)}
                </th>
              ))}
            </tr>
            <tr>
              {columns.map((c) => (
                <th key={`${c.cls}|${c.group ?? ""}`} scope="col" className={c.group === null ? "class" : undefined}>
                  {groupLabel(c.cls, c.group)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((f) => (
              <tr key={f}>
                <th scope="row" className="feature">
                  <Link to={links.variable(f)}>{f}</Link>
                </th>
                {columns.map((c) => {
                  const cell = byKey.get(`${f}|${c.cls}|${c.group ?? ""}`);
                  if (!cell) return <td key={`${c.cls}|${c.group ?? ""}`} className={`cell ${c.group === null ? "pooled" : ""}`}>—</td>;
                  return (
                    <td
                      key={`${c.cls}|${c.group ?? ""}`}
                      className={`cell ${cell.flagged ? "flagged" : ""} ${c.group === null ? "pooled" : ""}`}
                      style={{ background: heat(cell.proxy_auc, LO, HI, "crit") }}
                      title={`${f}, ${classLabel(c.cls)}, ${groupLabel(c.cls, c.group)}: proxy AUC ${fmtAuc(cell.proxy_auc, 3)}${cell.flagged ? " (flagged)" : ""}`}
                    >
                      <span className="v">{fmtAuc(cell.proxy_auc, 3)}</span>
                      {cell.flagged && <span className="flag">flagged</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row between small muted">
        <span>
          Showing the {shown.length} of {fmtNum(features.length)} features with the strongest proxy signal; {flaggedFeatures.size} flagged.
        </span>
        {features.length > INITIAL_ROWS && (
          <button className="btn small" type="button" onClick={() => setAll((x) => !x)} aria-expanded={all}>
            {all ? `Show the top ${INITIAL_ROWS}` : `Show all ${fmtNum(features.length)} features`}
          </button>
        )}
      </div>
    </div>
  );
}
