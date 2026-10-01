/**
 * Screen 10 — Fairness and compliance: how candidates do on adverse impact, which features could stand in for a
 * protected class, and what the compliance agent concluded. Ratios and the proxy scan are harness measurements;
 * compliance findings are agent output (proposed). Protected attributes are used only for testing, never as inputs.
 */
import { useDefinitions, useFairness, useModels, useStatus } from "../api/hooks";
import type { DefinitionRef, FairnessData, ModelRef } from "../api/types";
import { isUnavailable } from "../api/types";
import { CandidatesTable, lowestOf } from "../components/Fairness/CandidatesTable";
import { DecisionFairnessView } from "../components/Fairness/DecisionFairness";
import { ComplianceFindings, ProhibitedRegister } from "../components/Fairness/Findings";
import { ProxyHeatmap } from "../components/Fairness/ProxyHeatmap";
import { classLabel, comparison } from "../components/Fairness/labels";
import "../components/Fairness/fairness.css";
import { DefinitionSelect, HBars, definitionRefOf, isBaselineRef, modelOfRef, pickDefinition, plural, useDefinitionParam } from "../components/shared";
import { Banner, Card, EmptyState, Page, PageHeader, QueryView, Section, UnavailableState } from "../components/ui";
import { fmtAuc, fmtNum, refLabel } from "../lib/format";

export default function Fairness() {
  const defs = useDefinitions();
  const active = defs.data?.find((d) => d.is_active);
  const { requested, select } = useDefinitionParam(active?.version);
  const fair = useFairness(requested);
  const models = useModels();
  const status = useStatus();

  const refs: DefinitionRef[] = (defs.data ?? []).map(definitionRefOf);
  const current = pickDefinition(refs, requested, active?.version);
  const modelOf = (ref: string) => modelOfRef(models.data, ref);

  return (
    <Page>
      <PageHeader
        eyebrow="Models and evidence"
        title="Fairness and compliance"
        summary={fair.data ? summarySentence(fair.data, current) : undefined}
        actions={<DefinitionSelect refs={refs} value={fair.data?.definition_version ?? current?.version} activeVersion={active?.version} onChange={select} />}
      />
      <QueryView query={fair} loadingHeight={360}>
        {(f) => (
          <FairnessBody
            f={f}
            modelOf={modelOf}
            synthetic={status.data?.data_mode === "synthetic"}
          />
        )}
      </QueryView>
    </Page>
  );
}

