# Underwriting Console — design intent (from the approved UI proposal, v2)

This is the product proposal the console implements. Each screen's section says what it must answer. Where it names data that does not exist yet (live decisions, the loan-status feed, rollout stages, notifications), the API returns an `Unavailable` payload and the screen shows a designed empty state that says what is required. Figures quoted here were real on 2026-09-30; always render what the API returns, never these numbers.

Underwriting Console Proposal

Contents

- Summary
 
- The closed loop
 
- Proving it improves
 
- What the data shows today
 
- Everything versioned
 
- Real-time decision API
 
- Loan status feed
 
- 
Console
 
- Who it serves
 
- Design principles
 
- Always-visible context
 
- Screens
 
- Example screens
 
- Cross-cutting features
 
- Roles and permissions
 
- 
Delivery
 
- Architecture
 
- Data contracts
 
- Backend changes
 
- Production readiness
 
- Roadmap
 
- Open questions

Proposal · lending-agentic-underwriting · revision 2
 
Underwriting Console
 
This proposal turns the agentic research system into the live underwriting system: a real-time decision API, a feed of loan outcomes that flows back into learning, a record of how every definition, model and policy changes over time, and a console that shows people whether the system is actually getting better.
 
Revised 2026-09-30Status: proposal for reviewReal figures: workspace dbc-67e8cd43-5f63, catalog lending_uw_dev, synthetic data v2 (6b11c343ed0b)

## Summary
 
Today the system researches and proposes models, and a person promotes one. Three new requirements change its role:

#### Serve decisions in real time
Loan applications arrive through an API and get an approve, decline or refer decision with a probability of default, reason codes, and the exact versions that produced it.

#### Learn from what happens next
The servicing system sends the latest status of every loan. Outcomes mature into labels, monitoring compares predictions with reality, and new evidence starts the next improvement cycle.

#### Track change over time
Definitions of default, models, policy cut-offs, thresholds, data and code are all versioned. Anyone can see what changed between two dates, and every decision records which versions made it.

#### Prove it is improving
Improvement is measured on fixed yardsticks that survive definition changes and population drift, with confidence intervals, guardrails, and a verdict the console shows at the top of the page.

What we found when we measured it. We re-scored every model built so far on the same recent loans. The newest challenger, v11, scores 0.7241 AUC under 60 DPD. An older candidate, v7, scores 0.7268 on the same loans. The harness approved v11 because it beat the current baseline; nothing compared it with the best model already built. So the system can report a successful cycle while the best available model gets slightly worse. The measurement design below closes that gap, and the Progress screen is built to surface exactly this kind of result.

Recommendation. Build in four tracks.

- Evidence first: version stamping, a benchmark ledger that re-scores every model on the newest loans, confidence intervals, and a gate that compares against the best known model.
 
- Decisioning: a decision endpoint on Databricks Model Serving that runs the same feature code as training, the approved champion and a versioned policy, and writes every decision to an append-only log.
 
- Feedback: the loan status feed through Auto Loader and a Lakeflow pipeline, keeping both when a status was true and when we learned it.
 
- The console, as a Databricks App.

About 16 weeks with two engineers, then a production-readiness gate before the API takes real traffic.

## The closed loop
 
The system becomes a loop with three paths. Agents stay on the research path only: they never make, score or change a credit decision.

flowchart LR
 subgraph Decide["Decision path (real time)"]
 LOS["Loan origination system"] -- "application" --> DEC["Decision endpoint"]
 DEC --> F["Feature code, same as training"]
 DEC --> ONL["Online customer features"]
 DEC --> CH["Champion model, active definition"]
 DEC --> POL["Versioned policy: knock-outs, cut-offs, reasons"]
 DEC -. "shadow, no effect" .-> CL["Challengers"]
 DEC --> LOG[("Decision log")]
 end
 subgraph Learn["Feedback path (daily)"]
 SERV["Servicing system"] -- "booking and status" --> ING["Ingestion and quality checks"]
 ING --> PERF[("Loan performance: valid time and system time")]
 PERF --> LAB["Labels, per definition"]
 PERF --> ONL
 end
 subgraph Improve["Research path (cycles)"]
 LAB --> HAR["Harness and benchmark ledger"]
 LOG --> HAR
 HAR <--> AG["Agents propose"]
 HAR --> HUM["Human approval"]
 HUM --> DEP["Staged deploy, rollback"]
 end
 DEP --> DEC

- Decide. An application arrives. The endpoint computes features with the same code used in training, scores it with the approved champion, applies the policy, returns a decision with reasons, scores challengers in shadow, and logs everything.
 
- Book and service. Funded loans are linked to their decision. The servicer reports status, days past due, balances and events every day or month.
 
- Mature. As loans age past the observation window, their labels become final under each definition. Early indicators show up months before that.
 
- Measure. The harness scores predictions against outcomes, re-scores every model on the newest matured loans, and updates the improvement ledger.
 
- Improve. Drift, outcome gaps or newly matured data start a cycle. Agents propose; the harness judges; a person approves.
 
- Deploy. An approved champion goes to shadow, then serves. Rollback to the previous champion is one click and takes effect within minutes.

## Proving the system improves
 
"Is it improving?" is harder to answer than it looks, for five reasons:

- Definitions change. An AUC under 60 DPD cannot be compared with one under 90 DPD.
 
- Populations drift. A model's AUC can fall because applicants got harder to rank, not because the model got worse.
 
- Labels mature slowly. A 12-month definition needs a year of history, so recent decisions only have early indicators.
 
