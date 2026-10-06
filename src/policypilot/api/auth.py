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

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("POLICYPILOT_BACKEND_API_KEY must not be empty.")
        self.api_key = api_key

    def dependency(
        self,
        authorization: str | None = Header(default=None),
        x_user_id: str | None = Header(default=None),
    ) -> Identity:
        scheme, _, supplied = (authorization or "").partition(" ")
        valid = (
            scheme.lower() == "bearer"
            and bool(supplied)
            and hmac.compare_digest(supplied, self.api_key)
        )
        if not valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid bearer token.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user_id = (x_user_id or "").strip()
        if not user_id or len(user_id) > 128:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="X-User-ID is required and must be at most 128 characters.",
            )
        return Identity(user_id=user_id)
