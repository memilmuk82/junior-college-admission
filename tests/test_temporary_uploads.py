from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.temporary_uploads import (
    DeletionVerificationError,
    TemporaryUploadStore,
)


def test_session_purge_removes_original_and_derived_files(tmp_path: Path) -> None:
    store = TemporaryUploadStore(tmp_path)
    session_id = store.create_session()
    original = store.write_artifact(
        session_id, b"synthetic,score\nA,90", kind="original", suffix=".csv"
    )
    derived = store.write_artifact(session_id, b"synthetic-derived", kind="derived", suffix=".txt")

    assert original.path.exists()
    assert derived.path.exists()

    store.purge_session(session_id)

    assert not store.session_path(session_id).exists()


def test_purge_does_not_silently_ignore_a_remaining_session(tmp_path: Path) -> None:
    store = TemporaryUploadStore(tmp_path)
    session_id = store.create_session()
    store.write_artifact(session_id, b"synthetic", kind="original", suffix=".bin")

    with patch("app.services.temporary_uploads.shutil.rmtree", return_value=None):
        with pytest.raises(DeletionVerificationError):
            store.purge_session(session_id)


def test_invalid_session_identifier_is_rejected(tmp_path: Path) -> None:
    store = TemporaryUploadStore(tmp_path)

    with pytest.raises(ValueError):
        store.session_path("../outside")
