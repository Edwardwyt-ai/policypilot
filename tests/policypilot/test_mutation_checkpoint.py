from policypilot.checkpoint import JsonCheckpointStore
from policypilot.config import PolicyPilotConfig
from policypilot.runtime.actions import record_valid_tool_calls, validate_proposal
from policypilot.runtime.observation import apply_mutation_readback
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
