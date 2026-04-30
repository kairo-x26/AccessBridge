"""Print the OpenAPI schema (used to generate the frontend's typed API client)."""

import json

from app.main import create_app

if __name__ == "__main__":
    print(json.dumps(create_app().openapi(), indent=1))
