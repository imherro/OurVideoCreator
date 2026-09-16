"""Export the routes FastAPI actually registers without starting the app lifespan."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path


def export_routes(app) -> list[dict]:
    return [
        {
            "type": type(route).__name__,
            "path": getattr(route, "path", None),
            "name": getattr(route, "name", None),
            "methods": sorted(getattr(route, "methods", None) or []),
        }
        for route in app.routes
    ]


def unclassified_api_routes(routes: list[dict], route_map: str) -> list[str]:
    unclassified = []
    for item in routes:
        if not str(item.get("path") or "").startswith("/api/"):
            continue
        methods = [method for method in item.get("methods", []) if method not in {"HEAD", "OPTIONS"}]
        for method in methods:
            pattern = rf"{re.escape(method)}\s+`{re.escape(item['path'])}`"
            if re.search(pattern, route_map) is None:
                unclassified.append(f"{method} {item['path']}")
    return unclassified


def guard_exit_code(routes: list[dict], route_map: str) -> int:
    """Return the process exit status used by CI's fail-closed route guard."""
    return 1 if unclassified_api_routes(routes, route_map) else 0


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    with tempfile.TemporaryDirectory(prefix="ovc-p0-routes-") as data_dir:
        os.environ["MVC_DATA_DIR"] = data_dir
        from backend.app import app
        from starlette.routing import Mount

        routes = export_routes(app)
        mounts = [item for item in routes if item["type"] == Mount.__name__]
        route_map = (repo / "docs" / "multiuser-rollout" / "design" / "ROUTE_AUTH_MAP.md").read_text(
            encoding="utf-8"
        )
        api_routes = [
            item for item in routes if str(item["path"] or "").startswith("/api/")
        ]
        unclassified = unclassified_api_routes(routes, route_map)
        payload = {
            "audit": "P3 ACL-09 actual app.routes classification guard",
            "isolated_data_dir": True,
            "dist_exists": (repo / "dist").is_dir(),
            "route_count": len(routes),
            "api_decorator_route_count": sum(
                1 for item in routes if str(item["path"] or "").startswith("/api/")
            ),
            "classified_api_route_count": len(api_routes) - len(unclassified),
            "unclassified_api_routes": unclassified,
            "enforcement": "fail-closed; any unclassified API route exits non-zero",
            "framework_entries_documented": {
                "openapi_disabled": "openapi_url=None" in route_map,
                "static_mount": "StaticFiles" in route_map and "Mount" in route_map,
            },
            "openapi_route": next(
                (item for item in routes if item["path"] == "/openapi.json"), None
            ),
            "static_mounts": mounts,
            "without_dist_difference": (
                "backend/app.py conditionally omits only the '/' StaticFiles Mount; "
                "API routes remain registered and OpenAPI stays disabled"
            ),
            "routes": routes,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return guard_exit_code(routes, route_map)


if __name__ == "__main__":
    raise SystemExit(main())
