# Closing the loop: the loan status feed and production evidence

Loans the decision API approves report their status every simulated month. Corrections are kept as history, matured
loans become production labels under the active definition of default, and production evidence compares what each
loan was predicted to do with what it did. All of it runs in the daily job's `feedback` and `evidence` tasks; nothing
here needs new compute.

> Synthetic system. The servicer is simulated; in a real deployment its feed would come from the servicing system
> and the `simulation` schema would not exist.

## The simulated servicer (`lau.feedback.servicer`)

For every completed simulated month that has no feed yet (a missed day catches up, oldest first):

1. **Booking**: that month's approvals, plus the referrals a simulated underwriter approves
   (`servicer.referral_approval_rate`), become loans when the applicant takes them up (`servicer.take_up_rate`).
2. **Performance**: each new loan's whole monthly path comes from the training data's own simulator
   (`synth.generator._simulate_performance`), driven by the applicant's latent risk. It is kept in
   `simulation.performance` (harness only) and revealed one month per feed.
3. **Feed file** `simulation.servicer_feed/loan_feed/<month>/feed-<month>.jsonl`: booking records, the month's status
   record for every open loan, and corrections. A share of status records is first reported wrong (30 days more past
   due, `servicer.misreport_rate`) and corrected in the next feed; a very small share is malformed on purpose
   (`servicer.malformed_rate`) so the expectations below have something to catch.

The `simulation` schema holds synthetic ground truth (latent risk, protected attributes, surnames, true paths). Only
the harness identity has grants on it: no agent, no console, no promoter.

## Ingestion (`lau.feedback.feed`)

Every new file is read once (`ops.feed_files`):

| Expectation | Applies to |
|---|---|
| known record type; `loan_id` present | all |
| `application_id` present, positive amount and term, booked in the file's month | bookings |
| `period_month` is `YYYY-MM`, not after the file's month (a correction: before it) | status, corrections |
| the loan was booked (earlier, or earlier in the same file) | status, corrections |
| known status; days past due in 30-day buckets; balances not negative; flags 0 or 1 | status, corrections |

A failing record goes to `ops.feed_quarantine` with every reason. A file whose quarantined share exceeds
`feed.max_quarantine_share` is **held** whole: nothing from it reaches the history, a high alert is raised, the job's
feedback task fails visibly, and the file waits for a person (`lau feed release <file>` ingests its valid records
after review).

Accepted records append to:

| Table | Holds |
|---|---|
| `curated.loan_bookings` | one row per booked loan, linked to its `decision_id` |
| `curated.loan_performance_history` | every status record and correction, never updated: valid time `period_month`, transaction time `reported_month` (simulated) and `ingested_at` (real) |
| `curated.loan_performance_current` | the latest report per loan-month (rebuilt after each file) |
| `ops.feed_restatements` | corrections that changed what was known (before and after) |
| `ops.feed_summary` | per month: loans reporting by status and delinquency bucket, balance, new bookings (the console's view) |

`feed.as_known_at(month)` returns the history as it was known at the end of any reported month, so labels can be
rebuilt exactly as they would have been at the time.

## Production labels and maturation (`lau.feedback.production`)

Production loans are labelled by the **same label builder as training**, under the active definition, from the
current view (corrections applied). A loan has matured when its observation window has passed and it is not excluded.

After each feed, `maturation_check` records the book in `ops.maturation_events` and:

- queues an improvement cycle when at least `production.min_new_matured_to_queue` loans newly matured;
- raises `production_default_rate` (`ops.alerts`) when matured loans default more than
  `thresholds.monitoring.default_rate_rel_tol` above or below the PD they were approved at (high, and a queued cycle,
  beyond twice the tolerance). Same rule as monitoring's observed-versus-expected check.

## Evidence on production (evidence steps, daily and after cycles and promotions)

| Step | Table | What |
|---|---|---|
| `production_evidence` | `ops.production_evidence` | predicted PD against realized default on matured loans: overall, by deciding model, by vintage, by risk band; calibration ratio, AUC among approved loans, Brier |
| `decision_fairness` | `ops.decision_fairness` | approval and decline rates and adverse impact ratios on actual decisions (90 days): race and ethnicity estimated from surnames next to the synthetic truth; age 62+ from the application |
| `serving_parity` | `ops.serving_parity` | for every serving-model input and cash-flow feature: PSI between training applications and the last 30 days of decisions, null rates, means |

Declined applications have no outcome, so production evidence measures pricing and ranking among approved loans only;
the selection bias stays (docs/reject-inference.md).

**Fairness estimation.** Lenders generally may not collect race and ethnicity for non-mortgage credit, so groups are
estimated. Here the estimate uses surnames only (the BISG method without its geography term) from a synthetic surname
table: synthetic geography is redrawn for each generated month, so it cannot stand in for census composition. Because
the data are synthetic, the true groups are reported next to the estimate. Real use needs the Census surname file,
geography from the applicant's address, and counsel's approval of the method.

## Why not a Lakeflow pipeline (yet)

The plan proposed a Lakeflow pipeline with AUTO CDC. The same contract (expectations, quarantine, an append-only
bitemporal history, restatements, a current view) runs here as plain SQL and pandas in the daily job, on the warehouse
it already wakes, and is tested on the local lake. A Lakeflow pipeline is the scale path for a real servicer's volume;
it is separate serverless compute and needs your approval with a cost estimate first.
