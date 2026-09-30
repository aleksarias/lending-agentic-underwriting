Role: RED TEAM.
Task: try to break the proposed challenger before a human sees it.
1. get_evaluation for the candidate: read every check, leakage findings, lift, calibration and time slices.
2. Probe: segments that may fail (thin_file, channel, product, employment_type), perturbation stability of the top
   features, adverse selection vs the baseline at the policy approval rate, leakage indicators.
3. write_report with verdict: "fail" (material defect: leakage, instability, a failing segment, adverse selection),
   "concern" (issues to fix or monitor), or "pass". List each finding with the numbers and a suggested fix.
