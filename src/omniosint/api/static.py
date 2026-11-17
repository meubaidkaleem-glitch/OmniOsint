"""Serves the built web interface from the same origin as the API."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

_NOT_BUILT_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>OmniOSINT</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
<h1>OmniOSINT</h1>
<p>The API is running, but the web interface has not been built.</p>
<p>Run the installer (<code>install.bat</code> on Windows) or, from the
<code>frontend</code> folder, <code>npm ci</code> and <code>npm run build</code>,
then restart OmniOSINT.</p>
<p>API status: <a href="/api/v1/system/health/ready">/api/v1/system/health/ready</a></p>
</body>
</html>
"""


def _looks_like_page(path: str) -> bool:
    """A client-side route, as opposed to a request for a file that is missing."""
    name = PurePosixPath(path).name
    return "." not in name


class SpaStaticFiles(StaticFiles):
    """Static files with single-page-application fallback.

    Unknown paths that look like pages get ``index.html`` so that client-side
    routes survive a reload. Paths under ``/api`` never fall back: an unknown
    API route must be a JSON 404, not an HTML page. Path traversal is prevented
    by Starlette's own containment check.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        normalized = path.replace("\\", "/").lstrip("/")
        if normalized == "api" or normalized.startswith("api/"):
            raise StarletteHTTPException(status_code=404)
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or scope["method"] not in ("GET", "HEAD"):
                raise
            if not _looks_like_page(normalized):
                raise
            response = await super().get_response("index.html", scope)
            response.headers["Cache-Control"] = "no-cache"
            return response

        if normalized.startswith("assets/"):
            # Vite fingerprints everything under assets/, so it can be cached forever.
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response


def mount_frontend(app: FastAPI, dist: Path | None) -> bool:
    """Serve the web interface. Returns whether a build was found."""
    if dist is not None and (dist / "index.html").is_file():
        app.mount("/", SpaStaticFiles(directory=dist, html=True), name="frontend")
        return True

    @app.get("/", include_in_schema=False)
    async def frontend_not_built() -> HTMLResponse:
        return HTMLResponse(_NOT_BUILT_PAGE, headers={"Cache-Control": "no-store"})

    return False
