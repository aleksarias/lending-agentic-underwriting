/** Forecast tiles, the next plan preview and the hypothesis backlog on the Upcoming screen. */
import { Link } from "react-router-dom";
import { useFeatures } from "../../api/hooks";
import type { StatusSummary, Tile, UpcomingData } from "../../api/types";
import { fmtDiff, fmtNum, fmtPct, fmtUsd } from "../../lib/format";
import { Card, DataTable, EmptyState, Json, KindTag, Tiles, links } from "../ui";
import { LinkedText, ModelKeyBadge } from "../Agents/shared";

// ---------------------------------------------------------------------------------------------------- forecast
export function ForecastTiles({ f, status }: { f: UpcomingData["forecast"]; status: StatusSummary | undefined }) {
  const hard = status?.budget.hard_stop_usd ?? null;
  const share = f.month_end_usd != null && hard ? f.month_end_usd / hard : null;
  const m = f.maturation;
  const tiles: Tile[] = [
    {
      key: "month_end",
      label: "Projected month-end spend",
      value: f.month_end_usd == null ? "—" : fmtUsd(f.month_end_usd),
      sub: f.month_end_usd == null ? "no spend yet this month" : hard ? `${fmtPct(share, 1)} of the ${fmtUsd(hard, 0)} hard stop` : "straight-line projection",
      tone: share == null ? null : share >= 0.9 ? "crit" : share >= 0.75 ? "warn" : null,
      href: "/cost",
    },
    { key: "tests", label: "Validation tests since reset", value: fmtNum(f.tests_since_reset), sub: "under the active definition", href: "/performance" },
    { key: "margin", label: "Margin the next candidate must clear", value: fmtDiff(f.next_margin, 4), sub: "AUC over the reference; it rises with every test", href: "/performance" },
    {
      key: "holdout",
      label: "Holdout gates left",
      value: fmtNum(f.holdout_remaining),
      sub: "runs left for the active definition",
      tone: f.holdout_remaining === 0 ? "warn" : null,
      href: "/performance",
    },
  ];
  if (m) {
    tiles.push({
      key: "maturation",
      label: "Next maturation window",
      value: m.months_until_next_window == null ? "—" : `${m.months_until_next_window} month${m.months_until_next_window === 1 ? "" : "s"}`,
      sub: "of further performance data needed",
      href: links.definition(m.definition_version),
    });
  }
  return (
    <>
      <Tiles tiles={tiles} />
      <div className="small muted">
        Month-end spend is a straight-line projection: this month's spend so far, extended at the same daily rate. It is not a budget.
        {m && ` ${m.note}`}
      </div>
    </>
  );
}

// ------------------------------------------------------------------------------------------------------ plan
const PLAN_KEYS = ["focus", "goals", "feature_hypotheses", "model_types", "n_experiments", "run_profiler"];

const asList = (v: unknown): string[] => (Array.isArray(v) ? v.map((x) => (typeof x === "string" ? x : JSON.stringify(x))) : []);

