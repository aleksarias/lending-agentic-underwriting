/** "What happens next": the answer banner, the cycle queue and the declared job schedules. */
import { Link } from "react-router-dom";
import type { JobInfo, QueueItem, StatusSummary, UpcomingData } from "../../api/types";
import { isUnavailable } from "../../api/types";
import { fmtAgo, fmtDateTime, titleCase } from "../../lib/format";
import { Banner, Card, DataTable, EmptyState, Pill, TimeAgo, UnavailableState } from "../ui";
import { DefBadge, reasonLabel } from "../Agents/shared";

/** What each declared job does, from its entry point in src/lau/jobs.py. Unknown jobs simply show no description. */
const JOB_INFO: Record<string, string> = {
  "lau-definition-sync": "Detects a changed default-definition file and applies it only if a person has recorded an approval for that exact definition; otherwise it fails.",
  "lau-shadow-scoring": "Scores new applications with the challenger, next to the serving model if there is one, with no effect on any decision.",
  "lau-evidence": "Refreshes the evidence: re-scores every model on the same recent loans, then recomputes the improvement verdict, vintage curves and proxy scan.",
  "lau-monitoring": "Checks score and feature drift (PSI) and early and final outcomes against the baseline. A high-severity alert queues an improvement cycle.",
  "lau-improvement-cycle": "Runs one improvement cycle when the queue has work; does nothing when it is empty.",
};

export const queuedOf = (queue: QueueItem[]) => queue.filter((q) => q.status === "queued");

export function jobsOf(u: UpcomingData): JobInfo[] | null {
  return isUnavailable(u.jobs) ? null : u.jobs;
}

// --------------------------------------------------------------------------------------------------- summary
export function upcomingSentence(u: UpcomingData, status: StatusSummary | undefined): string {
  const parts: string[] = [];
  const running = status?.activity.state === "cycle_running";
  const queued = queuedOf(u.queue);
  const jobs = jobsOf(u);
  if (running) parts.push("An improvement cycle is running now.");
  if (jobs === null) parts.push("The job schedule is not available.");
  else if (jobs.length === 0) parts.push("No scheduled jobs are declared.");
  else {
    const paused = jobs.filter((j) => j.paused).length;
    parts.push(paused === jobs.length ? `Nothing runs on a schedule: all ${jobs.length} scheduled jobs are paused.` : `${jobs.length - paused} of ${jobs.length} scheduled jobs are active.`);
  }
  const cycleJob = jobs?.find((j) => j.name.includes("improvement-cycle"));
  if (queued.length && running) {
    parts.push(`${queued.length} queued request${queued.length === 1 ? "" : "s"} (${reasonLabel(queued[0].reason).toLowerCase()}) will be marked done when a cycle under the same definition ends.`);
  } else if (queued.length) {
    const many = queued.length > 1;
    const start =
      cycleJob && !cycleJob.paused ? `will start with the next run of the ${(cycleJob.schedule ?? "scheduled").toLowerCase()} cycle job` : `${many ? "are" : "is"} waiting for a person to start ${many ? "them" : "it"}`;
    parts.push(`${queued.length} improvement cycle${many ? "s are" : " is"} queued (${reasonLabel(queued[0].reason).toLowerCase()}) and ${start}.`);
  } else if (!running) {
    parts.push("No cycle is queued.");
  }
  if (u.waiting.length) parts.push(`${u.waiting.length} decision${u.waiting.length === 1 ? " is" : "s are"} waiting for a person.`);
  return parts.join(" ");
}

