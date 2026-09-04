"""Fake credential provider for tests — fully hermetic, reads no host secrets."""

from __future__ import annotations

from tools.credentials.base import LLMCredential


class FakeCredentialProvider:
    """Returns a fixed candidate list; never touches env vars or any store."""

    def __init__(self, credentials: list[LLMCredential] | None = None) -> None:
        self._credentials = list(credentials or [])

    def llm_credentials(self) -> list[LLMCredential]:
        return list(self._credentials)

    def __getstate__(self) -> dict:
        # Never let (possibly real-looking) fake credentials reach a pickle BLOB
        # if a graph state carrying this object is checkpointed.
        return {}

    def __setstate__(self, state: dict) -> None:
        self._credentials = []
