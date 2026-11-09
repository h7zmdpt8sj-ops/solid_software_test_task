from pathlib import Path

from flask import Flask
from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename

from app.routes import USER_ID_HEADER

SPEC_PATH = Path(__file__).parent.parent / "app" / "static" / "openapi.yaml"


def test_openapi_spec_is_valid() -> None:
    spec, _ = read_from_filename(str(SPEC_PATH))

    validate(spec)


def test_openapi_spec_documents_every_api_route(app: Flask) -> None:
    spec, _ = read_from_filename(str(SPEC_PATH))
    api_routes = {
        rule.rule.replace("<uuid:", "{").replace(">", "}")
        for rule in app.url_map.iter_rules()
        if rule.endpoint.startswith("payments.")
    }

    assert set(spec["paths"]) == api_routes


def test_swagger_ui_is_served(app: Flask) -> None:
    client = app.test_client()

    docs = client.get("/docs")
    spec = client.get("/static/openapi.yaml")

    assert docs.status_code == 200
    assert b"/static/openapi.yaml" in docs.data
    assert spec.status_code == 200
    assert spec.data.startswith(b"openapi: 3.0.3")


def test_openapi_spec_requires_user_id_header() -> None:
    spec, _ = read_from_filename(str(SPEC_PATH))
    parameters = spec["paths"]["/carts/{cart_id}/payments"]["post"]["parameters"]

    assert {"name": USER_ID_HEADER, "in": "header", "required": True}.items() <= next(
        parameter for parameter in parameters if parameter["in"] == "header"
    ).items()
