from __future__ import annotations

import pytest

from refcheckarena.refcheckarena_demo import (
    CollaborationTurn,
    ReferenceCheck,
    aggregate_checks,
    aggregate_peer_checks,
    collaboration_stage,
    format_transcript,
)


def make_check(
    collaboration: int,
    handoff_clarity: int,
    reliability: int,
    communication: int,
    initiative: int,
    overall: int,
    confidence: int,
    *,
    insufficient_evidence: bool = False,
    evidence: list[str] | None = None,
) -> ReferenceCheck:
    return ReferenceCheck(
        collaboration=collaboration,
        handoff_clarity=handoff_clarity,
        reliability=reliability,
        communication=communication,
        initiative=initiative,
        overall=overall,
        confidence=confidence,
        insufficient_evidence=insufficient_evidence,
        evidence=evidence or ["T01: grounded point", "T02: grounded point"],
        rationale=(
            "This score is based on observed planning quality, explicit handoffs, "
            "and risk handling across the transcript turns."
        ),
    )


def test_collaboration_stage_returns_expected_labels() -> None:
    assert collaboration_stage(0, 3) == "planning"
    assert collaboration_stage(1, 3) == "challenge"
    assert collaboration_stage(2, 3) == "synthesis"
    assert collaboration_stage(0, 1) == "planning"


def test_format_transcript_renders_turn_metadata() -> None:
    transcript = [
        CollaborationTurn(
            turn_id="T01",
            round_index=0,
            stage="planning",
            speaker="Planner",
            content="We should split this into three milestones.",
        ),
        CollaborationTurn(
            turn_id="T02",
            round_index=0,
            stage="planning",
            speaker="Implementer",
            content="I will own milestone one and report verification evidence.",
        ),
    ]

    rendered = format_transcript(transcript)

    assert "T01 | round=1 | stage=planning | Planner:" in rendered
    assert "T02 | round=1 | stage=planning | Implementer:" in rendered


def test_aggregate_checks_averages_core_dimensions() -> None:
    checks = [
        make_check(4, 3, 5, 4, 4, 4, 4),
        make_check(2, 3, 2, 3, 2, 2, 3),
    ]

    result = aggregate_checks(checks)

    assert result["collaboration"] == pytest.approx(3.0)
    assert result["handoff_clarity"] == pytest.approx(3.0)
    assert result["overall"] == pytest.approx(3.0)


def test_aggregate_peer_checks_reports_received_given_and_agreement() -> None:
    peer_checks = {
        "Planner": {
            "Implementer": make_check(4, 4, 4, 4, 4, 4, 4),
            "RiskReviewer": make_check(3, 3, 3, 3, 3, 3, 3, insufficient_evidence=True),
        },
        "Implementer": {
            "Planner": make_check(5, 4, 5, 4, 4, 5, 4),
            "RiskReviewer": make_check(2, 3, 2, 3, 2, 2, 2),
        },
        "RiskReviewer": {
            "Planner": make_check(4, 4, 4, 4, 5, 4, 4),
            "Implementer": make_check(3, 3, 3, 3, 3, 3, 3),
        },
    }

    aggregates = aggregate_peer_checks(peer_checks)

    assert aggregates["num_peer_checks"] == 6
    assert aggregates["global_averages"]["overall"] == pytest.approx(3.5)
    assert aggregates["per_agent_received"]["Planner"]["overall"] == pytest.approx(4.5)
    assert aggregates["per_agent_given"]["Planner"]["overall"] == pytest.approx(3.5)
    assert aggregates["agreement_by_target"]["RiskReviewer"]["overall_spread"] == pytest.approx(1.0)
    assert aggregates["evidence_quality"]["insufficient_evidence_rate"] == pytest.approx(1 / 6)
