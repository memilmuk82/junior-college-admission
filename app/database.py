from __future__ import annotations

from typing import Any

from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


db = SQLAlchemy(model_class=Base)
migrate = Migrate(compare_type=True)


def init_database(app: Flask) -> None:
    database_url = app.config.get("DATABASE_URL")
    if not database_url:
        return

    app.config["SQLALCHEMY_DATABASE_URI"] = str(database_url)
    app.config.setdefault("SQLALCHEMY_ENGINE_OPTIONS", {"pool_pre_ping": True})
    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)

    db.init_app(app)
    migrate.init_app(app, db, directory="migrations")

    # Phase 1에서 제공한 확장 키를 유지해 기존 호출부의 호환성을 보장한다.
    with app.app_context():
        app.extensions["database_engine"] = db.engine
        app.extensions["database_session"] = db.session


def get_engine(app: Flask) -> Engine:
    engine: Any = app.extensions.get("database_engine")
    if not isinstance(engine, Engine):
        raise RuntimeError("DATABASE_URL이 설정되지 않아 데이터베이스가 초기화되지 않았습니다.")
    return engine
