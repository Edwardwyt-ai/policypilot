from policypilot.checkpoint import JsonCheckpointStore
from policypilot.config import PolicyPilotConfig
from policypilot.runtime.actions import record_valid_tool_calls, validate_proposal
from policypilot.runtime.mutations import capture_action_authorization, mutation_manager
from policypilot.runtime.observation import apply_mutation_readback
from policypilot.state import MutationRecord
from tau2.data_model.message import AssistantMessage, ToolCall


def mutation(arguments=None, call_id="mutation-1"):
    return AssistantMessage(
        role="assistant",
        tool_calls=[
            ToolCall(
                id=call_id,
                name="mutate_account",
                arguments=arguments or {"account_id": "a1"},
                requestor="assistant",
            )
        ],
    )


def test_mutation_idempotency_blocks_sent_unknown_and_confirmed(agent_factory):
    agent = agent_factory(config=PolicyPilotConfig(memory_enabled=False))
    state = agent.get_init_state()
    first = mutation()
    record_valid_tool_calls(agent, first, state)

    for status in ("SENT", "UNKNOWN", "CONFIRMED"):
        state.mutations[-1].status = status
        result = validate_proposal(agent, mutation(call_id=f"again-{status}"), state)
        assert not result.allowed
        assert result.reason_code == "DUPLICATE_MUTATION"


def test_ambiguous_readback_stays_unknown_and_explicit_no_change_fails(agent_factory):
    agent = agent_factory(config=PolicyPilotConfig(memory_enabled=False))
    state = agent.get_init_state()
    record_valid_tool_calls(agent, mutation(), state)
    state.mutations[-1].status = "UNKNOWN"

    assert apply_mutation_readback(state, "read-1", "account a1 exists") == "UNKNOWN"
    assert state.mutations[-1].status == "UNKNOWN"
    assert apply_mutation_readback(state, "read-2", "No change was applied") == "FAILED"


def test_checkpoint_roundtrip_preserves_pending_mutation_and_recovery(tmp_path, agent_factory):
    config = PolicyPilotConfig(memory_enabled=False, checkpoint_dir=str(tmp_path))
    agent = agent_factory(config=config, task_id="task-checkpoint")
    state = agent.get_init_state()
    record_valid_tool_calls(agent, mutation(), state)
    state.mutations[-1].status = "UNKNOWN"
    state.control.guard_recovery_attempts = 2

    path = agent.save_checkpoint(state)
    restored = agent.load_checkpoint()

    assert path == JsonCheckpointStore(tmp_path).path_for("task-checkpoint")
    assert restored is not None
    assert restored.mutations[-1].status == "UNKNOWN"
    assert restored.control.guard_recovery_attempts == 2
    result = validate_proposal(agent, mutation(call_id="resumed"), restored)
    assert result.reason_code == "DUPLICATE_MUTATION"


def test_mutation_lifecycle_records_planned_and_sent_transitions(agent_factory):
    agent = agent_factory(config=PolicyPilotConfig(memory_enabled=False))
    state = agent.get_init_state()
    capture_action_authorization(
        state,
        content="Please update this account now.",
        turn=0,
        evidence_ref="user-authorization",
        explicit=True,
    )

    record_valid_tool_calls(agent, mutation(), state)

    record = state.mutations[-1]
    assert record.status == "SENT"
    assert [item.status for item in record.status_history] == ["PLANNED", "SENT"]
    assert record.operation_fingerprint == record.idempotency_key
    assert record.authorization_id == state.action_authorizations[-1].authorization_id


def test_readback_status_does_not_override_unmatched_expected_effect(agent_factory):
    agent = agent_factory(config=PolicyPilotConfig(memory_enabled=False))
    state = agent.get_init_state()
    proposal = mutation({"account_id": "a1", "amount": 125})
    record_valid_tool_calls(agent, proposal, state)
    mutation_manager.record_tool_result(
        state.mutations[-1],
        succeeded=False,
        turn=1,
        tool_call_id="mutation-1",
    )

    status = apply_mutation_readback(
        state, "read-amount", '{"status":"success","amount":100}'
    )

    assert status == "UNKNOWN"
    assert state.mutations[-1].status == "UNKNOWN"


def test_sensitive_value_must_be_in_explicit_authorization(agent_factory):
    agent = agent_factory(config=PolicyPilotConfig(memory_enabled=False))
    state = agent.get_init_state()
    capture_action_authorization(
        state,
        content="Please transfer 100 now.",
        turn=0,
        evidence_ref="user-authorization",
        explicit=True,
    )

    issue = mutation_manager.validate_authorization(
        state,
        tool_name="transfer_funds",
        arguments={"account_id": "a1", "amount": 200},
    )

    assert issue is not None
    assert issue.reason_code == "UNAUTHORIZED_ARGUMENT_VALUE"


def test_multiple_mutations_in_one_turn_are_blocked(agent_factory):
    agent = agent_factory(config=PolicyPilotConfig(memory_enabled=False))
    state = agent.get_init_state()
    proposal = AssistantMessage(
        role="assistant",
        tool_calls=[
            mutation(call_id="first").tool_calls[0],
            mutation(call_id="second").tool_calls[0],
        ],
    )

    result = validate_proposal(agent, proposal, state)

    assert not result.allowed
    assert result.reason_code == "MUTATION_MUST_EXECUTE_ALONE"


def test_legacy_idempotency_key_loads_as_operation_fingerprint():
    record = MutationRecord.model_validate(
        {
            "mutation_id": "legacy-mutation",
            "idempotency_key": "legacy-fingerprint",
            "tool_name": "mutate_account",
            "arguments": {"account_id": "a1"},
            "signature": 'mutate_account:{"account_id":"a1"}',
            "tool_call_id": "legacy-call",
            "status": "SENT",
            "planned_turn": 1,
            "updated_turn": 1,
        }
    )

    assert record.operation_fingerprint == "legacy-fingerprint"
    assert record.idempotency_key == "legacy-fingerprint"
