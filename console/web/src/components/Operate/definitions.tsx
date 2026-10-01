/**
 * Definition of default lookups for the Decide and operate screens.
 *
 * Rows that carry only a `definition_version` (alerts, shadow runs, approvals, maturation) still need to show what the
 * definition means ("60 DPD ever / 12 months"), so this builds a DefinitionRef for any known version from the
 * definitions list, using the same summary wording as the API.
 */
import { useMemo } from "react";
import { useDefinitions } from "../../api/hooks";
import type { DefinitionRef, DefinitionVersion } from "../../api/types";
import { DefinitionBadge } from "../ui";

function toRef(v: DefinitionVersion): DefinitionRef {
  const f = v.fields as Record<string, unknown>;
  const dpd = Number(f.delinquency_threshold_dpd ?? 0);
  const timing = f.delinquency_timing === "end_of_window" ? "end_of_window" : "ever";
  const window = Number(f.observation_window_months ?? 0);
  return {
    version: v.version,
    short: v.short,
    name: v.name,
    summary: `${dpd} DPD ${timing === "ever" ? "ever" : "at end of window"} / ${window} months`,
    dpd,
    timing,
    window_months: window,
  };
}

/** Returns a function from a definition version (full hash) to its DefinitionRef, or undefined while unknown. */
export function useDefinitionRefs(): (version: string | null | undefined) => DefinitionRef | undefined {
  const q = useDefinitions();
  return useMemo(() => {
    const map = new Map<string, DefinitionRef>();
    for (const v of q.data ?? []) map.set(v.version, toRef(v));
    return (version) => (version ? map.get(version) : undefined);
  }, [q.data]);
}

/** A DefinitionBadge that fills in the plain-language summary when the definition is known. */
export function DefBadge({ version }: { version: string | null | undefined }) {
  const find = useDefinitionRefs();
  if (!version) return <span className="faint">—</span>;
  return <DefinitionBadge def={find(version)} version={version} />;
}
