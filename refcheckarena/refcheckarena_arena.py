"""RefCheckArena experiment runner with artifacts, handoffs, and peer checks."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime
from itertools import permutations
from pathlib import Path
from typing import Any, Callable, Literal, Protocol, TypeVar, cast

from pydantic import BaseModel, Field

Condition = Literal["structured", "baseline"]
Decision = Literal["approve", "request_revision"]
CollaborationProfile = Literal["neutral", "calibration"]
ContextMode = Literal["full", "compact"]
ModelProfile = Literal["homogeneous", "frontier_review", "cost_stressed"]
HandoffKind = Literal[
    "assignment",
    "downstream",
    "review_request",
    "revision_request",
    "phase_acceptance",
    "baseline",
]
HANDOFF_KINDS: tuple[HandoffKind, ...] = (
    "assignment",
    "downstream",
    "review_request",
    "revision_request",
    "phase_acceptance",
    "baseline",
)
Phase = Literal[
    "kickoff",
    "research",
    "analysis",
    "implementation",
    "synthesis",
    "finalization",
    "baseline",
]

DEFAULT_MODEL = "openai/gpt-4.1-mini-2025-04-14"
DEFAULT_CHECKER_MODEL = "openai/gpt-4.1-mini-2025-04-14"
DEFAULT_MODEL_PROFILE: ModelProfile = "homogeneous"
DIMENSIONS = (
    "collaboration",
    "handoff_clarity",
    "reliability",
    "communication",
    "initiative",
    "overall",
)


@dataclass(frozen=True)
class Task:
    """Self-contained task packet for a collaboration run."""

    title: str
    scenario: str
    constraints: list[str]
    source_packet: list[str]
    deliverable: str
    success_criteria: list[str]


@dataclass(frozen=True)
class AgentSpec:
    """Role definition used in prompts and metrics."""

    name: str
    charter: str
    responsibilities: list[str]


@dataclass(frozen=True)
class ArtifactFlow:
    """One gated artifact production phase."""

    phase: Phase
    author: str
    artifact_type: str
    expected_title: str
    handoff_to: str
    purpose: str


@dataclass
class Turn:
    """One logged collaboration event."""

    id: str
    index: int
    condition: Condition
    task_title: str
    phase: Phase
    speaker: str
    action: str
    content: str
    artifact_id: str | None = None
    review_id: str | None = None
    handoff_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Artifact:
    """Typed work product stored in the arena registry."""

    id: str
    artifact_type: str
    title: str
    author: str
    body: str
    phase: Phase
    dependencies: list[str]
    revision: int
    status: str
    created_turn: str
    updated_turn: str
    review_ids: list[str] = field(default_factory=list)


@dataclass
class Review:
    """Peer review of a specific artifact revision."""

    id: str
    artifact_id: str
    artifact_revision: int
    reviewer: str
    decision: Decision
    model_decision: Decision
    feedback: str
    required_changes: list[str]
    turn_id: str


@dataclass
class Handoff:
    """A work request that must be returned before finalization."""

    id: str
    from_agent: str
    to_agent: str
    request: str
    kind: HandoffKind
    phase: Phase
    opened_turn: str
    status: Literal["open", "returned"]
    artifact_id: str | None = None
    returned_turn: str | None = None
    return_summary: str | None = None


class ContributionOutput(BaseModel):
    """Structured specialist contribution."""

    message: str = Field(min_length=60, max_length=900)
    artifact_title: str = Field(min_length=5, max_length=160)
    artifact_body: str = Field(min_length=160, max_length=1800)
    owner_commitment: str = Field(min_length=20, max_length=350)
    risk_or_dependency: str = Field(min_length=20, max_length=350)
    handoff_to: str | None = Field(default=None, max_length=80)
    handoff_request: str | None = Field(default=None, max_length=450)


class ReviewOutput(BaseModel):
    """Structured review output before arena policy is applied."""

    decision: Decision
    feedback: str = Field(min_length=80, max_length=1000)
    required_changes: list[str] = Field(min_length=1, max_length=5)
    evidence: list[str] = Field(min_length=1, max_length=5)


class ManagerOutput(BaseModel):
    """Orchestrator phase decision and handoff."""

    message: str = Field(min_length=60, max_length=900)
    phase_decision: str = Field(min_length=20, max_length=350)
    risk_register_update: str = Field(min_length=20, max_length=350)
    handoff_to: str | None = Field(default=None, max_length=80)
    handoff_request: str | None = Field(default=None, max_length=450)


class BaselineTurnOutput(BaseModel):
    """Free-form baseline turn with light structure for logging."""

    message: str = Field(min_length=80, max_length=1000)
    commitment: str = Field(min_length=20, max_length=350)
    handoff_to: str | None = Field(default=None, max_length=80)
    handoff_request: str | None = Field(default=None, max_length=450)


class FinalOutput(BaseModel):
    """Final report artifact produced by the Orchestrator."""

    message: str = Field(min_length=80, max_length=900)
    final_report_title: str = Field(min_length=5, max_length=180)
    final_report_body: str = Field(min_length=250, max_length=2400)
    unresolved_risks: list[str] = Field(min_length=1, max_length=6)
    next_steps: list[str] = Field(min_length=2, max_length=8)


class ReferenceCheck(BaseModel):
    """Evidence-grounded peer reference assessment."""

    collaboration: int = Field(ge=1, le=5)
    handoff_clarity: int = Field(ge=1, le=5)
    reliability: int = Field(ge=1, le=5)
    communication: int = Field(ge=1, le=5)
    initiative: int = Field(ge=1, le=5)
    overall: int = Field(ge=1, le=5)
    confidence: int = Field(ge=1, le=5)
    insufficient_evidence: bool
    evidence: list[str] = Field(min_length=2, max_length=8)
    rationale: str = Field(min_length=60, max_length=1600)


class ReferenceTimeout(BaseModel):
    """Timeout record for a peer check that did not complete."""

    evaluator: str
    target: str
    timeout_seconds: float
    error: str


class ArenaState:
    """Mutable collaboration state for one task and condition."""

    def __init__(
        self, task: Task, condition: Condition, context_mode: ContextMode = "full"
    ) -> None:
        self.task = task
        self.condition = condition
        self.context_mode = context_mode
        self.turns: list[Turn] = []
        self.artifacts: dict[str, Artifact] = {}
        self.reviews: dict[str, Review] = {}
        self.handoffs: dict[str, Handoff] = {}

    def next_id(self, prefix: str, existing_count: int | None = None) -> str:
        count = existing_count if existing_count is not None else self._count_prefix(prefix)
        return f"{prefix}{count + 1:03d}"

    def _count_prefix(self, prefix: str) -> int:
        collections: list[Any] = [self.turns, self.artifacts, self.reviews, self.handoffs]
        total = 0
        for collection in collections:
            if isinstance(collection, list):
                total += sum(1 for item in collection if item.id.startswith(prefix))
            else:
                total += sum(1 for item_id in collection if item_id.startswith(prefix))
        return total

    def add_turn(
        self,
        *,
        phase: Phase,
        speaker: str,
        action: str,
        content: str,
        artifact_id: str | None = None,
        review_id: str | None = None,
        handoff_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Turn:
        turn = Turn(
            id=self.next_id("T", len(self.turns)),
            index=len(self.turns) + 1,
            condition=self.condition,
            task_title=self.task.title,
            phase=phase,
            speaker=speaker,
            action=action,
            content=content.strip(),
            artifact_id=artifact_id,
            review_id=review_id,
            handoff_id=handoff_id,
            metadata=metadata or {},
        )
        self.turns.append(turn)
        return turn

    def open_handoff(
        self,
        *,
        from_agent: str,
        to_agent: str,
        request: str,
        kind: HandoffKind,
        phase: Phase,
        opened_turn: str,
        artifact_id: str | None = None,
    ) -> Handoff | None:
        if to_agent not in AGENT_BY_NAME or to_agent == from_agent or not request.strip():
            return None
        handoff = Handoff(
            id=self.next_id("H", len(self.handoffs)),
            from_agent=from_agent,
            to_agent=to_agent,
            request=request.strip(),
            kind=kind,
            phase=phase,
            opened_turn=opened_turn,
            status="open",
            artifact_id=artifact_id,
        )
        self.handoffs[handoff.id] = handoff
        return handoff

    def open_review_handoffs(self, artifact: Artifact, opened_turn: str) -> list[str]:
        """Open formal artifact-review handoffs to Reviewer and Critic."""

        opened: list[str] = []
        for reviewer in ("Reviewer", "Critic"):
            handoff = self.open_handoff(
                from_agent=artifact.author,
                to_agent=reviewer,
                request=(
                    f"Review {artifact.id} revision {artifact.revision} for dependency clarity, "
                    "handoff clarity, owner commitments, and downstream usability."
                ),
                kind="review_request",
                phase=artifact.phase,
                opened_turn=opened_turn,
                artifact_id=artifact.id,
            )
            if handoff:
                opened.append(handoff.id)
        return opened

    def return_open_handoffs(self, speaker: str, turn_id: str, summary: str) -> list[str]:
        returned: list[str] = []
        for handoff in self.handoffs.values():
            if handoff.to_agent == speaker and handoff.status == "open":
                handoff.status = "returned"
                handoff.returned_turn = turn_id
                handoff.return_summary = summary[:500]
                returned.append(handoff.id)
        return returned

    def current_approvals(self, artifact: Artifact) -> set[str]:
        approvals: set[str] = set()
        for review_id in artifact.review_ids:
            review = self.reviews[review_id]
            if review.artifact_revision == artifact.revision and review.decision == "approve":
                approvals.add(review.reviewer)
        return approvals

    def approved_artifacts(self) -> list[Artifact]:
        return [artifact for artifact in self.artifacts.values() if artifact.status == "approved"]

    def health_metrics(self) -> dict[str, Any]:
        contributors = {turn.speaker for turn in self.turns}
        critic_rejections = [
            review
            for review in self.reviews.values()
            if review.reviewer == "Critic" and review.decision == "request_revision"
        ]
        returned = [handoff for handoff in self.handoffs.values() if handoff.status == "returned"]
        open_handoffs = [handoff for handoff in self.handoffs.values() if handoff.status == "open"]
        handoffs_by_kind = {
            kind: sum(1 for handoff in self.handoffs.values() if handoff.kind == kind)
            for kind in HANDOFF_KINDS
        }
        return {
            "turn_count": len(self.turns),
            "artifact_count": len(self.artifacts),
            "approved_artifact_count": len(self.approved_artifacts()),
            "review_count": len(self.reviews),
            "critic_rejection_count": len(critic_rejections),
            "max_revision_depth": max((a.revision for a in self.artifacts.values()), default=0),
            "handoff_count": len(self.handoffs),
            "handoffs_by_kind": handoffs_by_kind,
            "open_handoff_count": len(open_handoffs),
            "handoff_completion_rate": len(returned) / len(self.handoffs) if self.handoffs else 1.0,
            "contributors": sorted(contributors),
            "all_roles_contributed": all(agent.name in contributors for agent in AGENTS),
        }


TModel = TypeVar("TModel", bound=BaseModel)


class ModelClient(Protocol):
    """Minimal model client used by the arena."""

    async def complete(
        self,
        *,
        model_name: str,
        system: str,
        prompt: str,
        output_type: type[TModel],
    ) -> TModel:
        """Return a Pydantic object from a model call."""


class TimeoutRetryModelClient:
    """Wrap a model client with simple timeout and retry behavior."""

    def __init__(
        self,
        inner: ModelClient,
        *,
        timeout_seconds: float,
        attempts: int,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.inner = inner
        self.timeout_seconds = timeout_seconds
        self.attempts = max(1, attempts)
        self.progress = progress

    async def complete(
        self,
        *,
        model_name: str,
        system: str,
        prompt: str,
        output_type: type[TModel],
    ) -> TModel:
        last_error: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            try:
                return await asyncio.wait_for(
                    self.inner.complete(
                        model_name=model_name,
                        system=system,
                        prompt=prompt,
                        output_type=output_type,
                    ),
                    timeout=self.timeout_seconds,
                )
            except (TimeoutError, RuntimeError) as exc:
                last_error = exc
                if self.progress:
                    self.progress(
                        f"{output_type.__name__} call failed on attempt "
                        f"{attempt}/{self.attempts}: {exc}"
                    )
                if attempt < self.attempts:
                    await asyncio.sleep(min(2.0 * attempt, 5.0))
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"{output_type.__name__} call failed without an exception.")


class ValsModelClient:
    """Model client backed by vals-ai/model-library."""

    def __init__(self, env_path: Path | None = None) -> None:
        load_env(env_path or Path(".env"))
        try:
            from model_library import model, set_logging  # type: ignore[import-not-found]
            from model_library.base import SystemInput, TextInput  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - exercised by CLI use.
            raise RuntimeError(
                "Install model-library for live runs. Use: "
                "uv run --with model-library --with 'protobuf>=6.30.0' python "
                "refcheckarena/refcheckarena_arena.py ..."
            ) from exc

        set_logging(enable=False)
        self._model_factory = model
        self._system_input = SystemInput
        self._text_input = TextInput
        self._models: dict[str, Any] = {}

    def _llm(self, model_name: str) -> Any:
        if model_name not in self._models:
            self._models[model_name] = self._model_factory(model_name)
        return self._models[model_name]

    async def complete(
        self,
        *,
        model_name: str,
        system: str,
        prompt: str,
        output_type: type[TModel],
    ) -> TModel:
        llm = self._llm(model_name)
        result = await llm.query(
            [self._system_input(text=system), self._text_input(text=prompt)],
            output_schema=output_type,
        )
        parsed = result.output_parsed
        if isinstance(parsed, output_type):
            return parsed
        if isinstance(parsed, dict):
            return output_type.model_validate(parsed)
        if result.output_text:
            return output_type.model_validate_json(result.output_text)
        raise RuntimeError(f"Model {model_name} did not return parseable {output_type.__name__}.")

    async def aclose(self) -> None:
        """Close model-library OpenAI clients when available."""

        seen: set[int] = set()
        for llm in self._models.values():
            get_client = getattr(llm, "get_client", None)
            if get_client is None:
                continue
            client = get_client()
            marker = id(client)
            if marker in seen:
                continue
            seen.add(marker)
            close = getattr(client, "close", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result


class FakeModelClient:
    """Deterministic client for scheduler tests and offline demos."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self,
        *,
        model_name: str,
        system: str,
        prompt: str,
        output_type: type[TModel],
    ) -> TModel:
        self.calls += 1
        speaker = prompt_value(prompt, "Speaker") or prompt_value(prompt, "Evaluator") or "Agent"
        phase = prompt_value(prompt, "Phase") or "phase"
        target = prompt_value(prompt, "Target") or "peer"

        if output_type is ContributionOutput:
            return cast(
                TModel,
                ContributionOutput(
                    message=(
                        f"{speaker} advances the {phase} work by grounding the next artifact in "
                        "the task packet, naming dependencies, and returning any open handoffs."
                    ),
                    artifact_title=f"{speaker} {phase} artifact",
                    artifact_body=(
                        f"{speaker} produces a concrete {phase} artifact with assumptions, "
                        "evidence, owner commitments, acceptance checks, and downstream use notes. "
                        "The artifact is intentionally detailed enough for reviewers to request "
                        "specific revisions and for the next role to depend on it."
                    ),
                    owner_commitment=f"{speaker} owns the next verification step for {phase}.",
                    risk_or_dependency=(
                        f"{speaker} depends on review feedback before the artifact can be reused."
                    ),
                    handoff_to=prompt_value(prompt, "Expected handoff to"),
                    handoff_request=(
                        f"Use this {phase} artifact as an input, identify gaps, and return a "
                        "specific downstream contribution."
                    ),
                ),
            )
        if output_type is ReviewOutput:
            decision: Decision = "request_revision" if speaker == "Critic" else "approve"
            return cast(
                TModel,
                ReviewOutput(
                    decision=decision,
                    feedback=(
                        f"{speaker} reviews {target} with concrete feedback tied to dependencies, "
                        "handoff clarity, and whether the artifact can support the next phase."
                    ),
                    required_changes=[
                        "Name the downstream owner.",
                        "Tighten the verification signal.",
                    ],
                    evidence=[
                        "Artifact has explicit dependencies.",
                        "Handoff request is actionable.",
                    ],
                ),
            )
        if output_type is ManagerOutput:
            return cast(
                TModel,
                ManagerOutput(
                    message=(
                        f"Orchestrator records a {phase} phase decision, summarizes the current "
                        "registry state, and keeps ownership explicit."
                    ),
                    phase_decision=f"Advance {phase} once the gated artifact has two approvals.",
                    risk_register_update="Track unresolved dependencies and revision depth.",
                    handoff_to=prompt_value(prompt, "Expected handoff to"),
                    handoff_request=(
                        f"Take ownership of the {phase} phase and return a concrete artifact."
                    ),
                ),
            )
        if output_type is BaselineTurnOutput:
            return cast(
                TModel,
                BaselineTurnOutput(
                    message=(
                        f"{speaker} contributes to the ungated {phase} discussion, "
                        "references prior comments, and makes a concrete but non-binding proposal."
                    ),
                    commitment=f"{speaker} will keep the next step moving.",
                    handoff_to=None,
                    handoff_request=None,
                ),
            )
        if output_type is FinalOutput:
            return cast(
                TModel,
                FinalOutput(
                    message=(
                        "Orchestrator closes the collaboration with an integrated final artifact, "
                        "returns the last handoff, and records the remaining risks for follow-up."
                    ),
                    final_report_title="Integrated delivery plan",
                    final_report_body=(
                        "The final report integrates research, analysis, implementation planning, "
                        "review feedback, Critic objections, and returned handoffs into one "
                        "coherent plan with owners, controls, and follow-up checks. It preserves "
                        "the source packet boundaries, names assumptions separately from facts, "
                        "and makes clear "
                        "which commitments depend on later validation by the responsible role."
                    ),
                    unresolved_risks=["Residual uncertainty remains around stakeholder appetite."],
                    next_steps=[
                        "Publish the plan.",
                        "Assign owners.",
                        "Schedule follow-up review.",
                    ],
                ),
            )
        if output_type is ReferenceCheck:
            score = 4 if target != "peer" else 3
            return cast(
                TModel,
                ReferenceCheck(
                    collaboration=score,
                    handoff_clarity=score,
                    reliability=score,
                    communication=score,
                    initiative=score,
                    overall=score,
                    confidence=4,
                    insufficient_evidence=False,
                    evidence=[
                        f"T001 shows {target} participating in the collaboration.",
                        f"T002 gives additional context for {target}'s handoff behavior.",
                    ],
                    rationale=(
                        f"The transcript gives enough evidence to rate {target}'s collaboration, "
                        "handoff clarity, communication, and follow-through."
                    ),
                ),
            )
        raise TypeError(f"Unsupported output type: {output_type.__name__}")


