/** For each version, the fields that differ from the version activated before it. */
import { Link } from "react-router-dom";
import type { DefinitionVersion } from "../../api/types";
import { Card, DefinitionBadge } from "../ui";
import { aroundActivation, compareHref } from "../Compare/instants";
import { FieldDiffTable } from "./FieldDiffTable";
import { definitionLabel, definitionRefOf, inActivationOrder, neighbours } from "./labels";

export function FieldChanges({ defs }: { defs: DefinitionVersion[] }) {
  const newestFirst = [...inActivationOrder(defs)].reverse();
  return (
    <div className="stack" style={{ gap: "var(--gap)" }}>
      {newestFirst.map((d) => {
        const { previous } = neighbours(defs, d.version);
        const switchRange = d.active_from && previous ? aroundActivation(d.active_from) : null;
        return (
          <Card key={d.version}>
            <div className="row between definitions-wrap" style={{ marginBottom: 8 }}>
              <span className="row" style={{ gap: 8 }}>
                <DefinitionBadge def={definitionRefOf(d)} />
                <span className="small muted">{previous ? `compared with ${definitionLabel(previous)} (${previous.short})` : "the first recorded definition"}</span>
              </span>
              {switchRange && (
                <Link className="small" to={compareHref(switchRange.from, switchRange.to)}>
                  Everything that changed at the switch
                </Link>
              )}
            </div>
            {!d.active_from ? (
              <div className="small muted">This version has not been activated, so there is no earlier version to compare it with.</div>
            ) : !previous ? (
              <div className="small muted">Nothing was active before this definition, so there are no changes to show.</div>
            ) : d.diff_vs_previous.length === 0 ? (
              <div className="small muted">No field differs from the previous version.</div>
            ) : (
              <FieldDiffTable diffs={d.diff_vs_previous} />
            )}
          </Card>
        );
      })}
    </div>
  );
}
