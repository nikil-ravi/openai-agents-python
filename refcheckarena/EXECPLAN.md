# Build a Rich RefCheckArena Experiment

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries, Decision Log, and Outcomes & Retrospective must stay up to date as work proceeds.

If PLANS.md is present in the repo, maintain this document in accordance with `/Users/nikilravi/Desktop/Personal/openai-agents-python/PLANS.md`.

## Purpose / Big Picture

The current RefCheckArena demo produces a short three-agent transcript with too little collaborative signal for meaningful peer reference checks. This change builds a local experimental runner under `/Users/nikilravi/Desktop/Personal/openai-agents-python/refcheckarena/` that reliably creates rich multi-agent traces: an Orchestrator, six specialists, structured phase gates, artifact submissions, peer reviews, forced Critic revisions, handoff returns, final artifacts, and ordered pair reference checks. The user should be able to run a small smoke experiment with OpenAI through `vals-ai/model-library`, inspect the transcript and metrics, then scale to fuller runs.

## Progress

- [x] (2026-06-04T22:44:42Z) Read the existing demo, methodology note, paper draft, and repository planning rules.
- [x] (2026-06-04T22:44:42Z) Confirmed `.env` contains `OPENAI_API_KEY` without printing the value.
- [x] (2026-06-04T22:44:42Z) Confirmed `model_library` works with OpenAI structured output when invoked through `uv run --with model-library --with 'protobuf>=6.30.0'`.
- [x] (2026-06-04T23:25:47Z) Implemented `/Users/nikilravi/Desktop/Personal/openai-agents-python/refcheckarena/refcheckarena_arena.py` with typed tasks, agents, artifacts, reviews, handoffs, metrics, reference checks, fake client, Vals model-library client, progress logging, and checker timeouts.
- [x] (2026-06-04T23:25:47Z) Added focused tests using the deterministic fake model client in `/Users/nikilravi/Desktop/Personal/openai-agents-python/refcheckarena/test_refcheckarena_arena.py`.
- [x] (2026-06-04T23:25:47Z) Ran offline tests, fake smoke runs, live structured smoke runs, and a live baseline sample.
- [x] (2026-06-04T23:25:47Z) Iterated on handoff gating and reference prompts until live structured runs produced closed handoffs, target-specific evidence, and non-perfect score clusters.
- [x] (2026-06-04T23:47:57Z) Made tasks harder and modeled review/revision work transfer as formal handoffs, raising the structured fake run to 33 handoffs and the latest live run to 36 handoffs with 0 open handoffs.
- [x] (2026-06-05T00:28:00Z) Added per-model-call timeout and retry controls after a full live run stalled during collaboration before reference collection.
- [x] (2026-06-05T01:46:39Z) Completed the main neutral full-matrix live suite for two tasks and both conditions.
- [x] (2026-06-05T02:00:34Z) Completed the structured calibration full-matrix live run for two tasks.
- [x] (2026-06-05T02:13:08Z) Completed the no-forced-Critic ablation for two structured calibration tasks.
- [x] (2026-06-05T02:19:42Z) Added role-specific model-profile support and verified saved role-to-model metadata.
- [x] (2026-06-05T02:49:52Z) Completed a sampled GPT-5.4 checker recheck on an existing structured calibration trace.
- [x] (2026-06-05T03:10:30Z) Completed full-matrix benchmark-alignment rows for GPT-4o mini, GPT-4.1 mini, and GPT-4.1 under compact structured calibration with a common checker.

## Surprises & Discoveries

- Observation: `model_library` is not installed in the project environment.
  Evidence: `uv run python -c "import importlib.util; ..."` reported `model_library=missing`.
- Observation: `uv run --with model-library` initially fails because `xai_sdk` loads protobuf 6.x generated code while the project environment has protobuf 5.x.
  Evidence: importing `model_library` raised `google.protobuf.runtime_version.VersionError`.
- Observation: Adding `--with 'protobuf>=6.30.0'` makes `model_library` import successfully.
  Evidence: `uv run --with model-library --with 'protobuf>=6.30.0' python -c ...` printed `model_library import ok`.
- Observation: `model_library` does not automatically load `.env`; the key must be in process environment or set through library settings.
  Evidence: instantiating `model('openai/gpt-4o-mini')` without loading `.env` raised `AttributeError: Missing config key: OPENAI_API_KEY`.
- Observation: A tiny structured-output call to `openai/gpt-4.1-mini-2025-04-14` succeeds through `model_library`, but the library emits an unclosed aiohttp session warning.
  Evidence: the call returned `MiniOut(answer='Hello')` and then printed an aiohttp client-session warning.
