/**
 * Plain-language names for the harness checks (validation) and the gate checks (holdout). The wording follows what
 * lau.harness.evaluate and lau.harness.gate actually test. Unknown keys fall back to a sentence-case version of the key.
 */
import { checkLabel } from "../../lib/format";

const INFO: Record<string, { label: string; detail: string }> = {
  improves_on_reference: {
    label: "Improves on the reference model",
    detail: "Validation AUC is above the reference model's by at least the required margin, which grows with every test run.",
  },
  calibration: { label: "Calibration", detail: "Predicted and observed default rates agree within the limit." },
  time_stability: { label: "Stable across time slices", detail: "No time slice scores much worse than the whole validation window." },
  segment_floor: { label: "Every segment ranks well", detail: "AUC stays above the floor in every segment, including thin-file applicants." },
  score_psi: { label: "Stable score distribution", detail: "The score distribution in validation is close to training (PSI within the limit)." },
  no_leakage: { label: "No leakage", detail: "No feature is rated a high leakage risk: none looks like the outcome or uses information from after the decision." },
  no_prohibited_features: { label: "No prohibited features", detail: "The model uses none of the features the register prohibits." },
  no_proxy_features: { label: "No proxy features", detail: "No feature predicts a protected class strongly enough to be flagged as a proxy." },
  adverse_impact: { label: "Adverse impact ratio", detail: "The minimum adverse impact ratio across protected groups is above the limit." },
  reason_codes: { label: "Reason codes", detail: "Principal reasons can be given for declines, and none rest on a flagged feature." },
  beats_best_known: { label: "Beats the best known model", detail: "Scores at least as well as the best model in the benchmark ledger on the same validation loans." },
  validation_checks: { label: "Validation checks repeated", detail: "The validation checks above still pass when the gate re-runs them (this does not count as a new test)." },
  holdout_auc_vs_reference: { label: "Holdout AUC at least the reference's", detail: "On the holdout, AUC is not below the reference model's (the champion, else the baseline)." },
  holdout_calibration: { label: "Holdout calibration", detail: "Calibration error on the holdout is within the limit, with a little extra room." },
  holdout_adverse_impact: { label: "Holdout adverse impact ratio", detail: "The minimum adverse impact ratio in the holdout window is above the limit." },
};

export const checkName = (key: string): string => INFO[key]?.label ?? checkLabel(key);
export const checkDetail = (key: string): string | null => INFO[key]?.detail ?? null;
