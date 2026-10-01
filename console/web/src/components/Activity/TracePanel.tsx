/**
 * The tool-call trace of the running cycle: newest first, filterable by agent and by kind, each entry expandable to
 * its inputs and outputs. Kinds: proposed = an agent wrote something (a claim); measured = a read-only lookup or a
 * harness result; system = orchestration.
 */
import "./activity.css";
import { memo, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { TraceEntry } from "../../api/types";
import { fmtDateTime, fmtUsd } from "../../lib/format";
import { Card, CodeBlock, EmptyState, KeyValue, KindTag, Pill, links } from "../ui";
import { FilterSelect, ChipFilter, fmtClock, roleLabel } from "../Agents/shared";

type Kind = TraceEntry["kind"];
const KINDS: { value: "all" | Kind; label: string }[] = [
  { value: "all", label: "All" },
  { value: "proposed", label: "Proposed" },
  { value: "measured", label: "Measured" },
  { value: "system", label: "System" },
];
const PAGE = 40;
/** The activity endpoint returns at most this many trace entries for the running cycle. */
const API_LIMIT = 200;

/** Inputs and outputs are JSON text stored by the trace writer (cut at 4,000 characters, so a long one may not parse). */
function pretty(raw: string | null | undefined): string {
  if (raw == null || raw === "") return "Nothing recorded";
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return `${raw}\n\n(cut off by the trace writer at 4,000 characters)`;
  }
}

function EntryDetail({ e }: { e: TraceEntry }) {
  return (
    <div className="activity-detail">
      <KeyValue
        items={[
          ["Tool or step", <code key="a">{e.action}</code>],
          ["Status", e.status],
          ["Changes state", e.state_changing ? "Yes: this call wrote something" : "No: read-only"],
          ["Cost", e.cost_usd > 0 ? fmtUsd(e.cost_usd, 4) : "none"],
          ["Time", fmtDateTime(e.ts)],
        ]}
      />
      <div className="activity-io">
        <div className="stack" style={{ gap: 4 }}>
          <span className="small muted">Inputs</span>
          <CodeBlock>{pretty(e.inputs)}</CodeBlock>
        </div>
        <div className="stack" style={{ gap: 4 }}>
          <span className="small muted">Outputs</span>
          <CodeBlock>{pretty(e.outputs)}</CodeBlock>
        </div>
      </div>
    </div>
  );
}

const Entry = memo(function Entry({ e }: { e: TraceEntry }) {
  const [open, setOpen] = useState(false);
  const failed = e.status !== "ok" && e.status !== "success";
  return (
    <li>
      <details className={`activity-entry ${e.kind}`} onToggle={(ev) => setOpen(ev.currentTarget.open)}>
        <summary>
          <span className="num muted" title={fmtDateTime(e.ts)}>
            {fmtClock(e.ts)}
          </span>
          <span className="activity-who">
            <strong>{roleLabel(e.agent)}</strong> <KindTag kind={e.kind} />
          </span>
          <span className="activity-summary-text">{e.summary}</span>
          <span className="activity-tail">
            {failed ? <Pill tone="crit">{e.status}</Pill> : <span className="xs muted">{e.status}</span>}
            {e.cost_usd > 0 && <span className="num xs muted">{fmtUsd(e.cost_usd, 3)}</span>}
          </span>
        </summary>
        {open && <EntryDetail e={e} />}
      </details>
    </li>
  );
});

export function TracePanel({ trace }: { trace: TraceEntry[] }) {
  const [agent, setAgent] = useState("all");
  const [kind, setKind] = useState<"all" | Kind>("all");
  const [shown, setShown] = useState(PAGE);

  const agents = useMemo(() => {
    const counts = new Map<string, number>();
    for (const t of trace) counts.set(t.agent, (counts.get(t.agent) ?? 0) + 1);
    return [...counts.entries()];
  }, [trace]);
  const byAgent = useMemo(() => (agent === "all" ? trace : trace.filter((t) => t.agent === agent)), [trace, agent]);
  const kindCounts = useMemo(() => {
    const c: Record<string, number> = { all: byAgent.length, proposed: 0, measured: 0, system: 0 };
    for (const t of byAgent) c[t.kind] += 1;
    return c;
  }, [byAgent]);
  const rows = useMemo(
    () => (kind === "all" ? byAgent : byAgent.filter((t) => t.kind === kind)).slice().sort((a, b) => (a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0)),
    [byAgent, kind],
  );

  return (
    <Card flush>
      <div className="activity-filters">
        <FilterSelect
          label="Agent"
          value={agent}
          onChange={(v) => {
            setAgent(v);
            setShown(PAGE);
          }}
          options={[{ value: "all", label: `All agents (${trace.length})` }, ...agents.map(([a, n]) => ({ value: a, label: `${roleLabel(a)} (${n})` }))]}
        />
        <ChipFilter
          label="Kind"
          value={kind}
          onChange={(v) => {
            setKind(v as "all" | Kind);
            setShown(PAGE);
          }}
          options={KINDS.map((k) => ({ ...k, count: kindCounts[k.value] }))}
        />
        <span className="small muted" style={{ marginLeft: "auto" }}>
          Newest first · times in UTC · {rows.length} of {trace.length} entries
          {trace.length >= API_LIMIT && trace[0] && (
            <>
              {" "}
              (the newest {API_LIMIT}; <Link to={links.cycle(trace[0].cycle_id)}>open the cycle</Link> for the rest)
            </>
          )}
        </span>
      </div>
      {rows.length === 0 ? (
        <div style={{ padding: 14 }}>
          <EmptyState title={trace.length ? "No entries match these filters" : "No tool calls recorded yet"}>
            {trace.length
              ? "Choose another agent or kind to see the rest of the trace."
              : "Entries appear when the first agent run ends: the orchestrator writes the trace after every agent run."}
          </EmptyState>
        </div>
      ) : (
        <>
          <ol className="activity-trace">
            {rows.slice(0, shown).map((e) => (
              <Entry key={e.id} e={e} />
            ))}
          </ol>
          {rows.length > shown && (
            <div style={{ padding: 12, textAlign: "center" }}>
              <button type="button" className="btn small" onClick={() => setShown((n) => n + PAGE)}>
                Show {Math.min(PAGE, rows.length - shown)} more (older)
              </button>
            </div>
          )}
        </>
      )}
    </Card>
  );
}
