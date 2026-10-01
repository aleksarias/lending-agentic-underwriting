/**
 * Screen 2 — Live activity. Answers: is a cycle running, which agent is working, what has it spent and done, and can a
 * person stop it? Polls every 5 seconds. A running cycle shows lanes, budget gauges, heartbeat and the tool-call
 * trace; otherwise the page shows the last cycle, what is queued and pipeline freshness.
 */
import { useActivity, useStatus } from "../api/hooks";
import { IdleView } from "../components/Activity/IdleView";
import { LiveView } from "../components/Activity/LiveView";
import { ErrorState, Loading, Page } from "../components/ui";

export default function Activity() {
  const q = useActivity();
  const status = useStatus();
  if (!q.data) {
    return <Page>{q.isError ? <ErrorState error={q.error} /> : <Loading height={360} />}</Page>;
  }
  const updatedAt = q.dataUpdatedAt ? new Date(q.dataUpdatedAt).toISOString() : null;
  // A failed refresh keeps the last good data on screen and says so, instead of replacing a live page with an error box.
  const refreshFailed = q.isError;
  return (
    <Page>
      {q.data.cycle ? (
        <LiveView cycle={q.data.cycle} actionsEnabled={status.data?.actions_enabled ?? false} updatedAt={updatedAt} refreshFailed={refreshFailed} />
      ) : (
        <IdleView data={q.data} status={status.data} updatedAt={updatedAt} refreshFailed={refreshFailed} />
      )}
    </Page>
  );
}
