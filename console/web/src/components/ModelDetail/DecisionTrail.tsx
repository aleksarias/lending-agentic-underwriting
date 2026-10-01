/** The governance trail for this version: holdout gate, approvals (people) and agent reports (proposed). */
import { Link } from "react-router-dom";
import type { ApprovalRecord, GateSummary, ModelCard, ReportMeta } from "../../api/types";
import { fmtAuc, fmtDateTime, fmtDiff, reviewTone, titleCase } from "../../lib/format";
import { checkName } from "../shared";
import { Card, EmptyState, KindTag, Pill, Section, links } from "../ui";
import "./modeldetail.css";

export function DecisionTrail({ card, candidateRef }: { card: ModelCard; candidateRef: string | null }) {
  const evaluated = card.evaluations.length > 0;
  return (
    <Section title="Gate, approvals and reports" note="What happens after validation: one read of the holdout, a person’s decision, and the agents’ written reviews.">
      <div className="modeldetail-trail">
        <GateCard gate={card.gate} candidateRef={candidateRef} evaluated={evaluated} />
        <ApprovalsCard approvals={card.approvals} candidateRef={candidateRef} evaluated={evaluated} />
        <ReportsCard reports={card.reports} />
      </div>
    </Section>
  );
}

function GateCard({ gate, candidateRef, evaluated }: { gate: GateSummary | null; candidateRef: string | null; evaluated: boolean }) {
  if (!gate) {
    return (
      <Card title="Holdout gate" kind="measured">
        <EmptyState
          title="Holdout gate not run"
          action={candidateRef ? <Link to={links.approval(candidateRef)}>Open approval evidence</Link> : undefined}
        >
          {evaluated
            ? "The gate reads the holdout once for a candidate and spends part of a limited budget, so it is run deliberately from Approvals after the candidate passes validation and has red-team and compliance reports."
            : "The gate needs a validation result first. This version has none, so it cannot be gated."}
        </EmptyState>
      </Card>
    );
  }
  const checks = Object.entries(gate.checks);
  return (
    <Card title="Holdout gate" kind="measured">
      <div className="stack">
        <div className="row between">
          <Pill tone={gate.passed ? "good" : "crit"}>{gate.passed ? "passed" : "failed"}</Pill>
          <span className="xs muted">{fmtDateTime(gate.ts)}</span>
        </div>
        <div className="small">
          Holdout AUC <span className="num">{fmtAuc(gate.holdout_auc)}</span> against the reference’s <span className="num">{fmtAuc(gate.reference_holdout_auc)}</span> (
          <span className="num">{fmtDiff(gate.holdout_auc - gate.reference_holdout_auc)}</span>).
        </div>
        {checks.length > 0 && (
          <ul className="modeldetail-gate-checks">
            {checks.map(([k, ok]) => (
              <li key={k}>
                <span>{checkName(k)}</span>
                <Pill tone={ok ? "good" : "crit"}>{ok ? "pass" : "fail"}</Pill>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

function ApprovalsCard({ approvals, candidateRef, evaluated }: { approvals: ApprovalRecord[]; candidateRef: string | null; evaluated: boolean }) {
  return (
    <Card title="Approvals">
      {approvals.length === 0 ? (
        <EmptyState title="No decision recorded" action={candidateRef ? <Link to={links.approval(candidateRef)}>Open approval evidence</Link> : undefined}>
          A named person approves or rejects a candidate with a written rationale, after the holdout gate.{" "}
          {evaluated ? "Nothing has been decided for this version." : "This version has no validation result yet, so there is nothing to decide."}
        </EmptyState>
      ) : (
        <ul className="modeldetail-list">
          {approvals.map((a) => (
            <li key={a.approval_id}>
              <div className="row between">
                <Pill tone={a.decision.startsWith("approve") ? "good" : "crit"}>{a.decision.startsWith("approve") ? "approved" : a.decision.startsWith("reject") ? "rejected" : a.decision}</Pill>
                <span className="xs muted">{fmtDateTime(a.ts)}</span>
              </div>
              <div className="small">by {a.approver}</div>
              {a.rationale && <div className="small muted">“{a.rationale}”</div>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function ReportsCard({ reports }: { reports: ReportMeta[] }) {
  return (
    <Card title="Agent reports" kind="proposed">
      {reports.length === 0 ? (
        <EmptyState title="No agent reports">The red-team and compliance agents write a report for each candidate that passes validation.</EmptyState>
      ) : (
        <>
          <div className="xs muted" style={{ marginBottom: 8 }}>
            Written by agents. <KindTag kind="proposed" /> A verdict here is an agent’s opinion until the harness measures the same thing.
          </div>
          <ul className="modeldetail-list">
            {reports.map((r) => (
              <li key={r.report_id}>
                <div className="row between">
                  <span className="row" style={{ gap: 6 }}>
                    <strong className="small">{r.kind === "redteam" ? "Red team" : titleCase(r.kind)}</strong>
                    <Pill tone={reviewTone(r.verdict)}>{r.verdict ?? "no verdict"}</Pill>
                  </span>
                  <span className="xs muted">{fmtDateTime(r.created_at)}</span>
                </div>
                <Link className="small" to={links.report(r.report_id)}>
                  {r.title}
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}
