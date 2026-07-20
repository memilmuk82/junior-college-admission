from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import click
from flask import Flask
from sqlalchemy.orm import Session

from app.database import db
from app.services.phase14_public_seed import load_phase14_public_seed, load_phase17_public_seed
from app.services.temporary_uploads import TemporaryUploadStore


def register_phase14_cli(app: Flask) -> None:
    @app.cli.command("purge-expired-anonymous-calculations")
    @click.option("--max-age-seconds", type=click.IntRange(min=1), default=30 * 60)
    def purge_expired_anonymous_calculations(max_age_seconds: int) -> None:
        """Purge expired anonymous input and upload sessions without requiring traffic."""
        count = TemporaryUploadStore(app.config["TEMP_UPLOAD_ROOT"]).purge_expired_sessions(
            max_age_seconds=max_age_seconds
        )
        click.echo(f"expired anonymous sessions purged: {count}")

    @app.cli.command("seed-phase14-public-results")
    @click.option("--actor-ref", required=True, help="게시 작업을 수행한 관리자 actor ref")
    def seed_phase14_public_results(actor_ref: str) -> None:
        """검수 범위가 고정된 4개 대학 공개 catalog·2025 결과를 게시한다."""
        try:
            dataset_id = load_phase14_public_seed(
                cast(Session, db.session),
                repository_root=Path(app.root_path).parent,
                actor_ref=actor_ref,
                occurred_at=datetime.now(UTC),
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        click.echo(f"phase14 public dataset ready: {dataset_id}")

    @app.cli.command("seed-phase17-public-results")
    @click.option("--actor-ref", required=True, help="게시 작업을 수행한 관리자 actor ref")
    def seed_phase17_public_results(actor_ref: str) -> None:
        """42개 대학 전체 catalog와 검증된 2026 참고 결과를 게시한다."""

        try:
            seeded = load_phase17_public_seed(
                cast(Session, db.session),
                repository_root=Path(app.root_path).parent,
                actor_ref=actor_ref,
                occurred_at=datetime.now(UTC),
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        click.echo(
            "phase17 public datasets ready: "
            f"2025={seeded.result_2025_dataset_id} 2026={seeded.result_2026_dataset_id}"
        )


__all__ = ["register_phase14_cli"]
