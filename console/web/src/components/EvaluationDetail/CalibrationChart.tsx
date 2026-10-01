/**
 * Calibration: observed default rate against predicted, per score bin, with the perfect-calibration diagonal and an
 * approximate 95% binomial (Wilson) interval on each observed rate. Pure SVG, drawn to scale.
 */
import { fmtPct } from "../../lib/format";
import { useChartColors } from "../charts";
import { useElementWidth } from "../shared";
import { niceTicks, wilson } from "./stats";

export interface CalibrationBin {
  bin: number;
  n: number;
  predicted: number;
  observed: number;
}

export function CalibrationChart({ bins, title }: { bins: CalibrationBin[]; title: string }) {
  const c = useChartColors();
  const [ref, width] = useElementWidth<HTMLElement>(480);
  const W = Math.max(280, width);
  const H = Math.round(Math.min(400, Math.max(270, W * 0.75)));
  const m = { l: 50, r: 18, t: 30, b: 44 };
  const ints = bins.map((b) => wilson(b.observed, b.n));
  const top = Math.max(0.01, ...bins.flatMap((b, i) => [b.predicted, b.observed, ints[i]?.hi ?? 0])) * 1.05;
  const { ticks } = niceTicks(0, top, 6);
  const max = ticks[ticks.length - 1];
  const x = (v: number) => m.l + (v / max) * (W - m.l - m.r);
  const y = (v: number) => H - m.b - (v / max) * (H - m.t - m.b);
  const digits = max <= 0.1 ? 1 : 0;
  return (
    <figure ref={ref} className="chart-box" style={{ margin: 0 }} aria-label={title} role="img">
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} style={{ display: "block", maxWidth: "100%" }}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={m.l} x2={W - m.r} y1={y(t)} y2={y(t)} stroke={c.grid} />
            <line x1={x(t)} x2={x(t)} y1={m.t} y2={H - m.b} stroke={c.grid} />
            <text x={m.l - 7} y={y(t) + 4} textAnchor="end" fill={c.muted} fontSize="11">
              {fmtPct(t, digits)}
            </text>
            <text x={x(t)} y={H - m.b + 16} textAnchor="middle" fill={c.muted} fontSize="11">
              {fmtPct(t, digits)}
            </text>
          </g>
        ))}
        <text x={(m.l + W - m.r) / 2} y={H - 6} textAnchor="middle" fill={c.muted} fontSize="11">
          Predicted default rate
        </text>
        <text x={8} y={12} fill={c.muted} fontSize="11">
          Observed default rate
        </text>
        <line x1={x(0)} y1={y(0)} x2={x(max)} y2={y(max)} stroke={c.muted} strokeWidth={1.5} strokeDasharray="6 4" />
        <text x={x(max) - 4} y={y(max) + 14} textAnchor="end" fill={c.muted} fontSize="10">
          perfect calibration
        </text>
        <polyline points={bins.map((b) => `${x(b.predicted)},${y(b.observed)}`).join(" ")} fill="none" stroke={c.series[0]} strokeWidth={1.5} opacity={0.6} />
        {bins.map((b, i) => {
          const ci = ints[i];
          return (
            <g key={b.bin}>
              {ci && <line x1={x(b.predicted)} x2={x(b.predicted)} y1={y(ci.lo)} y2={y(ci.hi)} stroke={c.series[0]} strokeWidth={2} opacity={0.55} />}
              <circle cx={x(b.predicted)} cy={y(b.observed)} r={4.5} fill={c.series[0]} stroke={c.surface} strokeWidth={1.2} />
              <title>{`Bin ${b.bin + 1}: predicted ${fmtPct(b.predicted, 1)}, observed ${fmtPct(b.observed, 1)}${ci ? ` (95% interval ${fmtPct(ci.lo, 1)} to ${fmtPct(ci.hi, 1)})` : ""}, ${b.n} loans`}</title>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}
