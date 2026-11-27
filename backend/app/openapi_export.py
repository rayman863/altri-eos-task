"""`python -m app.openapi_export`: print the API's OpenAPI document (plan 3.17).

The committed copy (`openapi.json` at the repo root) is what the frontend's typed client is
generated from (`npm run gen:api`); a test fails when it no longer matches the code, so the
TypeScript types can't silently drift from the API. Regenerate with `make openapi`.
"""

import json
import sys

from app.main import create_app


def render() -> str:
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True, ensure_ascii=True) + "\n"


if __name__ == "__main__":
    sys.stdout.write(render())
