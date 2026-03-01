# RefCheckArena methodology sketch grounded in the OpenAI Agents SDK

## Core idea
RefCheckArena evaluates a set of agents by collecting structured, rubric-based reference checks from their peers after working on shared tasks. This mirrors human reference checks: evaluators focus on collaboration quality, reliability, and communication, not just task correctness.

## SDK-grounded building blocks
- **Team agents**: multiple `Agent` instances with complementary roles (planner, implementer, risk reviewer).
- **Reference checkers**: lightweight evaluator agents instantiated per pairwise check.
- **Execution**: repeated `Runner.run(...)` calls to drive multi-round collaboration, then additional runs for each reference checker.
- **Structured scoring**: `output_type` with a validated schema (e.g., `ReferenceCheck` model with bounded 1–5 ratings, confidence, and evidence fields).
- **Tracing**: `trace(...)` to group the full evaluation run and allow later inspection of all subcalls.
- **Transcript context**: explicit turn logs (turn ID, round, stage, speaker, content) passed to evaluators.

## Proposed evaluation protocol
1. **Task suite selection**
   - Assemble tasks that are long enough to require planning, challenge, and synthesis.
   - Favor scenarios with dependencies, uncertainty, ownership conflicts, and rollback/communication requirements.
   - Include explicit constraints and concrete deliverables so collaborative tradeoffs are visible.

2. **Multi-round team execution**
   - For each task, run multiple collaboration rounds across all team members in fixed order.
   - Use stage-aware prompts:
     - **Planning**: decomposition, ownership, sequencing.
     - **Challenge**: risk surfacing, contradiction detection, mitigation.
     - **Synthesis**: convergence, final handoffs, accountability.
   - Record every turn into a transcript with stable IDs (e.g., `T01`, `T02`, ...).

3. **Reference checks (peer ratings)**
   - For each ordered evaluator-target pair, run a reference checker with full transcript context.
   - Require evidence-grounded output: each rating includes transcript-cited evidence and rationale.
   - Core rubric dimensions:
     - **Collaboration** (1–5): readiness to coordinate, invite feedback, and align on goals.
     - **Handoff clarity** (1–5): concrete next steps, ownership, deadlines.
     - **Reliability** (1–5): realistic commitments and verification steps.
     - **Communication** (1–5): concise, structured, and appropriate tone.
     - **Initiative** (1–5): proactive issue spotting and mitigation.
   - Include:
     - **Overall** (1–5)
     - **Confidence** (1–5)
     - **Insufficient evidence** flag for low-observability cases.

4. **Aggregation and analysis**
   - Compute per-task and overall means across dimensions.
   - Report per-agent **received** scores (how peers evaluated them).
   - Report per-agent **given** scores (rater leniency/strictness profile).
   - Compute disagreement signals per target (spread/stddev of overall ratings).
   - Track evidence quality metrics (average evidence count, insufficient-evidence rate, average confidence).

5. **Optional extensions**
   - **Role-conditioned evaluators**: different prompts for managers, peers, and cross-functional partners.
   - **Tool usage audit**: include tool call logs in the evaluator context.
   - **Longitudinal checks**: multiple tasks over time to approximate “working history.”
   - **Calibration tasks**: shared anchor transcripts with known quality levels to reduce rater drift.

## Implementation sketch (script in this repo)
- `refcheckarena/refcheckarena_demo.py` provides a minimal runnable example:
  - Defines a complementary three-agent team and a long-form task suite.
  - Runs multi-round collaboration with stage-aware prompts and a shared transcript.
  - Collects ordered peer ratings using transcript-grounded reference checkers.
  - Prints per-task peer checks plus richer aggregates (received/given/agreement/evidence quality).

## Expected outcomes
- Reference checks are grounded in actual collaboration history rather than one-shot outputs.
- Rater disagreement is measurable and interpretable, not hidden by global averaging.
- Aggregates produce actionable diagnostics (who collaborates well, who rates strictly, where evidence is weak).
- Scores can complement benchmark metrics in a broader evaluation suite.