- Observation: Neutral same-model live runs create strong collaboration signal but peer scores cluster around 4s and 5s.
  Evidence: `refcheckarena/results/refcheck_20260604_160348.json` and `refcheckarena/results/refcheck_20260604_160743.json` both showed target-specific but mostly strong ratings.
- Observation: A live calibration run once stalled in the reference phase on a model-library checker call.
  Evidence: the process ran for about 11 minutes after printing `collaboration complete with 30 turns; collecting 6 reference checks`, so the runner now has per-check progress logging and `--reference-timeout`.
- Observation: The calibration profile creates recoverable collaboration friction without adding scheduler complexity.
  Evidence: `refcheckarena/results/refcheck_20260604_162520.json` produced 30 turns, 5 artifacts, 16 reviews, 4 Critic rejections, 9 handoffs, 0 open handoffs, 6 completed sampled checks, 0 timeouts, 0% insufficient evidence, 98% citation rate, and mostly 4/5 ratings with target-specific rationales.
- Observation: Treating review and revision movement as first-class handoffs produces dozens of meaningful handoffs without lengthening the scheduler.
  Evidence: `refcheckarena/results/refcheck_20260604_164750.json` produced 30 turns, 5 artifacts, 16 reviews, 4 forced Critic rejections, 36 handoffs, 0 open handoffs, 100% handoff completion, 4 completed sampled checks, 0 timeouts, and 100% citation rate.
- Observation: Full live experiments can stall before reference collection on a single model-library call.
  Evidence: the `main_neutral_gpt41mini` run started at 2026-06-04T17:21 local time printed only the structured kickoff message for several minutes and had to be terminated. The runner now wraps all model calls with `--model-timeout` and `--model-retries`, and records those settings in `run_config`.
- Observation: The main neutral full-matrix run strongly separates environment signal even when reference scores remain clustered.
  Evidence: `refcheckarena/results/refcheck_20260604_174639.json` contains four live result rows. Structured runs produced 30 turns with 37 and 36 handoffs, 0 open handoffs, 16 reviews, 4 Critic rejections, and 42/42 checks. Baselines produced 42 turns with 0 and 1 handoff, no artifacts/reviews, 42/42 checks, and one open baseline handoff in the second task. Received overall scores mostly stayed near 4.
- Observation: The calibration profile produces some lower peer-reference signal while preserving the closed handoff graph.
  Evidence: `refcheckarena/results/refcheck_20260604_180034.json` contains two structured calibration rows. The first task produced 30 turns, 37 handoffs, 0 open handoffs, 42 checks, 0 timeouts, and several roles at 3.83 overall. The second produced 30 turns, 36 handoffs, 0 open handoffs, 41 checks, 1 timeout, and ContentWriter at 3.67 overall.
- Observation: Removing the forced Critic revision gate shortens horizon length and reduces handoff volume while keeping the artifact workflow intact.
  Evidence: `refcheckarena/results/refcheck_20260604_181308.json` produced two structured calibration rows with 27 turns each, 28 and 29 handoffs, 14 reviews, 0 Critic rejections, 42/42 checks, and 0 timeouts.
- Observation: Vals' local registry has dated GPT-5.4 identifiers; plain `openai/gpt-5.4` and `openai/gpt-5.4-nano` are not valid local registry keys.
  Evidence: grepping the installed `model_library/config/openai_models.yaml` found `openai/gpt-5.4-2026-03-05`, `openai/gpt-5.4-mini-2026-03-17`, and `openai/gpt-5.4-nano-2026-03-17`; the earlier plain `openai/gpt-5.4` probe returned "Model not found in registry."
- Observation: `openai/gpt-5.5` works for a tiny structured probe but stalled on the larger arena collaboration prompt in this environment.
  Evidence: the tiny `Probe` schema call returned successfully, but `current_homogeneous_gpt55` stalled during the first research gate and was terminated without a saved result. This is a runtime caveat, not evidence that GPT-5.5 is unsuitable for the method.
- Observation: Among current-generation OpenAI candidates probed after the GPT-5.5 stall, `openai/gpt-5.4-2026-03-05` is the best confirmed Vals arena-run candidate.
  Evidence: a tiny structured probe succeeded for `openai/gpt-5.4-2026-03-05`; probes for `openai/gpt-5.4-2026-03-05-low`, `openai/gpt-5.4-mini-2026-03-17`, `openai/gpt-5.4-nano-2026-03-17`, `openai/gpt-5-mini-2025-08-07`, and `openai/gpt-5-nano-2025-08-07` timed out.
- Observation: GPT-5.4 can complete sampled reference checks on an existing long-horizon trace, but it is slow.
  Evidence: `refcheckarena/results/refcheck_20260604_184952.json` rechecked `refcheck_20260604_180034.json` result index 0 with `openai/gpt-5.4-2026-03-05`, 4 sampled ordered checks, and no terminal failure. Individual checks took roughly one to two minutes.
