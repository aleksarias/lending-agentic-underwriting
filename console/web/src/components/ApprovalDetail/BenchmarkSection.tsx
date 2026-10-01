/**
 * Benchmark position: how this candidate scores against the best known model on the same loans, under each frozen
 * benchmark definition, with paired 95% intervals.
 *
 * The evidence packet carries the candidate's own benchmark row and a yes/no/unknown "beats the best known model".
 * The comparison itself (who is best on each benchmark, and the paired difference) lives in the benchmark ledger that
 * the Progress screen reads, so this section reads that too. When the packet has no row for the model (for example
 * because the registry name in the packet is spelled differently from the ledger's) the row is found in the ledger by
 * version and the section says so; it never invents a number.
 */
import { useMemo, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useProgress } from "../../api/hooks";
import type { BenchmarkRow, DiffRow, EvidencePacket, ModelRef, Tone } from "../../api/types";
import { fmtAuc, fmtDiff, fmtInterval, intervalTone } from "../../lib/format";
import { IntervalChart } from "../charts";
import { sameModel } from "../Operate/models";
import { Banner, Card, DataTable, ErrorState, Loading, ModelBadge, Pill, Section, type Column } from "../ui";

interface BenchDef {
  key: string;
  label: string;
  dpd: number;
  primary: boolean;
}

export interface Position {
  loading: boolean;
  error: unknown;
  source: "packet" | "ledger" | "none";
  row: BenchmarkRow | null;
  defs: BenchDef[];
  best: ModelRef | null;
  bestOn: Record<string, { model: ModelRef; auc: number } | undefined>;
  diffs: Record<string, DiffRow | undefined>;
  isBest: boolean;
  beats: boolean | null;
  primary: BenchDef | null;
  modelsScored: number | null;
}

function defFromKey(key: string): { label: string; dpd: number } {
  const m = key.match(/^dpd(\d+)_(ever|eow)_(\d+)m$/);
  if (!m) return { label: key, dpd: 0 };
  return { label: `${m[1]} DPD ${m[2] === "ever" ? "ever" : "at end of window"} / ${m[3]} months`, dpd: Number(m[1]) };
}

export function useBenchmarkPosition(p: EvidencePacket): Position {
  const progress = useProgress();
  const data = progress.data;
  return useMemo(() => {
    const matrix = data?.benchmark ?? null;
    const ledgerRow = matrix?.rows.find((r) => sameModel(r.model, p.model)) ?? null;
    const row = p.benchmark.row ?? ledgerRow;
    const source: Position["source"] = p.benchmark.row ? "packet" : ledgerRow ? "ledger" : "none";
    const best = p.benchmark.best_known ?? data?.verdict?.best_known ?? null;
    const defs: BenchDef[] = matrix
      ? matrix.definitions.map((d) => ({ key: d.key, label: d.label, dpd: d.dpd, primary: d.key === matrix.primary_definition }))
      : row
        ? Object.keys(row.metrics)
            .map((k) => ({ key: k, ...defFromKey(k), primary: false }))
            .sort((a, b) => a.dpd - b.dpd)
        : [];
    const bestOn: Position["bestOn"] = {};
    for (const d of defs) {
      const b = matrix?.rows.find((r) => r.model.kind !== "reference" && r.is_best[d.key]);
      if (b && b.metrics[d.key]) bestOn[d.key] = { model: b.model, auc: b.metrics[d.key].auc };
    }
    const diffs: Position["diffs"] = {};
    for (const d of data?.best_known_diffs ?? []) if (sameModel(d.model, p.model)) diffs[d.definition_key] = d;
    const primary = defs.find((d) => d.primary) ?? null;
    const isBest = !!best && (sameModel(best, p.model) || (!!row && sameModel(row.model, best)));
    let beats = p.benchmark.beats_best_known;
    if (beats == null) {
      if (isBest) beats = true;
      else if (primary && diffs[primary.key]) beats = diffs[primary.key]!.diff.lo > 0;
    }
    return {
      loading: progress.isLoading,
      error: progress.error,
      source,
      row,
      defs,
      best,
      bestOn,
      diffs,
      isBest,
      beats,
      primary,
      modelsScored: matrix ? matrix.rows.filter((r) => r.model.kind !== "reference").length : null,
    };
  }, [data, p, progress.isLoading, progress.error]);
}

