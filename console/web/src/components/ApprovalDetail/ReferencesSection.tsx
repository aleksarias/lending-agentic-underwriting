/** Raw evidence: every identifier behind the packet, and the packet itself as returned by the API. */
import { useId, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { ApprovalRecord, EvidencePacket, Promotion } from "../../api/types";
import { Card, Json, KeyValue, Section, links } from "../ui";

export function ReferencesSection({ p, decision, promotion }: { p: EvidencePacket; decision: ApprovalRecord | null; promotion: Promotion | null }) {
  const [raw, setRaw] = useState(false);
  const rawId = useId();
  const items: [string, ReactNode][] = [
    ["Candidate", <span key="c" className="mono">{p.candidate_ref}</span>],
    ["Model", <span key="m" className="mono">{p.model.key}</span>],
    ["Definition of default", <Link key="d" to={links.definition(p.definition_version)} className="mono">{p.definition_version}</Link>],
    [
      "Validation run",
      p.evaluation ? (
        <Link key="e" to={links.evaluation(p.evaluation.eval_id)} className="mono">
          {p.evaluation.eval_id}
        </Link>
      ) : (
        "none"
      ),
    ],
    ["Holdout gate", p.gate ? <span key="g" className="mono">{p.gate.gate_id}</span> : "not run"],
    [
      "Reports",
      p.reports.length ? (
        <span key="r" className="row" style={{ gap: 10 }}>
          {p.reports.map((r) => (
            <Link key={r.report_id} to={links.report(r.report_id)} className="mono">
              {r.report_id}
            </Link>
          ))}
        </span>
      ) : (
        "none"
      ),
    ],
    ["Decision", decision ? <span key="a" className="mono">{decision.approval_id}</span> : "none recorded"],
    ["Promotion", promotion ? <span key="p" className="mono">{promotion.promotion_id}</span> : "not promoted"],
  ];
  return (
    <Section title="References" note="The identifiers behind this packet, for the audit trail.">
      <Card>
        <KeyValue items={items} />
        <div style={{ marginTop: 12 }}>
          <button type="button" className="btn small" aria-expanded={raw} aria-controls={rawId} onClick={() => setRaw((v) => !v)}>
            {raw ? "Hide the raw packet" : "Show the raw packet (JSON)"}
          </button>
          {raw && (
            <div id={rawId} style={{ marginTop: 8 }}>
              <Json value={p} />
            </div>
          )}
        </div>
      </Card>
    </Section>
  );
}