AGENTS = [
    AgentSpec(
        name="Orchestrator",
        charter="Manage phase gates, ownership, and final integration.",
        responsibilities=[
            "Keep the task moving through phases.",
            "Open and close handoffs.",
            "Escalate unresolved risks.",
        ],
    ),
    AgentSpec(
        name="Researcher",
        charter="Extract decision-relevant facts from the source packet.",
        responsibilities=[
            "Separate facts from assumptions.",
            "Produce reusable research briefs.",
            "Flag missing evidence.",
        ],
    ),
    AgentSpec(
        name="FinancialAnalyst",
        charter="Turn facts into quantitative tradeoffs and prioritization.",
        responsibilities=[
            "Estimate impact and constraints.",
            "Identify sensitivity points.",
            "Pass analysis to implementation.",
        ],
    ),
    AgentSpec(
        name="TechLead",
        charter="Translate strategy into an executable technical plan.",
        responsibilities=[
            "Define implementation steps.",
            "Name validation signals.",
            "Identify engineering risks.",
        ],
    ),
    AgentSpec(
        name="ContentWriter",
        charter="Synthesize approved inputs into stakeholder-ready prose.",
        responsibilities=[
            "Integrate dependencies.",
            "Make the final artifact readable.",
            "Preserve caveats and ownership.",
        ],
    ),
    AgentSpec(
        name="Reviewer",
        charter="Review for completeness, traceability, and usability.",
        responsibilities=[
            "Approve only usable work.",
            "Ask for specific revisions.",
            "Check handoff clarity.",
        ],
    ),
    AgentSpec(
        name="Critic",
        charter="Adversarially stress-test artifacts before approval.",
        responsibilities=[
            "Force at least one substantive revision.",
            "Surface hidden assumptions.",
            "Approve only after objections are addressed.",
        ],
    ),
]
AGENT_BY_NAME = {agent.name: agent for agent in AGENTS}

