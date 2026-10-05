"""Windows Credential Manager helper for Hermes projects.

This module provides a clean way to read credentials stored in the
Windows Credential Manager from WSL (or native Windows). It uses
PowerShell to invoke the advapi32 CredRead API via P/Invoke.

Usage:
    from tools.credential_helper import read_credential
    key = read_credential("deepseek-key")
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# PowerShell inline script to read from Windows Credential Manager
# Uses -Command (not -File) to avoid WSL banner pollution on stdout.
# The Add-Type block defines a C# P/Invoke wrapper around advapi32 CredRead.
_CR_SCRIPT = r'''Add-Type @"
using System;
using System.Runtime.InteropServices;
public class CredManager {
    [DllImport("advapi32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
    public static extern bool CredRead(string target, int type, int flags, out IntPtr credential);
    [DllImport("advapi32.dll", SetLastError=true)]
    public static extern void CredFree(IntPtr buffer);
    public static string Read(string target) {
        IntPtr ptr;
        if (CredRead(target, 1, 0, out ptr)) {
            try {
                var cred = (CREDENTIAL)Marshal.PtrToStructure(ptr, typeof(CREDENTIAL));
                return Marshal.PtrToStringUni(cred.CredentialBlob, cred.CredentialBlobSize / 2);
            } finally {
                CredFree(ptr);
            }
        }
        return null;
    }
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
    private struct CREDENTIAL { public int Flags; public int Type; public string TargetName; public string Comment; public long LastWritten; public int CredentialBlobSize; public IntPtr CredentialBlob; public int Persist; public int AttributeCount; public IntPtr Attributes; public string TargetAlias; public string UserName; }
}
"@
'''

def _find_powershell() -> str | None:
    """Locate a Windows PowerShell executable on native Windows or from WSL.

    Tried in order: ``PATH`` (via :func:`shutil.which`), then well-known
    absolute locations for both native Windows (``%SystemRoot%``) and WSL
    (``/mnt/c/...``). ``shutil.which`` correctly searches each ``PATH``
    *directory* for the executable — the previous implementation called
    ``os.path.isfile`` on the directory entries themselves, so it never
    matched and PowerShell was never found on native Windows.
    """
    for name in ("powershell.exe", "powershell", "pwsh.exe", "pwsh"):
        found = shutil.which(name)
        if found:
            return found

    system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
    candidates = [
        os.path.join(
            system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe"
        ),
        "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def read_credential(target: str) -> str | None:
    """Read a password from Windows Credential Manager.

    Uses inline PowerShell with Add-Type P/Invoke and -Command (not -File)
    to avoid Windows PowerShell startup banner leaking into stdout.

    Args:
        target: The credential target name.

    Returns:
        The password string, or None if not found / error.
    """
    ps = _find_powershell()
    if ps is None:
        logger.debug("Windows PowerShell not found, skipping Credential Manager")
        return None

    # Embed target directly into script to avoid -Command $args issues
    script = _CR_SCRIPT + (
        '$r = [CredManager]::Read("' + target + '"); '
        'if ($r) { Write-Host $r -NoNewline }'
    )

    try:
        r = subprocess.run(
            [ps, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.debug("Credential Manager read failed: %s", exc)
        return None

    if r.returncode != 0:
        logger.debug("Credential Manager PowerShell exited %d", r.returncode)
        return None

    # Parse the last non-banner line for the result
    for line in reversed(r.stdout.splitlines()):
        key = line.strip().rstrip("\r\n")
        if not key:
            continue
        # Skip banner lines (contain non-ASCII chars)
        if any(ord(c) > 127 for c in key):
            continue
        if "Windows PowerShell" in key or "https://" in key:
            continue
        # Looks like a valid API key
        return key

    return None


def store_credential(target: str, password: str) -> bool:
    """Store a password in Windows Credential Manager.

    Args:
        target: Credential target name.
        password: The secret to store.

    Returns:
        True on success, False on failure.
    """
    ps = _find_powershell()
    if ps is None:
        logger.error("Windows PowerShell not found, cannot store credential")
        return False

    cmd = f'cmdkey /generic:{target} /user:token /pass:{password}'
    try:
        r = subprocess.run(
            [ps, "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.error("Credential store failed: %s", exc)
        return False

    return r.returncode == 0


def resolve_api_key(
    env_vars: tuple[str, ...] = (),
    credential_target: str = "deepseek-key",
    registry_var: str = "",
) -> str | None:
    """Resolve an API key from multiple sources in priority order.

    1. Windows Credential Manager
    2. Optional Windows User-level registry environment variable

    Works on native Windows and from WSL.
    """
    # 1. Windows Credential Manager
    try:
        val = read_credential(credential_target)
        if val:
            logger.debug("Resolved API key from Credential Manager")
            return val
    except Exception:
        logger.debug("Credential Manager lookup failed", exc_info=True)

    # 2. Optional Windows User registry fallback
    if registry_var:
        try:
            ps = _find_powershell()
            if ps is not None:
                r = subprocess.run(
                    [ps, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                     f"[Environment]::GetEnvironmentVariable('{registry_var}','User')"],
                    capture_output=True, text=True, timeout=5,
                    encoding="utf-8", errors="replace",
                )
                if r.returncode == 0:
                    val = r.stdout.strip().rstrip("\r\n")
                    if val:
                        logger.debug("Resolved API key from Windows registry")
                        return val
        except Exception:
            logger.debug("Registry fallback failed", exc_info=True)

    return None
