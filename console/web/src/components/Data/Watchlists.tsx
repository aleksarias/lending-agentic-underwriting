/** Leakage and proxy watchlists: the variables a candidate must not use, with the reason each is on the list. */
import { Link } from "react-router-dom";
import type { CatalogVariable } from "../../api/types";
import { fmtAuc, fmtPct } from "../../lib/format";
import { classLabel } from "../Fairness/labels";
import { Card, EmptyState, Pill, Section } from "../ui";
import "./data.css";

/** Variable link that keeps the selected definition, so the detail screen shows the same catalog. */
export const variableHref = (name: string, defShort: string | null) => `/data/${encodeURIComponent(name)}${defShort ? `?def=${defShort}` : ""}`;

export function Watchlists({ variables, proxyThreshold, defShort }: { variables: CatalogVariable[]; proxyThreshold?: number; defShort: string | null }) {
  const leak = variables
    .filter((v) => v.leakage_risk !== "low")
    .sort((a, b) => (a.leakage_risk === b.leakage_risk ? (b.univariate_auc_train ?? 0) - (a.univariate_auc_train ?? 0) : a.leakage_risk === "high" ? -1 : 1));
  const proxy = variables.filter((v) => v.proxy_risk === "high").sort((a, b) => (b.proxy_auc ?? 0) - (a.proxy_auc ?? 0));
  return (
    <Section
      id="watchlists"
      title="Watchlists"
      note="Variables that would fail a check if a candidate used them. The harness blocks them; agents only see the flags, never the protected attributes behind them."
    >
      <div className="grid cols-2">
        <Card title={`Leakage watchlist (${leak.length})`} kind="measured">
          {leak.length === 0 ? (
            <EmptyState title="No variable has medium or high leakage risk">A variable lands here when it is populated after the decision, is named like the outcome, or predicts default implausibly well on its own.</EmptyState>
          ) : (
            <>
              <div className="small muted" style={{ marginBottom: 10 }}>
                A candidate that uses a high-risk variable fails the leakage check: the variable carries information from after the lending decision, so it would not exist when a real applicant
                is scored.
              </div>
              <ul className="data-watch">
                {leak.map((v) => (
                  <li key={v.variable}>
                    <div className="row between">
                      <Link className="name" to={variableHref(v.variable, defShort)}>
                        {v.variable}
                      </Link>
                      <Pill tone={v.leakage_risk === "high" ? "crit" : "warn"}>{v.leakage_risk} risk</Pill>
                    </div>
                    <div className="small">{v.leakage_reasons || "No reason recorded."}</div>
                    <div className="xs muted">
                      {v.description} · availability {v.availability === "decision" ? "at decision" : (v.availability || "unknown").replace(/_/g, " ")} · alone predicts default with AUC {fmtAuc(v.univariate_auc_train, 3)} · {fmtPct(v.missing_rate, 0)} missing
                    </div>
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>
        <Card title={`Proxy watchlist (${proxy.length})`} kind="measured">
          {proxy.length === 0 ? (
            <EmptyState title="No variable is flagged as a proxy">A variable lands here when it alone predicts membership of a protected group better than the scan threshold.</EmptyState>
          ) : (
            <>
              <div className="small muted" style={{ marginBottom: 10 }}>
                A flagged proxy could stand in for a protected class{proxyThreshold != null ? ` (flagged when it alone predicts group membership with AUC above ${fmtAuc(proxyThreshold, 2)})` : ""}. A
                candidate that uses one fails the “No proxy features” check. The per-group scan is on <Link to="/fairness">Fairness and compliance</Link>.
              </div>
              <ul className="data-watch">
                {proxy.map((v) => (
                  <li key={v.variable}>
                    <div className="row between">
                      <Link className="name" to={variableHref(v.variable, defShort)}>
                        {v.variable}
                      </Link>
                      <Pill tone="warn">proxy AUC {fmtAuc(v.proxy_auc, 3)}</Pill>
                    </div>
                    <div className="small">Predicts {v.proxy_class ? classLabel(v.proxy_class).toLowerCase() : "a protected class"} membership; 0.5 would mean no signal.</div>
                    <div className="xs muted">{v.description}</div>
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>
      </div>
    </Section>
  );
}
