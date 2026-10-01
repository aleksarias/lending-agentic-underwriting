/**
 * Screen 9, detail — everything the harness measured for one evaluation of one candidate. All of it is measured
 * (no agent input). The result and checks stay on top; the detail sits in tabs so the page stays navigable.
 */
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useDefinitions, useEvaluation, useModels, useSettings } from "../api/hooks";
import type { EvaluationDetail as Evaluation, Tile } from "../api/types";
import { ChecksSection } from "../components/EvaluationDetail/ChecksSection";
import { ControlsTab } from "../components/EvaluationDetail/ControlsTab";
import { DiscriminationTab } from "../components/EvaluationDetail/DiscriminationTab";
import { FairnessTab } from "../components/EvaluationDetail/FairnessTab";
import { FeaturesTab } from "../components/EvaluationDetail/FeaturesTab";
import { StabilityTab } from "../components/EvaluationDetail/StabilityTab";
import { DetailView, NotFoundState, checkName, definitionRefOf, isBaselineRef, modelOfRef } from "../components/Models/shared";
import { limitsFrom } from "../components/Performance/thresholds";
import { DefinitionBadge, Page, PageHeader, Tabs, Tiles, links } from "../components/ui";
import { fmtAuc, fmtDateTime, fmtDiff, fmtNum, fmtPct, refLabel } from "../lib/format";

const TABS = [
  { key: "discrimination", label: "Discrimination and calibration" },
  { key: "stability", label: "Stability" },
  { key: "fairness", label: "Fairness" },
  { key: "controls", label: "Leakage and reason codes" },
  { key: "features", label: "Features and reference" },
] as const;
type TabKey = (typeof TABS)[number]["key"];

export default function EvaluationDetail() {
  const { evalId } = useParams();
  const ev = useEvaluation(evalId);
  const models = useModels();
  const defs = useDefinitions();
  const settings = useSettings();
  const [params, setParams] = useSearchParams();
  const tab: TabKey = TABS.some((t) => t.key === params.get("tab")) ? (params.get("tab") as TabKey) : "discrimination";
  const setTab = (k: TabKey) => {
    const next = new URLSearchParams(params);
    if (k === "discrimination") next.delete("tab");
    else next.set("tab", k);
    setParams(next, { replace: true });
  };
  const limits = limitsFrom(settings.data);

  return (
    <Page>
      <DetailView
        query={ev}
        loadingHeight={360}
        header={<PageHeader eyebrow="Models and evidence" title="Evaluation" />}
        notFound={
          <>
            <PageHeader eyebrow="Models and evidence" title="Evaluation not found" />
            <NotFoundState title="No such evaluation" back={{ to: "/performance", label: "Back to performance" }}>
              There is no evaluation <code>{evalId}</code>. Evaluations are listed on the Performance screen.
            </NotFoundState>
          </>
        }
      >
        {(e) => {
          const def = defs.data?.map(definitionRefOf).find((d) => d.version === e.definition_version);
          const model = modelOfRef(models.data, e.candidate_ref);
          const baseline = isBaselineRef(e.candidate_ref);
          const split = defs.data?.find((d) => d.version === e.definition_version)?.split;
          return (
            <>
              <PageHeader
                eyebrow="Models and evidence"
                title={`Evaluation of ${refLabel(e.candidate_ref)}`}
                summary={summarySentence(e)}
                meta={
                  <>
                    <DefinitionBadge def={def} version={e.definition_version} />
                    <span>Evaluated {fmtDateTime(e.ts)}</span>
                    <span className="mono">{e.eval_id}</span>
                    <span>Measured by the harness, no agent input</span>
                    {model && <Link to={links.model(model.name, model.version)}>Open model {model.label}</Link>}
                    {!baseline && <Link to={links.approval(e.candidate_ref)}>Approval evidence</Link>}
                    <Link to={def ? `/performance?def=${def.short}` : "/performance"}>All evaluations under this definition</Link>
                  </>
                }
              />
              <Tiles tiles={tiles(e, split ? `${split.validation[0]} to ${split.validation[1]}` : null)} />
              <ChecksSection e={e} limits={limits} />
              <Tabs tabs={TABS.map((t) => ({ key: t.key, label: t.label }))} value={tab} onChange={setTab} />
              <div role="tabpanel" aria-label={TABS.find((t) => t.key === tab)?.label}>
                {tab === "discrimination" && <DiscriminationTab e={e} limits={limits} />}
                {tab === "stability" && <StabilityTab e={e} limits={limits} />}
                {tab === "fairness" && <FairnessTab e={e} limits={limits} />}
                {tab === "controls" && <ControlsTab e={e} limits={limits} />}
                {tab === "features" && <FeaturesTab e={e} models={models.data} />}
              </div>
            </>
          );
        }}
      </DetailView>
    </Page>
  );
}

