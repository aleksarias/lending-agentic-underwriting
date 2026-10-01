/** The answer at the top of the Definitions screen: which definition of default is active, in plain language, and who approved it. */
import { Link } from "react-router-dom";
import type { DefinitionVersion } from "../../api/types";
import { fmtDateTime, fmtNum, fmtPct } from "../../lib/format";
import { Banner, DefinitionBadge, EmptyState, KeyValue, KindTag } from "../ui";
import { definitionRefOf } from "./labels";

export function ActiveBanner({ active, hasAny }: { active: DefinitionVersion | undefined; hasAny: boolean }) {
  if (!active) {
    return hasAny ? (
      <Banner tone="warn" title="No definition of default is active">
        Definitions are recorded, but none has been activated, so nothing can be labelled. A definition is activated after a person approves it (<code>lau default-definition apply</code>).
      </Banner>
    ) : (
      <EmptyState title="No definition of default has been recorded">
        Every label, model and metric in the console depends on a definition of default. The first one is recorded when someone runs <code>lau default-definition apply</code> on a
        definition file and approves it.
      </EmptyState>
    );
  }
  const stats = active.label_stats;
  return (
    <Banner
      tone="accent"
      title={
        <span className="row" style={{ gap: 8 }}>
          <span>Active definition of default</span>
          <DefinitionBadge def={definitionRefOf(active)} />
        </span>
      }
    >
      <div className="definitions-wrap stack" style={{ gap: 10 }}>
        <p style={{ margin: "4px 0 0", maxWidth: "90ch" }}>{active.plain_language}</p>
        <KeyValue
          items={[
            ["Activated", active.active_from ? fmtDateTime(active.active_from) : <span className="muted">not recorded</span>],
            ["Activated by", active.activated_by ?? <span className="muted">not recorded</span>],
            [
              "Approval",
              active.approval_id ? (
                <span className="row" style={{ gap: 10 }}>
                  <code className="mono">{active.approval_id}</code>
                  <Link className="small" to={`/history?types=approval&definition=${encodeURIComponent(active.version)}`}>
                    Approval events
                  </Link>
                </span>
              ) : (
                <span className="muted">no approval id recorded</span>
              ),
            ],
            [
              <span key="l">
                Labelled loans <KindTag kind="measured" />
              </span>,
              stats ? (
                <span className="num">
                  {fmtNum(stats.n_eligible)} eligible of {fmtNum(stats.n_loans)}; {fmtNum(stats.n_default)} defaults, a default rate of {fmtPct(stats.default_rate)}
                </span>
              ) : (
                <span className="muted">not computed yet</span>
              ),
            ],
          ]}
        />
        <div>
          <Link className="small" to={`/definitions/${active.version}`}>
            Every field of this definition
          </Link>
        </div>
      </div>
    </Banner>
  );
}
