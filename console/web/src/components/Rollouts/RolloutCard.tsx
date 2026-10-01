/**
 * One shadow-first rollout: the shadow report (what the promoted champion would have decided on live traffic), the
 * approvals it has, its history, and the action that fits its state: approve or reject, serve, or roll back.
 * Buttons that cannot act say why instead of disappearing.
 */
import { useState } from "react";
import { ApiError } from "../../api/client";
import { useRolloutDecide, useRolloutRollback, useRolloutServe } from "../../api/hooks";
import type { ActionResult, Rollout, RolloutState } from "../../api/types";
import { fmtDateTime, fmtNum, fmtPct } from "../../lib/format";
import { ActionButton, ActionDialog } from "../Operate/actions";
import { ACTIONS_DISABLED } from "../Operate/constants";
import { DefBadge } from "../Operate/definitions";
import { Card, KeyValue, Pill, TimeAgo } from "../ui";

const STATE: Record<RolloutState, { label: string; tone: "good" | "warn" | "neutral" | "crit" | "accent" }> = {
  shadow: { label: "In shadow", tone: "accent" },
  serving: { label: "Serving", tone: "good" },
  retired: { label: "Retired", tone: "neutral" },
  rolled_back: { label: "Rolled back", tone: "warn" },
  superseded: { label: "Superseded", tone: "neutral" },
};

type Dialog = { kind: "approve" | "reject" | "serve" | "rollback" } | null;

export type ActionOutcome = { tone: "good" | "warn" | "crit"; message: string };

