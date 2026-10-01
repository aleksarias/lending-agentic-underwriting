/** The prohibited-feature register and the compliance agent's findings (proposed, not measured). */
import { Link } from "react-router-dom";
import type { ModelRef, ReportMeta } from "../../api/types";
import { fmtDateTime, refLabel, reviewTone } from "../../lib/format";
import { Card, EmptyState, KindTag, ModelBadge, Pill, links } from "../ui";
import "./fairness.css";

export function ProhibitedRegister({ features }: { features: string[] }) {
  return (
    <Card kind="measured">
      {features.length === 0 ? (
        <EmptyState title="The register is empty">Features that may never be model inputs (direct protected attributes and close proxies) are listed here.</EmptyState>
      ) : (
        <div className="stack">
          <ul className="fairness-register" aria-label="Prohibited features">
            {features.map((f) => (
              <li key={f} className="models-chip">
                {f}
              </li>
            ))}
          </ul>
          <div className="small muted">
            These may never be model inputs: they are protected attributes themselves or close proxies for them. Every evaluation checks that a candidate uses none of them, and a
            candidate that uses one fails validation. The attributes are used only to test results.
          </div>
        </div>
      )}
    </Card>
  );
}

export function ComplianceFindings({ findings, modelOf }: { findings: ReportMeta[]; modelOf: (ref: string) => ModelRef | undefined }) {
  return (
    <Card kind="proposed">
      {findings.length === 0 ? (
        <EmptyState title="No compliance findings under this definition">
          The compliance agent writes a fair-lending and adverse-action review for each candidate that passes validation. Each one appears here with its verdict and a link to the
          full report.
        </EmptyState>
      ) : (
        <>
          <div className="small muted" style={{ marginBottom: 10 }}>
            Written by the compliance agent. <KindTag kind="proposed" /> A verdict is the agent’s opinion on the evidence above until a person decides; the measured results are the
            ratios and the scan.
          </div>
          <ul className="fairness-list">
            {findings.map((r) => {
              const m = r.candidate_ref ? modelOf(r.candidate_ref) : undefined;
              return (
                <li key={r.report_id}>
                  <div className="row between">
                    <span className="row" style={{ gap: 8 }}>
                      <Pill tone={reviewTone(r.verdict)}>{r.verdict ?? "no verdict"}</Pill>
                      {m ? <ModelBadge model={m} /> : r.candidate_ref ? <span className="small">{refLabel(r.candidate_ref)}</span> : null}
                    </span>
                    <span className="xs muted">{fmtDateTime(r.created_at)}</span>
                  </div>
                  <Link to={links.report(r.report_id)}>{r.title}</Link>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </Card>
  );
}
