# Runbook

What to do when something needs a person. Synthetic dev system: the same steps apply in production once the readiness
checklist (`lau readiness status`) is signed.

## Every day (automatic)

The `lau-daily` job (deployed paused; 06:00 UTC once unpaused) runs, in order: definition sync, synthetic decisions,
the loan status feed, shadow scoring, monitoring, evidence, the monthly report on the first run of a month, the console
snapshot, and `notify`. **`notify` fails while anything needs a person**, so the job's failure email is the alarm. It
turns green once each item is handled. Weekly, `lau-improvement-cycle` runs a cycle only when one is queued.

## The daily job failed

1. Open the run in the workspace (Jobs, `lau-daily`) and read the failed task's error.
2. `notify` failed: the error lists what needs a person. Handle each item (below); nothing else is wrong.
3. Any other task failed: the remaining tasks still ran (`run_if: ALL_DONE`). Fix the cause, then rerun the job or
   just that task. Repeated failures of `evidence` leave the console's verdict stale (it says so).

## A high alert

| Alert | Meaning | What to do |
|---|---|---|
| Score or feature distribution shifted (PSI) | New applications look different from the definition's baseline | Check Data (parity) and Alerts; a cycle was queued. Acknowledge with a note once understood |
| Observed default rate versus expected | Matured historical loans default off the model's expectation | Check Progress and Performance; a cycle was queued |
| Matured production loans default more (or less) than predicted | Loans the API approved are off their approval PD | Check Progress (production evidence by band and vintage). If the model is clearly miscalibrated: roll back (below) or tighten the policy (`config/policy.yaml`, approved like any policy change) |
| Feed file held for review | Too many records in a servicer file failed the checks; nothing from it was loaded | Review `ops.feed_quarantine` for the file (console: Loan status feed). If the bad records are isolated, `lau feed release <file>`; otherwise get a corrected file from the servicer |

Acknowledge in the console (Alerts) or `lau ack-alert <id> --note "..."`. Acknowledging changes nothing else.

## Roll back a champion

One person, one step, with a reason: console Rollouts, or `lau rollout rollback <rollout_id> --reason "..."`. Serving
returns to the model that served before (or the legacy policy), the decision model is rebuilt and the endpoint updated.
Then: review what went wrong, and record it with the rollout. `lau decision check rollback` proves the restore path
works without touching production.

## The decision endpoint is down or slow

Callers get no decision. The endpoint itself already falls back to the legacy policy when the model errors or runs out
of its time budget (`timeout_ms`), and every such decision says so (`fallback_used`). If the endpoint is unavailable:

1. `lau decision status`: does the endpoint exist, is it ready, which version does it serve?
2. Scale-to-zero cold start: the first request after 30 idle minutes waits for a container. Expected, not an outage.
3. A failed update: `lau decision deploy` points it at the live build again.
4. Latency: `lau decision check load --via endpoint` against the targets (p95 300 ms, p99 800 ms).

## A bad model was promoted

Promotion alone changes nothing that decides (shadow first). If it already serves: roll back (above). Then reject
or fix the candidate; a person can reject features it relied on (`lau features decide <name> --decision reject`).

## The loan status feed is late

The `feedback` task writes and reads the feed once per simulated month and catches up on missed months, oldest first.
A real servicer feed that is late shows on the Loan status feed screen (newest file); maturation and production
evidence wait for it. Nothing decides differently.

## Credentials

Never paste a token into chat, code or config. Admin: `databricks auth login` (OAuth); service principals: OAuth
secrets in `.env` (mode 600) and the `lau` secret scope. Rotate a service principal secret: delete it in the account
console, remove its two lines from `.env`, run `lau init` (it creates a new one only when missing), update the secret
scope for jobs.

## Costs

`lau cost` shows actual DBUs from `system.billing.usage` and logged spend. The monthly hard stop
(`config/budgets.yaml`) stops agent work. The endpoint scales to zero; pause schedules in the workspace to stop all
recurring compute.

## On call

Whoever receives the job's failure email. In dev that is the person who deployed the bundle. Production needs a rota
(readiness item `security_operations`).
