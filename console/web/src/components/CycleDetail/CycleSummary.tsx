/** Top of the cycle screen: warnings first, then spend, tests and challenger as tiles, then the details. */
import { Link } from "react-router-dom";
import type { CycleDetail as CycleDetailData, DefinitionVersion, ModelRef } from "../../api/types";
import { fmtDateTime, fmtNum, fmtPct, fmtSeconds, fmtUsd } from "../../lib/format";
import { definitionRefOf } from "../Definitions/labels";
import { cycleStatus, VerdictPill } from "../History/CyclesTable";
import { Banner, Card, DefinitionBadge, KeyValue, KindTag, ModelBadge, Pill, Tiles, links } from "../ui";
import type { ApiErrorRuns, Caps } from "./cycle";

export function CycleSummary(props: {
  cycle: CycleDetailData;
  definition: DefinitionVersion | undefined;
  model: ModelRef | null;
  caps: Caps;
  errors: ApiErrorRuns;
}) {
  const { cycle: c, definition, model, caps, errors } = props;
  const status = cycleStatus(c.status);
  const usedPct = caps.usd && c.anthropic_usd != null ? ` (${fmtPct(c.anthropic_usd / caps.usd, 0)})` : "";
  const validation = c.challenger_passed_validation;
  const wallClock = c.steps.reduce((a, s) => a + s.duration_s, 0);
  const allFailed = errors.failed > 0 && errors.failed === errors.runs;

  return (
    <>
      {c.status === "running" && (
        <Banner tone="accent" title="This cycle is still running">
          This page shows what has been recorded so far and does not refresh on its own. <Link to="/activity">Live activity</Link> shows the current step and updates every few seconds.
        </Banner>
      )}
      {errors.failed > 0 && (
        <Banner tone="warn" title={allFailed ? "The agents did no work in this cycle" : "Some agent runs ended with an API error message"}>
          <p style={{ margin: "4px 0 0" }}>
            {errors.failed} of {errors.runs} agent run{errors.runs === 1 ? "" : "s"} ended with an API error message instead of work, for example: “{errors.sample}”. The orchestrator recorded{" "}
            {allFailed ? "them" : "those runs"} as successful and the cycle as {status.label.toLowerCase()}.
            {!c.plan && c.reports.length === 0 && c.challenger == null ? " No plan, agent report or challenger came out of it." : ""}
          </p>
        </Banner>
      )}

      <Tiles
        tiles={[
          { key: "status", label: "Status", value: status.label, tone: status.tone === "neutral" ? null : status.tone, sub: c.stop_reason },
          {
            key: "spend",
            label: "Agent spend",
            value: fmtUsd(c.anthropic_usd),
            sub: caps.usd != null ? `of the ${fmtUsd(caps.usd)} cycle cap${usedPct}` : "cap not available",
            href: "/cost",
          },
          {
            key: "tests",
            label: "Tests used",
            value: fmtNum(c.experiments_used),
            sub: caps.experiments != null ? `of ${fmtNum(caps.experiments)} allowed per cycle` : "cap not available",
          },
          {
            key: "challenger",
            label: "Challenger",
            value: c.challenger ? `v${c.challenger}` : "None",
            sub: c.challenger ? (validation === true ? "passed validation" : validation === false ? "did not pass validation" : "no validation result") : "no model was proposed",
            tone: validation === true ? "good" : validation === false ? "warn" : null,
            href: model && model.key !== "legacy_score" ? links.model(model.name, model.version) : null,
          },
        ]}
      />
      {caps.source && (
        <div className="xs muted">
          {caps.source === "report"
            ? "Caps are the limits this cycle ran under, as written in its cycle report."
            : "This cycle has no report, so the caps shown are today's budget configuration."}
        </div>
      )}

      <Card title="Cycle details" className="cycle-detail-details">
        <KeyValue
          items={[
            ["Reason", c.reason || <span className="muted">none recorded</span>],
            ["Definition of default", <DefinitionBadge def={definition ? definitionRefOf(definition) : null} version={c.definition_version} />],
            ["Started", fmtDateTime(c.started_at)],
            ["Time in agent steps", wallClock > 0 ? fmtSeconds(wallClock) : <span className="muted">none recorded</span>],
            ["Stop reason", c.stop_reason ?? <span className="muted">none: the cycle was not stopped early</span>],
            ["Challenger", model ? <ModelBadge model={model} /> : c.challenger ? `v${c.challenger}` : <span className="muted">none proposed</span>],
            [
              <span key="v">
                Validation <KindTag kind="measured" />
              </span>,
              validation == null ? <span className="muted">no validation result</span> : validation ? <Pill tone="good">passed the harness checks</Pill> : <Pill tone="warn">did not pass the harness checks</Pill>,
            ],
            [
              <span key="r">
                Red-team verdict <KindTag kind="proposed" />
              </span>,
              <VerdictPill verdict={c.redteam_verdict} />,
            ],
            [
              <span key="c">
                Compliance verdict <KindTag kind="proposed" />
              </span>,
              <VerdictPill verdict={c.compliance_verdict} />,
            ],
          ]}
        />
      </Card>
    </>
  );
}