- Observation: A mixed current-manager run with GPT-5.4 as Orchestrator was viable through phase gates but timed out during final synthesis.
  Evidence: `current_manager_gpt54_mixed` completed kickoff, research, analysis, implementation, synthesis, and reached finalization, then the GPT-5.4 `FinalOutput` call exceeded a 240 second timeout. No result file was saved for this failed run.
- Observation: The benchmark alignment table now has three comparable model rows and positive pilot correlations.
  Evidence: `refcheckarena/results/refcheck_20260604_191030.json` (GPT-4o mini), `refcheckarena/results/refcheck_20260604_192059.json` (GPT-4.1 mini compact), and `refcheckarena/results/refcheck_20260604_191621.json` (GPT-4.1) are compact structured calibration rows with a common `openai/gpt-4.1-mini-2025-04-14` checker. The regenerated report shows Pearson correlations of 0.77 for overall, 0.89 for handoff clarity, 0.81 for reliability, and 0.98 for communication across the three benchmark rows.

## Decision Log

- Decision: Keep `model-library` as an optional run-time dependency instead of adding it to `pyproject.toml`.
  Rationale: The user asked for local experiment work in `refcheckarena/`, and adding a repo-wide dependency plus lockfile churn is unnecessary for this prototype.
  Date/Author: 2026-06-04 / Codex.
- Decision: Implement a deterministic scheduler around model-generated content.
  Rationale: The experiment must reliably create handoffs, rejections, revisions, approvals, and manager decisions; leaving scheduling entirely to models recreates the brittle short-transcript failure mode.
  Date/Author: 2026-06-04 / Codex.
- Decision: Include the Orchestrator in the peer reference matrix.
  Rationale: The user explicitly confirmed the Orchestrator should be reference-checked.
  Date/Author: 2026-06-04 / Codex.
- Decision: Use self-contained task packets for the first version.
  Rationale: The user confirmed this is acceptable, and it reduces variance while testing the collaboration instrument.
  Date/Author: 2026-06-04 / Codex.
- Decision: Keep the original `/Users/nikilravi/Desktop/Personal/openai-agents-python/refcheckarena/refcheckarena_demo.py` intact and add a new runner.
  Rationale: The original script is useful as the compact baseline and should not be overwritten while exploring the richer experimental design.
  Date/Author: 2026-06-04 / Codex.
- Decision: Add `--collaboration-profile calibration` as an optional anchor condition.
  Rationale: Neutral same-model runs tend to produce uniformly strong teammates. The calibration profile seeds simple, recoverable collaboration flaws so the reference-check instrument can be tested against known signal.
  Date/Author: 2026-06-04 / Codex.
- Decision: Add per-check progress logging and `--reference-timeout`.
  Rationale: Long experiments should not silently wait on one slow checker call, and partial run artifacts are more useful than a lost collaboration trace.
  Date/Author: 2026-06-04 / Codex.
- Decision: Count review requests, revision requests, and phase acceptance as formal handoffs.
  Rationale: These are natural work transfers in the paper's artifact-gated environment. They increase handoff signal to dozens while keeping the runner simpler than a free-form autonomous manager loop.
  Date/Author: 2026-06-04 / Codex.
- Decision: Add a model-call timeout/retry wrapper instead of changing the task design after a stalled full live run.
  Rationale: The experimental setup should remain the same, but long-running API calls should not be allowed to hang the entire suite.
  Date/Author: 2026-06-05 / Codex.
- Decision: Add role-specific model profiles before running current-model experiments.
  Rationale: The paper should separate homogeneous capability comparisons from realistic heterogeneous team assignments, and saved JSON must show exactly which model each role used.
  Date/Author: 2026-06-05 / Codex.

## Outcomes & Retrospective

Implemented and validated. The runner produces 30-turn structured collaborations for one task with seven roles, formal artifacts, peer reviews, forced Critic revisions, returned handoffs, and final artifacts. The structured handoff graph now naturally reaches dozens of handoffs through assignment, downstream transfer, review requests, revision requests, and phase acceptance. It also supports a 42-turn ungated baseline. Live runs save timestamped JSON under `/Users/nikilravi/Desktop/Personal/openai-agents-python/refcheckarena/results/` and print concise health metrics.

The setup is intentionally simple: deterministic phase gates provide horizon length and signal, while models produce the artifact/review/reference content. The main remaining research choice is experimental scale. A fake full ordered-pair run completed 42/42 checks. A full live ordered-pair run is supported with `--reference-limit 0`, but will spend most time in the checker phase.

## Context and Orientation

