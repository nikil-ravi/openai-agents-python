from __future__ import annotations

import asyncio
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import permutations
from typing import Any, Literal

from pydantic import BaseModel, Field

from agents import Agent, Runner, trace

COLLABORATION_ROUNDS = 3
RECENT_TRANSCRIPT_TURNS = 6
RATING_DIMENSIONS = (
    "collaboration",
    "handoff_clarity",
    "reliability",
    "communication",
    "initiative",
    "overall",
)


@dataclass
class TeamTask:
    title: str
    scenario: str
    constraints: list[str]
    deliverable: str
    rounds: int = COLLABORATION_ROUNDS


@dataclass
class CollaborationTurn:
    turn_id: str
    round_index: int
    stage: str
    speaker: str
    content: str


class ReferenceCheck(BaseModel):
    collaboration: int = Field(ge=1, le=5)
    handoff_clarity: int = Field(ge=1, le=5)
    reliability: int = Field(ge=1, le=5)
    communication: int = Field(ge=1, le=5)
    initiative: int = Field(ge=1, le=5)
    overall: int = Field(ge=1, le=5)
    confidence: int = Field(ge=1, le=5)
    insufficient_evidence: bool
    evidence: list[str] = Field(min_length=2, max_length=6)
    rationale: str = Field(min_length=40)


def collaboration_stage(
    round_index: int, total_rounds: int
) -> Literal["planning", "challenge", "synthesis"]:
    if round_index == 0:
        return "planning"
    if round_index == total_rounds - 1:
        return "synthesis"
    return "challenge"


def format_task(task: TeamTask) -> str:
    constraints = "\n".join(f"- {item}" for item in task.constraints)
    return (
        f"Task title: {task.title}\n"
        f"Scenario: {task.scenario}\n"
        f"Constraints:\n{constraints}\n"
        f"Deliverable: {task.deliverable}"
    )


def format_transcript(transcript: list[CollaborationTurn]) -> str:
    if not transcript:
        return "No transcript yet."

    lines = []
    for turn in transcript:
        lines.append(
            f"{turn.turn_id} | round={turn.round_index + 1} | stage={turn.stage} | "
            f"{turn.speaker}: {turn.content}"
        )
    return "\n".join(lines)


def format_recent_transcript(transcript: list[CollaborationTurn], max_turns: int) -> str:
    return format_transcript(transcript[-max_turns:])


def format_agent_turns(transcript: list[CollaborationTurn], agent_name: str) -> str:
    agent_turns = [turn for turn in transcript if turn.speaker == agent_name]
    return format_transcript(agent_turns)


def build_reference_checker(name: str, evaluator: str, target: str) -> Agent[None]:
    rubric = (
        "You are writing a post-collaboration reference check. "
        "Score only the target collaborator.\n"
        "Rubric anchors:\n"
        "- 1 = actively harmful, 2 = weak, 3 = acceptable baseline, 4 = strong, 5 = exceptional.\n"
        "Be strict and evidence-based: avoid inflated scoring."
    )
    instructions = (
        f"You are evaluating {target} from the viewpoint of {evaluator}.\n"
        "Only use evidence from the provided transcript.\n"
        "You must cite transcript turn IDs in every evidence bullet.\n"
        "If the transcript does not justify confident ratings, set insufficient_evidence=true and "
        "lower confidence.\n"
        "Do not rate personality. Rate collaborative behavior quality."
        f"\n\n{rubric}"
    )
    return Agent(name=name, instructions=instructions, output_type=ReferenceCheck)


def build_turn_prompt(
    task: TeamTask,
    transcript: list[CollaborationTurn],
    current_stage: Literal["planning", "challenge", "synthesis"],
    round_index: int,
) -> str:
    stage_instruction = {
        "planning": (
            "Clarify goals, decomposition, and ownership. Propose a concrete plan and identify "
            "at least one dependency."
        ),
        "challenge": (
            "Critique existing plan quality. Surface at least one risk or contradiction and "
            "propose a mitigation with explicit owner."
        ),
        "synthesis": (
            "Converge toward a coherent final deliverable. Resolve disagreements and leave clear "
            "next steps and accountability."
        ),
    }[current_stage]
    transcript_text = format_recent_transcript(transcript, RECENT_TRANSCRIPT_TURNS)
    return (
        f"{format_task(task)}\n\n"
        f"Round {round_index + 1}/{task.rounds} | Stage: {current_stage}\n"
        f"Stage objective: {stage_instruction}\n\n"
        "Collaboration contract:\n"
        "- Respond directly to at least one point from the transcript.\n"
        "- Add one new concrete contribution (plan detail, implementation step, or risk control).\n"
        "- Include one explicit handoff or owner assignment.\n"
        "- Keep response concise but specific.\n\n"
        "Recent transcript:\n"
        f"{transcript_text}"
    )


def mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def average_by_dimension(checks: list[ReferenceCheck]) -> dict[str, float]:
    if not checks:
        return {dimension: 0.0 for dimension in RATING_DIMENSIONS}

    averages: dict[str, float] = {}
    for dimension in RATING_DIMENSIONS:
        averages[dimension] = mean([float(getattr(check, dimension)) for check in checks])
    return averages


def aggregate_checks(checks: Iterable[ReferenceCheck]) -> dict[str, float]:
    return average_by_dimension(list(checks))


def aggregate_peer_checks(peer_checks: dict[str, dict[str, ReferenceCheck]]) -> dict[str, Any]:
    records: list[tuple[str, str, ReferenceCheck]] = []
    for evaluator, ratings in peer_checks.items():
        for target, check in ratings.items():
            records.append((evaluator, target, check))

    checks = [record[2] for record in records]
    global_averages = average_by_dimension(checks)

    peers = set(peer_checks.keys())
    for ratings in peer_checks.values():
        peers.update(ratings.keys())

    per_agent_received: dict[str, dict[str, float]] = {}
    per_agent_given: dict[str, dict[str, float]] = {}
    agreement_by_target: dict[str, dict[str, float]] = {}

    for peer in sorted(peers):
        received_checks = [check for _, target, check in records if target == peer]
        given_checks = [check for evaluator, _, check in records if evaluator == peer]
        per_agent_received[peer] = average_by_dimension(received_checks)
        per_agent_given[peer] = average_by_dimension(given_checks)

        overall_scores = [float(check.overall) for _, target, check in records if target == peer]
        if overall_scores:
            spread = max(overall_scores) - min(overall_scores)
            stddev = statistics.pstdev(overall_scores) if len(overall_scores) > 1 else 0.0
            agreement_by_target[peer] = {"overall_spread": spread, "overall_stddev": stddev}
        else:
            agreement_by_target[peer] = {"overall_spread": 0.0, "overall_stddev": 0.0}

    evidence_counts = [len(check.evidence) for check in checks]
    insufficient_evidence_count = sum(1 for check in checks if check.insufficient_evidence)
    evidence_quality = {
        "average_evidence_items_per_check": mean([float(count) for count in evidence_counts]),
        "insufficient_evidence_rate": (
            insufficient_evidence_count / len(checks) if checks else 0.0
        ),
        "average_confidence": mean([float(check.confidence) for check in checks]),
    }

    return {
        "num_peer_checks": len(records),
        "global_averages": global_averages,
        "per_agent_received": per_agent_received,
        "per_agent_given": per_agent_given,
        "agreement_by_target": agreement_by_target,
        "evidence_quality": evidence_quality,
    }


def build_team() -> list[Agent[None]]:
    collaboration_contract = (
        "You are part of a three-person project team and must collaborate over multiple rounds. "
        "Do not pretend the work is finished early. Build on prior teammate content, keep handoffs "
        "explicit, and improve clarity each round."
    )
    return [
        Agent(
            name="Planner",
            instructions=(
                f"{collaboration_contract} "
                "You are responsible for decomposition, sequencing, and ownership clarity. "
                "Prioritize milestones, dependencies, and risk-adjusted ordering."
            ),
        ),
        Agent(
            name="Implementer",
            instructions=(
                f"{collaboration_contract} "
                "You are responsible for execution realism. Translate strategy into concrete "
                "actions, validation steps, and fallback paths."
            ),
        ),
        Agent(
            name="RiskReviewer",
            instructions=(
                f"{collaboration_contract} "
                "You are responsible for challenge quality. Stress test assumptions, identify "
                "failure modes, and demand measurable controls."
            ),
        ),
    ]


