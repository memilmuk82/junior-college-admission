import os

from flask import Flask


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "development-only-change-me"),
        DATABASE_URL=os.environ.get("DATABASE_URL"),
    )

    if test_config:
        app.config.update(test_config)

    from app.database import init_database

    init_database(app)

    from app.routes import bp

    app.register_blueprint(bp)
    return app