function verdictOf(diff: DiffRow["diff"] | undefined): "better" | "worse" | "noise" | null {
  if (!diff) return null;
  const t = intervalTone(diff);
  return t === "good" ? "better" : t === "crit" ? "worse" : "noise";
}

function Headline({ p, pos }: { p: EvidencePacket; pos: Position }) {
  const label = p.model.label;
  const primary = pos.primary;
  const pd = primary ? pos.diffs[primary.key] : undefined;
  const bestLabel = pd && !pos.isBest ? pd.versus.label : (pos.best?.label ?? "the best known model");
  const onPrimary = primary ? `under ${primary.label}` : "on the primary benchmark";
  const candAuc = primary ? pos.row?.metrics[primary.key]?.auc : undefined;
  const bestAuc = primary ? pos.bestOn[primary.key]?.auc : undefined;
  const verdict = verdictOf(pd?.diff);

  if (pos.beats === true && pos.isBest) {
    const established = verdict === "better";
    return (
      <Banner tone={established || !pd ? "good" : "neutral"} title={established || !pd ? "Yes: it is the best known model" : "Yes, it is the best known model, with no established lead"}>
        {label} has the highest AUC{pos.modelsScored ? ` of the ${pos.modelsScored} models scored` : ""} {onPrimary}.
        {pd && (
          <>
            {" "}
            Its lead over the runner-up ({pd.versus.label}) is {fmtInterval(pd.diff, 4)}
            {established ? "." : ": the interval includes zero, so the models near the top are not separated by this evidence."}
          </>
        )}
      </Banner>
    );
  }
  if (pos.beats === true) {
    return (
      <Banner tone="good" title={`Yes: it beats the best known model (${bestLabel})`}>
        {pd ? `Difference ${onPrimary}: ${fmtInterval(pd.diff, 4)}, so the whole interval is above zero.` : "The benchmark ledger shows its lead over the best known model is established."}
      </Banner>
    );
  }
  if (pos.beats === false) {
    return (
      <Banner tone="warn" title={`No: not shown to beat the best known model (${bestLabel})`}>
        {pd ? (
          <>
            {label} scores {fmtAuc(candAuc, 4)} against {fmtAuc(bestAuc, 4)} for {bestLabel} {onPrimary}. The difference is {fmtInterval(pd.diff, 4)}.{" "}
            {verdict === "worse"
              ? "The whole interval is below zero, so it is shown to be worse."
              : "The interval includes zero, so neither model is shown to be better."}
          </>
        ) : (
          "The benchmark ledger does not show it beating the best known model."
        )}
      </Banner>
    );
  }
  return (
    <Banner tone="neutral" title="Unknown: it has not been compared with the best known model">
      The benchmark ledger has no comparison for this model, so nobody can say whether it beats {bestLabel}. The evidence job (<code>lau evidence run</code>) scores every
      registered model on the same loans; run it before relying on this packet.
    </Banner>
  );
}

const VERDICT_TEXT: Record<"better" | "worse" | "noise", { tone: Tone; text: string }> = {
  better: { tone: "good", text: "interval above zero" },
  worse: { tone: "crit", text: "interval below zero" },
  noise: { tone: "warn", text: "interval includes zero" },
};

