/** What the page shows when no cycle is running: the last cycle, what is queued and pipeline freshness. */
import "./activity.css";
import { Link } from "react-router-dom";
import { useUpcoming } from "../../api/hooks";
import type { ActivityData, CycleSummary, QueueItem, StatusSummary } from "../../api/types";
import { fmtAgo, fmtDateTime, fmtUsd, refLabel, titleCase } from "../../lib/format";
import { StageList } from "../lists";
import { Banner, Card, EmptyState, KeyValue, KindTag, PageHeader, Pill, Section, TimeAgo, links } from "../ui";
import { DefBadge, LiveAgo, VerdictPill, cycleStatus, reasonLabel } from "../Agents/shared";

function idleSentence(last: CycleSummary | null, queued: number | null, rebuilding: StatusSummary["activity"] | null): string {
  const parts = ["No improvement cycle is running."];
  if (rebuilding) parts.push(`The pipeline is rebuilding (${rebuilding.step ? titleCase(rebuilding.step) : "a stage"}).`);
  if (last) {
    const st = cycleStatus(last.status).label.toLowerCase();
    parts.push(`The last cycle, ${last.cycle_id}, started ${fmtAgo(last.started_at)} and ${st === "completed" ? "completed" : `ended as: ${st}`}.`);
    if (last.challenger) {
      const v = last.challenger_passed_validation;
      parts.push(`Its challenger, ${refLabel(`candidate:${last.challenger}`)}, ${v == null ? "has no recorded validation result" : v ? "passed validation" : "did not pass validation"}.`);
    } else if (last.status === "completed") {
      parts.push("It proposed no challenger.");
    }
  } else {
    parts.push("No cycle has run yet.");
  }
  if (queued) parts.push(`${queued} cycle${queued === 1 ? " is" : "s are"} queued.`);
  return parts.join(" ");
}

function LastCycleCard({ c }: { c: CycleSummary }) {
  const st = cycleStatus(c.status);
  return (
    <Card title="Last cycle">
      <div className="row between" style={{ marginBottom: 8 }}>
        <Link className="mono" to={links.cycle(c.cycle_id)}>
          <strong>{c.cycle_id}</strong>
        </Link>
        <Pill tone={st.tone}>{st.label}</Pill>
      </div>
      <KeyValue
        items={[
          [
            "Started",
            <span key="s" title={fmtDateTime(c.started_at)}>
              <TimeAgo iso={c.started_at} /> · {fmtDateTime(c.started_at)}
            </span>,
          ],
          ["Why it ran", reasonLabel(c.reason)],
          ["Definition of default", <DefBadge key="d" version={c.definition_version} />],
          ["Agent spend", c.anthropic_usd == null ? "—" : fmtUsd(c.anthropic_usd)],
          ["Validation tests used", c.experiments_used ?? "—"],
          [
            "Challenger",
            c.challenger ? (
              <Link key="ch" to={links.approval(`candidate:${c.challenger}`)}>
                {refLabel(`candidate:${c.challenger}`)}
              </Link>
            ) : (
              "none proposed"
            ),
          ],
          [
            "Validation",
            c.challenger_passed_validation == null ? (
              "—"
            ) : (
              <span key="v" className="row" style={{ gap: 6 }}>
                <Pill tone={c.challenger_passed_validation ? "good" : "warn"}>{c.challenger_passed_validation ? "passed" : "did not pass"}</Pill>
                <KindTag kind="measured" />
              </span>
            ),
          ],
          [
            "Red team",
            <span key="r" className="row" style={{ gap: 6 }}>
              <VerdictPill verdict={c.redteam_verdict} />
              {c.redteam_verdict && <KindTag kind="proposed" />}
            </span>,
          ],
          [
            "Compliance",
            <span key="co" className="row" style={{ gap: 6 }}>
              <VerdictPill verdict={c.compliance_verdict} />
              {c.compliance_verdict && <KindTag kind="proposed" />}
            </span>,
          ],
          ...(c.stop_reason ? ([["Stop reason", c.stop_reason]] as [string, string][]) : []),
        ]}
      />
      <div className="small" style={{ marginTop: 10 }}>
        <Link to={links.cycle(c.cycle_id)}>Open this cycle</Link>
      </div>
    </Card>
  );
}

