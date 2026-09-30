from __future__ import annotations

import json

from policypilot.observability.final_response_judge import (
    FinalResponseCriteria,
    FinalResponseJudge,
    build_judge_packet,
    load_final_response_gold,
)
from tau2.data_model.message import AssistantMessage


def test_final_response_gold_covers_the_67_need_gold_tasks():
    gold = load_final_response_gold()

    assert gold.selected_task_count == 67
    assert len(gold.tasks) == 67
    assert all(item.criteria.correctness for item in gold.tasks.values())
    assert all(item.criteria.completeness for item in gold.tasks.values())
    assert all(item.criteria.grounded_safety for item in gold.tasks.values())


def test_build_judge_packet_keeps_sources_separate():
    payload = {
        "simulations": [
            {
                "task_id": "task_001",
                "termination_reason": "agent_stop",
                "reward_info": {
                    "reward": 1.0,
                    "db_check": {"db_match": True},
                },
                "messages": [
                    {"role": "user", "content": "I prefer cashback."},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "name": "KB_search",
                                "arguments": {"query": "cashback cards"},
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "id": "call-1",
                        "content": "Gold has no annual fee for subscribers.",
                        "error": False,
                    },
                    {"role": "assistant", "content": "Gold is the best fit."},
                ],
            }
        ]
    }

    packet = build_judge_packet(payload)

    assert packet["final_response"] == "Gold is the best fit."
    assert packet["user_messages"][0]["content"] == "I prefer cashback."
    assert packet["executed_tool_calls"][0]["name"] == "KB_search"
    assert packet["authoritative_tool_results"][0]["id"] == "call-1"
    assert packet["tau3_result"]["db_match"] is True


def test_judge_computes_score_from_three_structured_verdicts():
    content = json.dumps(
        {
            "correctness": {
                "passed": True,
                "reason": "Supported.",
                "evidence_ids": ["message:1"],
            },
            "completeness": {
                "passed": False,
                "reason": "A material constraint was omitted.",
                "evidence_ids": [],
            },
            "grounded_safety": {
                "passed": True,
                "reason": "No unsupported live-state claim.",
                "evidence_ids": [],
            },
            "critical_error": "MISSED_REQUIREMENT",
        }
    )

    def fake_generate(**kwargs):
        assert kwargs["model"] == "deepseek/deepseek-chat"
        return AssistantMessage(
            role="assistant",
            content=content,
            usage={"prompt_tokens": 100, "completion_tokens": 40},
            cost=0.001,
            generation_time_seconds=0.2,
        )

    judge = FinalResponseJudge(generate_fn=fake_generate)
    result = judge.judge(
        task_id="task_001",
        criteria=FinalResponseCriteria(
            correctness="Correct.",
            completeness="Complete.",
            grounded_safety="Grounded.",
        ),
        packet={"final_response": "Answer"},
    )

    assert result.semantic_score == 2 / 3
    assert result.semantic_pass is False
    assert result.usage.input_tokens == 100
    assert result.usage.output_tokens == 40
