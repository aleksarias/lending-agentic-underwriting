/** Status and definition filters for the registry; their state lives in the URL (the page passes `onChange`). */
import type { ModelStatus } from "../../api/types";
import { shortVersion } from "../../lib/format";
import { plural } from "./shared";
import "./models.css";

export function RegistryFilters(props: {
  total: number;
  shown: number;
  statusCounts: (readonly [ModelStatus, number])[];
  statusFilter: string;
  defFilter: string;
  definitions: { version: string; summary: string; active: boolean }[];
  onChange: (key: string, value: string) => void;
  onClear: () => void;
}) {
  const filtered = !!props.statusFilter || !!props.defFilter;
  return (
    <div className="models-toolbar" role="group" aria-label="Filter the registry">
      <label className="field">
        Status
        <select value={props.statusFilter} onChange={(e) => props.onChange("status", e.target.value)}>
          <option value="">All statuses ({props.total})</option>
          {props.statusCounts.map(([s, n]) => (
            <option key={s} value={s}>
              {s} ({n})
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        Definition of default
        <select value={props.defFilter} onChange={(e) => props.onChange("def", e.target.value)}>
          <option value="">All definitions</option>
          {props.definitions.map((d) => (
            <option key={d.version} value={d.version.slice(0, 8)}>
              {shortVersion(d.version)} · {d.summary}
              {d.active ? " (active)" : ""}
            </option>
          ))}
        </select>
      </label>
      {filtered && (
        <button className="btn small" type="button" onClick={props.onClear}>
          Clear filters
        </button>
      )}
      <span className="small muted" aria-live="polite">
        {props.shown === props.total ? plural(props.total, "version") : `${props.shown} of ${plural(props.total, "version")} shown`}
      </span>
    </div>
  );
}
