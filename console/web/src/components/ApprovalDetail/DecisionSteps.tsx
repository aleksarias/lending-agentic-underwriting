/**
 * The decision: three steps in order (run the holdout gate, approve or reject with a rationale, promote).
 *
 * Every button is enabled only when the console allows actions AND the packet's matching can_* flag is true. Otherwise it
 * is disabled with the reason as a tooltip and as visible text. Each action opens a confirmation that states exactly
 * what changes, and the API's own message is shown once it completes.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError } from "../../api/client";
import { useDecide, usePromote, useRunGate } from "../../api/hooks";
import type { ActionResult, EvidencePacket, Promotion } from "../../api/types";
import { fmtAuc, fmtDateTime, fmtDiff } from "../../lib/format";
import { ActionButton, ActionDialog } from "../Operate/actions";
import { Banner, Card, Pill, TimeAgo } from "../ui";
import { ACTIONS_DISABLED, stepViews, type Flow, type StepKey, type StepView } from "./derive";
import type { HoldoutBudget } from "./GateSection";
import "./ApprovalDetail.css";

interface Props {
  packet: EvidencePacket;
  flow: Flow;
  actionsEnabled: boolean;
  user: string | null;
  holdout: HoldoutBudget | null;
  /** "57d48e7c (60 DPD ever / 12 months)" */
  definitionLabel: string;
  activeDefinition: string | null;
  apiLive: boolean;
  /** the newest promotion under this candidate's definition, i.e. the current champion that a promotion would replace */
  currentChampion: Promotion | null;
  historyUnavailable: boolean;
}

type Dialog = null | "gate" | "approve" | "reject" | "promote";
interface Outcome {
  title: string;
  tone: "good" | "warn" | "crit";
  message: string;
}

const errorText = (e: unknown) => (e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e));

function Step(props: { n: number; title: string; view: StepView; pill: ReactNode; children: ReactNode }) {
  return (
    <li className={`approvaldetail-step ${props.view.status}`}>
      <span className="num" aria-hidden>
        {props.n}
      </span>
      <div className="body">
        <div className="row between">
          <h3>
            <span className="sr-only">Step {props.n}: </span>
            {props.title}
          </h3>
          {props.pill}
        </div>
        {props.children}
      </div>
    </li>
  );
}

function pillFor(key: StepKey, view: StepView, p: EvidencePacket, flow: Flow): ReactNode {
  if (view.status === "done") {
    if (key === "gate") return p.gate?.passed ? <Pill tone="good">Passed</Pill> : <Pill tone="crit">Failed</Pill>;
    if (key === "decision") return flow.decision?.decision === "approve" ? <Pill tone="good">Approved</Pill> : <Pill tone="crit">Rejected</Pill>;
    return <Pill tone="good">Promoted</Pill>;
  }
  if (view.status === "ready") return <Pill tone="accent">Ready</Pill>;
  if (view.status === "blocked") return <Pill tone="warn">Blocked</Pill>;
  return <Pill>Waiting</Pill>;
}

/** Why the step is not open, plus the console-wide note when actions are off. */
function Reasons({ view }: { view: StepView }) {
  if (view.status === "done") return null;
  const lines = [view.why, view.disabledReason === ACTIONS_DISABLED ? ACTIONS_DISABLED : null].filter((x): x is string => !!x);
  if (!lines.length) return null;
  return (
    <div className="xs muted stack" style={{ gap: 2 }}>
      {lines.map((l) => (
        <span key={l}>{l}</span>
      ))}
    </div>
  );
}

