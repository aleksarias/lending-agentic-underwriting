/**
 * Where a candidate stands in the three steps (holdout gate, human decision, promotion), and why a button is disabled.
 *
 * The API gives can_run_gate / can_decide / can_promote and a flat list of blockers. It does not say which step a
 * blocker belongs to, and it has no field for "a decision was recorded". This derives both from the packet plus the
 * approval history and the promotions list, so every disabled button can state its own reason.
 *
 * Two separate questions are answered here:
 *  - status: where the candidate is in the workflow (independent of whether this console allows actions)
 *  - disabledReason: whether the button can be used now. It follows `actions_enabled` and the packet's can_* flag
 *    exactly; the text says why when it cannot.
 */
import type { ApprovalRecord, EvidencePacket, Promotion } from "../../api/types";
import { ACTIONS_DISABLED } from "../Operate/constants";

// The packet adds ACTIONS_DISABLED as a blocker itself when the console runs with actions off. It is not a problem
// with the candidate, so it is kept out of the candidate's own blockers.
export { ACTIONS_DISABLED };

export type StepKey = "gate" | "decision" | "promote";
export type StepStatus = "done" | "ready" | "waiting" | "blocked";

export interface Flow {
  /** blockers that concern the candidate (the actions-disabled note is left out) */
  candidateBlockers: string[];
  /** the recorded decision on the candidate's current gate result, if any */
  decision: ApprovalRecord | null;
  promotion: Promotion | null;
}

export interface StepView {
  key: StepKey;
  status: StepStatus;
  /** one sentence on why the step is not open yet, or null when it is done or ready */
  why: string | null;
  /** why the action button is disabled, or null when it can be used */
  disabledReason: string | null;
}

export function deriveFlow(p: EvidencePacket, history: ApprovalRecord[] | undefined, promotions: Promotion[] | undefined): Flow {
  const candidateBlockers = p.blockers.filter((b) => b !== ACTIONS_DISABLED);
  const records = (history ?? [])
    .filter((h) => h.kind === "promotion" && h.ref === p.candidate_ref)
    .sort((a, b) => (a.ts < b.ts ? 1 : -1));
  const decision = p.gate && records[0] && records[0].ts >= p.gate.ts ? records[0] : null;
  const promotion = (promotions ?? []).find((x) => x.candidate_model_version === p.model.version) ?? null;
  return { candidateBlockers, decision, promotion };
}

export function stepViews(p: EvidencePacket, flow: Flow, actionsEnabled: boolean): Record<StepKey, StepView> {
  const first = flow.candidateBlockers[0];
  const off = actionsEnabled ? null : ACTIONS_DISABLED;
  const reason = (can: boolean, why: string | null) => off ?? (can ? null : why ?? "Not possible yet.");

  // 1. holdout gate
  let gate: StepView;
  if (p.gate) {
    gate = { key: "gate", status: "done", why: null, disabledReason: reason(p.can_run_gate, "The holdout gate has already run for this candidate.") };
  } else if (flow.candidateBlockers.length) {
    gate = { key: "gate", status: "blocked", why: first, disabledReason: reason(p.can_run_gate, first) };
  } else {
    gate = { key: "gate", status: "ready", why: null, disabledReason: reason(p.can_run_gate, "The gate cannot run yet.") };
  }

  // 2. human decision
  let decision: StepView;
  if (flow.decision) {
    decision = { key: "decision", status: "done", why: null, disabledReason: reason(p.can_decide, "A decision is already recorded for this gate result.") };
  } else if (flow.promotion) {
    decision = { key: "decision", status: "blocked", why: "Already promoted.", disabledReason: reason(p.can_decide, "Already promoted.") };
  } else if (!p.gate) {
    decision = { key: "decision", status: "waiting", why: "Needs a passing holdout gate result first.", disabledReason: reason(p.can_decide, "Run the holdout gate first.") };
  } else if (!p.gate.passed) {
    const why = "It failed the holdout gate, so nothing can be approved.";
    decision = { key: "decision", status: "blocked", why, disabledReason: reason(p.can_decide, why) };
  } else {
    decision = { key: "decision", status: "ready", why: null, disabledReason: reason(p.can_decide, first ?? "A decision cannot be recorded yet.") };
  }

  // 3. promotion
  let promote: StepView;
  if (flow.promotion) {
    promote = { key: "promote", status: "done", why: null, disabledReason: reason(p.can_promote, "Already promoted.") };
  } else if (p.gate && !p.gate.passed) {
    const why = "It failed the holdout gate, so it cannot be promoted.";
    promote = { key: "promote", status: "blocked", why, disabledReason: reason(p.can_promote, why) };
  } else if (!flow.decision) {
    promote = {
      key: "promote",
      status: "waiting",
      why: "Needs an approval first.",
      disabledReason: reason(p.can_promote, p.gate ? "Approve the candidate first." : "Run the holdout gate and record an approval first."),
    };
  } else if (flow.decision.decision !== "approve") {
    const why = "It was rejected, so it cannot be promoted from this console.";
    promote = { key: "promote", status: "blocked", why, disabledReason: reason(p.can_promote, why) };
  } else {
    promote = { key: "promote", status: "ready", why: null, disabledReason: reason(p.can_promote, first ?? "Promotion is not possible yet.") };
  }

  return { gate, decision, promote };
}
