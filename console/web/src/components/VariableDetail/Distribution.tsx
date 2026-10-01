/** How a variable's values are distributed: percentiles for a numeric variable, the most common values for a categorical one. */
import type { CatalogVariable } from "../../api/types";
import { fmtNum, fmtPct } from "../../lib/format";
import { HBars } from "../shared";
import { Card, EmptyState, KeyValue, Section } from "../ui";
import { RangeStrip, fmtVal } from "./RangeStrip";

export function Distribution({ x }: { x: CatalogVariable }) {
  const numeric = x.dtype === "numeric";
  return (
    <Section
      title={numeric ? "Distribution" : "Most common values"}
      note={numeric ? "Percentiles and the mean over the applications in the catalog sample." : `Shares of the ${fmtNum(x.cardinality)} distinct values; only the most common are kept.`}
    >
      {numeric ? <Percentiles x={x} /> : <TopValues x={x} />}
    </Section>
  );
}

function Percentiles({ x }: { x: CatalogVariable }) {
  if (x.p01 == null || x.p50 == null || x.mean == null || x.p99 == null) {
    return <EmptyState title="No distribution statistics">The catalog has no percentiles for this variable.</EmptyState>;
  }
  return (
    <div className="grid split">
      <Card title="Where the values sit" kind="measured">
        <RangeStrip
          p01={x.p01}
          p50={x.p50}
          mean={x.mean}
          p99={x.p99}
          title={`Distribution of ${x.variable}: 1st percentile ${fmtVal(x.p01)}, median ${fmtVal(x.p50)}, mean ${fmtVal(x.mean)}, 99th percentile ${fmtVal(x.p99)}`}
        />
        <div className="xs muted">The strip runs from the 1st to the 99th percentile; the lowest and highest 1% of values lie outside it.</div>
      </Card>
      <Card title="Exact values" kind="measured">
        <KeyValue
          items={[
            ["1st percentile", <span key="a" className="num">{fmtVal(x.p01)}</span>],
            ["Median", <span key="b" className="num">{fmtVal(x.p50)}</span>],
            ["Mean", <span key="c" className="num">{fmtVal(x.mean)}</span>],
            ["99th percentile", <span key="d" className="num">{fmtVal(x.p99)}</span>],
          ]}
        />
      </Card>
    </div>
  );
}

function TopValues({ x }: { x: CatalogVariable }) {
  const top = x.top_values ? Object.entries(x.top_values).sort((a, b) => b[1] - a[1]) : [];
  if (top.length === 0) {
    return <EmptyState title="No value counts recorded">The catalog keeps the five most common values of each categorical variable; none were recorded for this one.</EmptyState>;
  }
  const topSum = top.reduce((s, [, v]) => s + v, 0);
  const maxTop = Math.max(...top.map(([, v]) => v));
  const other = Math.max(0, 1 - topSum);
  return (
    <Card kind="measured">
      <HBars
        title={`Most common values of ${x.variable}`}
        rows={[
          ...top.map(([k, v]) => ({ key: k, label: <span className="mono">{k}</span>, value: v })),
          // a bar for "all other values" only when it is comparable to the common values; otherwise it would dwarf them
          ...(other > 0.0005 && other <= maxTop ? [{ key: "__other", label: <span className="muted">All other values</span>, value: other, tone: "muted" as const }] : []),
        ]}
        format={(v) => fmtPct(v, 1)}
        max={maxTop}
        footnote={`The top ${top.length} values hold ${fmtPct(topSum, 1)} of applications${x.cardinality ? `, out of ${fmtNum(x.cardinality)} distinct values` : ""}${other > maxTop ? `; all other values together hold ${fmtPct(other, 1)}` : ""}.`}
      />
    </Card>
  );
}
