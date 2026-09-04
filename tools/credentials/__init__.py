"""Unified LLM credential providers, selected per runtime environment."""

from __future__ import annotations

from tools.credentials.base import (
    EnvCredentialProvider,
    LLMCredential,
    LLMCredentialProvider,
)
from tools.credentials.factory import default_credential_provider
from tools.credentials.fake import FakeCredentialProvider
from tools.credentials.providers.systemd import SystemdCredentialProvider
from tools.credentials.providers.windows import WindowsCredentialProvider
from tools.credentials.registry import (
    clear_run_credential_provider,
    get_run_credential_provider,
    set_run_credential_provider,
)

__all__ = [
    "LLMCredential",
    "LLMCredentialProvider",
    "EnvCredentialProvider",
    "WindowsCredentialProvider",
    "SystemdCredentialProvider",
    "FakeCredentialProvider",
    "default_credential_provider",
    "set_run_credential_provider",
    "get_run_credential_provider",
    "clear_run_credential_provider",
]