- Outcomes are only observed for approved loans. A model that approves different people is judged on a population chosen by its predecessor.
 
- Testing many ideas inflates results. The best of twenty candidates looks better than it is.

The design uses six instruments. Each fixes one of these problems, and together they decide the verdict the console shows.

 | Instrument | What it measures | Problem it handles

 | Benchmark ledger | Every model ever built (champions, challengers, baselines, the legacy score) re-scored every month on the newest matured loans, under a fixed family of benchmark definitions (30, 60 and 90 DPD ever in 12 months). Benchmark definitions are frozen: new ones can be added, existing ones never edited. | Definition changes; "newest is not best"
 
 | Lift over a frozen reference | The champion's Gini minus the Gini of a model that never changes (the legacy policy score), on the same loans each period. | Population drift: if both fall, the period was harder
 
 | Definition-independent outcomes | Vintage curves (30+, 60+, 90+ days past due by month on book, per origination cohort) and realized loss per $100 originated. | Definition changes; business readability
 
 | Business impact at a fixed policy | Bad rate among approvals at a fixed approval rate, and the approval rate at a fixed target bad rate, for the champion against its predecessor and the legacy score. | Translating AUC into lending terms
 
 | Production performance | For decisions each champion actually made: predicted default rate against realized early indicators, then final outcomes, by vintage and risk band. | The only evidence from real decisions
 
 | Evidence strength | Paired bootstrap confidence intervals on every difference, the number of tests spent, holdout use, and the full denominator of candidates tried, including failures. | Multiple testing and survivorship

### Guardrails
 
A better headline number does not count as improvement if something important got worse. Each of these is tracked over time with its threshold, and any breach blocks an "improved" verdict:

- calibration error and calibration slope
 
- performance on thin-file applicants and on each channel and product
 
- minimum adverse impact ratio across protected groups
 
- score drift (PSI)
 
- reason-code coverage
 
- decision latency and error rate

### The verdict

 | Verdict | Rule

 | Improved | The champion beats the best known model on the benchmark ledger, and the 95% confidence interval of the difference is above zero under the primary benchmark definition. No guardrail breached. Production performance is consistent with validation.
 
 | No detectable change | The interval includes zero. The console says so plainly rather than reporting a noisy gain.
 
 | Not the best available | An older model beats the current champion or challenger on the same loans.
 
 | Regressed | The interval is below zero, or a guardrail is breached.

### Process health
 
The system should also get better at improving. The console tracks, per month:

- cycles run and completed
 
- share of candidates that pass the harness
 
- cost per accepted improvement
 
- time from hypothesis to production
 
- how many lessons were later confirmed or contradicted
 
- how much of the multiple-testing and holdout budget each gain consumed

## What the data shows today
 
Computed from the Databricks lake on 2026-09-30 (synthetic data v2; performance observed to 2026-06). These are the first entries of the benchmark ledger and the over-time views, produced by a one-off script. The proposed monthly job would produce them automatically.

### Benchmark ledger: every model on the same loans
 
Validation window: loans originated August to December 2024 (4,863 loans; 825, 581 and 443 defaults under 30, 60 and 90 DPD). Cells are AUC. The best model in each column is highlighted.

 | Model | Trained under | 30 DPD | 60 DPD | 90 DPD | Bad rate at 70% approval (60 DPD)

 | Legacy policy score (frozen reference) | — | 0.6226 | 0.6242 | 0.6310 | 9.6%
 
 | v2 · logistic regression, 12 bureau/application features | 90 DPD, data v1 | 0.6976 | 0.7265 | 0.7528 | 7.1%
 
 | v5 · LightGBM, 25 features incl. 6 engineered | 90 DPD, data v1 | 0.6841 | 0.7072 | 0.7337 | 7.6%
 
 | v7 · logistic regression, 11 bureau/application features | 60 DPD, data v1 | 0.6975 | 0.7268 | 0.7523 | 7.0%
 
 | Baseline v10 · regularized LR, full catalog | 60 DPD, data v2 | 0.6914 | 0.7182 | 0.7443 | 7.0%
 
 | v11 · LR, 8 features incl. cash flows (newest) | 60 DPD, data v2 | 0.6989 | 0.7241 | 0.7433 | 7.5%

What the ledger shows:

- The newest challenger is not the best model. v11 swapped three of the planted causal bureau features (dti, util_revolving, inq_6m) for cash-flow features. v7 kept them, and it wins under 60 and 90 DPD even though it was trained on an earlier data version. The best model would combine both. This is exactly what the benchmark ledger and a "best known model" gate are for.
 
- Rank order holds across definitions. Models trained under one definition rank loans well under the others, so the ledger can compare them. Calibration does not transfer, so calibration is judged only under each model's own definition.
 
- A bookkeeping bug surfaced. The multiple-testing counter carried tests from the previous data version into the new one, so v11 faced a stricter bar than intended. It still passed. The counter now resets whenever validation labels are rebuilt.
 
- Against the frozen legacy score, every model is far ahead: 0.10 AUC higher under 60 DPD. At the same 70% approval rate, the bad rate among approvals falls from 9.6% to about 7.0%, roughly 27% fewer defaults.

Caveat: these loans were approved by the legacy score, which truncates its range on this population and understates its AUC. The true gap is smaller than shown, and only a controlled approval experiment or production data can measure it (see docs/reject-inference.md).

### Evidence strength

 v11 minus legacy score, AUC difference with 95% bootstrap interval

