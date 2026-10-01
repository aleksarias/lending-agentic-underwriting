/** Header of a definition-era band on the history timeline: which definition, and when it was active. */
import type { DefinitionVersion, EventItem } from "../../api/types";
import { fmtDateTime } from "../../lib/format";
import { definitionRefOf } from "../Definitions/labels";
import { DefinitionBadge, Pill } from "../ui";
import { NO_ERA } from "./eras";

export function EraHeader({ era, defs, events }: { era: string; defs: DefinitionVersion[]; events: EventItem[] }) {
  if (era === NO_ERA) {
    // Without the definition list (it failed to load) there are no activation dates to say "before the first one".
    const known = defs.length > 0;
    return (
      <div className="history-era-head">
        <h3 className="history-era-title">{known ? "No definition of default yet" : "Events without a definition"}</h3>
        <span className="small muted">{known ? "These events are dated before the first definition was activated." : "These events belong to no definition of default."}</span>
      </div>
    );
  }
  const def = defs.find((d) => d.version === era);
  if (!def) {
    return (
      <div className="history-era-head">
        <h3 className="history-era-title">
          <DefinitionBadge version={era} />
        </h3>
        {/* With no definitions loaded at all (the list failed), "not in the registry" would be a false statement. */}
        {defs.length > 0 && <span className="small muted">This definition is not in the definition registry.</span>}
      </div>
    );
  }
  // Work done for a definition after another one replaced it (for example a stage rebuilt under the earlier definition).
  const replacedAt = def.active_to ? Date.parse(def.active_to) : null;
  const late = replacedAt == null ? 0 : events.filter((e) => e.definition_version === def.version && Date.parse(e.ts) > replacedAt).length;
  return (
    <div className="history-era-head">
      <h3 className="history-era-title">
        <DefinitionBadge def={definitionRefOf(def)} />
      </h3>
      {def.is_active && (
        <Pill tone="accent" dot>
          Active now
        </Pill>
      )}
      <span className="small muted">
        {def.active_from ? `Active from ${fmtDateTime(def.active_from)} to ${def.active_to ? fmtDateTime(def.active_to) : "now"}` : "Never activated"}
      </span>
      {late > 0 && (
        <span className="xs muted">
          {late} event{late === 1 ? "" : "s"} below {late === 1 ? "is" : "are"} dated after this definition was replaced.
        </span>
      )}
    </div>
  );
}
