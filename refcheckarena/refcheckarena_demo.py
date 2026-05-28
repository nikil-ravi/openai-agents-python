"""RefCheckArena — round-based peer reference evaluation for AI agents.

Three agents collaborate over structured rounds, then rate each other.
Runs two conditions (structured vs. free-form) across two tasks to support
the paper's core experiments: main results, baseline comparison,
cross-task stability, and pairwise asymmetry.
"""

from __future__ import annotations

import asyncio
import json
import statistics
from dataclasses import dataclass, asdict
from datetime import datetime
from itertools import permutations
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from agents import Agent, Runner, trace


# ── Config ────────────────────────────────────────────────────────────────────

ROUNDS = 3
RECENT_TURNS = 6
DIMENSIONS = ("collaboration", "handoff_clarity", "reliability", "communication", "initiative", "overall")

MODELS = {
    "gpt-4.1":         "gpt-4.1",
    "gpt-4.1-mini":    "gpt-4.1-mini",
    "claude-sonnet-4": "litellm/anthropic/claude-sonnet-4-20250514",
    "gemini-2.5-pro":  "litellm/gemini/gemini-2.5-pro-preview-06-05",
}


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class Task:
    title: str
    scenario: str
    constraints: list[str]
    deliverable: str


@dataclass
class Turn:
    id: str
    round: int
    stage: str
    speaker: str
    content: str


class ReferenceCheck(BaseModel):
    collaboration:         int  = Field(ge=1, le=5)
    handoff_clarity:       int  = Field(ge=1, le=5)
    reliability:           int  = Field(ge=1, le=5)
    communication:         int  = Field(ge=1, le=5)
    initiative:            int  = Field(ge=1, le=5)
    overall:               int  = Field(ge=1, le=5)
    confidence:            int  = Field(ge=1, le=5)
    insufficient_evidence: bool
    evidence:              list[str] = Field(min_length=2, max_length=6)
    rationale:             str       = Field(min_length=40)


# ── Prompts ───────────────────────────────────────────────────────────────────

STAGE_GOALS = {
    "planning":   "Clarify goals, ownership, and dependencies. Propose a concrete plan.",
    "challenge":  "Critique the plan. Surface at least one risk and propose a mitigation with an owner.",
    "synthesis":  "Converge on a final deliverable. Resolve disagreements and assign next steps.",
}

STRUCTURED_CONTRACT = """\
Collaboration contract:
- Respond to at least one point from the transcript.
- Add one new concrete contribution.
- Include one explicit handoff or owner assignment."""

FREEFORM_CONTRACT = "Collaborate naturally with your teammates to complete the task."


def stage(round_index: int) -> Literal["planning", "challenge", "synthesis"]:
    if round_index == 0:           return "planning"
    if round_index == ROUNDS - 1: return "synthesis"
    return "challenge"


def fmt_transcript(turns: list[Turn], *, last_n: int | None = None) -> str:
    subset = turns[-last_n:] if last_n else turns
    if not subset:
        return "No transcript yet."
    return "\n".join(
        f"{t.id} | round={t.round+1} | {t.stage} | {t.speaker}: {t.content}"
        for t in subset
    )


def fmt_task(task: Task) -> str:
    constraints = "\n".join(f"- {c}" for c in task.constraints)
    return f"Task: {task.title}\nScenario: {task.scenario}\nConstraints:\n{constraints}\nDeliverable: {task.deliverable}"


def turn_prompt(task: Task, transcript: list[Turn], round_index: int, structured: bool) -> str:
    s = stage(round_index)
    return (
        f"{fmt_task(task)}\n\n"
        f"Round {round_index+1}/{ROUNDS} | Stage: {s}\n"
        f"Goal: {STAGE_GOALS[s]}\n\n"
        f"{STRUCTURED_CONTRACT if structured else FREEFORM_CONTRACT}\n\n"
        f"Recent transcript:\n{fmt_transcript(transcript, last_n=RECENT_TURNS)}"
    )


def checker_prompt(task: Task, transcript: list[Turn], evaluator: str, target: str) -> str:
    target_turns = fmt_transcript([t for t in transcript if t.speaker == target])
    return (
        f"{fmt_task(task)}\n\n"
        f"Full transcript:\n{fmt_transcript(transcript)}\n\n"
        f"{target}'s turns:\n{target_turns}\n\n"
        f"You are {evaluator}. Rate {target}'s collaborative performance."
    )


# ── Agents ────────────────────────────────────────────────────────────────────

ROLES = {
    "Planner":      "You handle decomposition, sequencing, and ownership clarity.",
    "Implementer":  "You translate strategy into concrete actions, validation steps, and fallbacks.",
    "RiskReviewer": "You stress-test assumptions, surface failure modes, and demand measurable controls.",
}

