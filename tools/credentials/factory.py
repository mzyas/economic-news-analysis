"""Pick the credential provider implementation for the current environment."""

from __future__ import annotations

import os

from tools.credentials.base import EnvCredentialProvider, LLMCredentialProvider


def default_credential_provider() -> LLMCredentialProvider:
    """Select a provider by runtime environment.

    Windows dev box → Windows Credential Manager. A systemd service (detected
    via ``$CREDENTIALS_DIRECTORY``) → systemd credential files. Otherwise fall
    back to environment variables only.
    """
    if os.name == "nt":
        from tools.credentials.providers.windows import WindowsCredentialProvider

        return WindowsCredentialProvider()
    if os.environ.get("CREDENTIALS_DIRECTORY"):
        from tools.credentials.providers.systemd import SystemdCredentialProvider

        return SystemdCredentialProvider()
    return EnvCredentialProvider()
