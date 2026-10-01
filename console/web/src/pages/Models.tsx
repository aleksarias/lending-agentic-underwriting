/**
 * Screen 8 — Models: which model versions exist, under which definition of default, and which one (if any) is
 * making decisions. The registry is grouped by definition because models trained under different definitions are
 * not comparable on one axis; the benchmark ledger on Progress is the only place that re-scores them together.
 */
import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useDefinitions, useModels, useProgress } from "../api/hooks";
import type { DefinitionVersion, ModelStatus, ModelVersion, ProgressData } from "../api/types";
import { ModelGroup } from "../components/Models/ModelGroup";
import { RegistryFilters } from "../components/Models/RegistryFilters";
import { registryTiles, summarySentence } from "../components/Models/summary";
import { STATUS_HELP, STATUS_ORDER, definitionRefOf } from "../components/Models/shared";
import { DefinitionBadge, EmptyState, ErrorState, Loading, Page, PageHeader, Section, Tiles } from "../components/ui";
import { shortVersion } from "../lib/format";

export default function Models() {
  const models = useModels();
  const defs = useDefinitions();
  const progress = useProgress();
  return (
    <Page>
      {models.data === undefined ? (
        <>
          <PageHeader eyebrow="Models and evidence" title="Models" />
          {models.error ? <ErrorState error={models.error} /> : <Loading height={360} />}
        </>
      ) : (
        <ModelsBody list={models.data} defs={defs.data} progress={progress.data} />
      )}
    </Page>
  );
}

function ModelsBody({ list, defs, progress }: { list: ModelVersion[]; defs: DefinitionVersion[] | undefined; progress: ProgressData | undefined }) {
  const [params, setParams] = useSearchParams();
  const statusFilter = params.get("status") ?? "";
  const defFilter = params.get("def") ?? "";
  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  const refs = useMemo(() => (defs ?? []).map(definitionRefOf), [defs]);
  const active = defs?.find((d) => d.is_active);
  const bestKnown = progress?.verdict?.best_known ?? null;
  const matrix = progress?.benchmark ?? null;

  // model key -> the data version it was trained on, from the benchmark ledger (validation AUCs are only comparable
  // between models validated on the same sample)
  const dataVersionByKey = useMemo(() => {
    const out: Record<string, string> = {};
    for (const r of matrix?.rows ?? []) if (r.data_version) out[r.model.key] = shortVersion(r.data_version);
    return out;
  }, [matrix]);

  const scoredCount = (matrix?.rows ?? []).filter((r) => r.model.kind !== "reference").length;

  // Groups: the active definition first, then the others most recently active first, then models with no definition.
  const groupVersions = useMemo(() => {
    const present = Array.from(new Set(list.map((m) => m.model.definition_version ?? "")));
    const rank = (v: string) => (v === "" ? 1e6 : v === active?.version ? -1 : refs.findIndex((r) => r.version === v) >= 0 ? refs.findIndex((r) => r.version === v) : 1e5);
    return present.sort((a, b) => rank(a) - rank(b));
  }, [list, refs, active]);

  const matches = (m: ModelVersion) =>
    (!statusFilter || m.status === statusFilter) && (!defFilter || (m.model.definition_version ?? "").startsWith(defFilter));
  const shown = list.filter(matches);

  const statusCounts = STATUS_ORDER.map((s) => [s, list.filter((m) => m.status === s).length] as const).filter(([, n]) => n > 0);

  if (list.length === 0) {
    return (
      <>
        <PageHeader eyebrow="Models and evidence" title="Models" summary="No models are registered yet." />
        <EmptyState title="The registry is empty">
          Models appear here after the pipeline trains a baseline for the active definition of default and improvement cycles register candidates.
          Each version then shows its status, validation result and author.
        </EmptyState>
      </>
    );
  }

  const challenger = active ? list.find((m) => m.status === "challenger" && m.model.definition_version === active.version) : undefined;
  const serving = list.find((m) => m.status === "serving");
  const champion = list.find((m) => m.status === "champion");

  return (
    <>
      <PageHeader
        eyebrow="Models and evidence"
        title="Models"
        summary={summarySentence(list, groupVersions.length, !!active, challenger?.model, serving?.model, bestKnown)}
        meta={
          active ? (
            <>
              <span>Active definition of default</span>
              <DefinitionBadge def={definitionRefOf(active)} />
            </>
          ) : undefined
        }
      />

      <Tiles tiles={registryTiles(list, challenger, serving, champion, bestKnown, progress)} />

      <RegistryFilters
        total={list.length}
        shown={shown.length}
        statusCounts={statusCounts}
        statusFilter={statusFilter}
        defFilter={defFilter}
        definitions={groupVersions.filter((v) => v !== "").map((v) => ({ version: v, summary: refs.find((x) => x.version === v)?.summary ?? "definition", active: v === active?.version }))}
        onChange={setParam}
        onClear={() => setParams(new URLSearchParams(), { replace: true })}
      />

      {shown.length === 0 ? (
        <EmptyState
          title="No model versions match these filters"
          action={
            <button className="btn small" type="button" onClick={() => setParams(new URLSearchParams(), { replace: true })}>
              Clear filters
            </button>
          }
        >
          Try another status or definition of default.
        </EmptyState>
      ) : (
        groupVersions.map((v) => {
          const items = shown.filter((m) => (m.model.definition_version ?? "") === v);
          if (!items.length) return null;
          return (
            <ModelGroup
              key={v || "none"}
              version={v}
              def={refs.find((r) => r.version === v)}
              detail={defs?.find((d) => d.version === v)}
              isActive={!!active && v === active.version}
              models={items}
              bestKnownKey={bestKnown?.key ?? null}
              scoredCount={scoredCount}
              dataVersionByKey={dataVersionByKey}
            />
          );
        })
      )}

      <Section title="Reading this table">
        <div className="small muted stack">
          <div>
            Validation AUC is measured on each model’s own validation sample, so two AUCs are comparable only when the definition of default and the data version
            (shown under the AUC) are the same. To compare models fairly, use the benchmark ledger on{" "}
            <Link to="/progress">Progress</Link>, which re-scores every model on the same loans.
          </div>
          <details className="models-legend">
            <summary>What the statuses mean</summary>
            <dl>
              {STATUS_ORDER.map((s: ModelStatus) => (
                <div key={s} style={{ display: "contents" }}>
                  <dt>{s}</dt>
                  <dd>{STATUS_HELP[s]}</dd>
                </div>
              ))}
            </dl>
          </details>
        </div>
      </Section>
    </>
  );
}
