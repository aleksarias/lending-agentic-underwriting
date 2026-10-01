/** Validation result and the harness checks: what the harness measured before any human looked. */
import type { EvidencePacket } from "../../api/types";
import { fmtAuc, fmtDateTime, fmtDiff, fmtNum } from "../../lib/format";
import { Card, EmptyState, Pill, Section, Tiles, links } from "../ui";
import { CheckList, checkCounts } from "./CheckList";

export function ValidationSection({ p }: { p: EvidencePacket }) {
  const ev = p.evaluation;
  const counts = checkCounts(p.checks);
  if (!ev) {
    return (
      <Section title="Validation result">
        <EmptyState title="No validation result">The harness has not evaluated this candidate, so there is nothing to approve yet.</EmptyState>
      </Section>
    );
  }
  const bar = ev.reference_auc != null ? ev.reference_auc + ev.required_margin : null;
  const headroom = bar != null ? ev.val_auc - bar : null;
  return (
    <>
      <Section
        title="Validation result"
        note={
          <>
            Measured by the harness on the validation window, {fmtDateTime(ev.ts)}. The candidate must beat the reference model by a margin that grows with
            every test already run under this definition, so a lucky candidate among many does not pass. The holdout is not touched here.
          </>
        }
      >
        <Tiles
          tiles={[
            { key: "auc", label: "Validation AUC", value: fmtAuc(ev.val_auc, 4), sub: ev.passed_validation ? "passed validation" : "did not pass validation", tone: ev.passed_validation ? "good" : "crit", href: links.evaluation(ev.eval_id) },
            { key: "bar", label: "Bar to clear", value: fmtAuc(bar, 4), sub: ev.reference_auc != null ? `reference ${fmtAuc(ev.reference_auc, 4)} + margin ${fmtAuc(ev.required_margin, 4)}` : "no reference model to compare with", href: "/performance" },
            { key: "room", label: "Clears the bar by", value: fmtDiff(headroom, 4), sub: "AUC, no interval on this figure", tone: headroom != null && headroom < 0 ? "crit" : null },
            { key: "tests", label: "Tests under this definition", value: fmtNum(ev.n_tests), sub: "each test raises the bar for the next", href: "/performance" },
          ]}
        />
      </Section>
      <Section title="Harness checks" right={<Pill tone={counts.passed === counts.total ? "good" : "crit"}>{counts.passed} of {counts.total} passed</Pill>}>
        <Card kind="measured">{counts.total ? <CheckList checks={p.checks} /> : <EmptyState title="No checks recorded" />}</Card>
      </Section>
    </>
  );
}