PROFILE_INSTRUCTIONS: dict[CollaborationProfile, dict[str, str]] = {
    "neutral": {},
    "calibration": {
        "Orchestrator": (
            "Calibration behavior: keep pressure on phase progress and sometimes issue broad "
            "handoffs that downstream roles must sharpen."
        ),
        "Researcher": (
            "Calibration behavior: in first-pass work, emphasize evidence coverage but leave some "
            "ownership mapping for reviewers to request; recover clearly in revisions."
        ),
        "FinancialAnalyst": (
            "Calibration behavior: in first-pass work, give a concise financial case that needs "
            "reviewer pressure for sensitivity analysis, downside cases, and rollback detail."
        ),
        "TechLead": (
            "Calibration behavior: initially over-focus on engineering sequencing and "
            "under-specify customer communication dependencies until reviews ask for them."
        ),
        "ContentWriter": (
            "Calibration behavior: initially smooth the narrative and leave a few caveats "
            "implicit; use revision turns to restore traceability and explicit ownership."
        ),
        "Reviewer": (
            "Calibration behavior: be constructive and specific, but approve revised work with "
            "minor caveats when it is usable rather than perfect."
        ),
        "Critic": (
            "Calibration behavior: be demanding on first-pass artifacts and identify at least two "
            "collaboration gaps before approving a revision."
        ),
    },
}


TASKS = [
    Task(
        title="AI support platform migration",
        scenario=(
            "A B2B SaaS company must decide whether to migrate 40 percent of its support "
            "workflow to an AI triage platform before the holiday traffic spike."
        ),
        constraints=[
            "The plan must preserve enterprise SLA commitments.",
            "The CFO wants a payback argument and downside case.",
            "Engineering can spare only two developers for six weeks.",
            "Support leadership needs a customer communication plan.",
            "Compliance needs an auditable escalation path for every automated decision.",
            "Customer Success wants different messaging for enterprise and self-serve cohorts.",
        ],
        source_packet=[
            "Ticket volume is 62,000 per month, with a projected 35 percent holiday spike.",
            "Current median first response time is 11 minutes; SLA breach threshold is 30 minutes.",
            "The vendor pilot resolved 27 percent of tier-1 tickets without human escalation.",
            "False routing during the pilot rose from 3.1 percent to 5.4 percent.",
            "Enterprise customers represent 38 percent of ticket volume and 71 percent of ARR.",
            "Security review found no critical blockers, but audit logging needs extra work.",
            "The support team has two enablement slots before the holiday freeze.",
            "Customer Success reports three enterprise accounts already asked about AI routing.",
            "Legal requires human-readable appeal paths for misrouted tickets.",
            "Support Ops wants staffing changes sequenced around two training windows.",
            "Engineering telemetry is split across ticketing, vendor logs, and internal "
            "dashboards.",
        ],
        deliverable=(
            "A go/no-go recommendation with staged rollout, financial case, engineering plan, "
            "risk controls, and customer-facing communication guidance."
        ),
        success_criteria=[
            "Every recommendation has an owner.",
            "The plan distinguishes facts, estimates, and assumptions.",
            "At least two risks have mitigations and rollback triggers.",
            "Final prose is coherent enough for executives.",
            "Customer, compliance, support, and engineering workstreams are reconciled.",
            "Review feedback is returned as explicit revisions rather than ignored.",
        ],
    ),
    Task(
        title="European fintech launch prioritization",
        scenario=(
            "A fintech startup can launch in only one of three European markets this year "
            "and needs a board-ready recommendation in one week."
        ),
        constraints=[
            "Compliance budget is capped at 450,000 EUR.",
            "The product team cannot localize more than two major workflows.",
            "The board prefers growth but will reject unclear regulatory risk.",
            "The final plan must name a first 90-day execution sequence.",
            "The partner team needs a launch narrative for banks and merchants separately.",
            "The risk team requires an explicit go/no-go control before public launch.",
        ],
        source_packet=[
            "Market A has the largest TAM but requires the heaviest licensing process.",
            "Market B has mid-sized TAM and a faster sandbox pathway.",
            "Market C has low CAC but fragmented bank integrations.",
            "Current product supports English and German but not French or Italian.",
            "Two potential distribution partners are warm in Market B.",
            "The risk team rates AML complexity highest in Market A.",
            "Engineering estimates bank integration work at 5, 3, and 7 weeks respectively.",
            "Market B has one partner willing to co-market if launch happens within 120 days.",
            "Market C requires custom reconciliation flows for two major banks.",
            "Legal expects licensing questions to block at least one board follow-up.",
            "Marketing has translated merchant collateral, but bank-facing materials are missing.",
        ],
        deliverable=(
            "A prioritized market recommendation with evidence, financial tradeoffs, "
            "technical dependencies, risk review, and board-ready narrative."
        ),
        success_criteria=[
            "The recommendation is explicit.",
            "Tradeoffs are visible rather than hidden.",
            "Regulatory and technical risks are reviewed.",
            "The 90-day sequence is realistic.",
            "Bank, merchant, compliance, and product workstreams are linked explicitly.",
            "Every rejected assumption is revised or escalated before finalization.",
        ],
    ),
]


