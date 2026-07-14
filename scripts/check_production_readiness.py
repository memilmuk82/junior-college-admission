from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from app import create_app


def main() -> int:
    env_file = os.environ.get("PRODUCTION_ENV_FILE")
    if env_file:
        path = Path(env_file)
        if not path.is_file():
            print("운영 구성 사전검사 실패: PRODUCTION_ENV_FILE")
            return 1
        load_dotenv(path, override=False)

    try:
        app = create_app()
    except (RuntimeError, ValueError) as error:
        print(f"운영 구성 사전검사 실패: {error}")
        return 1
    if app.config.get("APP_ENV") != "production":
        print("운영 구성 사전검사 실패: APP_ENV")
        return 1
    print("운영 구성 사전검사 통과: 비밀값을 출력하지 않고 시작 조건을 확인했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