Intervals: 30 DPD +0.050 to +0.097 · 60 DPD +0.075 to +0.125 · 90 DPD +0.084 to +0.140 (400 paired resamples). All exclude zero, so "better than the legacy score" is well supported. The difference between v11 and v7 (−0.003 under 60 DPD) is well inside noise; the verdict for that comparison is "not the best available", not "regressed".

### Default rate over time under each definition
 
Portfolio default rate by origination quarter, for eligible loans with 12 months observed. Definitions move the level; the trend is shared. The 2025 jump is the drift planted in the synthetic data (channel mix, income, and a macro shock), and it shows up under every definition.

30 DPD (last: 23.6%)60 DPD, active (last: 17.9%)90 DPD (last: 14.1%)2,194 to 3,197 eligible loans per quarter

### Vintage curves: an outcome view that needs no definition
 
Share of each origination cohort that has reached 30+ days past due by each month on book. The 2025 H1 cohort separates from earlier cohorts by month 4 (9.0% against about 7.0%) and ends at 21.9% by month 12 against 15.6% to 16.6%. This early separation is what monitoring should catch months before the 12-month labels mature.

2023 H1 (4,759 loans, 16.6% at month 12)2024 H1 (5,588 loans, 15.7%)2025 H1 (6,502 loans, 21.9%)

## Everything versioned
 
To answer "what changed?" for any period, every input that can change the system's behaviour gets a version, and every decision, metric and model records the full set (its version vector).

 | Component | Version key | Changed by | Status today

 | Definition of default | content hash (definition_version) | Human, plan and apply with approval | exists
 
 | Raw data and performance snapshot | data_version, plus a performance cutoff in system time | Ingestion | partial data version only
 
 | Model | registry version and alias | Promotion with approval | exists
 
 | Policy: knock-outs, cut-offs, bands, reason statements | content hash (policy_version) | Policy owner with approval | new
 
 | Harness thresholds and budgets | content hash of config | Admin with approval | partial fingerprinted, not stamped
 
 | Benchmark definitions | frozen list, append-only | Model risk | new
 
 | Agent prompts and models | hash per role | Engineer with review | new
 
 | Access grants | hash of the grants specification | Admin | new
 
 | Code | git commit | Deployment | new

The console's Compare two dates view diffs the version vectors. For example, "between 1 September and 1 October: definition 90 → 60 DPD, policy cut-off 12% → 10% PD, champion v5 → v11, curator prompt revised, thresholds unchanged". Each line links to the approval that made the change.
 
Labels gain a second tag. The same definition gives different labels as new performance arrives, so a label set is identified by definition version plus performance cutoff, and any evaluation can be reproduced exactly.

## Real-time decision API

### Decision flow

sequenceDiagram
 autonumber
 participant L as Loan origination system
 participant E as Decision endpoint
 participant O as Online customer features
 participant M as Champion model
 participant P as Policy
 participant G as Decision log
 L->>E: application, bureau data, consented bank transactions
 E->>E: validate, idempotency check on request id
 E->>O: existing-customer features (loans with us, current status)
 E->>E: compute features with the training code
 E->>P: knock-out rules (licensing, identity, fraud flags)
 E->>M: probability of default
 E->>P: cut-off, risk band, refer band, reason statements
 E-->>L: decision, PD, band, reasons, versions, decision id
 E->>G: full record, inputs hash, features, versions, latency
 E->>E: shadow-score challengers after responding

### Interface

 | Call | Purpose | Served by

 | POST …/serving-endpoints/lau-decision/invocations | Make a decision (idempotent on request_id) | Model Serving endpoint (custom model)
 
 | GET /api/decisions/{decision_id} | Full decision record for audit and disputes | Console API
 
 | GET /api/decisions/{decision_id}/adverse-action | Principal reasons formatted for the adverse-action notice | Console API
 
 | GET /api/serving | Serving champion, definition, policy and code versions; health | Console API
 
 | Booking and status files, or events | Link decision to loan, then report status | Loan status feed (next section)

Example response (illustrative values):

{
 "decision_id": "dec_2026_10_01_000184",
 "request_id": "los-7c21a9",
 "decision": "decline",
 "probability_of_default": 0.214,
 "risk_band": "E",
 "reasons": [
 {"code": "R07", "statement": "Monthly payment is high relative to income", "feature": "pmt_to_income"},
 {"code": "R12", "statement": "Low average account balance", "feature": "cf_avg_balance_6m"},
 {"code": "R03", "statement": "Credit score below our minimum for this amount", "feature": "bureau_score"},
 {"code": "R15", "statement": "Recent returned payments on your account", "feature": "cf_nsf_count_6m"}
 ],
 "versions": {
 "model": "lending_uw_dev.production.pd_model/4",
 "definition": "57d48e7ce373",
 "policy": "pol_9f31c2a0",
 "features": "lau 0.3.0 (git 5a7ec05)"
 },
 "fallback_used": false,
 "latency_ms": 84
}

### Design decisions

- Model and policy are separate and separately versioned. A cut-off change is a policy change: it needs approval, but it does not need a new model or revalidation. A model change keeps the policy unless someone changes it.
 
- One feature implementation. The endpoint runs the same Python feature code as training, including cash-flow aggregation from submitted transactions. A parity test computes features both ways on the same inputs and fails the release if they differ.
 
- Customer history from an online store. Features about applicants' existing loans with us (current status, worst delinquency, months since last delinquency) come from a Lakebase-backed online feature store, updated by the loan status feed. Training uses point-in-time lookups, so a feature never includes information from after the decision.
 
