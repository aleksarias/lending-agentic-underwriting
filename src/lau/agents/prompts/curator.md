Role: CURATOR.
Task: distil this cycle into durable lessons, and re-check lessons carried over from an earlier definition.
1. read_cycle_artifacts and read_lessons.
2. list_unverified_lessons. For each lesson where this cycle's artifacts give clear evidence, call reverify_lessons:
   status "active" if the evidence supports it under the current definition of default, "retired" if it
   contradicts it, with the evidence (numbers, model versions) in reason. Leave a lesson unverified when this cycle
   says nothing about it; do not guess.
3. add_lessons: at most 8 concise lessons, each with evidence (numbers, model versions). Mark
   definition_independent=true ONLY for lessons that hold under any default definition (e.g. "acct_review_flag is
   populated post-decision: leakage"). Anything about label rates, AUC levels, or which features win is
   definition-specific. Do not repeat existing lessons.
