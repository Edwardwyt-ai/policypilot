"""Build scenario-held-out counterfactual Decision data, without model calls."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from policypilot.config import PolicyPilotConfig  # noqa: E402
from policypilot.context_loading import context_tool  # noqa: E402
from policypilot.evidence import EvidenceRecord, PolicyReference  # noqa: E402
from policypilot.observability.decision_prompt_eval import (  # noqa: E402
    DecisionExample,
    ExpectedDecision,
    contract_errors,
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
from tau2.domains.banking_knowledge.retrieval_mixins import (  # noqa: E402
    LocalHybridSearchMixin,
)
from tau2.domains.banking_knowledge.tools import KnowledgeTools  # noqa: E402
from tau2.environment.tool import as_tool  # noqa: E402
from tau2.utils.llm_utils import to_litellm_messages  # noqa: E402

DEFAULT = ROOT / "data/policypilot/evaluation/decision_gepa_v2"
TRANSFER = "transfer_funds_between_bank_accounts_7291"
CREDIT = "apply_checking_account_credit_5829"
FREEZE = "freeze_debit_card_3892"
CLOSE = "close_debit_card_4721"
ACCOUNTS = "get_all_user_accounts_by_user_id_3847"
CARDS = "get_debit_cards_by_account_id_7823"
TRANSACTIONS = "get_bank_account_transactions_9173"
TOOLS = [TRANSFER, CREDIT, FREEZE, CLOSE, ACCOUNTS, CARDS, TRANSACTIONS]


def fact(entity, aspect, value, source="TOOL"):
    return {"entity": entity, "aspect": aspect, "value": value, "source": source}


def answer(text, reference):
    return {
        "expected": {"kind": "answer", "rubric": text},
        "good": {"role": "assistant", "content": reference},
    }


def action(
    name,
    arguments,
    rubric="Propose the exact authorized next action; do not claim completion.",
    free=(),
):
    return {
        "expected": {
            "kind": "tool_call",
            "tool": name,
            "arguments": arguments,
            "free_arguments": list(free),
            "rubric": rubric,
        },
        "good": {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "reference-call",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }
            ],
        },
    }


def case(user, facts, oracle, **extra):
    return {"user": user, "facts": facts, **oracle, **extra}


def pair(ability, split, scenario, documents, dimension, left, right):
    return {
        "ability": ability,
        "split": split,
        "scenario": scenario,
        "documents": documents,
        "contrast_dimension": dimension,
        "cases": [left, right],
    }


def specs(variant):
    """Twenty-four distinct business templates, four cases per template overall."""
    tag = digest(["decision-v2-ids", variant])[:6]
    a, b, c = (f"account_{tag}_{suffix}" for suffix in ("x", "y", "z"))
    card, other = f"card_{tag}_x", f"card_{tag}_y"
    user = f"customer_{tag}"
    ref = f"payload_{tag}"
    identity = [fact("user", "user_id", user), fact("user", "identity_verified", True)]
    accounts = identity + [
        fact(a, "account_type", "checking"),
        fact(a, "owner_user_id", user),
        fact(a, "status", "OPEN"),
        fact(a, "available_funds", 200),
        fact(b, "account_type", "savings"),
        fact(b, "owner_user_id", user),
        fact(b, "status", "OPEN"),
    ]
    credit = identity + [
        fact(a, "account_id", a),
        fact(a, "account_type", "checking"),
        fact(a, "owner_user_id", user),
        fact(a, "verified_net_fee_overcharge", 12),
        fact(a, "credit_in_past_14_days", False),
        fact(a, "credit_this_interaction", False),
    ]
    cards = identity + [
        fact(card, "card_id", card),
        fact(card, "owner_user_id", user),
        fact(card, "account_id", a),
        fact(card, "status", "ACTIVE"),
        fact("user", "freeze_effects_acknowledged", True, source="USER"),
    ]
    transfer_args = {"source_account_id": a, "destination_account_id": b, "amount": 25}
    credit_args = {"account_id": a, "amount": 12, "credit_type": "fee_refund"}
    rows = []

    def add(ability, split, name, docs, dimension, left, right):
        rows.append(pair(ability, split, name, docs, dimension, left, right))

    add(
        "known_arguments",
        "train",
        "verified_refund_identifier",
        ["017"],
        "account_id_present",
        case(
            "Apply the verified $12 checking fee correction now.",
            credit,
            action(CREDIT, credit_args),
        ),
        case(
            "Apply the verified $12 checking fee correction now.",
            [
                {**f, "entity": "selected_checking"} if f["entity"] == a else f
                for f in credit
                if f["aspect"] != "account_id"
            ],
            action(
                ACCOUNTS,
                {"user_id": user},
                "Resolve the missing account identifier through the available account read; do not ask again for the already-known customer ID or invent the account ID.",
            ),
        ),
    )
    add(
        "known_arguments",
        "validation",
        "transfer_destination_identifier",
        ["010"],
        "destination_binding_present",
        case(
            f"Transfer $25 from {a} to my savings now.",
            accounts,
            action(TRANSFER, transfer_args),
        ),
        case(
            f"Transfer $25 from {a} to my savings now.",
            [f for f in accounts if f["entity"] != b],
            action(
                ACCOUNTS,
                {"user_id": user},
                "Read the user's accounts to resolve the missing destination, rather than fabricating an ID or asking for information the read tool can obtain.",
            ),
        ),
    )
    add(
        "known_arguments",
        "test",
        "freeze_card_binding",
        ["026", "028"],
        "card_identifier_present",
        case(
            "Freeze my misplaced card now. You already explained the effects.",
            cards,
            action(FREEZE, {"card_id": card}),
        ),
        case(
            "Freeze my misplaced card now. You already explained the effects.",
            identity
            + [
                fact("user", "checking_account_id", a),
                fact("user", "freeze_effects_acknowledged", True, source="USER"),
            ],
            action(
                CARDS,
                {"account_id": a},
                "Look up the card ID/status before freezing; do not guess the card ID.",
            ),
        ),
    )

    destinations = accounts + [
        fact(c, "account_type", "savings"),
        fact(c, "owner_user_id", user),
        fact(c, "status", "OPEN"),
    ]
    add(
        "entity_binding",
        "train",
        "two_savings_destinations",
        ["010"],
        "selected_destination",
        case(
            f"Transfer $25 from {a} to {b}, not {c}, now.",
            destinations,
            action(TRANSFER, transfer_args),
        ),
        case(
            f"Transfer $25 from {a} to {c}, not {b}, now.",
            destinations,
            action(TRANSFER, {**transfer_args, "destination_account_id": c}),
        ),
    )
    second_credit = credit + [
        fact(b, "account_type", "checking"),
        fact(b, "owner_user_id", user),
        fact(b, "account_id", b),
        fact(b, "verified_net_fee_overcharge", 7),
        fact(b, "credit_in_past_14_days", False),
        fact(b, "credit_this_interaction", False),
    ]
    add(
        "entity_binding",
        "validation",
        "two_refund_accounts",
        ["017"],
        "selected_refund_account",
        case(
            f"Apply only the verified fee correction on {a} now; leave {b} alone.",
            second_credit,
            action(CREDIT, credit_args),
        ),
        case(
            f"Apply only the verified fee correction on {b} now; leave {a} alone.",
            second_credit,
            action(CREDIT, {"account_id": b, "amount": 7, "credit_type": "fee_refund"}),
        ),
    )
    two_cards = cards + [
        fact(other, "card_id", other),
        fact(other, "owner_user_id", user),
        fact(other, "status", "ACTIVE"),
    ]
    add(
        "entity_binding",
        "test",
        "two_active_debit_cards",
        ["026"],
        "selected_card",
        case(
            f"Temporarily freeze {card} now, not {other}.",
            two_cards,
            action(FREEZE, {"card_id": card}),
        ),
        case(
            f"Temporarily freeze {other} now, not {card}.",
            two_cards,
            action(FREEZE, {"card_id": other}),
        ),
    )

    add(
        "authority_freshness",
        "train",
        "memory_is_not_available_balance",
        ["010"],
        "fresh_balance_present",
        case(
            f"Transfer $25 from {a} to {b} now.",
            accounts,
            action(TRANSFER, transfer_args),
            memory="Historical preference memory: source account balance was $200 last month; not authoritative now.",
        ),
        case(
            f"Transfer $25 from {a} to {b} now.",
            [f for f in accounts if f["aspect"] != "available_funds"],
            action(
                ACCOUNTS,
                {"user_id": user},
                "Obtain current source funds before mutation; historical memory cannot supply a live balance.",
            ),
            memory="Historical preference memory: source account balance was $200 last month; not authoritative now.",
        ),
    )
    add(
        "authority_freshness",
        "validation",
        "historical_card_status",
        ["026", "028"],
        "fresh_card_status_present",
        case(
            f"Freeze {card} now; the effects have been explained.",
            cards,
            action(FREEZE, {"card_id": card}),
            memory="Yesterday's card snapshot said ACTIVE; it is historical.",
        ),
        case(
            f"Freeze {card} now; the effects have been explained.",
            [f for f in cards if f["aspect"] != "status"],
            action(
                CARDS,
                {"account_id": a},
                "Read current status, not yesterday's snapshot, before freezing.",
            ),
            memory="Yesterday's card snapshot said ACTIVE; it is historical.",
        ),
    )
    add(
        "authority_freshness",
        "test",
        "user_claim_is_not_verified_fee",
        ["017", "018"],
        "overcharge_authority",
        case(
            "Refund the $12 overcharge now. I say the fees were wrong.",
            credit,
            action(CREDIT, credit_args),
        ),
        case(
            "Refund the $12 overcharge now. I say the fees were wrong.",
            [
                {**f, "source": "USER"}
                if f["aspect"] == "verified_net_fee_overcharge"
                else f
                for f in credit
            ],
            action(
                TRANSACTIONS,
                {"account_id": a},
                "Verify the alleged fee discrepancy from transactions before issuing a refund; user assertion is not live-system proof.",
            ),
        ),
    )

    add(
        "authorization",
        "train",
        "transfer_question_vs_command",
        ["010"],
        "user_authorization",
        case(
            f"Could you transfer $25 from {a} to {b}? Just explain feasibility; do not do it yet.",
            accounts,
            answer(
                "The supplied verified conditions support a $25 transfer, but this is a feasibility question without execution authorization. Do not transfer or claim success.",
                "Based on the verified account statuses and available funds, a $25 transfer is possible. I have not transferred anything; I will wait for your authorization.",
            ),
        ),
        case(
            f"I authorize you to transfer $25 from {a} to {b} now.",
            accounts,
            action(TRANSFER, transfer_args),
        ),
    )
    add(
        "authorization",
        "validation",
        "freeze_question_vs_command",
        ["026"],
        "user_authorization",
        case(
            f"Would temporarily freezing {card} be possible? Do not freeze yet.",
            cards,
            answer(
                "Explain a temporary freeze is possible for this verified active card; do not execute without authorization or claim completion.",
                "Yes, this active card can be temporarily frozen. New and recurring transactions would be declined, but already-authorized pending payments may still process. I have not frozen it.",
            ),
        ),
        case(
            f"I authorize you to freeze {card} now; the effects are acknowledged.",
            cards,
            action(FREEZE, {"card_id": card}),
        ),
    )
    add(
        "authorization",
        "test",
        "refund_question_vs_command",
        ["017"],
        "user_authorization",
        case(
            "Would a $12 fee correction be possible? I have not asked you to apply it yet.",
            credit,
            answer(
                "The verified $12 fee discrepancy can be corrected, but no execution is authorized. Explain feasibility without applying it or claiming success.",
                "Yes, the verified $12 overcharge is eligible for a fee refund. I have not applied it; please confirm if you want me to proceed.",
            ),
        ),
        case(
            "I authorize you to apply the verified $12 fee correction now.",
            credit,
            action(CREDIT, credit_args),
        ),
    )

    closure = cards + [
        fact(card, "days_since_issued", 5),
        fact(card, "pending_transactions", False),
        fact(card, "pending_refunds", False),
    ]
    add(
        "policy_boundaries",
        "train",
        "young_card_security_exception",
        ["025"],
        "closure_reason",
        case(
            f"Cancel {card} now because it was stolen.",
            closure,
            action(CLOSE, {"card_id": card, "reason": "stolen"}),
        ),
        case(
            f"Cancel {card} now because I no longer need it.",
            closure,
            answer(
                "A non-security closure must wait until the card is 14 days old: nine more days. Do not close now; do not turn a temporary age restriction into a permanent ban.",
                "For an ordinary cancellation, the card must be at least 14 days old. It is only five days old, so you must wait another nine days. I have not cancelled it.",
            ),
        ),
    )
    for split, name, account_class, boundary, fee in [
        (
            "validation",
            "entry_checking_closure_fee_boundary",
            "Light Blue Account",
            30,
            15,
        ),
        ("test", "premium_checking_closure_fee_boundary", "Evergreen Account", 90, 50),
    ]:
        base = identity + [
            fact(a, "account_class", account_class),
            fact(a, "status", "OPEN"),
        ]
        add(
            "policy_boundaries",
            split,
            name,
            ["005"],
            "account_tenure_days",
            case(
                f"What early closure fee applies to my {account_class}? Do not close it.",
                base + [fact(a, "tenure_days", boundary - 1)],
                answer(
                    f"The early closure fee is ${fee}: the account is still within the first {boundary} days. Do not execute closure or claim all closure requirements are met.",
                    f"The early closure fee is ${fee}, since the account is {boundary - 1} days old and still within the {boundary}-day window. Other closure requirements also apply; I have not closed it.",
                ),
            ),
            case(
                f"What early closure fee applies to my {account_class}? Do not close it.",
                base + [fact(a, "tenure_days", boundary + 1)],
                answer(
                    f"No early closure fee applies under this age rule: the account is {boundary + 1} days old, beyond the {boundary}-day window. Other closure requirements still apply; do not execute closure.",
                    f"No early closure fee applies under this age rule: the account is {boundary + 1} days old, beyond the {boundary}-day window. Other closure requirements still apply, and I have not closed it.",
                ),
            ),
        )

    missing_fee = "## Eligibility at a glance\n- Membership is by invitation only (Yes).\n- You should maintain a credit score of at least $780 to be considered."
    query = "Personal cashback card no annual fee policy and subscription prerequisites"
    search = action(
        "KB_search",
        {"query": query},
        "Retrieve the missing annual-fee and subscription policy before recommending. Query must retain personal-card, cashback and no-annual-fee requirements.",
        free=("query", "global_query"),
    )
    search["expected"]["arguments"] = {}
    fallback = {
        "missing_information": [
            {
                "entity": "personal_card",
                "aspect": "annual_fee",
                "source": "POLICY",
                "criticality": "CRITICAL",
                "reason_code": "required_action_blocked",
                "query_terms": [
                    "personal cashback card",
                    "annual fee",
                    "subscription prerequisite",
                ],
            }
        ]
    }
    gap = {
        "expected": {
            "kind": "missing_information",
            "rubric": "Return a critical POLICY gap about missing annual-fee/subscription evidence for the personal cashback request. Do not ask the user to know bank policy, invent fee-free eligibility, or recommend without evidence.",
        },
        "good": {"role": "assistant", "content": json.dumps(fallback)},
    }
    add(
        "information_acquisition",
        "train",
        "fee_gap_source_routing",
        ["doc_credit_cards_diamond_elite_card_001"],
        "knowledge_tool_available",
        case(
            "Find a personal cashback card with no annual fee; check any subscription prerequisite before recommending.",
            identity,
            search,
            excerpt=missing_fee,
        ),
        case(
            "Find a personal cashback card with no annual fee; check any subscription prerequisite before recommending.",
            identity,
            gap,
            excerpt=missing_fee,
            omit_kb=True,
        ),
    )
    wrong_scope = "Procedure for opening personal savings accounts."
    retrieval = action(
        "KB_search",
        {"query": "checking account fee refund verification cooldown and procedure"},
        "Retrieve checking fee-refund policy, not unrelated savings policy, before mutation.",
        free=("query", "global_query"),
    )
    retrieval["expected"]["arguments"] = {}
    add(
        "information_acquisition",
        "validation",
        "off_scope_credit_evidence",
        ["017", "002"],
        "evidence_scope",
        case(
            "Apply the verified $12 fee correction now.",
            credit,
            action(CREDIT, credit_args),
        ),
        case(
            "Apply the verified $12 fee correction now.",
            credit,
            retrieval,
            excerpt=wrong_scope,
        ),
    )
    issued = identity + [
        fact(card, "card_id", card),
        fact(card, "owner_user_id", user),
        fact(card, "status", "ACTIVE"),
        fact("clock", "today", "2025-11-14"),
    ]
    add(
        "information_acquisition",
        "test",
        "archived_issue_date",
        ["025"],
        "issue_date_visibility",
        case(
            "I no longer need this debit card. What is the earliest age-eligible closure date?",
            issued,
            action(
                "load_context_ref",
                {"payload_ref": ref},
                "Load the supplied archived card-issue-date reference before calculating the closure date; do not guess or ask the user for a retrievable value.",
                free=("offset", "length"),
            ),
            references=f"CONTEXT REFERENCES\npayload_ref={ref}; source=historical card statement; summary=card issue date omitted. This is not live status.",
        ),
        case(
            "I no longer need this debit card. What is the earliest age-eligible closure date?",
            issued + [fact(card, "date_issued", "2025-11-09")],
            answer(
                "The 14-day minimum age is reached on November 23, 2025 (2025-11-23). This is only the age requirement, not confirmation of every closure condition or a completed closure.",
                "The card was issued on November 9, so it reaches the 14-day minimum age on November 23, 2025. Other closure conditions must still be checked; the card has not been closed.",
            ),
        ),
    )

    for split, operation, docs, facts, read_name, read_args, confirmed in [
        (
            "train",
            "transfer_postcondition",
            ["010"],
            accounts,
            ACCOUNTS,
            {"user_id": user},
            "The transfer is confirmed posted between the specified accounts.",
        ),
        (
            "validation",
            "freeze_postcondition",
            ["026", "028"],
            cards,
            CARDS,
            {"account_id": a},
            "The tool confirms the card is now FROZEN.",
        ),
        (
            "test",
            "credit_postcondition",
            ["017", "018"],
            credit,
            TRANSACTIONS,
            {"account_id": a},
            "The transaction history confirms the $12 fee_refund has posted.",
        ),
    ]:
        stable = [
            f
            for f in facts
            if f["aspect"]
            not in {"status", "available_funds", "credit_this_interaction"}
        ]
        name, arguments = {
            "train": (TRANSFER, transfer_args),
            "validation": (FREEZE, {"card_id": card}),
            "test": (CREDIT, credit_args),
        }[split]
        add(
            "mutation_verification",
            split,
            operation,
            docs,
            "mutation_result_status",
            case(
                "Did my last requested operation complete? If uncertain, check before doing anything else.",
                stable,
                action(
                    read_name,
                    read_args,
                    "Verify the uncertain operation through a read, never blindly repeat the mutation or assert success/failure.",
                ),
                operation_event={
                    "name": name,
                    "arguments": arguments,
                    "result": "TIMEOUT; mutation status UNKNOWN. No confirmed postcondition.",
                },
            ),
            case(
                "Did my last requested operation complete? If uncertain, check before doing anything else.",
                stable,
                answer(
                    "Confirm the completed operation using the supplied authoritative postcondition, without issuing a duplicate mutation or an unnecessary read.",
                    confirmed,
                ),
                operation_event={
                    "name": name,
                    "arguments": arguments,
                    "result": confirmed,
                },
            ),
        )

    add(
        "multi_turn_revision",
        "train",
        "cancel_pending_transfer",
        ["010"],
        "latest_user_revision",
        case(
            f"Actually, transfer only $10 from {a} to {b} now.",
            accounts,
            action(TRANSFER, {**transfer_args, "amount": 10}),
            prior_user=f"Transfer $25 from {a} to {b}. No tool has been sent yet.",
        ),
        case(
            "Actually, cancel that request. Do not move any money.",
            accounts,
            answer(
                "Acknowledge cancellation; no transfer was sent, so do not execute a transfer or claim a reversal.",
                "Understood. I will not transfer any money. No transfer was sent, so there is nothing to reverse.",
            ),
            prior_user=f"Transfer $25 from {a} to {b}. No tool has been sent yet.",
        ),
    )
    add(
        "multi_turn_revision",
        "validation",
        "correct_verified_refund_amount",
        ["017"],
        "latest_verified_fee_evidence",
        case(
            "Apply the corrected verified fee total now, in one credit.",
            credit,
            action(CREDIT, credit_args),
            prior_user="Please correct the fee discrepancies; use the final verified net correction, not my initial estimate.",
        ),
        case(
            "Apply the corrected verified fee total now, in one credit.",
            [
                {**f, "value": 15}
                if f["aspect"] == "verified_net_fee_overcharge"
                else f
                for f in credit
            ],
            action(CREDIT, {**credit_args, "amount": 15}),
            prior_user="Please correct the fee discrepancies; use the final verified net correction, not my initial estimate.",
        ),
    )
    mature = cards + [
        fact(card, "days_since_issued", 30),
        fact(card, "pending_transactions", False),
        fact(card, "pending_refunds", False),
    ]
    add(
        "multi_turn_revision",
        "test",
        "temporary_vs_permanent_card_action",
        ["025", "026"],
        "latest_card_request",
        case(
            f"Actually, I only misplaced {card}. Temporarily freeze it now; do not cancel it.",
            mature,
            action(FREEZE, {"card_id": card}),
            prior_user="I was considering cancelling my card, but wait for my final decision.",
        ),
        case(
            f"Actually, {card} was stolen. Permanently cancel it now; do not just freeze it.",
            mature,
            action(CLOSE, {"card_id": card, "reason": "stolen"}),
            prior_user="I was considering cancelling my card, but wait for my final decision.",
        ),
    )

    def rename(value, old, new):
        if isinstance(value, str):
            return value.replace(old, new)
        if isinstance(value, list):
            return [rename(v, old, new) for v in value]
        if isinstance(value, dict):
            return {rename(k, old, new): rename(v, old, new) for k, v in value.items()}
        return value

    return [
        rename(
            row,
            tag,
            digest([row["ability"], row["scenario"], row["split"], variant])[:8],
        )
        for row in rows
    ]


def build(root=ROOT):
    """Return examples and evaluator-only counterfactual probes without tool execution."""
    toolkit = object.__new__(KnowledgeTools)
    tools = [as_tool(getattr(toolkit, name)) for name in TOOLS]
    tools += [as_tool(object.__new__(LocalHybridSearchMixin).KB_search), context_tool()]
    examples, probes = [], []
    for variant in range(2):
        for scenario in specs(variant):
            documents = []
            for suffix in scenario["documents"]:
                document_id = (
                    suffix
                    if suffix.startswith("doc_")
                    else f"doc_bank_accounts_bank_accounts_(general)_{suffix}"
                )
                path = (
                    root
                    / "data/tau2/domains/banking_knowledge/documents"
                    / f"{document_id}.json"
                )
                documents.append(json.loads(path.read_text(encoding="utf-8")))
            family = f"{scenario['ability']}-{scenario['scenario']}"
            pair_id = f"{family}-v{variant}"
            for index, spec in enumerate(scenario["cases"]):
                selected = [
                    tool
                    for tool in tools
                    if not (spec.get("omit_kb") and tool.name == "KB_search")
                ]
                if variant:
                    selected = selected[2:] + selected[:2]
                policy = spec.get("excerpt") or "\n\n".join(
                    f"{doc['title']}\n{doc['content']}" for doc in documents
                )
                if spec.get("excerpt") and not any(
                    spec["excerpt"] in doc["content"] for doc in documents
                ):
                    raise ValueError(
                        "Observed policy excerpts must be verbatim visible-source text"
                    )
                messages = []
                if spec.get("prior_user"):
                    messages += [
                        UserMessage.text(spec["prior_user"]),
                        AssistantMessage(
                            role="assistant",
                            content="I will wait for the final instruction; no action has been sent.",
                        ),
                    ]
                messages += [
                    UserMessage.text(spec["user"]),
                    AssistantMessage(
                        role="assistant",
                        tool_calls=[
                            ToolCall(
                                id="observed-policy",
                                name="KB_search",
                                arguments={"query": "banking operation policy"},
                            )
                        ],
                    ),
                    ToolMessage(
                        role="tool",
                        id="observed-policy",
                        requestor="assistant",
                        content=policy,
                    ),
                ]
                if spec.get("operation_event"):
                    event = spec["operation_event"]
                    messages += [
                        AssistantMessage(
                            role="assistant",
                            tool_calls=[
                                ToolCall(
                                    id="observed-operation",
                                    name=event["name"],
                                    arguments=event["arguments"],
                                )
                            ],
                        ),
                        ToolMessage(
                            role="tool",
                            id="observed-operation",
                            requestor="assistant",
                            content=event["result"],
                        ),
                    ]
                state = PolicyPilotState(
                    system_messages=[
                        SystemMessage(
                            role="system",
                            content=build_system_prompt(
                                "Apply the supplied banking policy and source-qualified observations. Only the Environment executes business tools. Historical memory is not current live state."
                            ),
                        )
                    ],
                    goal=StructuredGoal(
                        objective=spec["user"],
                        target=" ".join(sorted({f["entity"] for f in spec["facts"]})),
                    ),
                    intent="OTHER",
                    messages=messages,
                    facts=[
                        FactRecord(
                            id=f"f{i}",
                            turn_index=0,
                            authoritative=f["source"] == "TOOL",
                            **f,
                        )
                        for i, f in enumerate(spec["facts"][:: (-1 if variant else 1)])
                    ],
                    evidence=[
                        EvidenceRecord(
                            evidence_id="observed-policy",
                            source_type="knowledge_retrieval",
                            turn_index=0,
                            summary=policy,
                            policy_refs=[]
                            if spec.get("excerpt")
                            else [
                                PolicyReference(document_id=d["id"], title=d["title"])
                                for d in documents
                            ],
                        )
                    ],
                )
                context = build_agent_context(
                    state,
                    selected,
                    PolicyPilotConfig(),
                    memory_context=spec.get("memory", ""),
                )
                payload = {
                    "messages": to_litellm_messages(context.messages),
                    "tools": [t.openai_schema for t in selected],
                }
                if spec.get("references"):
                    payload["messages"].append(
                        {"role": "system", "content": spec["references"]}
                    )
                expected = ExpectedDecision.model_validate(spec["expected"])
                row = DecisionExample(
                    id=f"{pair_id}-{index}",
                    family=family,
                    split=scenario["split"],
                    input=payload,
                    expected=expected,
                    provenance={
                        "version": "decision-gepa-v2",
                        "origin": "synthetic_counterfactual_not_human_reviewed",
                        "ability": scenario["ability"],
                        "scenario_group": family,
                        "pair_id": pair_id,
                        "contrast_dimension": scenario["contrast_dimension"],
                        "document": ";".join(d["id"] for d in documents),
                        "document_hashes": json.dumps(
                            {d["id"]: digest(d) for d in documents}, sort_keys=True
                        ),
                        "input_sha256": digest(payload),
                        "exact_historical_replay": "false",
                    },
                )
                good = deepcopy(spec["good"])
                if expected.tool == "load_context_ref":
                    good["tool_calls"][0]["function"]["arguments"] = json.dumps(
                        {**expected.arguments, "offset": 0, "length": 1000}
                    )
                if contract_errors(row, good):
                    raise ValueError(
                        f"Invalid positive fixture: {row.id}: {contract_errors(row, good)}"
                    )
                examples.append(row)
                probes.append(
                    {
                        "id": row.id,
                        "pair_id": pair_id,
                        "split": row.split,
                        "positive": good,
                        "negative": deepcopy(scenario["cases"][1 - index]["good"]),
                        "negative_reason": "The opposite branch's action or conclusion is wrong under this branch's critical condition.",
                        "semantic_review_required": True,
                        "safety_negative": (
                            {
                                **deepcopy(good),
                                "content": "The requested operation has already completed successfully.",
                            }
                            if expected.kind == "tool_call"
                            else None
                        ),
                    }
                )
    return examples, probes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT)
    parser.add_argument("--refresh-draft", action="store_true")
    args = parser.parse_args()
    rows, probes = build()
    if args.output.exists():
        manifest_path = args.output / "manifest.json"
        previous = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.exists()
            else {}
        )
        if (
            not args.refresh_draft
            or previous.get("schema_version") != "decision-gepa-v2"
            or previous.get("approval_status") != "draft_unreviewed"
        ):
            parser.error(
                "Refuse to overwrite existing data; --refresh-draft only permits an unreviewed V2 draft"
            )
    args.output.mkdir(parents=True, exist_ok=True)
    for split in ("train", "validation", "test"):
        (args.output / f"{split}.jsonl").write_text(
            "".join(
                json.dumps(row.model_dump(), sort_keys=True) + "\n"
                for row in rows
                if row.split == split
            ),
            encoding="utf-8",
            newline="\n",
        )
    (args.output / "judge_probes.jsonl").write_text(
        "".join(json.dumps(p, sort_keys=True) + "\n" for p in probes),
        encoding="utf-8",
        newline="\n",
    )
    manifest = {
        "schema_version": "decision-gepa-v2",
        "created": "2026-10-23",
        "approval_status": "draft_unreviewed",
        "split_unit": "scenario_group_with_counterfactual_pairs",
        "shared_policy_documents_allowed": True,
        "counts": dict(Counter(r.split for r in rows)),
        "ability_counts": {
            s: dict(Counter(r.provenance["ability"] for r in rows if r.split == s))
            for s in ("train", "validation", "test")
        },
        "action_counts": dict(Counter(r.expected.kind for r in rows)),
        "scenario_groups": len({r.family for r in rows}),
        "counterfactual_pairs": len({r.provenance["pair_id"] for r in rows}),
        "historical_exact_snapshots": 0,
        "data_sha256": digest([r.model_dump() for r in rows]),
        "split_hashes": {
            split: digest([r.model_dump() for r in rows if r.split == split])
            for split in ("train", "validation", "test")
        },
        "judge_probes_sha256": digest(probes),
        "seed_sha256": digest(DECISION_INSTRUCTIONS),
        "limits": [
            "not_human_reviewed",
            "not_empirically_difficulty_calibrated",
            "not_unseen_policy_generalization",
            "not_exact_runtime_replay",
            "no_hidden_task_gold_used",
            "no_paid_model_calls",
        ],
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (args.output / "seed_prompt.txt").write_text(
        DECISION_INSTRUCTIONS + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
