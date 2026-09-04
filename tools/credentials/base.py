"""LLM credential provider interface and the store-backed base.

A provider returns the ordered list of ``(api_key, source)`` candidates the
LLM adapter should try. The *source* tag is consumed downstream
(``ResearchAdapter._build_llm``) to pick the right model and base URL, so it is
part of this module's catalog — not the storage mechanism.

Only the *storage* differs per environment (Windows Credential Manager vs
systemd credentials vs nothing). Concrete providers only override
:meth:`EnvCredentialProvider._read_store`.
"""

from __future__ import annotations

import os
from typing import Protocol

# (api_key, source) where source is one of the tags produced below.
LLMCredential = tuple[str, str]


class LLMCredentialProvider(Protocol):
    """Returns ordered ``(api_key, source)`` candidates to try in turn."""

    def llm_credentials(self) -> list[LLMCredential]:
        ...


def _clean(value: str | None) -> str | None:
    """Strip surrounding whitespace / stray CRLF; return None when empty."""
    if not value:
        return None
    value = value.strip().rstrip("\r\n")
    return value or None


class EnvCredentialProvider:
    """Base provider for store-backed credential readers.

    Subclasses supply credentials kept in a secret store by overriding
    :meth:`_read_store`. The ordered candidate catalog (which store targets, in
    what order, with which source tag) lives here so it is defined exactly
    once.
    """

    _STORE_TARGETS: tuple[tuple[str, str], ...] = (
        ("deepseek-key", "deepseek"),
    )

    # Environment-variable names checked before the platform secret store,
    # in the same (env_var, source) order as _STORE_TARGETS.
    _ENV_VARS: tuple[tuple[str, str], ...] = (
        ("DEEPSEEK_API_KEY", "deepseek"),
    )

    def _read_store(self, target: str) -> str | None:
        """Read ``target`` from the environment's secret store. None by default."""
        return None

    def llm_credentials(self) -> list[LLMCredential]:
        candidates: list[LLMCredential] = []
        seen_sources: set[str] = set()

        # 1. Environment variables take priority (portable across Linux / Windows).
        for env_var, source in self._ENV_VARS:
            val = _clean(os.environ.get(env_var))
            if val:
                candidates.append((val, source))
                seen_sources.add(source)

        # 2. Platform secret store as fallback (skipped if env var already won).
        for target, source in self._STORE_TARGETS:
            if source in seen_sources:
                continue
            try:
                val = _clean(self._read_store(target))
            except Exception:
                val = None
            if val:
                candidates.append((val, source))
                seen_sources.add(source)

        return candidates

    def __getstate__(self) -> dict:
        # Defensive: providers hold no secret state (reads are lazy), but if the
        # graph state carrying this object is checkpointed, never let any
        # instance attribute reach the pickle BLOB.
        return {}
