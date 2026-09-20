from policypilot.evidence import make_tool_evidence, parse_policy_references


def test_evidence_record_records_tool_provenance() -> None:
    record = make_tool_evidence(
        tool_name="get_user",
        tool_args={"user_id": "u1"},
        tool_call_id="call_1",
        content='{"user_id": "u1"}',
        turn_index=3,
        is_retrieval=False,
    )

    assert record.source_type == "transaction_tool"
    assert record.tool_name == "get_user"
    assert record.tool_args == {"user_id": "u1"}
    assert record.turn_index == 3


def test_retrieval_result_provenance_saved() -> None:
    content = """
1. Dispute Policy
   ID: doc_031
   Score: 7.2500
   Content: Pending transactions cannot be disputed.
"""

    refs = parse_policy_references(content)

    assert len(refs) == 1
    assert refs[0].document_id == "doc_031"
    assert refs[0].title == "Dispute Policy"
    assert refs[0].score == 7.25


def test_retrieval_summary_keeps_evidence_from_later_ranked_documents() -> None:
    content = """
1. Generic Result
   ID: doc_1
   Score: 10.0000
   Content: This is a generic referral overview.

2. Referral Restrictions
   ID: doc_2
   Score: 8.0000
   Content: The rolling referral limit is two bonuses in seven days.
   A third referral in the window is automatically denied.
"""

    record = make_tool_evidence(
        tool_name="KB_search",
        tool_args={"query": "referral bonus limit"},
        tool_call_id="call_2",
        content=content,
        turn_index=4,
        is_retrieval=True,
    )

    assert "[doc_1]" in record.summary
    assert "[doc_2]" in record.summary
    assert "rolling referral limit" in record.summary
    assert "automatically denied" in record.summary


def test_retrieval_summary_preserves_actionable_wait_or_retry_guidance() -> None:
    content = """
1. Referral Restrictions
   ID: doc_referral
   Score: 9.0000
   Content: The referral program applies to all consumer cards.
   The rolling referral limit is two bonuses in seven days.
   A third referral in the window is automatically denied.
   Different card types count toward the same cap.
   If a referral is denied for hitting the limit, wait until enough time has passed before attempting another.
"""

    record = make_tool_evidence(
        tool_name="KB_search",
        tool_args={"query": "referral bonus limit"},
        tool_call_id="call_action",
        content=content,
        turn_index=5,
        is_retrieval=True,
    )

    assert "wait until enough time has passed" in record.summary
    assert "before attempting another" in record.summary


def test_retrieval_summary_allocates_space_to_every_ranked_document() -> None:
    documents = []
    for index in range(1, 11):
        body = "Generic referral details. " * 20
        if index == 10:
            body = "Platinum Rewards Card has an active referral program."
        documents.append(
            f"{index}. Policy {index}\n"
            f"   ID: doc_{index}\n"
            f"   Score: {11 - index}.0000\n"
            f"   Content: {body}"
        )
    record = make_tool_evidence(
        tool_name="KB_search",
        tool_args={"query": "Platinum referral program"},
        tool_call_id="call_all_docs",
        content="\n\n".join(documents),
        turn_index=6,
        is_retrieval=True,
    )

    assert "[doc_1]" in record.summary
    assert "[doc_10]" in record.summary
    assert "Platinum Rewards Card" in record.summary


def test_retrieval_summary_keeps_numbered_steps_in_their_source_document() -> None:
    content = """
1. Example Card: Eligibility
   ID: doc_card
   Score: 9.0000
   Content: ## Key Terms
   - Subscription required: Yes
   - Annual fee: $0.00
   - Cash back: 2.5%

   ## How to Apply
   1. Confirm you have an active subscription.
   2. Submit the application.

2. Other Card: Overview
   ID: doc_other
   Score: 8.0000
   Content: Annual fee: $50.00
"""

    record = make_tool_evidence(
        tool_name="KB_search",
        tool_args={
            "query": "card no annual fee cash back eligibility subscription"
        },
        tool_call_id="call_numbered",
        content=content,
        turn_index=7,
        is_retrieval=True,
    )

    assert [ref.document_id for ref in record.policy_refs] == [
        "doc_card",
        "doc_other",
    ]
    card_line = next(
        line for line in record.summary.splitlines() if line.startswith("[doc_card]")
    )
    assert "Subscription required" in card_line
    assert "Annual fee: $0.00" in card_line
    assert "Cash back: 2.5%" in card_line
