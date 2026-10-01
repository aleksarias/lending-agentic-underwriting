/**
 * Cost content. Agent spend comes from the Anthropic API's own per-run cost; Databricks spend is an estimate (metered
 * warehouse time priced at the configured $/DBU), because billing actuals are not readable by the console identity.
 */
import { Link } from "react-router-dom";
import type { CostData, StatusSummary, Unavailable } from "../../api/types";
import { BarSeriesChart } from "../charts";
import { fmtNum, fmtPct, fmtUsd } from "../../lib/format";
import { Card, DataTable, EmptyState, KeyValue, Meter, PageHeader, Section, UnavailableState, links } from "../ui";
import { roleLabel } from "../Agents/shared";

const cents = (v: number) => Math.round(v * 100) / 100;

/** Spend of the current UTC month split into agents and Databricks, when the daily rows add up to the month-to-date figure. */
function monthSplit(c: CostData): { agents: number; databricks: number } | null {
  const prefix = new Date().toISOString().slice(0, 7);
  const days = c.by_day.filter((d) => d.day.startsWith(prefix));
  const agents = days.reduce((s, d) => s + d.anthropic, 0);
  const databricks = days.reduce((s, d) => s + d.databricks, 0);
  return Math.abs(agents + databricks - c.month_to_date_usd) <= 0.011 ? { agents, databricks } : null;
}

export function costSentence(c: CostData): string {
  const share = c.hard_stop_usd ? c.month_to_date_usd / c.hard_stop_usd : null;
  const split = monthSplit(c);
  const parts = [
    `${fmtUsd(c.month_to_date_usd)} has been spent this month${share != null ? `, ${fmtPct(share, 1)} of the ${fmtUsd(c.hard_stop_usd, 0)} hard stop` : ""}${
      split ? `: ${fmtUsd(split.agents)} on agents and an estimated ${fmtUsd(split.databricks)} on Databricks` : ""
    }.`,
  ];
  const top = [...c.by_cycle].sort((a, b) => b.anthropic + b.databricks - (a.anthropic + a.databricks))[0];
  if (top) parts.push(`The most expensive cycle, ${top.cycle_id}, cost ${fmtUsd(top.anthropic + top.databricks)}; every cycle is capped at ${fmtUsd(c.cycle_caps.anthropic_usd)} for agents and ${fmtNum(c.cycle_caps.dbu, 1)} DBU for Databricks.`);
  return parts.join(" ");
}

const BILLING: Unavailable = {
  available: false,
  reason: "Billing actuals are not readable by the console identity, so every Databricks figure on this page is an estimate priced from metered warehouse time.",
  requires: ["SELECT on system.billing.usage for the console's read-only identity"],
};
const SERVING: Unavailable = {
  available: false,
  reason: "Serving cost per 1,000 decisions cannot be measured until the decision API takes traffic.",
  requires: ["Decision API running", "Decision log to count decisions"],
};

