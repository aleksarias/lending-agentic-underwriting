/**
 * Screen 14 — Agents. Answers: who are the agents, what may each one do and what has it cost, and what have they
 * written? Agent output here is proposed: nothing on this page is a measurement.
 */
import { Link } from "react-router-dom";
import { useAgents, useLessons, useReports } from "../api/hooks";
import type { AgentInfo, ReportMeta } from "../api/types";
import { PermissionMatrix, Roster } from "../components/Agents/Roster";
import { ReportsLibrary } from "../components/Agents/ReportsLibrary";
import { roleLabel } from "../components/Agents/shared";
import { Card, ErrorState, Loading, Page, PageHeader, QueryView, Section } from "../components/ui";
import { fmtNum, fmtPct, fmtUsd } from "../lib/format";

function summary(agents: AgentInfo[], reports: ReportMeta[] | undefined): string {
  if (agents.length === 0) return "No agent roles are configured, so no agent can run.";
  const runs = agents.reduce((s, a) => s + a.runs, 0);
  const spend = agents.reduce((s, a) => s + a.total_cost_usd, 0);
  const worst = agents.filter((a) => a.tool_error_rate != null).sort((a, b) => (b.tool_error_rate ?? 0) - (a.tool_error_rate ?? 0))[0];
  const parts = [`${agents.length} agents have made ${fmtNum(runs)} runs at a total cost of ${fmtUsd(spend)}${reports ? ` and written ${fmtNum(reports.length)} reports` : ""}.`];
  if (worst && (worst.tool_error_rate ?? 0) > 0) parts.push(`Tool errors are most frequent for the ${roleLabel(worst.role).toLowerCase()} agent (${fmtPct(worst.tool_error_rate, 1)} of its tool calls).`);
  else if (worst) parts.push("No tool errors have been recorded.");
  return parts.join(" ");
}

function LessonsLink() {
  const q = useLessons();
  const lessons = q.data?.lessons ?? [];
  const active = q.data?.active_definition ?? null;
  const applicable = lessons.filter((l) => l.definition_version === active || l.scope === "definition-independent").length;
  return (
    <Card kind="proposed">
      <div className="row between">
        <div>
          <strong>Lessons</strong>
          <div className="small muted">
            {q.data
              ? `The curator agent has written ${lessons.length} lessons; ${applicable} apply to the active definition. Lessons learned under another definition are flagged unverified.`
              : "Lessons the curator agent distils after each cycle."}
          </div>
        </div>
        <Link to="/agents/lessons">Open lessons</Link>
      </div>
    </Card>
  );
}

export default function Agents() {
  const agents = useAgents();
  const reports = useReports();
  return (
    <Page>
      {agents.isError ? (
        <ErrorState error={agents.error} />
      ) : !agents.data ? (
        <Loading height={320} />
      ) : (
        <>
          <PageHeader eyebrow="Agents" title="Agents" summary={summary(agents.data, reports.data)} />

          <Section
            title="Roster"
            note="Agents run in this order inside a cycle. Caps are enforced by the orchestrator. Tool error rate is the share of an agent's tool calls that returned an error, over every cycle."
          >
            <Roster agents={agents.data} />
          </Section>

          <Section title="What each agent may call" note="Tools are the only way an agent touches data or writes anything.">
            <PermissionMatrix agents={agents.data} />
          </Section>

          <Section
            title="Reports library"
            note="Written by agents. What a report says is proposed: check it against the measured evidence linked from the report before relying on it."
            right={<Link className="small" to="/agents/lessons">Lessons</Link>}
          >
            <QueryView query={reports} loadingHeight={200}>
              {(list) => <ReportsLibrary reports={list} />}
            </QueryView>
          </Section>

          <LessonsLink />
        </>
      )}
    </Page>
  );
}
