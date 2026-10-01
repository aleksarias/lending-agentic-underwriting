/** Feature importance as bars drawn to scale plus an exact table. Used by the model and evaluation detail screens. */
import { Link } from "react-router-dom";
import { fmtPct } from "../../lib/format";
import { HBars } from "../shared";
import { Card, DataTable, EmptyState, links, type Column } from "../ui";

interface Row {
  feature: string;
  share: number;
  rank: number;
  cumulative: number;
  engineered: boolean;
}

export function FeatureImportance({ rows, engineered, modelType }: { rows: { feature: string; share: number }[]; engineered: string[]; modelType?: string | null }) {
  if (rows.length === 0) {
    return <EmptyState title="No feature importance recorded">Importance is recorded when the harness evaluates a version.</EmptyState>;
  }
  const eng = new Set(engineered);
  let running = 0;
  const data: Row[] = rows.map((r, i) => {
    running += r.share;
    return { ...r, rank: i + 1, cumulative: running, engineered: eng.has(r.feature) };
  });
  const method = modelType === "logreg" ? "the summed absolute coefficients" : modelType === "lightgbm" ? "total gain" : "the model’s importance score";
  const columns: Column<Row>[] = [
    { key: "rank", header: "#", align: "right", render: (r) => r.rank, sort: (r) => r.rank },
    {
      key: "feature",
      header: "Feature",
      render: (r) =>
        r.engineered ? (
          <span>
            <span className="mono">{r.feature}</span> <span className="xs muted">engineered</span>
          </span>
        ) : (
          <Link className="mono" to={links.variable(r.feature)}>
            {r.feature}
          </Link>
        ),
      sort: (r) => r.feature,
    },
    { key: "share", header: "Share", align: "right", render: (r) => <span className="num">{fmtPct(r.share, 1)}</span>, sort: (r) => r.share },
    { key: "cum", header: "Cumulative", align: "right", render: (r) => <span className="num">{fmtPct(r.cumulative, 1)}</span>, sort: (r) => r.cumulative },
  ];
  return (
    <div className="grid cols-2">
      <Card title="Share of the model’s importance" kind="measured">
        <HBars
          title="Feature importance shares"
          rows={data.map((r) => ({
            key: r.feature,
            label: r.engineered ? (
              <span>
                <span className="mono">{r.feature}</span> <span className="xs muted">engineered</span>
              </span>
            ) : (
              <Link className="mono" to={links.variable(r.feature)}>
                {r.feature}
              </Link>
            ),
            value: r.share,
          }))}
          format={(v) => fmtPct(v, 1)}
          footnote={`Importance is ${method}, as a share of the total. It shows how much the model relies on a feature, not that the feature causes default.`}
        />
      </Card>
      <Card flush kind="measured">
        <DataTable rows={data} columns={columns} rowKey={(r) => r.feature} maxHeight={420} />
      </Card>
    </div>
  );
}
