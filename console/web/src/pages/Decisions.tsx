/**
 * Screen 3 — Decisions: what is the real-time decision API doing?
 *
 * Every figure comes from the decision log (ops.decisions): outcomes, reasons, versions and latency of real decisions
 * made by the live decision model, test traffic excluded. When nothing has been decided yet, the screen says exactly
 * which step is missing (approve a policy, build the decision model, send traffic) instead of showing examples.
 */
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useDecisionSearch, useDecisions } from "../api/hooks";
import type { DecisionApiStatus, DecisionRow, DecisionsData, PolicyInfo, Tile } from "../api/types";
import { BarSeriesChart, useChartColors } from "../components/charts";
import { Banner, Card, CodeBlock, DataTable, EmptyState, KeyValue, Page, PageHeader, Pill, QueryView, Section, Tiles, TimeAgo, type Column } from "../components/ui";
import { fmtDateTime, fmtNum, fmtPct, shortVersion } from "../lib/format";
import { OutcomePill } from "../components/Decisions/OutcomePill";
import { WhatIfSection } from "../components/Decisions/WhatIf";
import "../components/Decisions/Decisions.css";

const PATH_LABEL: Record<string, string> = { model: "Model and policy", knockout: "Knock-out rule", legacy: "Legacy policy" };
const STATE_TEXT: Record<DecisionApiState, { label: string; tone: "good" | "warn" | "neutral" | "crit" }> = {
  endpoint: { label: "Serving endpoint live", tone: "good" },
  endpoint_not_ready: { label: "Endpoint starting or updating", tone: "warn" },
  in_process: { label: "Deciding in process (no endpoint)", tone: "neutral" },
  not_built: { label: "No decision model built", tone: "warn" },
  no_policy: { label: "No approved policy", tone: "warn" },
};
type DecisionApiState = DecisionApiStatus["state"];

function decidesWith(api: DecisionApiStatus): string {
  const v = api.live_build?.versions ?? {};
  const model = v.model_version ? `production model v${v.model_version}` : "the legacy policy (no model serves)";
  const shadow = v.shadow_model_version ? `, with v${v.shadow_model_version} scoring in shadow` : "";
  return `${model}${shadow}`;
}

function summarySentence(d: DecisionsData): string {
  if (!d.available || !d.totals || !d.shares) return d.reason ?? "No decision has been made yet.";
  const t = d.totals;
  const s = d.shares;
  const fallback = t.fallback ? ` ${fmtPct(s.fallback, 1)} fell back to the legacy policy.` : " None fell back to the legacy policy.";
  return (
    `${fmtNum(t.n)} decisions in the ${d.window_days} days to ${fmtDateTime(d.as_of)}: ${fmtPct(s.approve, 1)} approved, ` +
    `${fmtPct(s.refer, 1)} referred to a person, ${fmtPct(s.decline, 1)} declined.${fallback} ` +
    `The live decision model decides with ${decidesWith(d.api)}.`
  );
}

export default function Decisions() {
  const q = useDecisions();
  return (
    <Page>
      <QueryView query={q} loadingHeight={320}>
        {(d) => (
          <>
            <PageHeader
              eyebrow="Now"
              title="Decisions"
              summary={summarySentence(d)}
              meta={d.as_of ? <span>Newest decision <TimeAgo iso={d.as_of} /></span> : undefined}
            />
            <ApiSection api={d.api} />
            {d.available ? <LiveSections d={d} /> : <NextStep d={d} />}
            <PolicySection policy={d.policy} />
            {d.tradeoff && d.tradeoff.points.length > 0 && <WhatIfSection t={d.tradeoff} />}
          </>
        )}
      </QueryView>
    </Page>
  );
}

