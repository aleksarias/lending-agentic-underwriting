/**
 * Helpers shared by the FE2 screens (Live activity, Upcoming, Agents, Report detail, Lessons, Features, Cost, Settings).
 * They are generic and are candidates for promotion to the shared components; they live here because this folder
 * belongs to the FE2 screens and shared files are owned by the integrator.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useDefinitions, useStatus } from "../../api/hooks";
import type { DefinitionRef, DefinitionVersion, ModelRef, Tone } from "../../api/types";
import { fmtAgo, fmtDateTime, reviewTone, shortVersion, titleCase } from "../../lib/format";
import { DefinitionBadge, ModelBadge, Pill, links } from "../ui";

// ------------------------------------------------------------------------------------------------ names and labels
const ROLE_LABELS: Record<string, string> = {
  planner: "Planner",
  profiler: "Profiler",
  feature: "Feature",
  modeling: "Modeling",
  redteam: "Red team",
  compliance: "Compliance",
  curator: "Curator",
  ask: "Ask",
  orchestrator: "Orchestrator",
  system: "System",
};

/** "redteam" -> "Red team" */
export const roleLabel = (role: string) => ROLE_LABELS[role] ?? titleCase(role);

const KIND_LABELS: Record<string, string> = {
  redteam: "Red-team review",
  compliance: "Compliance review",
  features: "Feature research",
  modeling: "Modeling report",
  profile: "Data profile",
};

/** Report kind as a reader would name it: "redteam" -> "Red-team review". */
export const kindLabel = (kind: string) => KIND_LABELS[kind] ?? titleCase(kind);

const REASON_LABELS: Record<string, string> = {
  monitoring_alert: "Monitoring alert",
  definition_change: "Definition change",
  manual: "Started by a person",
  queued: "Queued request",
  maturation: "Newly matured loans",
};

/** Why a cycle was requested or started. Free-text reasons (demo runs) are shown as written. */
export const reasonLabel = (reason: string | null | undefined) => {
  if (!reason) return "—";
  return REASON_LABELS[reason] ?? reason;
};

const CYCLE_STATUS: Record<string, { label: string; tone: Tone }> = {
  running: { label: "Running", tone: "warn" },
  completed: { label: "Completed", tone: "good" },
  stopped_by_user: { label: "Stopped by a person", tone: "warn" },
  stopped_budget: { label: "Stopped at a budget cap", tone: "warn" },
  failed: { label: "Failed", tone: "crit" },
  failed_agent_api: { label: "Failed: agent API error", tone: "crit" },
  abandoned: { label: "Abandoned: no heartbeat", tone: "crit" },
};

export const cycleStatus = (status: string): { label: string; tone: Tone } =>
  CYCLE_STATUS[status] ?? { label: titleCase(status), tone: "neutral" };

/** Verdict from an agent review (pass, concern, fail, block) as a pill; the agent's opinion, not a measurement. */
export function VerdictPill({ verdict }: { verdict: string | null | undefined }) {
  if (!verdict) return <span className="faint">no verdict</span>;
  return <Pill tone={reviewTone(verdict)}>{verdict}</Pill>;
}

// ------------------------------------------------------------------------------------------------------ time
/** "22:41:07" in UTC (a trace reads in clock time; the full date and time is in the tooltip). */
export function fmtClock(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString("en-US", { hourCycle: "h23", timeZone: "UTC" });
}

/** Re-renders its component every `intervalMs` so relative times ("4 min ago") keep moving between polls. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

/** A relative time that keeps counting ("12 s ago" becomes "13 s ago"). */
export function LiveAgo({ iso }: { iso: string | null | undefined }) {
  const now = useNow(1000);
  return <span title={fmtDateTime(iso)}>{fmtAgo(iso, now)}</span>;
}

// -------------------------------------------------------------------------------------------------- definitions
function refFromVersion(d: DefinitionVersion): DefinitionRef {
  const f = d.fields as Record<string, unknown>;
  const dpd = Number(f.delinquency_threshold_dpd);
  const months = Number(f.observation_window_months);
  const timing: DefinitionRef["timing"] = f.delinquency_timing === "end_of_window" ? "end_of_window" : "ever";
  const known = Number.isFinite(dpd) && Number.isFinite(months);
  return {
    version: d.version,
    short: d.short,
    name: d.name,
    summary: known ? `${dpd} DPD ${timing === "ever" ? "ever" : "at end of window"} / ${months} months` : d.name,
    dpd: known ? dpd : 0,
    timing,
    window_months: known ? months : 0,
  };
}

/** Looks up a definition (12-hex version or its short form) so badges can say "60 DPD ever / 12 months". */
export function useDefinitionRefs() {
  const defs = useDefinitions();
  const status = useStatus();
  const active = status.data?.active_definition ?? null;
  return useMemo(() => {
    const list = (defs.data ?? []).map(refFromVersion);
    const find = (v: string | null | undefined): DefinitionRef | null => {
      if (!v) return null;
      if (active && active.version.startsWith(v)) return active;
      return list.find((r) => r.version.startsWith(v)) ?? null;
    };
    return { find, active, all: list };
  }, [defs.data, active]);
}