export function PlanPreview({ plan, cycleId }: { plan: Record<string, unknown> | null; cycleId: string | null }) {
  if (!plan) {
    return <EmptyState title="No plan yet">The planner writes a plan at the start of every improvement cycle. The latest one appears here once a cycle has run.</EmptyState>;
  }
  const focus = typeof plan.focus === "string" ? plan.focus : "";
  const goals = asList(plan.goals);
  const hyps = asList(plan.feature_hypotheses);
  const models = asList(plan.model_types);
  const extras = Object.fromEntries(Object.entries(plan).filter(([k]) => !PLAN_KEYS.includes(k)));
  return (
    <Card kind="proposed">
      <div className="row between" style={{ marginBottom: 6 }}>
        <strong>Latest plan from the planner agent</strong>
        <span className="row" style={{ gap: 8 }}>
          {cycleId && (
            <Link className="mono small" to={links.cycle(cycleId)}>
              {cycleId}
            </Link>
          )}
          <KindTag kind="proposed" />
        </span>
      </div>
      <div className="stack" style={{ gap: 12 }}>
        <div>
          <div className="small muted">Focus</div>
          <p style={{ margin: "2px 0 0" }}>{focus ? <LinkedText text={focus} /> : <span className="muted">No focus stated.</span>}</p>
        </div>
        <div>
          <div className="small muted">Goals</div>
          {goals.length ? (
            <ol style={{ margin: "2px 0 0", paddingLeft: 20, display: "grid", gap: 4 }}>
              {goals.map((g, i) => (
                <li key={i}>
                  <LinkedText text={g} />
                </li>
              ))}
            </ol>
          ) : (
            <p className="muted" style={{ margin: "2px 0 0" }}>No goals listed.</p>
          )}
        </div>
        <div>
          <div className="small muted">Feature hypotheses to test</div>
          {hyps.length ? (
            <ul style={{ margin: "2px 0 0", paddingLeft: 20, display: "grid", gap: 4 }}>
              {hyps.map((h, i) => (
                <li key={i}>
                  <LinkedText text={h} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted" style={{ margin: "2px 0 0" }}>None listed.</p>
          )}
        </div>
        <div className="row" style={{ gap: 24, alignItems: "flex-start" }}>
          <div>
            <div className="small muted">Model types</div>
            <div className="row" style={{ gap: 6, marginTop: 2 }}>
              {models.length ? models.map((m) => <span key={m} className="badge mono">{m}</span>) : <span className="muted">not stated</span>}
            </div>
          </div>
          <div>
            <div className="small muted">Validation tests planned</div>
            <div className="num" style={{ marginTop: 2 }}>{typeof plan.n_experiments === "number" ? plan.n_experiments : "not stated"}</div>
          </div>
          <div>
            <div className="small muted">Runs the data profiler first</div>
            <div style={{ marginTop: 2 }}>{typeof plan.run_profiler === "boolean" ? (plan.run_profiler ? "Yes" : "No") : "not stated"}</div>
          </div>
        </div>
        {Object.keys(extras).length > 0 && (
          <details>
            <summary className="small">Other plan fields</summary>
            <Json value={extras} />
          </details>
        )}
      </div>
    </Card>
  );
}

// --------------------------------------------------------------------------------------------------- backlog
interface BacklogRow {
  key: string;
  name: string | null;
  text: string;
  source: string;
}

/** Backlog entries from feature proposals read "name: hypothesis"; anything else is shown whole. */
function toRow(b: UpcomingData["backlog"][number], i: number): BacklogRow {
  const m = /^([a-z][a-z0-9_]{2,40}): (.*)$/s.exec(b.hypothesis);
  return { key: `${i}-${b.source}`, name: m ? m[1] : null, text: m ? m[2] : b.hypothesis, source: b.source };
}

/** "feature proposal (cy-...)" -> "Feature proposal in cycle cy-..." with the cycle linked. */
function SourceCell({ source }: { source: string }) {
  const m = /^(.*?) \((cy-[0-9a-z-]+)\)$/.exec(source);
  if (!m) return <LinkedText text={source} />;
  const kind = m[1] === "planner" ? "Planner goal" : m[1] === "feature proposal" ? "Feature proposal" : m[1];
  return (
    <span>
      {kind} in cycle{" "}
      <Link className="mono nowrap" to={links.cycle(m[2])}>
        {m[2]}
      </Link>
    </span>
  );
}

export function Backlog({ backlog }: { backlog: UpcomingData["backlog"] }) {
  const features = useFeatures();
  const used = new Map((features.data ?? []).map((f) => [f.name, f.used_in]));
  const rows = backlog.map(toRow);
  const tried = (r: BacklogRow) => (r.name && used.has(r.name) ? used.get(r.name)!.length : null);
  return (
    <Card flush kind="proposed">
      <DataTable
        rows={rows}
        rowKey={(r) => r.key}
        maxHeight={460}
        empty={
          <EmptyState title="No open hypotheses">
            Proposed features that no model has used yet, and lessons still to be re-verified under the active definition, appear here.
          </EmptyState>
        }
        columns={[
          {
            key: "name",
            header: "Proposal",
            render: (r) =>
              r.name ? (
                <div className="stack" style={{ gap: 2 }}>
                  <Link className="mono" to={`/features?q=${encodeURIComponent(r.name)}`}>
                    {r.name}
                  </Link>
                  <span className="small">{r.text}</span>
                </div>
              ) : (
                <span className="small">
                  <LinkedText text={r.text} />
                </span>
              ),
            sort: (r) => r.name ?? r.text,
          },
          { key: "source", header: "Source", render: (r) => <span className="small"><SourceCell source={r.source} /></span>, sort: (r) => r.source },
          {
            key: "tried",
            header: "Already used in a model",
            render: (r) => {
              if (!r.name) return <span className="muted">—</span>;
              if (features.isLoading) return <span className="muted">…</span>;
              const models = used.get(r.name);
              if (!models) return <span className="muted">—</span>;
              return models.length ? (
                <span className="row" style={{ gap: 4 }}>
                  {models.map((k) => (
                    <ModelKeyBadge key={k} modelKey={k} />
                  ))}
                </span>
              ) : (
                <span className="muted">not yet</span>
              );
            },
            sort: (r) => tried(r),
          },
        ]}
      />
    </Card>
  );
}
