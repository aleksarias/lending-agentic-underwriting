/**
 * Screen 17 — Shadow scoring: how does a challenger score the newest applications next to the serving model?
 *
 * Shadow scores are measurements kept for comparison. They never change a decision. This screen shows the runs, the score
 * distribution of each model scored, and the agreement statistic when a serving model exists to compare with.
 */
import { useProgress, useShadow } from "../api/hooks";
import type { ShadowData } from "../api/types";
import { DefBadge } from "../components/Operate/definitions";
import { useThresholds } from "../components/Operate/thresholds";
import { Distribution } from "../components/Shadow/Distribution";
import { RunsTable } from "../components/Shadow/RunsTable";
import { roleLabel } from "../components/Shadow/roles";
import { Banner, Card, EmptyState, Page, PageHeader, QueryView, Section, Tiles } from "../components/ui";
import { fmtAgo, fmtDateTime, fmtNum, fmtPct } from "../lib/format";

function latestRun(d: ShadowData) {
  const at = d.runs[0]?.scored_at ?? null;
  return { at, rows: at ? d.runs.filter((r) => r.scored_at === at) : [] };
}

function summarySentence(d: ShadowData): string {
  if (!d.available || d.runs.length === 0) return "Shadow scoring has not run yet, so there are no challenger scores to look at.";
  const { at, rows } = latestRun(d);
  const n = Math.max(...rows.map((r) => r.n));
  const who = rows.map((r) => `${roleLabel(r.role).toLowerCase()} v${r.model_version}`).join(" and ");
  const hasServing = rows.some((r) => r.role === "serving");
  const agreement =
    d.agreement_at_policy != null
      ? `the serving model and the challenger make the same decision on ${fmtPct(d.agreement_at_policy, 1)} of applications at the policy approval rate`
      : hasServing
        ? "agreement with the serving model could not be computed"
        : "there is no agreement statistic because no model is serving";
  return `The latest shadow run, ${fmtAgo(at)}, scored ${fmtNum(n)} applications with ${who}; ${agreement}.`;
}

export default function Shadow() {
  const q = useShadow();
  const progress = useProgress();
  const thresholds = useThresholds();
  const rate = progress.data?.benchmark?.fixed_approval_rate ?? thresholds.approvalRate;
  return (
    <Page>
      <QueryView query={q} loadingHeight={320}>
        {(d) => {
          const { at, rows } = latestRun(d);
          const runCount = new Set(d.runs.map((r) => r.scored_at)).size;
          const hasServing = rows.some((r) => r.role === "serving");
          const hasChallenger = rows.some((r) => r.role === "challenger");
          return (
            <>
              <PageHeader
                eyebrow="Decide and operate"
                title="Shadow scoring"
                summary={summarySentence(d)}
                meta={
                  rows[0] ? (
                    <>
                      <span>Definition of default</span>
                      <DefBadge version={rows[0].definition_version} />
                    </>
                  ) : undefined
                }
              />

              <Banner tone="neutral" title="Shadow scores never affect a decision">
                A shadow run scores the newest applications with a challenger next to the serving model and stores the scores for comparison only. No application is
                approved or declined because of them.
              </Banner>

              {!d.available || d.runs.length === 0 ? (
                <Section title="Runs">
                  <EmptyState title="Shadow scoring has not run yet">
                    {d.reason ?? "No shadow run is recorded."} When it has, this screen shows each run, the score distribution of every model scored, and how often a
                    challenger would decide differently from the serving model.
                  </EmptyState>
                </Section>
              ) : (
                <>
                  <Section title="Latest run">
                    <Tiles
                      tiles={[
                        { key: "at", label: "Scored", value: fmtAgo(at), sub: fmtDateTime(at) },
                        { key: "n", label: "Applications scored", value: fmtNum(Math.max(...rows.map((r) => r.n))), sub: "the newest applications in the data" },
                        { key: "models", label: "Models scored", value: rows.map((r) => `${roleLabel(r.role).toLowerCase()} v${r.model_version}`).join(", ") },
                        {
                          key: "agree",
                          label: rate != null ? `Agreement at ${fmtPct(rate, 0)} approval` : "Agreement at the policy approval rate",
                          value: d.agreement_at_policy != null ? fmtPct(d.agreement_at_policy, 1) : "Not available",
                          sub: d.agreement_at_policy != null ? "same approve or decline decision" : hasServing ? "could not be computed" : "no serving model to compare with",
                        },
                      ]}
                    />
                  </Section>

                  <Section title="Agreement with the serving model">
                    <Card kind={d.agreement_at_policy != null ? "measured" : undefined}>
                      {d.agreement_at_policy != null ? (
                        <div className="stack">
                          <div>
                            <span className="num" style={{ fontSize: 26, fontWeight: 700 }}>
                              {fmtPct(d.agreement_at_policy, 1)}
                            </span>{" "}
                            <span className="small muted">of applications get the same outcome from both models</span>
                          </div>
                          <div className="small">
                            The other {fmtPct(1 - d.agreement_at_policy, 1)} would swap: one model approves what the other declines.
                          </div>
                        </div>
                      ) : (
                        <div className="stack">
                          <div className="small">
                            <strong>Not available.</strong>{" "}
                            {!hasServing
                              ? "No model is serving, so there is no serving score to compare the challenger with."
                              : !hasChallenger
                                ? "The latest run scored no challenger, so there is nothing to compare the serving model with."
                                : "The latest run scored both models, but the statistic could not be computed."}
                          </div>
                          <div className="xs muted">It appears once a run scores a serving model and a challenger on the same applications.</div>
                        </div>
                      )}
                      <div className="xs muted" style={{ marginTop: 10 }}>
                        Agreement is the share of applications that get the same approve or decline outcome from the serving model and the challenger when each approves the
                        {rate != null ? ` ${fmtPct(rate, 0)}` : ""} of applicants it scores as least risky (the policy approval rate). The applications the two models would decide
                        differently, and how those loans later perform, are not shown yet.
                      </div>
                    </Card>
                  </Section>

                  {d.distributions.length > 0 && (
                    <Section
                      title="Score distribution by model"
                      note={`Predicted probability of default for the applications in the latest run, ${fmtAgo(at)}. A shift between the serving model and a challenger shows up here before any decision changes.`}
                    >
                      <Distribution distributions={d.distributions} />
                    </Section>
                  )}

                  <Section
                    title="Runs"
                    note={`${runCount} run${runCount === 1 ? "" : "s"}, one row per model scored. Mean predicted default probability is the average of the model's estimates, not an observed default rate.`}
                  >
                    <RunsTable runs={d.runs} />
                  </Section>
                </>
              )}
            </>
          );
        }}
      </QueryView>
    </Page>
  );
}
