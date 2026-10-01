"""Evidence backend: the aggregate `ops.*` tables the Underwriting Console reads.

Everything here runs as the harness identity (`get_store("harness")`): it may read raw/curated/labels/ops and never
touches `holdout`. Nothing in this package computes a default label itself; every outcome comes from
`lau.definition.label_builder.build_labels` (or its `early_indicator` for vintage curves).

Tables (schemas in docs/console/contract.md, column lists in `lau.evidence.schemas`):

    ops.benchmark_results       every model + the frozen reference re-scored under the frozen benchmarks
    ops.definition_sensitivity  default rate by origination quarter under each benchmark definition
    ops.vintage_curves          cumulative delinquency by month on book, half-year cohorts
    ops.cashflow_cohorts        bank-statement (cf_*) cohort summaries
    ops.proxy_scan              feature-vs-protected-group proxy AUCs (aggregates only)
    ops.improvement_ledger      the verdict: is the system improving?
    ops.model_registry          snapshot of the MLflow/UC registry (replaced each sync)
    ops.evaluation_metrics      ops.evaluations.result_json flattened to (metric, value) rows (replaced each sync)

Entry points: `lau.evidence.run.run_all` and the `lau.evidence.cli.app` Typer sub-app.
"""
