"""Tests for the LLM credential provider package."""

import os
import pickle
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.credentials import (
    EnvCredentialProvider,
    FakeCredentialProvider,
    SystemdCredentialProvider,
    WindowsCredentialProvider,
    default_credential_provider,
)

_ENV_VARS = (
    "CREDENTIALS_DIRECTORY",
)


class _CleanEnvMixin:
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        for var in _ENV_VARS:
            os.environ.pop(var, None)


class EnvCredentialProviderTests(_CleanEnvMixin, unittest.TestCase):
    def test_empty_when_nothing_set(self):
        self.assertEqual(EnvCredentialProvider().llm_credentials(), [])


class WindowsCredentialProviderTests(_CleanEnvMixin, unittest.TestCase):
    def test_reads_only_deepseek_store_candidate(self):
        store = {"deepseek-key": "ds-store"}
        with mock.patch(
            "tools.credential_helper.read_credential",
            side_effect=lambda target: store.get(target),
        ):
            creds = WindowsCredentialProvider().llm_credentials()

        self.assertEqual(creds, [("ds-store", "deepseek")])

    def test_store_failure_is_swallowed(self):
        with mock.patch(
            "tools.credential_helper.read_credential",
            side_effect=RuntimeError("boom"),
        ):
            self.assertEqual(WindowsCredentialProvider().llm_credentials(), [])


class SystemdCredentialProviderTests(_CleanEnvMixin, unittest.TestCase):
    def test_reads_from_credentials_directory(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "deepseek-key").write_text("creds-key", encoding="utf-8")
            os.environ["CREDENTIALS_DIRECTORY"] = d

            creds = SystemdCredentialProvider().llm_credentials()

        self.assertEqual(creds, [("creds-key", "deepseek")])

    def test_no_directory_returns_env_only(self):
        self.assertEqual(SystemdCredentialProvider().llm_credentials(), [])


class DefaultCredentialProviderTests(_CleanEnvMixin, unittest.TestCase):
    def test_windows_selected_on_nt(self):
        with mock.patch("tools.credentials.factory.os.name", "nt"):
            self.assertIsInstance(
                default_credential_provider(), WindowsCredentialProvider
            )

    def test_systemd_selected_when_credentials_directory_set(self):
        os.environ["CREDENTIALS_DIRECTORY"] = "/run/credentials/x"
        with mock.patch("tools.credentials.factory.os.name", "posix"):
            self.assertIsInstance(
                default_credential_provider(), SystemdCredentialProvider
            )

    def test_env_fallback_otherwise(self):
        with mock.patch("tools.credentials.factory.os.name", "posix"):
            provider = default_credential_provider()
        self.assertIsInstance(provider, EnvCredentialProvider)
        self.assertNotIsInstance(provider, WindowsCredentialProvider)
        self.assertNotIsInstance(provider, SystemdCredentialProvider)


class FakeCredentialProviderTests(_CleanEnvMixin, unittest.TestCase):
    def test_returns_given_list_unaffected_by_host_env(self):
        provider = FakeCredentialProvider([("k", "deepseek")])
        self.assertEqual(provider.llm_credentials(), [("k", "deepseek")])

    def test_pickle_drops_credentials(self):
        # Defensive: if a graph state carrying this object is checkpointed, the
        # fake credentials must not survive into the pickle BLOB.
        provider = FakeCredentialProvider([("secret", "deepseek")])
        restored = pickle.loads(pickle.dumps(provider))
        self.assertEqual(restored.llm_credentials(), [])


if __name__ == "__main__":
    unittest.main()