- Every decision is logged, immutably. Inputs (encrypted, with a masked analytic copy), features, PD, decision, reasons, the version vector, latency and fallback use go to an append-only production.decisions table. Model Serving inference tables also capture raw requests and responses in Unity Catalog. This log feeds adverse-action notices, audits, monitoring on real traffic, fairness monitoring on actual decisions, and reject-inference data.
 
- Shadow first, then serve. A newly approved champion first runs in shadow on live traffic for a set period. Serving switches only after the shadow report is reviewed. Randomized traffic splits between models are not used without compliance approval, because they treat similar applicants differently.
 
- Safe failure. If the model is unavailable or exceeds its time limit, the endpoint falls back to the legacy policy path or refers the application to a person, per policy, and logs that it did. One click rolls back to the previous champion.
 
- Agents are not in this path. Decisions come from the approved model and approved policy only. No LLM call happens during a decision.
 
- Latency target to be set with the origination team. Proposed: 95th percentile under 300 ms, 99th under 800 ms, confirmed by load tests before launch.

## Loan status feed
 
The servicing system reports what happens to every funded loan. This replaces the synthetic raw.performance table with the real one and makes the loop continuous.

 | Record | Fields | Frequency

 | Booking | decision_id, loan_id, funded date and amount, rate, term, product | At funding
 
 | Status | loan_id, as_of_date (valid time), status, days past due, balance, past-due amount, payment, charge-off, bankruptcy, settlement, forbearance, payoff, fraud and deceased flags, reported_at (system time) | Daily or monthly
 
 | Corrections | Same fields, with a later reported_at for an earlier as_of_date | As they happen

- Ingestion. Files land in a Unity Catalog volume, or events arrive on a stream. Auto Loader picks them up, and a Lakeflow pipeline validates them and applies changes with AUTO CDC. AUTO CDC's bitemporal mode (generally available since May 2026) keeps both when a status was true and when we learned it. Its configuration parameters aren't yet named in the docs, so this needs a spike.
 
- Why both timelines. Servicers restate history. With both timelines the harness can rebuild labels "as known on" any date, so backtests never use hindsight and the console's time travel shows what people actually knew then.
 
- Quality checks as pipeline expectations:

- every loan is known and linked to a decision
 
- days past due rises by at most one bucket per month unless the loan cured
 
- closed loans stay closed
 
- balances are never negative
 
- one record per loan per date per report
 
- the feed arrives on schedule
 
 Failures quarantine records and raise an alert. They are never silently dropped.
 
- Maturation. Each month the pipeline reports how many loans crossed each definition's observation window and became final labels. Newly matured loans trigger the benchmark ledger re-score and, when enough accumulate, a retraining cycle.
 
- Early indicators. Vintage curves and 30+ days past due by month 3 and month 6 update daily, so deterioration is visible long before 12-month labels exist (see the 2025 H1 cohort above).
 
- Online features. The latest status per customer updates the online store used by the decision endpoint.

## Who it serves

 | Person | Needs to know | Needs to do | Lands on

 | Head of credit risk | Whether the system is improving; which model and policy decide; expected loss impact | Approve promotions, policy and definition changes | Overview, Progress, Approvals
 
 | Model risk / validation | Full evidence for any model; how it performs in production against validation | Review evidence, record validation findings, block a promotion | Progress, Models, Performance, History
 
 | Compliance / fair lending | Adverse impact on actual decisions, proxies, reason statements, notice timeliness | Record findings, require remediation, export an audit pack | Fairness & compliance, Decisions
 
 | Policy owner | Approval rates, bad rates and volumes by band and channel | Propose cut-off and knock-out changes | Decisions, Progress
 
 | Data scientist / ML engineer | What agents tried, why candidates failed, feature performance, benchmark results | Start or stop cycles, investigate traces | Live activity, Features, Agents
 
 | Operations / on-call | API health, feed freshness, pipeline failures, spend | Roll back a champion, pause jobs, acknowledge alerts | Decisions, Loan status feed, Alerts
 
 | Customer operations | Why a specific applicant was declined | Look up a decision and its reasons | Decision lookup
 
 | Executive / auditor (read-only) | A plain-language status and history | Read, export | Overview, Progress, History

## Design principles

- Answer "is it improving?" honestly. The console's verdict follows the rules above. It shows uncertainty, shows the denominator of everything tried, and reports "not the best available" or "no detectable change" as readily as "improved".
 
- The definition of default is always on screen. Every metric carries its definition version. Models from different definitions share an axis only in the benchmark ledger, where every model is re-scored under the same benchmark definitions, and in the labelled Compare Definitions view.
 
- Everything has a history. Every screen can be viewed as of a past date, and every changeable component shows its version history.
 
- The console reads the system of record. Everything comes from the Delta tables and the model registry; each number links to its source.
 
- Read by default, act with intent. Actions (approve, reject, promote, roll back, stop, change policy) require a named person, a rationale and a confirmation that states exactly what changes.
 
- Agents and measurements look different. Agent output is marked as proposed. Harness and production measurements are marked as measured.
 
- Nothing sensitive leaks. No holdout labels, no row-level protected attributes, no credentials. Applicant-level views are masked and role-restricted in production.