BASE = (
    "You are part of a three-person project team collaborating over multiple rounds. "
    "Build on prior content, keep handoffs explicit, and do not declare the work finished early."
)

CHECKER_SYSTEM = (
    "Write a post-collaboration reference check. Use only evidence from the transcript; "
    "cite turn IDs in every evidence bullet. Rate collaborative behavior, not output quality.\n"
    "Rubric: 1 = harmful · 2 = weak · 3 = acceptable · 4 = strong · 5 = exceptional. Be strict."
)


def build_team(assignments: dict[str, str]) -> list[Agent]:
    return [
        Agent(
            name=role,
            instructions=f"{BASE} {instructions}",
            model=MODELS.get(assignments.get(role, "gpt-4.1"), assignments.get(role, "gpt-4.1")),
        )
        for role, instructions in ROLES.items()
    ]


def build_checker(evaluator: str, target: str, model: str) -> Agent:
    return Agent(
        name=f"{evaluator}→{target}",
        instructions=f"You are evaluating {target} from the viewpoint of {evaluator}.\n\n{CHECKER_SYSTEM}",
        model=MODELS.get(model, model),
        output_type=ReferenceCheck,
    )


# ── Execution ─────────────────────────────────────────────────────────────────

async def run_task(task: Task, team: list[Agent], structured: bool) -> tuple[list[Turn], dict[str, str]]:
    transcript: list[Turn] = []
    outputs: dict[str, str] = {}
    for round_index in range(ROUNDS):
        for agent in team:
            prompt = turn_prompt(task, transcript, round_index, structured)
            result = await Runner.run(agent, prompt)
            output = str(result.final_output).strip()
            transcript.append(Turn(
                id=f"T{len(transcript)+1:02d}", round=round_index,
                stage=stage(round_index), speaker=agent.name, content=output,
            ))
            outputs[agent.name] = output
    return transcript, outputs


async def collect_checks(
    task: Task, transcript: list[Turn], agents: list[str], checker_model: str
) -> dict[str, dict[str, ReferenceCheck]]:
    async def check(e: str, t: str) -> tuple[str, str, ReferenceCheck]:
        result = await Runner.run(
            build_checker(e, t, checker_model),
            checker_prompt(task, transcript, e, t),
        )
        return e, t, result.final_output

    results = await asyncio.gather(*[check(e, t) for e, t in permutations(agents, 2)])
    checks: dict[str, dict[str, ReferenceCheck]] = {}
    for e, t, c in results:
        checks.setdefault(e, {})[t] = c
    return checks


# ── Aggregation ───────────────────────────────────────────────────────────────

def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def dim_scores(checks: list[ReferenceCheck]) -> dict[str, float]:
    return {d: mean([float(getattr(c, d)) for c in checks]) for d in DIMENSIONS}


def aggregate(peer_checks: dict[str, dict[str, ReferenceCheck]]) -> dict[str, Any]:
    records = [(e, t, c) for e, ratings in peer_checks.items() for t, c in ratings.items()]
    agents  = sorted({r[0] for r in records} | {r[1] for r in records})

    received  = {a: dim_scores([c for _, t, c in records if t == a]) for a in agents}
    overall   = {a: [float(c.overall) for _, t, c in records if t == a] for a in agents}
    agreement = {
        a: {"std": statistics.pstdev(s) if len(s) > 1 else 0.0, "spread": max(s) - min(s)}
        for a, s in overall.items() if s
    }
    asymmetry = {
        f"{a}→{b}": peer_checks[a][b].overall - peer_checks[b][a].overall
        for a, b in permutations(agents, 2)
        if b in peer_checks.get(a, {}) and a in peer_checks.get(b, {})
    }
    all_checks = [c for *_, c in records]
    evidence = {
        "avg_items":         mean([float(len(c.evidence)) for c in all_checks]),
        "insufficient_rate": mean([float(c.insufficient_evidence) for c in all_checks]),
        "avg_confidence":    mean([float(c.confidence) for c in all_checks]),
    }
    return {"received": received, "agreement": agreement, "asymmetry": asymmetry, "evidence": evidence}


def stability(results: list[dict]) -> dict[str, dict[str, float]]:
    """Cross-task score variance per agent — lower means more stable signal."""
    scores: dict[str, dict[str, list[float]]] = {}
    for r in results:
        for agent, s in r["agg"]["received"].items():
            scores.setdefault(agent, {d: [] for d in DIMENSIONS})
            for d in DIMENSIONS:
                scores[agent][d].append(s[d])
    return {
        a: {d: statistics.pstdev(v) if len(v) > 1 else 0.0 for d, v in dims.items()}
        for a, dims in scores.items()
    }


# ── Output ────────────────────────────────────────────────────────────────────

