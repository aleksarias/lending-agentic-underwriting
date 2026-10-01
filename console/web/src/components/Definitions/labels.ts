/**
 * Definition helpers shared by the History, Cycle, Compare, Definitions and Definition detail screens.
 * Versions come from GET /definitions (DefinitionVersion); these helpers give them the same labels the rest of the
 * console uses for a DefinitionRef ("60 DPD ever / 12 months").
 */
import type { DefinitionRef, DefinitionVersion } from "../../api/types";

const asNumber = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** "60 DPD ever / 12 months": the wording of DefinitionRef.summary, rebuilt for versions that only carry raw fields. */
export function definitionLabel(d: Pick<DefinitionVersion, "fields" | "short">): string {
  const f = d.fields;
  const dpd = asNumber(f.delinquency_threshold_dpd);
  const months = asNumber(f.observation_window_months);
  // Fields from a schema this console does not know: fall back to the hash rather than print "undefined".
  if (dpd == null || months == null) return d.short;
  const timing = (f.delinquency_timing ?? "ever") === "ever" ? "ever" : "at end of window";
  return `${dpd} DPD ${timing} / ${months} months`;
}

/** A DefinitionRef for <DefinitionBadge/>, built from a listed version. */
export function definitionRefOf(d: DefinitionVersion): DefinitionRef {
  const f = d.fields;
  return {
    version: d.version,
    short: d.short,
    name: d.name,
    summary: definitionLabel(d),
    dpd: asNumber(f.delinquency_threshold_dpd) ?? 0,
    timing: (f.delinquency_timing ?? "ever") === "ever" ? "ever" : "end_of_window",
    window_months: asNumber(f.observation_window_months) ?? 0,
  };
}

const ms = (iso: string | null | undefined): number => (iso ? Date.parse(iso) : NaN);

/** Versions in the order they were activated, oldest first. Versions never activated come last, by creation time. */
export function inActivationOrder(defs: DefinitionVersion[]): DefinitionVersion[] {
  return [...defs].sort((a, b) => {
    const ta = ms(a.active_from);
    const tb = ms(b.active_from);
    if (Number.isNaN(ta) && Number.isNaN(tb)) return (ms(a.created_at) || 0) - (ms(b.created_at) || 0);
    if (Number.isNaN(ta)) return 1;
    if (Number.isNaN(tb)) return -1;
    return ta - tb;
  });
}

/** The version in force at an instant (epoch ms), from the activation periods the API reports; null before the first. */
export function definitionAt(defs: DefinitionVersion[], at: number): DefinitionVersion | null {
  let hit: DefinitionVersion | null = null;
  let hitFrom = -Infinity;
  for (const d of defs) {
    const from = ms(d.active_from);
    if (Number.isNaN(from)) continue;
    const to = d.active_to ? ms(d.active_to) : Infinity;
    if (at >= from && at < to && from > hitFrom) {
      hit = d;
      hitFrom = from;
    }
  }
  return hit;
}

/** The definition activated just before `version`, and the one activated just after it (either may be null). */
export function neighbours(defs: DefinitionVersion[], version: string): { previous: DefinitionVersion | null; next: DefinitionVersion | null } {
  const order = inActivationOrder(defs);
  const i = order.findIndex((d) => d.version === version);
  if (i < 0) return { previous: null, next: null };
  return { previous: order[i - 1] ?? null, next: order[i + 1] ?? null };
}
