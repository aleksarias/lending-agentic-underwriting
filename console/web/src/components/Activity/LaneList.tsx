/** One lane per agent role, in the order the orchestrator runs them. */
import "./activity.css";
import type { AgentInfo, AgentLane } from "../../api/types";
import { fmtDateTime, fmtSeconds, fmtUsd } from "../../lib/format";
import { Card, Meter, Pill } from "../ui";
import { fmtClock, roleLabel } from "../Agents/shared";

export type LaneView = AgentLane["state"] | "skipped";
export type ViewLane = AgentLane & { view: LaneView };

/**
 * The orchestrator runs roles in a fixed order and skips some of them (the profiler is optional; red team and
 * compliance only run when a challenger is proposed). A role that is still pending after a later role has started
 * was therefore skipped, not delayed.
 */
export function withSkipped(lanes: AgentLane[]): ViewLane[] {
  const lastStarted = lanes.reduce((acc, l, i) => (l.state !== "pending" ? i : acc), -1);
  return lanes.map((l, i) => ({ ...l, view: l.state === "pending" && i < lastStarted ? "skipped" : l.state }));
}

const STATE_PILL: Record<LaneView, { label: string; tone: "good" | "warn" | "crit" | "neutral" | "accent"; title: string }> = {
  pending: { label: "Waiting", tone: "neutral", title: "Has not started; earlier agents are still working" },
  running: { label: "Running", tone: "accent", title: "Working now" },
  done: { label: "Done", tone: "good", title: "Finished its run" },
  error: { label: "Error", tone: "crit", title: "Its run ended with an error" },
  skipped: { label: "Skipped", tone: "neutral", title: "Not run in this cycle: a later agent has already started" },
};

export function summarizeLanes(lanes: ViewLane[]) {
  const count = (v: LaneView) => lanes.filter((l) => l.view === v).length;
  return { done: count("done"), running: count("running"), error: count("error"), skipped: count("skipped"), waiting: count("pending"), total: lanes.length };
}

function seconds(a: string, b: string) {
  return (new Date(b).getTime() - new Date(a).getTime()) / 1000;
}

function LaneTimes({ lane }: { lane: ViewLane }) {
  return (
    <div className="activity-lane-times">
      {lane.view === "pending" && <span>Waiting for the agents before it</span>}
      {lane.view === "skipped" && <span>Not run in this cycle</span>}
      {lane.started_at && (
        <span title={fmtDateTime(lane.started_at)}>
          Started <span className="num">{fmtClock(lane.started_at)}</span> UTC
        </span>
      )}
      {lane.finished_at && (
        <span title={fmtDateTime(lane.finished_at)}>
          {lane.view === "error" ? "Ended with an error" : "Finished"} <span className="num">{fmtClock(lane.finished_at)}</span> UTC
          {lane.started_at ? <span className="num"> · {fmtSeconds(seconds(lane.started_at, lane.finished_at))}</span> : null}
        </span>
      )}
      {lane.view === "running" && <span>Turns and spend are counted when this run ends</span>}
    </div>
  );
}

export function LaneList({ lanes, agents }: { lanes: AgentLane[]; agents: Record<string, AgentInfo> }) {
  const view = withSkipped(lanes);
  return (
    <Card flush kind="measured">
      <ol className="activity-lanes">
        {view.map((l, i) => {
          const pill = STATE_PILL[l.view];
          const model = agents[l.role]?.model;
          return (
            <li key={l.role} className={`activity-lane ${l.view}`}>
              <div className="activity-lane-name">
                <span className="activity-lane-step" aria-hidden>
                  {i + 1}
                </span>
                <strong>{roleLabel(l.role)}</strong>
                <span title={pill.title}>
                  <Pill tone={pill.tone} dot={l.view === "running"}>
                    {pill.label}
                  </Pill>
                </span>
                {model && <span className="xs muted mono" style={{ flexBasis: "100%", paddingLeft: 30 }}>{model}</span>}
              </div>
              <div className="activity-lane-meters">
                <Meter label="Turns" used={l.turns} cap={l.max_turns} />
              </div>
              <div className="activity-lane-meters">
                <Meter label="Spend" used={l.cost_usd} cap={l.max_cost_usd} format={(v) => fmtUsd(v)} />
              </div>
              <LaneTimes lane={l} />
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
