/** Red-team and compliance reports. Agents wrote them, so they are proposed claims, not measurements. */
import { Link } from "react-router-dom";
import type { ReportMeta } from "../../api/types";
import { fmtDateTime, reviewTone } from "../../lib/format";
import { Card, KindTag, Pill, Section, TimeAgo, links } from "../ui";

const ROLES = [
  { kind: "redteam", label: "Red team", what: "An agent that tries to find weaknesses the harness checks do not cover." },
  { kind: "compliance", label: "Compliance", what: "An agent that reviews fair lending and adverse-action readiness." },
] as const;

function ReportRow({ r }: { r: ReportMeta }) {
  return (
    <li className="item stack" style={{ gap: 4 }}>
      <div className="row between">
        <Link to={links.report(r.report_id)}>
          <strong>{r.title}</strong>
        </Link>
        <Pill tone={reviewTone(r.verdict)}>{r.verdict ? `Verdict: ${r.verdict}` : "No verdict"}</Pill>
      </div>
      <div className="xs muted row" style={{ gap: 10 }}>
        <span title={fmtDateTime(r.created_at)}>
          written <TimeAgo iso={r.created_at} />
        </span>
        <span>
          cycle <Link to={links.cycle(r.cycle_id)} className="mono">{r.cycle_id}</Link>
        </span>
      </div>
    </li>
  );
}

export function ReportsSection({ reports }: { reports: ReportMeta[] }) {
  const byNewest = [...reports].sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
  const other = byNewest.filter((r) => !ROLES.some((x) => x.kind === r.kind));
  return (
    <Section
      title="Red-team and compliance reports"
      right={<KindTag kind="proposed" />}
      note="Written by agents. The harness has not verified what they say, so read them before deciding. A compliance verdict of block stops promotion."
    >
      <div className="stack" style={{ gap: "var(--gap)" }}>
        {ROLES.map((role) => {
          const mine = byNewest.filter((r) => r.kind === role.kind);
          return (
            <Card key={role.kind} kind="proposed" title={role.label}>
              <div className="xs muted" style={{ marginBottom: 6 }}>
                {role.what}
              </div>
              {mine.length ? (
                <ul className="list">
                  {mine.map((r) => (
                    <ReportRow key={r.report_id} r={r} />
                  ))}
                </ul>
              ) : (
                <div className="row">
                  <Pill tone="warn">Missing</Pill>
                  <span className="small">No {role.label.toLowerCase()} report for this candidate yet, so it cannot be promoted.</span>
                </div>
              )}
            </Card>
          );
        })}
        {other.length > 0 && (
          <Card kind="proposed" title="Other reports">
            <ul className="list">
              {other.map((r) => (
                <ReportRow key={r.report_id} r={r} />
              ))}
            </ul>
          </Card>
        )}
      </div>
    </Section>
  );
}
