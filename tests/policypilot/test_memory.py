import json

from policypilot.config import PolicyPilotConfig
from policypilot.context import build_agent_context
from policypilot.memory.context import render_memory_context
from policypilot.memory.episodic import EpisodeFormer, EpisodeRetriever
from policypilot.memory.models import EpisodeMemory, MemorySnapshot, PreferenceCandidate
from policypilot.memory.profile import (
    ProfileMemoryGate,
    ProfileMemoryManager,
    ProfileMerger,
)
from policypilot.memory.service import MemoryService
from policypilot.memory.store import JsonMemoryStore
from policypilot.state import FactRecord, PolicyPilotState, StructuredGoal
from tau2.data_model.message import AssistantMessage, SystemMessage, UserMessage


class StaticExtractor:
    def __init__(self, candidates):
        self.candidates = candidates
        self.calls = 0

    def extract(self, message, task_context):
        self.calls += 1
        return list(self.candidates)


def make_state():
    return PolicyPilotState(
        system_messages=[SystemMessage(role="system", content="system")],
        goal=StructuredGoal(objective="Compare cards with no annual fee", target="card"),
    )


def test_store_hashes_user_id_and_round_trips_profile(tmp_path):
    store = JsonMemoryStore(tmp_path)
    manager = ProfileMemoryManager(
        store,
        StaticExtractor([]),
    )
    profile, accepted, rejected, changed = manager.apply(
        "private_user_123",
        [
            PreferenceCandidate(
                aspect="annual_fee",
                value="Avoid annual fees",
                polarity="AVOID",
                confidence=0.9,
                source_excerpt="I prefer to avoid annual fees.",
            )
        ],
    )

    assert accepted == 1
    assert rejected == 0
    assert changed
    loaded = store.load_profile("private_user_123")
    assert loaded.subject_key == store.subject_key("private_user_123")
    assert loaded.active_preferences()[0].value == "Avoid annual fees"
    path = next((tmp_path / "profiles").glob("*.json"))
    assert "private_user_123" not in path.name
    assert "private_user_123" not in path.read_text(encoding="utf-8")


def test_profile_gate_rejects_live_sensitive_and_inferred_memory():
    gate = ProfileMemoryGate()
    assert gate.accept(
        PreferenceCandidate(
            aspect="rewards",
            value="Prefer cash back",
            confidence=0.9,
            explicit=True,
        )
    )
    assert not gate.accept(
        PreferenceCandidate(
            aspect="general_preference",
            value="My current balance is 5000",
            confidence=0.9,
            explicit=True,
        )
    )
    assert not gate.accept(
        PreferenceCandidate(
            aspect="annual_fee",
            value="Avoid fees",
            confidence=0.9,
            explicit=False,
        )
    )


def test_profile_merger_supersedes_conflicting_active_preference():
    store = JsonMemoryStore("unused")
    profile = store.load_profile("user-a")
    merger = ProfileMerger()
    merger.merge(
        profile,
        [PreferenceCandidate(aspect="annual_fee", value="Avoid fees", polarity="AVOID", confidence=0.8)],
    )
    merger.merge(
        profile,
        [PreferenceCandidate(aspect="annual_fee", value="Fees are acceptable", polarity="PREFER", confidence=0.9)],
    )

    assert len(profile.preferences) == 2
    assert len(profile.active_preferences()) == 1
    assert profile.active_preferences()[0].value == "Fees are acceptable"


def test_episode_contains_no_facts_or_tool_arguments(tmp_path):
    state = make_state()
    state.facts.append(
        FactRecord(
            id="secret",
            entity="user",
            aspect="balance",
            value="99999",
            source="TOOL",
            turn_index=1,
            authoritative=True,
        )
    )
    episode = EpisodeFormer().form(
        episode_id="episode-1",
        subject_key="subject",
        state=state,
        final_message=AssistantMessage.text("Your current balance is 99999."),
    )

    assert episode is not None
    payload = json.dumps(episode.model_dump(mode="json"))
    assert "99999" not in payload
    assert "balance" not in payload


