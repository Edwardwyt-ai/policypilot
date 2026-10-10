import json
from types import SimpleNamespace

import pytest

from policypilot.api.authorization import (
    RESOURCE_TABLES,
    BankingToolAuthorizer,
    ToolAuthorizationError,
)
from tau2.data_model.message import ToolCall
from tau2.environment.tool import Tool


def read_account(account_id: str) -> str:
    return account_id


def get_user_information_by_id(user_id: str) -> str:
    return user_id


def get_user_information_by_name(customer_name: str) -> str:
    return customer_name


def call_discoverable_agent_tool(agent_tool_name: str, arguments: str = "{}") -> str:
    return arguments


def KB_search(query: str) -> str:
    return query


@pytest.fixture
def authorizer():
    tables = {
        name: SimpleNamespace(data={})
        for names in RESOURCE_TABLES.values()
        for name in names
    }
    tables["accounts"].data = {
        "own": {"user_id": "alice"},
        "foreign": {"user_id": "bob"},
    }
    tables["users"] = SimpleNamespace(
        data={"alice": {"name": "Alice", "user_id": "alice"}}
    )
    toolkit = SimpleNamespace(
        db=SimpleNamespace(**tables),
        get_discoverable_tools=lambda: {"read_account": read_account},
    )
    tools = [
        Tool(f)
        for f in (
            read_account,
            get_user_information_by_id,
            get_user_information_by_name,
            call_discoverable_agent_tool,
            KB_search,
        )
    ]
    return BankingToolAuthorizer(
        "alice", SimpleNamespace(tools=toolkit, get_tools=lambda: tools)
    )


def call(name, **arguments):
    return ToolCall(id="test", name=name, arguments=arguments)


def test_own_reads_public_policy_and_nested_tools(authorizer):
    authorizer.authorize(call("read_account", account_id="own"))
    authorizer.authorize(call("get_user_information_by_id", user_id="alice"))
    authorizer.authorize(call("KB_search", query="no annual fee"))
    authorizer.authorize(
        call(
            "call_discoverable_agent_tool",
            agent_tool_name="read_account",
            arguments=json.dumps({"account_id": "own"}),
        )
    )


@pytest.mark.parametrize(
    "proposal",
    [
        call("read_account", account_id="foreign"),
        call("read_account", account_id="missing"),
        call("read_account", account_id="foreign", user_id="alice"),
        call("get_user_information_by_id", user_id="bob"),
        call("KB_search", query="policy", user_id="alice"),
        call("shell", command="anything", user_id="alice"),
        call(
            "call_discoverable_agent_tool",
            agent_tool_name="read_account",
            arguments='{"account_id":"foreign"}',
        ),
        call(
            "call_discoverable_agent_tool",
            agent_tool_name="read_account",
            arguments="[]",
        ),
    ],
)
def test_foreign_unknown_and_spoofed_calls_denied(authorizer, proposal):
    with pytest.raises(ToolAuthorizationError):
        authorizer.authorize(proposal)


def test_name_collision_fails_closed(authorizer):
    authorizer.authorize(call("get_user_information_by_name", customer_name="Alice"))
    authorizer.db.users.data["bob"] = {"user_id": "bob", "name": "Alice"}
    with pytest.raises(ToolAuthorizationError):
        authorizer.authorize(
            call("get_user_information_by_name", customer_name="Alice")
        )


def test_real_banking_toolkit_identity_and_account_ownership():
    from tau2.domains.banking_knowledge.environment import get_environment

    environment = get_environment(retrieval_variant="bm25")
    records = environment.tools.db.accounts.data
    owned_id, owned = next(
        (key, value) for key, value in records.items() if value.get("user_id")
    )
    authorizer = BankingToolAuthorizer(owned["user_id"], environment)
    authorizer.authorize(call("get_user_information_by_id", user_id=owned["user_id"]))
    assert authorizer._owns("account_id", owned_id)
    foreign_id = next(
        key
        for key, value in records.items()
        if value.get("user_id") != owned["user_id"]
    )
    assert not authorizer._owns("account_id", foreign_id)
    authorizer.authorize(call("KB_search", query="card annual fees"))
    authorizer.authorize(
        call(
            "give_discoverable_user_tool",
            discoverable_tool_name="get_referral_link",
            arguments=json.dumps({"user_id": owned["user_id"], "card_name": "example"}),
        )
    )
    with pytest.raises(ToolAuthorizationError):
        authorizer.authorize(
            call(
                "give_discoverable_user_tool",
                discoverable_tool_name="get_referral_link",
                arguments=json.dumps({"user_id": "other-user", "card_name": "example"}),
            )
        )
