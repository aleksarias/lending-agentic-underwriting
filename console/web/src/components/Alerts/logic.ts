/**
 * Alert wording and classification.
 *
 * The API marks an alert as open when the newest monitoring run raised it and nobody acknowledged it (the status bar
 * counts the same way), but it does not send that flag, so it is recomputed here from the run times.
 */
import type { AlertItem, AlertsData } from "../../api/types";
import { fmtAuc, fmtPct } from "../../lib/format";
import type { Thresholds } from "../Operate/thresholds";

export const SEVERITY_LABEL: Record<AlertItem["severity"], string> = { high: "High", medium: "Medium", low: "Low" };
const SEVERITY_RANK: Record<AlertItem["severity"], number> = { high: 0, medium: 1, low: 2 };

export const subjectLabel = (subject: string): string => (subject === "score" ? "model score" : subject.replace(/_/g, " "));

export function alertTitle(a: AlertItem): string {
  if (a.kind === "psi") return a.subject === "score" ? "Score distribution shifted" : `Distribution of ${subjectLabel(a.subject)} shifted`;
  if (a.kind === "default_rate") {
    return a.value >= 0 ? `Observed default rate is ${fmtPct(a.value, 0)} above expected` : `Observed default rate is ${fmtPct(-a.value, 0)} below expected`;
  }
  if (a.kind === "production_default_rate") {
    const gap = fmtPct(Math.abs(a.value), 0);
    return a.value >= 0 ? `Matured production loans default ${gap} more than predicted` : `Matured production loans default ${gap} less than predicted`;
  }
  if (a.kind === "feed_held") return `Feed file held for review: ${a.subject}`;
  const kind = a.kind.replace(/_/g, " ");
  return `${kind.charAt(0).toUpperCase()}${kind.slice(1)}: ${subjectLabel(a.subject)}`;
}

/** A few words for the page summary: "bureau score PSI 0.313", "observed default rate +31% against expected". */
export function alertBrief(a: AlertItem): string {
  if (a.kind === "psi") return `${subjectLabel(a.subject)} PSI ${fmtAuc(a.value, 3)}`;
  if (a.kind === "default_rate") return `observed default rate ${a.value >= 0 ? "+" : "−"}${fmtPct(Math.abs(a.value), 0)} against expected`;
  return alertTitle(a).toLowerCase();
}

/** The measured value, and the limit it is judged against when settings are available. */
export function alertMeasure(a: AlertItem, th: Thresholds): { value: string; limit: string | null } {
  if (a.kind === "psi") {
    const limit =
      th.psiAlert != null
        ? `the alert threshold of ${fmtAuc(th.psiAlert, 2)}${th.psiWarn != null ? ` (a warning starts at ${fmtAuc(th.psiWarn, 2)})` : ""}`
        : null;
    return { value: `PSI ${fmtAuc(a.value, 3)}`, limit };
  }
  if (a.kind === "default_rate") {
    return {
      value: `${a.value >= 0 ? "+" : "−"}${fmtPct(Math.abs(a.value), 0)} against the expected rate`,
      limit: th.defaultRateTol != null ? `a tolerance of ±${fmtPct(th.defaultRateTol, 0)}` : null,
    };
  }
  if (a.kind === "production_default_rate") {
    return {
      value: `${a.value >= 0 ? "+" : "−"}${fmtPct(Math.abs(a.value), 0)} against the PD the loans were approved at`,
      limit: th.defaultRateTol != null ? `a tolerance of ±${fmtPct(th.defaultRateTol, 0)}` : null,
    };
  }
  if (a.kind === "feed_held") {
    return { value: `${fmtPct(a.value, 1)} of its records failed the checks`, limit: "the feed's quarantine limit" };
  }
  return { value: fmtAuc(a.value, 3), limit: null };
}

/** PSI against the configured thresholds, as words, so that status never rests on color. */
export function psiState(value: number | null, th: Thresholds): "alert" | "warning" | "stable" | null {
  if (value == null || th.psiAlert == null) return null;
  if (value >= th.psiAlert) return "alert";
  if (th.psiWarn != null && value >= th.psiWarn) return "warning";
  return "stable";
}

export function classify(data: AlertsData) {
  // the API decides what is current: raised by the latest run of whatever raises that kind of alert
  const isCurrent = (a: AlertItem) => a.current;
  const open = data.alerts
    .filter((a) => isCurrent(a) && !a.acknowledged)
    .sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] || b.value - a.value);
  const history = data.alerts.filter((a) => !(isCurrent(a) && !a.acknowledged));
  return { open, history, isCurrent };
}
