"""Structured errors recorded by PolicyPilot's recovery layer."""

from enum import Enum

from pydantic import BaseModel


class PolicyPilotErrorType(str, Enum):
    """Error classes that PolicyPilot records in state and metrics."""

    LLM_API_FAILURE = "llm_api_failure"
    MALFORMED_TOOL_CALL = "malformed_tool_call"
    TOOL_VALIDATION_ERROR = "tool_validation_error"
    TOOL_EXECUTION_ERROR = "tool_execution_error"
    RETRIEVAL_MISS = "retrieval_miss"
    DUPLICATE_TOOL_CALL = "duplicate_tool_call"
    MAX_STEP_EXHAUSTION = "max_step_exhaustion"
    MAX_TOOL_EXHAUSTION = "max_tool_exhaustion"
    MAX_ERROR_EXHAUSTION = "max_error_exhaustion"
    LLM_TRANSIENT = "llm_transient"
    TOOL_VALIDATION = "tool_validation"
    RETRIEVAL_EMPTY = "retrieval_empty"
    BUDGET_EXHAUSTED = "budget_exhausted"
    MUTATION_UNCERTAIN = "mutation_uncertain"


class ErrorRecord(BaseModel):
    """Compact task-local error and recovery status."""

    category: PolicyPilotErrorType
    source: str
    message: str
    retryable: bool
    turn_index: int
    recovery_action: str | None = None
    resolved: bool = False
    unsafe_to_retry: bool = False
    attempts: int = 0


class PolicyPilotError(Exception):
    """Base exception for recoverable PolicyPilot guardrail failures."""

    def __init__(self, error_type: PolicyPilotErrorType, message: str):
        super().__init__(message)
        self.error_type = error_type
        self.message = message
