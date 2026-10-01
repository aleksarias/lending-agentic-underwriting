/**
 * Screen 8, detail — one model version: what it is, how it ranks against every other model on the same loans,
 * its harness evaluations, the gate/approval/report trail, what it relies on, and where it came from.
 */
import { Link, useParams } from "react-router-dom";
import { useDefinitions, useLineage, useModelCard, useProgress, useStatus } from "../api/hooks";
import type { DefinitionRef, ModelCard, ModelStatus, Tile } from "../api/types";
import { BenchmarkSection } from "../components/ModelDetail/BenchmarkSection";
import { DecisionTrail } from "../components/ModelDetail/DecisionTrail";
import { DescriptionSection } from "../components/ModelDetail/Description";
import { EvaluationsSection } from "../components/ModelDetail/EvaluationsSection";
import { FeatureImportance } from "../components/ModelDetail/FeatureImportance";
import { LineageFlow } from "../components/ModelDetail/LineageFlow";
import { benchLines, focusLine, noiseVerdict, vsBestSentence, type BenchLine } from "../components/ModelDetail/benchmark";
import { DetailView, NotFoundState, StatusPill, definitionRefOf, isBaselineRef } from "../components/Models/shared";
import { Card, DefinitionBadge, EmptyState, ErrorState, KeyValue, Loading, Page, PageHeader, Section, Tiles, links } from "../components/ui";
import { fmtAuc, fmtDiff } from "../lib/format";

export default function ModelDetail() {
  const { name, version } = useParams();
  const card = useModelCard(name, version);
  const lineage = useLineage(name, version);
  const progress = useProgress();
  const defs = useDefinitions();
  const status = useStatus();
  return (
    <Page>
      <DetailView
        query={card}
        loadingHeight={360}
        header={<PageHeader eyebrow="Models and evidence" title={version ? `Model v${version}` : "Model"} />}
        notFound={
          <>
            <PageHeader eyebrow="Models and evidence" title="Model not found" />
            <NotFoundState title="No such model version" back={{ to: "/models", label: "Back to all models" }}>
              Version {version ? <code>{version}</code> : null} of <code>{name}</code> is not in the registry. It may have been deleted, or the link may be mistyped.
            </NotFoundState>
          </>
        }
      >
        {(c) => {
          const def = defs.data?.map(definitionRefOf).find((d) => d.version === c.model.definition_version);
          const lines = benchLines(c, progress.data);
          // Approval evidence exists only for an evaluated candidate (the API answers 404 otherwise), never for a baseline
          const ref = c.evaluations[0]?.candidate_ref ?? null;
          const approvalRef = ref && !isBaselineRef(ref) ? ref : null;
          const trainedUnder = c.benchmark?.trained_under;
          return (
            <>
              <PageHeader
                eyebrow="Models and evidence"
                title={`Model ${c.model.label}`}
                summary={modelSummary(c, def, lines, defs.data?.find((d) => d.version === c.model.definition_version)?.is_active === false)}
                meta={
                  <>
                    <StatusPill status={c.status} />
                    {c.model.definition_version && <DefinitionBadge def={def} version={c.model.definition_version} />}
                    {c.aliases.map((a) => (
                      <code key={a} className="mono xs">
                        {a}
                      </code>
                    ))}
                    <span className="mono xs">{c.model.name}</span>
                  </>
                }
              />
              <Tiles tiles={tiles(c, lines, approvalRef)} />
              <DescriptionSection card={c} trainedUnder={trainedUnder} />
              <BenchmarkSection card={c} progress={progress.data} progressFailed={!!progress.error} />
              <EvaluationsSection card={c} />
              <DecisionTrail card={c} candidateRef={approvalRef} />
              <Section title="Feature importance">
                <FeatureImportance rows={c.feature_importance} engineered={c.description?.engineered ?? []} modelType={c.description?.model_type} />
              </Section>
              <Section title="Lineage from data to decision" note="What this version was built from and what it has been through. Cards link to where the evidence lives.">
                <Card>
                  {lineage.isLoading ? (
                    <Loading height={200} />
                  ) : lineage.error ? (
                    <ErrorState error={lineage.error} />
                  ) : lineage.data ? (
                    <LineageFlow graph={lineage.data} current={c.model} nothingServing={status.data ? status.data.serving == null : undefined} />
                  ) : (
                    <EmptyState title="No lineage recorded" />
                  )}
                </Card>
              </Section>
              <Section title="Registry tags" note="The raw tags stored on this version in the model registry.">
                <Card>
                  {Object.keys(c.tags).length === 0 ? (
                    <span className="muted small">No tags.</span>
                  ) : (
                    <KeyValue
                      items={Object.entries(c.tags)
                        .sort(([a], [b]) => a.localeCompare(b))
                        .map(([k, v]) => [
                          <span key={k} className="mono">
                            {k}
                          </span>,
                          k === "cycle_id" ? (
                            <Link key={k} className="mono" to={links.cycle(v)}>
                              {v}
                            </Link>
                          ) : k === "definition_version" ? (
                            <DefinitionBadge key={k} def={def} version={v} />
                          ) : (
                            <span key={k} className="mono">
                              {v}
                            </span>
                          ),
                        ])}
                    />
                  )}
                </Card>
              </Section>
            </>
          );
        }}
      </DetailView>
    </Page>
  );
}

