/**
 * Screen 16 — Rollouts and rollback: what has been promoted, and how does a change reach (or leave) production?
 *
 * Promotions are real records (production.promotions). Staged rollouts, with shadow and serving stages, need the decision
 * API and are an Unavailable payload, so the screen says what is missing. Rollback is explained as it works today.
 */
import { Link } from "react-router-dom";
import { useRollouts, useStatus } from "../api/hooks";
import type { RolloutsData } from "../api/types";
import { NotBuiltPanel, type WillShow } from "../components/Operate/NotBuiltPanel";
import { PromotionsTable } from "../components/Rollouts/PromotionsTable";
import { Card, EmptyState, Page, PageHeader, QueryView, Section } from "../components/ui";
import { fmtAgo } from "../lib/format";

const STAGED: WillShow[] = [
  { title: "Stages for each approved change", detail: "Shadow first, then serving, with the entry and exit criteria of each stage." },
  { title: "Who approved each step", detail: "The approver, the time and the rationale for every move between stages." },
  { title: "Shadow evidence", detail: "Score distributions and agreement with the serving model, reviewed before serving switches." },
  { title: "Traffic and decisions", detail: "How much traffic each stage carries and what it decided, once decisions are logged." },
];

function summarySentence(d: RolloutsData): string {
  if (d.promotions.length === 0) {
    return "Nothing has been promoted yet, so the legacy policy score still decides and there is nothing to roll back to.";
  }
  const newest = d.promotions[0];
  const effect = newest.serving ? "holds the serving alias" : "is champion for its definition but not serving";
  const plural = d.promotions.length === 1 ? "1 promotion" : `${d.promotions.length} promotions`;
  return `${plural} recorded; the newest, candidate v${newest.candidate_model_version} as production v${newest.production_model_version} ${fmtAgo(newest.ts)}, ${effect}. Staged rollouts are not built, so each promotion takes effect in one step.`;
}

export default function Rollouts() {
  const q = useRollouts();
  const status = useStatus();
  return (
    <Page>
      <QueryView query={q} loadingHeight={320}>
        {(d) => {
          const waiting = status.data?.decisions_waiting ?? 0;
          const newest = d.promotions[0];
          return (
            <>
              <PageHeader
                eyebrow="Decide and operate"
                title="Rollouts and rollback"
                summary={summarySentence(d)}
              />

              <Section
                title="Promotions"
                note="A promotion copies an approved candidate into the production model registry as a new version and marks it champion for its definition of default. When that is the active definition it also takes the serving alias, and the champion it replaces is retired but kept. It needs a passing holdout gate and a recorded human approval."
              >
                {d.promotions.length === 0 ? (
                  <EmptyState
                    title="Nothing has been promoted yet"
                    action={
                      <Link className="btn small" to="/approvals">
                        {waiting > 0 ? `Go to approvals (${waiting} waiting)` : "Go to approvals"}
                      </Link>
                    }
                  >
                    Promotions appear here once a candidate has passed the holdout gate and a person has approved and promoted it. Until then the legacy policy score decides every application.
                  </EmptyState>
                ) : (
                  <PromotionsTable rows={d.promotions} />
                )}
              </Section>

              <Section title="Staged rollout">
                <NotBuiltPanel title="Staged rollouts are not available" reason={d.live.reason} requires={d.live.requires} willShow={STAGED} />
              </Section>

              <Section title="Rollback">
                <div className="grid cols-2">
                  <Card title="Today">
                    <ul className="plain small">
                      <li>
                        <strong>This console has no rollback action yet.</strong> A promotion moves the serving alias in one step, and rolling back means promoting the
                        previous champion again.
                      </li>
                      <li>Champions are never deleted. The champion a promotion replaces is retired but kept in the registry, so it can be restored.</li>
                      <li>
                        {newest
                          ? newest.previous_champion_version
                            ? `The newest promotion replaced production v${newest.previous_champion_version}, which is the version a rollback would restore.`
                            : "The newest promotion had no earlier champion, so there is no earlier version to restore; the fallback is the legacy policy score."
                          : "With no promotion, there is nothing to roll back: the legacy policy score is still in charge."}
                      </li>
                    </ul>
                  </Card>
                  <Card title="When the decision API exists">
                    <ul className="plain small">
                      <li>Roll back to the previous champion or policy with a reason. It takes effect within minutes and is logged.</li>
                      <li>
                        On-call and approvers can roll back without a new approval, because returning to the last approved state is always safe. Each rollback is reviewed
                        afterwards.
                      </li>
                    </ul>
                  </Card>
                </div>
              </Section>
            </>
          );
        }}
      </QueryView>
    </Page>
  );
}
