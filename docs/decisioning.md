# Real-time decisioning

How an application becomes approve, refer or decline, how every decision is recorded, and how a new champion reaches
decisions (shadow first) and leaves them (rollback). No LLM is involved in a decision: agents propose models, the
harness judges them, people approve them, and only approved artifacts decide.

> Synthetic system. Nothing here is a compliant credit decisioning process by itself: the reason statements, the
> notice text and timing, and fair-lending monitoring need counsel's and compliance's sign-off before real use.

## What decides

One MLflow model, **`<catalog>.<production>.decision_model`** (alias `live`), holds everything a decision needs:

| Part | Source | Changes when |
|---|---|---|
| Serving champion | `production.pd_model@champion` (or none: the legacy policy decides) | a rollout is served or rolled back |
| Shadow champion | the rollout in state `shadow`, if any | a champion is promoted, served or superseded |
| Credit policy | the **active** version of `config/policy.yaml` (`ops.active_policy`) | a person approves and applies a policy |
| Reason statements | `config/reason_statements.yaml` | a rebuild after the file changes |
| Cash-flow aggregation | the curate stage's own SQL (`cashflow.monthly_sql`, run on DuckDB) and `summarize_monthly` | code changes |

Nothing is read from config or tables at request time, so a served version always decides the same way. The build
records a version vector (model, definition, policy, shadow, code) and a build id; every decision carries it.

`lau decision build` assembles it from approved state only, logs it in its own experiment
(`/Shared/lau/decision_models`: harness and promoter only, no agent access) and registers it as the promoter. Builds
happen automatically after `lau policy apply`, promotions, `lau rollout serve` and `lau rollout rollback`.

## One decision

Request (one row per application; all strings):

| Field | |
|---|---|
| `request_id` | the caller's idempotency key |
| `application_json` | the application as submitted. Submitted `cf_*` features are dropped: they are always recomputed |
| `transactions_json` | bank-statement lines `[{txn_date, amount, balance_after, category}]` |
| `decision_date` | the date decided for (default today); only lines strictly before it count, as in training |

Steps (`lau.decision.engine`):

1. **Knock-outs** (policy): debt-to-income above `max_dti`, or a bureau score below `min_bureau_score` when a score
   exists, decline before any model is consulted, with the matching reason.
2. **Cash-flow features** from the statement lines, by the training code itself.
3. **Probability of default** from the serving champion within `timeout_ms` (config/decisioning.yaml). On an error or
   time-out the legacy policy decides and the decision says so (`fallback_used`, `fallback_reason`).
4. **Decision and band**: approve at PD ≤ `approve_max_pd`, refer to a person up to `refer_max_pd`, decline above.
5. **Principal reasons** for refer and decline: the model inputs that pushed this applicant's PD up most, mapped to
   statements, up to four, never the same statement twice. An input without a mapping gets R99 and is counted; a
   refer or decline without reasons is flagged (`reasons_missing`) and counted on the console.
6. **Shadow score** by the shadow champion, recorded next to the decision; it never changes the decision.

`decision_id` is a hash of the request id, the payload, the model and the policy: a retried request returns the same
id, and the log keeps each decision once.

## Where decisions are recorded

| Table | Written by | Holds |
|---|---|---|
| `ops.decisions` | harness (append-only Delta table) | outcome, PD, band, reason codes and statements, version vector, shadow score, fallback, latency, source, `is_test` |
| `curated.decision_inputs` | harness | the application as submitted and the cash-flow features as served (applicant-level: agents and the console cannot read `curated`) |
| `ops.lau_decision_payload` | Model Serving (AI Gateway inference table) | raw requests and responses, once the endpoint exists; never copied into the console snapshot |
| `ops.decision_builds` | harness | every build: version, build id, version vector, who built it |
| `ops.release_checks` | harness | parity, load and rollback checks with their details |
| `production.rollouts`, `ops.rollout_approvals` | promoter / harness | rollout events and who approved serving |
| `ops.policy_versions`, `ops.policy_approvals`, `ops.active_policy` | harness | every policy version, its approvals, activation history |

Callers log what they receive (`lau.decision.log.record`); `lau decision reconcile` adds decisions the endpoint made for
anyone else from its inference table. Requests from release checks (`lt-`, `parity-`) are logged as tests and left out of
every figure.

## Synthetic traffic

`lau decision originate` (and the `decisions` task of the daily job) sends one simulated month of applications per run.
The simulated clock (`ops.sim_clock`) starts the month after the data's as-of month. Applications come from the same
generator as the training data, seeded by the month, so a retried run sends identical requests; the applicants' latent
risk, protected attributes and surname go to `simulation.truth` (harness only) for the servicer simulator and the
fairness checks, and never into a request. The transport is the endpoint when it
exists and otherwise the live decision model in process: the same registered artifact.

## Shadow-first rollouts

1. A promotion makes a champion (as before) and, for the active definition, starts a **rollout in shadow**. The decision
   model is rebuilt so the new champion scores every live decision; it decides nothing.
2. The **shadow report** compares the serving decisions with what the champion would have decided on the same
   applications since the rollout started: agreement, outcome shares, flips in both directions, mean PD.
3. People record decisions (`lau rollout decide`, or the console): serving needs `approvals.rollout` different
   approvers and at least `rollout.min_shadow_decisions` shadow decisions; one rejection blocks it.
4. **Serve** moves the serving alias (promoter identity), rebuilds the decision model and updates the endpoint.
5. **Rollback** returns serving to the model that served before (or the legacy policy) in one action, by one person,
   with a reason. A newer promotion supersedes a rollout still in shadow.

## Release checks

| Check | Passes when |
|---|---|
| `parity` | for the same applications, served cash-flow features equal the curated ones exactly and the served PD equals the training-path PD (to 1e-6) |
| `load` | single-application requests at a fixed concurrency meet `targets.p95_ms` and `targets.p99_ms` with no errors (cold start reported separately) |
| `rollback` | what a rollback would restore loads and decides a sample correctly, with reasons on every decline; production is untouched |

## The endpoint and its cost

`lau decision deploy --create` creates **`lau-decision`**: Model Serving, CPU, workload size Small (up to 4 concurrent
requests), scale to zero, with an AI Gateway inference table in the ops schema. The harness may query it, the promoter
manages it, the console identity may view its state. Creating it is compute: it waits for your approval.

Cost at list price (us-east-2, premium): CPU serving is $0.07 per DBU at 4 DBU per hour while scaled up, about $0.28 per
hour; a scale-to-zero endpoint stops billing after 30 minutes without requests. One daily traffic run (a minute of
requests plus the 30-minute idle tail) is roughly $0.17 a day, about $5 a month; each cold start adds wait time, not
cost. Measured costs replace this estimate once it runs (`lau cost`).

## Approvals in one place

| What | Who | Command |
|---|---|---|
| A policy version | `approvals.policy` different people, each at a terminal | `lau policy approve`, then `lau policy apply` |
| A champion (promotion) | `approvals.promotion` | `lau decide` / console Approvals |
| Serving a champion | `approvals.rollout` | `lau rollout decide` / console Rollouts |
| Rollback | one person, with a reason | `lau rollout rollback` / console Rollouts |