const STATUS_PHRASE: Record<ModelStatus, string> = {
  serving: "is serving decisions",
  champion: "is the champion",
  challenger: "is the challenger",
  candidate: "is a candidate",
  baseline: "is a baseline",
  retired: "is retired",
  superseded: "is superseded",
};

function modelSummary(card: ModelCard, def: DefinitionRef | undefined, lines: BenchLine[], replaced: boolean): string {
  const latest = [...card.evaluations].sort((a, b) => b.ts.localeCompare(a.ts))[0];
  const scope = def ? ` for ${def.summary}${replaced ? " (a replaced definition)" : ""}` : "";
  let evidence: string;
  if (!latest) evidence = "the harness has not evaluated it, so there is no validation result";
  else if (isBaselineRef(latest.candidate_ref)) evidence = `it sets the validation reference for later candidates (AUC ${fmtAuc(latest.val_auc)})`;
  else evidence = latest.passed_validation ? `it passed validation with AUC ${fmtAuc(latest.val_auc)}` : `it did not pass validation (AUC ${fmtAuc(latest.val_auc)})`;
  const line = focusLine(lines);
  const bench = line ? vsBestSentence(line) : "";
  let s = `${card.model.label} ${STATUS_PHRASE[card.status]}${scope}: ${evidence}`;
  // "but" only when the evidence clause is a positive claim about a candidate; a baseline or a failure reads better with a semicolon
  const positive = !!latest && !isBaselineRef(latest.candidate_ref) && latest.passed_validation;
  if (bench && line) s += line.isBest || !positive ? `; ${bench}` : `, but ${bench}`;
  return `${s}.`;
}

function dpdOf(label: string): string {
  return label.split(" ")[0];
}

function tiles(card: ModelCard, lines: BenchLine[], approvalRef: string | null): Tile[] {
  const out: Tile[] = [];
  const latest = [...card.evaluations].sort((a, b) => b.ts.localeCompare(a.ts))[0];
  if (latest) {
    const baseline = isBaselineRef(latest.candidate_ref);
    out.push({
      key: "val",
      label: "Validation AUC",
      value: fmtAuc(latest.val_auc),
      sub: baseline ? "reference for later candidates" : `${latest.passed_validation ? "passed" : "did not pass"}; ${latest.n_tests} test${latest.n_tests === 1 ? "" : "s"} counted`,
      tone: baseline ? null : latest.passed_validation ? "good" : "warn",
      href: links.evaluation(latest.eval_id),
    });
  } else {
    out.push({ key: "val", label: "Validation AUC", value: "—", sub: "not evaluated by the harness", tone: "warn" });
  }
  const line = focusLine(lines);
  if (line?.cell) {
    let sub: string;
    if (line.isBest) {
      const v = line.vsBest ? noiseVerdict(line.vsBest.diff) : null;
      sub = `highest on this benchmark${v && v.tone === "warn" ? "; within noise of the runner-up" : ""}`;
    } else if (line.best) {
      const v = line.vsBest ? noiseVerdict(line.vsBest.diff) : null;
      sub = `best is ${line.best.model.label} (${fmtAuc(line.best.cell.auc)}); gap ${line.vsBest ? fmtDiff(line.vsBest.diff.estimate) : "—"}${v ? `, ${v.text}` : ""}`;
    } else {
      sub = "on the benchmark ledger";
    }
    out.push({ key: "bench", label: `Same-loans AUC, ${dpdOf(line.label)} DPD`, value: fmtAuc(line.cell.auc), sub, href: "/progress" });
  } else {
    out.push({ key: "bench", label: "Same-loans AUC", value: "—", sub: "not on the benchmark ledger yet", href: "/progress" });
  }
  const gateHint = !latest ? "needs a validation result first" : approvalRef ? "run from Approvals" : "reference model; not sent for approval";
  out.push(
    card.gate
      ? { key: "gate", label: "Holdout gate", value: card.gate.passed ? "Passed" : "Failed", sub: `holdout AUC ${fmtAuc(card.gate.holdout_auc)}`, tone: card.gate.passed ? "good" : "crit", href: approvalRef ? links.approval(approvalRef) : null }
      : { key: "gate", label: "Holdout gate", value: "Not run", sub: gateHint, href: approvalRef ? links.approval(approvalRef) : null },
  );
  const a = card.approvals[0];
  out.push(
    a
      ? { key: "appr", label: "Decision", value: a.decision.startsWith("approve") ? "Approved" : a.decision.startsWith("reject") ? "Rejected" : a.decision, sub: `by ${a.approver}`, tone: a.decision.startsWith("approve") ? "good" : "crit", href: approvalRef ? links.approval(approvalRef) : null }
      : { key: "appr", label: "Decision", value: "None yet", sub: "no person has decided" },
  );
  return out;
}

