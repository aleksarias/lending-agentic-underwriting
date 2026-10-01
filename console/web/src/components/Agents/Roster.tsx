/** Agent roster (model, caps, prompt version, tools, usage) and the role-by-tool permission matrix. */
import { useMemo } from "react";
import { Link } from "react-router-dom";
import type { AgentInfo } from "../../api/types";
import { fmtNum, fmtPct, fmtUsd } from "../../lib/format";
import { Card, DataTable, EmptyState } from "../ui";
import { roleLabel } from "./shared";

export function Roster({ agents }: { agents: AgentInfo[] }) {
  return (
    <Card flush>
      <DataTable
        rows={agents}
        rowKey={(a) => a.role}
        empty={<EmptyState title="No agent roles are configured">Roles come from the model and budget configuration.</EmptyState>}
        columns={[
          {
            key: "role",
            header: "Agent and Claude model",
            render: (a) => (
              <div>
                <strong>{roleLabel(a.role)}</strong>
                <div className="xs muted mono nowrap">{a.model || "no model set"}</div>
              </div>
            ),
            sort: (a) => a.role,
          },
          {
            key: "caps",
            header: "Caps for one run",
            render: (a) => (
              <div className="num small">
                <div className="nowrap">{a.caps.max_turns} turns · {a.caps.timeout_min} min</div>
                <div className="nowrap muted">{fmtUsd(a.caps.max_budget_usd)} budget</div>
              </div>
            ),
            sort: (a) => a.caps.max_budget_usd,
          },
          {
            key: "prompt",
            header: "Prompt version",
            render: (a) =>
              a.prompt_hash ? (
                <Link className="mono" to="/settings#settings-versions" title="Content hash of the prompt (first 12 characters of its SHA-256). It changes whenever the prompt text changes. The version ledger is in Settings.">
                  {a.prompt_hash}
                </Link>
              ) : (
                "—"
              ),
          },
          {
            key: "tools",
            header: "Tools",
            render: (a) => (
              <details>
                <summary className="nowrap" style={{ cursor: "pointer" }}>
                  {a.tools.length} tool{a.tools.length === 1 ? "" : "s"}
                </summary>
                <ul className="plain" style={{ marginTop: 6 }}>
                  {a.tools.map((t) => (
                    <li key={t} className="mono xs">
                      {t}
                    </li>
                  ))}
                </ul>
              </details>
            ),
            sort: (a) => a.tools.length,
          },
          { key: "runs", header: "Runs", align: "right", render: (a) => fmtNum(a.runs), sort: (a) => a.runs },
          {
            key: "spend",
            header: "Spend",
            align: "right",
            render: (a) => (
              <Link to="/cost" title="Spend by agent on the Cost screen">
                {fmtUsd(a.total_cost_usd)}
              </Link>
            ),
            sort: (a) => a.total_cost_usd,
          },
          { key: "turns", header: "Avg turns", align: "right", render: (a) => fmtNum(a.avg_turns, 1), sort: (a) => a.avg_turns },
          {
            key: "errors",
            header: "Tool errors",
            align: "right",
            render: (a) => (a.tool_error_rate == null ? <span title="No tool calls recorded">—</span> : fmtPct(a.tool_error_rate, 1)),
            sort: (a) => a.tool_error_rate,
          },
        ]}
      />
    </Card>
  );
}

export function PermissionMatrix({ agents }: { agents: AgentInfo[] }) {
  // tools in the order they first appear when roles are read in run order, so each role's own tools sit together
  const tools = useMemo(() => {
    const seen: string[] = [];
    for (const a of agents) for (const t of a.tools) if (!seen.includes(t)) seen.push(t);
    return seen;
  }, [agents]);
  if (!tools.length) return <EmptyState title="No tool lists available">The tool lists come from the agent definitions in the code.</EmptyState>;
  return (
    <Card flush>
      <div className="table-wrap" tabIndex={0} role="region" aria-label="Table (scrolls sideways when narrow)" style={{ border: 0, borderRadius: 0 }}>
        {/* position: relative makes the table the containing block of the absolutely positioned sr-only text, so the scroll container clips it */}
        <table className="data" style={{ position: "relative" }}>
          <caption className="sr-only">Which tools each agent may call. A check mark means the agent may call the tool.</caption>
          <thead>
            <tr>
              <th scope="col">Tool</th>
              {agents.map((a) => (
                <th key={a.role} scope="col" style={{ textAlign: "center" }}>
                  {roleLabel(a.role)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tools.map((t) => (
              <tr key={t}>
                <td>
                  <span className="mono">{t}</span>
                </td>
                {agents.map((a) => {
                  const ok = a.tools.includes(t);
                  return (
                    <td key={a.role} style={{ textAlign: "center" }}>
                      <span aria-hidden className={ok ? "" : "faint"}>
                        {ok ? "✓" : "–"}
                      </span>
                      <span className="sr-only">{ok ? `${roleLabel(a.role)} may call ${t}` : `${roleLabel(a.role)} may not call ${t}`}</span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="small muted" style={{ padding: "10px 14px", borderTop: "1px solid var(--line)" }}>
        Agents cannot read the holdout or production data, and they never grade their own work: the harness computes every evaluation. Read access is enforced by
        database grants, not by these lists; the latest <Link to="/settings#settings-access">access checks</Link> show whether the grants hold.
      </div>
    </Card>
  );
}
