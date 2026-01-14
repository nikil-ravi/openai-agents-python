from __future__ import annotations

import asyncio
from dataclasses import dataclass
from itertools import combinations
from typing import Iterable

from agents import Agent, Runner, trace


@dataclass
class ReferenceCheck:
    collaboration: int
    handoff_clarity: int
    reliability: int
    communication: int
    initiative: int
    overall: int
    rationale: str


def build_reference_checker(name: str) -> Agent[None]:
    rubric = (
        "Rate the colleague using 1-5 integers for each dimension. "
        "Use 1 for poor and 5 for excellent. Provide an overall rating and a brief rationale."
    )
    instructions = (
        "You are a reference checker evaluating a colleague after working together on a task. "
        "Be direct, specific, and grounded in the provided task context. "
        f"{rubric}"
    )
    return Agent(name=name, instructions=instructions, output_type=ReferenceCheck)


def aggregate_checks(checks: Iterable[ReferenceCheck]) -> dict[str, float]:
    totals = {
        "collaboration": 0,
        "handoff_clarity": 0,
        "reliability": 0,
        "communication": 0,
        "initiative": 0,
        "overall": 0,
    }
    count = 0
    for check in checks:
        totals["collaboration"] += check.collaboration
        totals["handoff_clarity"] += check.handoff_clarity
        totals["reliability"] += check.reliability
        totals["communication"] += check.communication
        totals["initiative"] += check.initiative
        totals["overall"] += check.overall
        count += 1

    if count == 0:
        return {key: 0.0 for key in totals}

    return {key: value / count for key, value in totals.items()}


async def run_team_task(
    task_prompt: str,
    team: list[Agent],
) -> dict[str, object]:
    team_outputs: dict[str, str] = {}
    for agent in team:
        result = await Runner.run(agent, task_prompt)
        team_outputs[agent.name] = result.final_output

    return {
        "task": task_prompt,
        "team_outputs": team_outputs,
    }


async def collect_peer_checks(
    task_prompt: str,
    team_outputs: dict[str, str],
) -> dict[str, dict[str, ReferenceCheck]]:
    checks: dict[str, dict[str, ReferenceCheck]] = {}
    for rater, subject in combinations(team_outputs.keys(), 2):
        for evaluator, target in ((rater, subject), (subject, rater)):
            checker = build_reference_checker(name=f"{evaluator}_rates_{target}")
            context = (
                "Task prompt:\n"
                f"{task_prompt}\n\n"
                "Your output:\n"
                f"{team_outputs[evaluator]}\n\n"
                "Colleague output:\n"
                f"{team_outputs[target]}"
            )
            result = await Runner.run(checker, context)
            checks.setdefault(evaluator, {})[target] = result.final_output
    return checks


async def main() -> None:
    tasks = [
        "Draft a concise project update and hand off next steps to a teammate.",
        "Propose a plan for debugging a flaky test and specify who does what.",
    ]

    team = [
        Agent(
            name="Planner",
            instructions=(
                "You are a concise project planner. Focus on task breakdowns and handoffs."
            ),
        ),
        Agent(
            name="Implementer",
            instructions=(
                "You are an implementation-focused collaborator. Emphasize concrete actions."
            ),
        ),
        Agent(
            name="Reviewer",
            instructions=(
                "You are a reviewer who highlights risks and clarifies communication."
            ),
        ),
    ]

    results: list[dict[str, object]] = []

    with trace("RefCheckArena demo run"):
        for task_prompt in tasks:
            task_result = await run_team_task(task_prompt, team)
            checks = await collect_peer_checks(
                task_prompt,
                task_result["team_outputs"],
            )
            task_result["peer_checks"] = checks
            results.append(task_result)

    for result in results:
        print("\n=== Task ===")
        print(result["task"])
        print("\nTeam outputs:\n")
        for name, output in result["team_outputs"].items():
            print(f"[{name}] {output}")
        print("\nPeer checks:\n")
        for rater, ratings in result["peer_checks"].items():
            for subject, check in ratings.items():
                print(f"{rater} -> {subject}: {check}")

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
