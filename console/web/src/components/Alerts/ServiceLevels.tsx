/**
 * Service levels and notifications: the alert sources beyond model monitoring. Each needs something that is not built yet,
 * so each says what it is waiting for instead of showing an empty chart.
 */
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { SettingsData, StatusSummary } from "../../api/types";
import { isUnavailable } from "../../api/types";
import { fmtPct } from "../../lib/format";
import { Card, Pill } from "../ui";

function Row({ title, pill, children, link }: { title: string; pill: ReactNode; children: ReactNode; link?: { to: string; label: string } }) {
  return (
    <li className="item stack" style={{ gap: 4 }}>
      <div className="row between">
        <strong className="small">{title}</strong>
        <span className="row" style={{ gap: 8 }}>
          {pill}
          {link && (
            <Link className="small" to={link.to}>
              {link.label}
            </Link>
          )}
        </span>
      </div>
      <div className="xs muted">{children}</div>
    </li>
  );
}

export function ServiceLevels({ status, notifications }: { status: StatusSummary | undefined; notifications: SettingsData["notifications"] | undefined }) {
  const note: unknown = notifications;
  return (
    <Card>
      <ul className="list">
        <Row
          title="Decision API"
          link={{ to: "/decisions", label: "Decisions" }}
          pill={!status ? <Pill>Unknown</Pill> : status.api.live ? <Pill tone="good">Live</Pill> : <Pill>Not live</Pill>}
        >
          {!status
            ? "The console status could not be loaded."
            : status.api.live
            ? `99th-percentile latency ${status.api.p99_ms != null ? `${status.api.p99_ms} ms` : "not reported"}; fallback rate ${status.api.fallback_rate != null ? fmtPct(status.api.fallback_rate, 1) : "not reported"}.`
            : "Latency, error and fallback alerts begin when the real-time decision API is deployed. Until then there is no service to measure."}
        </Row>
        <Row
          title="Loan status feed"
          link={{ to: "/feed", label: "Loan status feed" }}
          pill={!status ? <Pill>Unknown</Pill> : status.feed.live ? <Pill tone="good">Live</Pill> : <Pill>Not connected</Pill>}
        >
          {!status
            ? "The console status could not be loaded."
            : status.feed.live
            ? `Latest status received ${status.feed.last_received_at ?? "at an unknown time"}.`
            : "Late-file and failed-check alerts begin when the servicing feed is connected. Performance currently arrives as batch data versions."}
        </Row>
        <Row
          title="Notifications"
          pill={note === undefined ? <Pill>Unknown</Pill> : isUnavailable(note) ? <Pill>Not set up</Pill> : <Pill tone="good">Set up</Pill>}
        >
          {note === undefined ? (
            "The notification settings could not be loaded."
          ) : isUnavailable(note) ? (
            <>
              {note.reason}
              {note.requires.length > 0 && <> Needs: {note.requires.join(" · ")}.</>}
            </>
          ) : (
            "Notification routing is configured."
          )}
        </Row>
      </ul>
    </Card>
  );
}
