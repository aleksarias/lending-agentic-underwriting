/** A small horizontal bar chart with the exact count and share beside every bar (drawn with the shared bar classes). */
import { fmtNum, fmtPct } from "../../lib/format";

export interface CountRow {
  key: string;
  label: string;
  count: number;
}

export function CountBars({ title, rows, total, basis }: { title: string; rows: CountRow[]; total: number; basis: string }) {
  const sorted = [...rows].sort((a, b) => b.count - a.count);
  const max = Math.max(...sorted.map((r) => r.count), 1);
  return (
    <figure className="definition-detail-bars" aria-label={title}>
      <ul className="plain">
        {sorted.map((r) => (
          <li key={r.key} className="definition-detail-bar-row">
            <span>{r.label}</span>
            <span className="bar-track" aria-hidden>
              <span className="bar-fill" style={{ width: `${(r.count / max) * 100}%` }} />
            </span>
            <span className="num definition-detail-bar-value">
              {fmtNum(r.count)} <span className="xs muted">{total > 0 ? fmtPct(r.count / total, 1) : "—"}</span>
            </span>
          </li>
        ))}
      </ul>
      <figcaption className="xs muted">Shares are of {basis}.</figcaption>
    </figure>
  );
}