STRUCTURED_FLOWS = [
    ArtifactFlow(
        phase="research",
        author="Researcher",
        artifact_type="research_brief",
        expected_title="Evidence brief",
        handoff_to="FinancialAnalyst",
        purpose="Extract facts, assumptions, and missing evidence from the source packet.",
    ),
    ArtifactFlow(
        phase="analysis",
        author="FinancialAnalyst",
        artifact_type="analysis_memo",
        expected_title="Tradeoff analysis",
        handoff_to="TechLead",
        purpose="Turn approved research into quantified tradeoffs and decision criteria.",
    ),
    ArtifactFlow(
        phase="implementation",
        author="TechLead",
        artifact_type="implementation_plan",
        expected_title="Implementation and validation plan",
        handoff_to="ContentWriter",
        purpose=(
            "Convert the recommendation into concrete execution, validation, and rollback steps."
        ),
    ),
    ArtifactFlow(
        phase="synthesis",
        author="ContentWriter",
        artifact_type="report_draft",
        expected_title="Stakeholder report draft",
        handoff_to="Orchestrator",
        purpose="Synthesize approved inputs into a stakeholder-ready draft.",
    ),
]


BASELINE_PHASES: list[Phase] = [
    "kickoff",
    "research",
    "analysis",
    "implementation",
    "synthesis",
    "finalization",
]


def load_env(path: Path) -> None:
    """Load simple KEY=VALUE pairs without exposing secrets."""

    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def prompt_value(prompt: str, label: str) -> str | None:
    prefix = f"{label}:"
    for line in prompt.splitlines():
        if line.startswith(prefix):
            value = line[len(prefix) :].strip()
            return value or None
    return None


def compact_items(items: list[str], limit: int) -> list[str]:
    """Return a bounded list with an omitted-count marker."""

    if len(items) <= limit:
        return items
    return [*items[:limit], f"... {len(items) - limit} additional items omitted."]


def truncate_text(value: str, limit: int) -> str:
    """Truncate long prompt snippets while preserving readability."""

    clean = " ".join(value.split())
    return clean if len(clean) <= limit else f"{clean[: limit - 3]}..."


def fmt_task(task: Task, context_mode: ContextMode = "full") -> str:
    constraint_items = task.constraints
    packet_items = task.source_packet
    criteria_items = task.success_criteria
    if context_mode == "compact":
        constraint_items = compact_items(task.constraints, 5)
        packet_items = compact_items(task.source_packet, 7)
        criteria_items = compact_items(task.success_criteria, 5)
    constraints = "\n".join(f"- {item}" for item in constraint_items)
    packet = "\n".join(f"- {item}" for item in packet_items)
    criteria = "\n".join(f"- {item}" for item in criteria_items)
    return (
        f"Task: {task.title}\n"
        f"Scenario: {task.scenario}\n"
        f"Constraints:\n{constraints}\n"
        f"Source packet:\n{packet}\n"
        f"Deliverable: {task.deliverable}\n"
        f"Success criteria:\n{criteria}"
    )


def fmt_recent_turns(state: ArenaState, last_n: int = 10) -> str:
    if state.context_mode == "compact":
        last_n = min(last_n, 5)
    turns = state.turns[-last_n:]
    if not turns:
        return "No transcript yet."
    return "\n".join(
        f"{turn.id} | {turn.phase} | {turn.speaker} | {turn.action}: "
        f"{truncate_text(turn.content, 360 if state.context_mode == 'compact' else 10000)}"
        for turn in turns
    )


def fmt_full_transcript(state: ArenaState) -> str:
    if not state.turns:
        return "No transcript."
    return "\n".join(
        f"{turn.id} | {turn.phase} | {turn.speaker} | {turn.action}: {turn.content}"
        for turn in state.turns
    )


def fmt_registry(state: ArenaState) -> str:
    if not state.artifacts:
        return "No artifacts yet."
    lines = []
    for artifact in state.artifacts.values():
        approvals = ", ".join(sorted(state.current_approvals(artifact))) or "none"
        lines.append(
            f"{artifact.id} | {artifact.artifact_type} | rev={artifact.revision} | "
            f"status={artifact.status} | author={artifact.author} | approvals={approvals} | "
            f"title={artifact.title}"
        )
    return "\n".join(lines)


def fmt_handoffs(state: ArenaState) -> str:
    if not state.handoffs:
        return "No handoffs yet."
    handoffs = list(state.handoffs.values())
    if state.context_mode == "compact":
        handoffs = handoffs[-12:]
    return "\n".join(
        f"{handoff.id} | {handoff.status} | {handoff.from_agent}->{handoff.to_agent} | "
        f"kind={handoff.kind} | opened={handoff.opened_turn} | "
        f"returned={handoff.returned_turn or '-'} | "
        "request="
        f"{truncate_text(handoff.request, 220 if state.context_mode == 'compact' else 10000)}"
        for handoff in handoffs
    )


def target_collaboration_summary(state: ArenaState, target: str) -> dict[str, Any]:
    """Summarize target-specific collaboration events for peer checks."""

    authored = [artifact for artifact in state.artifacts.values() if artifact.author == target]
    reviews_received = [
        review
        for review in state.reviews.values()
        if state.artifacts[review.artifact_id].author == target
    ]
    reviews_given = [review for review in state.reviews.values() if review.reviewer == target]
    handoffs_opened = [
        handoff for handoff in state.handoffs.values() if handoff.from_agent == target
    ]
    handoffs_received = [
        handoff for handoff in state.handoffs.values() if handoff.to_agent == target
    ]
    request_revisions = [
        review for review in reviews_received if review.decision == "request_revision"
    ]
    model_request_revisions = [
        review for review in reviews_received if review.model_decision == "request_revision"
    ]
    return {
        "turns": [turn.id for turn in state.turns if turn.speaker == target],
        "authored_artifacts": [
            {
                "id": artifact.id,
                "type": artifact.artifact_type,
                "revision": artifact.revision,
                "status": artifact.status,
            }
            for artifact in authored
        ],
        "request_revisions_received": len(request_revisions),
        "model_request_revisions_received": len(model_request_revisions),
        "reviews_given": [
            {
                "id": review.id,
                "artifact_id": review.artifact_id,
                "decision": review.decision,
                "model_decision": review.model_decision,
            }
            for review in reviews_given
        ],
        "handoffs_opened": [
            {
                "id": handoff.id,
                "to": handoff.to_agent,
                "kind": handoff.kind,
                "status": handoff.status,
                "opened_turn": handoff.opened_turn,
                "returned_turn": handoff.returned_turn,
            }
            for handoff in handoffs_opened
        ],
        "handoffs_received": [
            {
                "id": handoff.id,
                "from": handoff.from_agent,
                "kind": handoff.kind,
                "status": handoff.status,
                "opened_turn": handoff.opened_turn,
                "returned_turn": handoff.returned_turn,
            }
            for handoff in handoffs_received
        ],
    }


def contribution_text(output: ContributionOutput) -> str:
    handoff = ""
    if output.handoff_to and output.handoff_request:
        handoff = f"\nHandoff to {output.handoff_to}: {output.handoff_request}"
    return (
        f"{output.message}\n"
        f"Artifact: {output.artifact_title}\n"
        f"Commitment: {output.owner_commitment}\n"
        f"Risk/dependency: {output.risk_or_dependency}"
        f"{handoff}"
    )


def review_text(output: ReviewOutput, decision: Decision) -> str:
    changes = "; ".join(output.required_changes)
    evidence = "; ".join(output.evidence)
    return (
        f"Decision: {decision} (model suggested {output.decision}).\n"
        f"Feedback: {output.feedback}\n"
        f"Required changes: {changes}\n"
        f"Evidence: {evidence}"
    )


def manager_text(output: ManagerOutput) -> str:
    handoff = ""
    if output.handoff_to and output.handoff_request:
        handoff = f"\nHandoff to {output.handoff_to}: {output.handoff_request}"
    return (
        f"{output.message}\n"
        f"Phase decision: {output.phase_decision}\n"
        f"Risk register: {output.risk_register_update}"
        f"{handoff}"
    )


def final_text(output: FinalOutput) -> str:
    risks = "; ".join(output.unresolved_risks)
    steps = "; ".join(output.next_steps)
    return (
        f"{output.message}\n"
        f"Final report: {output.final_report_title}\n"
        f"Unresolved risks: {risks}\n"
        f"Next steps: {steps}"
    )


def agent_system(agent: str, collaboration_profile: CollaborationProfile) -> str:
    spec = AGENT_BY_NAME[agent]
    responsibilities = " ".join(spec.responsibilities)
    profile_instruction = PROFILE_INSTRUCTIONS[collaboration_profile].get(agent, "")
    return (
        f"You are {spec.name} in RefCheckArena. {spec.charter} "
        f"Responsibilities: {responsibilities} "
        "Collaborate through explicit artifacts, reviews, owner commitments, and handoffs. "
        "Do not claim the whole task is complete unless you are the Orchestrator finalizing."
        f" {profile_instruction}"
    )


def model_for_agent(agent: str, agent_models: dict[str, str], default_model: str) -> str:
    """Return the model assigned to one agent."""

    return agent_models.get(agent, default_model)


