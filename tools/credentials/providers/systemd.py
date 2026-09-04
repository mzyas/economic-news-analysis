"""systemd credential provider — reads store targets from $CREDENTIALS_DIRECTORY.

On a systemd service the secrets are encrypted at deploy time with
``systemd-creds encrypt`` and referenced from the unit via
``LoadCredentialEncrypted=``/``SetCredentialEncrypted=``. At runtime systemd
decrypts them into files under ``$CREDENTIALS_DIRECTORY``, one file per
credential whose filename is the credential name (matching our store target).
"""

from __future__ import annotations

import os
from pathlib import Path

from tools.credentials.base import EnvCredentialProvider


class SystemdCredentialProvider(EnvCredentialProvider):
    """Env vars plus systemd-provided credential files."""

    def _read_store(self, target: str) -> str | None:
        directory = os.environ.get("CREDENTIALS_DIRECTORY")
        if not directory:
            return None
        path = Path(directory) / target
        try:
            if path.is_file():
                return path.read_text(encoding="utf-8")
        except OSError:
            return None
        return None
