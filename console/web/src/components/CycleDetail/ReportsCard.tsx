/** Reports the agents wrote in this cycle. Agent output, so the card is marked proposed. */
import { Link } from "react-router-dom";
import type { ReportMeta } from "../../api/types";
import { fmtDateTime, refLabel, reviewTone, titleCase } from "../../lib/format";
import { Card, EmptyState, KindTag, Pill, links } from "../ui";
import { agentLabel } from "./cycle";

export function ReportsCard({ reports }: { reports: ReportMeta[] }) {
  if (reports.length === 0) {
    return (
      <EmptyState title="No agent reports were written in this cycle">
        Agents write a report when they finish: research notes from the feature and profiler agents, a modeling summary, and verdicts from the red-team and compliance agents.
        A cycle whose agents could not run has none.
      </EmptyState>
    );
  }
  // Oldest first: the order the agents wrote them.
  const ordered = [...reports].sort((a, b) => a.created_at.localeCompare(b.created_at));
  return (
    <Card kind="proposed">
      <div className="small muted" style={{ marginBottom: 6 }}>
        <KindTag kind="proposed" /> Written by agents. A verdict is an agent's opinion, not a harness measurement.
      </div>
      <ul className="list">
        {ordered.map((r) => (
          <li key={r.report_id} className="item stack" style={{ gap: 4 }}>
            <div className="row between">
              <Link to={links.report(r.report_id)}>
                <strong>{r.title}</strong>
              </Link>
              {r.verdict && <Pill tone={reviewTone(r.verdict)}>{r.verdict}</Pill>}
            </div>
            <div className="xs muted row" style={{ gap: 10 }}>
              <span>{agentLabel(r.author)}</span>
              <span>{titleCase(r.kind)} report</span>
              <span>{fmtDateTime(r.created_at)}</span>
              {r.candidate_ref?.startsWith("candidate:") && (
                <Link to={links.approval(r.candidate_ref)} title="Approval evidence for this candidate">
                  Evidence for {refLabel(r.candidate_ref)}
                </Link>
              )}
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}