/** `onOutcome` reports an action's result to the page: the card may move between lists (and remount) when its state changes. */
export function RolloutCard(props: {
  r: Rollout;
  minShadow: number;
  actionsEnabled: boolean | undefined;
  user: string | null;
  onOutcome: (o: ActionOutcome) => void;
}) {
  const { r, minShadow, actionsEnabled, user, onOutcome } = props;
  const decide = useRolloutDecide();
  const serve = useRolloutServe();
  const rollback = useRolloutRollback();
  const [dialog, setDialog] = useState<Dialog>(null);
  const rep = r.report;
  const a = r.approvals;
  const busy = decide.isPending || serve.isPending || rollback.isPending;

  const off = actionsEnabled ? null : actionsEnabled === undefined ? "Checking whether actions are enabled on this console." : ACTIONS_DISABLED;
  const alreadyDecided = user ? a.decisions.some((x) => x.approver === user) : false;
  const decideBlock = off ?? (alreadyDecided ? `You (${user}) already recorded a decision on this rollout.` : null);
  const serveBlock =
    off ??
    (a.rejected_by.length
      ? `Rejected by ${a.rejected_by.join(", ")}.`
      : rep.n < minShadow
        ? `${fmtNum(rep.n)} of ${fmtNum(minShadow)} shadow decisions so far.`
        : a.approvers.length < a.required
          ? `${a.approvers.length} of ${a.required} approvals recorded.`
          : null);

  const done = (r2: ActionResult) => {
    onOutcome({ tone: r2.ok ? "good" : "warn", message: r2.message });
    setDialog(null);
  };
  const failed = (e: Error) => {
    onOutcome({ tone: "crit", message: e instanceof ApiError ? e.detail : e.message });
    setDialog(null);
  };

  return (
    <Card>
      <div className="stack">
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          <Pill tone={STATE[r.state].tone}>{STATE[r.state].label}</Pill>
          <strong>production v{r.model_version}</strong>
          <DefBadge version={r.definition_version} />
          <span className="small muted">
            started <TimeAgo iso={r.started_at} /> by {r.started_by} <span className="mono xs">{r.rollout_id}</span>
          </span>
        </div>

        <div className="grid cols-2">
          <div>
            <div className="small muted" style={{ marginBottom: 4 }}>
              Shadow report: the same live applications, decided by what serves and scored by this champion
            </div>
            {rep.n === 0 ? (
              <p className="small" style={{ margin: 0 }}>
                No shadow decisions yet. It needs at least {fmtNum(minShadow)} before it can serve.
              </p>
            ) : (
              <KeyValue
                items={[
                  ["Shadow decisions", `${fmtNum(rep.n)}${rep.n < minShadow ? ` of ${fmtNum(minShadow)} needed` : ""}`],
                  ["Same decision", fmtPct(rep.agreement, 1)],
                  ["Approved: serving → shadow", `${fmtPct(rep.serving?.approve, 1)} → ${fmtPct(rep.shadow?.approve, 1)}`],
                  ["Declined: serving → shadow", `${fmtPct(rep.serving?.decline, 1)} → ${fmtPct(rep.shadow?.decline, 1)}`],
                  ["Would flip", `${fmtNum(rep.approve_to_decline)} approvals to declines, ${fmtNum(rep.decline_to_approve)} declines to approvals`],
                  ["Mean PD: serving → shadow", rep.mean_pd_serving != null ? `${fmtPct(rep.mean_pd_serving, 2)} → ${fmtPct(rep.mean_pd_shadow, 2)}` : "serving is the legacy policy (no PD)"],
                ]}
              />
            )}
          </div>
          <div>
            <div className="small muted" style={{ marginBottom: 4 }}>
              Approvals to serve: {a.approvers.length} of {a.required}
              {a.rejected_by.length ? `; rejected by ${a.rejected_by.join(", ")}` : ""}
            </div>
            {a.decisions.length === 0 ? (
              <p className="small" style={{ margin: 0 }}>Nobody has decided yet.</p>
            ) : (
              <ul className="plain small">
                {a.decisions.map((x) => (
                  <li key={`${x.approver}-${x.ts}`}>
                    <Pill tone={x.decision === "approve" ? "good" : "crit"}>{x.decision}</Pill> {x.approver}, {fmtDateTime(x.ts)}
                    {x.note && <div className="xs muted">{x.note}</div>}
                  </li>
                ))}
              </ul>
            )}
            <details className="small" style={{ marginTop: 8 }}>
              <summary>History ({r.events.length})</summary>
              <ul className="plain xs">
                {r.events.map((e) => (
                  <li key={`${e.event}-${e.ts}`}>
                    {fmtDateTime(e.ts)}: <strong>{e.event}</strong> by {e.by}
                    {e.note ? ` (${e.note})` : ""}
                  </li>
                ))}
              </ul>
            </details>
          </div>
        </div>

        {r.state === "shadow" && (
          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            <ActionButton variant="primary" disabledReason={decideBlock} onClick={() => setDialog({ kind: "approve" })}>
              Approve serving
            </ActionButton>
            <ActionButton disabledReason={decideBlock} onClick={() => setDialog({ kind: "reject" })}>
              Reject
            </ActionButton>
            <ActionButton disabledReason={serveBlock} onClick={() => setDialog({ kind: "serve" })}>
              Serve now
            </ActionButton>
          </div>
        )}
        {r.state === "serving" && (
          <div className="row" style={{ gap: 8 }}>
            <ActionButton variant="danger" disabledReason={off} onClick={() => setDialog({ kind: "rollback" })}>
              Roll back
            </ActionButton>
            <span className="xs muted">
              Restores {r.previous_serving_version ? `production v${r.previous_serving_version}` : "the legacy policy"}. One person is enough: returning to the last approved state
              never waits for a second approver.
            </span>
          </div>
        )}
      </div>

      {(dialog?.kind === "approve" || dialog?.kind === "reject") && (
        <ActionDialog
          open
          title={dialog.kind === "approve" ? "Approve this champion to serve?" : "Reject this rollout?"}
          confirmLabel={dialog.kind === "approve" ? "Approve" : "Reject"}
          danger={dialog.kind === "reject"}
          requireText={{ label: "What you checked in the shadow report (at least 10 characters)", minLength: 10 }}
          busy={busy}
          onCancel={() => setDialog(null)}
          onConfirm={(note) => decide.mutate({ rollout_id: r.rollout_id, decision: dialog.kind as "approve" | "reject", note }, { onSuccess: done, onError: failed })}
        >
          <p style={{ margin: "0 0 8px" }}>
            Records {user ? `your (${user})` : "your"} decision on production v{r.model_version}. Serving needs {a.required} different approver{a.required === 1 ? "" : "s"}; one
            rejection blocks it.
          </p>
          <p style={{ margin: 0 }}>Approving does not switch anything by itself: someone still has to serve it.</p>
        </ActionDialog>
      )}
      {dialog?.kind === "serve" && (
        <ActionDialog
          open
          title={`Make production v${r.model_version} decide?`}
          confirmLabel="Serve"
          busy={busy}
          onCancel={() => setDialog(null)}
          onConfirm={() => serve.mutate({ rollout_id: r.rollout_id }, { onSuccess: done, onError: failed })}
        >
          <p style={{ margin: "0 0 8px" }}>
            The serving alias moves to v{r.model_version}, the decision model is rebuilt with it, and the endpoint (when it exists) switches to the new build. Every later
            decision records the new versions.
          </p>
          <p style={{ margin: 0 }}>A rollback can undo it in one step.</p>
        </ActionDialog>
      )}
      {dialog?.kind === "rollback" && (
        <ActionDialog
          open
          danger
          title={`Roll back production v${r.model_version}?`}
          confirmLabel="Roll back"
          requireText={{ label: "Reason for the record (at least 10 characters)", minLength: 10 }}
          busy={busy}
          onCancel={() => setDialog(null)}
          onConfirm={(reason) => rollback.mutate({ rollout_id: r.rollout_id, reason }, { onSuccess: done, onError: failed })}
        >
          <p style={{ margin: 0 }}>
            {r.previous_serving_version ? `Production v${r.previous_serving_version}` : "The legacy policy"} decides again as soon as the decision model is rebuilt. The rollback is
            logged with your reason and reviewed afterwards.
          </p>
        </ActionDialog>
      )}
    </Card>
  );
}
