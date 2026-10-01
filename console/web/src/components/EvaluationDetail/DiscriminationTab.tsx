/** Validation metrics, lift by score decile and calibration. */
import type { EvaluationDetail } from "../../api/types";
import { checkLabel, fmtAuc, fmtDiff, fmtNum, fmtPct, fmtPp } from "../../lib/format";
import { BarSeriesChart, LineSeriesChart } from "../charts";
import type { Limits } from "../Performance/thresholds";
import { Card, DataTable, Pill, Section, type Column } from "../ui";
import { CalibrationChart } from "./CalibrationChart";
import { wilson } from "./stats";
import "./evaluation.css";

type Fmt = (v: number) => string;
const four: Fmt = (v) => fmtAuc(v, 4);

function metricRows(e: EvaluationDetail, limits: Limits): { key: string; label: string; value: string; help: string }[] {
  const defs: { key: string; label: string; fmt: Fmt; help: string }[] = [
    { key: "n", label: "Loans", fmt: (v) => fmtNum(v), help: "Loans in the validation sample." },
    { key: "default_rate", label: "Default rate", fmt: (v) => fmtPct(v, 2), help: "Share of validation loans that defaulted under this definition." },
    { key: "auc", label: "AUC", fmt: four, help: "Ranking power: the chance that a defaulted loan scores riskier than one that did not default. 0.5 is random." },
    { key: "ks", label: "KS", fmt: four, help: "Largest gap between the score distributions of defaulted and non-defaulted loans." },
    { key: "brier", label: "Brier score", fmt: four, help: "Mean squared error of the predicted default probabilities. Lower is better." },
    { key: "log_loss", label: "Log loss", fmt: four, help: "Penalizes confident wrong predictions. Lower is better." },
    {
      key: "ece",
      label: "Expected calibration error",
      fmt: four,
      help: `Average gap between predicted and observed default rates across score bins.${limits.maxEce != null ? ` Limit ${fmtAuc(limits.maxEce, 2)}.` : ""}`,
    },
    {
      key: "calibration_slope",
      label: "Calibration slope",
      fmt: (v) => fmtAuc(v, 3),
      help: "Slope of observed outcomes on the predicted log-odds. 1.0 is ideal; below 1 means predictions are too spread out, above 1 too compressed.",
    },
    { key: "calibration_intercept", label: "Calibration intercept", fmt: (v) => fmtDiff(v, 3), help: "Offset of that fit. 0 is ideal." },
    { key: "mean_pd", label: "Mean predicted default rate", fmt: (v) => fmtPct(v, 2), help: "Average predicted probability of default; compare with the default rate." },
  ];
  const known = new Set(defs.map((d) => d.key));
  const rows = defs.filter((d) => e.validation[d.key] != null).map((d) => ({ key: d.key, label: d.label, value: d.fmt(e.validation[d.key] as number), help: d.help }));
  for (const [k, v] of Object.entries(e.validation)) if (!known.has(k) && v != null) rows.push({ key: k, label: checkLabel(k), value: fmtAuc(v, 4), help: "" });
  return rows;
}

export function DiscriminationTab({ e, limits }: { e: EvaluationDetail; limits: Limits }) {
  const rows = metricRows(e, limits);
  const metricCols: Column<(typeof rows)[number]>[] = [
    { key: "label", header: "Metric", render: (r) => <strong>{r.label}</strong> },
    { key: "value", header: "Value", align: "right", render: (r) => <span className="num">{r.value}</span> },
    { key: "help", header: "What it tells you", render: (r) => <span className="small muted">{r.help}</span> },
  ];
  return (
    <div className="evaluation-panel">
      <Section title="Validation metrics" note="Measured on the validation sample for this definition of default.">
        <Card flush kind="measured">
          <DataTable rows={rows} columns={metricCols} rowKey={(r) => r.key} />
        </Card>
      </Section>
      <LiftSection e={e} />
      <CalibrationSection e={e} limits={limits} />
    </div>
  );
}

