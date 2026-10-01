/** Always-visible context: verdict, serving model, active definition, API/feed, activity, budget, waiting, alerts. */
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useSearch, useStatus } from "../api/hooks";
import type { StatusSummary } from "../api/types";
import { fmtAgo, fmtUsd, shortVersion, verdictLabel, verdictTone } from "../lib/format";
import { Pill } from "./ui";

function Search() {
  const [term, setTerm] = useState("");
  const [open, setOpen] = useState(false);
  const results = useSearch(term);
  const nav = useNavigate();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && !(e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement)) {
        e.preventDefault();
        ref.current?.querySelector("input")?.focus();
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div className="search" ref={ref}>
      <label className="sr-only" htmlFor="global-search">
        Search models, cycles, features, variables, reports
      </label>
      <input
        id="global-search"
        type="search"
        placeholder="Search  ( / )"
        value={term}
        onChange={(e) => {
          setTerm(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && results.data?.[0]) {
            nav(results.data[0].href);
            setOpen(false);
          }
        }}
      />
      {open && term.trim().length >= 2 && (
        <div className="results" role="listbox">
          {results.isLoading && <div className="small muted" style={{ padding: 8 }}>Searching…</div>}
          {results.data?.length === 0 && <div className="small muted" style={{ padding: 8 }}>No matches</div>}
          {results.data?.map((r) => (
            <Link key={`${r.type}:${r.id}`} to={r.href} onClick={() => setOpen(false)} role="option">
              <div className="row between">
                <strong className="small">{r.title}</strong>
                <span className="xs faint">{r.type}</span>
              </div>
              {r.subtitle && <div className="xs muted">{r.subtitle}</div>}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function Chips({ s }: { s: StatusSummary }) {
  const activity =
    s.activity.state === "cycle_running" ? (
      <Link to="/activity">
        <Pill tone="warn" dot>
          Cycle running{s.activity.step ? ` · ${s.activity.step}` : ""}
        </Pill>
      </Link>
    ) : s.activity.state === "pipeline_rebuilding" ? (
      <Link to="/activity">
        <Pill tone="warn" dot>
          Pipeline rebuilding
        </Pill>
      </Link>
    ) : (
      <Pill tone="neutral">Idle</Pill>
    );
  return (
    <>
      <Link to="/progress" title={s.verdict?.stale ? "Improvement verdict (out of date: newer results exist)" : "Improvement verdict"}>
        <Pill tone={verdictTone(s.verdict?.code)}>
          {verdictLabel(s.verdict?.code)}
          {s.verdict?.stale ? " · out of date" : ""}
        </Pill>
      </Link>
      <Link className="badge" to={s.serving ? `/models/${encodeURIComponent(s.serving.name)}/${encodeURIComponent(s.serving.version)}` : "/models"} title="Model making decisions">
        Serving: <strong>{s.serving ? s.serving.label : "legacy policy"}</strong>
        {s.serving_superseded && <Pill tone="warn">superseded</Pill>}
      </Link>
      {s.active_definition && (
        <Link className="badge" to={`/definitions/${s.active_definition.version}`} title="Active definition of default">
          <span className="mono">{shortVersion(s.active_definition.version)}</span>
          {s.active_definition.summary}
          {!s.yaml_matches_active && <Pill tone="warn">YAML differs</Pill>}
        </Link>
      )}
      <Link to="/decisions" title="Decision API">
        <Pill tone={s.api.live ? "good" : "neutral"}>{s.api.live ? "API live" : "API not live"}</Pill>
      </Link>
      <Link to="/feed" title="Loan status feed">
        <Pill tone={s.feed.live ? "good" : "neutral"}>{s.feed.live ? `Feed ${fmtAgo(s.feed.last_received_at)}` : "Feed not connected"}</Pill>
      </Link>
      {activity}
    </>
  );
}

export function StatusBar({ onMenu, onAsk }: { onMenu: () => void; onAsk: () => void }) {
  const status = useStatus();
  const s = status.data;
  return (
    <div className={`statusbar ${s?.environment === "prod" ? "prod" : ""}`}>
      <button className="btn small menu-button" type="button" onClick={onMenu} aria-label="Open navigation">
        Menu
      </button>
      {s ? <Chips s={s} /> : <span className="small muted">{status.error ? "Status unavailable" : "Loading status…"}</span>}
      <span className="spacer" />
      {s && (
        <>
          <Link to="/cost" title="Month-to-date spend against the hard stop">
            <Pill tone={s.budget.month_to_date_usd >= 0.9 * s.budget.hard_stop_usd ? "crit" : s.budget.month_to_date_usd >= 0.75 * s.budget.hard_stop_usd ? "warn" : "neutral"}>
              {fmtUsd(s.budget.month_to_date_usd)} of {fmtUsd(s.budget.hard_stop_usd, 0)}
            </Pill>
          </Link>
          {s.decisions_waiting > 0 && (
            <Link to="/approvals">
              <Pill tone="accent">{s.decisions_waiting} waiting</Pill>
            </Link>
          )}
          {s.alerts_open.high + s.alerts_open.medium > 0 && (
            <Link to="/alerts">
              <Pill tone={s.alerts_open.high ? "crit" : "warn"}>
                {s.alerts_open.high + s.alerts_open.medium} {s.alerts_open.high + s.alerts_open.medium === 1 ? "alert" : "alerts"}
              </Pill>
            </Link>
          )}
          <Pill tone={s.environment === "prod" ? "crit" : "neutral"}>
            {s.environment} · {s.data_mode}
          </Pill>
          {s.snapshot?.mode === "mirror" && (
            <span title={s.snapshot.error ? `Last sync failed: ${s.snapshot.error}` : "The console mirrors the workspace through its snapshot; it refreshes every minute"}>
              <Pill tone={s.snapshot.error ? "warn" : "neutral"}>
                data as of {s.snapshot.published_at ? fmtAgo(s.snapshot.published_at) : "no snapshot yet"}
              </Pill>
            </span>
          )}
          {s.snapshot?.mode === "fixture" && <Pill tone="warn">exported copy</Pill>}
        </>
      )}
      <Search />
      <button className="btn small" type="button" onClick={onAsk}>
        Ask
      </button>
    </div>
  );
}
