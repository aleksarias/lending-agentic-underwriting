/** approve / refer / decline as a toned pill (shared by the decisions list and a decision's page). */
import type { DecisionRow } from "../../api/types";
import { Pill } from "../ui";

const OUTCOME_TONE = { approve: "good", refer: "warn", decline: "crit" } as const;

export function OutcomePill({ outcome }: { outcome: DecisionRow["decision"] | null | undefined }) {
  if (!outcome) return <span className="muted">—</span>;
  return <Pill tone={OUTCOME_TONE[outcome]}>{outcome}</Pill>;
}
