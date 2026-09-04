"""Run-scoped registry for the credential provider.

The provider is a runtime-only dependency: it is needed *while* the graph runs
but must never be persisted. It cannot live in the graph state because LangGraph
checkpoints the whole state (msgpack/SQLite), and a live provider object is not
serializable — and we explicitly do not want any credential material reaching a
checkpoint BLOB. So the bootstrap registers it here keyed by the run/thread id,
nodes look it up by the run id from state, and the entry is cleared when the run
finishes.
"""

from __future__ import annotations

from tools.credentials.base import LLMCredentialProvider

_PROVIDERS: dict[str, LLMCredentialProvider] = {}


def set_run_credential_provider(run_id: str, provider: LLMCredentialProvider) -> None:
    if run_id:
        _PROVIDERS[run_id] = provider


def get_run_credential_provider(run_id: str | None) -> LLMCredentialProvider | None:
    if not run_id:
        return None
    return _PROVIDERS.get(run_id)


def clear_run_credential_provider(run_id: str | None) -> None:
    if run_id:
        _PROVIDERS.pop(run_id, None)
