/**
 * Where a model stands on the benchmark ledger: its AUC under each frozen benchmark definition, who is best there,
 * and the paired differences (with intervals) against the best model and against the frozen legacy score.
 * All numbers come from the progress payload (harness measurements); nothing is computed here except wording.
 */
import type { BenchmarkCell, DiffRow, Interval, ModelCard, ModelRef, ProgressData, Tone } from "../../api/types";
import { fmtAuc, fmtDiff, intervalTone } from "../../lib/format";

export interface BenchLine {
  key: string;
  label: string;
  nDefaults: number | null;
  isPrimary: boolean;
  /** the benchmark definition is the definition this model was trained under */
  isOwnDefinition: boolean;
  cell?: BenchmarkCell;
  isBest: boolean;
  best?: { model: ModelRef; cell: BenchmarkCell };
  /** this model minus the best model (or minus the runner-up when this model is the best) */
  vsBest?: DiffRow;
  vsLegacy?: DiffRow;
}

/** "dpd60_ever_12m" -> "60 DPD ever / 12 months" (only used when the benchmark matrix is unavailable) */
export function benchLabelFromKey(key: string): string {
  const m = /^dpd(\d+)_(ever|end_of_window)_(\d+)m$/.exec(key);
  return m ? `${m[1]} DPD ${m[2] === "ever" ? "ever" : "at end of window"} / ${m[3]} months` : key;
}

export function benchLines(card: ModelCard, progress: ProgressData | undefined): BenchLine[] {
  const row = card.benchmark;
  if (!row) return [];
  const matrix = progress?.benchmark ?? null;
  const defs = matrix
    ? matrix.definitions.map((d) => ({ key: d.key, label: d.label, version: d.version, nDefaults: d.n_defaults as number | null }))
    : Object.keys(row.metrics).map((key) => ({ key, label: benchLabelFromKey(key), version: "", nDefaults: null as number | null }));
  return defs.map((d) => {
    const bestRow = matrix?.rows.find((r) => r.model.kind !== "reference" && r.is_best[d.key]);
    const bestCell = bestRow?.metrics[d.key];
    return {
      key: d.key,
      label: d.label,
      nDefaults: d.nDefaults,
      isPrimary: matrix?.primary_definition === d.key,
      isOwnDefinition: !!d.version && d.version === card.model.definition_version,
      cell: row.metrics[d.key],
      isBest: !!row.is_best[d.key],
      best: bestRow && bestCell ? { model: bestRow.model, cell: bestCell } : undefined,
      vsBest: progress?.best_known_diffs.find((x) => x.model.key === card.model.key && x.definition_key === d.key),
      vsLegacy: progress?.reference_diffs.find((x) => x.model.key === card.model.key && x.definition_key === d.key),
    };
  });
}

/** The line a one-sentence summary should talk about: the model's own definition, else the primary benchmark. */
export function focusLine(lines: BenchLine[]): BenchLine | undefined {
  return lines.find((l) => l.isOwnDefinition && l.cell) ?? lines.find((l) => l.isPrimary && l.cell) ?? lines.find((l) => l.cell);
}

export function noiseVerdict(i: Interval | null | undefined): { text: string; tone: Tone } {
  const tone = intervalTone(i);
  if (tone === "good") return { text: "clearly ahead", tone };
  if (tone === "crit") return { text: "clearly behind", tone };
  return { text: "within noise", tone: i ? "warn" : "neutral" };
}

/** Plain-language comparison with the best model on one benchmark, used in the summary sentence and tiles. */
export function vsBestSentence(line: BenchLine): string {
  if (!line.cell) return "";
  const d = line.vsBest?.diff;
  if (line.isBest) {
    const runner = line.vsBest?.versus;
    if (!runner || !d) return `it has the highest AUC on the same loans (${fmtAuc(line.cell.auc)})`;
    const tail = noiseVerdict(d).tone === "warn" ? ", which is within noise" : "";
    return `it has the highest AUC on the same loans (${fmtAuc(line.cell.auc)}), ahead of the runner-up ${runner.label} by ${fmtDiff(d.estimate)}${tail}`;
  }
  if (!line.best) return "";
  const v = noiseVerdict(d);
  const gap = d ? (v.tone === "warn" ? "; the gap is within noise" : v.tone === "crit" ? "; the gap is larger than noise" : "") : "";
  return `${line.best.model.label} scores higher on the same loans (${fmtAuc(line.best.cell.auc)} against ${fmtAuc(line.cell.auc)})${gap}`;
}
