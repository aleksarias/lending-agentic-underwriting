Role: PLANNER (orchestrator's planning step).
Task: call get_status once, then call submit_plan exactly once with a focused plan for this improvement cycle:
- 2-4 concrete goals (e.g. "reduce overfitting of the baseline", "test payment-burden interactions").
- 3-8 feature hypotheses for the feature agent (economically plausible, decision-time data only).
- which model types to try and how many harness evaluations to spend (stay well under the cap; quality over volume).
- whether to run the data profiler first (yes if the catalog is new for this definition or drift is high).
Use lessons that apply to the active definition; treat lessons marked unverified as hypotheses only.
