/**
 * Screen 15 — Approvals: what is waiting for a person, and what has people decided?
 *
 * The rule the whole console follows: agents propose, the harness judges, a person approves. The inbox lists what
 * waits; the history is the audit trail of every decision with who made it and why. Evidence and the action buttons
 * live on the evidence packet (the detail route).
 */
import { useApprovals, useStatus } from "../api/hooks";
import type { ApprovalsData } from "../api/types";
import { HistoryTable } from "../components/Approvals/HistoryTable";
import { WaitingList } from "../components/lists";
import { Updated } from "../components/Operate/Updated";
import { Banner, Card, Page, PageHeader, QueryView, Section } from "../components/ui";
import { fmtAgo } from "../lib/format";

function summarySentence(a: ApprovalsData): string {
  const n = a.pending.length;
  if (n === 0) {
    const last = a.history[0];
    const tail = last ? ` The last decision was ${last.decision === "approve" ? "an approval" : "a rejection"} by ${last.approver || "an unnamed approver"}, ${fmtAgo(last.ts)}.` : "";
    return `Nothing is waiting for a person.${tail}`;
  }
  const oldest = a.pending.reduce((min, p) => (p.created_at < min ? p.created_at : min), a.pending[0].created_at);
  return `${n} decision${n === 1 ? " is" : "s are"} waiting for a person; the oldest arrived ${fmtAgo(oldest)}. Nothing is promoted without a recorded human decision.`;
}

export default function Approvals() {
  const q = useApprovals();
  const status = useStatus();
  const enabled = status.data?.actions_enabled ?? q.data?.actions_enabled ?? false;
  return (
    <Page>
      <QueryView query={q} loadingHeight={320}>
        {(a) => (
          <>
            <PageHeader
              eyebrow="Decide and operate"
              title="Approvals"
              summary={summarySentence(a)}
              meta={<Updated at={q.dataUpdatedAt} />}
            />

            {enabled ? (
              <Banner tone="accent" title="Actions are enabled">
                Running the holdout gate, approving, rejecting and promoting are available on each evidence packet. A decision is recorded with your name
                {status.data?.user ? ` (${status.data.user})` : ""} and stays in the history below.
              </Banner>
            ) : (
              <Banner tone="neutral" title="Actions are disabled on this console">
                You can read every evidence packet, but running the gate, approving, rejecting and promoting are switched off. The console must be started with
                actions enabled, and the person acting is recorded by name.
              </Banner>
            )}

            <Section
              title="Waiting for a person"
              note="Agents propose, the harness judges, a person approves. A candidate appears here after it passed validation and has both a red-team and a compliance report. Approving never promotes by itself: the holdout gate, the decision and the promotion are three separate, confirmed steps."
            >
              <Card>
                <WaitingList items={a.pending} />
              </Card>
            </Section>

            <Section
              title="Decision history"
              note="Promotions and definition changes, newest first. Each record keeps the approver's name and rationale as it was written."
              right={<span className="small muted">{a.history.length} record{a.history.length === 1 ? "" : "s"}</span>}
            >
              <HistoryTable rows={a.history} />
            </Section>
          </>
        )}
      </QueryView>
    </Page>
  );
}