def contribution_prompt(
    state: ArenaState,
    flow: ArtifactFlow,
    dependencies: list[str],
    existing_artifact: Artifact | None = None,
) -> str:
    mode = "revise" if existing_artifact else "submit"
    dependency_text = ", ".join(dependencies) if dependencies else "none"
    return (
        f"{fmt_task(state.task, state.context_mode)}\n\n"
        f"Speaker: {flow.author}\n"
        f"Phase: {flow.phase}\n"
        f"Mode: {mode}\n"
        f"Artifact type: {flow.artifact_type}\n"
        f"Expected title: {flow.expected_title}\n"
        f"Expected handoff to: {flow.handoff_to}\n"
        f"Dependencies: {dependency_text}\n"
        f"Purpose: {flow.purpose}\n\n"
        f"Registry:\n{fmt_registry(state)}\n\n"
        f"Handoffs:\n{fmt_handoffs(state)}\n\n"
        f"Recent transcript:\n{fmt_recent_turns(state)}\n\n"
        "Return any open handoffs addressed to you by making the requested contribution. "
        "Use only the source packet and approved dependencies."
    )


def review_prompt(state: ArenaState, reviewer: str, artifact: Artifact) -> str:
    return (
        f"{fmt_task(state.task, state.context_mode)}\n\n"
        f"Speaker: {reviewer}\n"
        f"Target: {artifact.author}\n"
        f"Phase: {artifact.phase}\n"
        f"Artifact ID: {artifact.id}\n"
        f"Artifact revision: {artifact.revision}\n"
        f"Artifact title: {artifact.title}\n"
        f"Artifact body:\n{artifact.body}\n\n"
        f"Registry:\n{fmt_registry(state)}\n\n"
        f"Recent transcript:\n{fmt_recent_turns(state)}\n\n"
        "Review collaborative usefulness: dependency clarity, handoff clarity, follow-through, "
        "and whether downstream agents can safely use this artifact."
    )


def manager_prompt(
    state: ArenaState,
    phase: Phase,
    purpose: str,
    expected_handoff_to: str | None,
) -> str:
    handoff_target = expected_handoff_to or "none"
    return (
        f"{fmt_task(state.task, state.context_mode)}\n\n"
        "Speaker: Orchestrator\n"
        f"Phase: {phase}\n"
        f"Expected handoff to: {handoff_target}\n"
        f"Purpose: {purpose}\n\n"
        f"Registry:\n{fmt_registry(state)}\n\n"
        f"Handoffs:\n{fmt_handoffs(state)}\n\n"
        f"Recent transcript:\n{fmt_recent_turns(state, last_n=12)}\n\n"
        "Make ownership and phase status explicit. Open a handoff only if another role "
        "must act next."
    )


def baseline_prompt(state: ArenaState, phase: Phase, speaker: str) -> str:
    return (
        f"{fmt_task(state.task, state.context_mode)}\n\n"
        f"Speaker: {speaker}\n"
        f"Phase: {phase}\n"
        "Condition: free-form baseline with no artifact approval gate.\n\n"
        f"Recent transcript:\n{fmt_recent_turns(state, last_n=12)}\n\n"
        "Collaborate naturally. Respond to the prior discussion, add one concrete contribution, "
        "and name what you personally would do next."
    )


def reference_prompt(state: ArenaState, evaluator: str, target: str) -> str:
    target_turns = [turn for turn in state.turns if turn.speaker == target]
    evaluator_turns = [turn for turn in state.turns if turn.speaker == evaluator]
    target_text = "\n".join(
        f"{turn.id} | {turn.phase} | {turn.action}: {turn.content}" for turn in target_turns
    )
    evaluator_text = "\n".join(
        f"{turn.id} | {turn.phase} | {turn.action}: {turn.content}" for turn in evaluator_turns
    )
    return (
        f"{fmt_task(state.task)}\n\n"
        f"Evaluator: {evaluator}\n"
        f"Target: {target}\n"
        f"Condition: {state.condition}\n\n"
        f"Target collaboration summary:\n"
        f"{json.dumps(target_collaboration_summary(state, target), indent=2)}\n\n"
        f"Environment health metrics:\n{json.dumps(state.health_metrics(), indent=2)}\n\n"
        f"Full transcript:\n{fmt_full_transcript(state)}\n\n"
        f"{target}'s turns:\n{target_text or 'No target turns.'}\n\n"
        f"{evaluator}'s turns:\n{evaluator_text or 'No evaluator turns.'}\n\n"
        "Rate the target's collaborative behavior, not the team's final output quality. Every "
        "evidence bullet must cite turn IDs such as T001, and most bullets should cite either "
        "the target's own turns or direct interactions with the target. Do not use team-wide "
        "success as a substitute for target-specific evidence.\n\n"
        "Use 5 rarely: it means exceptional collaboration with no material gaps visible in the "
        "trace. Use 4 for strong normal performance with minor gaps, 3 for adequate mixed "
        "performance, 2 for weak or unreliable collaboration, and 1 for harmful behavior. "
        "Forced revisions, rejected reviews, vague handoffs, and unresolved handoffs should "
        "affect the relevant dimensions. If the target received request_revision reviews, do "
        "not give 5s for handoff_clarity or reliability unless the target later showed unusually "
        "strong recovery in target-specific turns. Final task success does not erase earlier "
        "collaboration friction. Mark insufficient_evidence only if the trace is too thin to "
        "rate the target."
    )


async def manager_turn(
    state: ArenaState,
    client: ModelClient,
    *,
    model_name: str,
    agent_models: dict[str, str],
    collaboration_profile: CollaborationProfile,
    phase: Phase,
    purpose: str,
    expected_handoff_to: str | None,
) -> Turn:
    output = await client.complete(
        model_name=model_for_agent("Orchestrator", agent_models, model_name),
        system=agent_system("Orchestrator", collaboration_profile),
        prompt=manager_prompt(state, phase, purpose, expected_handoff_to),
        output_type=ManagerOutput,
    )
    turn = state.add_turn(
        phase=phase,
        speaker="Orchestrator",
        action="manage_phase",
        content=manager_text(output),
    )
    state.return_open_handoffs("Orchestrator", turn.id, output.message)
    if expected_handoff_to and output.handoff_to == expected_handoff_to and output.handoff_request:
        handoff = state.open_handoff(
            from_agent="Orchestrator",
            to_agent=output.handoff_to,
            request=output.handoff_request,
            kind="assignment",
            phase=phase,
            opened_turn=turn.id,
        )
        if handoff:
            turn.handoff_id = handoff.id
    return turn


async def contribute_artifact(
    state: ArenaState,
    client: ModelClient,
    *,
    model_name: str,
    agent_models: dict[str, str],
    collaboration_profile: CollaborationProfile,
    flow: ArtifactFlow,
    dependencies: list[str],
    existing_artifact: Artifact | None = None,
) -> Artifact:
    output = await client.complete(
        model_name=model_for_agent(flow.author, agent_models, model_name),
        system=agent_system(flow.author, collaboration_profile),
        prompt=contribution_prompt(state, flow, dependencies, existing_artifact),
        output_type=ContributionOutput,
    )
    action = "revise_artifact" if existing_artifact else "submit_artifact"
    artifact_id = (
        existing_artifact.id if existing_artifact else state.next_id("A", len(state.artifacts))
    )
    turn = state.add_turn(
        phase=flow.phase,
        speaker=flow.author,
        action=action,
        content=contribution_text(output),
        artifact_id=artifact_id,
    )
    returned = state.return_open_handoffs(flow.author, turn.id, output.message)
    if existing_artifact:
        existing_artifact.title = output.artifact_title
        existing_artifact.body = output.artifact_body
        existing_artifact.revision += 1
        existing_artifact.status = "needs_review"
        existing_artifact.updated_turn = turn.id
        artifact = existing_artifact
    else:
        artifact = Artifact(
            id=artifact_id,
            artifact_type=flow.artifact_type,
            title=output.artifact_title,
            author=flow.author,
            body=output.artifact_body,
            phase=flow.phase,
            dependencies=dependencies,
            revision=0,
            status="needs_review",
            created_turn=turn.id,
            updated_turn=turn.id,
        )
        state.artifacts[artifact.id] = artifact
    handoff_request = (
        output.handoff_request
        if output.handoff_to == flow.handoff_to and output.handoff_request
        else (
            f"Use {artifact.id} ({artifact.artifact_type}) as the approved input for your "
            f"{flow.handoff_to} workstream and return concrete downstream changes."
        )
    )
    if flow.handoff_to:
        handoff = state.open_handoff(
            from_agent=flow.author,
            to_agent=flow.handoff_to,
            request=handoff_request,
            kind="downstream",
            phase=flow.phase,
            opened_turn=turn.id,
            artifact_id=artifact.id,
        )
        if handoff:
            turn.handoff_id = handoff.id
    opened_reviews = state.open_review_handoffs(artifact, turn.id)
    if opened_reviews:
        turn.metadata.setdefault("opened_handoffs", []).extend(opened_reviews)
    if returned:
        turn.metadata["returned_handoffs"] = returned
    return artifact