function LiftSection({ e }: { e: EvaluationDetail }) {
  const lift = e.lift;
  if (lift.length === 0) return null;
  const k = lift.length;
  type Row = EvaluationDetail["lift"][number];
  const cols: Column<Row>[] = [
    { key: "decile", header: "Decile", render: (d) => `${d.decile}${d.decile === 1 ? " (riskiest)" : d.decile === k ? " (safest)" : ""}`, sort: (d) => d.decile },
    { key: "n", header: "Loans", align: "right", render: (d) => fmtNum(d.n), sort: (d) => d.n },
    {
      key: "rate",
      header: "Default rate",
      align: "right",
      render: (d) => {
        const ci = wilson(d.default_rate, d.n);
        return (
          <span className="num">
            {fmtPct(d.default_rate, 1)}
            {ci && (
              <span className="ci">
                {fmtPct(ci.lo, 1)} to {fmtPct(ci.hi, 1)}
              </span>
            )}
          </span>
        );
      },
      sort: (d) => d.default_rate,
    },
    { key: "pd", header: "Mean predicted", align: "right", render: (d) => fmtPct(d.mean_pd, 1), sort: (d) => d.mean_pd },
    { key: "lift", header: "Lift", align: "right", render: (d) => `${fmtAuc(d.lift, 2)}×`, sort: (d) => d.lift },
    { key: "cum", header: "Defaults captured, cumulative", align: "right", render: (d) => fmtPct(d.cum_capture, 1), sort: (d) => d.cum_capture },
  ];
  return (
    <Section
      title="Lift by score decile"
      note="Validation loans ranked from highest to lowest predicted risk and split into ten equal groups. Lift is a group’s default rate divided by the overall default rate."
    >
      <div className="grid cols-2">
        <Card title="Default rate by decile" kind="measured">
          <BarSeriesChart
            title="Observed default rate and mean predicted default rate by score decile, decile 1 is the riskiest"
            data={lift.map((d) => ({ decile: `D${d.decile}`, observed: d.default_rate, predicted: d.mean_pd }))}
            xKey="decile"
            series={[
              { key: "observed", label: "Observed default rate", color: 0 },
              { key: "predicted", label: "Mean predicted default rate", color: 3 },
            ]}
            yFormat={(v) => fmtPct(v, 0)}
            height={260}
          />
          <div className="xs muted">Decile 1 holds the applicants the model ranks riskiest.</div>
        </Card>
        <Card title="Defaults captured, riskiest first" kind="measured">
          <LineSeriesChart
            title="Cumulative share of defaults captured by the model against a random ranking, riskiest deciles first"
            data={[{ share: "0%", model: 0, random: 0 }, ...lift.map((d) => ({ share: fmtPct(d.decile / k, 0), model: d.cum_capture, random: d.decile / k }))]}
            xKey="share"
            series={[
              { key: "model", label: "This model", color: 0, width: 2.5 },
              { key: "random", label: "Random ranking", color: 1, dashed: true, width: 1.5 },
            ]}
            yFormat={(v) => fmtPct(v, 0)}
            height={260}
          />
          <div className="xs muted">Horizontal axis: share of applicants, riskiest first. Vertical axis: share of all defaults that fall in that group.</div>
        </Card>
      </div>
      <Card flush kind="measured">
        <DataTable rows={lift} columns={cols} rowKey={(d) => String(d.decile)} initialSort={{ key: "decile", dir: "asc" }} />
      </Card>
      <div className="xs muted">Intervals under each default rate are approximate 95% binomial (Wilson) intervals computed from the group size.</div>
    </Section>
  );
}

