/** The holdout gate result, or why there is none yet, together with the holdout budget it draws on. */
import type { EvidencePacket } from "../../api/types";
import { fmtAuc, fmtDateTime, fmtDiff } from "../../lib/format";
import { Link } from "react-router-dom";
import { Card, KeyValue, Meter, Pill, Section, TimeAgo } from "../ui";
import { CheckList, checkCounts } from "./CheckList";

export interface HoldoutBudget {
  used: number;
  budget: number;
}

export function GateSection({ p, holdout }: { p: EvidencePacket; holdout: HoldoutBudget | null }) {
  const gate = p.gate;
  const remaining = holdout ? Math.max(holdout.budget - holdout.used, 0) : null;
  const counts = gate ? checkCounts(gate.checks) : null;
  return (
    <Section
      title="Holdout gate"
      note="The holdout is out-of-time data that no agent and no validation step can read. Only the promotion gate reads it, and only a limited number of times for each definition of default."
      right={gate ? <Pill tone={gate.passed ? "good" : "crit"}>{gate.passed ? "Gate passed" : "Gate failed"}</Pill> : <Pill>Gate not run</Pill>}
    >
      {gate ? (
        <Card kind="measured">
          <KeyValue
            items={[
              ["Holdout AUC", <span key="a" className="num">{fmtAuc(gate.holdout_auc, 4)}</span>],
              ["Reference on the holdout", <span key="r" className="num">{fmtAuc(gate.reference_holdout_auc, 4)}</span>],
              ["Difference", <span key="d" className="num">{fmtDiff(gate.holdout_auc - gate.reference_holdout_auc, 4)}</span>],
              ["Checks passed", counts ? `${counts.passed} of ${counts.total}` : "—"],
              [
                "Run",
                <span key="t">
                  <TimeAgo iso={gate.ts} /> <span className="xs muted">({fmtDateTime(gate.ts)})</span>
                </span>,
              ],
              ["Gate id", <span key="g" className="mono">{gate.gate_id}</span>],
            ]}
          />
          {counts && counts.total > 0 && (
            <div style={{ marginTop: 10 }}>
              <CheckList checks={gate.checks} />
            </div>
          )}
          {holdout && (
            <div style={{ marginTop: 12 }}>
              <Meter used={holdout.used} cap={holdout.budget} label="Holdout reads used under this definition" />
            </div>
          )}
        </Card>
      ) : (
        <Card>
          <div className="stack">
            <div className="small">
              The gate has not been run for this candidate. It is step 1 of the decision. Until it passes, nothing can be approved or promoted.
            </div>
            {holdout ? (
              <>
                <Meter used={holdout.used} cap={holdout.budget} label="Holdout reads used under this definition" />
                <div className="xs muted">
                  {remaining === 0
                    ? "The holdout budget for this definition is used up: no further gate can run."
                    : `Running the gate uses one read, leaving ${Math.max((remaining ?? 1) - 1, 0)} of ${holdout.budget}.`}{" "}
                  Every gate run for this definition is listed on <Link to="/performance">Performance</Link>.
                </div>
              </>
            ) : (
              <div className="xs muted">The holdout budget could not be loaded.</div>
            )}
          </div>
        </Card>
      )}
    </Section>
  );
}