## Always-visible context

 | Element | Shows | Behaviour

 | Improvement verdict | Improved / no detectable change / not the best available / regressed | Opens Progress
 
 | Serving | Champion model, its definition, the policy version | Amber when superseded by a definition change or when rollout is in progress
 
 | Active definition | 57d48e7c · 60 DPD ever / 12 months | Amber when the repository YAML differs from the active version
 
 | Decision API | Healthy, degraded or failing; 99th-percentile latency; fallback rate | Opens Decisions
 
 | Loan feed | Age of the latest status file; quality failures | Opens Loan status feed
 
 | System activity | Idle, cycle running, pipeline rebuilding | Opens Live activity
 
 | Budget, decisions waiting, alerts | Monthly spend against the hard stop; approvals pending; unacknowledged alerts | Open their screens
 
 | Environment and as-of date | dev or prod, synthetic or real data; the date being viewed | Prod has a distinct header colour; the as-of control enables time travel

## Screens
 
Twenty screens, grouped by the question they answer. Reads: lines name the tables behind each screen; new tables are listed under Data contracts.

### Now

#### 1. Overview

- Status sentence generated from state: what is active, what serves, the improvement verdict, what needs a person.
 
- Tiles: decisions today and approval rate, default rate under the active definition, serving model lift over the legacy score, best challenger against the best known model, score drift, feed freshness, month-to-date spend.
 
- Decisions waiting on people, with age.
 
- Last ten events from History; pipeline freshness for the active definition.

#### 2. Live activity (research)

- Agent swim lanes with turns and dollars against caps; streaming tool-call feed marked proposed or measured.
 
- Budget gauges (tests, dollars, minutes, critique rounds); critique-loop view; pipeline rebuild lighting up stage by stage.
 
- Stop cycle, with a reason recorded in the trace.

Reads: ops.agent_trace (streamed), ops.cycles heartbeat, ops.pipeline_state

#### 3. Decisions (live API)

- Live counters: volume, approve / decline / refer rates, by channel, product and risk band; comparison with the same hour last week.
 
- Service health: latency percentiles, errors, time-outs, fallback use, knock-out rates.
 
- Decision lookup by decision, application or loan id: inputs (masked by role), features, PD, policy path, reasons, version vector, and the loan's later performance.
 
- Reason-code distribution for declines and adverse-action notice status.
 
- Policy in effect, with a link to its version history.

Reads: production.decisions, inference tables, ops.policy_versions

### Over time

#### 4. Progress: is it improving?

- Verdict banner with its evidence, generated by the rules in Proving it improves.
 
- Champion lineage: lift over the frozen reference (Gini points) by month, with a confidence band, markers for promotions and rollbacks, and shaded bands for definition eras.
 
- Benchmark ledger matrix: every model against every benchmark definition on the newest matured loans, best in each column highlighted, filterable by window.
 
- Business impact at a fixed policy: bad rate at a fixed approval rate and approvals at a fixed bad rate, for champion, predecessor and legacy score.
 
- Production performance: predicted against realized early indicators and final defaults for the loans each champion approved, by vintage and band.
 
- Guardrails as small multiples over time (calibration, thin-file, adverse impact, drift, reason coverage, latency) with thresholds.
 
- Process health: cycles, pass rate, cost per accepted improvement, time to production, tests and holdout spent.
 
- The denominator: every candidate tried in the period, including failures.

Reads: ops.benchmark_results, ops.improvement_ledger, production.decisions joined to loan performance, ops.evaluations

#### 5. History and change log

- Unified timeline banded by definition era: definition, policy, config and prompt changes; data loads and feed incidents; builds; cycles; evaluations; gate runs; approvals; promotions; rollbacks; alerts.
 
- Compare two dates: the version-vector diff with links to approvals.
 
- Cycle replay and cycle comparison; model lineage from data to decision.

Reads: ops.events (new view over all ops tables), ops.config_versions

#### 6. Definitions over time

- Active definition in plain language, version history with diffs and approvers, and the period each version was active.
 
- Definition sensitivity: portfolio default rate by origination period under every benchmark definition (the chart in What the data shows today).
 
- Label maturation and restatement: how each cohort's default rate evolves as loans age and as the servicer restates history.
 
- Plan preview and compare definitions (as in the CLI); changes proposed as pull requests and approved here.

Reads: ops.definition_versions, ops.active_definition, ops.label_stats, labels by performance cutoff

### Next

#### 7. Upcoming

- Schedules: jobs, next runs, paused state. The cycle queue and why each cycle was requested (definition change, alert, maturation, manual).
 
- Next plan preview and the hypothesis backlog.
 
- Maturation forecast: when enough newly matured loans will exist for the next benchmark re-score and retrain.
 
- Rollouts in progress and their next step; decisions waiting on people.
 
- Forecasts: month-end spend, holdout and multiple-testing headroom.

### Models and evidence

#### 8. Models

- Registry by definition with status (serving, shadow, champion, challenger, retired, superseded); model cards with features, engineered SQL, training window, evidence, approvals; diff two models; documentation pack.

#### 9. Performance

- Discrimination, calibration, lift, stability by time slice and segment, drift, with confidence intervals.
 
- Validation against production: the same metrics on real decisions once outcomes mature, side by side.
 
- Multiple-testing ledger and holdout budget per definition.

#### 10. Fairness & compliance

- Adverse impact by group on validation and on actual decisions (with estimated group membership in production, subject to counsel), trend over time.
 
- Proxy scan heatmap (pooled and per group), prohibited-feature register, input lineage.
 
- Reason-statement library and coverage; adverse-action notice timeliness; compliance findings and remediation; audit export.

### Data and feedback

#### 11. Loan status feed

