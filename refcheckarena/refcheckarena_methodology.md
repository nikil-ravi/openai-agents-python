# RefCheckArena methodology sketch grounded in the OpenAI Agents SDK

## Core idea
RefCheckArena evaluates a set of agents by collecting structured, rubric-based reference checks from their peers after working on shared tasks. This mirrors human reference checks: evaluators focus on collaboration quality, reliability, and communication, not just task correctness.

## SDK-grounded building blocks
- **Team agents**: multiple `Agent` instances with complementary roles (planner, implementer, reviewer).
- **Reference checkers**: lightweight evaluator agents instantiated per pairwise check.
- **Execution**: `Runner.run(...)` to produce each agent’s task response and to run each reference checker.
- **Structured scoring**: `output_type` with a dataclass (e.g., `ReferenceCheck`) to enforce numeric ratings and rationale.
- **Tracing**: `trace(...)` to group the full evaluation run and allow later inspection of all subcalls.
- **Message plumbing**: `TResponseInputItem` and `ItemHelpers` to construct inputs and extract model outputs for reference checkers.

## Proposed evaluation protocol
1. **Task suite selection**
   - Assemble a set of tasks that exercise: coordination, delegation, handoff clarity, and error recovery.
   - Use realistic prompts (e.g., “Draft a project plan, then hand off to a teammate with clear next steps.”).

2. **Team execution**
   - For each task, run each team agent with `Runner.run(agent, prompt)`.
   - Capture each agent’s output for downstream checks.

3. **Reference checks (peer ratings)**
   - For each pair of agents, collect bidirectional ratings.
   - Each reference checker scores a colleague on a rubric, for example:
     - **Collaboration** (1–5): readiness to coordinate, invite feedback, and align on goals.
     - **Handoff clarity** (1–5): concrete next steps, ownership, deadlines.
     - **Reliability** (1–5): realistic commitments and verification steps.
     - **Communication** (1–5): concise, structured, and appropriate tone.
     - **Initiative** (1–5): proactive issue spotting and mitigation.

4. **Aggregation and analysis**
   - Compute per-task and overall averages across all peer checks.
   - Compare variance across raters (signal of evaluator agreement).
   - Correlate with benchmark scores to quantify complementary information.

5. **Optional extensions**
   - **Role-conditioned evaluators**: different prompts for managers, peers, and cross-functional partners.
   - **Tool usage audit**: include tool call logs in the evaluator context.
   - **Longitudinal checks**: multiple tasks over time to approximate “working history.”

## Implementation sketch (script in this repo)
- `refcheckarena/refcheckarena_demo.py` provides a minimal runnable example:
  - Defines a small team of agents and runs a short task suite.
  - Collects bidirectional peer ratings for each task.
  - Prints peer checks and an aggregate score across all ratings.

## Expected outcomes
- Reference checks surface interaction quality signals not captured by static benchmarks.
- Disagreement among reference checkers highlights ambiguous or inconsistent behavior.
- Aggregated scores can be used alongside benchmark metrics in a composite evaluation suite.
