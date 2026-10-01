/** Field changes between two versions of a definition: field, before, after (FieldDiff[] from the API). */
import type { FieldDiff } from "../../api/types";
import { fieldLabel, fieldValue } from "./fields";

export function FieldDiffTable({ diffs }: { diffs: FieldDiff[] }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Field</th>
            <th>Before</th>
            <th>After</th>
          </tr>
        </thead>
        <tbody>
          {diffs.map((d) => (
            <tr key={d.field}>
              <td>
                {fieldLabel(d.field)}
                <div className="xs faint mono">{d.field}</div>
              </td>
              <td>{fieldValue(d.field, d.before)}</td>
              <td>
                <strong>{fieldValue(d.field, d.after)}</strong>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
