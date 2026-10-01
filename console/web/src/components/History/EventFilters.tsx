/** Filters for the history timeline: event types as toggle chips (grouped), and the definition of default. */
import type { DefinitionVersion, EventType } from "../../api/types";
import { definitionLabel, inActivationOrder } from "../Definitions/labels";
import { ALL_TYPES, EVENT_GROUPS, KEY_TYPES, type EventGroup } from "./groups";

export function EventFilters(props: {
  types: EventType[];
  definition: string | null;
  defs: DefinitionVersion[];
  /** The definition in the link is not one this system has recorded. */
  staleDefinition: boolean;
  onTypes: (next: EventType[]) => void;
  onDefinition: (version: string | null) => void;
  onClear: () => void;
}) {
  const { types, definition, defs } = props;
  const selected = new Set(types);
  const filtered = types.length > 0 || definition !== null;

  const toggleType = (t: EventType) => props.onTypes(ALL_TYPES.filter((x) => (x === t ? !selected.has(t) : selected.has(x))));
  const toggleGroup = (g: EventGroup) => {
    const inGroup = new Set<EventType>(g.types.map((x) => x.type));
    const allOn = g.types.every((x) => selected.has(x.type));
    props.onTypes(ALL_TYPES.filter((x) => (inGroup.has(x) ? !allOn : selected.has(x))));
  };
  const isKeyOnly = types.length === KEY_TYPES.length && KEY_TYPES.every((t) => selected.has(t));

  return (
    <div className="history-filters">
      <div className="row between">
        <strong className="small" id="history-types-label">
          Event types
        </strong>
        <span className="row" style={{ gap: 6 }}>
          <button type="button" className="btn small" aria-pressed={types.length === 0} onClick={() => props.onTypes([])}>
            {types.length === 0 ? "✓ " : ""}All events
          </button>
          <button type="button" className="btn small" aria-pressed={isKeyOnly} onClick={() => props.onTypes(KEY_TYPES)}>
            {isKeyOnly ? "✓ " : ""}Key events only
          </button>
        </span>
      </div>
      <div className="history-groups" role="group" aria-labelledby="history-types-label">
        {EVENT_GROUPS.map((g) => (
          <div className="history-group" key={g.key} role="group" aria-label={g.label}>
            <button type="button" className="history-group-name" onClick={() => toggleGroup(g)}>
              {g.label}
            </button>
            <div className="history-chips">
              {g.types.map((t) => {
                const on = selected.has(t.type);
                return (
                  <button key={t.type} type="button" className="history-chip" aria-pressed={on} onClick={() => toggleType(t.type)}>
                    {on && <span aria-hidden>✓ </span>}
                    {t.label}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <div className="xs muted">
        None selected shows every type. Click a group name to select or clear the group. Key events only leaves out stage builds and config records.
      </div>

      <div className="row" style={{ alignItems: "flex-end", gap: 14 }}>
        <label className="field">
          Definition of default
          <select value={definition ?? ""} disabled={defs.length === 0} onChange={(e) => props.onDefinition(e.target.value || null)}>
            <option value="">All definitions</option>
            {[...inActivationOrder(defs)].reverse().map((d) => (
              <option key={d.version} value={d.version}>
                {definitionLabel(d)} ({d.short}){d.is_active ? ", active" : ""}
              </option>
            ))}
          </select>
        </label>
        {filtered && (
          <button type="button" className="btn small" onClick={props.onClear}>
            Clear filters
          </button>
        )}
      </div>
      {definition && (
        <div className="xs muted">Events that belong to no definition (configuration records and data loads) are always included, because they affect every definition.</div>
      )}
      {props.staleDefinition && (
        <div className="small" role="status">
          The definition in this link is not recorded in this system, so all definitions are shown.
        </div>
      )}
    </div>
  );
}