def test_episode_retrieval_is_user_scoped_and_goal_relevant(tmp_path):
    store = JsonMemoryStore(tmp_path)
    key = store.subject_key("user-a")
    store.upsert_episode(
        EpisodeMemory(
            episode_id="card",
            subject_key=key,
            objective="Compare personal cards",
            target="card",
            intent="INFORMATIONAL",
            outcome="ANSWERED",
            lesson="used sources=POLICY",
        )
    )
    store.upsert_episode(
        EpisodeMemory(
            episode_id="loan",
            subject_key=key,
            objective="Understand mortgage options",
            target="mortgage",
            intent="INFORMATIONAL",
            outcome="ANSWERED",
            lesson="used sources=POLICY",
        )
    )

    result = EpisodeRetriever().retrieve(store.load_episodes("user-a"), "Which card should I choose?")
    assert [item.episode_id for item in result] == ["card"]
    assert store.load_episodes("user-b") == []


def test_service_loads_cross_task_memory_without_injecting_facts(tmp_path):
    store = JsonMemoryStore(tmp_path)
    candidate = PreferenceCandidate(
        aspect="rewards",
        value="Prefer cash back",
        confidence=0.95,
        source_excerpt="I prefer cash back.",
    )
    first = MemoryService(store, ProfileMemoryManager(store, StaticExtractor([candidate])))
    first.bind("user-a")
    first.observe_user("I prefer cash back.", "target=card")
    state = make_state()
    first.record_episode(state, AssistantMessage.text("Here is the comparison."))

    second = MemoryService(store, ProfileMemoryManager(store, StaticExtractor([])))
    second.bind("user-a", query="compare cards")
    context = second.context()

    assert "Prefer cash back" in context
    assert "Compare cards with no annual fee" in context
    assert state.facts == []
    assert "NON-AUTHORITATIVE" in context


def test_memory_context_is_bounded_and_kept_separate_from_facts(tmp_path, tools):
    store = JsonMemoryStore(tmp_path)
    profile, _, _, _ = ProfileMemoryManager(store, StaticExtractor([])).apply(
        "user-a",
        [PreferenceCandidate(aspect="rewards", value="Prefer cash back", confidence=0.9)],
    )
    memory_context = render_memory_context(MemorySnapshot(profile=profile), max_chars=300)
    state = make_state()
    context = build_agent_context(
        state,
        tools,
        PolicyPilotConfig(memory_max_context_chars=300),
        memory_context=memory_context,
    )
    assert "long_term_memory" in context.structured_summary
    assert state.facts == []


def test_agent_profile_chain_uses_explicit_user_binding(tmp_path, tools):
    candidate = PreferenceCandidate(
        aspect="annual_fee",
        value="Avoid annual fees",
        polarity="AVOID",
        confidence=0.9,
        source_excerpt="I prefer to avoid annual fees.",
    )
    store = JsonMemoryStore(tmp_path)
    from policypilot.agent import PolicyPilotAgent
    agent = PolicyPilotAgent(
        tools=tools,
        domain_policy="policy",
        llm="test-model",
        config=PolicyPilotConfig(memory_dir=str(tmp_path)),
        memory_store=store,
        memory_user_id="user-a",
        memory_extractor=StaticExtractor([candidate]),
    )
    state = agent.get_init_state()
    agent._observe(UserMessage.text("I prefer to avoid annual fees."), state)

    assert store.load_profile("user-a").active_preferences()[0].aspect == "annual_fee"
    assert not any(fact.aspect == "annual_fee" for fact in state.facts)


def test_existing_profile_is_visible_to_planner_without_becoming_fact(tmp_path, tools):
    store = JsonMemoryStore(tmp_path)
    ProfileMemoryManager(store, StaticExtractor([])).apply(
        "user-a",
        [
            PreferenceCandidate(
                aspect="rewards",
                value="Prefer cash back",
                confidence=0.9,
            )
        ],
    )
    from policypilot.agent import PolicyPilotAgent

    agent = PolicyPilotAgent(
        tools=tools,
        domain_policy="policy",
        llm="test-model",
        config=PolicyPilotConfig(memory_dir=str(tmp_path)),
        memory_store=store,
        memory_user_id="user-a",
        memory_extractor=StaticExtractor([]),
    )
    state = agent.get_init_state()
    agent._observe(UserMessage.text("Compare card options."), state)

    assert "semantic_planner_memory_hints:1" in state.control.route_trace
    assert not any(fact.value == "Prefer cash back" for fact in state.facts)
