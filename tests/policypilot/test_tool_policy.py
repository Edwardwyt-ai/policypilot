from policypilot.tool_policy import (
    ToolCallGuard,
    classify_tool,
    is_knowledge_tool,
    tool_signature,
)
from tau2.data_model.message import ToolCall


def test_tool_signature_is_order_independent():
    assert tool_signature("read", {"a": 1, "b": 2}) == tool_signature("read", {"b": 2, "a": 1})


def test_capability_classification(tools):
    by_name = {tool.name: tool for tool in tools}
    assert is_knowledge_tool("KB_search")
    assert classify_tool(by_name["read_account"]) == "transaction_read"
    assert classify_tool(by_name["mutate_account"]) == "mutation"


def test_guard_validates_tool_schema(tools):
    guard = ToolCallGuard(tools)
    valid = ToolCall(id="1", name="read_account", arguments={"account_id": "a1"}, requestor="assistant")
    invalid = ToolCall(id="2", name="read_account", arguments={"wrong": "a1"}, requestor="assistant")
    assert guard.validate_tool_call(valid) is None
    assert guard.validate_tool_call(invalid)
