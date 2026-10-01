/** What the page shows while a cycle is running (or stopping): lanes, budgets, heartbeat and the trace. */
import "./activity.css";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useAgents, useCycles, useStopCycle } from "../../api/hooks";
import type { ActionResult, AgentInfo, CycleLive } from "../../api/types";
import { fmtDateTime, fmtUsd } from "../../lib/format";
import { Banner, Card, KeyValue, PageHeader, Section, links } from "../ui";
import { DefBadge, LiveAgo, reasonLabel, roleLabel } from "../Agents/shared";
import { Gauges } from "./Gauges";
import { HeartbeatValue, StaleHeartbeatBanner } from "./Heartbeat";
import { LaneList, summarizeLanes, withSkipped } from "./LaneList";
import { StopButton, StopDialog } from "./StopCycle";
import { TracePanel } from "./TracePanel";

function liveSentence(cycle: CycleLive): string {
  const lanes = withSkipped(cycle.lanes);
  const s = summarizeLanes(lanes);
  const running = lanes.find((l) => l.view === "running");
  const spend = cycle.gauges.find((g) => g.key === "anthropic_usd");
  const tests = cycle.gauges.find((g) => g.key === "experiments");
  if (cycle.state === "stopping") {
    return `A stop was requested for cycle ${cycle.cycle_id}. It ends before its next agent run${
      running ? `; the ${roleLabel(running.role).toLowerCase()} run in progress finishes first` : ""
    }.`;
  }
  const parts = [
    `Cycle ${cycle.cycle_id} is running${running ? `: the ${roleLabel(running.role).toLowerCase()} agent is working` : ""}.`,
    `${s.done} of ${s.total - s.skipped} agents have finished${s.skipped ? ` (${s.skipped} skipped)` : ""}.`,
  ];
  if (s.error) parts.push(`${s.error === 1 ? "One agent ended" : `${s.error} agents ended`} with an error.`);
  if (spend) parts.push(`Agent spend is ${fmtUsd(spend.used)} of ${fmtUsd(spend.cap)}.`);
  if (tests) parts.push(`${tests.used} of ${tests.cap} validation tests are used.`);
  return parts.join(" ");
}

export function LiveView({
  cycle,
  actionsEnabled,
  updatedAt,
  refreshFailed,
}: {
  cycle: CycleLive;
  actionsEnabled: boolean;
  updatedAt: string | null;
  refreshFailed: boolean;
}) {
  const agents = useAgents();
  const cycles = useCycles();
  const stop = useStopCycle();
  const [confirming, setConfirming] = useState(false);
  const [result, setResult] = useState<ActionResult | null>(null);

  const byRole: Record<string, AgentInfo> = Object.fromEntries((agents.data ?? []).map((a) => [a.role, a]));
  const reason = cycles.data?.find((c) => c.cycle_id === cycle.cycle_id)?.reason;
  const lanes = withSkipped(cycle.lanes);
  const s = summarizeLanes(lanes);
  const wall = cycle.gauges.find((g) => g.key === "wall_clock");
  const running = lanes.find((l) => l.view === "running");

  const submit = (why: string) =>
    stop.mutate(
      { cycle_id: cycle.cycle_id, reason: why },
      {
        onSuccess: (res) => {
          setResult(res);
          setConfirming(false);
        },
        onError: (err) => {
          const detail = (err as { detail?: string }).detail ?? err.message;
          setResult({ ok: false, message: `The stop request failed: ${detail}` });
          setConfirming(false);
        },
      },
    );

  return (
    <>
      <PageHeader
        eyebrow="Now"
        title="Live activity"
        summary={liveSentence(cycle)}
        meta={
          <>
            <span>Definition of default</span>
            <DefBadge version={cycle.definition_version} />
            {updatedAt && (
              <span>
                · updated <LiveAgo iso={updatedAt} />
              </span>
            )}
          </>
        }
        actions={<StopButton cycle={cycle} actionsEnabled={actionsEnabled} onClick={() => setConfirming(true)} />}
      />

      {refreshFailed && (
        <Banner tone="warn" title="Live updates are not reaching the server">
          <span className="small">The figures below are from the last successful update ({updatedAt ? <LiveAgo iso={updatedAt} /> : "earlier"}). The page keeps trying every 5 seconds.</span>
        </Banner>
      )}
      {cycle.state === "stopping" && (
        <Banner tone="warn" title="Stopping">
          <span className="small">
            A stop was requested. The cycle ends before its next agent run and is recorded as stopped by a person; the run in progress finishes first.
          </span>
        </Banner>
      )}
      {result && (
        <div role="status">
          <Banner tone={result.ok ? "good" : "warn"} title={result.ok ? "Stop requested" : "Stop not requested"}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="small">{result.message}</span>
              <button type="button" className="btn small" onClick={() => setResult(null)}>
                Dismiss
              </button>
            </div>
          </Banner>
        </div>
      )}
      <StaleHeartbeatBanner heartbeatAt={cycle.heartbeat_at} step={cycle.current_step} abandonAfterMin={wall ? wall.cap + 10 : null} />

      <Card>
        <KeyValue
          items={[
            ["Cycle", <Link key="c" className="mono" to={links.cycle(cycle.cycle_id)}>{cycle.cycle_id}</Link>],
            ["Why it started", reason ? reasonLabel(reason) : "—"],
            [
              "Started",
              <span key="s">
                <span title={fmtDateTime(cycle.started_at)}>
                  <LiveAgo iso={cycle.started_at} />
                </span>
                <span className="muted"> · {fmtDateTime(cycle.started_at)}</span>
              </span>,
            ],
            [
              "Current step",
              cycle.current_step && cycle.current_step !== "start" ? (
                <span key="step">
                  {roleLabel(cycle.current_step)}
                  {byRole[cycle.current_step] && <span className="mono muted"> · {byRole[cycle.current_step].model}</span>}
                </span>
              ) : (
                "Starting"
              ),
            ],
            ["Last heartbeat", <HeartbeatValue key="h" heartbeatAt={cycle.heartbeat_at} />],
          ]}
        />
      </Card>

      <Section title="Budgets for this cycle" note="Caps are set in the budget configuration and enforced by the orchestrator, not by the agents.">
        <Gauges gauges={cycle.gauges} />
      </Section>

      <Section
        title="Agents in run order"
        note={`${s.done} done · ${s.running} running · ${s.waiting} waiting${s.skipped ? ` · ${s.skipped} skipped` : ""}${s.error ? ` · ${s.error} with an error` : ""}. Turns and spend for a run are recorded when it ends.`}
      >
        <LaneList lanes={cycle.lanes} agents={byRole} />
      </Section>

      <Section
        title="Tool-call trace"
        note="The orchestrator writes the trace when each agent run ends, so the tool calls of a run in progress appear when it finishes. Expand an entry for its inputs and outputs."
      >
        <div className="activity-legend">
          <span>
            <strong className="kind-proposed">proposed</strong> an agent wrote or proposed something: a claim
          </span>
          <span>
            <strong className="kind-measured">measured</strong> a read-only lookup or a harness result such as training or evaluation
          </span>
          <span>
            <strong className="faint">system</strong> orchestration, such as the summary of an agent run
          </span>
        </div>
        <TracePanel trace={cycle.trace} />
      </Section>

      {confirming && (
        <StopDialog
          cycle={cycle}
          agent={running ? byRole[running.role] : undefined}
          busy={stop.isPending}
          onConfirm={submit}
          onCancel={() => setConfirming(false)}
        />
      )}
    </>
  );
}
