/**
 * Improvement cycle: what one cycle of agent research planned, ran, produced and cost.
 *
 * Agent output (the plan, the reports, the red-team and compliance verdicts, the cycle report) is marked proposed; the
 * validation result, costs and tool results are recorded by the harness and orchestrator and are marked measured.
 * A cycle can be recorded as completed even though its agents never ran (every call failed on an API error): the page
 * says so rather than repeating the status.
 */
import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { useCost, useCycle, useDefinitions, useModels, useSettings } from "../api/hooks";
import type { CycleDetail as CycleDetailData } from "../api/types";
import { Markdown } from "../components/Markdown";
import { CycleSummary } from "../components/CycleDetail/CycleSummary";
import { PlanCard } from "../components/CycleDetail/PlanCard";
import { ReportsCard } from "../components/CycleDetail/ReportsCard";
import { StepsSection } from "../components/CycleDetail/StepsSection";
import { TraceSection } from "../components/CycleDetail/TraceSection";
import { apiErrorRuns, cycleCaps, type ApiErrorRuns, type Caps } from "../components/CycleDetail/cycle";
import "../components/CycleDetail/CycleDetail.css";
import { definitionRefOf } from "../components/Definitions/labels";
import { cycleStatus } from "../components/History/CyclesTable";
import { isMissing } from "../components/History/notFound";
import { Card, DefinitionBadge, EmptyState, ErrorState, KindTag, Page, PageHeader, QueryView, Section } from "../components/ui";
import { fmtDate, fmtDateTime, fmtUsd } from "../lib/format";

export default function CycleDetail() {
  const { cycleId } = useParams();
  const query = useCycle(cycleId);
  return (
    <Page>
      {query.error ? (
        <Unavailable id={cycleId} error={query.error} retry={() => void query.refetch()} />
      ) : (
        <QueryView query={query} loadingHeight={360}>
          {(cycle) => <CycleBody cycle={cycle} />}
        </QueryView>
      )}
    </Page>
  );
}

/** The cycle cannot be shown: the id is unknown (say so, and point back to History) or the API failed (say so, offer a retry). */
function Unavailable({ id, error, retry }: { id: string | undefined; error: unknown; retry: () => void }) {
  const back = (
    <Link className="btn" to="/history">
      Back to History
    </Link>
  );
  if (isMissing(error)) {
    return (
      <>
        <PageHeader eyebrow="Over time" title="Improvement cycle" summary="No improvement cycle with this id is recorded." />
        <EmptyState title="Cycle not found" action={back}>
          There is no cycle <code>{id}</code>. Cycles are listed on the History screen, newest first.
        </EmptyState>
      </>
    );
  }
  return (
    <>
      <PageHeader eyebrow="Over time" title="Improvement cycle" summary="This cycle could not be loaded." />
      <ErrorState error={error} />
      <div className="row">
        {back}
        <button type="button" className="btn" onClick={retry}>
          Try again
        </button>
      </div>
    </>
  );
}

function CycleBody({ cycle }: { cycle: CycleDetailData }) {
  const cost = useCost();
  const settings = useSettings();
  const models = useModels();
  const definitions = useDefinitions();
  const errors = useMemo(() => apiErrorRuns(cycle.trace), [cycle.trace]);
  const caps = cycleCaps(cycle.report_markdown, cost.data, settings.data);
  const definition = definitions.data?.find((d) => d.version === cycle.definition_version);
  const model = cycle.challenger ? (models.data?.find((m) => m.model.version === cycle.challenger)?.model ?? null) : null;

  return (
    <>
      <PageHeader
        eyebrow="Over time"
        title={`Cycle ${cycle.cycle_id}`}
        summary={summarise(cycle, caps, errors)}
        meta={
          <>
            <span>Definition of default</span>
            <DefinitionBadge def={definition ? definitionRefOf(definition) : null} version={cycle.definition_version} />
            <span>· started {fmtDateTime(cycle.started_at)}</span>
          </>
        }
        actions={
          <Link className="btn" to="/history">
            All history
          </Link>
        }
      />

      <CycleSummary cycle={cycle} definition={definition} model={model} caps={caps} errors={errors} />

      <Section title="Plan" note="What the planner agent said this cycle would try. The steps below show what actually ran.">
        <PlanCard plan={cycle.plan} experimentsCap={caps.experiments} />
      </Section>

      <Section title="Steps and cost" note="Each agent run, in the order it finished. Turns, tool calls and cost are recorded by the orchestrator.">
        <StepsSection steps={cycle.steps} apiErrorRoles={errors.roles} />
      </Section>

      <Section title="Reports written in this cycle">
        <ReportsCard reports={cycle.reports} />
      </Section>

      <Section title="Full trace" right={<span className="small muted">{cycle.trace.length} rows</span>}>
        <TraceSection trace={cycle.trace} />
      </Section>

      <Section title="Cycle report">
        {cycle.report_markdown ? (
          <Card kind="proposed">
            <div className="small muted" style={{ marginBottom: 8 }}>
              <KindTag kind="proposed" /> Assembled by the orchestrator when the cycle ended. The plan and verdicts in it are agent claims; the validation metrics come from the harness.
            </div>
            <Markdown source={cycle.report_markdown} />
          </Card>
        ) : (
          <EmptyState title="No cycle report is available">The orchestrator writes a markdown report when a cycle ends. This cycle has none, so it may have been interrupted.</EmptyState>
        )}
      </Section>
    </>
  );
}

/** One plain-language sentence: how the cycle ended, what it proposed, what the agents said, and what it cost. */
function summarise(c: CycleDetailData, caps: Caps, errors: ApiErrorRuns): string {
  const status = cycleStatus(c.status).label;
  const when = fmtDate(c.started_at);
  const cap = caps.usd != null ? ` of the ${fmtUsd(caps.usd, 0)} cap` : "";
  if (c.status === "running") {
    const tests = `${c.experiments_used ?? 0} test${c.experiments_used === 1 ? "" : "s"} used so far`;
    const spent = c.anthropic_usd == null ? "no agent spend recorded yet" : `agent spend so far is ${fmtUsd(c.anthropic_usd)}${cap}`;
    return `Running since ${when}: ${tests}; ${spent}.`;
  }
  const challenger = c.challenger
    ? `proposed challenger v${c.challenger}${c.challenger_passed_validation === true ? ", which passed validation" : c.challenger_passed_validation === false ? ", which did not pass validation" : ""}`
    : "proposed no challenger";
  const r = c.redteam_verdict;
  const k = c.compliance_verdict;
  const verdicts = !r && !k ? "" : r === k ? `, and the red-team and compliance agents both said "${r}"` : `, and the red-team agent said "${r ?? "nothing"}" while the compliance agent said "${k ?? "nothing"}"`;
  const spend = c.anthropic_usd == null ? "no agent spend was recorded" : `agent spend was ${fmtUsd(c.anthropic_usd)}${cap}`;
  if (errors.failed > 0) {
    const all = errors.failed === errors.runs ? `all ${errors.runs}` : `${errors.failed} of ${errors.runs}`;
    return `Recorded as ${status.toLowerCase()} on ${when}, but ${all} agent runs ended with an API error message, so the cycle ${challenger}; ${spend}.`;
  }
  return `${status} on ${when}: the cycle ${challenger}${verdicts}; ${spend}.`;
}