export function DecisionSteps(props: Props) {
  const { packet, flow, actionsEnabled, user, holdout, definitionLabel, activeDefinition, apiLive, currentChampion, historyUnavailable } = props;
  const gate = useRunGate();
  const decide = useDecide();
  const promote = usePromote();
  const [dialog, setDialog] = useState<Dialog>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const outcomeRef = useRef<HTMLDivElement>(null);
  // the button that opened a dialog may disappear once its step is done, so the result takes focus (and is read out)
  useEffect(() => {
    if (outcome) outcomeRef.current?.focus();
  }, [outcome]);
  const steps = stepViews(packet, flow, actionsEnabled);
  const label = packet.model.label;
  const who = user ? ` in your name (${user})` : " in your name";

  const finish = (title: string) => ({
    onSuccess: (r: ActionResult) => {
      setOutcome({ title, tone: r.ok ? "good" : "warn", message: r.message });
      setDialog(null);
    },
    onError: (e: Error) => {
      setOutcome({ title, tone: "crit", message: `The action did not complete: ${errorText(e)}` });
      setDialog(null);
    },
  });

  const remainingAfter = holdout ? Math.max(holdout.budget - holdout.used - 1, 0) : null;
  const servesOnPromotion = packet.definition_version === activeDefinition;

  return (
    <Card title="Decision: three steps, in order">
      <div className="stack" style={{ gap: 12 }}>
        {outcome && (
          <div ref={outcomeRef} tabIndex={-1}>
            <Banner tone={outcome.tone} title={outcome.title}>
              {outcome.message}
            </Banner>
          </div>
        )}
        {!actionsEnabled && (
          <Banner tone="neutral" title="Actions are disabled on this console">
            You can review the evidence, but the three steps cannot be run from here.
          </Banner>
        )}
        {historyUnavailable && (
          <div className="xs muted">The decision history could not be loaded, so the state of steps 2 and 3 may be incomplete. The buttons still follow the API.</div>
        )}

        <ol className="approvaldetail-steps">
          <Step n={1} title="Run the holdout gate" view={steps.gate} pill={pillFor("gate", steps.gate, packet, flow)}>
            <p className="small muted" style={{ margin: 0 }}>
              Reads the out-of-time holdout once and checks the candidate against the reference model on loans it has never seen. Each run uses one of the limited
              holdout reads for this definition{holdout ? ` (${holdout.used} of ${holdout.budget} used)` : ""}. It does not change any model.
            </p>
            {packet.gate && (
              <p className="small" style={{ margin: 0 }}>
                Holdout AUC {fmtAuc(packet.gate.holdout_auc, 4)} against {fmtAuc(packet.gate.reference_holdout_auc, 4)} for the reference (
                {fmtDiff(packet.gate.holdout_auc - packet.gate.reference_holdout_auc, 4)}), run <TimeAgo iso={packet.gate.ts} />.
              </p>
            )}
            <Reasons view={steps.gate} />
            {steps.gate.status !== "done" && (
              <div className="row">
                <ActionButton variant="primary" disabledReason={steps.gate.disabledReason} onClick={() => setDialog("gate")}>
                  Run holdout gate
                </ActionButton>
              </div>
            )}
          </Step>

          <Step n={2} title="Approve or reject, with a rationale" view={steps.decision} pill={pillFor("decision", steps.decision, packet, flow)}>
            <p className="small muted" style={{ margin: 0 }}>
              A person reads the evidence and approves or rejects the candidate with a rationale of at least 10 characters. Approving records a decision; it does not
              promote anything.
            </p>
            {packet.approvals && (
              <p className="small" style={{ margin: 0 }}>
                Approvals on the latest gate result: <strong>{packet.approvals.approvers.length} of {packet.approvals.required}</strong>
                {packet.approvals.required > 1 ? " (two-person rule: different people must approve)" : ""}
                {packet.approvals.approvers.length > 0 ? `, by ${packet.approvals.approvers.join(", ")}` : ""}
                {packet.approvals.rejected_by.length > 0 ? `; rejected by ${packet.approvals.rejected_by.join(", ")}` : ""}.
              </p>
            )}
            {flow.decision && (
              <div className="stack" style={{ gap: 4 }}>
                <span className="small">
                  {flow.decision.decision === "approve" ? "Approved" : "Rejected"} by <strong>{flow.decision.approver || "an unnamed approver"}</strong>{" "}
                  <span title={fmtDateTime(flow.decision.ts)}>
                    <TimeAgo iso={flow.decision.ts} />
                  </span>
                </span>
                <blockquote className="approvaldetail-quote">{flow.decision.rationale}</blockquote>
              </div>
            )}
            <Reasons view={steps.decision} />
            {steps.decision.status !== "done" && (
              <div className="row">
                <ActionButton variant="primary" disabledReason={steps.decision.disabledReason} onClick={() => setDialog("approve")}>
                  Approve
                </ActionButton>
                <ActionButton variant="danger" disabledReason={steps.decision.disabledReason} onClick={() => setDialog("reject")}>
                  Reject
                </ActionButton>
              </div>
            )}
          </Step>

          <Step n={3} title="Promote" view={steps.promote} pill={pillFor("promote", steps.promote, packet, flow)}>
            <p className="small muted" style={{ margin: 0 }}>
              Copies the approved candidate into the production model registry as a new version and marks it champion for this definition.{" "}
              {servesOnPromotion
                ? "This is the active definition, so it also takes the serving alias."
                : "This is not the active definition, so it would become champion for that definition without serving."}
              {!apiLive && " The real-time decision API is not deployed, so the legacy policy score keeps deciding applications until it is."}
            </p>
            {flow.promotion && (
              <p className="small" style={{ margin: 0 }}>
                Promoted as production v{flow.promotion.production_model_version} <TimeAgo iso={flow.promotion.ts} />.{" "}
                {flow.promotion.serving ? "It holds the serving alias." : "It is champion for its definition but not serving."}
              </p>
            )}
            <Reasons view={steps.promote} />
            {steps.promote.status !== "done" && (
              <div className="row">
                <ActionButton variant="primary" disabledReason={steps.promote.disabledReason} onClick={() => setDialog("promote")}>
                  Promote
                </ActionButton>
              </div>
            )}
          </Step>
        </ol>

        <div className="approvaldetail-note xs muted">
          Approving here is a human decision. It is recorded with the approver's name{user ? ` (${user})` : ""} and the rationale, and stays in the approval history.
        </div>
      </div>

      {dialog === "gate" && (
        <ActionDialog
          open
          title={`Run the holdout gate for ${label}?`}
          confirmLabel="Run the gate"
          busy={gate.isPending}
          onCancel={() => setDialog(null)}
          onConfirm={() => gate.mutate({ candidate_ref: packet.candidate_ref }, finish("Holdout gate"))}
        >
          <p style={{ margin: "0 0 8px" }}>
            This reads the holdout once
            {remainingAfter != null && holdout ? ` (${remainingAfter} of ${holdout.budget} remaining after this)` : ""} and records the gate result. It does not change any model.
          </p>
          <p style={{ margin: 0 }}>
            The run counts against the holdout budget for definition {definitionLabel} whether the candidate passes or fails, and a candidate is gated once. It can take
            a while.
          </p>
        </ActionDialog>
      )}

      {(dialog === "approve" || dialog === "reject") && (
        <ActionDialog
          open
          danger={dialog === "reject"}
          title={dialog === "approve" ? `Approve ${label}?` : `Reject ${label}?`}
          confirmLabel={dialog === "approve" ? "Record approval" : "Record rejection"}
          requireText={{ label: "Rationale (at least 10 characters). It is recorded with your name.", minLength: 10 }}
          busy={decide.isPending}
          onCancel={() => setDialog(null)}
          onConfirm={(text) => decide.mutate({ candidate_ref: packet.candidate_ref, decision: dialog, rationale: text }, finish(dialog === "approve" ? "Approval" : "Rejection"))}
        >
          {dialog === "approve" ? (
            <p style={{ margin: 0 }}>
              This records your approval of {label} under definition {definitionLabel}
              {packet.gate ? `, against holdout gate ${packet.gate.gate_id}` : ""},{who}. It does not promote the model: promotion is a separate step.
            </p>
          ) : (
            <p style={{ margin: 0 }}>
              This records your rejection of {label}{who}. From this console a rejection is final for the candidate: it leaves the inbox and cannot be promoted, and a new
              candidate would be needed.
            </p>
          )}
        </ActionDialog>
      )}

      {dialog === "promote" && (
        <ActionDialog
          open
          title={`Promote ${label} to champion?`}
          confirmLabel="Promote"
          busy={promote.isPending}
          onCancel={() => setDialog(null)}
          onConfirm={() => promote.mutate({ candidate_ref: packet.candidate_ref }, finish("Promotion"))}
        >
          <p style={{ margin: "0 0 8px" }}>
            This copies {label} into the production model registry as a new version and marks it champion for definition {definitionLabel}.{" "}
            {servesOnPromotion ? "That is the active definition, so it also takes the serving alias." : "That is not the active definition, so it will not take the serving alias."}
          </p>
          <p style={{ margin: "0 0 8px" }}>
            {currentChampion
              ? `It replaces production v${currentChampion.production_model_version} as champion for this definition. That version is retired but kept; promoting it again is how you roll back.`
              : "Nothing has been promoted under this definition before, so there is no previous champion to fall back to."}
          </p>
          {!apiLive && <p style={{ margin: 0 }}>The real-time decision API is not deployed, so the legacy policy score keeps deciding applications until it is.</p>}
        </ActionDialog>
      )}
    </Card>
  );
}
