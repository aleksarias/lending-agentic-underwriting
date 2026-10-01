/** Pure helpers for the improvement-cycle screen: labels, JSON handling, caps, and the API-error check. */
import type { CostData, SettingsData, TraceEntry } from "../../api/types";
import { titleCase } from "../../lib/format";

const AGENT_LABELS: Record<string, string> = {
  planner: "Planner",
  profiler: "Profiler",
  feature: "Feature",
  modeling: "Modeling",
  redteam: "Red team",
  compliance: "Compliance",
  curator: "Curator",
  ask: "Ask",
};
export const agentLabel = (agent: string): string => AGENT_LABELS[agent] ?? titleCase(agent);

/** The trace recorder keeps the first 4,000 characters of each input and output (src/lau/trace.py, MAX_FIELD_CHARS). */
export const RECORDER_LIMIT = 4000;
/** The API returns at most this many of the newest trace rows for one cycle. */
export const TRACE_ROW_LIMIT = 2000;

export type Parsed = { ok: true; value: unknown } | { ok: false };

/** Parse a recorded JSON string. Not JSON (or cut at the recorder's limit) gives { ok: false }. */
export function parseJson(text: string | null | undefined): Parsed {
  if (text == null || text === "") return { ok: false };
  try {
    return { ok: true, value: JSON.parse(text) };
  } catch {
    return { ok: false };
  }
}

/** The final message of an agent run, from the JSON the orchestrator records as the run's output. */
export function finalText(t: TraceEntry): string | null {
  if (t.action !== "agent_run") return null;
  const p = parseJson(t.outputs);
  if (!p.ok || !p.value || typeof p.value !== "object") return null;
  const text = (p.value as { final_text?: unknown }).final_text;
  return typeof text === "string" ? text : null;
}

export const looksLikeApiError = (text: string | null): boolean => !!text && /^\s*API Error\b/i.test(text);

/** Cut at a word boundary so the text never ends mid-word. */
function shorten(text: string, max: number): string {
  if (text.length <= max) return text;
  const cut = text.slice(0, max);
  const space = cut.lastIndexOf(" ");
  return `${(space > max / 2 ? cut.slice(0, space) : cut).trim()}…`;
}

export interface ApiErrorRuns {
  /** agent runs in the trace */
  runs: number;
  /** runs whose final message is an API error message */
  failed: number;
  /** roles of the failed runs */
  roles: Set<string>;
  /** the first error message, shortened */
  sample: string | null;
}

/** Agent runs that the orchestrator recorded as successful but whose final message is an API error. */
export function apiErrorRuns(trace: TraceEntry[]): ApiErrorRuns {
  const out: ApiErrorRuns = { runs: 0, failed: 0, roles: new Set(), sample: null };
  for (const t of trace) {
    if (t.action !== "agent_run") continue;
    out.runs += 1;
    const text = finalText(t);
    if (looksLikeApiError(text)) {
      out.failed += 1;
      out.roles.add(t.agent);
      if (out.sample === null) out.sample = shorten(text!.trim(), 200);
    }
  }
  return out;
}

export interface Caps {
  usd: number | null;
  experiments: number | null;
  /** "report": written into the cycle report when the cycle ended; "config": today's budget configuration */
  source: "report" | "config" | null;
}

/**
 * The caps this cycle ran under. The cycle report states them as they were when the cycle ended, which is what a
 * reviewer needs; today's configuration is the fallback for a cycle that has no report.
 */
export function cycleCaps(reportMarkdown: string | null, cost: CostData | undefined, settings: SettingsData | undefined): Caps {
  const m = reportMarkdown?.match(/Anthropic spend: \$[\d.,]+ \(cap \$([\d.,]+)\); experiments: [^\s(]+ \(cap (\d+)\)/);
  if (m) return { usd: Number(m[1].replace(/,/g, "")), experiments: Number(m[2]), source: "report" };
  const usd = cost?.cycle_caps?.anthropic_usd;
  const cycle = settings?.budgets?.cycle;
  const experiments = cycle && typeof cycle === "object" ? (cycle as Record<string, unknown>).max_experiments : undefined;
  const hasUsd = typeof usd === "number";
  const hasExp = typeof experiments === "number";
  return { usd: hasUsd ? usd : null, experiments: hasExp ? experiments : null, source: hasUsd || hasExp ? "config" : null };
}

/** A list of strings from a plan field that should be a list but may arrive as a single string. */
export function asStrings(v: unknown): string[] {
  if (Array.isArray(v)) return v.map((x) => (typeof x === "string" ? x : JSON.stringify(x)));
  return typeof v === "string" && v.trim() ? [v] : [];
}

/** "17:38:15" from an ISO timestamp, in UTC. */
export function clockTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toISOString().slice(11, 19);
}