// ---------------------------------------------------------------------------------------------------- banner
export function NextBanner({ u, status }: { u: UpcomingData; status: StatusSummary | undefined }) {
  const queued = queuedOf(u.queue);
  const running = status?.activity.state === "cycle_running";
  const jobs = jobsOf(u);
  const cycleJob = jobs?.find((j) => j.name.includes("improvement-cycle"));
  const next = queued[0];
  const cli = <code>lau run-cycle</code>;
  if (running) {
    return (
      <Banner tone="accent" title="A cycle is running now">
        <span className="small">
          <Link to="/activity">Live activity</Link> shows its agents, budgets and trace.
          {queued.length > 0 && ` A queued request stays queued until a cycle under the same definition ends, so the ${queued.length} below may be served by this one.`}
        </span>
      </Banner>
    );
  }
  if (next) {
    return (
      <Banner tone="accent" title={`Next: ${queued.length === 1 ? "an improvement cycle is" : `${queued.length} improvement cycles are`} queued`}>
        <span className="small">
          The latest request came {fmtAgo(next.requested_at)} from <strong>{reasonLabel(next.reason).toLowerCase()}</strong>
          {next.reason === "monitoring_alert" && (
            <>
              {" "}
              (see <Link to="/alerts">Alerts</Link>)
            </>
          )}
          .{" "}
          {cycleJob?.paused ? (
            <>
              Nothing starts it by itself because the {cycleJob.name} job is paused: a person runs {cli}, or resumes the job in Databricks.
            </>
          ) : cycleJob ? (
            <>It starts with the next run of the {cycleJob.name} job ({cycleJob.schedule ?? "scheduled"}), or when a person runs {cli}.</>
          ) : (
            <>A person starts it with {cli}.</>
          )}
        </span>
      </Banner>
    );
  }
  return (
    <Banner tone="neutral" title="Nothing is queued">
      <span className="small">
        A cycle is requested after a high-severity monitoring alert or when a definition change is applied; a person can also run {cli} at any time.
      </span>
    </Banner>
  );
}

// ----------------------------------------------------------------------------------------------------- queue
export function QueueTable({ queue }: { queue: QueueItem[] }) {
  return (
    <Card flush>
      <DataTable
        rows={queue}
        rowKey={(q) => `${q.requested_at}-${q.reason}-${q.definition_version}`}
        empty={<EmptyState title="The queue is empty">Requests are added when monitoring raises a high-severity alert or a definition change is applied.</EmptyState>}
        columns={[
          {
            key: "requested",
            header: "Requested",
            render: (q) => (
              <span title={fmtDateTime(q.requested_at)}>
                <span className="nowrap">{fmtDateTime(q.requested_at)}</span> <span className="xs muted">(<TimeAgo iso={q.requested_at} />)</span>
              </span>
            ),
            sort: (q) => q.requested_at,
          },
          {
            key: "reason",
            header: "Reason",
            render: (q) => (q.reason === "monitoring_alert" ? <Link to="/alerts">{reasonLabel(q.reason)}</Link> : reasonLabel(q.reason)),
            sort: (q) => reasonLabel(q.reason),
          },
          { key: "definition", header: "Definition of default", render: (q) => <DefBadge version={q.definition_version} /> },
          {
            key: "status",
            header: "Status",
            render: (q) => <Pill tone={q.status === "queued" ? "accent" : "neutral"}>{q.status === "queued" ? "Queued" : titleCase(q.status)}</Pill>,
            sort: (q) => q.status,
          },
        ]}
        initialSort={{ key: "requested", dir: "desc" }}
      />
    </Card>
  );
}

// ------------------------------------------------------------------------------------------------------ jobs
export function JobsTable({ jobs }: { jobs: JobInfo[] | UpcomingData["jobs"] }) {
  if (isUnavailable(jobs)) return <UnavailableState u={jobs} title="Job schedules are not available" />;
  const anyRun = jobs.some((j) => j.last_run_at || j.last_result);
  return (
    <Card flush>
      <DataTable
        rows={jobs}
        rowKey={(j) => j.name}
        empty={<EmptyState title="No scheduled jobs are declared">The Asset Bundle (resources/jobs.yml) declares none, or it could not be read.</EmptyState>}
        columns={[
          { key: "name", header: "Job", render: (j) => <span className="mono nowrap">{j.name}</span>, sort: (j) => j.name },
          { key: "what", header: "What it does", render: (j) => <span className="small">{JOB_INFO[j.name] ?? "—"}</span> },
          { key: "schedule", header: "Schedule", render: (j) => j.schedule ?? "—", sort: (j) => j.schedule },
          {
            key: "state",
            header: "State",
            render: (j) => <Pill tone={j.paused ? "neutral" : "good"}>{j.paused ? "Paused" : "Active"}</Pill>,
            sort: (j) => (j.paused ? 1 : 0),
          },
          {
            key: "next",
            header: "Next run",
            render: (j) => (j.next_run_at ? <TimeAgo iso={j.next_run_at} /> : <span className="muted">{j.paused ? "Not scheduled" : "Unknown"}</span>),
          },
          ...(anyRun
            ? [
                {
                  key: "last",
                  header: "Last run",
                  render: (j: JobInfo) => (j.last_run_at ? <span><TimeAgo iso={j.last_run_at} />{j.last_result ? ` · ${j.last_result}` : ""}</span> : <span className="muted">—</span>),
                },
              ]
            : []),
        ]}
      />
    </Card>
  );
}
