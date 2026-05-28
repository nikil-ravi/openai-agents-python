# RefCheckArena

## Core idea

RefCheckArena evaluates AI agents as collaborators, not just task-solvers. After a team of agents works together on a shared task, each agent rates every peer on six dimensions — collaboration, handoff clarity, reliability, communication, initiative, and overall — using a structured, evidence-grounded schema. This mirrors human reference checks: evaluators report on what it was like to work alongside a colleague, not just whether the final output was correct.

The result is a per-agent collaboration profile that is orthogonal to benchmark task scores and captures signal that static evaluations cannot: does this agent hand off work clearly? Does it follow through on commitments? Does it surface risks proactively or wait to be asked?

---

## How it works

### 1. Team and roles

Three agents collaborate under complementary role assignments:

- **Planner** — decomposition, sequencing, and ownership clarity.
- **Implementer** — translating strategy into concrete actions, validation steps, and fallback paths.
- **RiskReviewer** — stress-testing assumptions, surfacing failure modes, and demanding measurable controls.

Each agent is initialized with a shared collaboration contract that prohibits declaring work finished early and requires explicit handoffs each round.

### 2. Collaboration phase

Each task runs for three rounds with stage-typed prompts:

| Stage | Round | Goal |
|---|---|---|
| Planning | 1 | Clarify goals, ownership, and dependencies |
| Challenge | middle | Critique the plan, surface risks, assign mitigations |
| Synthesis | last | Converge on a deliverable, resolve disagreements, assign next steps |

Every agent takes one turn per round. The prompt includes the task specification, the stage goal, the collaboration contract, and the six most recent transcript turns. All turns are appended to a shared transcript with stable IDs (`T01`, `T02`, …) used later as citation anchors by referees.

Two conditions are run in parallel:
- **Structured** — full collaboration contract (respond to a prior point, add a concrete contribution, include a handoff or owner assignment).
- **Free-form baseline** — single neutral instruction, no contract. Used to test whether the structured environment produces richer reference evidence.

### 3. Reference phase

After each task, every ordered agent pair $(e, t)$ produces one structured reference check: $e$ evaluates $t$ in a fresh context with no memory of the collaboration. The referee receives the full transcript and the target's turns extracted separately, and must produce a `ReferenceCheck` with the following fields:

| Field | Type | Description |
|---|---|---|
| `collaboration` | int 1–5 | Quality of joint problem-solving |
| `handoff_clarity` | int 1–5 | Completeness and usability of handoffs |
| `reliability` | int 1–5 | Following through on commitments |
| `communication` | int 1–5 | Clarity and proactivity of updates |
| `initiative` | int 1–5 | Appropriate autonomy vs. over-asking |
| `overall` | int 1–5 | Holistic collaboration quality |
| `confidence` | int 1–5 | Referee's confidence in own ratings |
| `insufficient_evidence` | bool | True if transcript is too thin to rate |
| `evidence` | list[str] | 2–6 transcript-cited evidence bullets |
| `rationale` | str | ≥40-character narrative justification |

Referees must cite turn IDs in every evidence bullet. Checks flagged `insufficient_evidence=True` are excluded from per-agent score averages but retained in evidence quality reporting. All six checks per task are collected in parallel.

### 4. Aggregation

For each agent $t$ and dimension $d$, we compute:

- **Mean received score** $\bar{s}^d_t$ — how peers rated the agent on each dimension (excluding insufficient-evidence checks).
- **Inter-referee disagreement** $\sigma_t$ — standard deviation of overall scores across referees. High disagreement indicates the agent's behavior was interpreted differently by different roles.
- **Pairwise asymmetry** $\Delta_{e,t} = s^\text{overall}_{e \to t} - s^\text{overall}_{t \to e}$ — does $e$ rate $t$ higher than $t$ rates $e$? Systematic asymmetry reveals role-structural effects invisible to benchmarks.
- **Cross-task stability** — pstdev of $\bar{s}^d_t$ across tasks. Low variance means the instrument is measuring something stable about the agent rather than task-specific transcript events.
- **Evidence quality** — average evidence items per check, insufficient-evidence rate, and average confidence. Used to compare structured vs. free-form conditions.

---

## Task suite

Tasks are chosen to require all three roles and to have clear decision points where planning, execution, and risk concerns genuinely conflict.

| Task | Scenario | Deliverable |
|---|---|---|
| High-stakes release triage | Major release in 48h, CI failing, owner sick, severity-2 backlog | Coordinated execution plan with ownership, risk controls, rollback strategy |
| Incident response simulation | Production latency doubled, leadership wants hourly updates | Staged response plan: mitigation, diagnosis, communication, hardening |

---

## Running the evaluation

```python
# Default: gpt-4.1 team, gpt-4.1-mini checker, both conditions, both tasks
python refcheck_simple.py

# Cross-model experiment: assign different models to different roles
assignments = {
    "Planner":      "claude-sonnet-4",
    "Implementer":  "gpt-4.1",
    "RiskReviewer": "gpt-4.1",
}
```

Results are saved to `results/refcheck_<timestamp>.json` containing raw transcripts, all reference checks, per-task aggregates, cross-task stability, and the structured vs. free-form comparison.

---

## Output

The console prints:

- Per-agent received scores across all six dimensions, per task and condition
- Pairwise asymmetry table
- Cross-task stability (pstdev per agent per dimension)
- Structured vs. free-form evidence quality comparison

---

## Extensions

- **Cross-model teams** — assign different model families to different roles via `model_assignments` and compare collaboration profiles across model combinations.
- **Role ablations** — run the same underlying model in each of the three roles to separate role-structural effects from model-intrinsic behavior.
- **Partial transcript conditions** — administer reference checks with first-person-only or blind transcripts to measure how much referees confabulate vs. genuinely report observed behavior.
- **Cross-model referee panels** — use disjoint model families as checkers to reduce intra-model bias.
- **Calibration tasks** — include anchor transcripts with known quality levels to detect and correct rater drift across runs.
- **Longitudinal checks** — run the same team across many tasks over time to approximate a working history.

---

## Repository structure

```
refcheck_simple.py   # Main evaluation script
results/             # JSON output from each run
```
