from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def current_migration_head(config_path: Path = Path("alembic.ini")) -> str:
    config = Config(str(config_path))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise RuntimeError("Alembic migration head는 정확히 하나여야 합니다.")
    return heads[0]


def main() -> int:
    print(current_migration_head())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
