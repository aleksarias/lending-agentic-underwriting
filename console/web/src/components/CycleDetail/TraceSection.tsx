/**
 * The full trace of a cycle: every tool call and agent run, filterable by agent and by kind (proposed = an agent claim,
 * measured = a harness or tool result, system = orchestration). Each row expands to its recorded inputs and outputs.
 * Filters live in the URL (?agent=&kind=).
 */
import { Fragment, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { TraceEntry } from "../../api/types";
import { fmtDateTime, fmtNum, fmtUsd } from "../../lib/format";
import { CodeBlock, EmptyState, KindTag, Pill, Tabs } from "../ui";
import { RECORDER_LIMIT, TRACE_ROW_LIMIT, agentLabel, clockTime, finalText, looksLikeApiError, parseJson } from "./cycle";

type KindFilter = "all" | TraceEntry["kind"];
const KINDS: KindFilter[] = ["all", "proposed", "measured", "system"];
const KIND_LABEL: Record<KindFilter, string> = { all: "All", proposed: "Proposed", measured: "Measured", system: "System" };
const PAGE = 100;

/** One recorded input or output: pretty-printed when it is JSON, verbatim otherwise. */
function Payload({ label, text }: { label: string; text: string | null | undefined }) {
  const parsed = parseJson(text);
  const cut = !parsed.ok && !!text && text.length >= RECORDER_LIMIT;
  return (
    <div className="cycle-detail-payload">
      <h3 className="cycle-detail-sub">{label}</h3>
      {text == null || text === "" ? (
        <span className="small faint">Nothing was recorded.</span>
      ) : (
        <>
          <CodeBlock>{parsed.ok ? JSON.stringify(parsed.value, null, 2) : text}</CodeBlock>
          {cut && (
            <div className="xs muted">
              The trace keeps the first {fmtNum(RECORDER_LIMIT)} characters of each field, so this is cut off and is not complete JSON.
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function TraceSection({ trace }: { trace: TraceEntry[] }) {
  const [params, setParams] = useSearchParams();
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const [limit, setLimit] = useState(PAGE);

  const agents = [...new Set(trace.map((t) => t.agent))];
  const agent = agents.includes(params.get("agent") ?? "") ? params.get("agent")! : "";
  const kindParam = params.get("kind") as KindFilter | null;
  const kind: KindFilter = kindParam && KINDS.includes(kindParam) ? kindParam : "all";

  const byAgent = trace.filter((t) => !agent || t.agent === agent);
  const rows = byAgent.filter((t) => kind === "all" || t.kind === kind);
  const count = (k: KindFilter) => (k === "all" ? byAgent.length : byAgent.filter((t) => t.kind === k).length);

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
    setLimit(PAGE);
  };
  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  if (trace.length === 0) {
    return (
      <EmptyState title="No trace was recorded for this cycle">
        The trace lists every tool call an agent made and every agent run, with its inputs and outputs. It appears as the cycle runs.
      </EmptyState>
    );
  }
  const shown = rows.slice(0, limit);
  return (
    <div className="stack">
      <div className="row between" style={{ alignItems: "flex-end" }}>
        <Tabs tabs={KINDS.map((k) => ({ key: k, label: `${KIND_LABEL[k]} (${count(k)})` }))} value={kind} onChange={(k) => setParam("kind", k === "all" ? null : k)} />
        <label className="field">
          Agent
          <select value={agent} onChange={(e) => setParam("agent", e.target.value || null)}>
            <option value="">All agents</option>
            {agents.map((a) => (
              <option key={a} value={a}>
                {agentLabel(a)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="xs muted">
        Proposed: an agent wrote or claimed something. Measured: a result the harness or a tool returned. System: the orchestrator's own bookkeeping.
        {trace.length >= TRACE_ROW_LIMIT && ` Only the newest ${fmtNum(TRACE_ROW_LIMIT)} rows are available.`}
      </div>
      {rows.length === 0 ? (
        <EmptyState title="No trace rows match these filters" />
      ) : (
        <div className="table-wrap">
          <table className="data cycle-detail-trace">
            <thead>
              <tr>
                <th>
                  <span className="sr-only">Show inputs and outputs</span>
                </th>
                <th>Time (UTC)</th>
                <th>Agent</th>
                <th>Step</th>
                <th>Kind</th>
                <th>Result</th>
                <th>What happened</th>
                <th className="r">Cost</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((t) => {
                const isOpen = open.has(t.id);
                const apiError = looksLikeApiError(finalText(t));
                return (
                  <Fragment key={t.id}>
                    <tr>
                      <td>
                        <button
                          type="button"
                          className="cycle-detail-toggle"
                          aria-expanded={isOpen}
                          aria-controls={isOpen ? `trace-${t.id}` : undefined}
                          onClick={() => toggle(t.id)}
                        >
                          <span aria-hidden>{isOpen ? "▾" : "▸"}</span>
                          <span className="sr-only">
                            {isOpen ? "Hide" : "Show"} inputs and outputs of {t.action}
                          </span>
                        </button>
                      </td>
                      <td className="nowrap">
                        <time dateTime={t.ts} title={fmtDateTime(t.ts)}>
                          {clockTime(t.ts)}
                        </time>
                      </td>
                      <td>{agentLabel(t.agent)}</td>
                      <td>
                        <span className="mono">{t.action}</span>
                        {t.state_changing && <div className="xs muted">changes state</div>}
                      </td>
                      <td>
                        <KindTag kind={t.kind} />
                      </td>
                      <td>{t.status === "ok" || t.status === "success" ? <Pill tone="good">ok</Pill> : <Pill tone="crit">{t.status}</Pill>}</td>
                      <td className="cycle-detail-summary">
                        {t.summary}
                        {apiError && (
                          <div>
                            <Pill tone="warn">final message is an API error</Pill>
                          </div>
                        )}
                      </td>
                      <td className="r">{t.cost_usd > 0 ? fmtUsd(t.cost_usd, 3) : "—"}</td>
                    </tr>
                    {isOpen && (
                      <tr id={`trace-${t.id}`} className="cycle-detail-expand">
                        <td colSpan={8}>
                          <div className="cycle-detail-payloads">
                            <Payload label="Inputs" text={t.inputs} />
                            <Payload label="Outputs" text={t.outputs} />
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="row between small muted">
        <span>
          Showing {shown.length} of {rows.length} row{rows.length === 1 ? "" : "s"}
          {rows.length !== trace.length ? ` (${trace.length} in the whole trace)` : ""}.
        </span>
        {rows.length > shown.length && (
          <button type="button" className="btn small" onClick={() => setLimit((l) => l + PAGE)}>
            Show {Math.min(PAGE, rows.length - shown.length)} more
          </button>
        )}
      </div>
    </div>
  );
}
