from dataclasses import replace

from policypilot.config import PolicyPilotConfig
from policypilot.errors import PolicyPilotErrorType
from policypilot.skills import SkillLoader, SkillMatcher, SkillRuntime
from policypilot.state import (
    GoalCriterion,
    InformationNeed,
    PolicyPilotState,
    StructuredGoal,
)
from tau2.data_model.message import (
    AssistantMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
)


def make_state() -> PolicyPilotState:
    return PolicyPilotState(
        system_messages=[SystemMessage(role="system", content="system")]
    )


def test_loader_discovers_six_skills_and_lazy_reference_metadata():
    loader = SkillLoader()

    metadata = loader.metadata()
    artifact = loader.load("constraint-aware-recommendation")

    assert len(metadata) == 6
    assert artifact is not None
    assert artifact.metadata.version == "2.0"
    assert {item.id for item in artifact.available_references} == {
        "candidate-evaluation",
        "constraint-modeling",
        "decision-checklist",
        "information-needs",
    }


def test_matcher_supports_bounded_multiple_active_skills():
    value = make_state()
    value.intent = "TRANSACTIONAL"
    value.goal = StructuredGoal(
        objective="Compare options before applying",
        target="account",
        comparative=True,
        criteria=[
            GoalCriterion(
                id="fee",
                kind="CONSTRAINT",
                aspect="annual_fee",
                value="no annual fee",
                hard=True,
                source_turn=0,
            )
        ],
    )
    value.information_needs.extend(
        [
            InformationNeed(
                id="policy",
                entity="account",
                aspect="eligibility",
                source="POLICY",
                reason="Need policy.",
            ),
            InformationNeed(
                id="identity",
                entity="user",
                aspect="user_id",
                source="USER",
                reason="Need identity.",
            ),
        ]
    )

    selected = SkillMatcher(max_active_skills=3).match(
        value, SkillLoader().metadata(), event="NEW_GOAL"
    )

    assert selected == [
        "policy-grounded-transaction",
        "constraint-aware-recommendation",
        "retrieval-investigation",
    ]


def test_decision_jit_loads_candidate_references_only():
    value = make_state()
    value.goal = StructuredGoal(
        objective="Compare options",
        target="account",
        comparative=True,
        criteria=[
            GoalCriterion(
                id="limit",
                kind="CONSTRAINT",
                aspect="limit",
                value="at least ten",
                hard=True,
                source_turn=0,
            )
        ],
    )
    runtime = SkillRuntime()
    runtime.refresh(value, event="NEW_GOAL")

    contexts = runtime.get_guidance("decision", value, max_chars=5000)
    recommendation = next(
        item for item in contexts if item.skill_id == "constraint-aware-recommendation"
    )

    assert recommendation.loaded_reference_ids == (
        "candidate-evaluation",
        "decision-checklist",
    )
    rendered = recommendation.render()
    assert "mutation-uncertainty" not in rendered
    assert "retrieval-refinement" not in rendered


def test_mutation_recovery_loads_only_high_priority_failure_references():
    value = make_state()
    value.control.mutation_verification_required = True
    value.add_error(
        PolicyPilotErrorType.MUTATION_UNCERTAIN,
        "Mutation outcome unknown.",
        retryable=False,
        unsafe_to_retry=True,
    )
    runtime = SkillRuntime()
    runtime.refresh(
        value,
        event="RECOVERY_MODE_CHANGE",
        recovery_mode="mutation_uncertain",
    )

    contexts = runtime.get_guidance(
        "recovery",
        value,
        error_category="mutation_uncertain",
        max_chars=5000,
    )
    failure = next(item for item in contexts if item.skill_id == "failure-diagnosis")

    assert failure.loaded_reference_ids == (
        "mutation-uncertainty",
        "diagnostic-evidence",
    )
    assert "recovery-strategies" not in failure.render()


def test_phase_filter_keeps_retrieval_guidance_out_of_decision():
    value = make_state()
    value.intent = "TRANSACTIONAL"
    value.information_needs.append(
        InformationNeed(
            id="policy",
            entity="account",
            aspect="eligibility",
            source="POLICY",
            reason="Need policy.",
        )
    )
    runtime = SkillRuntime()
    runtime.refresh(value, event="NEW_GOAL")

    contexts = runtime.get_guidance("decision", value, max_chars=5000)

    assert "policy-grounded-transaction" in {item.skill_id for item in contexts}
    assert "retrieval-investigation" not in {item.skill_id for item in contexts}


def test_reference_loader_rejects_path_outside_skill_reference_directory():
    loader = SkillLoader()
    artifact = loader.load("constraint-aware-recommendation")
    assert artifact is not None
    reference = artifact.available_references[0]
    unsafe = replace(reference, path=artifact.metadata.path.parent / "outside.md")

    assert loader.load_reference(artifact.metadata.name, unsafe) is None


def test_guidance_budget_skips_whole_blocks_and_records_reference_ids():
    value = make_state()
    value.goal.comparative = True
    runtime = SkillRuntime(max_references_per_skill=2)
    runtime.refresh(value, event="NEW_GOAL")

    text = runtime.guidance("decision", value, max_chars=900)
    snapshot = runtime.snapshot()

    assert len(text) <= 900
    assert not text.endswith("<skill_reference")
    assert any(
        event["event"] in {"reference_loaded", "reference_skipped"}
        for event in snapshot["events"]
    )
    assert all("content" not in event for event in snapshot["events"])


def test_uncertain_mutation_creates_targeted_verification_need(agent_factory):
    agent = agent_factory(config=PolicyPilotConfig(memory_enabled=False))
    value = agent.get_init_state()
    mutation = ToolCall(
        id="mutation-1",
        name="mutate_account",
        arguments={"account_id": "account-1"},
        requestor="assistant",
    )
    proposal = AssistantMessage(role="assistant", tool_calls=[mutation])
    value.messages.append(proposal)
    agent._record_valid_tool_calls(proposal, value)

    agent._observe_tool_message(
        ToolMessage(
            role="tool",
            id="mutation-1",
            content="Outcome unknown.",
            error=True,
        ),
        value,
    )

    verification = next(
        need for need in value.open_needs("TOOL") if need.purpose == "VERIFICATION"
    )
    assert verification.capability == "read_account"
    assert verification.tool_arguments == {"account_id": "account-1"}
    assert value.control.mutation_verification_required

    read_call = agent._tool_call_for_need(verification, value)
    assert read_call is not None
    read_message = AssistantMessage(role="assistant", tool_calls=[read_call])
    value.messages.append(read_message)
    agent._record_valid_tool_calls(read_message, value, verification.id)
    agent._observe_tool_message(
        ToolMessage(
            role="tool",
            id=read_call.id,
            content='{"account_id":"account-1","status":"updated"}',
        ),
        value,
    )

    assert verification.status == "RESOLVED"
    assert not value.control.mutation_verification_required
