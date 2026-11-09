import os

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.docs import docs_blueprint
from app.routes import payments_blueprint

DEFAULT_DATABASE_URL = "postgresql+psycopg://shop:shop@localhost:5432/shop"


def create_app(database_url: str | None = None) -> Flask:
    app = Flask(__name__)
    engine = create_engine(
        database_url or os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        pool_pre_ping=True,
    )
    app.extensions["session_factory"] = sessionmaker(engine, expire_on_commit=False)
    app.register_blueprint(payments_blueprint)
    app.register_blueprint(docs_blueprint)
    return app