- Freshness and volume by file; quality check results with quarantined records; restatements by period.
 
- Status transitions (current → 30 → 60 …, cures, charge-offs, payoffs) this period against last.
 
- Maturation: loans that became final labels under each definition this month.
 
- Vintage curves updating daily, with early-warning highlights.
 
- Unlinked loans (no matching decision) and decisions with no booking after the expected period.

Reads: pipeline event log, raw.loan_status_events, raw.performance (bitemporal), quarantine tables

#### 12. Data catalog and cash flows

- Variables with statistics, drift, leakage and proxy risk, lineage; leakage watchlist; cash-flow explorer for cohorts; ground truth panel in dev only.
 
- Training-serving parity: feature distributions in training against live decisions, per feature.

#### 13. Features lab

- Engineered features with SQL, rationale, author, per-definition screens, usage in models; reject a feature or pin a hypothesis.

### Agents

#### 14. Agents

- Roster with model, caps and prompt version history; tool and data permission matrix; effectiveness over time; reports library; lessons filtered by definition.

### Decide and operate

#### 15. Approvals

- Inbox: promotions, definition changes, policy changes, rollouts, config changes.
 
- Evidence packet: harness checks, benchmark position against the best known model, gate result, shadow report, red-team and compliance reports, fairness, cost.
 
- Approve or reject with rationale; the confirmation states exactly what changes; two-person rule.

#### 16. Rollouts and rollback

- Stages for each approved change: shadow, serving; entry and exit criteria; who approved each step.
 
- Roll back to the previous champion or policy, with a reason; takes effect within minutes and is logged.

#### 17. Shadow scoring

- Serving against shadow models on live traffic: score distributions, decision agreement, swap sets and their later outcomes.

#### 18. Alerts and service levels

- Model alerts (drift, outcome gaps), service alerts (latency, errors, fallback), feed alerts (late, failed checks), budget alerts; acknowledge, assign, link to triggered cycles; notification routing.

#### 19. Cost

- Spend by day, activity, cycle and agent; serving cost per 1,000 decisions; billing actuals and estimates; caps, burn-down and forecast; cost per accepted improvement.

#### 20. Reports and settings

- Cycle, demo, comparison, monthly improvement and model documentation reports; exports.
 
- Budgets, thresholds, benchmark definitions and routing (each change approved and versioned); access verification results.

## Example screens
 
Four screens. The first two use the real figures above; the others use figures from the demo cycles. Layout and priorities only, not final visual design.

 Progress
 Primary benchmark 60 DPD / 12m
 Window Aug–Dec 2024 · 4,863 loans
 
 Not the best available

Newest challenger v11 is not the best known model. On the same loans, v7 scores 0.7268 against v11's 0.7241 (60 DPD); the gap is within noise. Every model beats the frozen legacy score by about 0.10 AUC (95% interval +0.075 to +0.125). Nothing has been promoted yet, so there is no production evidence.

 Benchmark ledger · AUC on the same loans

 | Model | 30 | 60 | 90 | Bad @70%

 | Legacy score | 0.623 | 0.624 | 0.631 | 9.6%
 
 | v2 | 0.698 | 0.727 | 0.753 | 7.1%
 
 | v7 | 0.698 | 0.727 | 0.752 | 7.0%
 
 | Baseline v10 | 0.691 | 0.718 | 0.744 | 7.0%
 
 | v11 (newest) | 0.699 | 0.724 | 0.743 | 7.5%

Rounded; exact values in What the data shows today. v5 omitted for space.

 Guardrails · v11

Calibration error 0.012ok
 
Min adverse impact ratiook
 
Leakage, proxies, prohibitednone
 
Thin-file performancewatch
 
Production evidencenone yet
 
 Denominator this definition
 
3 validation tests recorded for 60 DPD, 1 of them on the v2 data · holdout 0 of 5 used · last cycle $0.46
 
v11 was held to the 3-test bar (margin 0.0055) because the counter did not reset when the data changed. Fixed while writing this proposal: the budget now resets whenever validation labels are rebuilt.

Progress. The verdict, ledger and denominator come from the benchmark computation above and the synthetic v2 cycle. The recommended next step, generated by the rules: combine v7's bureau features with v11's cash-flow features and evaluate against the best known model.

 Underwriting Console
 Not the best available
 Serving: legacy policy
 Active 57d48e7c 60 DPD / 12m
 
 API not yet live
 $4.64 of $100
 1 decision waiting
 dev · synthetic

60 DPD is active and the legacy policy still decides. Challenger v11 passed its checks, but v7, built earlier, scores higher on the same loans. Review both before promoting.

Default rate
13.4%
60 DPD, 26,817 eligible loans

Best known model
0.727
v7 · 60 DPD benchmark

Newest challenger
0.724
v11 · −0.003 vs best

Lift over legacy
+0.10
AUC, 95% CI +0.075 to +0.125

Latest cohort
21.9%
2025 H1, 30+ DPD by month 12

 Waiting on people

Promote challenger v112 h ago
 
10/10 checks Not best known Red team: concern
 
Holdout gate not yet runEvidence Compare with v7

 Pipeline · 60 DPD · data v2

curate

37.1 s
 
labels

19.2 s
 
catalog

23.4 s
 
baselines

54.1 s
 
monitoring

21.1 s

Overview, before the API is live. Tiles use the real figures above and the synthetic v2 rebuild. Once decisions flow, tiles for volume, approval rate and API health join the top row.

 Live activity
 Cycle cy-202609301513-3bec
 Running · 6 of 7 agents done
 
 $0.49 of $10
 2 of 20 tests
 9.6 of 60 min
 Stop cycle

 Agents

