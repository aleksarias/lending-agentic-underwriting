/**
 * Instants for the Compare screen. The two dates live in the URL as "YYYY-MM-DDTHH:mm:ss" and are always UTC
 * (a datetime-local input has no zone, so the screen labels it UTC and reads it as UTC).
 */
import type { DefinitionVersion } from "../../api/types";
import { fmtDateTime } from "../../lib/format";
import { definitionLabel, inActivationOrder } from "../Definitions/labels";

const LOCAL = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/;

/** Epoch ms for "YYYY-MM-DDTHH:mm[:ss]" read as UTC; null when it is not a real date and time. */
export function parseInstant(value: string | null | undefined): number | null {
  const m = value ? LOCAL.exec(value.trim()) : null;
  if (!m) return null;
  const [y, mo, d, h, mi, s] = [m[1], m[2], m[3], m[4], m[5], m[6] ?? "0"].map(Number);
  const t = Date.UTC(y, mo - 1, d, h, mi, s);
  const back = new Date(t);
  // Date.UTC rolls 31 February over into March; a date that does not exist is not accepted.
  if (back.getUTCFullYear() !== y || back.getUTCMonth() !== mo - 1 || back.getUTCDate() !== d || back.getUTCHours() !== h || back.getUTCMinutes() !== mi) return null;
  return t;
}

/** "2026-09-30T14:30:31": the form used in the URL and in the date inputs. */
export const formatInstant = (ms: number): string => new Date(ms).toISOString().slice(0, 19);
/** Full ISO string with Z, for the API. */
export const apiInstant = (ms: number): string => new Date(ms).toISOString();

/**
 * "Sep 30, 2026, 03:10:11 PM UTC": the look of fmtDateTime with seconds, which a comparison window of a few seconds needs
 * (fmtDateTime stops at the minute).
 */
export function fmtInstant(value: number | string): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  });
}

export const floorSecond = (ms: number): number => Math.floor(ms / 1000) * 1000;
export const ceilSecond = (ms: number): number => Math.ceil(ms / 1000) * 1000;

export function compareHref(from: number, to: number): string {
  return `/history/compare?${new URLSearchParams({ from: formatInstant(from), to: formatInstant(to) }).toString()}`;
}

/**
 * The instants just before and just after a definition was activated. Activation times carry fractions of a second, so
 * the earlier one is rounded down and taken a second back, and the later one is rounded up: the "before" state then
 * holds the previous definition and the "after" state holds the new one.
 */
export function aroundActivation(activeFromIso: string): { from: number; to: number } {
  const t = Date.parse(activeFromIso);
  return { from: floorSecond(t) - 1000, to: ceilSecond(t) };
}

export interface Preset {
  key: string;
  label: string;
  detail: string;
  from: number;
  to: number;
}

/** Whole history, plus for every definition change the moment of the change and the stretch until the next change (or now). */
export function buildPresets(defs: DefinitionVersion[], now: number): Preset[] {
  const order = inActivationOrder(defs).filter((d) => d.active_from);
  if (order.length === 0) return [];
  const presets: Preset[] = [
    {
      key: "history",
      label: "Whole history",
      detail: `From the first definition activation, ${fmtDateTime(order[0].active_from)}, to now`,
      from: ceilSecond(Date.parse(order[0].active_from!)),
      to: now,
    },
  ];
  order.forEach((d, i) => {
    if (i === 0) return;
    const { from, to } = aroundActivation(d.active_from!);
    const next = order[i + 1];
    presets.push({
      key: `at-${d.version}`,
      label: `Before and after the change to ${definitionLabel(d)}`,
      detail: `Just before to just after ${fmtDateTime(d.active_from)}`,
      from,
      to,
    });
    presets.push({
      key: `through-${d.version}`,
      label: `Since the change to ${definitionLabel(d)}, until ${next ? "the next change" : "now"}`,
      detail: `From just before ${fmtDateTime(d.active_from)}${next ? ` to just before ${fmtDateTime(next.active_from)}` : " to now"}`,
      from,
      to: next ? floorSecond(Date.parse(next.active_from!)) - 1000 : now,
    });
  });
  return presets;
}
