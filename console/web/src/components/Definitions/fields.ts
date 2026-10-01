/**
 * Plain-language names and values for the fields of a definition of default (the DefaultDefinition schema).
 * Shared by the Definitions screen (field changes) and the Definition detail screen (every field).
 */
import { checkLabel, fmtUsd } from "../../lib/format";

const FIELD_LABELS: Record<string, string> = {
  delinquency_threshold_dpd: "Delinquency threshold",
  delinquency_timing: "Delinquency timing",
  observation_window_months: "Observation window",
  min_seasoning_months: "Minimum seasoning",
  maturity_rule: "Loans without the full window",
  include_charge_off: "Charge-off counts as default",
  include_bankruptcy: "Bankruptcy counts as default",
  include_settlement: "Settlement counts as default",
  include_forbearance_as_default: "Forbearance counts as default",
  cure_handling: "Cure handling",
  exclusions: "Excluded loans",
  early_payoff_within_months: "Early payoff window",
  balance_materiality_threshold: "Past-due materiality threshold",
  custom_sql_predicate: "Custom SQL rule",
};

/** One sentence on what each field does, for the detail screen. */
export const FIELD_HELP: Record<string, string> = {
  delinquency_threshold_dpd: "Days past due at which a loan counts as delinquent.",
  delinquency_timing: "Whether the threshold must be reached at any point in the window, or only at its end.",
  observation_window_months: "Months on book over which a loan is watched for default.",
  min_seasoning_months: "Loans with fewer months on book than this are left out of the labels.",
  maturity_rule: "What happens to loans that have not been observed for the whole window.",
  include_charge_off: "Whether a charge-off is a default.",
  include_bankruptcy: "Whether a bankruptcy is a default.",
  include_settlement: "Whether a settlement for less than the balance is a default.",
  include_forbearance_as_default: "Whether a loan placed in forbearance is a default.",
  cure_handling: "Whether a loan that catches up after a delinquency still counts.",
  exclusions: "Loans removed from the labelled data for these reasons.",
  early_payoff_within_months: "A payoff within this many months counts as an early payoff.",
  balance_materiality_threshold: "Past-due amounts below this are ignored.",
  custom_sql_predicate: "An extra rule that also counts a loan as default.",
};

const EXCLUSION_LABELS: Record<string, string> = {
  fraud_confirmed: "confirmed fraud",
  early_payoff: "early payoff",
  deceased: "death of the borrower",
};

export const fieldLabel = (field: string): string => FIELD_LABELS[field] ?? checkLabel(field);

const plural = (n: number, unit: string) => `${n} ${unit}${n === 1 ? "" : "s"}`;

function generic(v: unknown): string {
  if (v === null || v === undefined) return "not set";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "number") return String(v);
  if (typeof v === "string") return v === "" ? "empty" : v.replace(/_/g, " ");
  if (Array.isArray(v)) return v.length ? v.map(generic).join(", ") : "none";
  if (typeof v === "object") {
    const parts = Object.entries(v as Record<string, unknown>).map(([k, x]) => `${k.replace(/_/g, " ")}: ${generic(x)}`);
    return parts.length ? parts.join("; ") : "none";
  }
  return String(v);
}

function cure(v: unknown): string {
  if (!v || typeof v !== "object") return generic(v);
  const { mode, cure_months_required: months } = v as { mode?: unknown; cure_months_required?: unknown };
  const period = typeof months === "number" ? ` (cure period ${plural(months, "month")})` : "";
  if (mode === "count_if_ever") return `counts as default even if the loan later cures${period}`;
  if (mode === "cured_not_default") return `treated as cured, not default, after ${typeof months === "number" ? `${plural(months, "month")} current` : "the cure period"}`;
  return generic(v);
}

/** The value of one definition field in plain language ("60 days past due", "yes", "3 months", "none"). */
export function fieldValue(field: string, v: unknown): string {
  switch (field) {
    case "delinquency_threshold_dpd":
      return typeof v === "number" ? `${v} days past due` : generic(v);
    case "delinquency_timing":
      return v === "ever" ? "ever in the window" : v === "end_of_window" ? "at the end of the window" : generic(v);
    case "observation_window_months":
    case "min_seasoning_months":
    case "early_payoff_within_months":
      return typeof v === "number" ? plural(v, "month") : generic(v);
    case "maturity_rule":
      return v === "exclude" ? "excluded" : v === "censor" ? "kept, marked not yet mature" : generic(v);
    case "cure_handling":
      return cure(v);
    case "exclusions":
      return Array.isArray(v) && v.length ? v.map((x) => EXCLUSION_LABELS[String(x)] ?? generic(x)).join(", ") : "none";
    case "balance_materiality_threshold":
      return typeof v === "number" ? (v === 0 ? "none (every past-due amount counts)" : fmtUsd(v)) : generic(v);
    case "custom_sql_predicate":
      return v == null || v === "" ? "none" : String(v);
    default:
      return generic(v);
  }
}

/** Plain-language names for the reasons a loan is left out of the labels, and for what triggered a default. */
const EXCLUSION_KEYS: Record<string, string> = {
  unseasoned: "Not yet seasoned",
  early_payoff: "Paid off early",
  fraud_confirmed: "Confirmed fraud",
  deceased: "Borrower deceased",
};
export const exclusionLabel = (key: string): string => EXCLUSION_KEYS[key] ?? checkLabel(key);

export function triggerLabel(key: string, dpd: number | null): string {
  switch (key) {
    case "delinquency":
      return dpd ? `Reached ${dpd} days past due` : "Reached the delinquency threshold";
    case "charge_off":
      return "Charge-off";
    case "bankruptcy":
      return "Bankruptcy";
    case "settlement":
      return "Settlement";
    case "forbearance":
      return "Forbearance";
    case "custom_predicate":
      return "Custom SQL rule";
    default:
      return checkLabel(key);
  }
}
