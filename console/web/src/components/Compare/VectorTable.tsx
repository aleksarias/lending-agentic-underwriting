/** The version-vector diff: each tracked component as it was at the first instant and at the second. */
import { Link } from "react-router-dom";
import type { ChangeSet, DefinitionVersion } from "../../api/types";
import { Pill } from "../ui";
import { VectorValue, componentLabel, isConfig } from "./components";

type Component = ChangeSet["components"][number];

/**
 * Text and tone for the changed pill. Colour is never the only signal: the pill always says what happened.
 * "First recorded" is only for configuration components, where an empty "before" means nothing had been recorded yet
 * (the component existed); for the others an empty side is a real state, such as no challenger.
 */
function status(c: Component): { text: string; tone: "accent" | "neutral" | "info" | "warn" } {
  if (!c.changed) return { text: "unchanged", tone: "neutral" };
  if (isConfig(c.component) && c.before == null) return { text: "first recorded", tone: "info" };
  if (c.after == null) return { text: "removed", tone: "warn" };
  return { text: "changed", tone: "accent" };
}

export function VectorTable({ components, defs, label }: { components: Component[]; defs: DefinitionVersion[]; label: string }) {
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label="Table (scrolls sideways when narrow)">
      <table className="data compare-vector">
        <caption className="sr-only">{label}</caption>
        <thead>
          <tr>
            <th>Component</th>
            <th>Before</th>
            <th>After</th>
            <th>Changed</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {components.map((c) => {
            const s = status(c);
            return (
              <tr key={c.component}>
                <td>
                  <strong>{componentLabel(c.component)}</strong>
                  <div className="xs faint mono">{c.component}</div>
                </td>
                <td>
                  <VectorValue c={c} side="before" defs={defs} />
                </td>
                <td>
                  <VectorValue c={c} side="after" defs={defs} />
                </td>
                <td>
                  <Pill tone={s.tone}>{s.text}</Pill>
                </td>
                <td>{c.href ? <Link to={c.href}>Open</Link> : <span className="faint">none</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
