"""Tests for FirestoreClient initialization."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.infrastructure.firestore_client import FirestoreClient


def test_init_with_explicit_path(tmp_path):
    """When path is given, FirestoreClient uses it as service account."""
    fake = tmp_path / "fake-sa.json"
    fake.write_text('{"type": "service_account", "project_id": "demo-test"}')
    with patch("app.infrastructure.firestore_client.firestore.Client") as mock_client, patch(
        "app.infrastructure.firestore_client.service_account.Credentials.from_service_account_file"
    ) as mock_creds:
        client = FirestoreClient(project_id="demo-test", service_account_path=str(fake))
        _ = client.db
        mock_creds.assert_called_once_with(str(fake))
        mock_client.assert_called_once()


def test_init_with_ambient_credentials():
    """When path is empty, FirestoreClient falls back to ambient credentials."""
    with patch("app.infrastructure.firestore_client.firestore.Client") as mock_client:
        client = FirestoreClient(project_id="demo-test", service_account_path="")
        _ = client.db
        mock_client.assert_called_once()


def test_emulator_host_respected(monkeypatch):
    """When FIRESTORE_EMULATOR_HOST is set, the client connects to the emulator
    regardless of credentials."""
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "localhost:8088")
    with patch("app.infrastructure.firestore_client.firestore.Client") as mock_client:
        client = FirestoreClient(project_id="demo-test", service_account_path="")
        _ = client.db
        mock_client.assert_called_once()


def test_db_is_cached():
    """Calling .db twice returns the same client (singleton per FirestoreClient)."""
    with patch("app.infrastructure.firestore_client.firestore.Client") as mock_client:
        mock_client.return_value = object()
        client = FirestoreClient(project_id="demo-test", service_account_path="")
        first = client.db
        second = client.db
        assert first is second
        mock_client.assert_called_once()