export function CostView({ c, status }: { c: CostData; status: StatusSummary | undefined }) {
  const hourly = c.pricing.dbu_per_hour * c.pricing.usd_per_dbu;
  const capDbxUsd = c.cycle_caps.dbu * c.pricing.usd_per_dbu;
  const split = monthSplit(c);
  const left = c.hard_stop_usd - c.month_to_date_usd;
  const running = status?.activity.state === "cycle_running";
  const maxAgents = Math.max(0, ...c.by_cycle.map((x) => x.anthropic));
  const maxDbx = Math.max(0, ...c.by_cycle.map((x) => x.databricks));
  const agentTotal = c.by_agent.reduce((s, a) => s + a.cost_usd, 0);
  const loggedAgents = c.by_cycle.reduce((s, x) => s + x.anthropic, 0);
  const gap = cents(agentTotal - loggedAgents);

  return (
    <>
      <PageHeader eyebrow="Decide and operate" title="Cost" summary={costSentence(c)} />

      <Section title="This month">
        <div className="grid split">
          <Card>
            <Meter label="Month to date against the monthly hard stop" used={c.month_to_date_usd} cap={c.hard_stop_usd} format={(v) => fmtUsd(v)} />
            <div style={{ marginTop: 12 }}>
              <KeyValue
                items={[
                  ["Agents (Anthropic, as reported per run)", split ? fmtUsd(split.agents) : "—"],
                  ["Databricks (estimated from metered warehouse time)", split ? fmtUsd(split.databricks) : "—"],
                  ["Left before the hard stop", left >= 0 ? fmtUsd(left) : `Over by ${fmtUsd(-left)}`],
                ]}
              />
            </div>
            <div className="small muted" style={{ marginTop: 10 }}>
              A new cycle is refused when this month's logged spend plus the cycle's estimated cost would pass the hard stop.
              {running && (
                <>
                  {" "}
                  A cycle is running now; its spend is logged when it finishes, so it is not in these figures yet (<Link to="/activity">Live activity</Link> shows its spend so far).
                </>
              )}
            </div>
          </Card>
          <Card title="Largest cycle so far against the per-cycle caps">
            <div className="stack" style={{ gap: 12 }}>
              <Meter label="Agents" used={maxAgents} cap={c.cycle_caps.anthropic_usd} format={(v) => fmtUsd(v)} />
              <Meter label={`Databricks, estimated (cap is ${fmtNum(c.cycle_caps.dbu, 1)} DBU)`} used={maxDbx} cap={capDbxUsd} format={(v) => fmtUsd(v)} />
            </div>
            <div className="xs muted" style={{ marginTop: 8 }}>
              The Databricks cap is set in DBU; it is shown in dollars at {fmtUsd(c.pricing.usd_per_dbu)} per DBU. Each agent run also has its own caps: see <Link to="/agents">Agents</Link>.
            </div>
          </Card>
        </div>
      </Section>

      <Section title="Spend by day" note="Agents are the Anthropic cost of each agent run. Databricks is estimated. Days are UTC.">
        {c.by_day.length === 0 ? (
          <EmptyState title="No spend has been logged yet">Each improvement cycle and pipeline run adds a row to the cost log when it finishes.</EmptyState>
        ) : (
          <div className="grid split">
            <Card>
              <BarSeriesChart
                title="Spend by day in US dollars, agents and estimated Databricks stacked"
                data={c.by_day.map((d) => ({ day: d.day, agents: d.anthropic, databricks: d.databricks }))}
                xKey="day"
                series={[
                  { key: "agents", label: "Agents (Anthropic)", color: 3 },
                  { key: "databricks", label: "Databricks (estimated)", color: 4 },
                ]}
                stacked
                yFormat={(v) => fmtUsd(v)}
                height={260}
              />
            </Card>
            <Card flush>
              <DataTable
                rows={c.by_day}
                rowKey={(d) => d.day}
                initialSort={{ key: "day", dir: "desc" }}
                columns={[
                  { key: "day", header: "Day", render: (d) => d.day, sort: (d) => d.day },
                  { key: "agents", header: "Agents", align: "right", render: (d) => fmtUsd(d.anthropic), sort: (d) => d.anthropic },
                  { key: "dbx", header: "Databricks, est.", align: "right", render: (d) => fmtUsd(d.databricks), sort: (d) => d.databricks },
                  { key: "total", header: "Total", align: "right", render: (d) => fmtUsd(d.anthropic + d.databricks), sort: (d) => d.anthropic + d.databricks },
                ]}
              />
            </Card>
          </div>
        )}
      </Section>

      <Section title="Spend by cycle" note="Logged when a cycle finishes. The share column is the cycle's agent spend against the per-cycle agent cap.">
        <Card flush>
          <DataTable
            rows={c.by_cycle}
            rowKey={(x) => x.cycle_id}
            empty={<EmptyState title="No cycle has logged spend yet">A cycle's agent spend and metered warehouse time are logged when it ends.</EmptyState>}
            columns={[
              { key: "cycle", header: "Cycle", render: (x) => <Link className="mono nowrap" to={links.cycle(x.cycle_id)}>{x.cycle_id}</Link>, sort: (x) => x.cycle_id },
              { key: "agents", header: "Agents", align: "right", render: (x) => fmtUsd(x.anthropic), sort: (x) => x.anthropic },
              { key: "dbx", header: "Databricks, est.", align: "right", render: (x) => fmtUsd(x.databricks), sort: (x) => x.databricks },
              { key: "total", header: "Total", align: "right", render: (x) => fmtUsd(x.anthropic + x.databricks), sort: (x) => x.anthropic + x.databricks },
              {
                key: "share",
                header: "Agent spend vs cap",
                align: "right",
                render: (x) => fmtPct(c.cycle_caps.anthropic_usd ? x.anthropic / c.cycle_caps.anthropic_usd : null, 1),
                sort: (x) => x.anthropic,
              },
            ]}
          />
        </Card>
      </Section>

      <Section
        title="Spend by agent"
        note={
          <>
            Counts every agent run in the trace.{" "}
            {Math.abs(gap) > 0.005 &&
              (running && gap > 0
                ? `It is ${fmtUsd(gap)} higher than the agent spend logged by day and by cycle because a cycle is still in progress and logs its cost when it ends. `
                : `It differs from the agent spend logged by day and by cycle by ${fmtUsd(Math.abs(gap))}: the trace and the cost log are written separately. `)}
            A run with no recorded cost is left out.
          </>
        }
      >
        {c.by_agent.length === 0 ? (
          <EmptyState title="No agent runs have a recorded cost">Agent runs are costed when they end.</EmptyState>
        ) : (
          <div className="grid split">
            <Card>
              <BarSeriesChart
                title="Agent spend in US dollars by agent role"
                data={c.by_agent.map((a) => ({ agent: roleLabel(a.agent), cost_usd: a.cost_usd }))}
                xKey="agent"
                series={[{ key: "cost_usd", label: "Spend", color: 3 }]}
                layout="vertical"
                yFormat={(v) => fmtUsd(v)}
                height={Math.max(200, c.by_agent.length * 36 + 50)}
              />
            </Card>
            <Card flush>
              <DataTable
                rows={c.by_agent}
                rowKey={(a) => a.agent}
                columns={[
                  { key: "agent", header: "Agent", render: (a) => roleLabel(a.agent), sort: (a) => a.agent },
                  { key: "runs", header: "Runs", align: "right", render: (a) => fmtNum(a.runs), sort: (a) => a.runs },
                  { key: "spend", header: "Spend", align: "right", render: (a) => fmtUsd(a.cost_usd), sort: (a) => a.cost_usd },
                  { key: "per", header: "Per run", align: "right", render: (a) => fmtUsd(a.runs ? a.cost_usd / a.runs : null), sort: (a) => (a.runs ? a.cost_usd / a.runs : null) },
                  { key: "share", header: "Share", align: "right", render: (a) => fmtPct(agentTotal ? a.cost_usd / agentTotal : null, 0), sort: (a) => a.cost_usd },
                ]}
                initialSort={{ key: "spend", dir: "desc" }}
              />
            </Card>
          </div>
        )}
      </Section>

      <Section title="Pricing assumptions and what is not measured">
        <div className="grid cols-2">
          <Card title="Databricks estimate">
            <KeyValue
              items={[
                ["Warehouse size", c.pricing.warehouse_size || "—"],
                ["DBU per hour", fmtNum(c.pricing.dbu_per_hour, 1)],
                ["Price per DBU", fmtUsd(c.pricing.usd_per_dbu)],
                ["Implied price per warehouse hour", fmtUsd(hourly)],
              ]}
            />
            <div className="small muted" style={{ marginTop: 10 }}>
              The pipeline meters warehouse time and prices it at these rates. Invoiced amounts can differ.
            </div>
          </Card>
          <div className="stack">
            {!c.billing_available && <UnavailableState u={BILLING} title="Billing actuals are not available" />}
            <UnavailableState u={SERVING} title="Serving cost per 1,000 decisions is not measured" />
          </div>
        </div>
      </Section>
    </>
  );
}

