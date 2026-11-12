"""Build synthetic, policy-grounded frozen Decision I/O without model calls."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from policypilot.config import PolicyPilotConfig  # noqa: E402
from policypilot.evidence import EvidenceRecord, PolicyReference  # noqa: E402
from policypilot.observability.decision_prompt_eval import (  # noqa: E402
    DecisionExample,
    ExpectedDecision,
    digest,
)
from policypilot.prompts import DECISION_INSTRUCTIONS, build_system_prompt  # noqa: E402
from policypilot.state import FactRecord, PolicyPilotState, StructuredGoal  # noqa: E402
from policypilot.workflow.context import build_agent_context  # noqa: E402
from tau2.data_model.message import (  # noqa: E402
    AssistantMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from tau2.domains.banking_knowledge.tools import KnowledgeTools  # noqa: E402
from tau2.environment.tool import as_tool  # noqa: E402
from tau2.utils.llm_utils import to_litellm_messages  # noqa: E402

DEFAULT = ROOT / "data/policypilot/evaluation/decision_gepa_v1"
DOMAIN_NOTE = (
    "Banking Decision fixture. Apply the supplied policy evidence and verified "
    "observations. A proposed tool call is not a completed banking operation."
)


def build_examples(root: Path = ROOT) -> list[DecisionExample]:
    """Use real context construction and tool schemas over explicit synthetic state."""
    source = root / "data/policypilot/evaluation/decision_gepa_v1/scenarios.json"
    scenarios = json.loads(source.read_text(encoding="utf-8"))
    toolkit = object.__new__(KnowledgeTools)
    tool_names = {
        case[3]["tool"]
        for family in scenarios["families"]
        for case in family["cases"]
        if len(case) == 4
    }
    # Schema construction binds methods but never initializes a DB or calls tools.
    tools = [as_tool(getattr(toolkit, name)) for name in sorted(tool_names)]
    examples = []
    for family in scenarios["families"]:
        document_id = (
            "doc_bank_accounts_bank_accounts_(general)_" + family["document_suffix"]
        )
        path = (
            root
            / "data/tau2/domains/banking_knowledge/documents"
            / f"{document_id}.json"
        )
        document = json.loads(path.read_text(encoding="utf-8"))
        for index, case in enumerate(family["cases"], 1):
            question, facts, rubric, *action = case
            case_id = f"{family['id']}-{index:02d}"
            state = PolicyPilotState(
                run_id="decision-gepa-fixture",
                system_messages=[
                    SystemMessage(
                        role="system", content=build_system_prompt(DOMAIN_NOTE)
                    )
                ],
                goal=StructuredGoal(objective=question, target=document["title"]),
                intent="TRANSACTIONAL" if action else "INFORMATIONAL",
                facts=[
                    FactRecord(
                        id=f"{case_id}-fact-{i}",
                        entity=document["title"],
                        aspect=f"observation_{i}",
                        value=sentence,
                        source="TOOL",
                        turn_index=0,
                        authoritative=True,
                        evidence_ref="fixture-observation",
                    )
                    for i, sentence in enumerate(facts.split(". "))
                ],
                evidence=[
                    EvidenceRecord(
                        evidence_id="fixture-policy",
                        source_type="knowledge_retrieval",
                        turn_index=0,
                        tool_name="KB_search",
                        summary=document["content"],
                        policy_refs=[
                            PolicyReference(
                                document_id=document_id, title=document["title"]
                            )
                        ],
                    )
                ],
                messages=[
                    UserMessage.text(question),
                    AssistantMessage(
                        role="assistant",
                        tool_calls=[
                            ToolCall(
                                id="fixture-kb",
                                name="KB_search",
                                arguments={"query": document["title"]},
                                requestor="assistant",
                            )
                        ],
                    ),
                    ToolMessage(
                        role="tool",
                        id="fixture-kb",
                        requestor="assistant",
                        content=document["content"],
                    ),
                    UserMessage.text(question),
                ],
            )
            context = build_agent_context(state, tools, PolicyPilotConfig())
            payload = {
                "messages": to_litellm_messages(context.messages),
                "tools": [tool.openai_schema for tool in tools],
            }
            expected = ExpectedDecision(
                kind="tool_call" if action else "answer",
                rubric=rubric,
                **(action[0] if action else {}),
            )
            examples.append(
                DecisionExample(
                    id=case_id,
                    family=family["id"],
                    split=family["split"],
                    input=payload,
                    expected=expected,
                    provenance={
                        "origin": "synthetic_agent_authored_not_human_reviewed",
                        "document": str(path.relative_to(root)).replace("\\", "/"),
                        "document_sha256": digest(document),
                        "input_sha256": digest(payload),
                        "domain_policy": "minimal_fixture_not_full_runtime_policy",
                    },
                )
            )
    return examples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT)
    args = parser.parse_args()
    examples = build_examples()
    args.output.mkdir(parents=True, exist_ok=True)
    for split in ("train", "validation", "test"):
        rows = [e.model_dump() for e in examples if e.split == split]
        (args.output / f"{split}.jsonl").write_text(
            "".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                for row in rows
            ),
            encoding="utf-8",
            newline="\n",
        )
    (args.output / "seed_prompt.txt").write_text(
        DECISION_INSTRUCTIONS + "\n", encoding="utf-8", newline="\n"
    )
    manifest = {
        "schema_version": "decision-gepa-v1",
        "created": "2026-10-22",
        "counts": dict(Counter(e.split for e in examples)),
        "action_counts": dict(Counter(e.expected.kind for e in examples)),
        "family_count": len({e.family for e in examples}),
        "split_unit": "policy_document_and_scenario_family",
        "dataset_sha256": digest([e.model_dump() for e in examples]),
        "seed_sha256": digest(DECISION_INSTRUCTIONS),
        "limits": [
            "synthetic_not_real_rollouts",
            "not_human_reviewed",
            "no_benchmark_reward_claim",
            "minimal_domain_policy",
            "fixed_tool_subset",
            "no_environment_execution",
        ],
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
