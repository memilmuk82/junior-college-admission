from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tests.test_consultation_routes import _seed


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url or not database_url.startswith("postgresql+"):
        raise RuntimeError("합성 E2E seed에는 PostgreSQL DATABASE_URL이 필요합니다.")
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            _seed(session)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
