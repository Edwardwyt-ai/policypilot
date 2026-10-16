"""Offline contracts for the task-independent user simulation harness."""

import json
import random
from types import SimpleNamespace

import pytest

from policypilot.api.runtime import RuntimeTurn
from policypilot.api.schemas import PendingActionView, utc_now
from policypilot.simulation.rollout import SimulatedUser, run_rollout
from policypilot.simulation.users import UserMove, initialize_user
from tau2.domains.banking_knowledge.data_model import DatabaseTable, TransactionalDB


def scenario(seed=0):
    db = TransactionalDB(
        users=DatabaseTable(
            data={
                "u1": {
                    "name": "Synthetic User",
                    "user_id": "u1",
                    "verification_code": "NEVER_SEND",
                }
            }
        )
    )
    return initialize_user(db, seed)


def test_initialization_is_reproducible_and_does_not_change_global_rng():
    random.seed(71)
    before = random.getstate()
    assert scenario() == scenario()
    assert before == random.getstate()
    assert "verification_code" not in scenario().known_identity
    assert len({scenario(i).model_dump_json(exclude={"seed"}) for i in range(30)}) > 10


def test_unknown_or_empty_user_database_rejected():
    with pytest.raises(ValueError):
        initialize_user(TransactionalDB(), 0)
    with pytest.raises(ValueError):
        initialize_user(
            TransactionalDB(users=DatabaseTable(data={"u": {}})), 0, "missing"
        )


def simulator_reply(content, captured):
    def generate(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(
            content=content, tool_calls=[], usage={"input_tokens": 12}, cost=None
        )

    return generate


def test_user_prompt_contains_only_private_scenario_and_public_dialogue():
    captured = []
    user = SimulatedUser(
        scenario(),
        "fake/model",
        simulator_reply('{"action":"say","content":"Hello"}', captured),
    )
    assert user.next_move([], None).content == "Hello"
    payload = json.loads(captured[0]["messages"][1].content)
    assert set(payload) == {"private_scenario", "conversation", "pending_action"}
    assert "NEVER_SEND" not in captured[0]["messages"][1].content
    assert user.calls[0]["cost"] is None


@pytest.mark.parametrize(
    "reply",
    [
        "not json",
        '{"action":"confirm"}',
        '{"action":"say","content":" "}',
        '{"action":"say","content":"ok","hidden":"extra"}',
    ],
)
def test_invalid_simulator_moves_rejected(reply):
    user = SimulatedUser(scenario(), "fake/model", simulator_reply(reply, []))
    with pytest.raises(ValueError):
        user.next_move([], None)


def test_declining_user_cannot_confirm_pending_mutation():
    private = scenario().model_copy(update={"mutation_policy": "decline"})
    user = SimulatedUser(
        private, "fake/model", simulator_reply('{"action":"confirm"}', [])
    )
    with pytest.raises(ValueError, match="refusal"):
        user.next_move([], {"action_id": "a"})


class FakeRuntime:
    def __init__(self):
        self.pending_action = None
        self.value = "before"

    def export_snapshot(self):
        return {"environment_db": {"value": self.value}, "llm_traces": []}

    def send(self, content):
        self.pending_action = PendingActionView(
            action_id="action-1",
            tool_name="example_write",
            arguments={},
            created_at=utc_now(),
        )
        return RuntimeTurn("Confirm?", self.pending_action)

    def confirm(self, action_id):
        assert action_id == "action-1"
        self.pending_action = None
        self.value = "after"
        return RuntimeTurn("Done", tool_calls_executed=1)

    def cancel(self, action_id):
        self.pending_action = None
        return RuntimeTurn("Cancelled")


class ScriptedUser:
    model = "fake"
    calls = []

    def __init__(self, moves):
        self.scenario = scenario()
        self.moves = iter(moves)

    def next_move(self, conversation, pending):
        return next(self.moves)


def test_rollout_routes_confirmation_and_preserves_artifacts(tmp_path):
    runtime = FakeRuntime()
    user = ScriptedUser(
        [
            UserMove(action="say", content="Please change it"),
            UserMove(action="confirm"),
            UserMove(action="stop"),
        ]
    )
    output = tmp_path / "run"
    report = run_rollout(runtime, user, output)
    assert report["status"] == "user_stopped"
    assert report["business_success"] is None
    assert report["final_snapshot"]["environment_db"]["value"] == "after"
    assert (
        json.loads((output / "initial.private.json").read_text())["environment_db"][
            "value"
        ]
        == "before"
    )
    assert len((output / "turns.private.jsonl").read_text().splitlines()) == 2
    with pytest.raises(FileExistsError):
        run_rollout(runtime, user, output)


def test_simulator_invalid_is_not_an_agent_failure(tmp_path):
    user = SimulatedUser(scenario(), "fake", simulator_reply("invalid json", []))
    report = run_rollout(FakeRuntime(), user, tmp_path / "invalid")
    assert report["status"] == "simulator_invalid"
    assert report["error_type"] == "ValidationError"


def test_simulator_provider_failure_is_separate(tmp_path):
    def unavailable(**kwargs):
        raise ConnectionError("provider unreachable")

    report = run_rollout(
        FakeRuntime(),
        SimulatedUser(scenario(), "fake", unavailable),
        tmp_path / "unavailable",
    )
    assert report["status"] == "simulator_error"
    assert report["error_type"] == "ConnectionError"


def test_runtime_failure_is_reported_separately(tmp_path):
    class BrokenRuntime(FakeRuntime):
        def send(self, content):
            raise RuntimeError("secret must not appear in report")

    report = run_rollout(
        BrokenRuntime(),
        ScriptedUser([UserMove(action="say", content="Hi")]),
        tmp_path / "broken",
    )
    assert report["status"] == "runtime_error"
    assert report["error_type"] == "RuntimeError"
    assert "secret" not in json.dumps(report)


def test_turn_limit_does_not_claim_success(tmp_path):
    report = run_rollout(
        FakeRuntime(),
        ScriptedUser([UserMove(action="say", content="Hi")]),
        tmp_path / "bounded",
        1,
    )
    assert report["status"] == "turn_limit"
    assert report["business_success"] is None