function QueueCard({ queue }: { queue: QueueItem[] | null; }) {
  const queued = queue?.filter((q) => q.status === "queued") ?? [];
  return (
    <Card title="Queued cycles">
      {queue === null ? (
        <div className="small muted">The queue could not be loaded.</div>
      ) : queued.length === 0 ? (
        <div className="small">Nothing is queued. A cycle is requested after a high-severity monitoring alert or a definition change.</div>
      ) : (
        <ul className="list">
          {queued.map((q) => (
            <li key={q.requested_at} className="item stack" style={{ gap: 4 }}>
              <div className="row between">
                <strong>{reasonLabel(q.reason)}</strong>
                <span className="xs muted">
                  requested <TimeAgo iso={q.requested_at} />
                </span>
              </div>
              <DefBadge version={q.definition_version} />
            </li>
          ))}
        </ul>
      )}
      <div className="small" style={{ marginTop: 10 }}>
        {queued.length > 0 && "A queued request does not start a cycle by itself; a person starts it from the command line. "}
        <Link to="/upcoming">See what happens next</Link>
      </div>
    </Card>
  );
}

export function IdleView({
  data,
  status,
  updatedAt,
  refreshFailed,
}: {
  data: ActivityData;
  status: StatusSummary | undefined;
  updatedAt: string | null;
  refreshFailed: boolean;
}) {
  const upcoming = useUpcoming();
  const queue = upcoming.data?.queue ?? null;
  const queuedCount = queue?.filter((q) => q.status === "queued").length ?? null;
  const rebuilding = status?.activity.state === "pipeline_rebuilding" ? status.activity : null;
  const stale = data.pipeline.filter((s) => s.status !== "fresh").length;
  const last = data.last_cycle;
  return (
    <>
      <PageHeader
        eyebrow="Now"
        title="Live activity"
        summary={idleSentence(last, queuedCount, rebuilding)}
        meta={
          <>
            {status?.active_definition && (
              <>
                <span>Definition of default</span>
                <DefBadge version={status.active_definition.version} />
              </>
            )}
            {updatedAt && (
              <span>
                · updated <LiveAgo iso={updatedAt} />
              </span>
            )}
          </>
        }
      />
      {refreshFailed && (
        <Banner tone="warn" title="Live updates are not reaching the server">
          <span className="small">The page keeps trying every 5 seconds.</span>
        </Banner>
      )}
      {rebuilding ? (
        <Banner tone="accent" title={`The pipeline is rebuilding: ${rebuilding.step ? titleCase(rebuilding.step) : "a stage"}`}>
          <span className="small">
            It started <TimeAgo iso={rebuilding.since} />. Stages light up below as they finish; a stage that is running shows as stale with the reason "rebuilding now".
          </span>
        </Banner>
      ) : (
        <Banner tone="neutral" title="No cycle is running">
          <span className="small">
            Agent lanes, budget gauges and the tool-call trace appear here while a cycle runs. Cycles start from the command line (<code>lau run-cycle</code>) or
            from the weekly job once it is resumed.
          </span>
        </Banner>
      )}
      {last?.status === "abandoned" && (
        <Banner tone="warn" title={`Cycle ${last.cycle_id} is marked abandoned`}>
          <span className="small">It stopped sending heartbeats and never recorded a result. Check the process that ran it before starting another cycle.</span>
        </Banner>
      )}

      <div className="grid split">
        {last ? (
          <LastCycleCard c={last} />
        ) : (
          <EmptyState title="No cycle has run yet">Run <code>lau run-cycle</code> to start the first improvement cycle. Its summary appears here afterwards.</EmptyState>
        )}
        <QueueCard queue={queue} />
      </div>

      <Section
        title="Pipeline freshness"
        note="Each stage for the active definition. A stage is stale when the definition or configuration changed after it last ran."
        right={<span className="small muted">{stale ? `${stale} of ${data.pipeline.length} stages not fresh` : "all stages fresh"}</span>}
      >
        <Card>
          <StageList stages={data.pipeline} />
        </Card>
      </Section>
    </>
  );
}
