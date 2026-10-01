/**
 * Harness limits read from the settings payload (config/thresholds.yaml), so the screens state the rule next to the
 * measurement without hard-coding numbers. Every field is optional: when settings cannot be read, the screens simply
 * omit the limit.
 */
import type { SettingsData } from "../../api/types";

export interface Limits {
  baseMargin?: number;
  mtPenaltyK?: number;
  maxEce?: number;
  maxSliceAucDrop?: number;
  maxScorePsi?: number;
  minSegmentAuc?: number;
  minAir?: number;
  proxyAucFlag?: number;
  approvalRate?: number;
  psiWarn?: number;
  psiAlert?: number;
  reasonTopN?: number;
  singleFeatureAucMax?: number;
}

function pick(root: unknown, ...path: string[]): number | undefined {
  let cur: unknown = root;
  for (const k of path) {
    if (typeof cur !== "object" || cur === null) return undefined;
    cur = (cur as Record<string, unknown>)[k];
  }
  return typeof cur === "number" && Number.isFinite(cur) ? cur : undefined;
}

export function limitsFrom(settings: SettingsData | undefined): Limits {
  const t = settings?.thresholds;
  return {
    baseMargin: pick(t, "gate", "base_auc_margin"),
    mtPenaltyK: pick(t, "gate", "mt_penalty_k"),
    maxEce: pick(t, "gate", "max_ece"),
    maxSliceAucDrop: pick(t, "gate", "max_slice_auc_drop"),
    maxScorePsi: pick(t, "gate", "max_score_psi"),
    minSegmentAuc: pick(t, "gate", "min_segment_auc"),
    minAir: pick(t, "fairness", "min_air"),
    proxyAucFlag: pick(t, "fairness", "proxy_auc_flag"),
    approvalRate: pick(t, "fairness", "approval_rate"),
    psiWarn: pick(t, "monitoring", "psi_warn"),
    psiAlert: pick(t, "monitoring", "psi_alert"),
    reasonTopN: pick(t, "reason_codes", "top_n"),
    singleFeatureAucMax: pick(t, "leakage", "single_feature_auc_max"),
  };
}