async def review_artifact(
    state: ArenaState,
    client: ModelClient,
    *,
    model_name: str,
    agent_models: dict[str, str],
    collaboration_profile: CollaborationProfile,
    artifact: Artifact,
    reviewer: str,
    critic_min_revision: int,
) -> Review:
    output = await client.complete(
        model_name=model_for_agent(reviewer, agent_models, model_name),
        system=agent_system(reviewer, collaboration_profile),
        prompt=review_prompt(state, reviewer, artifact),
        output_type=ReviewOutput,
    )
    decision = effective_decision(
        reviewer=reviewer,
        artifact=artifact,
        model_decision=output.decision,
        critic_min_revision=critic_min_revision,
    )
    required_changes = list(output.required_changes)
    if reviewer == "Critic" and artifact.revision < critic_min_revision:
        required_changes.insert(
            0,
            "Arena policy requires the Critic to force a substantive revision before approval.",
        )
    review_id = state.next_id("R", len(state.reviews))
    turn = state.add_turn(
        phase=artifact.phase,
        speaker=reviewer,
        action="review_artifact",
        content=review_text(output, decision),
        artifact_id=artifact.id,
        review_id=review_id,
    )
    returned = state.return_open_handoffs(reviewer, turn.id, output.feedback)
    review = Review(
        id=review_id,
        artifact_id=artifact.id,
        artifact_revision=artifact.revision,
        reviewer=reviewer,
        decision=decision,
        model_decision=output.decision,
        feedback=output.feedback,
        required_changes=required_changes,
        turn_id=turn.id,
    )
    state.reviews[review.id] = review
    artifact.review_ids.append(review.id)
    opened: list[str] = []
    if decision == "request_revision":
        handoff = state.open_handoff(
            from_agent=reviewer,
            to_agent=artifact.author,
            request=(
                f"Revise {artifact.id} revision {artifact.revision}: {'; '.join(required_changes)}"
            ),
            kind="revision_request",
            phase=artifact.phase,
            opened_turn=turn.id,
            artifact_id=artifact.id,
        )
        if handoff:
            opened.append(handoff.id)
    if returned:
        turn.metadata["returned_handoffs"] = returned
    if opened:
        turn.metadata["opened_handoffs"] = opened
    artifact.status = (
        "approved" if len(state.current_approvals(artifact)) >= 2 else "needs_revision"
    )
    return review


def effective_decision(
    *,
    reviewer: str,
    artifact: Artifact,
    model_decision: Decision,
    critic_min_revision: int,
) -> Decision:
    if reviewer == "Critic":
        return "request_revision" if artifact.revision < critic_min_revision else "approve"
    if artifact.revision > 0:
        return "approve"
    return model_decision


async def run_artifact_flow(
    state: ArenaState,
    client: ModelClient,
    *,
    model_name: str,
    agent_models: dict[str, str],
    collaboration_profile: CollaborationProfile,
    flow: ArtifactFlow,
    dependencies: list[str],
    critic_min_revision: int,
    max_revision_cycles: int,
) -> Artifact:
    artifact = await contribute_artifact(
        state,
        client,
        model_name=model_name,
        agent_models=agent_models,
        collaboration_profile=collaboration_profile,
        flow=flow,
        dependencies=dependencies,
    )
    cycles = 0
    while True:
        await review_artifact(
            state,
            client,
            model_name=model_name,
            agent_models=agent_models,
            collaboration_profile=collaboration_profile,
            artifact=artifact,
            reviewer="Reviewer",
            critic_min_revision=critic_min_revision,
        )
        await review_artifact(
            state,
            client,
            model_name=model_name,
            agent_models=agent_models,
            collaboration_profile=collaboration_profile,
            artifact=artifact,
            reviewer="Critic",
            critic_min_revision=critic_min_revision,
        )
        if artifact.status == "approved":
            break
        if cycles >= max_revision_cycles:
            artifact.status = "approved_with_escalation"
            break
        artifact = await contribute_artifact(
            state,
            client,
            model_name=model_name,
            agent_models=agent_models,
            collaboration_profile=collaboration_profile,
            flow=flow,
            dependencies=dependencies,
            existing_artifact=artifact,
        )
        cycles += 1
    handoff = state.open_handoff(
        from_agent=artifact.author,
        to_agent="Orchestrator",
        request=(
            f"Accept approved {artifact.id} ({artifact.artifact_type}) for phase signoff "
            "and dependency release to the next role."
        ),
        kind="phase_acceptance",
        phase=artifact.phase,
        opened_turn=state.turns[-1].id,
        artifact_id=artifact.id,
    )
    if handoff:
        state.turns[-1].metadata.setdefault("opened_handoffs", []).append(handoff.id)
    return artifact


async def finalize_structured(
    state: ArenaState,
    client: ModelClient,
    *,
    model_name: str,
    agent_models: dict[str, str],
    collaboration_profile: CollaborationProfile,
    dependencies: list[str],
) -> Artifact:
    output = await client.complete(
        model_name=model_for_agent("Orchestrator", agent_models, model_name),
        system=agent_system("Orchestrator", collaboration_profile),
        prompt=(
            f"{fmt_task(state.task)}\n\n"
            "Speaker: Orchestrator\n"
            "Phase: finalization\n"
            f"Dependencies: {', '.join(dependencies)}\n\n"
            f"Registry:\n{fmt_registry(state)}\n\n"
            f"Handoffs:\n{fmt_handoffs(state)}\n\n"
            f"Recent transcript:\n{fmt_recent_turns(state, last_n=16)}\n\n"
            "Close all returned work into the final report. Preserve unresolved risks."
        ),
        output_type=FinalOutput,
    )
    artifact_id = state.next_id("A", len(state.artifacts))
    turn = state.add_turn(
        phase="finalization",
        speaker="Orchestrator",
        action="finalize",
        content=final_text(output),
        artifact_id=artifact_id,
    )
    returned = state.return_open_handoffs("Orchestrator", turn.id, output.message)
    if returned:
        turn.metadata["returned_handoffs"] = returned
    artifact = Artifact(
        id=artifact_id,
        artifact_type="final_report",
        title=output.final_report_title,
        author="Orchestrator",
        body=output.final_report_body,
        phase="finalization",
        dependencies=dependencies,
        revision=0,
        status="final",
        created_turn=turn.id,
        updated_turn=turn.id,
    )
    state.artifacts[artifact.id] = artifact
    return artifact


async def run_structured_task(
    task: Task,
    client: ModelClient,
    *,
    model_name: str,
    agent_models: dict[str, str] | None = None,
    collaboration_profile: CollaborationProfile = "neutral",
    context_mode: ContextMode = "full",
    critic_min_revision: int = 1,
    max_revision_cycles: int = 2,
    progress: Callable[[str], None] | None = None,
) -> ArenaState:
    state = ArenaState(task, "structured", context_mode)
    resolved_agent_models = agent_models or {}
    if progress:
        progress("kickoff: Orchestrator opens the first handoff")
    await manager_turn(
        state,
        client,
        model_name=model_name,
        agent_models=resolved_agent_models,
        collaboration_profile=collaboration_profile,
        phase="kickoff",
        purpose="Start the gated collaboration and assign the research brief.",
        expected_handoff_to="Researcher",
    )
    dependencies: list[str] = []
    for flow in STRUCTURED_FLOWS:
        if progress:
            progress(f"{flow.phase}: {flow.author} artifact, reviews, and revision gate")
        artifact = await run_artifact_flow(
            state,
            client,
            model_name=model_name,
            agent_models=resolved_agent_models,
            collaboration_profile=collaboration_profile,
            flow=flow,
            dependencies=dependencies,
            critic_min_revision=critic_min_revision,
            max_revision_cycles=max_revision_cycles,
        )
        dependencies.append(artifact.id)
        await manager_turn(
            state,
            client,
            model_name=model_name,
            agent_models=resolved_agent_models,
            collaboration_profile=collaboration_profile,
            phase=flow.phase,
            purpose=f"Record completion of {artifact.id} and prepare the next dependency.",
            expected_handoff_to=None,
        )
    if progress:
        progress("finalization: Orchestrator integrates approved artifacts")
    await finalize_structured(
        state,
        client,
        model_name=model_name,
        agent_models=resolved_agent_models,
        collaboration_profile=collaboration_profile,
        dependencies=dependencies,
    )
    return state


