"""Focused checks for the RefCheckArena experimental runner."""

from __future__ import annotations

import asyncio

from refcheckarena.refcheckarena_arena import (
    AGENTS,
    DIMENSIONS,
    TASKS,
    FakeModelClient,
    ReferenceCheck,
    aggregate,
    build_arg_parser,
    ordered_reference_pairs,
    resolve_agent_models,
    run_structured_task,
    state_from_dict,
    state_to_dict,
)


def test_fake_structured_run_creates_reference_signal() -> None:
    state = asyncio.run(
        run_structured_task(
            TASKS[0],
            FakeModelClient(),
            model_name="fake",
        )
    )

    health = state.health_metrics()
    assert health["turn_count"] >= 30
    assert health["all_roles_contributed"] is True
    assert health["critic_rejection_count"] >= 4
    assert health["max_revision_depth"] >= 1
    assert health["handoff_count"] >= 30
    assert health["handoffs_by_kind"]["review_request"] >= 16
    assert health["handoffs_by_kind"]["revision_request"] >= 4
    assert health["handoffs_by_kind"]["phase_acceptance"] >= 4
    assert health["open_handoff_count"] == 0
    assert health["handoff_completion_rate"] == 1.0
    assert len(state.approved_artifacts()) >= 4


def test_reference_pairs_include_orchestrator() -> None:
    pairs = ordered_reference_pairs([agent.name for agent in AGENTS])

    assert ("Orchestrator", "Researcher") in pairs
    assert ("Researcher", "Orchestrator") in pairs
    assert len(pairs) == len(AGENTS) * (len(AGENTS) - 1)


def test_aggregate_excludes_insufficient_evidence_scores() -> None:
    valid = ReferenceCheck(
        collaboration=1,
        handoff_clarity=1,
        reliability=1,
        communication=1,
        initiative=1,
        overall=1,
        confidence=4,
        insufficient_evidence=False,
        evidence=["T001 shows a concrete behavior.", "T002 confirms the pattern."],
        rationale="The valid check should be the only one used in received means.",
    )
    insufficient = ReferenceCheck(
        collaboration=5,
        handoff_clarity=5,
        reliability=5,
        communication=5,
        initiative=5,
        overall=5,
        confidence=1,
        insufficient_evidence=True,
        evidence=["T003 is too thin.", "T004 is also too thin."],
        rationale="This check is retained for evidence metrics but excluded from scores.",
    )

    result = aggregate(
        {
            "Researcher": {"Orchestrator": valid},
            "Reviewer": {"Orchestrator": insufficient},
        },
        valid_turn_ids={"T001", "T002", "T003", "T004"},
    )

    for dimension in DIMENSIONS:
        assert result["received"]["Orchestrator"][dimension] == 1.0
    assert result["evidence"]["insufficient_rate"] == 0.5


def test_resolve_agent_models_supports_cost_stressed_profiles() -> None:
    parser = build_arg_parser()
    args = parser.parse_args(
        [
            "--model-profile",
            "cost_stressed",
            "--model",
            "frontier",
            "--specialist-model",
            "small",
            "--reviewer-model",
            "reviewer",
            "--critic-model",
            "critic",
            "--orchestrator-model",
            "manager",
            "--agent-models",
            '{"TechLead": "override"}',
        ]
    )

    models = resolve_agent_models(args)

    assert models["Orchestrator"] == "manager"
    assert models["Researcher"] == "small"
    assert models["FinancialAnalyst"] == "small"
    assert models["TechLead"] == "override"
    assert models["ContentWriter"] == "small"
    assert models["Reviewer"] == "reviewer"
    assert models["Critic"] == "critic"


def test_state_roundtrip_preserves_health_metrics() -> None:
    state = asyncio.run(
        run_structured_task(
            TASKS[0],
            FakeModelClient(),
            model_name="fake",
            context_mode="compact",
        )
    )

    restored = state_from_dict(state_to_dict(state))

    assert restored.context_mode == "compact"
    assert restored.health_metrics() == state.health_metrics()
    assert len(restored.turns) == len(state.turns)
