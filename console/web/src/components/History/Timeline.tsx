/**
 * The unified timeline: events newest first, banded by definition era, loaded a page at a time.
 *
 * Each page is its own component that calls useEvents for its cursor and renders the next page below itself once
 * "Load older events" is pressed. That lets pages accumulate without any page calling the API outside the hooks. A page
 * is told which events earlier pages already showed (so a repeated boundary event is dropped) and which era the previous
 * page ended in (so an era that continues across a page boundary gets one header, not two).
 */
import { useMemo, useState } from "react";
import { useEvents } from "../../api/hooks";
import type { DefinitionVersion, EventType } from "../../api/types";
import { fmtDateTime } from "../../lib/format";
import { EventList } from "../lists";
import { EmptyState, ErrorState, Loading } from "../ui";
import { EraHeader } from "./EraHeader";
import { bandByEra, eventKey, olderCursor, timelineRows } from "./eras";
import { TYPE_HINTS, typeLabel } from "./groups";

export const PAGE_SIZE = 50;

export interface TimelineFilters {
  types: EventType[];
  definition: string | null;
}

const NOTHING_SEEN: ReadonlySet<string> = new Set();

/** Render with `key` set to the filters, so a change of filters starts again from the newest page. */
export function Timeline(props: { filters: TimelineFilters; defs: DefinitionVersion[]; onClear: () => void }) {
  return (
    <div className="card flush history-timeline">
      <EventPage
        filters={props.filters}
        defs={props.defs}
        before={undefined}
        seen={NOTHING_SEEN}
        previousEra={null}
        shownBefore={0}
        lossy={false}
        onClear={props.onClear}
      />
    </div>
  );
}

interface PageProps {
  filters: TimelineFilters;
  defs: DefinitionVersion[];
  /** Cursor for this page: only events older than this. Undefined for the newest page. */
  before: string | undefined;
  seen: ReadonlySet<string>;
  previousEra: string | null;
  shownBefore: number;
  /** The cursor had to skip events that share one timestamp. */
  lossy: boolean;
  onClear: () => void;
}

function EventPage({ filters, defs, before, seen, previousEra, shownBefore, lossy, onClear }: PageProps) {
  const query = useEvents({
    types: filters.types.join(",") || undefined,
    definition: filters.definition ?? undefined,
    before,
    limit: PAGE_SIZE,
  });
  const [older, setOlder] = useState(false);
  const page = query.data;
  const fresh = useMemo(() => (page ? page.events.filter((e) => !seen.has(eventKey(e))) : []), [page, seen]);
  const bands = useMemo(() => bandByEra(fresh, defs, previousEra), [fresh, defs, previousEra]);
  const seenNow = useMemo(() => new Set([...seen, ...fresh.map(eventKey)]), [seen, fresh]);

  if (query.isLoading || (!page && !query.error)) return <Loading height={shownBefore ? 120 : 300} label="Loading events" />;
  if (query.error || !page) {
    return (
      <div className="history-state stack">
        <ErrorState error={query.error} />
        <div>
          <button type="button" className="btn small" onClick={() => void query.refetch()}>
            Try again
          </button>
        </div>
      </div>
    );
  }

  const shown = shownBefore + fresh.length;
  if (shown === 0) {
    const filtered = filters.types.length > 0 || filters.definition !== null;
    return (
      <div className="history-state">
        <EmptyState
          title={filtered ? "No events match these filters" : "No events yet"}
          action={
            filtered ? (
              <button type="button" className="btn small" onClick={onClear}>
                Clear filters
              </button>
            ) : undefined
          }
        >
          {filtered
            ? "Try selecting more event types or all definitions."
            : "Events appear as the pipeline builds, agents run cycles, the harness evaluates candidates and people approve changes."}
          {filters.types.length > 0 && (
            <ul className="plain" style={{ textAlign: "left", marginTop: 8 }}>
              {filters.types.map((t) => (
                <li key={t}>
                  <strong>{typeLabel(t)}.</strong> {TYPE_HINTS[t]}
                </li>
              ))}
            </ul>
          )}
        </EmptyState>
      </div>
    );
  }

  const cursor = page.next_before ? olderCursor(page.next_before, fresh.length > 0) : null;
  const lastEra = bands.length ? bands[bands.length - 1].era : previousEra;
  const oldest = fresh.length ? fresh[fresh.length - 1].ts : null;
  // A page of nothing but events already shown: keep going rather than ask for a second click.
  const showOlder = !!cursor && (older || fresh.length === 0);

  return (
    <>
      {shownBefore > 0 && fresh.length > 0 && (
        // Pressing "Load older events" replaces the button, so tell assistive technology what arrived.
        <div className="sr-only" role="status">
          Loaded {fresh.length} older event{fresh.length === 1 ? "" : "s"}, back to {fmtDateTime(fresh[fresh.length - 1].ts)}.
        </div>
      )}
      {lossy && (
        <div className="history-state small" role="status">
          More events share one timestamp than fit on a page, so some events recorded at that instant may be missing here. Narrow the filters to see them.
        </div>
      )}
      {bands.map((band, i) => (
        <div className={`history-band${band.header ? "" : " continued"}`} key={`${i}-${band.era}-${band.events[0].id}`}>
          {band.header && <EraHeader era={band.era} defs={defs} events={band.events} />}
          <div className="history-band-body">
            {/* The era header states the definition, so the per-row definition link is left out. */}
            <EventList events={timelineRows(band.events)} showDefinition={false} />
          </div>
        </div>
      ))}
      {showOlder && cursor ? (
        <EventPage
          filters={filters}
          defs={defs}
          before={cursor.before}
          seen={seenNow}
          previousEra={lastEra}
          shownBefore={shown}
          lossy={cursor.lossy}
          onClear={onClear}
        />
      ) : (
        <div className="history-foot">
          <span className="small muted">
            {shown} event{shown === 1 ? "" : "s"} shown{oldest ? `, back to ${fmtDateTime(oldest)}` : ""}.
            {cursor ? "" : " That is the start of the recorded history for these filters."}
          </span>
          {cursor && (
            <button type="button" className="btn" onClick={() => setOlder(true)}>
              Load older events
            </button>
          )}
        </div>
      )}
    </>
  );
}
