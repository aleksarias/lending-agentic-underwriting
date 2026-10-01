/**
 * Screen 7 — Upcoming. Answers: what will the system do next, and what is waiting on a person?
 * The queue and the plan come from ops tables and the planner's latest output. Jobs are the schedules declared in the
 * Databricks Asset Bundle (the console cannot read the Jobs API), so they are labelled as declared, not observed.
 */
import { Link } from "react-router-dom";
import { useStatus, useUpcoming } from "../api/hooks";
import { WaitingList } from "../components/lists";
import { Backlog, ForecastTiles, PlanPreview } from "../components/Upcoming/Outlook";
import { JobsTable, NextBanner, QueueTable, upcomingSentence } from "../components/Upcoming/NextUp";
import { Card, DefinitionBadge, Page, PageHeader, QueryView, Section } from "../components/ui";

export default function Upcoming() {
  const q = useUpcoming();
  const status = useStatus();
  return (
    <Page>
      <QueryView query={q} loadingHeight={360}>
        {(u) => (
          <>
            <PageHeader
              eyebrow="Next"
              title="Upcoming"
              summary={upcomingSentence(u, status.data)}
              meta={
                <>
                  <span>Definition of default</span>
                  <DefinitionBadge def={status.data?.active_definition} />
                </>
              }
            />

            <NextBanner u={u} status={status.data} />

            <Section
              title="Cycle queue"
              note="Why each improvement cycle was requested. A request stays queued until a cycle finishes under the same definition."
            >
              <QueueTable queue={u.queue} />
            </Section>

            <Section
              title="Waiting for a person"
              right={
                <Link className="small" to="/approvals">
                  All approvals
                </Link>
              }
            >
              <Card>
                <WaitingList items={u.waiting} />
              </Card>
            </Section>

            <Section
              title="Scheduled jobs"
              note={
                <>
                  These are the schedules declared in the Databricks Asset Bundle (<code>resources/jobs.yml</code>). The bundle deploys every job paused, and the console's
                  read-only identity cannot query the Databricks Jobs API, so no next run is scheduled and run history is not shown here.
                </>
              }
            >
              <JobsTable jobs={u.jobs} />
            </Section>

            <Section title="Forecast" note="Budget and testing headroom under the active definition.">
              <ForecastTiles f={u.forecast} status={status.data} />
            </Section>

            <Section
              title="Next plan preview"
              note="A preview, not a commitment. The planner writes a new plan at the start of every cycle and the orchestrator caps what it submits; this is the most recent plan it submitted."
            >
              <PlanPreview plan={u.next_plan} cycleId={u.next_plan_cycle_id} />
            </Section>

            <Section
              title="Hypothesis backlog"
              note="Open questions the next cycles can take up: features an agent proposed that no candidate model has used yet, and lessons carried over from an earlier definition of default that still need re-checking under the active one. These are agent proposals, not results."
            >
              <Backlog backlog={u.backlog} />
            </Section>
          </>
        )}
      </QueryView>
    </Page>
  );
}
