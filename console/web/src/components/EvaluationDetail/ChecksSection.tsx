/** The harness checks for this evaluation: failed first, each with the rule, the measurement and its limit. */
import type { EvaluationDetail } from "../../api/types";
import { checkName } from "../Models/shared";
import type { Limits } from "../Performance/thresholds";
import { Card, DataTable, Pill, Section, type Column } from "../ui";
import { CHECK_RULE, measuredFor } from "./checks";
import "./evaluation.css";

interface Row {
  key: string;
  ok: boolean;
}

export function ChecksSection({ e, limits }: { e: EvaluationDetail; limits: Limits }) {
  const rows: Row[] = Object.entries(e.checks)
    .map(([key, ok]) => ({ key, ok }))
    .sort((a, b) => Number(a.ok) - Number(b.ok));
  const failed = rows.filter((r) => !r.ok).length;
  const columns: Column<Row>[] = [
    {
      key: "check",
      header: "Check",
      render: (r) => (
        <span>
          <strong>{checkName(r.key)}</strong>
          {CHECK_RULE[r.key] && <span className="evaluation-rule">{CHECK_RULE[r.key]}</span>}
        </span>
      ),
    },
    {
      key: "result",
      header: "Result",
      render: (r) => <Pill tone={r.ok ? "good" : "crit"}>{r.ok ? "pass" : "fail"}</Pill>,
    },
    {
      key: "measured",
      header: "What was measured",
      render: (r) => {
        const text = measuredFor(r.key, e, limits);
        return text ? <span className="evaluation-measured">{text}</span> : <span className="muted">—</span>;
      },
    },
  ];
  return (
    <Section
      title="Checks"
      note={
        failed
          ? `${failed} of ${rows.length} checks failed, so the candidate did not pass validation. Failed checks are listed first.`
          : `All ${rows.length} checks passed. A candidate must pass every check to pass validation.`
      }
    >
      <Card flush kind="measured">
        <DataTable rows={rows} columns={columns} rowKey={(r) => r.key} />
      </Card>
    </Section>
  );
}
