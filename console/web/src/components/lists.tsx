/**
 * Shared lists that several screens show the same way: the event timeline, pipeline freshness and the
 * "waiting for a person" inbox. Use these instead of re-implementing them per page.
 */
import { Link } from "react-router-dom";
import type { EventItem, EventType, StageFreshness, WaitingItem } from "../api/types";
import { fmtDateTime, fmtSeconds, shortVersion, titleCase } from "../lib/format";
import { Badges, EmptyState, KindTag, Pill, TimeAgo } from "./ui";

export const EVENT_LABELS: Record<EventType, string> = {
  definition_activated: "Definition",
  data_loaded: "Data",
  stage_built: "Build",
  stage_failed: "Build failed",
  cycle_started: "Cycle",
  cycle_finished: "Cycle",
  evaluation: "Evaluation",
  gate: "Holdout gate",
  approval: "Approval",
  promotion: "Promotion",
  rollback: "Rollback",
  alert: "Alert",
  budget_stop: "Budget",
  config_changed: "Config",
  report: "Agent report",
  benchmark: "Evidence",
};

/** Which events carry an agent claim versus a measurement (everything else is system bookkeeping). */
const EVENT_KIND: Partial<Record<EventType, "proposed" | "measured">> = {
  report: "proposed",
  evaluation: "measured",
  gate: "measured",
  benchmark: "measured",
  alert: "measured",
};

export function EventList({ events, showDefinition = true, empty }: { events: EventItem[]; showDefinition?: boolean; empty?: string }) {
  if (!events.length) return <EmptyState title={empty ?? "No events yet"}>Events appear as the pipeline, agents, harness and people act.</EmptyState>;
  return (
    <ol className="timeline">
      {events.map((e) => (
        <li key={e.id} className={`item ${e.tone}`}>
          <div className="when small muted" title={fmtDateTime(e.ts)}>
            <TimeAgo iso={e.ts} />
          </div>
          <div className="what">
            <div className="row" style={{ gap: 6 }}>
              <Pill tone={e.tone}>{EVENT_LABELS[e.type] ?? titleCase(e.type)}</Pill>
              {EVENT_KIND[e.type] && <KindTag kind={EVENT_KIND[e.type]!} />}
              {e.href ? <Link to={e.href}>{e.title}</Link> : <span>{e.title}</span>}
            </div>
            {(e.detail || e.actor || (showDefinition && e.definition_version)) && (
              <div className="xs muted row" style={{ gap: 10, marginTop: 2 }}>
                {e.detail && <span>{e.detail}</span>}
                {e.actor && <span>by {e.actor}</span>}
                {showDefinition && e.definition_version && (
                  <Link className="mono" to={`/definitions/${e.definition_version}`} title="Definition of default in effect">
                    def {shortVersion(e.definition_version)}
                  </Link>
                )}
              </div>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

const STAGE_TONE = { fresh: "good", stale: "warn", failed: "crit", never: "neutral" } as const;

export function StageList({ stages }: { stages: StageFreshness[] }) {
  if (!stages.length) return <EmptyState title="No pipeline runs yet">Stages appear after the first `lau default-definition apply`.</EmptyState>;
  return (
    <ul className="list">
      {stages.map((s) => (
        <li key={s.stage} className="item row between">
          <span>{titleCase(s.stage)}</span>
          <span className="row" style={{ gap: 8 }}>
            {s.last_run_at && (
              <span className="xs muted" title={fmtDateTime(s.last_run_at)}>
                <TimeAgo iso={s.last_run_at} />
                {s.duration_s != null ? ` · ${fmtSeconds(s.duration_s)}` : ""}
              </span>
            )}
            <Pill tone={STAGE_TONE[s.status]}>{s.status}</Pill>
          </span>
          {s.reason && <span className="xs muted" style={{ flexBasis: "100%" }}>{s.reason}</span>}
        </li>
      ))}
    </ul>
  );
}

export function WaitingList({ items }: { items: WaitingItem[] }) {
  if (!items.length) return <EmptyState title="Nothing is waiting for a person">Candidates appear here once they pass validation and have red-team and compliance reports.</EmptyState>;
  return (
    <ul className="list">
      {items.map((w) => (
        <li key={w.id} className="item stack" style={{ gap: 4 }}>
          <div className="row between">
            <Link to={w.href}>
              <strong>{w.title}</strong>
            </Link>
            <span className="xs muted" title={fmtDateTime(w.created_at)}>
              waiting <TimeAgo iso={w.created_at} />
            </span>
          </div>
          <Badges items={w.badges} />
        </li>
      ))}
    </ul>
  );
}
