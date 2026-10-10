"""Server-owned authorization policies at the banking tool execution boundary."""

from __future__ import annotations

import json
from typing import Any

from tau2.data_model.message import ToolCall
from tau2.environment.tool import Tool


class ToolAuthorizationError(PermissionError):
    """A call cannot be authorized for the authenticated principal."""


# Explicit relationships, not model-authored ownership claims.
RESOURCE_TABLES = {
    "account_id": ("accounts", "credit_card_accounts"),
    "source_account_id": ("accounts",),
    "destination_account_id": ("accounts",),
    "checking_account_id": ("accounts",),
    "credit_card_account_id": ("credit_card_accounts",),
    "card_id": ("debit_cards",),
    "transaction_id": (
        "credit_card_transaction_history",
        "bank_account_transaction_history",
    ),
    "referral_id": ("referrals",),
    "application_id": ("credit_card_applications",),
    "request_id": ("credit_limit_increase_requests",),
    "dispute_id": ("transaction_disputes", "debit_card_disputes", "cash_back_disputes"),
    "order_id": ("credit_card_orders", "debit_card_orders"),
}
PUBLIC_TOOLS = {
    "KB_search",
    "KB_search_bm25",
    "KB_search_dense",
    "get_current_time",
    "list_discoverable_agent_tools",
    "list_discoverable_user_tools",
    "unlock_discoverable_agent_tool",
    "transfer_to_human_agents",
    "initial_transfer_to_human_agent_0218",
    "initial_transfer_to_human_agent_1822",
    "emergency_credit_bureau_incident_transfer_1114",
}
WRAPPERS = {
    "call_discoverable_agent_tool": "agent_tool_name",
    "give_discoverable_user_tool": "discoverable_tool_name",
}


class BankingToolAuthorizer:
    """Check current DB ownership for every call, including nested tools."""

    def __init__(self, user_id: str, environment: Any):
        self.user_id = user_id
        self.environment = environment

    @property
    def db(self):
        return self.environment.tools.db

    def _records(self, table: str) -> dict:
        return getattr(self.db, table).data

    def _owned_record(self, table: str, record: dict, seen: set[tuple]) -> bool:
        direct = record.get("user_id") or record.get("referrer_id")
        if direct is not None:
            return direct == self.user_id
        for key in (
            "account_id",
            "credit_card_account_id",
            "card_id",
            "transaction_id",
        ):
            if record.get(key):
                return self._owns(key, record[key], seen)
        return False

    def _owns(self, key: str, value: Any, seen: set[tuple] | None = None) -> bool:
        if not isinstance(value, str) or not value:
            return False
        seen = set(seen or ())
        marker = (key, value)
        if marker in seen:
            return False
        seen.add(marker)
        matches = []
        for table in RESOURCE_TABLES[key]:
            records = self._records(table)
            record = records.get(value)
            if record is None:
                # Some fixtures key records differently from their public ID.
                record = next(
                    (
                        r
                        for r in records.values()
                        if r.get(key) == value
                        or (key.endswith("account_id") and r.get("account_id") == value)
                    ),
                    None,
                )
            if record is not None:
                matches.append(self._owned_record(table, record, seen))
        return bool(matches) and all(matches)

    def authorize(self, call: ToolCall, *, user_tool: bool = False) -> None:
        """Reject unknown policies and foreign resources before tool execution."""
        name, arguments = call.name, call.arguments or {}
        available = (
            {}
            if user_tool
            else {tool.name: tool for tool in self.environment.get_tools()}
        )
        toolkit = self.environment.user_tools if user_tool else self.environment.tools
        discoverable = toolkit.get_discoverable_tools()
        tool = available.get(name)
        if tool is None and name in discoverable:
            tool = Tool(discoverable[name])
        if tool is None or name in {"shell", "grep", "query_database", "execute_sql"}:
            raise ToolAuthorizationError("Tool policy is not configured.")
        try:
            if set(arguments) - set(tool.params.model_fields):
                raise ValueError("Unexpected arguments.")
            tool.params.model_validate(arguments, strict=True)
        except (ValueError, TypeError) as exc:
            raise ToolAuthorizationError("Invalid tool arguments.") from exc
        if name in WRAPPERS:
            nested_name = arguments.get(WRAPPERS[name])
            try:
                nested_args = json.loads(arguments.get("arguments", "{}"))
            except (TypeError, ValueError) as exc:
                raise ToolAuthorizationError("Invalid nested arguments.") from exc
            if (
                not isinstance(nested_name, str)
                or not isinstance(nested_args, dict)
                or nested_name in WRAPPERS
            ):
                raise ToolAuthorizationError("Invalid nested tool.")
            self.authorize(
                ToolCall(id=call.id, name=nested_name, arguments=nested_args),
                user_tool=name == "give_discoverable_user_tool",
            )
            return
        if name in {"get_user_information_by_name", "get_user_information_by_email"}:
            field, arg = (
                ("name", "customer_name")
                if name.endswith("name")
                else ("email", "email")
            )
            matches = [
                (key, record)
                for key, record in self._records("users").items()
                if record.get(field) == arguments.get(arg)
            ]
            if not matches or any(
                (record.get("user_id") or key) != self.user_id
                for key, record in matches
            ):
                raise ToolAuthorizationError("Identity lookup denied.")
            return
        checked = False
        for key, value in arguments.items():
            if key in {"user_id", "customer_id", "referrer_id"}:
                checked = True
                if value != self.user_id:
                    raise ToolAuthorizationError("Principal mismatch.")
            elif key in RESOURCE_TABLES:
                checked = True
                if not self._owns(key, value):
                    raise ToolAuthorizationError("Resource access denied.")
            elif key.endswith("_id"):
                raise ToolAuthorizationError("Resource policy is not configured.")
        # Broad SQL, shell and unknown tools do not inherit policy-read access.
        if not checked and name not in PUBLIC_TOOLS:
            raise ToolAuthorizationError("Tool policy is not configured.")
