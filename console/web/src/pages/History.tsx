/**
 * Screen 5 — History and change log: what changed, when, and under which definition of default.
 *
 * The timeline is assembled by the API from every table that records something happening (definitions, data loads,
 * builds, cycles, evaluations, gates, approvals, alerts, config, agent reports). It is banded by definition era, filtered
 * by event type and definition (both kept in the URL), and loaded a page at a time. Below it, one row per improvement
 * cycle. Agent reports and verdicts are claims and are marked proposed; evaluations, gates and alerts are measurements.
 */
import { Link, useSearchParams } from "react-router-dom";
import { useCycles, useDefinitions, useModels } from "../api/hooks";
import type { CycleSummary, DefinitionVersion, EventType } from "../api/types";
import { definitionLabel, definitionRefOf, inActivationOrder } from "../components/Definitions/labels";
import { CyclesTable } from "../components/History/CyclesTable";
import { EventFilters } from "../components/History/EventFilters";
import { ALL_TYPES, parseTypes } from "../components/History/groups";
import { Timeline } from "../components/History/Timeline";
import "../components/History/History.css";
import { Card, DefinitionBadge, EmptyState, Loading, Page, PageHeader, QueryView, Section } from "../components/ui";
import { fmtAgo, fmtDate, fmtUsd } from "../lib/format";

export default function History() {
  const definitions = useDefinitions();
  const cycles = useCycles();
  const models = useModels();
  const [params, setParams] = useSearchParams();

  const defs = definitions.data ?? [];
  const types = parseTypes(params.get("types"));
  const requested = params.get("definition");
  const resolved = requested ? resolveDefinition(defs, requested) : null;
  // A link can carry a definition this system never recorded. The API would then silently return every event, so the
  // page ignores it and says so instead of claiming a filter that is not applied.
  const stale = !!requested && !definitions.isLoading && !resolved;
  const definition = resolved?.version ?? null;

  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    setParams(next, { replace: true });
  };
  const setTypes = (next: EventType[]) => update({ types: next.length > 0 && next.length < ALL_TYPES.length ? next.join(",") : null });
  const clear = () => update({ types: null, definition: null });

  const active = defs.find((d) => d.is_active);
  const visibleCycles = (cycles.data ?? []).filter((c) => !definition || c.definition_version === definition);

  return (
    <Page>
      <PageHeader
        eyebrow="Over time"
        title="History and change log"
        summary={
          definitions.data && cycles.data
            ? summarise(definitions.data, cycles.data)
            : "Every change to the definition of default, the data, the models, the agents' cycles, approvals and configuration, newest first."
        }
        meta={
          <>
            <span>Definition of default now</span>
            {active ? <DefinitionBadge def={definitionRefOf(active)} /> : <span>none activated</span>}
            <span>· all times UTC</span>
          </>
        }
        actions={
          <Link className="btn primary history-compare-link" to="/history/compare">
            Compare two dates
          </Link>
        }
      />

      <Section
        title="Timeline"
        note="Every change and result, newest first, grouped by the definition of default in effect. Agent reports are claims (marked proposed); evaluations, holdout gates, evidence runs and alerts are measurements."
        right={
          <a className="small" href="#improvement-cycles">
            Jump to improvement cycles
          </a>
        }
      >
        <Card>
          {definitions.isLoading ? (
            <Loading height={120} label="Loading filters" />
          ) : (
            <>
              {definitions.error && (
                <div className="small" role="status" style={{ marginBottom: 10 }}>
                  The definitions could not be loaded, so events are grouped only by the definition recorded on each one, without the dates it was active, and the definition filter is unavailable.
                </div>
              )}
              <EventFilters
                types={types}
                definition={definition}
                defs={defs}
                staleDefinition={stale}
                onTypes={setTypes}
                onDefinition={(v) => update({ definition: v })}
                onClear={clear}
              />
            </>
          )}
        </Card>
        {!definitions.isLoading && <Timeline key={`${types.join(",")}|${definition ?? ""}`} filters={{ types, definition }} defs={defs} onClear={clear} />}
      </Section>

      <Section
        title="Improvement cycles"
        id="improvement-cycles"
        note={
          <>
            One row per cycle of agent research. The validation result is measured by the harness; the red-team and compliance verdicts are agent opinions
            (proposed). Open a cycle for its plan, steps and full trace.
            {definition && " Showing only cycles run under the selected definition."}
          </>
        }
      >
        <QueryView query={cycles} loadingHeight={160}>
          {(all) =>
            all.length === 0 ? (
              <EmptyState title="No improvement cycles yet">
                A cycle starts when someone runs <code>lau run-cycle</code>, or when a definition change or alert queues one. Each cycle appears here with its plan, verdicts and spend.
              </EmptyState>
            ) : visibleCycles.length === 0 ? (
              <EmptyState
                title="No cycles under this definition"
                action={
                  <button type="button" className="btn small" onClick={clear}>
                    Clear filters
                  </button>
                }
              >
                None of the {all.length} cycle{all.length === 1 ? "" : "s"} ran under the selected definition.
              </EmptyState>
            ) : (
              <>
                <div className="small muted">{cycleTotals(visibleCycles)}</div>
                {models.error && <div className="small muted">The model list could not be loaded, so challengers are shown without links to their model pages.</div>}
                <CyclesTable cycles={visibleCycles} defs={defs} models={models.data ?? []} />
              </>
            )
          }
        </QueryView>
      </Section>
    </Page>
  );
}

/** Exact version or a unique prefix, the way the API resolves a definition. */
function resolveDefinition(defs: DefinitionVersion[], raw: string): DefinitionVersion | null {
  const exact = defs.find((d) => d.version === raw);
  if (exact) return exact;
  const hits = defs.filter((d) => d.version.startsWith(raw));
  return hits.length === 1 ? hits[0] : null;
}

/** One plain-language sentence: how the definition has changed and how many cycles have run. */
function summarise(defs: DefinitionVersion[], cycles: CycleSummary[]): string {
  const activated = inActivationOrder(defs).filter((d) => d.active_from);
  const current = defs.find((d) => d.is_active) ?? activated[activated.length - 1];
  let first: string;
  if (!current || activated.length === 0) first = "No definition of default has been activated yet";
  else if (activated.length === 1) first = `${definitionLabel(current)} has been the definition of default since ${fmtDate(current.active_from)}`;
  else {
    const changes = activated.length - 1;
    first = `The definition of default changed ${changes === 1 ? "once" : `${changes} times`}, most recently to ${definitionLabel(current)} on ${fmtDate(current.active_from)}`;
  }
  if (cycles.length === 0) return `${first}, and no improvement cycle has run yet.`;
  const completed = cycles.filter((c) => c.status === "completed").length;
  const latest = cycles.reduce((a, c) => (c.started_at > a.started_at ? c : a));
  return `${first}, and ${cycles.length} improvement cycle${cycles.length === 1 ? " has" : "s have"} run (${completed} completed), the latest started ${fmtAgo(latest.started_at)}.`;
}

function cycleTotals(cycles: CycleSummary[]): string {
  const spend = cycles.reduce((s, c) => s + (c.anthropic_usd ?? 0), 0);
  const challengers = cycles.filter((c) => c.challenger).length;
  const passed = cycles.filter((c) => c.challenger_passed_validation).length;
  return `${cycles.length} cycle${cycles.length === 1 ? "" : "s"}: ${challengers} proposed a challenger and ${passed} of those passed validation. Agent spend in these cycles: ${fmtUsd(spend)}.`;
}
