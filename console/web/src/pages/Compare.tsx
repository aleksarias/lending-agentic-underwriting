/**
 * Compare two dates: the version vector at each instant, component by component, and the events between them.
 *
 * A version vector is the set of versions of everything that can change how the system behaves. The API reports, for
 * each component, its version at the first instant and at the second. Both instants are UTC and live in the URL
 * (?from=&to=) so a comparison can be shared; the defaults are the first definition activation and the moment the page
 * opened.
 */
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useChanges, useDefinitions } from "../api/hooks";
import type { ChangeSet, DefinitionVersion } from "../api/types";
import { Controls } from "../components/Compare/Controls";
import "../components/Compare/Compare.css";
import { VectorTable } from "../components/Compare/VectorTable";
import { describeChange, isConfig } from "../components/Compare/components";
import {
  apiInstant,
  buildPresets,
  ceilSecond,
  floorSecond,
  fmtInstant,
  formatInstant,
  parseInstant,
  type Preset,
} from "../components/Compare/instants";
import { inActivationOrder } from "../components/Definitions/labels";
import { timelineRows } from "../components/History/eras";
import { EventList } from "../components/lists";
import { Card, EmptyState, Page, PageHeader, QueryView, Section } from "../components/ui";

const DAY = 24 * 3600 * 1000;
/** The API returns at most this many events between two instants. */
const EVENT_LIMIT = 300;
const EVENT_PAGE = 50;

export default function Compare() {
  const definitions = useDefinitions();
  const [params, setParams] = useSearchParams();
  // "Now" is taken once, so the query key does not change on every render.
  const [openedAt] = useState(() => floorSecond(Date.now()));

  const defs = definitions.data ?? [];
  const activated = inActivationOrder(defs).filter((d) => d.active_from);
  const fromUrl = parseInstant(params.get("from"));
  const toUrl = parseInstant(params.get("to"));
  const from = fromUrl ?? (activated.length ? ceilSecond(Date.parse(activated[0].active_from!)) : openedAt - 7 * DAY);
  const to = toUrl ?? openedAt;
  const reversed = from > to;
  const [lo, hi] = reversed ? [to, from] : [from, to];

  // Wait for the definitions so the default start date is settled before the first request.
  const changes = useChanges(definitions.isLoading ? null : apiInstant(lo), definitions.isLoading ? null : apiInstant(hi));

  const setParam = (key: "from" | "to", value: string) => {
    const t = parseInstant(value);
    if (t == null) return;
    // Rebuilt from valid values only, so a stale or malformed date in the link does not linger in the URL.
    const next = new URLSearchParams();
    const f = key === "from" ? t : fromUrl;
    const u = key === "to" ? t : toUrl;
    if (f != null) next.set("from", formatInstant(f));
    if (u != null) next.set("to", formatInstant(u));
    setParams(next, { replace: true });
  };
  const applyPreset = (p: Preset) => setParams(new URLSearchParams({ from: formatInstant(p.from), to: formatInstant(p.to) }));

  return (
    <Page>
      <PageHeader
        eyebrow="Over time"
        title="Compare two dates"
        summary={changes.data ? summarise(changes.data, defs) : "Pick two dates to see which versions of the definition, data, models, configuration and code changed between them."}
        meta={<span>All times UTC</span>}
        actions={
          <Link className="btn" to="/history">
            Back to History
          </Link>
        }
      />

      <Section title="Choose the two dates">
        <Card>
          <Controls
            from={from}
            to={to}
            fromInUrl={fromUrl != null}
            toInUrl={toUrl != null}
            presets={buildPresets(defs, openedAt)}
            reversed={reversed}
            onFrom={(v) => setParam("from", v)}
            onTo={(v) => setParam("to", v)}
            onPreset={applyPreset}
            onReset={() => setParams(new URLSearchParams(), { replace: true })}
          />
          {definitions.error && (
            <div className="small" role="status" style={{ marginTop: 10 }}>
              The definitions could not be loaded, so the presets are unavailable and definition versions appear as hashes.
            </div>
          )}
        </Card>
      </Section>

      <QueryView query={changes} loadingHeight={260}>
        {(cs) => <Result cs={cs} defs={defs} />}
      </QueryView>
    </Page>
  );
}

