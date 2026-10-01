/** The 16 event types of the history timeline, grouped the way a reviewer asks about them. */
import type { EventType } from "../../api/types";

export interface EventGroup {
  key: string;
  label: string;
  types: { type: EventType; label: string }[];
}

export const EVENT_GROUPS: EventGroup[] = [
  {
    key: "definitions",
    label: "Definitions and data",
    types: [
      { type: "definition_activated", label: "Definition activated" },
      { type: "data_loaded", label: "Data loaded" },
    ],
  },
  {
    key: "pipeline",
    label: "Pipeline",
    types: [
      { type: "stage_built", label: "Stage built" },
      { type: "stage_failed", label: "Stage failed" },
    ],
  },
  {
    key: "cycles",
    label: "Research cycles",
    types: [
      { type: "cycle_started", label: "Cycle started" },
      { type: "cycle_finished", label: "Cycle finished" },
      { type: "report", label: "Agent report" },
    ],
  },
  {
    key: "harness",
    label: "Harness",
    types: [
      { type: "evaluation", label: "Evaluation" },
      { type: "gate", label: "Holdout gate" },
      { type: "benchmark", label: "Evidence recomputed" },
    ],
  },
  {
    key: "people",
    label: "People",
    types: [
      { type: "approval", label: "Approval" },
      { type: "promotion", label: "Promotion" },
      { type: "rollback", label: "Rollback" },
    ],
  },
  {
    key: "operations",
    label: "Operations",
    types: [
      { type: "alert", label: "Alert" },
      { type: "budget_stop", label: "Budget stop" },
    ],
  },
  {
    key: "config",
    label: "Config",
    types: [{ type: "config_changed", label: "Config change" }],
  },
];

/** Every type in a fixed order, so URLs and query keys stay stable however the chips were clicked. */
export const ALL_TYPES: EventType[] = EVENT_GROUPS.flatMap((g) => g.types.map((t) => t.type));

/** Routine bookkeeping that buries the decisions: one row per rebuilt stage and per recorded config component. */
const ROUTINE: EventType[] = ["stage_built", "config_changed"];
export const KEY_TYPES: EventType[] = ALL_TYPES.filter((t) => !ROUTINE.includes(t));

/** Shown when a filter matches nothing: what this kind of event is and how it gets onto the timeline. */
export const TYPE_HINTS: Record<EventType, string> = {
  definition_activated: "A definition of default is activated after a person approves the change (lau default-definition apply).",
  data_loaded: "A data load appears when a new data version is ingested.",
  stage_built: "A build appears each time the pipeline rebuilds a stage for a definition.",
  stage_failed: "A failed build appears when a pipeline stage stops with an error.",
  cycle_started: "A cycle starts with lau run-cycle, or when a definition change or alert queues one.",
  cycle_finished: "A cycle finishes when its agents are done, a person stops it, or a budget cap ends it.",
  report: "Agent reports appear as the agents write them during a cycle.",
  evaluation: "An evaluation appears when the harness validates a candidate model.",
  gate: "A holdout gate appears when a candidate runs the promotion gate, which reads the holdout a limited number of times.",
  approval: "An approval appears when a person approves or rejects a definition change or a promotion.",
  promotion: "A promotion appears after a person approves a candidate and it is promoted to production.",
  rollback: "A rollback appears when production returns to the previous champion.",
  alert: "An alert appears when monitoring finds drift or a breached limit.",
  budget_stop: "A budget stop appears when a spend cap ends a cycle early.",
  config_changed: "A config record appears when thresholds, budgets, prompts or code change.",
  benchmark: "An evidence run appears each time the evidence job re-scores every model (lau evidence run).",
};

export const typeLabel = (t: EventType): string => EVENT_GROUPS.flatMap((g) => g.types).find((x) => x.type === t)?.label ?? t;

/** Event types from the URL: unknown names are dropped, the rest are put in canonical order. */
export function parseTypes(raw: string | null): EventType[] {
  const wanted = new Set((raw ?? "").split(",").map((s) => s.trim()).filter(Boolean));
  return ALL_TYPES.filter((t) => wanted.has(t));
}