function refName(e: Evaluation): string {
  return referenceName(e) ?? "no reference";
}

function referenceName(e: Evaluation): string | null {
  const r = e.reference;
  if (r.kind === "none") return null;
  if (r.kind === "baseline") return `baseline v${r.model_version}`;
  if (r.kind === "champion") return `champion (production v${r.model_version})`;
  return `${r.kind}${r.model_version ? ` v${r.model_version}` : ""}`;
}

function summarySentence(e: Evaluation): string {
  const entries = Object.entries(e.checks);
  const failed = entries.filter(([, ok]) => !ok).map(([k]) => checkName(k).toLowerCase());
  const who = refLabel(e.candidate_ref);
  if (entries.length === 0) return `${who} has a validation AUC of ${fmtAuc(e.val_auc)}; no checks were recorded for this evaluation.`;
  const checks = failed.length ? `${failed.length} of ${entries.length} checks failed (${failed.join(", ")})` : `all ${entries.length} checks passed`;
  if (e.reference.auc == null) return `${who.charAt(0).toUpperCase()}${who.slice(1)} sets the reference that later candidates must beat: AUC ${fmtAuc(e.val_auc)} on the validation sample, and ${checks}.`;
  const head = e.passed_validation ? `${who} passed validation` : `${who} did not pass validation`;
  return `${head}: ${checks}; AUC ${fmtAuc(e.val_auc)} against a reference of ${fmtAuc(e.reference.auc)} (${referenceName(e)}) plus a required margin of ${fmtAuc(e.required_margin)}.`;
}

function tiles(e: Evaluation, validationWindow: string | null): Tile[] {
  const entries = Object.entries(e.checks);
  const failed = entries.filter(([, ok]) => !ok).map(([k]) => checkName(k));
  const ref = e.reference.auc;
  const out: Tile[] = [];
  out.push({
    key: "auc",
    label: "Validation AUC",
    value: fmtAuc(e.val_auc, 4),
    sub: ref == null ? "sets the reference for later candidates" : `reference ${fmtAuc(ref, 4)}, ${refName(e)}`,
    tone: e.passed_validation ? "good" : "warn",
  });
  if (ref != null) {
    const gain = e.val_auc - ref;
    const room = gain - e.required_margin;
    out.push({
      key: "gain",
      label: "Gain over the reference",
      value: fmtDiff(gain, 4),
      sub: `required ${fmtDiff(e.required_margin, 4)}; ${room >= 0 ? `cleared by ${fmtAuc(room, 4)}` : `short by ${fmtAuc(-room, 4)}`}`,
      tone: room >= 0 ? "good" : "warn",
    });
  }
  out.push({
    key: "checks",
    label: "Checks",
    value: `${entries.length - failed.length} of ${entries.length} passed`,
    sub: failed.length ? `failed: ${failed.join(", ")}` : entries.length ? "every check passed" : "none recorded",
    tone: entries.length === 0 ? null : failed.length ? "crit" : "good",
  });
  out.push({ key: "tests", label: "Validation tests counted", value: fmtNum(e.n_tests), sub: "when this candidate was evaluated" });
  if (e.validation.n != null) {
    out.push({
      key: "sample",
      label: "Validation sample",
      value: `${fmtNum(e.validation.n)} loans`,
      sub: `${e.validation.default_rate != null ? `default rate ${fmtPct(e.validation.default_rate, 1)}` : ""}${validationWindow ? `${e.validation.default_rate != null ? "; " : ""}${validationWindow} originations` : ""}`,
    });
  }
  return out;
}
