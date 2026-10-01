/**
 * The predicted default probability of the newest applications under each model scored in the latest run, as shares of
 * applications in 5-point bands. The chart is labeled and the exact shares sit in a table beside it.
 */
import type { ShadowData } from "../../api/types";
import { fmtPct } from "../../lib/format";
import { BarSeriesChart, useChartColors } from "../charts";
import { Card, DataTable, type Column } from "../ui";
import { roleLabel } from "./roles";

type Dist = ShadowData["distributions"][number];

/** "0.05" with a step of 0.05 becomes "5–10%". */
function band(edge: number, step: number): string {
  const lo = Math.round(edge * 100);
  const hi = Math.round((edge + step) * 100);
  return `${lo}–${hi}%`;
}

export function Distribution({ distributions }: { distributions: Dist[] }) {
  const c = useChartColors();
  const roles = distributions.map((d) => d.role);
  const first = distributions[0]?.bins ?? [];
  const step = first.length > 1 ? first[1].edge - first[0].edge : 0.05;
  const rows = first.map((b, i) => {
    const row: Record<string, string | number> = { band: band(b.edge, step), edge: b.edge };
    for (const d of distributions) row[d.role] = d.bins[i]?.share ?? 0;
    return row;
  });
  const color = (role: string, i: number): number | string => (role === "serving" ? 0 : role === "challenger" ? 3 : role === "baseline" ? c.muted : i + 1);

  const columns: Column<(typeof rows)[number]>[] = [
    { key: "band", header: "Band", render: (r) => String(r.band), sort: (r) => Number(r.edge) },
    ...roles.map<Column<(typeof rows)[number]>>((role) => ({
      key: role,
      header: roleLabel(role),
      align: "right",
      render: (r) => <span className="num">{fmtPct(Number(r[role]), 1)}</span>,
      sort: (r) => Number(r[role]),
    })),
  ];

  return (
    <div className="grid split">
      <Card kind="measured" title="Share of applications by predicted default probability">
        <BarSeriesChart
          title="Share of the newest applications in each 5-point band of predicted default probability, one series per model scored"
          data={rows}
          xKey="band"
          series={roles.map((role, i) => ({ key: role, label: roleLabel(role), color: color(role, i) }))}
          yFormat={(v) => fmtPct(v, 1)}
          height={300}
        />
        <div className="xs muted">Horizontal axis: predicted probability of default in 5-point bands. Vertical axis: share of the applications scored.</div>
      </Card>
      <div className="stack">
        <div className="small muted">Exact shares of the applications scored, by band of predicted default probability.</div>
        <Card flush kind="measured">
          <DataTable rows={rows} columns={columns} rowKey={(r) => String(r.band)} initialSort={{ key: "band", dir: "asc" }} maxHeight={360} />
        </Card>
      </div>
    </div>
  );
}
