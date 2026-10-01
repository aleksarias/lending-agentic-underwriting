/**
 * Where a numeric variable's values sit: a strip from the 1st to the 99th percentile with the median and the mean
 * marked. Pure SVG drawn at 1:1 scale (labels stay readable on a phone); labels are placed on the first free row above
 * or below the strip so they never overlap. Values are printed, so the picture never stands alone.
 */
import { fmtNum } from "../../lib/format";
import { useElementWidth } from "../Models/shared";
import { useChartColors } from "../charts";
import "./variable.css";

export const fmtVal = (v: number | null | undefined): string => {
  if (v == null || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  const digits = a >= 1000 ? 0 : a >= 100 ? 1 : a >= 1 ? 2 : 3;
  return fmtNum(v, digits);
};

const LABEL_W = 92; // room one label needs, in pixels

export function RangeStrip(props: { p01: number; p50: number; mean: number; p99: number; title: string }) {
  const c = useChartColors();
  const [ref, width] = useElementWidth<HTMLElement>(560);
  const W = Math.max(280, width);
  const pad = LABEL_W / 2 + 4;
  const lo = Math.min(props.p01, props.mean);
  const hi = Math.max(props.p99, props.mean);
  const span = hi - lo || 1;
  const x = (v: number) => pad + ((v - lo) / span) * (W - 2 * pad);

  const marks = [
    { key: "p01", v: props.p01, label: "1st percentile", col: c.muted, bold: false },
    { key: "p50", v: props.p50, label: "Median", col: c.series[0], bold: true },
    { key: "mean", v: props.mean, label: "Mean", col: c.series[3], bold: true },
    { key: "p99", v: props.p99, label: "99th percentile", col: c.muted, bold: false },
  ].sort((a, b) => a.v - b.v);

  // rows: above the strip (nearest first), then below; take the first row whose last label is far enough away
  const rows = [
    { side: "above", level: 0 },
    { side: "below", level: 0 },
    { side: "above", level: 1 },
    { side: "below", level: 1 },
  ] as const;
  const last = rows.map(() => -1e9);
  const placed = marks.map((m) => {
    let r = rows.findIndex((_, i) => x(m.v) - last[i] >= LABEL_W);
    if (r < 0) r = last.indexOf(Math.min(...last));
    last[r] = x(m.v);
    return { ...m, row: rows[r] };
  });
  const aboveLevels = Math.max(-1, ...placed.filter((p) => p.row.side === "above").map((p) => p.row.level)) + 1;
  const belowLevels = Math.max(-1, ...placed.filter((p) => p.row.side === "below").map((p) => p.row.level)) + 1;
  const rowH = 34;
  const yLine = aboveLevels * rowH + 16;
  const H = yLine + belowLevels * rowH + 16;

  return (
    <figure ref={ref} className="chart-box" style={{ margin: 0 }} aria-label={props.title} role="img">
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} style={{ display: "block", maxWidth: "100%" }}>
        <line x1={x(props.p01)} x2={x(props.p99)} y1={yLine} y2={yLine} stroke={c.grid} strokeWidth={10} strokeLinecap="round" />
        <line x1={x(props.p01)} x2={x(props.p99)} y1={yLine} y2={yLine} stroke={c.muted} strokeWidth={1.5} />
        {placed.map((m) => {
          const above = m.row.side === "above";
          const ty = above ? yLine - 14 - m.row.level * rowH : yLine + 14 + m.row.level * rowH;
          return (
            <g key={m.key}>
              <line x1={x(m.v)} x2={x(m.v)} y1={yLine - 10} y2={yLine + 10} stroke={m.col} strokeWidth={m.bold ? 3 : 2} />
              {m.row.level > 0 && <line x1={x(m.v)} x2={x(m.v)} y1={above ? yLine - 10 : yLine + 10} y2={above ? ty + 2 : ty - 12} stroke={c.grid} />}
              <text x={x(m.v)} y={above ? ty - 14 : ty + 12} textAnchor="middle" fill={c.muted} fontSize="11">
                {m.label}
              </text>
              <text x={x(m.v)} y={above ? ty : ty + 26} textAnchor="middle" fill={c.ink} fontSize="12" fontWeight="600">
                {fmtVal(m.v)}
              </text>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}
