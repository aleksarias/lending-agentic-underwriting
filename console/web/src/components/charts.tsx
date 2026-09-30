/**
 * Chart building blocks. Colors come from CSS tokens (--s1..--s6, --chart-grid, --muted), so charts follow the
 * light/dark theme. Every chart takes a `title` used as its accessible label; pages should also offer the numbers
 * in a table nearby (screen readers and exact values).
 */
import { useEffect, useState, type ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export interface ThemeColors {
  series: string[];
  grid: string;
  muted: string;
  ink: string;
  surface: string;
  good: string;
  warn: string;
  crit: string;
  accent: string;
}

function readColors(): ThemeColors {
  const cs = getComputedStyle(document.documentElement);
  const v = (n: string, fallback: string) => cs.getPropertyValue(n).trim() || fallback;
  return {
    series: ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6"].map((n, i) => v(n, ["#1f6a58", "#8a5a9c", "#b86b1f", "#2f5f8a", "#7a7f3a", "#a3312b"][i])),
    grid: v("--chart-grid", "#e2e5dd"),
    muted: v("--muted", "#5a6470"),
    ink: v("--ink", "#18212b"),
    surface: v("--surface", "#ffffff"),
    good: v("--good", "#2e7d4f"),
    warn: v("--warn", "#9a5b0f"),
    crit: v("--crit", "#a3312b"),
    accent: v("--accent", "#1f6a58"),
  };
}

/** Theme colors that update when the OS/app theme changes. */
export function useChartColors(): ThemeColors {
  const [c, setC] = useState<ThemeColors>(() => readColors());
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setC(readColors());
    mq.addEventListener("change", update);
    const obs = new MutationObserver(update);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      mq.removeEventListener("change", update);
      obs.disconnect();
    };
  }, []);
  return c;
}

export interface SeriesSpec {
  key: string;
  label: string;
  /** index into theme series colors, or an explicit CSS color */
  color?: number | string;
  dashed?: boolean;
  width?: number;
}

const pickColor = (c: ThemeColors, s: SeriesSpec, i: number) =>
  typeof s.color === "string" ? s.color : c.series[(s.color ?? i) % c.series.length];

function tooltipStyle(c: ThemeColors) {
  return {
    contentStyle: { background: c.surface, border: `1px solid ${c.grid}`, borderRadius: 8, color: c.ink, fontSize: 12 },
    labelStyle: { color: c.muted },
  };
}

export function ChartFrame({ title, height = 260, children, legend }: { title: string; height?: number; children: ReactNode; legend?: ReactNode }) {
  return (
    <figure className="chart-box" style={{ margin: 0 }} aria-label={title} role="img">
      <div style={{ width: "100%", height }}>{children}</div>
      {legend}
    </figure>
  );
}

/** Multi-series line chart over a categorical or time x axis. */
export type ChartDatum = Record<string, string | number | null | undefined>;

