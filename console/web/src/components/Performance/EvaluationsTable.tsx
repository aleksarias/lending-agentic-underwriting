/**
 * Harness evaluations as a table: validation AUC against the reference plus the multiple-testing margin the
 * candidate had to clear. Used by Performance (all candidates) and the model detail screen (one model).
 */
import { Link } from "react-router-dom";
import type { EvaluationSummary, ModelRef } from "../../api/types";
import { fmtAuc, fmtDateTime, fmtDiff, refLabel } from "../../lib/format";
import { WrapHeader as H, isBaselineRef } from "../Models/shared";
import { DataTable, ModelBadge, Pill, links, type Column } from "../ui";

const passText =
  "Passed means every harness check passed: the margin over the reference, calibration, time stability, segment floor, score drift, leakage, prohibited and proxy features, adverse impact and reason codes.";

export function EvaluationsTable(props: {
  rows: EvaluationSummary[];
  /** resolves "candidate:11" to the registered model so the candidate links to its model page */
  modelOf?: (ref: string) => ModelRef | undefined;
  showCandidate?: boolean;
  maxHeight?: number;
}) {
  const columns: Column<EvaluationSummary>[] = [];
  if (props.showCandidate) {
    columns.push({
      key: "candidate",
      header: "Candidate",
      render: (e) => {
        const m = props.modelOf?.(e.candidate_ref);
        return (
          <span className="row" style={{ gap: 6 }}>
            {m ? <ModelBadge model={m} /> : <span>{refLabel(e.candidate_ref)}</span>}
            {isBaselineRef(e.candidate_ref) && <span className="xs muted">baseline</span>}
          </span>
        );
      },
      sort: (e) => Number(e.candidate_ref.split(":")[1]),
    });
  }
  columns.push(
    {
      key: "when",
      header: <H>Evaluated (UTC)</H>,
      render: (e) => <span className="small">{fmtDateTime(e.ts)}</span>,
      sort: (e) => e.ts,
    },
    {
      key: "auc",
      header: <H>Validation AUC</H>,
      align: "right",
      render: (e) => (
        <Link className="num" to={links.evaluation(e.eval_id)} title="Open the full evaluation">
          {fmtAuc(e.val_auc)}
        </Link>
      ),
      sort: (e) => e.val_auc,
    },
    {
      key: "ref",
      header: <H>Reference AUC</H>,
      align: "right",
      render: (e) =>
        e.reference_auc == null ? (
          <span className="muted" title="A baseline has no earlier reference; it sets the reference for later candidates.">
            none
          </span>
        ) : (
          <span className="num">{fmtAuc(e.reference_auc)}</span>
        ),
      sort: (e) => e.reference_auc,
    },
    {
      key: "diff",
      header: "Difference",
      align: "right",
      render: (e) => {
        if (e.reference_auc == null) return <span className="muted">—</span>;
        const gain = e.val_auc - e.reference_auc;
        const room = gain - e.required_margin;
        return (
          <span className="num">
            {fmtDiff(gain)}
            <span className="models-cell-sub">{room >= 0 ? `clears the margin by ${fmtAuc(room)}` : `short of the margin by ${fmtAuc(-room)}`}</span>
          </span>
        );
      },
      sort: (e) => (e.reference_auc == null ? null : e.val_auc - e.reference_auc),
    },
    {
      key: "margin",
      header: <H>Required margin</H>,
      align: "right",
      render: (e) => <span className="num">{fmtDiff(e.required_margin)}</span>,
      sort: (e) => e.required_margin,
    },
    {
      key: "tests",
      header: <H>Tests counted</H>,
      align: "right",
      render: (e) => <span className="num">{e.n_tests}</span>,
      sort: (e) => e.n_tests,
    },
    {
      key: "passed",
      header: "Result",
      render: (e) => (
        <span title={passText}>
          <Pill tone={e.passed_validation ? "good" : "warn"}>{e.passed_validation ? "passed" : "did not pass"}</Pill>
        </span>
      ),
      sort: (e) => (e.passed_validation ? 1 : 0),
    },
    {
      key: "open",
      header: "Evidence",
      render: (e) => (
        <Link className="mono xs nowrap" to={links.evaluation(e.eval_id)}>
          {e.eval_id}
        </Link>
      ),
    },
  );
  return <DataTable rows={props.rows} columns={columns} rowKey={(e) => e.eval_id} initialSort={{ key: "when", dir: "desc" }} maxHeight={props.maxHeight} />;
}
