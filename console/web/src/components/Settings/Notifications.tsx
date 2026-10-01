/** Notifications delivered by the mirrored console: desktop alerts for high alerts, waiting decisions, finished cycles. */
import { Link } from "react-router-dom";
import type { NotificationsInfo, Unavailable } from "../../api/types";
import { isUnavailable } from "../../api/types";
import { fmtDateTime } from "../../lib/format";
import { EmptyState, Pill, TimeAgo, UnavailableState } from "../ui";

export function notificationsTile(n: Unavailable | NotificationsInfo) {
  if (isUnavailable(n)) return { key: "notify", label: "Notifications", value: "Off", sub: "run the console with --mirror", tone: "neutral" as const };
  return {
    key: "notify",
    label: "Notifications",
    value: n.channel === "desktop" ? "Desktop" : "Log only",
    sub: `${n.recent.length} recent`,
    tone: "good" as const,
  };
}

export function Notifications({ n }: { n: Unavailable | NotificationsInfo }) {
  if (isUnavailable(n)) return <UnavailableState u={n} title="Notifications are off on this console" />;
  return (
    <div className="stack">
      <p className="small muted" style={{ margin: 0 }}>
        {n.channel === "desktop"
          ? "This console shows a desktop notification when a high alert is raised, a decision starts waiting for a person, a cycle finishes, or the improvement verdict changes. Job failures are also emailed by Databricks."
          : "This console records notifications here (desktop notifications need macOS). Job failures are emailed by Databricks."}
      </p>
      {n.recent.length === 0 ? (
        <EmptyState title="Nothing yet">New alerts, waiting decisions, finished cycles and verdict changes will appear here.</EmptyState>
      ) : (
        <ul className="list">
          {n.recent.map((x) => (
            <li key={`${x.kind}-${x.id}-${x.ts}`} className="item row between">
              <span className="stack" style={{ gap: 2 }}>
                <Link to={x.href}>
                  <strong>{x.title}</strong>
                </Link>
                <span className="small">{x.body}</span>
              </span>
              <span className="row" style={{ gap: 8 }}>
                <span className="xs muted" title={fmtDateTime(x.ts)}>
                  <TimeAgo iso={x.ts} />
                </span>
                <Pill tone={x.delivered ? "good" : "neutral"}>{x.delivered ? "shown" : "logged"}</Pill>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
