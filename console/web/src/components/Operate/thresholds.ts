/**
 * Harness and monitoring thresholds, read defensively from the settings endpoint. They give the screens the limit a
 * number is judged against (PSI alert level, minimum adverse impact ratio, approval rate). Every value may be null when
 * settings cannot be loaded; screens then show the measured number without a limit.
 */
import { useMemo } from "react";
import { useSettings } from "../../api/hooks";
import type { SettingsData } from "../../api/types";

export interface Thresholds {
  psiWarn: number | null;
  psiAlert: number | null;
  defaultRateTol: number | null;
  minAir: number | null;
  approvalRate: number | null;
}

const rec = (v: unknown): Record<string, unknown> => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {});
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

export function thresholdsFrom(s: SettingsData | undefined): Thresholds {
  const t = rec(s?.thresholds);
  const monitoring = rec(t.monitoring);
  const fairness = rec(t.fairness);
  return {
    psiWarn: num(monitoring.psi_warn),
    psiAlert: num(monitoring.psi_alert),
    defaultRateTol: num(monitoring.default_rate_rel_tol),
    minAir: num(fairness.min_air),
    approvalRate: num(fairness.approval_rate),
  };
}

export function useThresholds(): Thresholds {
  const q = useSettings();
  return useMemo(() => thresholdsFrom(q.data), [q.data]);
}
