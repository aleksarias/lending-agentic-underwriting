/**
 * Plain-language rule and measured value for each harness check, so a reader sees what was tested, what was
 * measured and what the limit is. Limits come from settings when they can be read; otherwise they are omitted.
 */
import type { EvaluationDetail } from "../../api/types";
import { fmtAuc, fmtPct } from "../../lib/format";
import type { Limits } from "../Performance/thresholds";

export const CHECK_RULE: Record<string, string> = {
  improves_on_reference: "Validation AUC beats the reference by at least the required margin.",
  calibration: "Predicted default rates match observed ones: expected calibration error is within the limit.",
  time_stability: "The weakest time slice is not far below the overall AUC.",
  segment_floor: "Every segment that is large enough to measure (for example channel, product, thin file or employment type) keeps an AUC above the floor.",
  score_psi: "The score distribution in validation has not moved away from training by more than the limit.",
  no_leakage: "No model feature has high leakage risk (information that is only known after the decision).",
  no_prohibited_features: "No feature from the prohibited register is used as a model input.",
  no_proxy_features: "No model feature is flagged as a proxy for a protected class.",
  adverse_impact: "The lowest adverse impact ratio across protected groups is at or above the threshold.",
  reason_codes: "Declined applications get reason codes, and no reason cites a flagged or prohibited feature.",
  beats_best_known: "The candidate beats the best model already built, re-scored on the same loans.",
};

const lim = (v: number | undefined, digits = 2) => (v == null ? "" : fmtAuc(v, digits));

/** "thin_file=True" -> "thin file: yes", "employment_type=retired" -> "employment type: retired" */
export function segmentName(key: string): string {
  const [variable, ...rest] = key.split("=");
  const value = rest.join("=");
  const v = value === "True" ? "yes" : value === "False" ? "no" : value;
  return `${variable.replace(/_/g, " ")}: ${v}`;
}

/** What was measured for a check, as one short sentence fragment; undefined when nothing useful can be said. */
export function measuredFor(key: string, e: EvaluationDetail, limits: Limits): string | undefined {
  const auc = e.val_auc;
  switch (key) {
    case "improves_on_reference": {
      const ref = e.reference.auc;
      if (ref == null) return "No reference: this evaluation sets the reference for later candidates";
      const gain = auc - ref;
      return `AUC ${fmtAuc(auc)} is ${fmtAuc(Math.abs(gain))} ${gain >= 0 ? "above" : "below"} the reference ${fmtAuc(ref)}; the required margin is ${fmtAuc(e.required_margin)}`;
    }
    case "calibration": {
      const ece = e.validation.ece;
      return ece == null ? undefined : `Expected calibration error ${fmtAuc(ece)}${limits.maxEce != null ? `, limit ${lim(limits.maxEce)}` : ""}`;
    }
    case "time_stability": {
      const slices = Object.entries(e.time_slices);
      if (!slices.length) return undefined;
      const [name, worst] = slices.reduce((a, b) => (b[1] < a[1] ? b : a));
      return `Weakest slice ${name.replace("..", " to ")} at ${fmtAuc(worst)}, ${fmtAuc(auc - worst)} below overall${limits.maxSliceAucDrop != null ? ` (limit ${lim(limits.maxSliceAucDrop)})` : ""}`;
    }
    case "segment_floor": {
      const segs = Object.entries(e.segments);
      if (!segs.length) return undefined;
      const [name, worst] = segs.reduce((a, b) => (b[1] < a[1] ? b : a));
      return `Lowest segment ${segmentName(name)} at ${fmtAuc(worst)}${limits.minSegmentAuc != null ? `, floor ${lim(limits.minSegmentAuc)}` : ""}`;
    }
    case "score_psi":
      return e.score_psi == null ? undefined : `Score PSI ${fmtAuc(e.score_psi, 4)}${limits.maxScorePsi != null ? `, limit ${lim(limits.maxScorePsi)}` : ""}`;
    case "no_leakage": {
      const high = e.leakage.filter((l) => l.risk === "high").length;
      return `${high} of ${e.leakage.length} model features with high leakage risk`;
    }
    case "no_prohibited_features":
      return undefined;
    case "no_proxy_features":
      return e.proxies_flagged.length ? `Flagged: ${e.proxies_flagged.join(", ")}` : `No model feature flagged${limits.proxyAucFlag != null ? ` (flag at proxy AUC ${lim(limits.proxyAucFlag)})` : ""}`;
    case "adverse_impact": {
      const m = e.fairness.min_air;
      return m == null ? undefined : `Lowest ratio ${fmtAuc(m, 3)}${limits.minAir != null ? `, threshold ${lim(limits.minAir)}` : ""}`;
    }
    case "reason_codes": {
      const q = e.reason_codes.quality as Record<string, unknown>;
      const any = typeof q.coverage_any === "number" ? q.coverage_any : null;
      const flagged = typeof q.flagged_feature_share === "number" ? q.flagged_feature_share : null;
      if (any == null && flagged == null) return undefined;
      return [any != null ? `${fmtPct(any, 1)} of declines have a reason` : null, flagged != null ? `${fmtPct(flagged, 1)} cite a flagged feature` : null].filter(Boolean).join("; ");
    }
    default:
      return undefined;
  }
}
