# RefCheckArena Experiment Report

This report is generated from local JSON result files under `refcheckarena/results/`.

## Scope

- Result rows analyzed: 12
- Reference-check matrix modes are reported in CSV outputs; `full` means all 42 ordered evaluator-target pairs were attempted.
- Benchmark source: OpenAI GPT-4.1 launch benchmark appendix (https://openai.com/index/gpt-4-1/).
- Benchmark alignment uses GPT-4o mini, GPT-4.1 mini, and GPT-4.1 because those models have comparable scores in the same official table.
- Benchmark alignment is filtered to compact, structured, forced-Critic calibration runs, excluding baseline, no-forced-Critic ablations, and checker-only rechecks.

## Environment Health

|condition|collaboration_profile|model|checker_model|profile|model_profile|context_mode|critic_min_revision|reference_mode|n|turns|artifacts|reviews|critic_rejections|handoffs|open_handoffs|checks|insufficient_rate|citation_rate|
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
|baseline|neutral|openai/gpt-4.1-mini-2025-04-14|openai/gpt-4.1-mini-2025-04-14|full|homogeneous|full|1|full|2|42.000|0.000|0.000|0.000|0.500|0.500|42.000|0.000|0.911|
|structured|calibration|openai/gpt-4.1-2025-04-14|openai/gpt-4.1-mini-2025-04-14|smoke|homogeneous|compact|1|full|1|30.000|5.000|16.000|4.000|36.000|0.000|41.000|0.000|0.936|
|structured|calibration|openai/gpt-4.1-mini-2025-04-14|openai/gpt-4.1-mini-2025-04-14|smoke|homogeneous|compact|1|full|1|30.000|5.000|16.000|4.000|37.000|0.000|42.000|0.000|0.954|
|structured|calibration|openai/gpt-4.1-mini-2025-04-14|openai/gpt-4.1-mini-2025-04-14|smoke|homogeneous|full|0|full|2|27.000|5.000|14.000|0.000|28.500|0.000|42.000|0.000|0.951|
|structured|calibration|openai/gpt-4.1-mini-2025-04-14|openai/gpt-4.1-mini-2025-04-14|smoke|homogeneous|full|1|full|2|30.000|5.000|16.000|4.000|36.500|0.000|41.500|0.000|0.900|
|structured|calibration|openai/gpt-4.1-mini-2025-04-14|openai/gpt-5.4-2026-03-05|recheck|unknown|unknown|unknown|sampled_4|1|30.000|5.000|16.000|4.000|37.000|0.000|4.000|0.000|1.000|
|structured|calibration|openai/gpt-4o-mini-2024-07-18|openai/gpt-4.1-mini-2025-04-14|smoke|homogeneous|compact|1|full|1|30.000|5.000|16.000|4.000|36.000|0.000|42.000|0.000|0.876|
|structured|neutral|openai/gpt-4.1-mini-2025-04-14|openai/gpt-4.1-mini-2025-04-14|full|homogeneous|full|1|full|2|30.000|5.000|16.000|4.000|36.500|0.000|42.000|0.000|0.932|

## Reference Score Summary

|condition|collaboration_profile|model|checker_model|profile|model_profile|context_mode|critic_min_revision|reference_mode|n|refcheck_overall|collaboration|handoff_clarity|reliability|communication|initiative|score_spread|
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
|baseline|neutral|openai/gpt-4.1-mini-2025-04-14|openai/gpt-4.1-mini-2025-04-14|full|homogeneous|full|1|full|2|4.036|4.036|4.071|4.083|4.048|4.238|0.167|
|structured|calibration|openai/gpt-4.1-2025-04-14|openai/gpt-4.1-mini-2025-04-14|smoke|homogeneous|compact|1|full|1|3.919|4.000|3.895|3.895|3.971|4.000|0.400|
|structured|calibration|openai/gpt-4.1-mini-2025-04-14|openai/gpt-4.1-mini-2025-04-14|smoke|homogeneous|compact|1|full|1|3.976|4.000|3.905|3.976|3.857|4.000|0.167|
|structured|calibration|openai/gpt-4.1-mini-2025-04-14|openai/gpt-4.1-mini-2025-04-14|smoke|homogeneous|full|0|full|2|4.000|4.000|3.595|3.881|3.988|3.988|0.000|
|structured|calibration|openai/gpt-4.1-mini-2025-04-14|openai/gpt-4.1-mini-2025-04-14|smoke|homogeneous|full|1|full|2|3.940|4.000|3.467|3.771|3.881|4.024|0.250|
|structured|calibration|openai/gpt-4.1-mini-2025-04-14|openai/gpt-5.4-2026-03-05|recheck|unknown|unknown|unknown|sampled_4|1|3.250|3.500|2.750|3.000|3.500|3.500|1.000|
|structured|calibration|openai/gpt-4o-mini-2024-07-18|openai/gpt-4.1-mini-2025-04-14|smoke|homogeneous|compact|1|full|1|3.738|3.952|3.262|3.524|3.524|3.952|0.667|
|structured|neutral|openai/gpt-4.1-mini-2025-04-14|openai/gpt-4.1-mini-2025-04-14|full|homogeneous|full|1|full|2|3.976|4.000|3.476|3.583|3.976|4.000|0.167|

## Benchmark vs Reference-Check Alignment

|label|benchmark_avg|academic_avg|coding|instruction_avg|tool_avg|refcheck_overall|collaboration|handoff_clarity|reliability|communication|initiative|benchmark_rank|refcheck_rank|rank_delta|
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
|GPT-4.1|64.963|78.250|54.600|62.850|60.967|3.919|4.000|3.895|3.895|3.971|4.000|1|2|-1|
|GPT-4.1 mini|54.637|76.250|23.600|59.950|47.033|3.976|4.000|3.905|3.976|3.857|4.000|2|1|1|
|GPT-4o mini|41.775|61.100|8.700|49.350|34.867|3.738|3.952|3.262|3.524|3.524|3.952|3|3|0|

## Benchmark Correlations

|metric|pearson_r|spearman_rho|n|
|---|---|---|---|
|refcheck_overall|0.770|0.500|3|
|handoff_clarity|0.890|0.500|3|
|reliability|0.809|0.500|3|
|communication|0.978|1.000|3|

## Generated Plots

- `handoffs_by_condition.svg` shows mean handoff counts for each analyzed condition.
- `benchmark_alignment.svg` plots official benchmark average against RefCheck overall.

## Doubts and Caveats

- Current live runs are still small. Treat correlations as pilot results until we add repeated runs and full reference matrices for every model.
- The calibration profile deliberately seeds recoverable collaboration friction. It is useful for validating the instrument, but neutral-profile results should be reported separately as the main condition.
- Reference checks are LLM-generated. The target-specific summaries reduce generic team praise, but a human or cross-model rater panel would strengthen claims.
- Benchmark alignment uses public benchmark percentages from one OpenAI source. This is clean for a pilot table, but the paper should clearly describe it as a coarse capability index rather than a definitive leaderboard.
- Full ordered-pair checks are more rigorous than sampled checks. Any table that uses sampled checks should say so explicitly.
- GPT-5.4/GPT-5.5 collaboration-generation attempts through Vals were materially slower than GPT-4.1 mini in this local environment. Completed GPT-5-family data in this report should be read as checker-only unless the `model` column itself is a GPT-5-family model.
