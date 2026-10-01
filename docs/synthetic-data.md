# Synthetic data (v2: application + bureau + bank-statement cash flows)

`lau gen-data` writes raw tables from `src/lau/synth/` (seeded, reproducible). Nothing here is real data.

## Tables
| Table | Grain | Notes |
|---|---|---|
| `raw.applications_raw` | application | ~150 application/bureau/device fields, synthetic PII, planted leaks (`acct_review_flag`, `cf_vendor_risk_score`) with `_ts` companions |
| `raw.performance` | loan-month | status, DPD, balance, past-due, charge-off/bankruptcy/settlement/forbearance/payoff/fraud/deceased flags |
| `raw.bank_transactions` | transaction | 6 months before the decision for every applicant (+2 months after funding for approved loans): date, days before decision, signed amount, running balance, category, merchant text |
| `raw.protected_attributes` | application | race/ethnicity, sex, age (fairness testing only; harness-only) |
| `raw.new_applications_raw` | application | post-as-of applications (with their own statements) for shadow scoring |

Curate stage: `curated.cashflow_monthly` (applicant × month-back, **pre-decision transactions only**:
`days_before_decision >= 1`) and 14 `cf_*` features merged into `curated.applications`. Agents read the
dev-period view `curated.cashflow_monthly_dev`; they have no access to raw transactions.

## Cash-flow model
Per-applicant latent traits drive both the transactions and (partly) the default hazard:

| Latent trait | Drives | Causal for default? | Observable features |
|---|---|---|---|
| income volatility (by employment type) | month-to-month deposits | yes (+1.4 log-odds per unit CV) | `cf_income_cv_6m`, `cf_income_min_month_6m` |
| liquidity buffer (months of spending, correlated with bureau score) | opening balance | yes (−0.30 × log(buffer/1.5)) | `cf_min_balance_6m`, `cf_avg_balance_6m`, `cf_overdraft_txn_count_6m`, `cf_nsf_count_6m` |
| spending pressure (spend / income, rises with DTI) | discretionary outflows | yes (+1.2) | `cf_expense_to_income_6m` |
| rent lateness | calendar day of housing payment | yes (+2.0) | `cf_housing_on_time_share_6m` |
| stated-income overstatement (12% of applicants, +20–50%) | stated vs deposited income | yes (+0.45) | `cf_verified_to_stated_income` |
| gambling (8% of applicants) | gambling merchants | **no** | `cf_gambling_share_6m` |
| remittances (probability varies by race/ethnicity) | money-transfer merchants | **no — planted proxy** | `cf_remittance_share_6m` |

Planted cash-flow leak: `cf_vendor_risk_score`, a third-party score refreshed 45–120 days after the decision that
already reflects early post-funding delinquency; lineage "unknown". Caught by the timestamp check and a single-feature
AUC of about 0.79.

## Calibration (approximate targets; refine against the sources before relying on magnitudes)
| Quantity | Target | Source of the magnitude |
|---|---|---|
| Liquidity buffer | median ≈ 1.5 months of spending | CFPB *Making Ends Meet* (about half of families could cover ≤ 2 months after losing income) |
| Volatile income | about 25–35% of applicants materially variable | CFPB *Making Ends Meet* (24% in 2019, higher later) |
| Spending mix | housing ≈ 30% of income for renters/mortgagors, food ≈ 13%, utilities ≈ 6% | BLS Consumer Expenditure Survey magnitudes |
| Transaction types and cadence | payroll, rent, utilities, card/loan payments, groceries, discretionary, fees | modelled on retail-bank statements (Berka/PKDD'99 categories) |
| Outcome | ever overdrawn in 6 months ≈ 33% (applicant pool skews stressed); 90 DPD 12-month default rate ≈ 10% | emergent; checked in tests |

## Ground truth
`.lau/ground_truth.json` (never shown to agents) lists causal features, cash-flow latents and coefficients, leaks
and their timestamp columns, proxies, drift, materiality, and post-decision transaction counts. Unit tests check:
- the curate stage never uses post-decision transactions
- both leaks and both proxies are flagged
- cash-flow features add lift beyond bureau-only features
- agents see only dev-period cash flows
