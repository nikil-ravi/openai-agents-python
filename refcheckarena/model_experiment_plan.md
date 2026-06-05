# RefCheckArena Model Experiment Plan

This document records the model-assignment dimension separately from the generated result
tables. It should be updated as keys, model access, and runtime feasibility change.

## Completed Rows

|Purpose|Agents|Checker|Result file|Notes|
|---|---|---|---|---|
|Main structured vs baseline pilot|`openai/gpt-4.1-mini-2025-04-14` for all roles|same|`results/refcheck_20260604_174639.json`|Two tasks, structured and baseline, full ordered checks.|
|Calibration validity|`openai/gpt-4.1-mini-2025-04-14` for all roles|same|`results/refcheck_20260604_180034.json`|Two structured tasks, full ordered checks; one final checker timeout.|
|No-forced-Critic ablation|`openai/gpt-4.1-mini-2025-04-14` for all roles|same|`results/refcheck_20260604_181308.json`|Two structured tasks, full ordered checks; confirms shorter horizon and fewer handoffs.|
|Current-model checker sample|Original `gpt-4.1-mini` collaboration trace|`openai/gpt-5.4-2026-03-05`|`results/refcheck_20260604_184952.json`|Four sampled checks on an existing calibration trace; slow but completed.|
|Benchmark alignment: GPT-4o mini|`openai/gpt-4o-mini-2024-07-18` for all roles|`openai/gpt-4.1-mini-2025-04-14`|`results/refcheck_20260604_191030.json`|One structured calibration task, full ordered checks.|
|Benchmark alignment: GPT-4.1|`openai/gpt-4.1-2025-04-14` for all roles|`openai/gpt-4.1-mini-2025-04-14`|`results/refcheck_20260604_191621.json`|One structured calibration task, 41 completed checks and one timeout.|
|Benchmark alignment: GPT-4.1 mini compact|`openai/gpt-4.1-mini-2025-04-14` for all roles|same|`results/refcheck_20260604_192059.json`|One structured calibration task, compact context, full ordered checks; apples-to-apples with the new alignment rows.|

## Current OpenAI Model Findings

Vals model-library registry contains these relevant OpenAI IDs:

- `openai/gpt-5.5`
- `openai/gpt-5.5-high`
- `openai/gpt-5.5-pro`
- `openai/gpt-5.4-2026-03-05`
- `openai/gpt-5.4-2026-03-05-high`
- `openai/gpt-5.4-2026-03-05-low`
- `openai/gpt-5.4-mini` / `openai/gpt-5.4-mini-2026-03-17`
- `openai/gpt-5.4-nano-2026-03-17`
- `openai/gpt-5.2`, `openai/gpt-5.2-pro`, `openai/gpt-5.2-codex`

Observed locally:

- `openai/gpt-5.5` completed a tiny structured probe but stalled on the first arena research gate.
- `openai/gpt-5.4-2026-03-05` completed a tiny structured probe and a four-check recheck sample.
- `openai/gpt-5.4-2026-03-05` timed out during arena collaboration generation, including a mixed run where it served as Orchestrator and reached finalization before timing out.
- Smaller or lower-effort GPT-5.4/GPT-5 variants timed out on tiny probes in this local Vals setup.

## Recommended Model Assignment Experiments

|Name|Orchestrator|Specialists|Reviewer|Critic|Checker|Purpose|
|---|---|---|---|---|---|---|
|Homogeneous frontier|`openai/gpt-5.4-2026-03-05`|same|same|same|same|Direct current-model capability row; currently high-latency.|
|Frontier manager|`openai/gpt-5.4-2026-03-05`|`openai/gpt-4.1-mini-2025-04-14`|`gpt-4.1-mini`|`gpt-4.1-mini`|`gpt-4.1-mini`|Tests whether a stronger manager improves handoff quality.|
|Frontier review board|`openai/gpt-5.4-2026-03-05`|`gpt-4.1-mini`|`openai/gpt-5.4-2026-03-05`|`openai/gpt-5.4-2026-03-05`|`gpt-4.1-mini` or `gpt-5.4`|Tests whether stronger reviewers create better revision pressure.|
|Checker ablation|existing completed traces|existing completed traces|existing completed traces|existing completed traces|`gpt-4.1-mini`, `gpt-5.4`, Opus if available|Separates collaboration quality from judge strictness.|
|Anthropic homogeneous|`anthropic/claude-sonnet-4-6`|same|same|same|`anthropic/claude-opus-4-7`|Requires `ANTHROPIC_API_KEY`; likely best next provider run.|
|Anthropic review board|`anthropic/claude-opus-4-7`|`anthropic/claude-sonnet-4-6`|`anthropic/claude-opus-4-7`|`anthropic/claude-opus-4-7`|`anthropic/claude-opus-4-7`|Tests manager/reviewer strength under a realistic mixed team.|

## Key Requirements

- OpenAI runs can continue with the existing `.env`.
- Anthropic runs require `ANTHROPIC_API_KEY` in `.env`.
- If provider latency remains high, prioritize checker ablations and mixed-role runs before homogeneous frontier full matrices.
- Full 42-check matrices should be used for paper tables when feasible; sampled current-model rows must be labeled as sampled.
