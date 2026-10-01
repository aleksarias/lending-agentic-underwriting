/**
 * Screen 16 — Rollouts and rollback: how does an approved champion reach (or leave) the decisions?
 *
 * Shadow first: a promotion makes a champion, which then scores live decisions in shadow and decides nothing. A person
 * reviews the shadow report and approves serving (two-person rule where configured); serving moves the serving alias
 * and rebuilds the decision model. Rollback restores what served before, in one step, by one person.
 */
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useRollouts, useStatus } from "../api/hooks";
import type { RolloutsData, StatusSummary } from "../api/types";
import { PromotionsTable } from "../components/Rollouts/PromotionsTable";
import { RolloutCard, type ActionOutcome } from "../components/Rollouts/RolloutCard";
import { Banner, Card, EmptyState, Page, PageHeader, QueryView, Section } from "../components/ui";

function summarySentence(d: RolloutsData, status: StatusSummary | undefined): string {
  const serving = d.rollouts.find((r) => r.state === "serving");
  const shadow = d.rollouts.find((r) => r.state === "shadow");
  const parts: string[] = [];
  if (serving) parts.push(`Production v${serving.model_version} serves through rollout ${serving.rollout_id}.`);
  else if (status?.serving) parts.push(`${status.serving.label} decides; it serves outside any current rollout (promoted before rollouts existed, or restored by a rollback).`);
  else parts.push("No model serves: the legacy policy decides.");
  if (shadow) {
    const need = Math.max(d.min_shadow_decisions - shadow.report.n, 0);
    parts.push(
      `Production v${shadow.model_version} is in shadow with ${shadow.report.n} shadow decision${shadow.report.n === 1 ? "" : "s"}` +
        (need > 0 ? ` (${need} more needed)` : "") +
        ` and ${shadow.approvals.approvers.length} of ${shadow.approvals.required} approvals.`,
    );
  } else {
    parts.push("Nothing is waiting in shadow.");
  }
  return parts.join(" ");
}

export default function Rollouts() {
  const q = useRollouts();
  const status = useStatus();
  const [outcome, setOutcome] = useState<ActionOutcome | null>(null);
  const outcomeRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (outcome) outcomeRef.current?.focus(); // the card that acted may have moved lists: the result takes focus
  }, [outcome]);
  return (
    <Page>
      <QueryView query={q} loadingHeight={320}>
        {(d) => {
          const current = d.rollouts.filter((r) => r.state === "shadow" || r.state === "serving");
          const past = d.rollouts.filter((r) => r.state !== "shadow" && r.state !== "serving");
          const waiting = status.data?.decisions_waiting ?? 0;
          return (
            <>
              <PageHeader eyebrow="Decide and operate" title="Rollouts and rollback" summary={summarySentence(d, status.data)} />
              {outcome && (
                <div ref={outcomeRef} tabIndex={-1}>
                  <Banner tone={outcome.tone} title={outcome.tone === "crit" ? "The action did not complete" : "Done"}>
                    {outcome.message}
                  </Banner>
                </div>
              )}

              <Section
                title="Current"
                note={`A champion needs at least ${d.min_shadow_decisions} shadow decisions and ${d.required_approvals} approval${d.required_approvals === 1 ? "" : "s"} from different people before it can serve.`}
              >
                {current.length === 0 ? (
                  <EmptyState
                    title="No rollout in shadow or serving"
                    action={
                      <Link className="btn small" to="/approvals">
                        {waiting > 0 ? `Go to approvals (${waiting} waiting)` : "Go to approvals"}
                      </Link>
                    }
                  >
                    A rollout starts when a champion is promoted for the active definition of default. It then scores live decisions in shadow until it is approved and
                    served.
                  </EmptyState>
                ) : (
                  <div className="stack">
                    {current.map((r) => (
                      <RolloutCard key={r.rollout_id} r={r} minShadow={d.min_shadow_decisions} actionsEnabled={status.data?.actions_enabled} user={status.data?.user ?? null} onOutcome={setOutcome} />
                    ))}
                  </div>
                )}
              </Section>

              {past.length > 0 && (
                <Section title="Earlier rollouts">
                  <div className="stack">
                    {past.map((r) => (
                      <RolloutCard key={r.rollout_id} r={r} minShadow={d.min_shadow_decisions} actionsEnabled={status.data?.actions_enabled} user={status.data?.user ?? null} onOutcome={setOutcome} />
                    ))}
                  </div>
                </Section>
              )}

              <Section
                title="Promotions"
                note="A promotion copies an approved candidate into the production registry and makes it champion for its definition of default. For the active definition it starts a rollout in shadow; it does not change what decides."
              >
                {d.promotions.length === 0 ? (
                  <EmptyState title="Nothing has been promoted yet">
                    Promotions appear here once a candidate has passed the holdout gate and enough people have approved it.
                  </EmptyState>
                ) : (
                  <PromotionsTable rows={d.promotions} />
                )}
              </Section>

              <Section title="How rollback works">
                <Card>
                  <ul className="plain small">
                    <li>Rolling back the serving rollout restores the model that served before it, or the legacy policy if none did, and rebuilds the decision model.</li>
                    <li>One person can do it with a reason: returning to the last approved state never waits for a second approver. Each rollback is reviewed afterwards.</li>
                    <li>
                      Champions are never deleted. <span className="mono">lau decision check rollback</span> proves the restore works without changing production.
                    </li>
                  </ul>
                </Card>
              </Section>
            </>
          );
        }}
      </QueryView>
    </Page>
  );
}
