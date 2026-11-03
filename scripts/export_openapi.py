"""Writes the API's OpenAPI document to stdout (deterministic). CI fails if docs/api/openapi.json is stale."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "api"))
os.environ.setdefault("VAND_ENV", "local")
from app.main import create_app  # noqa: E402

print(json.dumps(create_app().openapi(), indent=1, sort_keys=True))
