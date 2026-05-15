"""Manage the Firebase Firestore emulator lifecycle for tests.

The emulator is a Java process that runs from `firebase-tools`. We start
it once per test session, point google-cloud-firestore at it via
FIRESTORE_EMULATOR_HOST, and clear all collections between tests for
isolation.

Requirements:
- firebase-tools installed (`brew install firebase-cli`)
- Java 11+ on PATH
- firebase.json at repo root (port 8088)
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from contextlib import closing
from pathlib import Path

EMULATOR_HOST = "127.0.0.1"
EMULATOR_PORT = 8088
PROJECT_ID = "demo-test"


class EmulatorUnavailable(RuntimeError):
    """firebase CLI missing or emulator can't start."""


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.settimeout(timeout)
        try:
            s.connect((host, port))
            return True
        except (OSError, socket.timeout):
            return False


def _wait_for_port(host: str, port: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_open(host, port):
            return
        time.sleep(0.5)
    raise EmulatorUnavailable(
        f"Firestore emulator did not start within {timeout}s on {host}:{port}"
    )


def start_emulator() -> subprocess.Popen[bytes]:
    """Start the Firestore emulator as a subprocess. Caller must terminate it."""
    if shutil.which("firebase") is None:
        raise EmulatorUnavailable(
            "firebase CLI not found. Install with: brew install firebase-cli"
        )

    repo_root = Path(__file__).resolve().parents[3]
    if _port_open(EMULATOR_HOST, EMULATOR_PORT):
        raise EmulatorUnavailable(
            f"Port {EMULATOR_PORT} already in use; stop existing emulator first."
        )

    proc = subprocess.Popen(
        [
            "firebase",
            "emulators:start",
            "--only", "firestore",
            "--project", PROJECT_ID,
        ],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_port(EMULATOR_HOST, EMULATOR_PORT, timeout=45.0)
    except Exception:
        proc.terminate()
        raise

    os.environ["FIRESTORE_EMULATOR_HOST"] = f"{EMULATOR_HOST}:{EMULATOR_PORT}"
    return proc


def stop_emulator(proc: subprocess.Popen[bytes]) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    os.environ.pop("FIRESTORE_EMULATOR_HOST", None)


def clear_emulator_data() -> None:
    """Delete all documents from the emulator. Use between tests."""
    import urllib.request

    # The emulator exposes a clear-all endpoint:
    # DELETE /emulator/v1/projects/{project}/databases/(default)/documents
    url = (
        f"http://{EMULATOR_HOST}:{EMULATOR_PORT}"
        f"/emulator/v1/projects/{PROJECT_ID}/databases/(default)/documents"
    )
    req = urllib.request.Request(url, method="DELETE")
    with urllib.request.urlopen(req, timeout=5) as resp:
        if resp.status != 200:
            raise RuntimeError(f"emulator clear returned {resp.status}")
