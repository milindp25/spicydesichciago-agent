"""Quick sanity check that the emulator fixture works."""
from __future__ import annotations


def test_emulator_writes_and_reads(firestore_db):
    """Basic round trip via Firestore client against the emulator."""
    doc_ref = firestore_db.collection("smoke").document("sanity")
    doc_ref.set({"hello": "world"})
    snap = doc_ref.get()
    assert snap.exists
    assert snap.to_dict() == {"hello": "world"}


def test_emulator_clears_between_tests(firestore_db):
    """After clear, no docs from prior test should leak."""
    docs = list(firestore_db.collection("smoke").stream())
    assert docs == []