function Result({ cs, defs }: { cs: ChangeSet; defs: DefinitionVersion[] }) {
  const [shown, setShown] = useState(EVENT_PAGE);
  const core = cs.components.filter((c) => !isConfig(c.component));
  const config = cs.components.filter((c) => isConfig(c.component));
  const events = timelineRows(cs.events_between);
  return (
    <>
      <Section
        title="Version vector: before and after"
        note="A version vector is the list of versions of everything that can change how the system behaves: the definition of default, the data, the models, thresholds and budgets, agent prompts and code. Comparing two instants shows which parts changed in between."
      >
        <div className="stack compare-table">
          <VectorTable components={core} defs={defs} label="Definition, data and models" />
          {config.length > 0 && (
            <>
              <h3 className="compare-sub">Configuration, prompts and code</h3>
              <VectorTable components={config} defs={defs} label="Configuration, prompts and code" />
            </>
          )}
        </div>
        <div className="xs muted">
          A configuration component is recorded when its content first appears or changes. “First recorded” means nothing had been recorded by the first date, not that the
          component did not exist. Policy cut-offs and knock-outs are not versioned yet, so they cannot appear here.
        </div>
      </Section>

      <Section
        title="Events between the two dates"
        note={`After ${fmtInstant(cs.from < cs.to ? cs.from : cs.to)}, up to and including ${fmtInstant(cs.from < cs.to ? cs.to : cs.from)}. Newest first.`}
      >
        {events.length === 0 ? (
          <EmptyState title="No events between these dates">Nothing was recorded in this period. Events appear as the pipeline, agents, harness and people act.</EmptyState>
        ) : (
          <Card>
            <EventList events={events.slice(0, shown)} />
            <div className="row between small muted" style={{ marginTop: 8 }}>
              <span>
                Showing {Math.min(shown, events.length)} of {events.length} event{events.length === 1 ? "" : "s"}
                {events.length >= EVENT_LIMIT ? `. The API returns at most ${EVENT_LIMIT} events for a range, so narrow the dates to see the rest` : ""}.
              </span>
              {events.length > shown && (
                <button type="button" className="btn small" onClick={() => setShown((n) => n + EVENT_PAGE)}>
                  Show {Math.min(EVENT_PAGE, events.length - shown)} more
                </button>
              )}
            </div>
          </Card>
        )}
      </Section>
    </>
  );
}

/** One plain-language sentence: how many tracked components changed, which ones matter most, how many events. */
function summarise(cs: ChangeSet, defs: DefinitionVersion[]): string {
  const [a, b] = cs.from < cs.to ? [cs.from, cs.to] : [cs.to, cs.from];
  // A configuration component with nothing before it was first recorded in the period; that is record-keeping, not a change.
  const firstRecorded = cs.components.filter((c) => c.changed && isConfig(c.component) && c.before == null);
  const changed = cs.components.filter((c) => c.changed && !(isConfig(c.component) && c.before == null));
  const headline = changed.filter((c) => !isConfig(c.component)).map((c) => describeChange(c, defs));
  const n = cs.events_between.length;
  const events = `${n}${n >= EVENT_LIMIT ? " or more" : ""} event${n === 1 ? " was" : "s were"} recorded in between`;
  const span = `Between ${fmtInstant(a)} and ${fmtInstant(b)}`;
  const recorded = firstRecorded.length
    ? `${firstRecorded.length} configuration component${firstRecorded.length === 1 ? " was" : "s were"} first recorded`
    : "";
  if (changed.length === 0) {
    return `${span}, none of the ${cs.components.length} tracked components changed${recorded ? `, but ${recorded}` : ""}; ${events}.`;
  }
  const list = headline.length === 0 ? "" : `, including ${headline.length === 1 ? headline[0] : `${headline.slice(0, -1).join(", ")} and ${headline[headline.length - 1]}`}`;
  return `${span}, ${changed.length} of ${cs.components.length} tracked components changed${list}${recorded ? `, and ${recorded}` : ""}; ${events}.`;
}
