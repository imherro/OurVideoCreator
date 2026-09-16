"""Export the routes FastAPI actually registers without starting the app lifespan."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    with tempfile.TemporaryDirectory(prefix="ovc-p0-routes-") as data_dir:
        os.environ["MVC_DATA_DIR"] = data_dir
        from backend.app import app
        from starlette.routing import Mount

        routes = []
        for route in app.routes:
            methods = sorted(getattr(route, "methods", None) or [])
            routes.append(
                {
                    "type": type(route).__name__,
                    "path": getattr(route, "path", None),
                    "name": getattr(route, "name", None),
                    "methods": methods,
                }
            )
        mounts = [item for item in routes if item["type"] == Mount.__name__]
        route_map = (repo / "docs" / "multiuser-rollout" / "design" / "ROUTE_AUTH_MAP.md").read_text(
            encoding="utf-8"
        )
        api_routes = [
            item for item in routes if str(item["path"] or "").startswith("/api/")
        ]
        unclassified = []
        for item in api_routes:
            methods = [method for method in item["methods"] if method not in {"HEAD", "OPTIONS"}]
            for method in methods:
                pattern = rf"{re.escape(method)}\s+`{re.escape(item['path'])}`"
                if re.search(pattern, route_map) is None:
                    unclassified.append(f"{method} {item['path']}")
        payload = {
            "audit": "P0-R1 actual app.routes",
            "isolated_data_dir": True,
            "dist_exists": (repo / "dist").is_dir(),
            "route_count": len(routes),
            "api_decorator_route_count": sum(
                1 for item in routes if str(item["path"] or "").startswith("/api/")
            ),
            "classified_api_route_count": len(api_routes) - len(unclassified),
            "unclassified_api_routes": unclassified,
            "framework_entries_documented": {
                "openapi": "/openapi.json" in route_map,
                "static_mount": "StaticFiles" in route_map and "Mount" in route_map,
            },
            "openapi_route": next(
                (item for item in routes if item["path"] == "/openapi.json"), None
            ),
            "static_mounts": mounts,
            "without_dist_difference": (
                "backend/app.py conditionally omits only the '/' StaticFiles Mount; "
                "API routes and /openapi.json remain registered"
            ),
            "routes": routes,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
