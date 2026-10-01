/**
 * Screen 9 — Performance: what the harness measured for every candidate under one definition of default, and how
 * hard the bar has become. Validation results are harness measurements. Each validation test under a definition
 * raises the AUC margin the next candidate must clear, and the holdout may be read only a limited number of times.
 */
import { Link } from "react-router-dom";
import { useDefinitions, useModels, usePerformance, useProgress, useSettings, useStatus } from "../api/hooks";
import type { DefinitionRef, DefinitionVersion, Denominator, PerformanceData, Tile, Unavailable } from "../api/types";
import { DefinitionSelect, isBaselineRef, modelOfRef, pickDefinition, plural, useDefinitionParam, definitionRefOf } from "../components/Models/shared";
import { EvaluationsTable } from "../components/Performance/EvaluationsTable";
import { HoldoutSection } from "../components/Performance/HoldoutSection";
import { MarginLedgerChart } from "../components/Performance/MarginLedgerChart";
import { limitsFrom, type Limits } from "../components/Performance/thresholds";
import "../components/Performance/performance.css";
import { Card, EmptyState, KeyValue, Page, PageHeader, QueryView, Section, Tiles, UnavailableState } from "../components/ui";
import { fmtDiff, fmtNum } from "../lib/format";

export default function Performance() {
  const defs = useDefinitions();
  const active = defs.data?.find((d) => d.is_active);
  const { requested, select } = useDefinitionParam(active?.version);
  const perf = usePerformance(requested);
  const models = useModels();
  const progress = useProgress();
  const settings = useSettings();
  const status = useStatus();

  const refs: DefinitionRef[] = perf.data?.definitions ?? (defs.data ?? []).map(definitionRefOf);
  const current = pickDefinition(refs, requested, active?.version);
  const limits = limitsFrom(settings.data);
  const denominator = progress.data?.denominator ?? null;

  return (
    <Page>
      <PageHeader
        eyebrow="Models and evidence"
        title="Performance"
        summary={perf.data ? summarySentence(perf.data, current, denominator) : undefined}
        actions={<DefinitionSelect refs={refs} value={perf.data?.definition_version ?? current?.version} activeVersion={active?.version} onChange={select} />}
      />
      <QueryView query={perf} loadingHeight={360}>
        {(p) => <PerformanceBody p={p} def={current} defDetail={defs.data?.find((d) => d.version === p.definition_version)} modelOf={(ref) => modelOfRef(models.data, ref)} denominator={denominator} limits={limits} nothingServing={status.data ? status.data.serving == null : undefined} />}
      </QueryView>
    </Page>
  );
}

