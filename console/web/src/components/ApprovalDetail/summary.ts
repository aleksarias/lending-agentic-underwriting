/** The one-sentence answer at the top of the evidence packet, computed from the packet, the benchmark position and the flow. */
import type { EvidencePacket } from "../../api/types";
import type { Position } from "./BenchmarkSection";
import { checkCounts } from "./CheckList";
import type { Flow, StepKey, StepView } from "./derive";

export function packetSummary(p: EvidencePacket, pos: Position, flow: Flow, steps: Record<StepKey, StepView>, actionsEnabled: boolean): string {
  const label = p.model.label;
  const { passed, total } = checkCounts(p.checks);
  const ev = p.evaluation;
  const checks = total ? ` (${passed} of ${total} harness checks)` : "";
  const validation = !ev ? "has no validation result" : ev.passed_validation ? `passed validation${checks}` : `did not pass validation${checks}`;
  const best = pos.best ? ` (${pos.best.label})` : "";
  const bench =
    pos.beats === true
      ? pos.isBest
        ? "is the best known model"
        : `beats the best known model${best}`
      : pos.beats === false
        ? `does not beat the best known model${best}`
        : "has not been compared with the best known model";
  const gate = p.gate ? (p.gate.passed ? "passed the holdout gate" : "failed the holdout gate") : "has not been through the holdout gate";

  let next = "";
  if (flow.promotion) next = `it was promoted as production v${flow.promotion.production_model_version}`;
  else if (flow.candidateBlockers.length) next = flow.candidateBlockers.length === 1 ? "a blocker stands in the way of promotion" : `${flow.candidateBlockers.length} blockers stand in the way of promotion`;
  else if (flow.decision?.decision === "reject") next = "it was rejected";
  else if (steps.gate.status === "ready") next = "the next step is to run the holdout gate";
  else if (steps.decision.status === "ready") next = "the next step is a human decision";
  else if (steps.promote.status === "ready") next = "the next step is promotion";
  if (next.startsWith("the next step") && !actionsEnabled) next += ", but actions are disabled on this console";
  return `${label} ${validation}, ${bench}, and ${gate}${next ? `; ${next}` : ""}.`;
}