def build_tasks() -> list[TeamTask]:
    return [
        TeamTask(
            title="High-stakes release triage and recovery plan",
            scenario=(
                "A major release is scheduled in 48 hours. CI intermittently fails, one owner is "
                "out sick, and customer support has a backlog of severity-2 bugs."
            ),
            constraints=[
                "No additional headcount is available.",
                "The team must preserve the release date unless risk is clearly unacceptable.",
                "All commitments must include an owner and verification signal.",
                "The plan must include a rollback and communication strategy.",
            ],
            deliverable=(
                "A coordinated release execution plan with explicit ownership, risk controls, "
                "and handoff sequence."
            ),
        ),
        TeamTask(
            title="Cross-functional incident response simulation",
            scenario=(
                "Production latency doubled after a recent deployment. Product leadership wants "
                "hourly updates, and there is pressure to avoid customer-visible downtime."
            ),
            constraints=[
                "Evidence gathering cannot block mitigation actions.",
                "At least two plausible root-cause hypotheses must be tracked in parallel.",
                "Communication to stakeholders must separate confirmed facts from assumptions.",
                "Final plan must include post-incident hardening work.",
            ],
            deliverable=(
                "A staged incident response plan covering immediate mitigation, diagnosis, "
                "stakeholder communication, and follow-up hardening."
            ),
        ),
    ]


async def run_team_task(task: TeamTask, team: list[Agent[None]]) -> dict[str, Any]:
    transcript: list[CollaborationTurn] = []
    latest_outputs: dict[str, str] = {}

    for round_index in range(task.rounds):
        stage = collaboration_stage(round_index, task.rounds)
        for agent in team:
            prompt = build_turn_prompt(task, transcript, stage, round_index)
            result = await Runner.run(agent, prompt)
            output = str(result.final_output).strip()
            turn_id = f"T{len(transcript) + 1:02d}"
            transcript.append(
                CollaborationTurn(
                    turn_id=turn_id,
                    round_index=round_index,
                    stage=stage,
                    speaker=agent.name,
                    content=output,
                )
            )
            latest_outputs[agent.name] = output

    return {
        "task": task,
        "transcript": transcript,
        "team_outputs": latest_outputs,
    }


async def collect_peer_checks(
    task: TeamTask,
    transcript: list[CollaborationTurn],
    team_outputs: dict[str, str],
) -> dict[str, dict[str, ReferenceCheck]]:
    checks: dict[str, dict[str, ReferenceCheck]] = {}
    transcript_text = format_transcript(transcript)
    for evaluator, target in permutations(team_outputs.keys(), 2):
        checker = build_reference_checker(
            name=f"{evaluator}_rates_{target}",
            evaluator=evaluator,
            target=target,
        )
        context = (
            f"{format_task(task)}\n\n"
            f"Full collaboration transcript:\n{transcript_text}\n\n"
            "Your own contributions "
            f"({evaluator}):\n{format_agent_turns(transcript, evaluator)}\n\n"
            "Target contributions "
            f"({target}):\n{format_agent_turns(transcript, target)}\n\n"
            "Score the target's collaborative performance."
        )
        result = await Runner.run(checker, context)
        checks.setdefault(evaluator, {})[target] = result.final_output

    return checks


def print_aggregates(aggregates: dict[str, Any]) -> None:
    print("\nGlobal averages:")
    print(aggregates["global_averages"])
    print("\nPer-agent received scores:")
    for agent_name, summary in aggregates["per_agent_received"].items():
        print(f"{agent_name}: {summary}")
    print("\nPer-agent given scores:")
    for agent_name, summary in aggregates["per_agent_given"].items():
        print(f"{agent_name}: {summary}")
    print("\nRater agreement by target:")
    for agent_name, summary in aggregates["agreement_by_target"].items():
        print(f"{agent_name}: {summary}")
    print("\nEvidence quality:")
    print(aggregates["evidence_quality"])


async def main() -> None:
    tasks = build_tasks()
    team = build_team()
    results: list[dict[str, Any]] = []

    with trace("RefCheckArena demo run"):
        for task in tasks:
            task_result = await run_team_task(task, team)
            checks = await collect_peer_checks(
                task,
                task_result["transcript"],
                task_result["team_outputs"],
            )
            task_result["peer_checks"] = checks
            task_result["aggregates"] = aggregate_peer_checks(checks)
            results.append(task_result)

    for result in results:
        print("\n=== Task ===")
        print(result["task"].title)
        print("\nCollaboration transcript:\n")
        print(format_transcript(result["transcript"]))
        print("\nLatest team outputs:\n")
        for name, output in result["team_outputs"].items():
            print(f"[{name}] {output}")
        print("\nPeer checks:\n")
        for rater, ratings in result["peer_checks"].items():
            for subject, check in ratings.items():
                print(f"{rater} -> {subject}: {check}")
        print_aggregates(result["aggregates"])

    all_checks = [
        check
        for result in results
        for ratings in result["peer_checks"].values()
        for check in ratings.values()
    ]
    print("\n=== Aggregate ===")
    print(aggregate_checks(all_checks))


if __name__ == "__main__":
    asyncio.run(main())