// ---------------------------------------------------------------------------------------------------- the API itself
function ApiSection({ api }: { api: DecisionApiStatus }) {
  const state = STATE_TEXT[api.state];
  const ep = api.endpoint;
  const build = api.live_build;
  const endpointText = !ep.known
    ? "Not reported here: the endpoint's state comes with the console snapshot (lau console --mirror)."
    : ep.exists
      ? `${ep.name}: ${ep.ready ? "ready" : "not ready"}${ep.updating ? ", updating" : ""}${ep.update_failed ? ", last update failed" : ""}; serves decision model v${ep.served_version ?? "?"} (${ep.workload_size ?? "?"} CPU${ep.scale_to_zero ? ", scales to zero when idle" : ""})`
      : `${ep.name} is not created. Creating it is compute and needs your approval: lau decision deploy --create`;
  return (
    <Section
      title="Decision API"
      right={<Pill tone={state.tone}>{state.label}</Pill>}
      note="One registered decision model holds the serving champion, the approved policy and the reason statements. It is the same artifact whether it runs on the endpoint or in process."
    >
      <div className="stack">
        {api.gaps.length > 0 && (
          <Banner tone="warn" title="Registry, live build and endpoint disagree">
            <ul className="plain">
              {api.gaps.map((g) => (
                <li key={g}>{g}</li>
              ))}
            </ul>
          </Banner>
        )}
        <div className="grid cols-2">
          <Card title="What decides">
            <KeyValue
              items={[
                ["Live decision model", build ? <span>v{build.version} <span className="mono xs muted">build {build.build_id}</span></span> : <span className="muted">none built</span>],
                ["Built", build ? <span>{fmtDateTime(build.built_at)} by {build.built_by ?? "unknown"}</span> : "—"],
                ["Decides with", build ? decidesWith(api) : "—"],
                ["Policy", api.policy_version ? <span className="mono">{api.policy_version}</span> : <span className="muted">none active</span>],
                ["Endpoint", <span key="ep" className="small">{endpointText}</span>],
              ]}
            />
          </Card>
          <Card title="Release checks" kind="measured">
            {api.checks.length === 0 ? (
              <p className="small muted" style={{ margin: 0 }}>
                None run yet. <span className="mono">lau decision check parity</span>, <span className="mono">load</span> and <span className="mono">rollback</span> record
                their results here.
              </p>
            ) : (
              <ul className="plain small">
                {api.checks.map((c) => (
                  <li key={c.check} style={{ marginBottom: 6 }}>
                    <Pill tone={c.passed ? "good" : "crit"}>{c.passed ? "pass" : "fail"}</Pill> <strong>{CHECK_LABEL[c.check] ?? c.check}</strong>{" "}
                    <span className="muted">
                      <TimeAgo iso={c.run_at} />
                    </span>
                    <div className="xs muted">{c.summary}</div>
                  </li>
                ))}
              </ul>
            )}
            <div className="xs muted">
              Targets per single request: p95 under {api.targets.p95_ms} ms, p99 under {api.targets.p99_ms} ms.
            </div>
          </Card>
        </div>
      </div>
    </Section>
  );
}

const CHECK_LABEL: Record<string, string> = {
  parity: "Training–serving parity",
  load: "Latency under load",
  rollback: "Rollback drill",
};

function NextStep({ d }: { d: DecisionsData }) {
  const step =
    d.api.state === "no_policy"
      ? ["lau policy plan", "lau policy approve", "lau policy apply"]
      : d.api.state === "not_built"
        ? ["lau decision build"]
        : ["lau decision originate --via inprocess"];
  return (
    <Section title="Live decisions">
      <EmptyState title="No decisions to show yet">
        <p style={{ marginTop: 0 }}>{d.reason}</p>
        <CodeBlock>{step.join("\n")}</CodeBlock>
        <p className="small muted" style={{ marginBottom: 0 }}>
          Approving a policy needs a person at a terminal. Decisions appear here after the next console snapshot.
        </p>
      </EmptyState>
    </Section>
  );
}

