/**
 * Heartbeat of the running cycle. The orchestrator writes one when the cycle starts and when each agent run starts
 * or ends, so the age can legitimately grow during a long agent run. Older than two minutes is shown as a warning;
 * the console itself treats a cycle as abandoned after the wall-clock cap plus ten minutes without one.
 */
import { fmtAgo, fmtDateTime } from "../../lib/format";
import { Banner, Pill } from "../ui";
import { roleLabel, useNow } from "../Agents/shared";

export const STALE_AFTER_S = 120;

const ageSeconds = (iso: string, now: number) => (now - new Date(iso).getTime()) / 1000;

export function HeartbeatValue({ heartbeatAt }: { heartbeatAt: string | null }) {
  const now = useNow(1000);
  if (!heartbeatAt) return <span className="muted">none recorded yet</span>;
  const stale = ageSeconds(heartbeatAt, now) > STALE_AFTER_S;
  return (
    <span className="row" style={{ gap: 8 }}>
      <span className="num" title={fmtDateTime(heartbeatAt)}>
        {fmtAgo(heartbeatAt, now)}
      </span>
      {stale ? <Pill tone="warn">Stale: over 2 minutes</Pill> : <Pill tone="good">Within 2 minutes</Pill>}
    </span>
  );
}

export function StaleHeartbeatBanner({ heartbeatAt, step, abandonAfterMin }: { heartbeatAt: string | null; step: string | null; abandonAfterMin: number | null }) {
  const now = useNow(1000);
  if (!heartbeatAt || ageSeconds(heartbeatAt, now) <= STALE_AFTER_S) return null;
  const what = !step || step === "start" ? "the start of the cycle" : `the ${roleLabel(step).toLowerCase()} agent`;
  return (
    <Banner tone="warn" title={`Last heartbeat ${fmtAgo(heartbeatAt, now)}`}>
      <span className="small">
        The last heartbeat was for {what}. Heartbeats are written when a cycle starts and when each agent run starts or ends, so a long agent run
        can be quiet.
        {abandonAfterMin != null && ` If none arrives for ${abandonAfterMin} minutes (the wall-clock cap plus 10), the console treats the cycle as abandoned.`}
      </span>
    </Banner>
  );
}
