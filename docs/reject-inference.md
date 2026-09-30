# Reject inference and selection bias (not solved)

Every label comes from loans the legacy policy approved (~70% of applicants in the synthetic data). A challenger
that would approve applicants the legacy policy declined ("swap-ins") is evaluated only on previously approved
loans, so its performance in exactly the region where it differs is unobserved. Validation/holdout AUC therefore
overstates confidence for policy changes that expand approvals.

What the system does:
- The red-team tool `probe_adverse_selection` reports swap-in/swap-out default rates at the policy approval rate —
  on approved loans only, with that caveat stated in the output.
- `promotion/reject_inference.py` defines a `RejectInferenceStrategy` hook (default `NoRejectInference`, which
  changes nothing and says so).
- `controlled_approval_design()` sizes a randomized, time-boxed approval experiment in a score band just below the
  cutoff (the only way to get unbiased outcome data), with expected defaults, detectable difference, and expected
  loss.

What it does not do: parcelling, augmentation or any silent re-weighting. Running a controlled-approval experiment
needs credit-policy, compliance and loss-budget sign-off and is out of scope for agents.
