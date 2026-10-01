/**
 * Vintage curves: the cumulative share of each half-year origination cohort that reached 30, 60 or 90 days past due, by
 * month on book. They are an early-indicator view computed from loan status alone, so they need no definition of
 * default and keep their meaning when the definition changes. The threshold tab lives in the URL (?dpd=).
 */
import { useSearchParams } from "react-router-dom";
import type { VintageData } from "../../api/types";
import { LineSeriesChart } from "../charts";
import { Card, DataTable, EmptyState, Section, Tabs, TimeAgo, type Column } from "../ui";
import { fmtNum, fmtPct } from "../../lib/format";
import "./Feed.css";

type Cohort = VintageData["cohorts"][number];

/** How the newest cohort compares with the earlier ones at the last month they all have, as one factual sentence. */
export function readingSentence(cohorts: Cohort[], dpd: number): string | null {
  if (cohorts.length < 2) return null;
  const series = cohorts.map((c) => ({ cohort: c.cohort, values: c.curves[String(dpd)] ?? [] }));
  const newest = series[series.length - 1];
  const earlier = series.slice(0, -1);
  const month = Math.min(newest.values.length, ...earlier.map((e) => e.values.length));
  if (!Number.isFinite(month) || month < 1) return null;
  const cur = newest.values[month - 1];
  const others = earlier.map((e) => e.values[month - 1]);
  const lo = Math.min(...others);
  const hi = Math.max(...others);
  const where = cur > hi ? "above every earlier cohort" : cur < lo ? "below every earlier cohort" : "inside the range of the earlier cohorts";
  return `By month ${month}, the newest cohort (${newest.cohort}) has reached ${fmtPct(cur, 1)}, ${where} (${fmtPct(lo, 1)} to ${fmtPct(hi, 1)}).`;
}

export function VintageSection({ vintage }: { vintage: VintageData }) {
  const [params, setParams] = useSearchParams();
  const thresholds = vintage.dpd_thresholds.length ? vintage.dpd_thresholds : Array.from(new Set(vintage.cohorts.flatMap((c) => Object.keys(c.curves).map(Number)))).sort((a, b) => a - b);
  const requested = Number(params.get("dpd"));
  const dpd = thresholds.includes(requested) ? requested : thresholds[0];
  const setDpd = (k: string) => {
    const next = new URLSearchParams(params);
    if (Number(k) === thresholds[0]) next.delete("dpd");
    else next.set("dpd", k);
    setParams(next, { replace: true });
  };

  const note = (
    <>
      Share of each half-year origination cohort that has reached the stated days past due by each month on book. These curves need no definition of
      default: they count loans by days past due alone, so they keep their meaning when the definition changes. Only cohorts with 12 months of
      performance appear, and there are no confidence intervals: each curve is the observed share of the loans in that cohort.
    </>
  );

  if (!vintage.cohorts.length || dpd == null) {
    return (
      <Section title="Vintage curves" note={note}>
        <EmptyState title="No vintage curves yet">
          The evidence job (<code>lau evidence run</code>) computes them for each half-year cohort once its loans have 12 months of performance.
        </EmptyState>
      </Section>
    );
  }

  const key = String(dpd);
  const months = Math.max(...vintage.cohorts.map((c) => (c.curves[key] ?? []).length));
  const rows = Array.from({ length: months }, (_, i) => ({ mob: i + 1 }));
  const newestIndex = vintage.cohorts.length - 1;
  const chartData = rows.map((r) => {
    const row: Record<string, string | number | null> = { mob: String(r.mob) };
    vintage.cohorts.forEach((c, i) => {
      row[`c${i}`] = c.curves[key]?.[r.mob - 1] ?? null;
    });
    return row;
  });
  const columns: Column<(typeof rows)[number]>[] = [
    { key: "mob", header: "Month on book", render: (r) => r.mob, sort: (r) => r.mob },
    ...vintage.cohorts.map<Column<(typeof rows)[number]>>((c) => ({
      key: c.cohort,
      header: (
        <span>
          {c.cohort}
          <span className="feed-th-sub">{fmtNum(c.n)} loans</span>
        </span>
      ),
      align: "right",
      render: (r) => fmtPct(c.curves[key]?.[r.mob - 1], 1),
      sort: (r) => c.curves[key]?.[r.mob - 1] ?? null,
    })),
  ];
  const reading = readingSentence(vintage.cohorts, dpd);

  return (
    <Section
      title="Vintage curves"
      note={note}
      right={<Tabs tabs={thresholds.map((d) => ({ key: String(d), label: `${d}+ days past due` }))} value={key} onChange={setDpd} />}
    >
      <Card kind="measured" title={`Cumulative share of each cohort's loans that reached ${dpd}+ days past due, by month on book`}>
        <LineSeriesChart
          title={`Cumulative share of loans that reached ${dpd} or more days past due by month on book, one line per half-year origination cohort`}
          data={chartData}
          xKey="mob"
          xFormat={(v) => `M${v}`}
          series={vintage.cohorts.map((c, i) => ({
            key: `c${i}`,
            label: `${c.cohort} (${fmtNum(c.n)} loans)`,
            color: i,
            dashed: i >= 6,
            width: i === newestIndex ? 3 : 1.8,
          }))}
          yFormat={(v) => fmtPct(v, 1)}
          yDomain={[0, "auto"]}
          height={300}
        />
        <div className="feed-reading">
          {reading && <span>{reading}</span>}
          {vintage.computed_at && (
            <span className="xs muted">
              Computed <TimeAgo iso={vintage.computed_at} />
            </span>
          )}
        </div>
      </Card>
      <Card flush>
        <DataTable rows={rows} columns={columns} rowKey={(r) => String(r.mob)} initialSort={{ key: "mob", dir: "asc" }} />
      </Card>
    </Section>
  );
}
