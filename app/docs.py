from flask import Blueprint, render_template, url_for

docs_blueprint = Blueprint("docs", __name__)


@docs_blueprint.get("/docs")
def swagger_ui() -> str:
    return render_template("docs.html", spec_url=url_for("static", filename="openapi.yaml"))