export function LineSeriesChart(props: {
  title: string;
  data: ChartDatum[];
  xKey: string;
  series: SeriesSpec[];
  height?: number;
  yFormat?: (v: number) => string;
  xFormat?: (v: string) => string;
  yDomain?: [number | "auto" | "dataMin" | "dataMax", number | "auto" | "dataMin" | "dataMax"];
  bands?: { from: string; to: string; label?: string; tone?: "warn" | "crit" | "neutral" }[];
  refLines?: { y: number; label?: string; tone?: "good" | "warn" | "crit" | "neutral" }[];
}) {
  const c = useChartColors();
  const fmt = props.yFormat ?? ((v: number) => String(v));
  return (
    <ChartFrame title={props.title} height={props.height}>
      <ResponsiveContainer>
        <LineChart data={props.data} margin={{ top: 10, right: 16, bottom: 4, left: 4 }}>
          <CartesianGrid stroke={c.grid} vertical={false} />
          <XAxis dataKey={props.xKey} tick={{ fill: c.muted, fontSize: 11 }} tickFormatter={props.xFormat} stroke={c.grid} />
          <YAxis tick={{ fill: c.muted, fontSize: 11 }} tickFormatter={fmt} stroke={c.grid} domain={props.yDomain ?? ["auto", "auto"]} width={56} />
          <Tooltip formatter={(v: unknown) => (typeof v === "number" ? fmt(v) : String(v))} {...tooltipStyle(c)} />
          <Legend wrapperStyle={{ fontSize: 12, color: c.muted }} />
          {props.bands?.map((b, i) => (
            <ReferenceArea key={i} x1={b.from} x2={b.to} fill={b.tone === "crit" ? c.crit : b.tone === "neutral" ? c.grid : c.warn} fillOpacity={0.12} label={b.label ? { value: b.label, fill: c.muted, fontSize: 11, position: "insideTop" } : undefined} />
          ))}
          {props.refLines?.map((r, i) => (
            <ReferenceLine key={i} y={r.y} stroke={r.tone === "crit" ? c.crit : r.tone === "warn" ? c.warn : r.tone === "good" ? c.good : c.muted} strokeDasharray="4 4" label={r.label ? { value: r.label, fill: c.muted, fontSize: 11, position: "insideTopRight" } : undefined} />
          ))}
          {props.series.map((s, i) => (
            <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={pickColor(c, s, i)} strokeWidth={s.width ?? 2} strokeDasharray={s.dashed ? "5 4" : undefined} dot={{ r: 2.5 }} activeDot={{ r: 4 }} connectNulls isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

/** Grouped or stacked bars. */
export function BarSeriesChart(props: {
  title: string;
  data: ChartDatum[];
  xKey: string;
  series: SeriesSpec[];
  stacked?: boolean;
  height?: number;
  yFormat?: (v: number) => string;
  layout?: "horizontal" | "vertical";
}) {
  const c = useChartColors();
  const fmt = props.yFormat ?? ((v: number) => String(v));
  const vertical = props.layout === "vertical";
  return (
    <ChartFrame title={props.title} height={props.height}>
      <ResponsiveContainer>
        <BarChart data={props.data} layout={vertical ? "vertical" : "horizontal"} margin={{ top: 10, right: 16, bottom: 4, left: 4 }}>
          <CartesianGrid stroke={c.grid} vertical={vertical} horizontal={!vertical} />
          {vertical ? (
            <>
              <XAxis type="number" tick={{ fill: c.muted, fontSize: 11 }} tickFormatter={fmt} stroke={c.grid} />
              <YAxis type="category" dataKey={props.xKey} tick={{ fill: c.muted, fontSize: 11 }} stroke={c.grid} width={140} />
            </>
          ) : (
            <>
              <XAxis dataKey={props.xKey} tick={{ fill: c.muted, fontSize: 11 }} stroke={c.grid} />
              <YAxis tick={{ fill: c.muted, fontSize: 11 }} tickFormatter={fmt} stroke={c.grid} width={56} />
            </>
          )}
          <Tooltip formatter={(v: unknown) => (typeof v === "number" ? fmt(v) : String(v))} {...tooltipStyle(c)} />
          {props.series.length > 1 && <Legend wrapperStyle={{ fontSize: 12, color: c.muted }} />}
          {props.series.map((s, i) => (
            <Bar key={s.key} dataKey={s.key} name={s.label} fill={pickColor(c, s, i)} stackId={props.stacked ? "a" : undefined} isAnimationActive={false} radius={props.stacked ? 0 : [3, 3, 0, 0]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

/** Confidence intervals: one row per estimate, with a zero (no-difference) line. Pure SVG, drawn to scale. */
export function IntervalChart(props: {
  title: string;
  rows: { label: string; estimate: number; lo: number; hi: number }[];
  format?: (v: number) => string;
  zeroLabel?: string;
}) {
  const c = useChartColors();
  const fmt = props.format ?? ((v: number) => v.toFixed(3));
  const W = 560;
  const rowH = 34;
  const top = 18;
  // room for the longest row label (about 7 units per character at 12px), within sensible bounds
  const left = Math.min(240, Math.max(64, Math.max(0, ...props.rows.map((r) => r.label.length)) * 7 + 18));
  const right = 20;
  const H = top + props.rows.length * rowH + 30;
  const vals = props.rows.flatMap((r) => [r.lo, r.hi, 0]);
  let min = Math.min(...vals);
  let max = Math.max(...vals);
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const pad = (max - min) * 0.08;
  min -= pad;
  max += pad;
  const x = (v: number) => left + ((v - min) / (max - min)) * (W - left - right);
  const ticks = Array.from({ length: 5 }, (_, i) => min + ((max - min) * i) / 4);
  return (
    <figure className="chart-box" style={{ margin: 0 }} aria-label={props.title} role="img">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: "block" }}>
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={x(t)} x2={x(t)} y1={top - 6} y2={H - 24} stroke={c.grid} />
            <text x={x(t)} y={H - 8} textAnchor="middle" fill={c.muted} fontSize="11">
              {fmt(t)}
            </text>
          </g>
        ))}
        <line x1={x(0)} x2={x(0)} y1={top - 8} y2={H - 24} stroke={c.muted} strokeWidth={1.5} />
        {props.zeroLabel && (
          <text x={x(0) + 4} y={top - 8} fill={c.muted} fontSize="10">
            {props.zeroLabel}
          </text>
        )}
        {props.rows.map((r, i) => {
          const y = top + i * rowH + rowH / 2;
          const above = r.lo > 0;
          const below = r.hi < 0;
          const col = above ? c.good : below ? c.crit : c.warn;
          return (
            <g key={r.label}>
              <text x={left - 10} y={y + 4} textAnchor="end" fill={c.ink} fontSize="12">
                {r.label}
              </text>
              <line x1={x(r.lo)} x2={x(r.hi)} y1={y} y2={y} stroke={col} strokeWidth={4} strokeLinecap="round" />
              <circle cx={x(r.estimate)} cy={y} r={5} fill={col} />
              <text x={x(r.estimate)} y={y - 9} textAnchor="middle" fill={c.ink} fontSize="11" fontWeight="600">
                {fmt(r.estimate)}
              </text>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}

/** Tiny trend line for tables and tiles. */
export function Sparkline({ values, width = 90, height = 24, tone = "accent" }: { values: number[]; width?: number; height?: number; tone?: "accent" | "good" | "warn" | "crit" }) {
  const c = useChartColors();
  if (values.length < 2) return <span className="faint xs">—</span>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * (width - 4) + 2},${height - 2 - ((v - min) / span) * (height - 4)}`).join(" ");
  const color = { accent: c.accent, good: c.good, warn: c.warn, crit: c.crit }[tone];
  const last = pts.split(" ").pop()!.split(",");
  return (
    <svg width={width} height={height} aria-hidden style={{ verticalAlign: "middle" }}>
      <polyline fill="none" stroke={color} strokeWidth={1.6} points={pts} />
      <circle cx={Number(last[0])} cy={Number(last[1])} r={2.4} fill={color} />
    </svg>
  );
}

/** Heat color for a value in [lo, hi] (used by matrix/heatmap cells). Returns a CSS color-mix string. */
export function heat(value: number, lo: number, hi: number, tone: "good" | "crit" | "accent" = "accent"): string {
  const t = Math.max(0, Math.min(1, (value - lo) / (hi - lo || 1)));
  const pct = Math.round(8 + t * 55);
  return `color-mix(in srgb, var(--${tone === "accent" ? "accent" : tone}) ${pct}%, var(--surface))`;
}
