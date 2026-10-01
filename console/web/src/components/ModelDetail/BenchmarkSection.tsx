/**
 * Benchmark position: this model re-scored on the same loans as every other model, under each frozen benchmark
 * definition, with paired differences and their 95% intervals against the best model and the legacy score.
 */
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { BenchmarkMatrix, BenchmarkRow, ModelCard, ProgressData } from "../../api/types";
import { fmtAuc, fmtDiff, fmtInterval, fmtNum, fmtPct } from "../../lib/format";
import { IntervalChart } from "../charts";
import { Card, DataTable, EmptyState, KeyValue, ModelBadge, Pill, Section, TimeAgo, type Column } from "../ui";
import { benchLines, noiseVerdict, type BenchLine } from "./benchmark";

export function BenchmarkSection({ card, progress, progressFailed }: { card: ModelCard; progress: ProgressData | undefined; progressFailed: boolean }) {
  const row = card.benchmark;
  if (!row) {
    return (
      <Section title="Benchmark position">
        <EmptyState title="Not on the benchmark ledger yet">
          The evidence job re-scores every registered model on the newest matured loans under each benchmark definition. This version has not been scored yet,
          so it cannot be compared with the other models. <Link to="/progress">Open the ledger on Progress</Link>.
        </EmptyState>
      </Section>
    );
  }
  const matrix = progress?.benchmark ?? null;
  const lines = benchLines(card, progress);
  const legacy = matrix?.rows.find((r) => r.model.kind === "reference");

  const columns: Column<BenchLine>[] = [
    {
      key: "bench",
      header: "Benchmark",
      render: (l) => (
        <span>
          {l.label}
          <span className="models-cell-sub">
            {[l.isPrimary ? "primary" : null, l.isOwnDefinition ? "this model’s definition" : null, l.nDefaults != null ? `${fmtNum(l.nDefaults)} defaults` : null].filter(Boolean).join(" · ")}
          </span>
        </span>
      ),
    },
    {
      key: "auc",
      header: "AUC, this model",
      align: "right",
      render: (l) =>
        l.cell ? (
          <span className="num">
            {fmtAuc(l.cell.auc, 4)}
            {l.isBest && <span className="xs"> best</span>}
            {l.cell.ci_lo != null && l.cell.ci_hi != null && (
              <span className="ci">
                {fmtAuc(l.cell.ci_lo, 3)} to {fmtAuc(l.cell.ci_hi, 3)}
              </span>
            )}
          </span>
        ) : (
          "—"
        ),
      className: (l) => (l.isBest ? "cell-best" : undefined),
    },
    {
      key: "best",
      header: "Best of all models on this benchmark",
      render: (l) =>
        l.best ? (
          <span className="row" style={{ gap: 6 }}>
            <ModelBadge model={l.best.model} />
            <span className="num small">{fmtAuc(l.best.cell.auc, 4)}</span>
          </span>
        ) : (
          <span className="muted">—</span>
        ),
    },
    {
      key: "vs",
      header: "Paired difference from the best",
      render: (l) => {
        if (!l.vsBest) return <span className="muted">—</span>;
        const v = noiseVerdict(l.vsBest.diff);
        return (
          <span>
            <span className="num">
              {l.vsBest.model.label} − {l.vsBest.versus.label}
              {l.isBest ? " (runner-up)" : ""}: {fmtInterval(l.vsBest.diff, 4)}
            </span>
            <span className="models-cell-sub">
              <Pill tone={v.tone}>{v.text}</Pill>
            </span>
          </span>
        );
      },
    },
    {
      key: "lift",
      header: "Lift over the legacy score",
      render: (l) =>
        l.vsLegacy ? (
          <span className="num">
            {fmtInterval(l.vsLegacy.diff, 3)}
            <span className="models-cell-sub">AUC, same loans</span>
          </span>
        ) : (
          <span className="muted">—</span>
        ),
    },
  ];

  const chartRows = (pick: (l: BenchLine) => { label: string; diff: { estimate: number; lo: number; hi: number } } | undefined) =>
    lines.flatMap((l) => {
      const r = pick(l);
      return r ? [{ label: r.label, ...r.diff }] : [];
    });
  const vsBestRows = chartRows((l) => (l.vsBest ? { label: `${l.label.split(" ")[0]} DPD: ${l.vsBest.model.label} − ${l.vsBest.versus.label}`, diff: l.vsBest.diff } : undefined));
  const vsLegacyRows = chartRows((l) => (l.vsLegacy ? { label: `${l.label.split(" ")[0]} DPD`, diff: l.vsLegacy.diff } : undefined));
  const dagger = row.selected_on_window;

  return (
    <Section
      title="Benchmark position"
      right={
        <Link className="small" to="/progress">
          Full ledger on Progress
        </Link>
      }
      note={
        matrix ? (
          <BenchNote matrix={matrix} />
        ) : (
          "Comparisons with other models need the benchmark ledger, which did not load."
        )
      }
    >
      <Card flush kind="measured">
        <DataTable rows={lines} columns={columns} rowKey={(l) => l.key} />
      </Card>
      {progressFailed && (
        <div className="small muted">The benchmark ledger did not load, so the best model and the paired differences are not shown.</div>
      )}
      {vsBestRows.length > 0 && (
        <div className="grid cols-2">
          <Card title="Paired AUC difference from the best other model" kind="measured">
            <IntervalChart title="AUC difference from the best model on each benchmark, with 95% interval" rows={vsBestRows} format={(v) => fmtDiff(v, 3)} zeroLabel="same as best" />
            <div className="xs muted">Where this model is the best, the comparison is with the runner-up. An interval that includes zero means no difference is established.</div>
          </Card>
          <Card title="Lift over the frozen legacy score" kind="measured">
            <IntervalChart title="AUC difference from the legacy score on each benchmark, with 95% interval" rows={vsLegacyRows} format={(v) => fmtDiff(v, 3)} zeroLabel="no lift" />
            <div className="xs muted">The legacy score never changes, so this lift shows progress independent of the population getting easier or harder.</div>
          </Card>
        </div>
      )}
      {matrix && row.bad_rate_at_fixed_approval != null && (
        <Card title={`Bad rate when approving ${fmtPct(matrix.fixed_approval_rate, 0)} of applicants`} kind="measured">
          <KeyValue
            items={badRateItems(
              row.bad_rate_at_fixed_approval,
              legacy?.bad_rate_at_fixed_approval ?? null,
              matrix.rows.find((r) => r.model.kind !== "reference" && r.is_best[matrix.primary_definition]),
              card.model.key,
            )}
          />
          <div className="xs muted" style={{ marginTop: 6 }}>
            Share of approved loans that default when the model approves the lowest-risk {fmtPct(matrix.fixed_approval_rate, 0)}; lower is better. Measured under the primary benchmark.
          </div>
        </Card>
      )}
      {dagger && (
        <div className="xs muted">This model was evaluated on this window while it was being selected, so its scores here are optimistic.</div>
      )}
    </Section>
  );
}

function BenchNote({ matrix }: { matrix: BenchmarkMatrix }) {
  const n = matrix.rows.filter((r) => r.model.kind !== "reference").length;
  return (
    <>
      All {n} registered models are scored on the same {fmtNum(matrix.window.n_loans)} loans ({matrix.window.start} to {matrix.window.end} originations) under each frozen benchmark definition, so
      “best” means the highest of {n}. Computed <TimeAgo iso={matrix.computed_at} />.
    </>
  );
}

function badRateItems(model: number, legacy: number | null, best: BenchmarkRow | undefined, selfKey: string): [ReactNode, ReactNode][] {
  const items: [ReactNode, ReactNode][] = [["This model", <span key="m" className="num">{fmtPct(model, 1)}</span>]];
  if (best && best.model.key !== selfKey && best.bad_rate_at_fixed_approval != null) {
    items.push([`Best known model (${best.model.label})`, <span key="b" className="num">{fmtPct(best.bad_rate_at_fixed_approval, 1)}</span>]);
  }
  if (legacy != null) items.push(["Legacy score", <span key="l" className="num">{fmtPct(legacy, 1)}</span>]);
  return items;
}
