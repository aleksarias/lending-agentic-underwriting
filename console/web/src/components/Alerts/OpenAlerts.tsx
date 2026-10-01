/**
 * Alerts that need a person: raised by the newest monitoring run and not yet acknowledged. Acknowledging records who saw
 * the alert and why it is acceptable or handled, with a note. It changes no threshold, model or cycle.
 */
import { useEffect, useRef, useState } from "react";
import { ApiError } from "../../api/client";
import { useAckAlert } from "../../api/hooks";
import type { ActionResult, AlertItem } from "../../api/types";
import { fmtDateTime } from "../../lib/format";
import { ActionButton, ActionDialog } from "../Operate/actions";
import { ACTIONS_DISABLED } from "../Operate/constants";
import { DefBadge } from "../Operate/definitions";
import type { Thresholds } from "../Operate/thresholds";
import { Banner, Card, EmptyState, Pill, TimeAgo } from "../ui";
import { AlertTitle } from "./AlertTitle";
import { SEVERITY_LABEL, alertMeasure, alertTitle } from "./logic";
import "./Alerts.css";

const TONE = { high: "crit", medium: "warn", low: "neutral" } as const;

export function AlertSummaryLine({ a, th }: { a: AlertItem; th: Thresholds }) {
  const m = alertMeasure(a, th);
  return (
    <>
      <span className="num">{m.value}</span>
      {m.limit && <span className="muted"> against {m.limit}</span>}
    </>
  );
}

export function OpenAlerts({ alerts, th, actionsEnabled, user }: { alerts: AlertItem[]; th: Thresholds; actionsEnabled: boolean | undefined; user: string | null }) {
  const ack = useAckAlert();
  const [target, setTarget] = useState<AlertItem | null>(null);
  const [outcome, setOutcome] = useState<{ tone: "good" | "warn" | "crit"; message: string } | null>(null);
  const outcomeRef = useRef<HTMLDivElement>(null);
  // the acknowledged alert leaves this list, taking its button with it, so the result takes focus (and is read out)
  useEffect(() => {
    if (outcome) outcomeRef.current?.focus();
  }, [outcome]);

  if (!alerts.length) {
    return (
      <div className="stack">
        {outcome && (
          <div ref={outcomeRef} tabIndex={-1}>
            <Banner tone={outcome.tone} title={outcome.tone === "crit" ? "The acknowledgement did not complete" : "Acknowledged"}>
              {outcome.message}
            </Banner>
          </div>
        )}
        <EmptyState title="No alerts are open">
          An alert is open when the newest monitoring run raised it and nobody has acknowledged it. Monitoring compares the newest applications with the baseline built for the
          definition of default, and raises an alert when a distribution has shifted too far.
        </EmptyState>
      </div>
    );
  }

  return (
    <div className="stack" style={{ gap: "var(--gap)" }}>
      {outcome && (
        <div ref={outcomeRef} tabIndex={-1}>
          <Banner tone={outcome.tone} title={outcome.tone === "crit" ? "The acknowledgement did not complete" : "Acknowledged"}>
            {outcome.message}
          </Banner>
        </div>
      )}
      <Card flush kind="measured">
        <ul className="list" style={{ padding: "0 16px" }}>
          {alerts.map((a) => (
            <li className="item" key={a.id}>
              <div className="alerts-row">
                <div className="alerts-main">
                  <div className="row" style={{ gap: 8 }}>
                    <Pill tone={TONE[a.severity]}>{SEVERITY_LABEL[a.severity]}</Pill>
                    <span className="alerts-title">
                      <AlertTitle a={a} />
                    </span>
                  </div>
                  <div className="small">
                    <AlertSummaryLine a={a} th={th} />
                  </div>
                  <div className="alerts-meta">
                    <DefBadge version={a.definition_version} />
                    <span title={fmtDateTime(a.ts)}>
                      raised <TimeAgo iso={a.ts} />
                    </span>
                    <span>not acknowledged</span>
                  </div>
                </div>
                <div className="alerts-actions">
                  <ActionButton small disabledReason={actionsEnabled ? null : actionsEnabled === undefined ? "Checking whether actions are enabled on this console." : ACTIONS_DISABLED} onClick={() => setTarget(a)}>
                    Acknowledge
                  </ActionButton>
                </div>
              </div>
            </li>
          ))}
        </ul>
      </Card>
      {actionsEnabled === false && <div className="xs muted">{ACTIONS_DISABLED} Acknowledging needs the console to run with actions enabled; the person acknowledging is recorded by name.</div>}

      {target && (
        <ActionDialog
          open
          title="Acknowledge this alert?"
          confirmLabel="Acknowledge"
          requireText={{ label: "Note for the record (at least 10 characters): why it is acceptable, or what is being done", minLength: 10 }}
          busy={ack.isPending}
          onCancel={() => setTarget(null)}
          onConfirm={(note) =>
            ack.mutate(
              { alert_id: target.id, note },
              {
                onSuccess: (r: ActionResult) => {
                  setOutcome({ tone: r.ok ? "good" : "warn", message: r.message });
                  setTarget(null);
                },
                onError: (e: Error) => {
                  setOutcome({ tone: "crit", message: e instanceof ApiError ? e.detail : e.message });
                  setTarget(null);
                },
              },
            )
          }
        >
          <p style={{ margin: "0 0 8px" }}>
            This records that {user ? `you (${user})` : "you"} have seen <strong>{alertTitle(target)}</strong> and saves your note with it. The alert stays in the history.
          </p>
          <p style={{ margin: 0 }}>It does not change any threshold or model, and it does not start, stop or cancel an improvement cycle.</p>
        </ActionDialog>
      )}
    </div>
  );
}
