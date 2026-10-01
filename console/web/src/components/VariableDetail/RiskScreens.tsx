/** The three screens that can stop a candidate from using a variable: leakage, proxy for a protected class, prohibited register. */
import { Link } from "react-router-dom";
import type { CatalogVariable } from "../../api/types";
import { fmtAuc } from "../../lib/format";
import { availabilityLabel } from "../Data/CatalogTable";
import { classLabel } from "../Fairness/labels";
import { HBars } from "../Models/shared";
import type { Limits } from "../Performance/thresholds";
import { Card, KeyValue, Pill, Section } from "../ui";
import "./variable.css";

export function RiskScreens({ x, limits }: { x: CatalogVariable; limits: Limits }) {
  return (
    <Section title="Risk screens" note="The harness runs these screens on every candidate. A variable that fails one cannot be used by a model.">
      <div className="variable-risks">
        <LeakageCard x={x} limits={limits} />
        <ProxyCard x={x} limits={limits} />
        <ProhibitedCard x={x} />
      </div>
    </Section>
  );
}

function LeakageCard({ x, limits }: { x: CatalogVariable; limits: Limits }) {
  return (
    <Card kind="measured">
      <div className="variable-risk">
        <div className="head">
          <strong>Leakage</strong>
          <Pill tone={x.leakage_risk === "high" ? "crit" : x.leakage_risk === "medium" ? "warn" : "good"}>{x.leakage_risk} risk</Pill>
        </div>
        {x.leakage_risk === "low" ? (
          <p>
            No leakage concern was found. The screen checks whether the value is only populated after the lending decision, whether its name looks like the outcome, and whether it alone
            predicts default implausibly well.
          </p>
        ) : (
          <p>
            <strong>{x.leakage_reasons || "No reason recorded."}</strong>{" "}
            {x.leakage_risk === "high" ? "A candidate that uses this variable fails the leakage check, because the value would not exist when a real applicant is scored." : "It is worth a look before a candidate uses it."}
          </p>
        )}
        <KeyValue
          items={[["Available at", x.availability === "decision" ? availabilityLabel(x.availability) : <Pill key="a" tone="warn">{availabilityLabel(x.availability)}</Pill>]]}
        />
        {x.univariate_auc_train != null && limits.singleFeatureAucMax != null && (
          <HBars
            title="Univariate AUC against the leakage limit"
            rows={[{ key: "auc", label: "Univariate AUC", value: x.univariate_auc_train, tone: x.univariate_auc_train > limits.singleFeatureAucMax ? "crit" : "accent" }]}
            format={(v) => fmtAuc(v, 3)}
            min={0.5}
            max={1}
            markers={[{ value: limits.singleFeatureAucMax, label: "Leakage limit" }]}
            footnote="The axis starts at 0.50, where a variable says nothing about default."
          />
        )}
      </div>
    </Card>
  );
}

function ProxyCard({ x, limits }: { x: CatalogVariable; limits: Limits }) {
  const flagged = x.proxy_risk === "high";
  return (
    <Card kind="measured">
      <div className="variable-risk">
        <div className="head">
          <strong>Proxy for a protected class</strong>
          <Pill tone={flagged ? "warn" : "good"}>{flagged ? "flagged" : "not flagged"}</Pill>
        </div>
        <p>
          {x.proxy_auc == null
            ? "The proxy scan has no result for this variable."
            : `Alone, this variable predicts ${x.proxy_class ? classLabel(x.proxy_class).toLowerCase() : "protected-group"} membership with AUC ${fmtAuc(x.proxy_auc, 3)} (0.5 means no signal${limits.proxyAucFlag != null ? `; flagged above ${fmtAuc(limits.proxyAucFlag, 2)}` : ""}).`}{" "}
          {flagged ? "A candidate that uses it fails the “No proxy features” check." : ""}
        </p>
        {x.proxy_auc != null && (
          <HBars
            title="Proxy AUC against the flag threshold"
            rows={[{ key: "p", label: "Proxy AUC", value: x.proxy_auc, tone: flagged ? "warn" : "accent" }]}
            format={(v) => fmtAuc(v, 3)}
            min={0.5}
            max={0.8}
            markers={limits.proxyAucFlag != null ? [{ value: limits.proxyAucFlag, label: "Flag threshold" }] : []}
            footnote="The axis starts at 0.50. The per-group scan is on the Fairness and compliance screen."
          />
        )}
        <Link className="small" to="/fairness">
          Open the proxy scan
        </Link>
      </div>
    </Card>
  );
}

function ProhibitedCard({ x }: { x: CatalogVariable }) {
  return (
    <Card kind="measured">
      <div className="variable-risk">
        <div className="head">
          <strong>Prohibited register</strong>
          <Pill tone={x.prohibited ? "crit" : "good"}>{x.prohibited ? "prohibited" : "not prohibited"}</Pill>
        </div>
        <p>
          {x.prohibited
            ? "This variable is on the prohibited register: a protected attribute or a close proxy for one. It may never be a model input, and a candidate that uses it fails validation."
            : "This variable is not on the prohibited register. The register lists protected attributes and close proxies that may never be model inputs."}
        </p>
      </div>
    </Card>
  );
}
