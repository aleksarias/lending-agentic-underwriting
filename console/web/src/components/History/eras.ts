/**
 * Pure logic for the history timeline: which definition era an event belongs to, how a page of events is banded by
 * era, and how the next page is requested.
 */
import type { DefinitionVersion, EventItem } from "../../api/types";
import { fmtDateTime } from "../../lib/format";
import { definitionAt } from "../Definitions/labels";

/** Era key for events dated before the first definition was activated. */
export const NO_ERA = "none";

export interface EraBand {
  /** Definition version, or NO_ERA. */
  era: string;
  /** True when this band opens an era; false when it continues the band that ended the previous page. */
  header: boolean;
  events: EventItem[];
}

/**
 * The era of an event is the definition it is stamped with. Events that belong to no definition (configuration records,
 * data loads) take the definition that was active at their timestamp, so they never split a band of their own.
 */
export function eraOf(e: EventItem, defs: DefinitionVersion[]): string {
  return e.definition_version ?? definitionAt(defs, Date.parse(e.ts))?.version ?? NO_ERA;
}

/** Split newest-first events into runs of the same era. `previousEra` is the era the previous page ended in. */
export function bandByEra(events: EventItem[], defs: DefinitionVersion[], previousEra: string | null): EraBand[] {
  const bands: EraBand[] = [];
  for (const e of events) {
    const era = eraOf(e, defs);
    const last = bands[bands.length - 1];
    if (last && last.era === era) last.events.push(e);
    else bands.push({ era, header: !(bands.length === 0 && previousEra === era), events: [e] });
  }
  return bands;
}

/** Identity of an event across pages. Ids alone repeat (the same data version can be loaded twice). */
export const eventKey = (e: EventItem): string => `${e.id}|${e.ts}`;

/**
 * Rows for EventList. Two changes: React keys must be unique (ids repeat), and the exact UTC time is written into the
 * detail line because EventList only shows a relative time ("5 h ago") and the change log is read by exact time.
 */
export function timelineRows(events: EventItem[]): EventItem[] {
  return events.map((e) => ({
    ...e,
    id: `${e.id}@${e.ts}`,
    detail: [fmtDateTime(e.ts), e.detail].filter(Boolean).join(" · "),
  }));
}

/**
 * Cursor for the next (older) page. `next_before` is an exact cursor (timestamp and event id), so events that share a
 * timestamp at the page boundary are neither skipped nor repeated. `lossy` is kept for the caller's banner and is
 * always false now.
 */
export function olderCursor(nextBefore: string, _pageHadNewEvents: boolean): { before: string; lossy: boolean } {
  return { before: nextBefore, lossy: false };
}
