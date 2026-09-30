# Compliance notes (assumptions and items for counsel / compliance review)

**This system is not claimed to be compliant with ECOA/Regulation B, FCRA, UDAAP, state law, or model-risk-
management guidance (e.g. SR 11-7 / OCC 2011-12). It is engineering scaffolding designed to make review possible.**

## Assumptions
1. Development uses fully synthetic data. Protected attributes (race/ethnicity, sex, age) are *generated* so
   fairness testing can be exercised. For non-mortgage credit, lenders generally may not collect race/ethnicity/sex
   except in limited circumstances; production testing would rely on proxy estimation (e.g. BISG) under a
   documented methodology.
2. Age: ECOA permits age in an empirically derived, demonstrably and statistically sound system only under specific
   conditions (and never to the detriment of applicants 62+). The system treats `age`/`age_62_plus` as prohibited
   model inputs and tests adverse impact for 62+.
3. Adverse impact is measured with the four-fifths rule (AIR ≥ 0.80) at a simulated approval rate of 70% on the
   through-the-door population of the evaluation window. The threshold, approval rate and reference groups are
   configuration (`config/thresholds.yaml`, `config/protected_classes.yaml`) — policy decisions, not engineering.
4. Proxy detection flags any feature whose single-feature AUC for protected-group membership exceeds 0.65. The
   planted proxy (`geo_affluence_idx`, ZIP-composition based) is caught; real proxies can be subtler (combinations).
5. Adverse-action reason codes are derived from model contributions (TreeSHAP/linear), mapped to catalog
   descriptions. Mapping to consumer-facing reason statements is not implemented.
6. Post-decision information (e.g. servicing/CRM data) is treated as leakage and blocked from models.

## Items for review
- [ ] Protected-class definitions, reference groups, AIR threshold, and approval-rate assumption.
- [ ] Whether and how proxy estimation (BISG) may be used; data governance for any estimated attributes.
- [ ] Less-discriminatory-alternative (LDA) search obligations: the harness reports AIR per candidate but does not
      search for LDAs systematically.
- [ ] Reason-code methodology and the consumer-facing reason-statement mapping (Reg B specificity).
- [ ] FCRA: permissible purpose, bureau data usage in development, and adverse-action notice content.
- [ ] Model-risk documentation: conceptual soundness, the multiple-testing heuristic, OOT holdout budget,
      ongoing monitoring thresholds, and the champion/challenger process.
- [ ] Use of an external LLM API: data-handling terms, and the masking layer before any real data is used
      (masking is on by default when `environment=prod`).
- [ ] Reject inference / selection bias (docs/reject-inference.md); any controlled-approval experiment design.
- [ ] Human-approval controls: who may approve promotions and definition changes; segregation of duties (today the
      same person owns the catalog and approves).
- [ ] Record retention for approvals, traces and model lineage.
