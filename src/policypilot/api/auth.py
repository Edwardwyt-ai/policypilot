"""Small authentication boundary for the local PolicyPilot API."""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import Header, HTTPException, status


@dataclass(frozen=True)
class Identity:
    user_id: str


class ApiKeyAuthenticator:
    """Authenticate a trusted client and bind requests to one user id."""

    def __init__(
        self, api_key: str, user_id: str, user_tokens: dict[str, str] | None = None
    ):
        self.tokens = dict(user_tokens or {})
        if api_key:
            if not user_id:
                raise ValueError(
                    "A backend key must be bound to a server-configured user."
                )
            if api_key in self.tokens and self.tokens[api_key] != user_id:
                raise ValueError("Conflicting identity binding for backend key.")
            self.tokens[api_key] = user_id
        if not self.tokens or any(
            not token or not user or len(user) > 128
            for token, user in self.tokens.items()
        ):
            raise ValueError("Configure nonempty user-bound backend credentials.")

    def dependency(
        self,
        authorization: str | None = Header(default=None),
        x_user_id: str | None = Header(default=None),
    ) -> Identity:
        scheme, _, supplied = (authorization or "").partition(" ")
        user_id = None
        if scheme.lower() == "bearer" and supplied:
            for token, subject in self.tokens.items():
                if hmac.compare_digest(supplied.encode(), token.encode()):
                    user_id = subject
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid bearer token.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if x_user_id is not None and x_user_id.strip() != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User header does not match the authenticated identity.",
            )
        return Identity(user_id=user_id)
