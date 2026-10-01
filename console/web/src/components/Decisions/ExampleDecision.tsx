/**
 * The decision the endpoint will return, rendered as an annotated example plus the raw JSON behind a toggle.
 * The values come from the API's preview payload and are illustrative: no application was decided.
 */
import { useId, useState, type ReactNode } from "react";
import type { DecisionsData, Tone } from "../../api/types";
import { fmtPct } from "../../lib/format";
import { DefBadge } from "../Operate/definitions";
import { Card, Json, KeyValue, Pill } from "../ui";
import { asBoolean, asNumber, asRecord, asString, readReasonCodes } from "./parse";
import "./Decisions.css";

const DECISION_TONE: Record<string, Tone> = { approve: "good", decline: "crit", refer: "warn" };

function Row({ label, value, why }: { label: string; value: ReactNode; why: ReactNode }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd className="value">{value}</dd>
      <dd className="why">{why}</dd>
    </div>
  );
}

function decisionWhy(decision: string | null, pd: number | null, cutoff: number | null): string {
  const compare = pd != null && cutoff != null ? (pd <= cutoff ? "at or below" : "above") : null;
  if (decision === "approve") return compare ? `The estimated default probability is ${compare} the cut-off, so the application is approved.` : "The application is approved.";
  if (decision === "decline") return compare ? `The estimated default probability is ${compare} the cut-off, so the application is declined, and the reason codes are the principal reasons for the adverse-action notice.` : "The application is declined.";
  if (decision === "refer") return "The application is sent to a person instead of being decided automatically.";
  return "The outcome of the policy applied to the model's estimate.";
}

export function ExampleDecision({ preview }: { preview: DecisionsData["preview"] }) {
  const [showJson, setShowJson] = useState(false);
  const jsonId = useId();
  const ex = asRecord(preview.example_response);
  const decision = asString(ex.decision);
  const pd = asNumber(ex.pd);
  const cutoff = asNumber(ex.cutoff_pd);
  const model = asRecord(ex.model);
  const modelName = asString(model.name);
  const modelVersion = asString(model.version);
  const modelAlias = asString(model.alias);
  const definition = asString(ex.definition_version);
  const reasons = readReasonCodes(ex.reason_codes);
  const latency = asNumber(ex.latency_ms);
  const fallback = asBoolean(ex.fallback);
  const applicationId = asString(ex.application_id);

  return (
    <Card>
      <div className="row between" style={{ marginBottom: 10 }}>
        <span className="row" style={{ gap: 8 }}>
          <Pill tone="warn">Illustrative example</Pill>
          <span className="small muted">Invented values that show the shape of a response. No application was decided.</span>
        </span>
      </div>
      <KeyValue
        items={[
          ["Endpoint", <code key="e">{preview.endpoint}</code>],
          ["Policy version", <DefBadge key="p" version={preview.policy_version} />],
        ]}
      />
      <dl className="decisions-annot" style={{ marginTop: 10 }} aria-label="Annotated example decision">
        <Row label="Application" value={applicationId ?? "—"} why="Identifies the application the decision is for." />
        <Row
          label="Decision"
          value={decision ? <Pill tone={DECISION_TONE[decision] ?? "neutral"}>{decision}</Pill> : "—"}
          why={decisionWhy(decision, pd, cutoff)}
        />
        <Row
          label="Default probability against the cut-off"
          value={
            pd != null && cutoff != null ? (
              <span className="num">
                {fmtPct(pd, 2)} against {fmtPct(cutoff, 2)}
              </span>
            ) : (
              "—"
            )
          }
          why="The model's estimated probability of default next to the cut-off set by the policy. Knock-out rules and a refer band can also change the outcome."
        />
        <Row
          label="Model"
          value={modelName ? `${modelName} v${modelVersion ?? "?"}${modelAlias ? ` (alias ${modelAlias})` : ""}` : "—"}
          why="The registered production model that scored the application, by name, version and alias."
        />
        <Row
          label="Definition of default"
          value={definition ? <DefBadge version={definition} /> : "—"}
          why="The definition the model was trained and validated under. Each decision will record the definition version it was made under."
        />
        <Row
          label="Reason codes"
          value={
            reasons.length ? (
              <ol className="decisions-reasons">
                {reasons.map((r) => (
                  <li key={`${r.rank}-${r.feature}`}>
                    {r.text} <span className="mono faint">({r.feature})</span>
                  </li>
                ))}
              </ol>
            ) : (
              "—"
            )
          }
          why="The features that pushed the estimate up the most, ranked. On a decline they are the principal reasons in the adverse-action notice."
        />
        <Row
          label="Latency"
          value={latency != null ? <span className="num">{latency} ms</span> : "—"}
          why="Time from request to response. The proposed targets are the 95th percentile under 300 ms and the 99th under 800 ms, to be confirmed with the origination team."
        />
        <Row
          label="Fallback used"
          value={fallback == null ? "—" : fallback ? "Yes" : "No"}
          why="If the model is unavailable or too slow, the endpoint uses the legacy policy path or refers the application to a person, and records that it did."
        />
      </dl>
      <div style={{ marginTop: 12 }}>
        <button type="button" className="btn small" aria-expanded={showJson} aria-controls={jsonId} onClick={() => setShowJson((v) => !v)}>
          {showJson ? "Hide raw JSON" : "Show raw JSON"}
        </button>
        {showJson && (
          <div id={jsonId} style={{ marginTop: 8 }}>
            <Json value={preview.example_response} />
          </div>
        )}
      </div>
    </Card>
  );
}
