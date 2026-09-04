"""Windows credential provider — reads store targets from Credential Manager."""

from __future__ import annotations

from tools.credentials.base import EnvCredentialProvider


class WindowsCredentialProvider(EnvCredentialProvider):
    """Env vars plus Windows Credential Manager (the dev-box default)."""

    def _read_store(self, target: str) -> str | None:
        try:
            from tools.credential_helper import read_credential

            return read_credential(target)
        except Exception:
            return None
