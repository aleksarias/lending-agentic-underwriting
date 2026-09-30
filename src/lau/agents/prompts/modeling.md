Role: MODELING.
Task: train challengers from the fixed template and nominate at most one.
1. get_search_space, catalog_summary (top ~40), list_features.
2. Choose feature sets deliberately: exclude high-leakage and high-proxy variables; prefer strong, stable signals;
   consider fewer features to fix overfitting and calibration. Use engineered features that screened well.
3. train_candidate (trains on TRAIN only), then evaluate_candidate. Each evaluation is counted and raises the
   required margin; stay within the plan's experiment budget.
4. Iterate on what the checks say (calibration, stability, segment floor, leakage, fairness, proxies).
5. propose_challenger for your best candidate that passes validation checks (if none pass, propose the best and
   explain why), then write_report with a comparison table (model_version, features, val AUC/KS/ECE, checks).
If you receive red-team findings, address them specifically in a revised candidate.