// ---------------------------------------------------------------------------------------------------- live decisions
function LiveSections({ d }: { d: DecisionsData }) {
  const c = useChartColors();
  const t = d.totals!;
  const s = d.shares!;
  const load = d.latency?.load_check;
  const tiles: Tile[] = [
    { key: "n", label: `Decisions, ${d.window_days} days`, value: fmtNum(t.n), sub: `${fmtNum(t.approve)} approved` },
    { key: "approve", label: "Approved", value: fmtPct(s.approve, 1), tone: "good" },
    { key: "refer", label: "Referred to a person", value: fmtPct(s.refer, 1), tone: "warn" },
    { key: "decline", label: "Declined", value: fmtPct(s.decline, 1), tone: "crit" },
    {
      key: "fallback",
      label: "Legacy fallback",
      value: fmtPct(s.fallback, 1),
      sub: t.fallback ? "the model failed or ran out of time" : "never needed",
      tone: t.fallback ? "warn" : "good",
    },
    {
      key: "latency",
      label: "p99 latency (load check)",
      value: load?.details?.p99_ms != null ? `${Math.round(Number(load.details.p99_ms))} ms` : "not measured",
      sub: load ? (load.passed ? "within target" : "outside target") : "lau decision check load",
      tone: load ? (load.passed ? "good" : "crit") : "neutral",
    },
  ];
  return (
    <>
      <Section title="Outcomes">
        <div className="stack">
          <Tiles tiles={tiles} />
          {(t.reasons_missing > 0 || t.unmapped > 0) && (
            <Banner tone="crit" title="Some adverse decisions are not fully explained">
              {t.reasons_missing > 0 && <div>{fmtNum(t.reasons_missing)} declines or referrals have no principal reasons: no notice can be sent for them.</div>}
              {t.unmapped > 0 && <div>{fmtNum(t.unmapped)} use a reason without an approved statement (R99): add it to config/reason_statements.yaml.</div>}
            </Banner>
          )}
          <Card>
            <BarSeriesChart
              title="Decisions per day"
              data={d.daily}
              xKey="date"
              stacked
              series={[
                { key: "approve", label: "Approved", color: c.good },
                { key: "refer", label: "Referred", color: c.warn },
                { key: "decline", label: "Declined", color: c.crit },
              ]}
              height={240}
            />
          </Card>
          <div className="grid cols-2">
            <Card title="How each decision was made">
              <KeyValue items={d.paths.map((p) => [PATH_LABEL[p.path] ?? p.path, <span key={p.path} className="num">{fmtNum(p.n)} ({fmtPct(p.n / t.n, 1)})</span>])} />
            </Card>
            <Card title="Approval rate by risk band" kind="measured">
              <KeyValue items={d.bands.map((b) => [`Band ${b.band}`, <span key={b.band} className="num">{fmtPct(b.approve_share, 1)} of {fmtNum(b.n)}</span>])} />
            </Card>
          </div>
        </div>
      </Section>

      <Section title="Principal reasons for declines" note="Statements an applicant would read, most frequent first. Counsel approves the statement list and the notice itself before anything is sent.">
        <Card flush>
          <DataTable
            rows={d.reasons}
            rowKey={(r) => r.code}
            initialSort={{ key: "n", dir: "desc" }}
            empty={<EmptyState title="No declines in this window" />}
            columns={[
              { key: "code", header: "Code", render: (r) => <span className="mono">{r.code}</span>, sort: (r) => r.code },
              { key: "statement", header: "Statement", render: (r) => r.statement },
              { key: "n", header: "Declines", render: (r) => fmtNum(r.n), sort: (r) => r.n, align: "right" },
              { key: "share", header: "Share of declines", render: (r) => fmtPct(r.share, 1), sort: (r) => r.share, align: "right" },
            ]}
          />
        </Card>
      </Section>

      <Section title="Versions that decided" note="Every decision records the model, policy and build it used, so any decision can be replayed and explained later.">
        <Card flush>
          <DataTable
            rows={d.versions}
            rowKey={(r) => `${r.model_version}-${r.policy_version}-${r.build_id}`}
            initialSort={{ key: "last", dir: "desc" }}
            columns={[
              { key: "model", header: "Model", render: (r) => (r.model_version ? `production v${r.model_version}` : "legacy policy") },
              { key: "policy", header: "Policy", render: (r) => <span className="mono">{shortVersion(r.policy_version)}</span> },
              { key: "build", header: "Build", render: (r) => <span className="mono xs">{r.build_id ?? "—"}</span> },
              { key: "n", header: "Decisions", render: (r) => fmtNum(r.n), sort: (r) => r.n, align: "right" },
              { key: "last", header: "Last used", render: (r) => <TimeAgo iso={r.last} />, sort: (r) => r.last },
            ]}
          />
        </Card>
      </Section>

      <Lookup recent={d.recent} />
    </>
  );
}

