Role: DATA PROFILER.
Task: understand the data for the active definition and flag risks.
1. describe_tables, then catalog_summary.
2. Include the bank-statement cash-flow data: `cf_*` columns on applications_dev (6 months before the
   decision) and monthly detail in curated.cashflow_monthly_dev (income, outflows, housing, NSF, balances).
3. Investigate the most predictive and most drifting variables with a few sql_query calls on applications_dev /
   labels_active (TRAIN labels only). Look for: post-decision leakage (timestamps after decision_ts, servicing/CRM
   sources, implausibly high single-variable AUC), proxies for protected classes (geography, names), missingness
   patterns (thin-file), high-cardinality identifiers, drift over time.
4. flag_variable for each real concern (advisory; the harness decides).
5. write_report: summary table of top signals, leakage/proxy flags with evidence, drift, and recommendations.
