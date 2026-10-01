/** Stability: AUC by time slice and by segment, thin-file performance, and score drift. */
import type { EvaluationDetail, Tile } from "../../api/types";
import { fmtAuc, fmtDiff, titleCase } from "../../lib/format";
import { HBars, type HBarRow } from "../shared";
import type { Limits } from "../Performance/thresholds";
import { Card, EmptyState, Section, Tiles } from "../ui";
import "./evaluation.css";

const slice = (k: string) => k.replace("..", " to ");

function segmentLabel(variable: string, value: string): string {
  if (variable === "thin_file") return value === "True" ? "Thin file" : "Not thin file";
  return value;
}

function axis(values: number[]): { min: number; max: number } {
  const hi = Math.max(0.75, ...values);
  return { min: 0.5, max: Math.ceil(hi * 20) / 20 };
}

export function StabilityTab({ e, limits }: { e: EvaluationDetail; limits: Limits }) {
  const auc = e.validation.auc ?? e.val_auc;
  const slices = Object.entries(e.time_slices);
  const segs = Object.entries(e.segments);
  const groups = new Map<string, [string, number][]>();
  for (const [k, v] of segs) {
    const [variable, ...rest] = k.split("=");
    groups.set(variable, [...(groups.get(variable) ?? []), [rest.join("="), v]]);
  }
  const floorSlice = limits.maxSliceAucDrop != null ? auc - limits.maxSliceAucDrop : undefined;
  const sliceAxis = axis(slices.map(([, v]) => v));
  const worstSlice = slices.length ? slices.reduce((a, b) => (b[1] < a[1] ? b : a)) : undefined;

  const tiles: Tile[] = [];
  if (e.thin_file_auc != null) {
    tiles.push({ key: "thin", label: "Thin-file AUC", value: fmtAuc(e.thin_file_auc), sub: `${fmtDiff(e.thin_file_auc - auc)} against the overall AUC ${fmtAuc(auc)}` });
  }
  if (e.score_psi != null) {
    const warn = limits.psiWarn;
    const alert = limits.maxScorePsi ?? limits.psiAlert;
    const band = alert != null && e.score_psi >= alert ? "large shift" : warn != null && e.score_psi >= warn ? "moderate shift" : warn != null ? "stable" : null;
    tiles.push({
      key: "psi",
      label: "Score PSI, training to validation",
      value: fmtAuc(e.score_psi, 4),
      sub: `${band ? `${band}; ` : ""}${alert != null ? `limit ${fmtAuc(alert, 2)}` : "population stability index of the score"}`,
      tone: band === "large shift" ? "crit" : band === "moderate shift" ? "warn" : null,
    });
  }

  return (
    <div className="evaluation-panel">
      {tiles.length > 0 && <Tiles tiles={tiles} />}

      <Section
        title="AUC by time slice"
        note="Validation loans split into consecutive periods by origination month. A model that only works in some periods is unstable, which is why the weakest slice must not fall far below the overall AUC."
      >
        {slices.length === 0 ? (
          <EmptyState title="No time slices recorded" />
        ) : (
          <Card kind="measured">
            <HBars
              title="AUC by origination-month slice"
              rows={slices.map(([k, v]) => ({
                key: k,
                label: slice(k),
                value: v,
                display: <span className="num">{fmtAuc(v)}</span>,
                note: `${fmtDiff(v - auc)} against overall${floorSlice != null && v < floorSlice ? "; below the lowest allowed" : ""}`,
                tone: floorSlice != null && v < floorSlice ? "crit" : "accent",
              }))}
              format={(v) => fmtAuc(v, 3)}
              min={sliceAxis.min}
              max={sliceAxis.max}
              markers={[{ value: auc, label: "Overall AUC" }, ...(floorSlice != null ? [{ value: floorSlice, label: "Lowest allowed slice" }] : [])]}
              footnote={`The axis starts at ${fmtAuc(sliceAxis.min, 2)}, where ranking is no better than chance.${worstSlice ? ` Weakest slice: ${slice(worstSlice[0])} at ${fmtAuc(worstSlice[1])}.` : ""}`}
            />
          </Card>
        )}
      </Section>

      <Section
        title="AUC by segment"
        note="Validation loans grouped by channel, product, thin-file status and employment type. Segments too small to measure are left out, and sizes are not reported, so AUCs on smaller segments are noisy."
      >
        {groups.size === 0 ? (
          <EmptyState title="No segments recorded" />
        ) : (
          <div className="evaluation-class-grid">
            {[...groups.entries()].map(([variable, items]) => {
              const rows: HBarRow[] = items.map(([value, v]) => {
                const below = limits.minSegmentAuc != null && v < limits.minSegmentAuc;
                return {
                  key: value,
                  label: segmentLabel(variable, value),
                  value: v,
                  display: <span className="num">{fmtAuc(v)}</span>,
                  note: `${fmtDiff(v - auc)} against overall${below ? "; below the floor" : ""}`,
                  tone: below ? "crit" : "accent",
                };
              });
              const ax = axis(items.map(([, v]) => v));
              return (
                <Card key={variable} title={titleCase(variable)} kind="measured">
                  <HBars
                    title={`AUC by ${titleCase(variable).toLowerCase()}`}
                    rows={rows}
                    format={(v) => fmtAuc(v, 3)}
                    min={ax.min}
                    max={ax.max}
                    markers={[{ value: auc, label: "Overall AUC" }, ...(limits.minSegmentAuc != null ? [{ value: limits.minSegmentAuc, label: "Segment floor" }] : [])]}
                  />
                </Card>
              );
            })}
          </div>
        )}
      </Section>
    </div>
  );
}
