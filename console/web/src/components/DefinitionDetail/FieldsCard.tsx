/** Every field of a definition with its value in plain language and what it controls. */
import type { DefinitionVersion } from "../../api/types";
import { FIELD_HELP, fieldLabel, fieldValue } from "../Definitions/fields";

export function FieldsCard({ def }: { def: DefinitionVersion }) {
  const entries = Object.entries(def.fields);
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Field</th>
            <th>Value</th>
            <th>What it controls</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([key, value]) => (
            <tr key={key}>
              <td>
                {fieldLabel(key)}
                <div className="xs faint mono">{key}</div>
              </td>
              <td>
                <strong>{fieldValue(key, value)}</strong>
              </td>
              <td className="small muted">{FIELD_HELP[key] ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