planner

$0.09
 
profiler

$0.07
 
feature

$0.10
 
modeling

$0.12
 
red team

$0.05
 
compliance

$0.04
 
curator

$0.02

finishedrunning

 Tool calls

15:21:40curatorread_cycle_artifacts · 5 reports
 
15:20:58compliancewrite_finding · verdict pass · v7
 
15:20:31complianceget_fairness_report · min AIR 0.989 measured
 
15:19:47redteamwrite_report · verdict concern proposed
 
15:19:02redteamprobe_segment thin_file=true · AUC 0.600
 
15:17:40modelingevaluate_candidate v9 · failed 1 check
 
15:16:12modelingevaluate_candidate v7 · AUC 0.6944 10/10
 
15:15:05modelingtrain_candidate logreg · 11 features

Live activity. Agent costs, the evaluations of v7 and v9 (validation AUC under 60 DPD on data v1), and the verdicts come from the demo cycle; timestamps and lane widths are illustrative.

 Performance
 Definition 9a8e4e56 90 DPD / 12m
 
 Validation · 4,828 loans · 8.9% default rate

 Multiple-testing ledger

candidate validation AUCrequired bar (reference + margin)

 Challenger v5 · checks

Improves on the 90 DPD baselinepass
 
Calibration error 0.007pass
 
Time slices 0.661 to 0.727pass
 
Score PSI 0.003pass
 
Min adverse impact ratio 0.965pass
 
Beats best known modelnew check

The proposed gate adds the last check: a candidate must also beat the best model already built, re-scored on the same loans.

Performance. The ledger plots every evaluation under the 90 DPD definition on data v1, with values from ops.evaluations.

## Cross-cutting features

#### Time travel
View any screen as of a past date, including labels as they were known then (bitemporal data), the model that served, and the policy in force.

#### Compare two dates
A version-vector diff across definitions, models, policy, thresholds, prompts, data and code, with the approvals behind each change.

#### Ask the system
Questions in plain language ("Why did applications from the broker channel get declined more this week?"). A read-only Claude agent answers from the console's tables, cites rows, and cannot act.

#### Monthly improvement report
Generated each month from the ledger: verdict, benchmark position, business impact, production performance, guardrails, spend. Suitable for a risk committee.

#### Explain this
Every metric and term has a short explanation and a link to how it is computed.

#### Evidence links
Every number links to its source: an evaluation, a decision record, a trace entry, a table row, a model run.

#### What-if planner
Draft a definition, policy or budget change and see its plan before anyone opens a pull request: affected stages, label impact, approval and bad-rate impact at the proposed cut-off, cost.

#### Notifications
Email and Slack for decisions waiting, verdict changes, service-level breaches, feed failures, budget thresholds and alerts, routed by role.

#### Mobile summary
Phone layouts for Overview, Progress, Approvals (evidence readable; approval after re-authentication, if allowed) and Alerts.

#### Accessibility
Keyboard navigation, data tables behind every chart, status shown with text and icon as well as colour, light and dark themes.

## Roles and permissions

 | Capability | Viewer | Engineer | Model risk | Compliance | Policy owner | On-call | Approver | Admin

 | Read aggregate screens | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓
 
 | Look up an individual decision (masked by role) | | | ✓ | ✓ | | ✓ | ✓ | 
 
 | See trace detail (redacted) | | ✓ | ✓ | ✓ | | ✓ | ✓ | ✓
 
 | Start or stop a cycle | | ✓ | | | | | | ✓
 
 | Run the holdout gate | | | ✓ | | | | ✓ | 
 
 | Record validation or compliance findings | | | ✓ | ✓ | | | | 
 
 | Propose a policy change | | | | | ✓ | | | 
 
 | Approve promotion, definition or policy change | | | | | | | ✓ | 
 
 | Roll back champion or policy | | | | | | ✓ | ✓ | 
 
 | Change budgets, thresholds, benchmarks (itself approved) | | | | | | | | ✓

Two-person rule: nobody approves work they started. Rollback is deliberately available to on-call without approval, because reverting to the previously approved state is always safe to do fast; it is recorded and reviewed afterwards.

## Architecture

 | Part | Databricks service | Notes

 | Decision endpoint | Model Serving, custom model (MLflow pyfunc wrapping features, champion and policy) | Serverless scaling; AI Gateway inference tables log requests and responses to Unity Catalog
 
 | Customer features online | Online Feature Store (Lakebase) | Low-latency lookups, consistent with offline feature tables
 
 | Loan status ingestion | Auto Loader and a Lakeflow pipeline with expectations and AUTO CDC (bitemporal) | Quarantine on failed checks
 
 | Harness, benchmark ledger, pipeline | Existing jobs on serverless compute | New monthly ledger job
 
 | Research agents | Existing orchestrator (Claude Agent SDK) | Unchanged; never in the decision path
 
 | Console | Databricks App (React and FastAPI) | Workspace SSO; actions run with the signed-in person's identity through the app's user authorization

- New identities. lau-decision for the endpoint (reads the champion, policy and online features; writes only the decision log) and lau-ui for the console (read-only, no holdout, no raw applicant data). Both join the live isolation tests.
 
- Live updates in the console: server-sent events from the console API, polling the trace and decision tables only while there is activity, so the warehouse can still stop when idle.