export function BenchmarkSection({ p, pos }: { p: EvidencePacket; pos: Position }) {
  const { row } = pos;

  type R = BenchDef;
  const columns: Column<R>[] = [
    {
      key: "bench",
      header: "Benchmark",
      render: (d) => (
        <span>
          {d.label}
          {d.primary && <span className="xs muted"> (primary)</span>}
        </span>
      ),
      sort: (d) => d.dpd,
    },
    {
      key: "cand",
      header: `${p.model.label} AUC`,
      align: "right",
      render: (d) => {
        const c = row?.metrics[d.key];
        if (!c) return "—";
        return (
          <span className="num">
            {fmtAuc(c.auc, 4)}
            {row?.selected_on_window && <span className="xs muted" title="Evaluated on this window while being selected: optimistic"> †</span>}
            {c.ci_lo != null && c.ci_hi != null && (
              <span className="ci">
                {fmtAuc(c.ci_lo, 3)} to {fmtAuc(c.ci_hi, 3)}
              </span>
            )}
          </span>
        );
      },
    },
    {
      key: "best",
      header: "Best on this benchmark",
      render: (d) => {
        const b = pos.bestOn[d.key];
        if (!b) return <span className="faint">—</span>;
        const itself = sameModel(b.model, p.model);
        return (
          <span className="row" style={{ gap: 6 }}>
            {itself ? <strong>{p.model.label} (this candidate)</strong> : <ModelBadge model={b.model} />}
            <span className="num muted">{fmtAuc(b.auc, 4)}</span>
          </span>
        );
      },
    },
    {
      key: "diff",
      header: "Difference (AUC, paired)",
      render: (d) => {
        const diff = pos.diffs[d.key];
        if (!diff) return <span className="faint">—</span>;
        const top = pos.bestOn[d.key];
        const itself = !!top && sameModel(top.model, p.model);
        const v = verdictOf(diff.diff)!;
        return (
          <span className="stack" style={{ gap: 2 }}>
            <span className="num">
              {itself ? "lead over" : "against"} {diff.versus.label}: {fmtInterval(diff.diff, 4)}
            </span>
            <span>
              <Pill tone={VERDICT_TEXT[v].tone}>{itself && v !== "better" ? "lead inside noise" : VERDICT_TEXT[v].text}</Pill>
            </span>
          </span>
        );
      },
    },
  ];

  const chartRows = pos.defs
    .map((d) => ({ d, diff: pos.diffs[d.key] }))
    .filter((x): x is { d: BenchDef; diff: DiffRow } => !!x.diff)
    .map(({ d, diff }) => ({ label: `${d.dpd} DPD: ${p.model.label} − ${diff.versus.label}`, ...diff.diff }));

  let body: ReactNode;
  if (!row && pos.loading) body = <Loading height={120} />;
  else if (!row && pos.error) body = <ErrorState error={pos.error} />;
  else {
    body = (
      <>
        <Headline p={p} pos={pos} />
        {row ? (
          <Card flush kind="measured">
            <DataTable rows={pos.defs} columns={columns} rowKey={(d) => d.key} initialSort={{ key: "bench", dir: "asc" }} />
          </Card>
        ) : null}
        {chartRows.length > 0 && (
          <Card kind="measured" title="Paired differences with 95% intervals: this candidate minus the best model on each benchmark">
            <IntervalChart title={`AUC difference between ${p.model.label} and the best model on each benchmark`} rows={chartRows} format={(v) => fmtDiff(v, 3)} zeroLabel="no difference" />
          </Card>
        )}
        <div className="xs muted">
          {row?.selected_on_window && <span>† Evaluated on this window while being selected, so its scores here are optimistic. </span>}
          {pos.source === "ledger" && (
            <span>
              The evidence packet has no benchmark row for this model, so the figures come from the benchmark ledger on <Link to="/progress">Progress</Link>.{" "}
            </span>
          )}
          Where the interval includes zero, the models are not separated by this evidence.
        </div>
      </>
    );
  }

  return (
    <Section
      title="Benchmark position against the best known model"
      note="Every model is re-scored on the same recent loans under the same frozen benchmark definitions, so they can share an axis here and nowhere else. Intervals are paired bootstrap, 95%."
    >
      {body}
    </Section>
  );
}
