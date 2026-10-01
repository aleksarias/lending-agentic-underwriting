/**
 * One decision: outcome, probability of default, the principal reasons (with the model input behind each, for
 * reviewers), the adverse-action content an applicant would read, the versions that decided, and the shadow score when
 * a promoted champion was scoring in shadow. Applicant inputs are never shown in the console.
 */
import { Link, useParams } from "react-router-dom";
import { useDecision } from "../api/hooks";
import type { DecisionDetail as Detail } from "../api/types";
import { Banner, Card, KeyValue, Page, PageHeader, Pill, QueryView, Section } from "../components/ui";
import { fmtDateTime, fmtPct, shortVersion } from "../lib/format";
import { OutcomePill } from "../components/Decisions/OutcomePill";
import "../components/Decisions/Decisions.css";

const PATH_TEXT: Record<string, string> = {
  model: "the serving model's probability of default under the active policy",
  knockout: "a knock-out rule, before any model was consulted",
  legacy: "the legacy policy score",
};

function summary(d: Detail): string {
  const how = d.fallback_used ? "the legacy policy, because the model could not decide in time or failed" : PATH_TEXT[d.path] ?? d.path;
  const pd = d.probability_of_default != null ? ` (probability of default ${fmtPct(d.probability_of_default, 1)}, band ${d.risk_band})` : "";
  return `${d.decision[0].toUpperCase()}${d.decision.slice(1)} for application ${d.application_id}, decided ${fmtDateTime(d.decided_at)} by ${how}${pd}.`;
}

export default function DecisionDetail() {
  const { decisionId } = useParams();
  const q = useDecision(decisionId);
  return (
    <Page>
      <QueryView query={q} loadingHeight={280}>
        {(d) => (
          <>
            <PageHeader eyebrow="Decision" title={d.decision_id} summary={summary(d)} meta={<Link to="/decisions">All decisions</Link>} />
            {d.is_test && <Banner tone="neutral" title="Test traffic">This decision came from a release check; it is excluded from every figure.</Banner>}
            {d.reasons_missing && (
              <Banner tone="crit" title="No principal reasons">
                This {d.decision} has no reasons, so no adverse-action notice could be sent for it. It is counted on the Decisions screen.
              </Banner>
            )}
            <Section title="Outcome">
              <div className="grid cols-2">
                <Card>
                  <KeyValue
                    items={[
                      ["Decision", <OutcomePill key="o" outcome={d.decision} />],
                      ["Probability of default", d.probability_of_default != null ? fmtPct(d.probability_of_default, 2) : "— (not scored)"],
                      ["Risk band", d.risk_band ?? "—"],
                      ["Decided by", PATH_TEXT[d.path] ?? d.path],
                      ["Fallback", d.fallback_used ? <span key="f">yes: {d.fallback_reason ?? "reason not recorded"}</span> : "no"],
                      ["Decision date", d.decision_date ?? "—"],
                    ]}
                  />
                </Card>
                <Card title="Service">
                  <KeyValue
                    items={[
                      ["Model time", d.latency_ms != null ? `${d.latency_ms.toFixed(1)} ms per application` : "—"],
                      ["Round trip seen by the caller", d.client_latency_ms != null ? `${d.client_latency_ms.toFixed(d.client_latency_ms < 10 ? 1 : 0)} ms` : "—"],
                      ["Logged from", d.source ?? "—"],
                    ]}
                  />
                </Card>
              </div>
            </Section>

            <Section title="Principal reasons" note="Ranked by how much each model input pushed the probability of default up for this applicant. One statement is never listed twice.">
              {d.reasons.length === 0 ? (
                <Card>
                  <p className="small muted" style={{ margin: 0 }}>
                    {d.decision === "approve" ? "Approvals carry no adverse-action reasons." : "No reasons were recorded."}
                  </p>
                </Card>
              ) : (
                <Card flush>
                  <ol className="decisions-reasons" style={{ padding: "12px 16px 12px 36px" }}>
                    {d.reasons.map((r) => (
                      <li key={r.rank}>
                        <strong className="mono">{r.code}</strong> {r.statement}{" "}
                        <span className="xs muted">
                          from <span className="mono">{r.feature ?? "?"}</span>
                          {!r.mapped && (
                            <>
                              {" "}
                              <Pill tone="crit">no approved statement</Pill>
                            </>
                          )}
                        </span>
                      </li>
                    ))}
                  </ol>
                </Card>
              )}
            </Section>

            <Section title="Adverse-action content" note={d.notice.caveat ?? undefined}>
              <Card>
                {d.notice.required ? (
                  <>
                    <p className="small" style={{ marginTop: 0 }}>
                      A notice is required for this decline. The applicant would read these principal reasons:
                    </p>
                    <ol className="decisions-reasons">
                      {d.notice.principal_reasons.map((r) => (
                        <li key={r.rank}>{r.statement}</li>
                      ))}
                    </ol>
                  </>
                ) : (
                  <p className="small" style={{ margin: 0 }}>
                    {d.decision === "refer"
                      ? "No notice yet: a referral is not adverse until a person declines it. The reasons above support that review."
                      : "No notice: the application was approved."}
                  </p>
                )}
              </Card>
            </Section>

            <Section title="Versions that decided">
              <Card>
                <KeyValue
                  items={[
                    ["Model", d.model_version ? `production v${d.model_version}` : "none (legacy policy)"],
                    ["Definition of default", d.definition_version ? <Link key="def" to={`/definitions/${d.definition_version}`}>{shortVersion(d.definition_version)}</Link> : "—"],
                    ["Policy", <span key="p" className="mono">{shortVersion(d.policy_version)}</span>],
                    ["Decision model build", <span key="b" className="mono">{d.build_id ?? "—"}</span>],
                    ["Code", <span key="c" className="mono">{d.code_version ?? "—"}</span>],
                  ]}
                />
              </Card>
            </Section>

            {d.shadow && (
              <Section title="Shadow score" note="A promoted champion scored this application next to the serving model. It decided nothing.">
                <Card>
                  <KeyValue
                    items={[
                      ["Shadow model", d.shadow.model_version ? `production v${d.shadow.model_version}` : "—"],
                      ["Would have decided", <OutcomePill key="s" outcome={d.shadow.decision} />],
                      ["Its probability of default", d.shadow.probability_of_default != null ? fmtPct(d.shadow.probability_of_default, 2) : "—"],
                    ]}
                  />
                </Card>
              </Section>
            )}
          </>
        )}
      </QueryView>
    </Page>
  );
}
