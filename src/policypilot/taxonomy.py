"""Finite banking taxonomy used to identify information needs semantically."""

from __future__ import annotations

import re
from typing import Literal, get_args

CanonicalAspect = Literal[
    "annual_fee",
    "rewards",
    "eligibility_rule",
    "qualified_signup_definition",
    "reward_limit",
    "payout_timeline",
    "resubmission_rule",
    "procedure",
    "escalation_path",
    "product_terms",
    "candidate_options",
    "customer_identifier",
    "identity_verification",
    "verification_status",
    "current_account_state",
    "current_transaction_state",
    "current_referral_records",
    "mutation_precondition",
    "mutation_outcome",
]

CANONICAL_ASPECTS = frozenset(get_args(CanonicalAspect))

_ALIASES: tuple[tuple[CanonicalAspect, str], ...] = (
    ("annual_fee", r"annual.?fee|fee.?free|no.?fee"),
    ("qualified_signup_definition", r"qualified.*sign.?up|sign.?up.*qualif"),
    ("reward_limit", r"referral.*(?:limit|cap|maximum)|(?:limit|cap|maximum).*referral|payout.?limit"),
    ("payout_timeline", r"payout.*(?:time|timeline|wait)|bonus.*(?:time|timeline|wait)"),
    ("resubmission_rule", r"resubmit|resubmission|retry.*rule"),
    ("escalation_path", r"escalat|human.?review|complaint|dispute.?path"),
    ("current_referral_records", r"referral.*(?:record|status)|(?:record|status).*referral"),
    ("current_transaction_state", r"transaction.*(?:record|status|state)"),
    ("current_account_state", r"account.*(?:record|status|state|balance)"),
    ("customer_identifier", r"user.?id|customer.?id|customer.?identifier"),
    ("identity_verification", r"identity|verification|verify|date.?of.?birth|mailing.?address"),
    ("verification_status", r"verification.?status|verified"),
    ("eligibility_rule", r"eligib|qualif|requirement|prerequisite"),
    ("rewards", r"cash.?back|rewards?|points?"),
    ("procedure", r"procedure|how.?to|steps?|process"),
    ("candidate_options", r"candidate|alternatives?|options?|compare"),
    ("mutation_precondition", r"precondition|before.*(?:change|close|update|submit)"),
    ("mutation_outcome", r"mutation.?outcome|write.?result|post.?condition"),
    ("product_terms", r"product.?terms|terms.?and.?conditions"),
)

_REFERRAL_ASPECTS = {
    "qualified_signup_definition",
    "reward_limit",
    "payout_timeline",
    "resubmission_rule",
    "current_referral_records",
}


def normalize_text(value: str | None) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")
    return re.sub(r"_+", "_", text)


def canonicalize_aspect(
    value: str,
    *,
    entity: str = "",
    scope: str | None = None,
) -> CanonicalAspect | None:
    normalized = normalize_text(value)
    if normalized in CANONICAL_ASPECTS:
        return normalized  # type: ignore[return-value]
    searchable = " ".join((value, entity, scope or ""))
    if normalized in {"policy", "requirement"}:
        return None
    for aspect, pattern in _ALIASES:
        if re.search(pattern, searchable, re.I):
            return aspect
    if normalized in {"eligibility", "requirements"}:
        return "eligibility_rule"
    if normalized in {"limit", "limits"}:
        return "reward_limit" if "referral" in searchable.lower() else None
    if normalized in {"timing", "timeline"}:
        return "payout_timeline" if "referral" in searchable.lower() else None
    return None


def canonical_entity(entity: str, aspect: str) -> str:
    normalized = normalize_text(entity).removesuffix("s") or "unknown"
    if aspect in {"customer_identifier", "identity_verification", "verification_status"}:
        return "user"
    if aspect in _REFERRAL_ASPECTS or "referral" in normalized:
        return "referral"
    if aspect == "current_transaction_state":
        return "transaction"
    if aspect == "current_account_state":
        return "account"
    if normalized in {"rho_bank", "bank", "policy", "product"}:
        return "banking_product"
    return normalized
