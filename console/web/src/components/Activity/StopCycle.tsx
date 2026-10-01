/** Stop-cycle control: the button (enabled only when the console allows actions) and its confirmation dialog. */
import type { AgentInfo, CycleLive } from "../../api/types";
import { fmtUsd } from "../../lib/format";
import { ConfirmDialog } from "../ui";
import { roleLabel } from "../Agents/shared";

export const ACTIONS_DISABLED = "Actions are disabled on this console";

export function StopButton({ cycle, actionsEnabled, onClick }: { cycle: CycleLive; actionsEnabled: boolean; onClick: () => void }) {
  const stopping = cycle.state === "stopping";
  const why = stopping ? "A stop has already been requested for this cycle" : !actionsEnabled ? ACTIONS_DISABLED : null;
  return (
    <span className="row" style={{ gap: 8 }}>
      <span title={why ?? undefined}>
        <button type="button" className="btn danger" disabled={why !== null} onClick={onClick} title={why ?? undefined}>
          Stop cycle
        </button>
      </span>
      {why && <span className="xs muted">{why}</span>}
    </span>
  );
}

export function StopDialog({
  cycle,
  agent,
  busy,
  onConfirm,
  onCancel,
}: {
  cycle: CycleLive;
  agent: AgentInfo | undefined;
  busy: boolean;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}) {
  const lane = cycle.lanes.find((l) => l.state === "running");
  const limits = lane
    ? `${lane.max_turns} turns, ${fmtUsd(lane.max_cost_usd)}${agent ? ` and ${agent.caps.timeout_min} minutes` : ""}`
    : null;
  return (
    <ConfirmDialog
      open
      danger
      title={`Stop cycle ${cycle.cycle_id}?`}
      confirmLabel="Stop the cycle"
      requireText={{ label: "Reason (saved with the stop request, at least 10 characters)", minLength: 10 }}
      busy={busy}
      onConfirm={onConfirm}
      onCancel={onCancel}
    >
      <p style={{ margin: "0 0 6px" }}>This does not interrupt the agent that is working now. Exactly what happens:</p>
      <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 4 }}>
        <li>
          The cycle stops before its next agent run.
          {lane ? ` The ${roleLabel(lane.role).toLowerCase()} run in progress finishes first, within its own limits (${limits}).` : " Nothing is running at this moment."}
        </li>
        <li>Everything recorded so far is kept: the trace, proposed features, trained candidates and reports. The cycle ends as stopped by a person.</li>
        <li>Nothing is promoted, approved or rolled back. Spend stops growing once the current run ends.</li>
      </ul>
    </ConfirmDialog>
  );
}