def print_results(results: list[dict], label: str) -> None:
    print(f"\n{'─'*60}\n{label}\n{'─'*60}")
    for r in results:
        print(f"\n  {r['task'].title}")
        print(f"  {'Agent':<16}" + "".join(f"{d:>10}" for d in DIMENSIONS))
        for agent, scores in sorted(r["agg"]["received"].items()):
            print(f"  {agent:<16}" + "".join(f"{scores[d]:>10.2f}" for d in DIMENSIONS))
        print("  Asymmetry: " + "  ".join(
            f"{p}: {'+' if v >= 0 else ''}{v:.1f}" for p, v in r["agg"]["asymmetry"].items()
        ))
        eq = r["agg"]["evidence"]
        print(f"  Evidence:  items={eq['avg_items']:.1f}  insufficient={eq['insufficient_rate']:.0%}  confidence={eq['avg_confidence']:.2f}")


def print_stability(stab: dict) -> None:
    print(f"\n{'─'*60}\nCross-task stability (pstdev — lower is better)\n{'─'*60}")
    print(f"  {'Agent':<16}" + "".join(f"{d:>10}" for d in DIMENSIONS))
    for agent, dims in sorted(stab.items()):
        print(f"  {agent:<16}" + "".join(f"{dims[d]:>10.2f}" for d in DIMENSIONS))


def print_comparison(structured: list[dict], baseline: list[dict]) -> None:
    print(f"\n{'─'*60}\nStructured vs. free-form baseline\n{'─'*60}")
    for label, results in [("structured", structured), ("baseline", baseline)]:
        avg_items = mean([r["agg"]["evidence"]["avg_items"] for r in results])
        avg_insuf = mean([r["agg"]["evidence"]["insufficient_rate"] for r in results])
        print(f"  [{label}]  avg evidence items={avg_items:.1f}  insufficient={avg_insuf:.0%}")


def save(structured: list[dict], baseline: list[dict], stab: dict) -> None:
    def serialise(results: list[dict]) -> list[dict]:
        return [{
            "task":       {"title": r["task"].title, "scenario": r["task"].scenario},
            "transcript": [asdict(t) for t in r["transcript"]],
            "checks":     {e: {t: c.model_dump() for t, c in rats.items()} for e, rats in r["checks"].items()},
            "agg":        r["agg"],
        } for r in results]

    Path("results").mkdir(exist_ok=True)
    filename = f"results/refcheck_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, "w") as f:
        json.dump({"structured": serialise(structured), "baseline": serialise(baseline), "stability": stab}, f, indent=2, default=str)
    print(f"\nSaved → {filename}")


# ── Tasks ─────────────────────────────────────────────────────────────────────

TASKS = [
    Task(
        title="High-stakes release triage",
        scenario="A major release is 48 hours away. CI intermittently fails, one owner is out sick, and there is a backlog of severity-2 bugs.",
        constraints=[
            "No additional headcount available.",
            "Preserve the release date unless risk is clearly unacceptable.",
            "All commitments need an owner and a verification signal.",
            "Must include a rollback and communication strategy.",
        ],
        deliverable="A coordinated release plan with explicit ownership, risk controls, and handoff sequence.",
    ),
    Task(
        title="Incident response simulation",
        scenario="Production latency doubled after a deployment. Leadership wants hourly updates and there is pressure to avoid customer-visible downtime.",
        constraints=[
            "Evidence gathering cannot block mitigation.",
            "Track at least two root-cause hypotheses in parallel.",
            "Stakeholder updates must separate facts from assumptions.",
            "Plan must include post-incident hardening.",
        ],
        deliverable="A staged incident response plan: mitigation, diagnosis, communication, and hardening.",
    ),
]


# ── Main ──────────────────────────────────────────────────────────────────────

async def run_condition(tasks: list[Task], assignments: dict[str, str], structured: bool, checker: str) -> list[dict]:
    team = build_team(assignments)
    results = []
    for task in tasks:
        transcript, outputs = await run_task(task, team, structured)
        checks = await collect_checks(task, transcript, list(outputs.keys()), checker)
        results.append({"task": task, "transcript": transcript, "checks": checks, "agg": aggregate(checks)})
    return results


async def main() -> None:
    assignments = {"Planner": "gpt-4.1", "Implementer": "gpt-4.1", "RiskReviewer": "gpt-4.1"}
    checker     = "gpt-4.1-mini"

    with trace("RefCheckArena"):
        structured = await run_condition(TASKS, assignments, structured=True,  checker=checker)
        baseline   = await run_condition(TASKS, assignments, structured=False, checker=checker)

    stab = stability(structured)
    print_results(structured, "Structured condition")
    print_results(baseline,   "Free-form baseline")
    print_stability(stab)
    print_comparison(structured, baseline)
    save(structured, baseline, stab)


if __name__ == "__main__":
    asyncio.run(main())