function decisionColumns(): Column<DecisionRow>[] {
  return [
    { key: "when", header: "Decided", render: (r) => <span className="nowrap" title={fmtDateTime(r.decided_at)}><TimeAgo iso={r.decided_at} /></span>, sort: (r) => r.decided_at },
    { key: "app", header: "Application", render: (r) => <span className="mono xs">{r.application_id}</span>, sort: (r) => r.application_id },
    { key: "decision", header: "Decision", render: (r) => <OutcomePill outcome={r.decision} />, sort: (r) => r.decision },
    { key: "pd", header: "PD", render: (r) => (r.probability_of_default != null ? fmtPct(r.probability_of_default, 1) : "—"), sort: (r) => r.probability_of_default, align: "right" },
    { key: "band", header: "Band", render: (r) => r.risk_band ?? "—", sort: (r) => r.risk_band },
    { key: "reasons", header: "Reasons", render: (r) => <span className="mono xs">{r.reason_codes.join(" ") || "—"}</span> },
    { key: "path", header: "Path", render: (r) => (r.fallback_used ? <Pill tone="warn">fallback</Pill> : PATH_LABEL[r.path] ?? r.path) },
    { key: "model", header: "Model", render: (r) => (r.model_version ? `v${r.model_version}` : "legacy") },
  ];
}

function Lookup({ recent }: { recent: DecisionRow[] }) {
  const [term, setTerm] = useState("");
  const search = useDecisionSearch(term);
  const navigate = useNavigate();
  const open = (r: DecisionRow) => navigate(`/decisions/${encodeURIComponent(r.decision_id)}`);
  const searching = term.trim().length >= 3;
  const rows = searching ? (search.data?.results ?? []) : recent;
  return (
    <Section
      title={searching ? "Search results" : "Newest decisions"}
      right={
        <label className="row small" style={{ gap: 6 }}>
          <span className="muted">Find</span>
          <input
            type="search"
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            placeholder="decision or application id"
            aria-label="Find a decision by decision id or application id"
            style={{ minWidth: 220 }}
          />
        </label>
      }
    >
      <Card flush>
        <DataTable
          rows={rows}
          rowKey={(r) => r.decision_id}
          onRowClick={open}
          initialSort={{ key: "when", dir: "desc" }}
          empty={<EmptyState title={searching ? (search.isLoading ? "Searching…" : "No decision matches") : "No decisions yet"} />}
          columns={decisionColumns()}
        />
      </Card>
      <div className="xs muted" style={{ marginTop: 6 }}>
        Select a row for its reasons, versions and adverse-action content. Applicant inputs are not shown in the console.
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------------------------------- policy
function PolicySection({ policy }: { policy: PolicyInfo | null }) {
  return (
    <Section title="Policy in effect" note="Cut-offs, knock-outs and bands are a separately versioned policy (config/policy.yaml). A change needs its own approvals; it needs no new model.">
      {!policy ? (
        <EmptyState title="No policy is active">
          A person reviews the policy with <span className="mono">lau policy plan</span>, approves it at a terminal with <span className="mono">lau policy approve</span>, and
          activates it with <span className="mono">lau policy apply</span>.
        </EmptyState>
      ) : (
        <div className="grid cols-2">
          <Card title={`${policy.name} (${shortVersion(policy.version)})`}>
            <KeyValue
              items={[
                ["Approve when PD is at most", fmtPct(policy.approve_max_pd, 1)],
                ["Refer to a person up to", fmtPct(policy.refer_max_pd, 1)],
                ["Decline above", fmtPct(policy.refer_max_pd, 1)],
                ["Knock-outs", `debt-to-income above ${fmtPct(policy.knockouts.max_dti, 0)}; bureau score below ${fmtNum(policy.knockouts.min_bureau_score)}`],
                ["Legacy policy (fallback)", `approve at score ${fmtNum(policy.legacy_min_score)} or above`],
                ["Principal reasons per notice", `up to ${policy.reason_codes ?? 4}`],
              ]}
            />
          </Card>
          <Card title="Risk bands and approval">
            <KeyValue
              items={[
                ...policy.bands.map((b): [string, string] => [`Band ${b.band}`, `PD up to ${fmtPct(b.max_pd, 0)}`]),
                ["Active since", policy.activated_at ? `${fmtDateTime(policy.activated_at)} (by ${policy.activated_by ?? "unknown"})` : "—"],
                ["Approved by", policy.approvers.join(", ") || "—"],
              ]}
            />
            <div className="xs muted">
              Synthetic starting values, measured on the validation window. <Link to="/rollouts">Rollouts</Link> shows how a new champion reaches these decisions.
            </div>
          </Card>
        </div>
      )}
    </Section>
  );
}
