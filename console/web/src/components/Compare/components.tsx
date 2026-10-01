/** Names and value formatting for the components of a version vector (GET /changes). */
import type { ChangeSet, DefinitionVersion } from "../../api/types";
import { shortVersion } from "../../lib/format";
import { agentLabel } from "../CycleDetail/cycle";
import { definitionLabel, definitionRefOf } from "../Definitions/labels";
import { DefinitionBadge } from "../ui";

type Component = ChangeSet["components"][number];

const LABELS: Record<string, string> = {
  definition: "Definition of default",
  data: "Data version",
  serving_model: "Model making decisions",
  challenger: "Newest challenger",
  "config:thresholds": "Harness thresholds",
  "config:budgets": "Budgets",
  "config:protected_classes": "Protected classes",
  "config:models": "Agent models",
  "config:benchmarks": "Benchmark definitions",
  "config:grants": "Access grants",
  "config:code": "Code",
};

export const isConfig = (component: string): boolean => component.startsWith("config:");

export function componentLabel(component: string): string {
  if (LABELS[component]) return LABELS[component];
  if (component.startsWith("config:prompt:")) return `Agent prompt: ${agentLabel(component.slice("config:prompt:".length))}`;
  return component.replace(/^config:/, "").replace(/[_:]+/g, " ");
}

/** What to say when a component has no value at that instant. */
const NONE: Record<string, string> = {
  definition: "none active",
  data: "no data loaded",
  challenger: "none",
};

export function VectorValue({ c, side, defs }: { c: Component; side: "before" | "after"; defs: DefinitionVersion[] }) {
  const value = side === "before" ? c.before : c.after;
  if (value == null) return <span className="muted">{NONE[c.component] ?? "not recorded"}</span>;
  if (c.component === "definition") {
    const d = defs.find((x) => x.version === value);
    return <DefinitionBadge def={d ? definitionRefOf(d) : null} version={value} />;
  }
  if (c.component === "serving_model") return <span>{value === "legacy_score" ? "Legacy policy score" : value}</span>;
  if (c.component === "challenger") return <span>{value}</span>;
  if (c.component === "data") {
    return (
      <span>
        <code className="mono">{shortVersion(value)}</code>
        {side === "after" && c.detail && <div className="xs muted">{c.detail}</div>}
      </span>
    );
  }
  return (
    <code className="mono" title={value}>
      {shortVersion(value)}
    </code>
  );
}

/** One plain-language clause for a changed component: "the definition of default (90 DPD ... to 60 DPD ...)". */
export function describeChange(c: Component, defs: DefinitionVersion[]): string {
  const name = (v: string | null) => {
    if (v == null) return "none";
    if (c.component === "definition") {
      const d = defs.find((x) => x.version === v);
      return d ? definitionLabel(d) : shortVersion(v);
    }
    if (c.component === "serving_model") return v === "legacy_score" ? "the legacy score" : v;
    if (c.component === "data") return shortVersion(v);
    return v;
  };
  const label = c.component === "definition" ? "the definition of default" : c.component === "challenger" ? "the newest challenger" : c.component === "serving_model" ? "the model making decisions" : "the data version";
  return `${label} (${name(c.before)} to ${name(c.after)})`;
}