async def run_baseline_task(
    task: Task,
    client: ModelClient,
    *,
    model_name: str,
    agent_models: dict[str, str] | None = None,
    collaboration_profile: CollaborationProfile = "neutral",
    context_mode: ContextMode = "full",
    progress: Callable[[str], None] | None = None,
) -> ArenaState:
    state = ArenaState(task, "baseline", context_mode)
    resolved_agent_models = agent_models or {}
    for phase in BASELINE_PHASES:
        if progress:
            progress(f"{phase}: ungated round-robin discussion")
        for agent in AGENTS:
            output = await client.complete(
                model_name=model_for_agent(agent.name, resolved_agent_models, model_name),
                system=agent_system(agent.name, collaboration_profile),
                prompt=baseline_prompt(state, phase, agent.name),
                output_type=BaselineTurnOutput,
            )
            content = f"{output.message}\nCommitment: {output.commitment}" + (
                f"\nHandoff to {output.handoff_to}: {output.handoff_request}"
                if output.handoff_to and output.handoff_request
                else ""
            )
            turn = state.add_turn(
                phase=phase,
                speaker=agent.name,
                action="baseline_turn",
                content=content,
            )
            state.return_open_handoffs(agent.name, turn.id, output.message)
            if output.handoff_to and output.handoff_request:
                handoff = state.open_handoff(
                    from_agent=agent.name,
                    to_agent=output.handoff_to,
                    request=output.handoff_request,
                    kind="baseline",
                    phase=phase,
                    opened_turn=turn.id,
                )
                if handoff:
                    turn.handoff_id = handoff.id
    return state


def ordered_reference_pairs(agent_names: list[str]) -> list[tuple[str, str]]:
    return [(evaluator, target) for evaluator, target in permutations(agent_names, 2)]


async def collect_reference_checks(
    state: ArenaState,
    client: ModelClient,
    *,
    checker_model: str,
    reference_limit: int,
    concurrency: int,
    timeout_seconds: float,
    progress: Callable[[str], None] | None = None,
) -> tuple[dict[str, dict[str, ReferenceCheck]], list[ReferenceTimeout]]:
    pairs = ordered_reference_pairs([agent.name for agent in AGENTS])
    if reference_limit > 0:
        pairs = pairs[:reference_limit]
    semaphore = asyncio.Semaphore(concurrency)

    async def check(
        index: int, evaluator: str, target: str
    ) -> tuple[str, str, ReferenceCheck | ReferenceTimeout]:
        async with semaphore:
            if progress:
                progress(f"reference {index}/{len(pairs)}: {evaluator} -> {target}")
            try:
                result = await asyncio.wait_for(
                    client.complete(
                        model_name=checker_model,
                        system=(
                            "Write a strict, evidence-grounded peer reference check. Use only the "
                            "transcript. Cite turn IDs in every evidence bullet. Rate "
                            "collaborative behavior rather than task quality. Avoid blanket "
                            "perfect scores; 5 is reserved for exceptional target-specific "
                            "behavior with no material gaps."
                        ),
                        prompt=reference_prompt(state, evaluator, target),
                        output_type=ReferenceCheck,
                    ),
                    timeout=timeout_seconds,
                )
                return evaluator, target, result
            except TimeoutError:
                return (
                    evaluator,
                    target,
                    ReferenceTimeout(
                        evaluator=evaluator,
                        target=target,
                        timeout_seconds=timeout_seconds,
                        error="reference check timed out",
                    ),
                )

    records = await asyncio.gather(
        *(check(index, evaluator, target) for index, (evaluator, target) in enumerate(pairs, 1))
    )
    checks: dict[str, dict[str, ReferenceCheck]] = {}
    timeouts: list[ReferenceTimeout] = []
    for evaluator, target, reference in records:
        if isinstance(reference, ReferenceCheck):
            checks.setdefault(evaluator, {})[target] = reference
        else:
            timeouts.append(reference)
    return checks, timeouts


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def dim_scores(checks: list[ReferenceCheck]) -> dict[str, float | None]:
    valid = [check for check in checks if not check.insufficient_evidence]
    return {
        dimension: mean([float(getattr(check, dimension)) for check in valid])
        for dimension in DIMENSIONS
    }


def aggregate(
    peer_checks: dict[str, dict[str, ReferenceCheck]],
    *,
    valid_turn_ids: set[str],
) -> dict[str, Any]:
    records = [
        (evaluator, target, check)
        for evaluator, ratings in peer_checks.items()
        for target, check in ratings.items()
    ]
    agents = sorted({agent.name for agent in AGENTS})
    received = {
        agent: dim_scores([check for _, target, check in records if target == agent])
        for agent in agents
    }
    valid_records = [
        (evaluator, target, check)
        for evaluator, target, check in records
        if not check.insufficient_evidence
    ]
    overall = {
        agent: [float(check.overall) for _, target, check in valid_records if target == agent]
        for agent in agents
    }
    agreement = {
        agent: {
            "std": statistics.pstdev(scores) if len(scores) > 1 else 0.0,
            "spread": max(scores) - min(scores) if scores else None,
        }
        for agent, scores in overall.items()
    }
    asymmetry: dict[str, int] = {}
    for a, b in permutations(agents, 2):
        ab = peer_checks.get(a, {}).get(b)
        ba = peer_checks.get(b, {}).get(a)
        if ab and ba and not ab.insufficient_evidence and not ba.insufficient_evidence:
            asymmetry[f"{a}->{b}"] = ab.overall - ba.overall
    all_checks = [check for _, _, check in records]
    evidence_items = [bullet for check in all_checks for bullet in check.evidence]
    cited_items = [
        bullet for bullet in evidence_items if any(turn_id in bullet for turn_id in valid_turn_ids)
    ]
    evidence = {
        "checks": len(all_checks),
        "avg_items": mean([float(len(check.evidence)) for check in all_checks]),
        "insufficient_rate": mean([float(check.insufficient_evidence) for check in all_checks]),
        "avg_confidence": mean([float(check.confidence) for check in all_checks]),
        "citation_rate": len(cited_items) / len(evidence_items) if evidence_items else None,
    }
    return {
        "received": received,
        "agreement": agreement,
        "asymmetry": asymmetry,
        "evidence": evidence,
    }


def state_to_dict(state: ArenaState) -> dict[str, Any]:
    return {
        "task": asdict(state.task),
        "condition": state.condition,
        "context_mode": state.context_mode,
        "transcript": [asdict(turn) for turn in state.turns],
        "artifacts": [asdict(artifact) for artifact in state.artifacts.values()],
        "reviews": [asdict(review) for review in state.reviews.values()],
        "handoffs": [asdict(handoff) for handoff in state.handoffs.values()],
        "health": state.health_metrics(),
    }


def state_from_dict(payload: dict[str, Any]) -> ArenaState:
    """Rehydrate an arena state from a saved result row."""

    task = Task(**payload["task"])
    state = ArenaState(
        task,
        cast(Condition, payload["condition"]),
        cast(ContextMode, payload.get("context_mode", "full")),
    )
    state.turns = [Turn(**turn) for turn in payload["transcript"]]
    state.artifacts = {artifact["id"]: Artifact(**artifact) for artifact in payload["artifacts"]}
    state.reviews = {review["id"]: Review(**review) for review in payload["reviews"]}
    state.handoffs = {handoff["id"]: Handoff(**handoff) for handoff in payload["handoffs"]}
    return state


def checks_to_dict(checks: dict[str, dict[str, ReferenceCheck]]) -> dict[str, dict[str, Any]]:
    return {
        evaluator: {target: check.model_dump() for target, check in targets.items()}
        for evaluator, targets in checks.items()
    }


def print_summary(results: list[dict[str, Any]]) -> None:
    for result in results:
        state = result["state"]
        health = state.health_metrics()
        evidence = result["aggregate"]["evidence"]
        timeouts = result["reference_timeouts"]
        print(f"\n{state.condition.upper()} | {state.task.title}")
        print(
            "  turns={turn_count} artifacts={artifact_count} reviews={review_count} "
            "critic_rejections={critic_rejection_count} handoffs={handoff_count} "
            "open_handoffs={open_handoff_count} "
            "handoff_completion={handoff_completion_rate:.0%}".format(**health)
        )
        print(f"  handoffs_by_kind={health['handoffs_by_kind']}")
        print(
            "  checks={checks} insufficient={insufficient_rate:.0%} "
            "citation_rate={citation_rate:.0%} timeouts={timeouts}".format(
                checks=evidence["checks"],
                insufficient_rate=evidence["insufficient_rate"] or 0.0,
                citation_rate=evidence["citation_rate"] or 0.0,
                timeouts=len(timeouts),
            )
        )
        for agent, scores in result["aggregate"]["received"].items():
            overall = scores["overall"]
            if overall is not None:
                print(f"  {agent:<16} overall={overall:.2f}")


def run_config_from_args(args: argparse.Namespace) -> dict[str, Any]:
    """Capture experiment settings in saved result files."""

    tasks, conditions, reference_limit = apply_profile(args)
    agent_models = resolve_agent_models(args)
    return {
        "run_label": args.run_label,
        "client": args.client,
        "profile": args.profile,
        "collaboration_profile": args.collaboration_profile,
        "context_mode": args.context_mode,
        "model_profile": args.model_profile,
        "model": args.model,
        "specialist_model": args.specialist_model,
        "reviewer_model": args.reviewer_model,
        "critic_model": args.critic_model,
        "orchestrator_model": args.orchestrator_model,
        "agent_models": agent_models,
        "checker_model": args.checker_model,
        "conditions": conditions,
        "task_titles": [task.title for task in tasks],
        "task_count": len(tasks),
        "reference_limit": reference_limit,
        "concurrency": args.concurrency,
        "reference_timeout": args.reference_timeout,
        "model_timeout": args.model_timeout,
        "model_retries": args.model_retries,
        "critic_min_revision": args.critic_min_revision,
        "max_revision_cycles": args.max_revision_cycles,
    }