/** Definition badge with its plain-language label when the definition is known. */
export function DefBadge({ version }: { version: string | null | undefined }) {
  const { find } = useDefinitionRefs();
  if (!version) return <span className="badge">none</span>;
  return <DefinitionBadge def={find(version)} version={version} />;
}

/** Compact definition badge for dense tables: short hash and days past due; the full summary is in the tooltip. */
export function DefChip({ version }: { version: string | null | undefined }) {
  const { find } = useDefinitionRefs();
  if (!version) return <span className="muted">—</span>;
  const d = find(version);
  return (
    <Link className="badge" to={links.definition(version)} title={`Definition of default${d ? `: ${d.summary}` : ""}`}>
      <span className="mono">{shortVersion(version)}</span>
      {d && <span>{d.dpd} DPD</span>}
    </Link>
  );
}

/** A registered model key such as "pd_candidates/11" as the shared model badge. */
export function ModelKeyBadge({ modelKey }: { modelKey: string }) {
  const i = modelKey.lastIndexOf("/");
  if (i < 0) return <span className="badge">{modelKey}</span>;
  const ref: ModelRef = { key: modelKey, name: modelKey.slice(0, i), version: modelKey.slice(i + 1), label: `v${modelKey.slice(i + 1)}`, kind: "unknown", definition_version: null };
  return <ModelBadge model={ref} />;
}

// ------------------------------------------------------------------------------------------------------- text
const REF_RE = /\b(ev-[0-9a-f]{8,12}|cy-[0-9a-z]+(?:-[0-9a-z]+)*|L-[0-9a-f]{6})\b/g;

const refLink = (id: string) =>
  id.startsWith("ev-") ? links.evaluation(id) : id.startsWith("L-") ? `/agents/lessons?def=all&q=${encodeURIComponent(id)}` : links.cycle(id);

/** Plain text in which evaluation ids (ev-…), cycle ids (cy-…) and lesson ids (L-…) become links to where they come from. */
export function LinkedText({ text }: { text: string }) {
  const parts = text.split(REF_RE);
  return (
    <>
      {parts.map((p, i) =>
        i % 2 === 1 ? (
          <Link key={i} className="mono nowrap" to={refLink(p)}>
            {p}
          </Link>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}

// ---------------------------------------------------------------------------------------------------- filters
/** Reads and writes a set of query-string filters without touching other parameters. Empty means "not set". */
export function useUrlFilters<K extends string>(keys: readonly K[]) {
  const [params, setParams] = useSearchParams();
  const values = Object.fromEntries(keys.map((k) => [k, params.get(k) ?? ""])) as Record<K, string>;
  const set = (key: K, value: string) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value) next.set(key, value);
        else next.delete(key);
        return next;
      },
      { replace: true },
    );
  const clear = () =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        keys.forEach((k) => next.delete(k));
        return next;
      },
      { replace: true },
    );
  return { values, set, clear, active: keys.some((k) => params.get(k)) };
}

export interface FilterOption {
  value: string;
  label: string;
}

export function FilterSelect({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: FilterOption[] }) {
  return (
    <label className="field" style={{ minWidth: 150, maxWidth: "100%", gridTemplateColumns: "minmax(0, 1fr)" }}>
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)} style={{ maxWidth: "100%", minWidth: 0 }}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

/** A row of toggle buttons that act as a single-choice filter. */
export function ChipFilter({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: { value: string; label: ReactNode; count?: number }[] }) {
  return (
    <div className="stack" style={{ gap: 4 }} role="group" aria-label={label}>
      <span className="small muted">{label}</span>
      <div className="row" style={{ gap: 6 }}>
        {options.map((o) => (
          <button key={o.value} type="button" className={`btn small ${value === o.value ? "primary" : ""}`} aria-pressed={value === o.value} onClick={() => onChange(o.value)}>
            {o.label}
            {o.count !== undefined && <span className="num"> {o.count}</span>}
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * Search box whose text lives in the query string. The input keeps its own state so typing never lags behind the
 * router, and it only follows the URL when the URL changed for another reason (back button, cleared filters).
 */
export function UrlSearch({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  const [text, setText] = useState(value);
  const pushed = useRef(value);
  useEffect(() => {
    if (value !== pushed.current) {
      pushed.current = value;
      setText(value);
    }
  }, [value]);
  useEffect(() => {
    if (text === pushed.current) return;
    const id = setTimeout(() => {
      pushed.current = text;
      onChange(text);
    }, 250);
    return () => clearTimeout(id);
    // onChange is recreated on every render; the typed text is the only trigger
  }, [text]);
  return (
    <label className="field" style={{ minWidth: 200, maxWidth: "100%", flex: "1 1 200px", gridTemplateColumns: "minmax(0, 1fr)" }}>
      {label}
      <input type="search" value={text} placeholder={placeholder} onChange={(e) => setText(e.target.value)} />
    </label>
  );
}
