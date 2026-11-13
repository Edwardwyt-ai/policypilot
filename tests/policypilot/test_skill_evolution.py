from pathlib import Path

import pytest

from policypilot.skills.evolution import detect_signals
from policypilot.skills.evolution_models import (
    Candidate,
    EvidenceSource,
    EvolutionConfig,
    Extraction,
    Pattern,
    Proposal,
    SkillSpec,
    Trigger,
)
from policypilot.skills.experience import Discovery, ExperienceStore
from policypilot.skills.library import SkillLibrary, preview
from policypilot.skills.loader import SkillLoader
from policypilot.skills.runtime import SkillRuntime
from policypilot.skills.skill_evaluation import (
    EvaluationPlan,
    Observation,
    PromotionPolicy,
    Trial,
)
from policypilot.state import PolicyPilotState


def test_discovery_counts_independent_tasks_and_updates_changed_sources(tmp_path):
    store = ExperienceStore(tmp_path / "experience.sqlite")
    calls = []

    def extract(source):
        calls.append(source.source_id)
        return Extraction(
            patterns=[
                Pattern(
                    kind="SUCCESS_STRATEGY",
                    behavior_key="verify-before-answer",
                    steps=["read authoritative status", "explain verified status"],
                    lesson="Use the read result to explain status",
                    evidence_indexes=[0, 1],
                )
            ]
        )

    config = EvolutionConfig(min_success_tasks=2)
    discovery = Discovery(store, extract, config=config)
    first = EvidenceSource(
        kind="trajectory",
        source_id="first",
        trace_id="first",
        task_id="A",
        task_type="status",
        success=True,
        observations=["read status", "explained status"],
    )
    second = first.model_copy(update={"source_id": "second", "trace_id": "second"})
    discovery.ingest([first, second])
    assert not list(detect_signals(store, config))
    discovery.ingest([first, second])
    assert calls == ["first", "second"]
    discovery.ingest([second.model_copy(update={"task_id": "B"})])
    assert calls == ["first", "second", "second"]
    signals = list(detect_signals(store, config))
    assert len(signals) == 1
    assert len(store.members(signals[0].cluster_id)) == 2


def test_publication_requires_independent_ab_and_supports_rollback(
    tmp_path, monkeypatch
):
    library = SkillLibrary(tmp_path / "library.sqlite")
    base = library.active()
    spec = SkillSpec(
        skill_id="status-verification",
        description="Verify status from a trusted observation",
        trigger=Trigger(
            intents=["STATUS_CHECK"], targets=[], need_sources=[], recovery_modes=[]
        ),
        preconditions=["goal"],
        procedure=["Read current status", "Report observed status"],
    )
    candidate = Candidate(
        candidate_id="example-candidate",
        base_release=base.id,
        cluster_id="example-cluster",
        proposal=Proposal(
            operation="CREATE", targets=[], skill=spec, rationale="Repeated evidence"
        ),
        evidence_ids=["e1"],
        trace_ids=["trace-training"],
        training_task_ids=["training"],
    )
    library.propose(candidate)
    loader = SkillLoader(root=Path(tmp_path), release=library.active())
    assert loader.load(spec.skill_id) is None
    after = preview(base, candidate, set())
    monkeypatch.setenv("POLICYPILOT_SKILL_LIBRARY", str(library.path))
    monkeypatch.setenv("POLICYPILOT_SKILL_EVAL_CANDIDATE", candidate.candidate_id)
    monkeypatch.delenv("POLICYPILOT_SKILL_EVAL", raising=False)
    assert SkillLoader().load(spec.skill_id) is None
    monkeypatch.setenv("POLICYPILOT_SKILL_EVAL", "1")
    assert SkillLoader().load(spec.skill_id) is not None
    assert library.active().id == base.id
    monkeypatch.delenv("POLICYPILOT_SKILL_EVAL")
    plan = EvaluationPlan(
        configuration_id="shared-config",
        reviewed_non_redundant=True,
        builtin_ids=[],
        trials=[
            Trial(
                task_id="A",
                seed=1,
                expected_before=[],
                expected_after=[spec.skill_id],
                expected_after_tool_sequence=["status"],
            ),
            Trial(task_id="B", seed=1, expected_before=[], expected_after=[]),
        ],
    )
    rows = [
        Observation(
            arm=arm,
            release_id=(base if arm == "baseline" else after).id,
            configuration_id=plan.configuration_id,
            task_id=task,
            seed=1,
            trace_id=f"{arm}-{task}",
            source=f"{arm}/{task}/results.json",
            selected={spec.skill_id} if arm == "candidate" and task == "A" else set(),
            retrieved={spec.skill_id} if arm == "candidate" and task == "A" else set(),
            executed_tools=["status"],
            tokens=100,
            latency=1.0,
            tool_calls=1,
            success=arm == "candidate" or task == "B",
        )
        for arm in ("baseline", "candidate")
        for task in ("A", "B")
    ]
    policy = PromotionPolicy(min_tasks=2)
    leaked = plan.model_copy(
        update={
            "trials": [
                plan.trials[0].model_copy(update={"task_id": "training"}),
                plan.trials[1],
            ]
        }
    )
    with pytest.raises(ValueError, match="Independent"):
        library.promote(candidate.candidate_id, leaked, rows, policy)
    with pytest.raises(ValueError, match="exactly one"):
        library.promote(candidate.candidate_id, plan, rows[:-1], policy)
    wrong = [*rows[:-1], rows[-1].model_copy(update={"selected": {spec.skill_id}})]
    with pytest.raises(ValueError, match="negative"):
        library.promote(candidate.candidate_id, plan, wrong, policy)
    assert library.active().id == base.id
    assert library.promote(candidate.candidate_id, plan, rows, policy).id == after.id

    runtime = SkillRuntime(loader=SkillLoader(root=tmp_path, release=library.active()))
    state = PolicyPilotState(system_messages=[], intent="STATUS_CHECK")
    runtime.refresh(state, event="NEW_GOAL")
    assert not runtime.selected
    state.goal.objective = "Check card status"
    runtime.refresh(state, event="TASK_STATE_CHANGED")
    assert "Read current status" in runtime.guidance("decision", state)
    assert spec.skill_id in state.control.active_skill_versions
    assert runtime.snapshot()["activated_versions"][spec.skill_id]
    assert library.rollback(base.id).id == base.id
