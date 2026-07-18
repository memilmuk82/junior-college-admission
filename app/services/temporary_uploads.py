from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

SESSION_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
SUFFIX_PATTERN = re.compile(r"^\.[a-z0-9]{1,10}$")
ARTIFACT_KINDS = frozenset({"original", "derived"})


class DeletionVerificationError(RuntimeError):
    """Raised when a temporary review session cannot be proven deleted."""


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    path: Path
    sha256: str
    size: int


class TemporaryUploadStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)

    def create_session(self) -> str:
        session_id = uuid4().hex
        self.session_path(session_id).mkdir(mode=0o700)
        return session_id

    def purge_expired_sessions(
        self, *, max_age_seconds: int = 30 * 60, now: float | None = None
    ) -> int:
        if max_age_seconds <= 0:
            raise ValueError("임시 세션 만료시간은 양수여야 합니다.")
        cutoff = (time.time() if now is None else now) - max_age_seconds
        purged = 0
        for candidate in self.root.iterdir():
            if not candidate.is_dir() or not SESSION_ID_PATTERN.fullmatch(candidate.name):
                continue
            state_paths = (
                candidate / "derived" / "review-state.json",
                candidate / "derived" / "anonymous-calculation.json",
            )
            modified_at = max(
                [candidate.stat().st_mtime]
                + [path.stat().st_mtime for path in state_paths if path.is_file()]
            )
            if modified_at <= cutoff:
                self.purge_session(candidate.name)
                purged += 1
        return purged

    def session_path(self, session_id: str) -> Path:
        if not SESSION_ID_PATTERN.fullmatch(session_id):
            raise ValueError("유효하지 않은 검수 세션 식별자입니다.")
        return self.root / session_id

    def write_artifact(
        self,
        session_id: str,
        content: bytes,
        *,
        kind: str,
        suffix: str,
    ) -> StoredArtifact:
        if kind not in ARTIFACT_KINDS:
            raise ValueError("임시 산출물 종류는 original 또는 derived여야 합니다.")
        normalized_suffix = suffix.lower()
        if not SUFFIX_PATTERN.fullmatch(normalized_suffix):
            raise ValueError("안전하지 않은 파일 확장자입니다.")

        session_path = self.session_path(session_id)
        if not session_path.is_dir():
            raise FileNotFoundError("검수 세션이 존재하지 않습니다.")
        kind_path = session_path / kind
        kind_path.mkdir(mode=0o700, exist_ok=True)
        artifact_path = kind_path / f"{uuid4().hex}{normalized_suffix}"
        with artifact_path.open("xb") as artifact_file:
            artifact_file.write(content)
        os.chmod(artifact_path, 0o600)
        return StoredArtifact(
            path=artifact_path,
            sha256=hashlib.sha256(content).hexdigest(),
            size=len(content),
        )

    def purge_session(self, session_id: str) -> None:
        session_path = self.session_path(session_id)
        if not session_path.exists():
            return
        try:
            shutil.rmtree(session_path)
        except OSError as error:
            raise DeletionVerificationError(
                f"임시 검수 세션 삭제에 실패했습니다: {session_id}"
            ) from error
        if session_path.exists():
            raise DeletionVerificationError(
                f"임시 검수 세션 삭제를 검증하지 못했습니다: {session_id}"
            )