The current file `/Users/nikilravi/Desktop/Personal/openai-agents-python/refcheckarena/refcheckarena_demo.py` runs three agents for three rounds and then asks every ordered pair of agents for a `ReferenceCheck`. The paper draft describes a richer environment with an Orchestrator, Researcher, FinancialAnalyst, TechLead, ContentWriter, Reviewer, and Critic. It also describes a shared artifact registry, phase locks, forced Critic revision behavior, a bouncing-ball handoff protocol, and finalization blocked until every role contributes.

In this plan, an artifact is a typed work product such as a research brief, analysis memo, technical plan, report draft, or final report. A review is a peer decision on an artifact. A handoff is a logged request from one role to another that must later be returned. A reference check is the post-collaboration structured peer assessment of one agent by another.

## Plan of Work

Add a new runner file under `refcheckarena/` rather than rewriting the compact demo in place. The runner will define typed dataclasses and Pydantic schemas for tasks, agent outputs, artifacts, reviews, handoffs, transcript turns, metrics, and reference checks. It will include two clients: a Vals model-library client for live runs and a deterministic fake client for tests.

The structured condition will run a phase-locked artifact flow: Orchestrator kickoff, specialist artifact submission, Reviewer review, Critic forced rejection until the minimum revision threshold, author revision, second review pass, Orchestrator phase advance, final synthesis, final review, and Orchestrator finalization. The baseline condition will run a longer ungated conversation with the same agents and step budget but without artifact approval gates.

The runner will save JSON output under `/Users/nikilravi/Desktop/Personal/openai-agents-python/refcheckarena/results/`. The JSON will include task metadata, transcript turns, artifacts, reviews, handoffs, peer checks, score aggregates, and environment-health metrics.

Add focused pytest tests under `refcheckarena/` that use the fake client to prove the scheduler creates enough turns, every role contributes, the Critic forces revisions, handoffs close, the Orchestrator is included in reference pairs, and insufficient-evidence checks are excluded from score means.

## Concrete Steps

Run these commands from `/Users/nikilravi/Desktop/Personal/openai-agents-python`:

    uv run pytest refcheckarena -q
    uv run --with model-library --with 'protobuf>=6.30.0' python refcheckarena/refcheckarena_arena.py --client fake --tasks 1 --conditions structured --reference-limit 8
    uv run --with model-library --with 'protobuf>=6.30.0' python refcheckarena/refcheckarena_arena.py --client vals --tasks 1 --conditions structured --reference-limit 8
    uv run --with model-library --with 'protobuf>=6.30.0' python refcheckarena/refcheckarena_arena.py --client vals --tasks 1 --conditions structured --reference-limit 6 --collaboration-profile calibration --reference-timeout 90

For full local experiments, run:

    uv run --with model-library --with 'protobuf>=6.30.0' python refcheckarena/refcheckarena_arena.py --client vals --profile full

## Validation and Acceptance

Acceptance criteria:

- A fake structured run produces at least 30 collaboration turns for one task.
- The Orchestrator plus all six specialists appear as contributors and peer-check participants.
- The Critic rejects at least one initial artifact and later approves after revision.
- Every opened handoff is returned before finalization.
- Aggregation excludes checks marked `insufficient_evidence=True` from received-score means.
- A live OpenAI smoke run through `model_library` completes and writes a results JSON file.
- A checker timeout does not lose the collaboration trace; it is saved in `reference_timeouts`.

The repository-wide mandatory verification stack is only required if the change affects core runtime code, tests outside `refcheckarena/`, build/test configuration, or examples. This plan adds experimental files under `refcheckarena/`, so focused pytest plus live smoke runs are the primary validation. If wider checks become necessary, run `.agents/skills/code-change-verification/scripts/run.sh`.

## Idempotence and Recovery

The runner writes timestamped result files, so rerunning does not overwrite prior experiment output. The fake client can be used if API keys or model-library dependencies fail. The live run command keeps model-library isolated via `uv run --with`, so no dependency or lockfile rollback is expected.

## Artifacts and Notes

The Vals model-library upstream README says to install with `pip install model-library`, call models with `from model_library import model`, and rely on environment variables such as `OPENAI_API_KEY`. The local command requires `--with 'protobuf>=6.30.0'` to avoid the protobuf mismatch observed in this repository environment.

## Interfaces and Dependencies

New public local entry point:

    /Users/nikilravi/Desktop/Personal/openai-agents-python/refcheckarena/refcheckarena_arena.py

Expected command-line options:

    --client {vals,fake}
    --profile {smoke,full}
    --model <model-library model name>
    --checker-model <model-library model name>
    --conditions structured,baseline
    --tasks <count>
    --reference-limit <count or 0 for all>
    --collaboration-profile {neutral,calibration}
    --reference-timeout <seconds>
