from sqlalchemy import Engine

from app import create_app
from app.database import db, get_engine


def test_app_factory_initializes_postgresql(postgres_engine: Engine) -> None:
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "DATABASE_URL": str(postgres_engine.url),
        }
    )

    assert get_engine(app).dialect.name == "postgresql"
    assert app.extensions["sqlalchemy"] is db
    assert "migrate" in app.extensions


def test_flask_migrate_cli_is_registered(postgres_engine: Engine) -> None:
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "DATABASE_URL": str(postgres_engine.url),
        }
    )

    result = app.test_cli_runner().invoke(args=["db", "--help"])

    assert result.exit_code == 0
    assert "migrate" in result.output
    assert "upgrade" in result.output
