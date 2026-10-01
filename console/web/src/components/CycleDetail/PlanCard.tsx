/** The plan the planner agent submitted for a cycle: focus, goals, hypotheses, model types, limits. An agent claim. */
import { Card, EmptyState, Json, KindTag, Pill } from "../ui";
import { asStrings } from "./cycle";

const KNOWN = new Set(["focus", "goals", "feature_hypotheses", "model_types", "n_experiments", "run_profiler"]);

function Sub({ children }: { children: string }) {
  return <h3 className="cycle-detail-sub">{children}</h3>;
}

function Numbered({ items }: { items: string[] }) {
  return (
    <ol className="cycle-detail-list">
      {items.map((t, i) => (
        <li key={i}>{t}</li>
      ))}
    </ol>
  );
}

/** A field this screen does not know: short values inline, anything structured as JSON. */
function Extra({ name, value }: { name: string; value: unknown }) {
  const inline = typeof value === "string" || typeof value === "number" || typeof value === "boolean";
  return (
    <div>
      <Sub>{name.replace(/_/g, " ")}</Sub>
      {inline ? <div>{String(value)}</div> : <Json value={value} />}
    </div>
  );
}

export function PlanCard({ plan, experimentsCap }: { plan: Record<string, unknown> | null; experimentsCap: number | null }) {
  if (!plan) {
    return (
      <EmptyState title="No plan was recorded for this cycle">
        The planner agent submits a plan at the start of a cycle (its focus, goals, feature hypotheses and model types). This cycle has none, so there is nothing to show
        here. If the orchestrator fell back to a default plan, it is written in the cycle report at the end of this page.
      </EmptyState>
    );
  }
  const focus = typeof plan.focus === "string" ? plan.focus : null;
  const goals = asStrings(plan.goals);
  const hypotheses = asStrings(plan.feature_hypotheses);
  const modelTypes = asStrings(plan.model_types);
  const n = typeof plan.n_experiments === "number" ? plan.n_experiments : null;
  const profiler = typeof plan.run_profiler === "boolean" ? plan.run_profiler : null;
  const extras = Object.entries(plan).filter(([k]) => !KNOWN.has(k));
  return (
    <Card kind="proposed" title="Plan submitted by the planner agent">
      <div className="stack" style={{ gap: 14 }}>
        <div className="small muted">
          <KindTag kind="proposed" /> An agent's plan. The harness does not check what it claims; figures quoted in it are the agent's reading of earlier results.
        </div>
        {focus && (
          <div>
            <Sub>Focus</Sub>
            <p className="cycle-detail-focus">{focus}</p>
          </div>
        )}
        {goals.length > 0 && (
          <div>
            <Sub>Goals</Sub>
            <Numbered items={goals} />
          </div>
        )}
        {hypotheses.length > 0 && (
          <div>
            <Sub>Feature hypotheses</Sub>
            <Numbered items={hypotheses} />
          </div>
        )}
        <dl className="kv">
          <dt>Model types to try</dt>
          <dd>
            {modelTypes.length ? (
              <span className="row" style={{ gap: 6 }}>
                {modelTypes.map((m) => (
                  <Pill key={m} tone="info">
                    {m}
                  </Pill>
                ))}
              </span>
            ) : (
              <span className="muted">not specified</span>
            )}
          </dd>
          <dt>Harness evaluations allowed</dt>
          <dd>
            {n == null ? (
              <span className="muted">not specified</span>
            ) : (
              <span className="num">
                at most {n}
                {experimentsCap != null ? ` (the cycle cap is ${experimentsCap})` : ""}
              </span>
            )}
          </dd>
          <dt>Profiler agent</dt>
          <dd>{profiler == null ? <span className="muted">not specified</span> : profiler ? "runs first, to profile the data" : "skipped"}</dd>
        </dl>
        {extras.map(([k, v]) => (
          <Extra key={k} name={k} value={v} />
        ))}
        <details className="cycle-detail-raw">
          <summary>Raw plan as submitted (JSON)</summary>
          <Json value={plan} />
        </details>
      </div>
    </Card>
  );
}
