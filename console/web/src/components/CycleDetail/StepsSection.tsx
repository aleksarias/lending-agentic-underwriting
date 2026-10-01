/** One row per agent run in the cycle (role, outcome, turns, tool calls, cost, duration) and the cost of each step. */
import type { CycleDetail as CycleDetailData } from "../../api/types";
import { fmtNum, fmtSeconds, fmtUsd, titleCase } from "../../lib/format";
import { BarSeriesChart } from "../charts";
import { Card, DataTable, EmptyState, Pill, type Column } from "../ui";
import { agentLabel } from "./cycle";

type Step = CycleDetailData["steps"][number];
interface Row extends Step {
  n: number;
  /** x-axis label, made unique when a role ran more than once */
  label: string;
}

export function StepsSection({ steps, apiErrorRoles }: { steps: Step[]; apiErrorRoles: ReadonlySet<string> }) {
  if (steps.length === 0) {
    return (
      <EmptyState title="No agent runs were recorded">
        Each agent (planner, profiler, feature, modeling, red team, compliance, curator) records a run with its turns, tool calls and cost when it finishes.
      </EmptyState>
    );
  }
  const seen = new Map<string, number>();
  const rows: Row[] = steps.map((s, n) => {
    const k = (seen.get(s.role) ?? 0) + 1;
    seen.set(s.role, k);
    return { ...s, n, label: k === 1 ? agentLabel(s.role) : `${agentLabel(s.role)} ${k}` };
  });
  const total = {
    turns: steps.reduce((a, s) => a + s.turns, 0),
    calls: steps.reduce((a, s) => a + s.tool_calls, 0),
    usd: steps.reduce((a, s) => a + s.cost_usd, 0),
    seconds: steps.reduce((a, s) => a + s.duration_s, 0),
  };
  const columns: Column<Row>[] = [
    { key: "step", header: "Step", render: (r) => <strong>{r.label}</strong> },
    {
      key: "outcome",
      header: "Outcome",
      render: (r) => (
        <span className="row" style={{ gap: 6 }}>
          <Pill tone={r.subtype === "success" ? "good" : "warn"}>{titleCase(r.subtype)}</Pill>
          {apiErrorRoles.has(r.role) && <Pill tone="warn">API error</Pill>}
        </span>
      ),
    },
    { key: "turns", header: "Turns", align: "right", render: (r) => fmtNum(r.turns) },
    { key: "calls", header: "Tool calls", align: "right", render: (r) => fmtNum(r.tool_calls) },
    { key: "cost", header: "Cost", align: "right", render: (r) => fmtUsd(r.cost_usd, 3) },
    { key: "duration", header: "Duration", align: "right", render: (r) => fmtSeconds(r.duration_s) },
  ];
  const hasCost = total.usd > 0;
  const table = (
    <div className="stack">
      <Card flush kind="measured">
        <DataTable rows={rows} columns={columns} rowKey={(r) => `${r.n}-${r.role}`} />
      </Card>
      <div className="xs muted">
        Total: {fmtNum(steps.length)} step{steps.length === 1 ? "" : "s"}, {fmtNum(total.turns)} turns, {fmtNum(total.calls)} tool calls, {fmtUsd(total.usd, 3)}, {fmtSeconds(total.seconds)}.
        Duration counts from the end of the previous step, so it includes the tool calls made before the run ended.
        {apiErrorRoles.size > 0 && " API error: the run's final message is an API error message, although the orchestrator recorded the run as successful."}
      </div>
    </div>
  );
  if (!hasCost) {
    return (
      <div className="stack">
        {table}
        <div className="small muted">No agent cost was recorded for this cycle, so there is no cost chart.</div>
      </div>
    );
  }
  return (
    <div className="grid split">
      {table}
      <Card kind="measured" title="Cost per step" className="cycle-detail-chart">
        <BarSeriesChart
          title="Agent cost per step, in US dollars"
          data={rows.map((r) => ({ step: r.label, cost: r.cost_usd }))}
          xKey="step"
          series={[{ key: "cost", label: "Cost (USD)", color: 0 }]}
          yFormat={(v) => fmtUsd(v, 2)}
          layout="vertical"
          height={Math.max(180, 44 * rows.length + 40)}
        />
      </Card>
    </div>
  );
}