function PerformanceBody(props: {
  p: PerformanceData;
  def: DefinitionRef | undefined;
  defDetail: DefinitionVersion | undefined;
  modelOf: (ref: string) => ReturnType<typeof modelOfRef>;
  denominator: Denominator | null;
  limits: Limits;
  nothingServing?: boolean;
}) {
  const { p, limits } = props;
  // the progress denominator describes the active definition only
  const denom = props.denominator && props.denominator.definition_version === p.definition_version ? props.denominator : null;
  const cands = p.evaluations.filter((e) => !isBaselineRef(e.candidate_ref));
  const baselines = p.evaluations.length - cands.length;
  const passed = cands.filter((e) => e.passed_validation).length;
  const latest = [...p.evaluations].sort((a, b) => b.ts.localeCompare(a.ts))[0];
  const split = props.defDetail?.split;

  if (p.evaluations.length === 0) {
    return (
      <>
        <EmptyState title="No evaluations under this definition yet">
          The pipeline evaluates a baseline first, then improvement cycles submit candidates; each one appears here with its validation AUC, the margin it had to clear
          and the result of every check. Choose another definition above to see earlier evaluations.
        </EmptyState>
        <HoldoutSection holdout={p.holdout} modelOf={props.modelOf} />
      </>
    );
  }

  const tiles: Tile[] = [
    {
      key: "passed",
      label: "Candidates passing validation",
      value: cands.length ? `${passed} of ${cands.length}` : "—",
      sub: baselines === 0 ? "no baseline evaluated" : `${plural(baselines, "baseline")} evaluated as ${baselines === 1 ? "the reference" : "references"}`,
    },
    {
      key: "tests",
      label: "Validation tests counted",
      value: fmtNum(latest?.n_tests ?? 0),
      sub: denom ? `${denom.tests_since_reset} since the validation labels were last rebuilt` : "at the latest evaluation",
    },
    denom
      ? { key: "next", label: "Margin the next candidate must clear", value: fmtDiff(denom.next_margin, 4), sub: "AUC over its reference" }
      : { key: "margin", label: "Margin at the latest evaluation", value: fmtDiff(latest?.required_margin, 4), sub: "AUC over the reference" },
    {
      key: "holdout",
      label: "Holdout gates used",
      value: `${p.holdout.used} of ${p.holdout.budget}`,
      sub: p.holdout.used >= p.holdout.budget ? "budget spent" : p.holdout.used === 0 ? "the holdout has not been read" : "reads of the holdout so far",
      tone: p.holdout.used >= p.holdout.budget ? "warn" : null,
      href: "/approvals",
    },
  ];

  return (
    <>
      <Tiles tiles={tiles} />

      <Section
        title="Evaluations"
        note={
          <>
            Every evaluation the harness ran under this definition, newest first.
            {split ? ` The validation window is ${split.validation[0]} to ${split.validation[1]} originations; each evaluation states its own sample size.` : ""}
          </>
        }
      >
        <Card flush kind="measured">
          <EvaluationsTable rows={p.evaluations} showCandidate modelOf={props.modelOf} />
        </Card>
        <div className="xs muted">
          Difference is validation AUC minus the reference AUC (the baseline or champion the candidate is measured against). Passed means every check passed, not only
          the margin: open an evaluation to see which check failed. A baseline has no earlier reference; it sets the reference for later candidates. Validation AUCs are
          comparable only between evaluations on the same validation sample.
        </div>
      </Section>

      <Section title="Multiple-testing ledger" note="Every test raises the bar, so the best of many candidates is not as impressive as it looks.">
        <div className="grid split">
          <Card title="Required margin and each candidate’s gain over its reference" kind="measured">
            <MarginLedgerChart title="Required AUC margin by number of validation tests counted, and each candidate's AUC gain over its reference" ledger={p.ledger} />
          </Card>
          <Card title="How the bar rises">
            <div className="performance-explain">
              <p>
                A candidate counts as an improvement only if its validation AUC beats its reference by the required margin. The margin grows with every validation test
                under the same definition, because the more ideas are tried, the more likely the best one looks good by chance.
              </p>
              {limits.baseMargin != null && limits.mtPenaltyK != null && (
                <p className="performance-formula">
                  margin = {fmtNum(limits.baseMargin, 4)} + {fmtNum(limits.mtPenaltyK, 4)} × √ln(1 + tests counted)
                </p>
              )}
              <p>
                The count restarts when the validation labels are rebuilt (a new definition of default or a new data version), because tests on the earlier sample say
                nothing about the new one. The next margin can therefore be lower than the last.
              </p>
              {denom && (
                <KeyValue
                  items={[
                    ["Tests under this definition", fmtNum(denom.tests_total)],
                    ["Tests since the last reset", fmtNum(denom.tests_since_reset)],
                    ["Margin for the next candidate", <span key="m" className="num">{fmtDiff(denom.next_margin, 4)} AUC</span>],
                  ]}
                />
              )}
              <p className="muted">
                Clearing the margin is a screening rule. It does not show that a candidate beats every model built so far; the benchmark ledger on{" "}
                <Link to="/progress">Progress</Link> compares them on the same loans with intervals.
              </p>
            </div>
          </Card>
        </div>
      </Section>

      <HoldoutSection holdout={p.holdout} modelOf={props.modelOf} />

      <Section title="Validation against production" note="The same metrics on real decisions, side by side with validation, once outcomes mature.">
        <UnavailableState u={production(props.nothingServing)} title="No production decisions to compare yet" />
      </Section>
    </>
  );
}

function production(nothingServing: boolean | undefined): Unavailable {
  return {
    available: false,
    reason:
      nothingServing === false
        ? "A model is serving, but outcomes for its decisions have not matured enough to compare with validation."
        : "No model is making decisions, so there is nothing to compare with validation. Once a promoted model decides applications and their outcomes mature, discrimination, calibration and stability are shown here on real decisions.",
    requires: ["A promoted model serving decisions", "Loan status feed", "Matured outcomes for those decisions"],
  };
}

function summarySentence(p: PerformanceData, def: DefinitionRef | undefined, denom: Denominator | null): string {
  const d = def?.summary ?? "this definition";
  if (p.evaluations.length === 0) return `No evaluations have been run under ${d} yet.`;
  const cands = p.evaluations.filter((e) => !isBaselineRef(e.candidate_ref));
  if (cands.length === 0) return `Only baselines have been evaluated under ${d}; no candidate has been tested yet.`;
  const passed = cands.filter((e) => e.passed_validation).length;
  const next = denom && denom.definition_version === p.definition_version ? `; the next candidate must beat its reference by ${fmtDiff(denom.next_margin, 4)} AUC` : "";
  return `${plural(cands.length, "candidate")} evaluated under ${d}: ${passed} passed validation and ${cands.length - passed} did not${next}, and ${p.holdout.used} of ${p.holdout.budget} holdout gates have been used.`;
}
