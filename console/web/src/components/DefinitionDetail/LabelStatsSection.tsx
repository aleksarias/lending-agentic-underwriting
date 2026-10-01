/** What this definition does to the loan book: how many loans are labelled, how many default, and why loans are left out. */
import type { DefinitionVersion } from "../../api/types";
import { fmtNum, fmtPct } from "../../lib/format";
import { exclusionLabel, triggerLabel } from "../Definitions/fields";
import { Card, EmptyState, KindTag, Tiles } from "../ui";
import { CountBars } from "./CountBars";

export function LabelStatsSection({ def }: { def: DefinitionVersion }) {
  const s = def.label_stats;
  if (!s) {
    return (
      <EmptyState title="No labels have been built for this definition">
        The labels stage counts eligible loans, defaults, exclusions and triggers when the definition is applied (<code>lau default-definition apply</code>). Nothing has been
        recorded for this version yet.
      </EmptyState>
    );
  }
  const dpd = typeof def.fields.delinquency_threshold_dpd === "number" ? def.fields.delinquency_threshold_dpd : null;
  const excluded = Object.values(s.exclusions).reduce((a, n) => a + n, 0);
  const triggered = Object.values(s.triggers).reduce((a, n) => a + n, 0);
  // Each loan has one exclusion reason and each default one first trigger, so the parts should add up to the whole.
  const exclusionsAddUp = excluded === s.n_loans - s.n_eligible;
  const triggersAddUp = triggered === s.n_default;
  return (
    <div className="stack" style={{ gap: "var(--gap)" }}>
      <Tiles
        tiles={[
          { key: "loans", label: "Loans in the data", value: fmtNum(s.n_loans) },
          { key: "eligible", label: "Eligible loans", value: fmtNum(s.n_eligible), sub: `${fmtPct(s.n_loans ? s.n_eligible / s.n_loans : null)} of all loans` },
          { key: "defaults", label: "Defaults", value: fmtNum(s.n_default) },
          { key: "rate", label: "Default rate", value: fmtPct(s.default_rate), sub: "defaults among eligible loans", tone: "accent" },
        ]}
      />
      <div className="xs muted">
        <KindTag kind="measured" /> Counted by the labels stage from the loan performance data.
        {exclusionsAddUp && ` ${fmtNum(s.n_loans)} loans − ${fmtNum(excluded)} excluded = ${fmtNum(s.n_eligible)} eligible.`}
      </div>
      <div className="grid cols-2">
        <Card kind="measured" title="Why loans are left out">
          {Object.keys(s.exclusions).length === 0 ? (
            <div className="small muted">No loan is excluded under this definition.</div>
          ) : (
            <CountBars
              title="Loans left out of the labels, by reason"
              rows={Object.entries(s.exclusions).map(([k, n]) => ({ key: k, label: exclusionLabel(k), count: n }))}
              total={s.n_loans}
              basis="all loans in the data"
            />
          )}
        </Card>
        <Card kind="measured" title="What made each loan default">
          {Object.keys(s.triggers).length === 0 ? (
            <div className="small muted">No defaults were recorded under this definition.</div>
          ) : (
            <>
              <CountBars
                title="Defaults, by the first event that made the loan default"
                rows={Object.entries(s.triggers).map(([k, n]) => ({ key: k, label: triggerLabel(k, dpd), count: n }))}
                total={s.n_default}
                basis="defaults"
              />
              {!triggersAddUp && <div className="xs muted">The triggers do not add up to the number of defaults ({fmtNum(triggered)} against {fmtNum(s.n_default)}).</div>}
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