Service capabilities checked against current Databricks documentation: custom model serving, AI Gateway inference tables, Online Feature Stores, AUTO CDC and its bitemporal release, Auto Loader, Databricks Apps authorization.

## Data contracts

 | New table or view | Grain | Purpose

 | production.decisions | decision | Append-only record: masked inputs, features, PD, decision, reasons, version vector, latency, fallback
 
 | production.bookings | loan | Links decision to funded loan
 
 | raw.loan_status_events | report | As received from the servicer (bronze), with quarantine for failed checks
 
 | raw.performance (changed) | loan × month × report | Bitemporal: valid time and system time
 
 | ops.policy_versions | policy version | Content-hashed policy with approvals
 
 | ops.config_versions | component version | Thresholds, budgets, benchmarks, prompts, grants, code commit
 
 | ops.benchmark_results | model × window × benchmark definition × metric | The benchmark ledger, with confidence intervals
 
 | ops.improvement_ledger | month | Verdict, evidence, guardrails, process health
 
 | ops.rollouts | rollout step | Shadow and serving stages, approvals, rollbacks
 
 | ops.events (view) | event | Unified history for the timeline
 
 | Metric and findings tables | evaluation × metric; finding | Flattened metrics for charts; human validation and compliance findings

## Backend changes

#### Evidence

- Stamp the version vector on every evaluation, cycle and (later) decision; version policy, config, prompts, grants and code.
 
- Monthly benchmark ledger job: re-score every registered model and the frozen reference on the newest matured window under every benchmark definition, with paired bootstrap intervals.
 
- Harness gate: add "beats the best known model on the same loans" and report intervals for every comparison.
 
- Feed the ledger to the planner and curator, so agents build on the best model rather than the latest baseline.

#### Decisioning

- Decision model (pyfunc) that wraps shared feature code, the champion and a versioned policy; reason-statement mapping approved by compliance.
 
- Feature parity tests between the SQL path used in training and the Python path used in serving.
 
- Promotion deploys to the endpoint in shadow, then serving; one-step rollback; fallback path.
 
- Decision log writer, the lau-decision identity, load tests.

#### Feedback

- Booking and status ingestion with expectations and quarantine; bitemporal performance; labels identified by definition and performance cutoff.
 
- Maturation tracking and triggers; online customer features; production performance joins.

#### Console support

- Per-call trace flush, cycle heartbeat and stop request; events view; flattened metrics; findings tables; the lau-ui identity; API wrappers for actions.

## Production readiness
 
Before the API decides on real applications, each of these must be done and signed off:

- Parallel run: the new champion runs in shadow beside the legacy policy on live traffic for an agreed period, with a reviewed comparison.
 
- Independent model validation of the champion, the policy and the benchmark method.
 
- Compliance sign-off: reason statements, adverse-action notice process and timing, fair-lending monitoring on actual decisions, the method for estimating protected-group membership.
 
- Records: retention for applications and decisions. Reg B requires at least 25 months after notifying the applicant; counsel to confirm scope.
 
- Security review of the endpoint, identities, encryption and masking; real-data masking switched on.
 
- Load test at peak volume plus margin; latency targets met.
 
- Rollback and failure drills: endpoint down, feed late, bad model promoted.
 
- Runbook and on-call rota; alert routing tested.

## Roadmap

Weeks 1–4
Evidence
Version vector stamping; benchmark ledger job with intervals; "best known model" gate; ledger fed to agents. Console release 1 (read-only): Overview, Progress, History and change log, Definitions over time, Models, Performance, Cost.

Weeks 3–10
Decisioning
Decision model and endpoint, feature parity tests, decision log, fallback, shadow challengers, promotion to shadow and serving, rollback, load tests. Console: Decisions, Rollouts, decision lookup.

Weeks 7–12
Feedback
Booking and status ingestion with expectations and quarantine, bitemporal performance, labels by cutoff, maturation triggers, online customer features, production performance. Console: Loan status feed; production evidence on Progress.

Weeks 11–16
Console
Approvals inbox with evidence packets and two-person rule, Live activity streaming, Fairness on actual decisions, Alerts and service levels, time travel, compare two dates, ask the system, what-if planner, monthly improvement report, mobile layouts.

Then
Readiness
Parallel run, validation, compliance and security sign-off, drills. Then the API takes real traffic.

Assumes two engineers (platform and full-stack) with part-time design, model risk and compliance input. The evidence track goes first because it changes how every later result is judged.

## Open questions

- Decision scope. Which decisions are fully automated and which bands are referred to a person? Is pricing in scope, or only approve or decline?
 
- Integration. Which origination system calls the API; who pulls the bureau report; how consented bank transactions arrive (aggregator, file, in the request).
 
- Volume and latency. Peak applications per minute and the latency the origination flow can accept.
 
- Servicer feed. Format, frequency (daily or monthly), how corrections arrive, and who owns the booking link from decision to loan.
 
- Benchmarks. Confirm 30, 60 and 90 DPD ever in 12 months as the frozen benchmark definitions, and the legacy score as the frozen reference.
 
- Rollout. Minimum shadow period, and whether any staged traffic split is acceptable to compliance.
 
- Approvals. Named approvers for models, policy and definitions; whether the two-person rule applies from day one; whether approvals from a phone are allowed.
 
- Adverse action. Which system generates and sends notices; the approved list of reason statements.
 
- Retention and privacy. Retention periods, and which roles may see applicant-level data in the console.
 
- Ask the system. Whether a Claude-powered read-only Q&A agent may run in production.