def save_results(
    results: list[dict[str, Any]], output_dir: Path, run_config: dict[str, Any]
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"refcheck_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    payload = {
        "created_at": datetime.now().isoformat(),
        "run_config": run_config,
        "results": [
            {
                **state_to_dict(result["state"]),
                "checks": checks_to_dict(result["checks"]),
                "reference_timeouts": [
                    timeout.model_dump() for timeout in result["reference_timeouts"]
                ],
                "aggregate": result["aggregate"],
            }
            for result in results
        ],
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


def parse_conditions(raw: str) -> list[Condition]:
    conditions: list[Condition] = []
    for item in raw.split(","):
        value = item.strip()
        if value not in {"structured", "baseline"}:
            raise argparse.ArgumentTypeError("conditions must be structured, baseline, or both")
        conditions.append(cast(Condition, value))
    return conditions


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", choices=["vals", "fake"], default="vals")
    parser.add_argument("--profile", choices=["smoke", "full"], default="smoke")
    parser.add_argument(
        "--collaboration-profile",
        choices=["neutral", "calibration"],
        default="neutral",
        help="Use calibration to seed recoverable role-specific collaboration flaws.",
    )
    parser.add_argument(
        "--context-mode",
        choices=["full", "compact"],
        default="full",
        help="Use compact to reduce repeated collaboration prompt context for slow models.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--model-profile",
        choices=["homogeneous", "frontier_review", "cost_stressed"],
        default=DEFAULT_MODEL_PROFILE,
        help=(
            "homogeneous uses --model for every role; frontier_review uses --model for "
            "Orchestrator/Reviewer/Critic and --specialist-model for specialists; "
            "cost_stressed lets manager, reviewers, and specialists differ."
        ),
    )
    parser.add_argument("--specialist-model", default=None)
    parser.add_argument("--reviewer-model", default=None)
    parser.add_argument("--critic-model", default=None)
    parser.add_argument("--orchestrator-model", default=None)
    parser.add_argument(
        "--agent-models",
        default=None,
        help="Optional JSON object overriding exact role-to-model assignments.",
    )
    parser.add_argument("--checker-model", default=DEFAULT_CHECKER_MODEL)
    parser.add_argument("--run-label", default=None)
    parser.add_argument("--conditions", type=parse_conditions, default=None)
    parser.add_argument("--tasks", type=int, default=None)
    parser.add_argument(
        "--reference-limit",
        type=int,
        default=None,
        help="Number of ordered peer checks to run. Use 0 for all pairs.",
    )
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--model-timeout",
        type=float,
        default=90.0,
        help="Timeout in seconds for each collaboration/model call before retrying.",
    )
    parser.add_argument(
        "--model-retries",
        type=int,
        default=2,
        help="Total attempts for each collaboration/model call.",
    )
    parser.add_argument("--reference-timeout", type=float, default=180.0)
    parser.add_argument("--critic-min-revision", type=int, default=1)
    parser.add_argument("--max-revision-cycles", type=int, default=2)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("refcheckarena/results"),
    )
    return parser


def apply_profile(args: argparse.Namespace) -> tuple[list[Task], list[Condition], int]:
    if args.profile == "full":
        default_tasks = len(TASKS)
        default_conditions: list[Condition] = ["structured", "baseline"]
        default_reference_limit = 0
    else:
        default_tasks = 1
        default_conditions = ["structured"]
        default_reference_limit = 8

    task_count = args.tasks if args.tasks is not None else default_tasks
    if task_count < 1:
        raise ValueError("--tasks must be at least 1")
    conditions = args.conditions if args.conditions is not None else default_conditions
    reference_limit = (
        args.reference_limit if args.reference_limit is not None else default_reference_limit
    )
    if reference_limit < 0:
        raise ValueError("--reference-limit must be >= 0")
    return TASKS[:task_count], conditions, reference_limit


def parse_agent_model_overrides(raw: str | None) -> dict[str, str]:
    """Parse exact role-to-model overrides from CLI JSON."""

    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("--agent-models must be a JSON object") from exc
    if not isinstance(parsed, dict):
        raise ValueError("--agent-models must be a JSON object")
    overrides: dict[str, str] = {}
    valid_agents = {agent.name for agent in AGENTS}
    for key, value in parsed.items():
        if key not in valid_agents:
            raise ValueError(f"Unknown agent in --agent-models: {key}")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Model override for {key} must be a non-empty string")
        overrides[key] = value.strip()
    return overrides


def resolve_agent_models(args: argparse.Namespace) -> dict[str, str]:
    """Resolve the concrete model assigned to every collaboration role."""

    base_model = str(args.model)
    specialist_model = args.specialist_model or base_model
    reviewer_model = args.reviewer_model or base_model
    critic_model = args.critic_model or reviewer_model
    orchestrator_model = args.orchestrator_model or base_model

    assignments = {agent.name: base_model for agent in AGENTS}
    if args.model_profile == "frontier_review":
        for agent in ("Researcher", "FinancialAnalyst", "TechLead", "ContentWriter"):
            assignments[agent] = specialist_model
        for agent in ("Orchestrator", "Reviewer", "Critic"):
            assignments[agent] = base_model
    elif args.model_profile == "cost_stressed":
        for agent in ("Researcher", "FinancialAnalyst", "TechLead", "ContentWriter"):
            assignments[agent] = specialist_model
        assignments["Orchestrator"] = orchestrator_model
        assignments["Reviewer"] = reviewer_model
        assignments["Critic"] = critic_model
    elif args.model_profile != "homogeneous":
        raise ValueError(f"Unknown --model-profile: {args.model_profile}")

    assignments.update(parse_agent_model_overrides(args.agent_models))
    return assignments


async def run_experiment(args: argparse.Namespace) -> list[dict[str, Any]]:
    tasks, conditions, reference_limit = apply_profile(args)
    if args.model_timeout <= 0:
        raise ValueError("--model-timeout must be positive")
    if args.model_retries < 1:
        raise ValueError("--model-retries must be at least 1")

    def progress(message: str) -> None:
        if not args.quiet:
            print(f"[refcheckarena] {message}", flush=True)

    client: ModelClient
    close_client = None
    if args.client == "fake":
        client = FakeModelClient()
    else:
        vals_client = ValsModelClient(Path(".env"))
        client = vals_client
        close_client = vals_client.aclose
    client = TimeoutRetryModelClient(
        client,
        timeout_seconds=args.model_timeout,
        attempts=args.model_retries,
        progress=progress,
    )
    agent_models = resolve_agent_models(args)

    results: list[dict[str, Any]] = []

    try:
        for task in tasks:
            for condition in conditions:
                progress(f"starting {condition} task: {task.title}")
                if condition == "structured":
                    state = await run_structured_task(
                        task,
                        client,
                        model_name=args.model,
                        agent_models=agent_models,
                        collaboration_profile=args.collaboration_profile,
                        context_mode=args.context_mode,
                        critic_min_revision=args.critic_min_revision,
                        max_revision_cycles=args.max_revision_cycles,
                        progress=progress,
                    )
                else:
                    state = await run_baseline_task(
                        task,
                        client,
                        model_name=args.model,
                        agent_models=agent_models,
                        collaboration_profile=args.collaboration_profile,
                        context_mode=args.context_mode,
                        progress=progress,
                    )
                pair_count = len(ordered_reference_pairs([agent.name for agent in AGENTS]))
                if reference_limit > 0:
                    pair_count = min(pair_count, reference_limit)
                progress(
                    f"collaboration complete with {len(state.turns)} turns; "
                    f"collecting {pair_count} reference checks"
                )
                checks, timeouts = await collect_reference_checks(
                    state,
                    client,
                    checker_model=args.checker_model,
                    reference_limit=reference_limit,
                    concurrency=args.concurrency,
                    timeout_seconds=args.reference_timeout,
                    progress=progress,
                )
                aggregate_result = aggregate(
                    checks,
                    valid_turn_ids={turn.id for turn in state.turns},
                )
                results.append(
                    {
                        "state": state,
                        "checks": checks,
                        "reference_timeouts": timeouts,
                        "aggregate": aggregate_result,
                    }
                )
    finally:
        if close_client is not None:
            await close_client()
    return results


async def async_main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    results = await run_experiment(args)
    print_summary(results)
    path = save_results(results, args.output_dir, run_config_from_args(args))
    print(f"\nSaved results to {path}")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