function CalibrationSection({ e, limits }: { e: EvaluationDetail; limits: Limits }) {
  const bins = e.calibration;
  if (bins.length === 0) return null;
  type Row = EvaluationDetail["calibration"][number];
  const halves = bins.flatMap((b) => {
    const ci = wilson(b.observed, b.n);
    return ci ? [(ci.hi - ci.lo) / 2] : [];
  });
  const typicalHalfWidth = halves.length ? [...halves].sort((a, b) => a - b)[Math.floor(halves.length / 2)] : 0;
  const cols: Column<Row>[] = [
    { key: "bin", header: "Bin", render: (b) => `${b.bin + 1}${b.bin === 0 ? " (lowest risk)" : b.bin === bins.length - 1 ? " (highest risk)" : ""}`, sort: (b) => b.bin },
    { key: "n", header: "Loans", align: "right", render: (b) => fmtNum(b.n), sort: (b) => b.n },
    { key: "pred", header: "Predicted", align: "right", render: (b) => fmtPct(b.predicted, 1), sort: (b) => b.predicted },
    {
      key: "obs",
      header: "Observed",
      align: "right",
      render: (b) => {
        const ci = wilson(b.observed, b.n);
        return (
          <span className="num">
            {fmtPct(b.observed, 1)}
            {ci && (
              <span className="ci">
                {fmtPct(ci.lo, 1)} to {fmtPct(ci.hi, 1)}
              </span>
            )}
          </span>
        );
      },
      sort: (b) => b.observed,
    },
    { key: "gap", header: "Observed minus predicted", align: "right", render: (b) => fmtPp(b.observed - b.predicted, 1), sort: (b) => b.observed - b.predicted },
    {
      key: "in",
      header: "Predicted rate",
      render: (b) => {
        const ci = wilson(b.observed, b.n);
        if (!ci) return <span className="muted">—</span>;
        const inside = b.predicted >= ci.lo && b.predicted <= ci.hi;
        return inside ? <span className="small muted">inside the interval</span> : <Pill tone="warn">outside the interval</Pill>;
      },
    },
  ];
  return (
    <Section
      title="Calibration"
      note={`Loans grouped into ${bins.length} bins by predicted default rate, lowest first. Points on the diagonal mean predicted and observed rates agree. The whisker is an approximate 95% binomial interval on the observed rate.`}
    >
      <div className="grid cols-2">
        <Card title="Predicted against observed" kind="measured">
          <CalibrationChart title="Observed against predicted default rate by score bin, with the perfect calibration diagonal and 95% intervals" bins={bins} />
        </Card>
        <Card title="How well calibrated" kind="measured">
          <dl className="kv">
            <dt>Expected calibration error</dt>
            <dd className="num">
              {fmtAuc(e.validation.ece, 4)}
              {limits.maxEce != null && <span className="muted"> (limit {fmtAuc(limits.maxEce, 2)})</span>}
            </dd>
            <dt>Calibration slope</dt>
            <dd className="num">{fmtAuc(e.validation.calibration_slope, 3)} <span className="muted">(1.0 is ideal)</span></dd>
            <dt>Calibration intercept</dt>
            <dd className="num">{e.validation.calibration_intercept == null ? "—" : fmtDiff(e.validation.calibration_intercept, 3)} <span className="muted">(0 is ideal)</span></dd>
            <dt>Mean predicted default rate</dt>
            <dd className="num">{fmtPct(e.validation.mean_pd, 2)}</dd>
            <dt>Observed default rate</dt>
            <dd className="num">{fmtPct(e.validation.default_rate, 2)}</dd>
          </dl>
          <div className="xs muted" style={{ marginTop: 8 }}>
            With about {fmtNum(Math.round(bins.reduce((t, b) => t + b.n, 0) / bins.length))} loans per bin, the 95% interval on an observed rate is typically ±{fmtNum(typicalHalfWidth * 100, 1)}{" "}
            points, so smaller gaps between predicted and observed are within sampling noise.
          </div>
        </Card>
      </div>
      <Card flush kind="measured">
        <DataTable rows={bins} columns={cols} rowKey={(b) => String(b.bin)} initialSort={{ key: "bin", dir: "asc" }} />
      </Card>
    </Section>
  );
}