function FairnessBody({ f, modelOf, synthetic }: { f: FairnessData; modelOf: (ref: string) => ModelRef | undefined; synthetic: boolean }) {
  const cands = [...f.candidates].sort((a, b) => b.ts.localeCompare(a.ts));
  const latest = cands.find((c) => !isBaselineRef(c.candidate_ref)) ?? cands[0];
  const measured = cands.filter((c) => c.min_air != null);
  const worst = measured.length ? measured.reduce((a, b) => ((b.min_air as number) < (a.min_air as number) ? b : a)) : undefined;
  const low = latest ? lowestOf(latest) : null;
  const latestBelow = latest?.min_air != null && latest.min_air < f.threshold_air;

  // the protected classes actually tested, named from the data rather than assumed
  const classKeys = Array.from(new Set([...cands.flatMap((c) => Object.keys(c.classes)), ...f.proxy_heatmap.map((c) => c.protected_class)]));
  const names = classKeys.map((k) => classLabel(k).toLowerCase());
  const attributeList = names.length ? `${names.slice(0, -1).join(", ")}${names.length > 1 ? " and " : ""}${names[names.length - 1]}`.replace(/^./, (c) => c.toUpperCase()) : "";


  return (
    <>
      {!latest ? (
        <EmptyState title="No fairness results under this definition yet">
          Every evaluation measures the adverse impact ratio for each protected group at a fixed approval rate. Results appear here once the harness has evaluated a baseline or a
          candidate under this definition.
        </EmptyState>
      ) : (
        <Banner
          tone={latest.min_air == null ? "neutral" : latestBelow ? "crit" : "good"}
          title={
            latest.min_air == null
              ? `${refLabel(latest.candidate_ref)}: no adverse impact ratio was measured`
              : `${refLabel(latest.candidate_ref)}: lowest adverse impact ratio ${fmtAuc(latest.min_air, 3)} against a threshold of ${fmtAuc(f.threshold_air, 2)}`
          }
        >
          {latest.min_air != null && (
            <p style={{ margin: "4px 0 0" }}>
              {low ? `${comparison(low.cls, low.group, low.ref)} (${classLabel(low.cls).toLowerCase()}). ` : ""}
              {latestBelow
                ? `That is ${fmtAuc(f.threshold_air - latest.min_air, 3)} below the threshold, so the adverse-impact check fails.`
                : `That is ${fmtAuc(latest.min_air - f.threshold_air, 3)} above the threshold, so the adverse-impact check passes.`}{" "}
              {worst && measured.length > 1
                ? `Across the ${plural(measured.length, "evaluation")} under this definition the lowest ratio is ${fmtAuc(worst.min_air, 3)} (${refLabel(worst.candidate_ref)}). `
                : ""}
              Ratios are measured on every application in the validation period, approved or declined, when the model approves the lowest-risk {fmtNum(f.approval_rate * 100)}%. They are point
              estimates, and group sizes are not reported, so a ratio a few points from 1.0 may be sampling noise.
            </p>
          )}
        </Banner>
      )}

      <Banner tone="neutral" title="Protected attributes are used only for testing">
        {attributeList}
        {attributeList ? " are" : "Protected attributes are"} used only to test results, never as model inputs.
        {synthetic ? " In this environment the group labels are synthetic; in production they would be estimated for testing only, under counsel’s review." : ""}
      </Banner>

      {cands.length > 0 && (
        <Section title="Adverse impact by candidate" note="The lowest ratio across all protected groups for each evaluation under this definition, newest first. The dashed lines mark parity with the reference group and the threshold.">
          <Card title="Lowest adverse impact ratio" kind="measured">
            <HBars
              title="Lowest adverse impact ratio by evaluation, against the threshold"
              rows={cands.slice(0, 8).map((c) => {
                const l = lowestOf(c);
                const below = c.min_air != null && c.min_air < f.threshold_air;
                return {
                  key: c.eval_id,
                  label: refLabel(c.candidate_ref),
                  value: c.min_air ?? 0,
                  display: <span className="num">{c.min_air == null ? "—" : fmtAuc(c.min_air, 3)}</span>,
                  note: l ? `${comparison(l.cls, l.group, l.ref)}${below ? "; below the threshold" : ""}` : undefined,
                  tone: below ? ("crit" as const) : ("accent" as const),
                };
              })}
              format={(v) => fmtAuc(v, 2)}
              min={0}
              max={1.2}
              markers={[
                { value: 1, label: "Parity with the reference group" },
                { value: f.threshold_air, label: "Threshold" },
              ]}
            />
          </Card>
          <Card flush kind="measured">
            <CandidatesTable candidates={cands} threshold={f.threshold_air} modelOf={modelOf} />
          </Card>
        </Section>
      )}

      <Section
        title="Proxy scan"
        note={`How well each feature alone predicts membership of a protected group, pooled and group by group. A feature flagged above ${fmtAuc(f.proxy_threshold, 2)} could stand in for the protected class, so a candidate that uses one fails the “No proxy features” check.`}
      >
        <Card kind="measured">
          <ProxyHeatmap cells={f.proxy_heatmap} threshold={f.proxy_threshold} />
        </Card>
      </Section>

      <div className="grid split">
        <Section title="Prohibited-feature register">
          <ProhibitedRegister features={f.prohibited_features} />
        </Section>
        <Section title="Compliance findings">
          <ComplianceFindings findings={f.findings} modelOf={modelOf} />
        </Section>
      </div>

      <Section title="Adverse impact on actual decisions" note="Validation results show how a model would treat applicants; decisions show how it does.">
        {isUnavailable(f.decisions) ? (
          <UnavailableState u={f.decisions} title="No decisions to measure yet" />
        ) : (
          <DecisionFairnessView d={f.decisions} threshold={f.threshold_air} />
        )}
      </Section>
    </>
  );
}

function summarySentence(f: FairnessData, def: DefinitionRef | undefined): string {
  const d = def?.summary ?? "this definition";
  const cands = [...f.candidates].sort((a, b) => b.ts.localeCompare(a.ts));
  const latest = cands.find((c) => !isBaselineRef(c.candidate_ref)) ?? cands[0];
  const flagged = new Set(f.proxy_heatmap.filter((c) => c.flagged).map((c) => c.feature));
  const scanned = new Set(f.proxy_heatmap.map((c) => c.feature));
  const scan = f.proxy_heatmap.length
    ? `the proxy scan flags ${plural(flagged.size, "feature")} of ${fmtNum(scanned.size)}`
    : "no proxy scan has run";
  if (!latest) return `No fairness results under ${d} yet; ${scan}.`;
  if (latest.min_air == null) return `${refLabel(latest.candidate_ref)} has no adverse impact ratio under ${d}; ${scan}.`;
  const below = latest.min_air < f.threshold_air;
  return `${refLabel(latest.candidate_ref)} has a lowest adverse impact ratio of ${fmtAuc(latest.min_air, 3)}, ${below ? "below" : "above"} the ${fmtAuc(f.threshold_air, 2)} threshold under ${d}; ${scan}.`;
}
