/**
 * Multiple-testing ledger: the AUC margin a candidate had to clear (it rises with every validation test under the
 * definition) and each candidate's actual gain over its reference, at the test number it was evaluated as.
 * Pure SVG, drawn to scale. Marker shape carries the result (circle passed, diamond did not pass), not only color.
 */
import type { PerformanceData } from "../../api/types";
import { fmtDiff, refLabel } from "../../lib/format";
import { niceTicks } from "../EvaluationDetail/stats";
import { useElementWidth } from "../Models/shared";
import { useChartColors } from "../charts";
import "./performance.css";

type Point = PerformanceData["ledger"][number];

export function MarginLedgerChart({ ledger, title }: { ledger: Point[]; title: string }) {
  const c = useChartColors();
  const [ref, width] = useElementWidth<HTMLElement>();
  // drawn at 1:1 scale so text stays readable on a phone
  const W = Math.max(290, width);
  const H = Math.round(Math.min(330, Math.max(250, W * 0.5)));
  const m = { l: 58, r: 24, t: 22, b: 50 };

  // the margin is a function of the test number alone, so one point per test number
  const marginByN = new Map<number, number>();
  for (const p of ledger) if (!marginByN.has(p.n_tests)) marginByN.set(p.n_tests, p.required_margin);
  const curve = [...marginByN.entries()].sort((a, b) => a[0] - b[0]);
  const cands = ledger.filter((p) => p.reference_auc != null && !p.candidate_ref.startsWith("baseline:"));
  const gains = cands.map((p) => p.val_auc - (p.reference_auc as number));

  const nMin = Math.min(...curve.map(([n]) => n), 0);
  const nMax = Math.max(...curve.map(([n]) => n), 1);
  const { ticks: yTicks, digits: tickDigits } = niceTicks(Math.min(0, ...gains), Math.max(...gains, ...curve.map(([, v]) => v), 0.001) * 1.1);
  const digits = Math.max(2, tickDigits);
  const yTop = yTicks[yTicks.length - 1];
  const yBot = yTicks[0];
  const x = (n: number) => m.l + ((n - (nMin - 0.4)) / (nMax - nMin + 0.8)) * (W - m.l - m.r);
  const y = (v: number) => H - m.b - ((v - yBot) / (yTop - yBot)) * (H - m.t - m.b);
  const xTicks = Array.from({ length: nMax - nMin + 1 }, (_, i) => nMin + i);

  // nudge labels that would overlap when candidates share a test number
  const placed: { px: number; py: number }[] = [];
  const labelY = (px: number, py: number) => {
    let ly = py;
    while (placed.some((q) => Math.abs(q.px - px) < 30 && Math.abs(q.py - ly) < 13)) ly += 13;
    placed.push({ px, py: ly });
    return ly;
  };

  return (
    <figure ref={ref} className="chart-box" style={{ margin: 0 }} aria-label={title} role="img">
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} style={{ display: "block", maxWidth: "100%" }}>
        {yTicks.map((t, i) => (
          <g key={i}>
            <line x1={m.l} x2={W - m.r} y1={y(t)} y2={y(t)} stroke={c.grid} />
            <text x={m.l - 8} y={y(t) + 4} textAnchor="end" fill={c.muted} fontSize="11">
              {fmtDiff(t, digits)}
            </text>
          </g>
        ))}
        <line x1={m.l} x2={W - m.r} y1={y(0)} y2={y(0)} stroke={c.muted} strokeWidth={1.2} />
        {xTicks.map((n) => (
          <g key={n}>
            <line x1={x(n)} x2={x(n)} y1={H - m.b} y2={H - m.b + 4} stroke={c.muted} />
            <text x={x(n)} y={H - m.b + 18} textAnchor="middle" fill={c.muted} fontSize="11">
              {n}
            </text>
          </g>
        ))}
        <text x={(m.l + W - m.r) / 2} y={H - 8} textAnchor="middle" fill={c.muted} fontSize="11">
          Validation tests counted
        </text>
        <text x={m.l} y={12} fill={c.muted} fontSize="11">
          AUC above the reference
        </text>

        {/* the bar: required margin by test number */}
        {curve.length > 1 && <polyline points={curve.map(([n, v]) => `${x(n)},${y(v)}`).join(" ")} fill="none" stroke={c.ink} strokeWidth={2} strokeDasharray="6 4" />}
        {curve.map(([n, v]) => (
          <g key={n}>
            <rect x={x(n) - 4} y={y(v) - 4} width={8} height={8} fill={c.surface} stroke={c.ink} strokeWidth={1.6} />
            <text x={x(n) - 9} y={y(v) - 7} textAnchor="end" fill={c.muted} fontSize="10">
              {fmtDiff(v, 4)}
            </text>
            <title>{`Required margin after ${n} test${n === 1 ? "" : "s"}: ${fmtDiff(v, 4)}`}</title>
          </g>
        ))}

        {/* candidates: actual gain over the reference */}
        {cands.map((p, i) => {
          const gain = p.val_auc - (p.reference_auc as number);
          const px = x(p.n_tests);
          const py = y(gain);
          const ly = labelY(px, py);
          const col = p.passed ? c.good : c.crit;
          return (
            <g key={`${p.candidate_ref}-${i}`}>
              {p.passed ? (
                <circle cx={px} cy={py} r={6} fill={col} stroke={c.surface} strokeWidth={1.5} />
              ) : (
                <rect x={px - 5.5} y={py - 5.5} width={11} height={11} transform={`rotate(45 ${px} ${py})`} fill={c.surface} stroke={col} strokeWidth={2.4} />
              )}
              <text x={px + 11} y={ly + 4} fill={c.ink} fontSize="12" fontWeight="600">
                {refLabel(p.candidate_ref)}
                {p.passed ? "" : " did not pass"}
              </text>
              <title>{`${refLabel(p.candidate_ref)}: ${fmtDiff(gain, 4)} over its reference at test ${p.n_tests}; required ${fmtDiff(p.required_margin, 4)}; ${p.passed ? "passed" : "did not pass"} validation`}</title>
            </g>
          );
        })}
      </svg>
      <div className="performance-legend">
        <span>
          <svg width="26" height="12" aria-hidden>
            <line x1="0" x2="26" y1="6" y2="6" style={{ stroke: "var(--ink)" }} strokeWidth="2" strokeDasharray="5 3" />
          </svg>
          Required margin (the bar)
        </span>
        <span>
          <svg width="14" height="14" aria-hidden>
            <circle cx="7" cy="7" r="5.5" style={{ fill: "var(--good)" }} />
          </svg>
          Passed validation
        </span>
        <span>
          <svg width="14" height="14" aria-hidden>
            <rect x="2.5" y="2.5" width="9" height="9" transform="rotate(45 7 7)" style={{ fill: "var(--surface)", stroke: "var(--crit)" }} strokeWidth="2" />
          </svg>
          Did not pass
        </span>
      </div>
    </figure>
  );
}
