/**
 * Definition sensitivity: the default rate of loans originated in each quarter, recomputed under each benchmark
 * definition (30, 60 and 90 DPD ever in 12 months). It shows how much of the default rate is the definition and how much is
 * the portfolio. This is the labelled comparison of definitions: the rates are label counts, not model scores.
 */
import type { DefinitionVersion, SensitivityData } from "../../api/types";
import { fmtNum, fmtPct } from "../../lib/format";
import { LineSeriesChart, type ChartDatum } from "../charts";
import { Card, DataTable, EmptyState, KindTag, TimeAgo, type Column } from "../ui";

/** Series colors by meaning: 30 DPD is series 2, 60 DPD is series 0, 90 DPD is series 1. */
const COLOR_BY_DPD: Record<number, number> = { 30: 2, 60: 0, 90: 1 };

type Series = SensitivityData["series"][number];

export function SensitivitySection({ data, active }: { data: SensitivityData; active: DefinitionVersion | undefined }) {
  if (data.series.length === 0) {
    return (
      <EmptyState title="Not computed yet">
        The evidence job recomputes the default rate under every benchmark definition (<code>lau evidence run</code>). Once it has run, this chart shows the rate for each origination
        quarter under 30, 60 and 90 DPD.
      </EmptyState>
    );
  }
  const isActive = (s: Series) => !!active && (active.name === s.definition_key || Number(active.fields.delinquency_threshold_dpd) === s.dpd);
  const periods = [...new Set(data.series.flatMap((s) => s.points.map((p) => p.period)))].sort();
  const at = (s: Series, period: string) => s.points.find((p) => p.period === period);
  const chartData: ChartDatum[] = periods.map((period) => ({
    period,
    ...Object.fromEntries(data.series.map((s) => [s.definition_key, at(s, period)?.default_rate ?? null])),
  }));
  const values = data.series.flatMap((s) => s.points.map((p) => p.default_rate));
  const span = Math.max(...values) - Math.min(...values);
  const digits = span < 0.05 ? 1 : 0;

  // The loans behind each point are the same under every definition when the eligible population does not change.
  const sameLoans = periods.every((p) => new Set(data.series.map((s) => at(s, p)?.n)).size <= 1);
  const rows = periods.map((period) => ({ period }));
  const columns: Column<{ period: string }>[] = [
    { key: "period", header: "Origination quarter", render: (r) => r.period, sort: (r) => r.period },
    ...data.series.map<Column<{ period: string }>>((s) => ({
      key: s.definition_key,
      header: `${s.label}${isActive(s) ? " (active)" : ""}`,
      align: "right",
      render: (r) => {
        const p = at(s, r.period);
        return <span className={`num ${isActive(s) ? "definitions-strong" : ""}`}>{p ? fmtPct(p.default_rate) : "—"}</span>;
      },
      sort: (r) => at(s, r.period)?.default_rate ?? null,
    })),
    ...(sameLoans
      ? [
          {
            key: "n",
            header: "Eligible loans",
            align: "right" as const,
            render: (r: { period: string }) => fmtNum(at(data.series[0], r.period)?.n),
            sort: (r: { period: string }) => at(data.series[0], r.period)?.n ?? null,
          },
        ]
      : data.series.map<Column<{ period: string }>>((s) => ({
          key: `n-${s.definition_key}`,
          header: `Loans, ${s.label}`,
          align: "right",
          render: (r) => fmtNum(at(s, r.period)?.n),
          sort: (r) => at(s, r.period)?.n ?? null,
        }))),
  ];

  const last = periods[periods.length - 1];
  const first = periods[0];
  const activeSeries = data.series.find(isActive);
  const latest = data.series.map((s) => `${s.label} ${fmtPct(at(s, last)?.default_rate)}`).join(", ");

  return (
    <div className="stack" style={{ gap: "var(--gap)" }}>
      <Card kind="measured" title="Default rate by origination quarter">
        <div className="small muted" style={{ marginBottom: 8 }}>
          <KindTag kind="measured" /> Computed <TimeAgo iso={data.computed_at} /> by the harness, for eligible loans with 12 months observed. Latest quarter ({last}): {latest}.
          {activeSeries && at(activeSeries, first) && at(activeSeries, last) && (
            <>
              {" "}
              Under the active definition the rate went from {fmtPct(at(activeSeries, first)!.default_rate)} in {first} to {fmtPct(at(activeSeries, last)!.default_rate)} in {last}.
            </>
          )}
        </div>
        <LineSeriesChart
          title="Default rate by origination quarter under the 30, 60 and 90 days past due definitions, in percent"
          data={chartData}
          xKey="period"
          series={data.series.map((s, i) => ({
            key: s.definition_key,
            label: `${s.label}${isActive(s) ? " (active)" : ""}`,
            color: COLOR_BY_DPD[s.dpd] ?? 3 + i,
            width: isActive(s) ? 3 : 1.75,
          }))}
          yFormat={(v) => fmtPct(v, digits)}
          yDomain={[0, "auto"]}
          height={300}
        />
        <div className="xs muted">
          Y axis: share of eligible loans that default, in percent. A stricter definition (fewer days past due) counts more loans as defaults, so the lines differ in level; read
          the movement over time, not the gap between lines.
        </div>
      </Card>
      <Card flush kind="measured">
        <DataTable rows={rows} columns={columns} rowKey={(r) => r.period} initialSort={{ key: "period", dir: "asc" }} />
      </Card>
    </div>
  );
}
