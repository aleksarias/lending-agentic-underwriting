/** Formatting helpers. Use these everywhere so numbers read the same across screens. */
import type { Tone, VerdictCode } from "../api/types";

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

export const fmtNum = (v: number | null | undefined, digits = 0) =>
  isNum(v) ? v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }) : "—";

/** 0.1234 -> "12.3%" */
export const fmtPct = (v: number | null | undefined, digits = 1) => (isNum(v) ? `${(v * 100).toFixed(digits)}%` : "—");

/** Percentage-point difference: 0.0329 -> "+3.29 pp" */
export const fmtPp = (v: number | null | undefined, digits = 2) =>
  isNum(v) ? `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(digits)} pp` : "—";

/** AUC-like metric with fixed decimals */
export const fmtAuc = (v: number | null | undefined, digits = 4) => (isNum(v) ? v.toFixed(digits) : "—");

/** Signed difference: 0.0059 -> "+0.0059" */
export const fmtDiff = (v: number | null | undefined, digits = 4) =>
  isNum(v) ? `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(digits)}` : "—";

export const fmtUsd = (v: number | null | undefined, digits = 2) =>
  isNum(v) ? `$${v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}` : "—";

export const fmtSeconds = (v: number | null | undefined) => {
  if (!isNum(v)) return "—";
  if (v < 60) return `${v.toFixed(1)} s`;
  const m = Math.floor(v / 60);
  return `${m} min ${Math.round(v % 60)} s`;
};

/** "Sep 30, 2026, 05:45 PM UTC"; pass { seconds: true } where instants closer than a minute matter. */
export const fmtDateTime = (iso: string | null | undefined, opts: { seconds?: boolean } = {}) => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    ...(opts.seconds ? { second: "2-digit" } : {}),
    timeZone: "UTC",
    timeZoneName: "short",
  });
};

export const fmtDate = (iso: string | null | undefined) => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
};

export const fmtAgo = (iso: string | null | undefined, now = Date.now()) => {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const s = Math.round((now - t) / 1000);
  if (s < 60) return `${Math.max(s, 0)} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
};

export const shortVersion = (v: string | null | undefined) => (v ? v.slice(0, 8) : "—");

export const titleCase = (s: string) => s.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

/** Plain-language label for a snake_case check key, e.g. "no_proxy_features" -> "No proxy features" */
export const checkLabel = (s: string) => {
  const t = s.replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
};

export const verdictTone = (code: VerdictCode | null | undefined): Tone => {
  switch (code) {
    case "improved":
      return "good";
    case "not_best":
      return "warn";
    case "regressed":
      return "crit";
    default:
      return "neutral";
  }
};

export const verdictLabel = (code: VerdictCode | null | undefined) => {
  switch (code) {
    case "improved":
      return "Improved";
    case "no_change":
      return "No detectable change";
    case "not_best":
      return "Not the best available";
    case "regressed":
      return "Regressed";
    case "insufficient_evidence":
      return "Not enough evidence yet";
    default:
      return "No verdict yet";
  }
};

/** Tone for a pass/fail-ish string verdict from agents (pass / concern / fail / block) */
export const reviewTone = (v: string | null | undefined): Tone =>
  v === "pass" ? "good" : v === "concern" ? "warn" : v === "fail" || v === "block" ? "crit" : "neutral";

/** Candidate ref like "candidate:11" -> "v11"; "baseline:10" -> "baseline v10" */
export const refLabel = (ref: string | null | undefined) => {
  if (!ref) return "—";
  const [kind, id] = ref.split(":");
  if (!id) return ref;
  return kind === "candidate" ? `v${id}` : `${kind} v${id}`;
};

/** An estimate with its interval: "+0.103, 95% CI +0.077 to +0.129" (the convention for any uncertain number). */
export const fmtInterval = (i: { estimate: number; lo: number; hi: number } | null | undefined, digits = 3, level = 95) =>
  i ? `${fmtDiff(i.estimate, digits)}, ${level}% CI ${fmtDiff(i.lo, digits)} to ${fmtDiff(i.hi, digits)}` : "—";

/** Tone of a difference interval: entirely above zero good, entirely below crit, straddling zero warn (noise). */
export const intervalTone = (i: { lo: number; hi: number } | null | undefined): Tone =>
  !i ? "neutral" : i.lo > 0 ? "good" : i.hi < 0 ? "crit" : "warn";
