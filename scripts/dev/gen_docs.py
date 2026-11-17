"""Regenerate the generated parts of the documentation.

Usage (from the project root, inside the virtual environment):

    python scripts/dev/gen_docs.py            # rewrite generated sections
    python scripts/dev/gen_docs.py --check    # exit 1 if anything is out of date

Generated content:

* docs/PROVIDERS.md       catalogue table, from config/providers.yaml
* docs/API_REFERENCE.md   endpoint reference, from the OpenAPI document
* docs/DEPENDENCIES.md    dependency inventory, from the installed packages
                          and frontend/package-lock.json
"""

from __future__ import annotations

import argparse
import json
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"


def _replace_block(text: str, name: str, body: str) -> str:
    begin = f"<!-- BEGIN GENERATED: {name} -->"
    end = f"<!-- END GENERATED: {name} -->"
    start = text.index(begin) + len(begin)
    stop = text.index(end)
    return text[:start] + "\n" + body.rstrip("\n") + "\n" + text[stop:]


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


# --------------------------------------------------------------------------- providers
def providers_markdown() -> str:
    from omniosint.providers.catalog import CATEGORY_LABELS, load_catalogue

    catalogue = load_catalogue()
    counts = catalogue.status_counts()
    lines = [
        f"{len(catalogue.providers)} entries: {counts['available']} available, "
        f"{counts['planned']} planned, {counts['excluded']} excluded.",
        "",
    ]
    for category, label in CATEGORY_LABELS.items():
        entries = [p for p in catalogue.providers if p.category == category]
        if not entries:
            continue
        lines += [
            f"### {label}",
            "",
            "| Provider | Access | Auth | Phase | Status | Notes |",
            "|---|---|---|---|---|---|",
        ]
        for provider in entries:
            name = f"[{provider.name}]({provider.docs_url})" if provider.docs_url else provider.name
            lines.append(
                f"| {_cell(name)} | {provider.access_label} | {provider.auth.replace('_', ' ')} "
                f"| {provider.phase} | {provider.status.capitalize()} | {_cell(provider.notes)} |"
            )
        lines.append("")
    return "\n".join(lines)


def render_providers() -> tuple[Path, str]:
    path = DOCS / "PROVIDERS.md"
    return path, _replace_block(
        path.read_text(encoding="utf-8"), "provider-catalogue", providers_markdown()
    )


# --------------------------------------------------------------------------- API reference
def _schema_name(schema: dict[str, Any] | None) -> str:
    if not schema:
        return ""
    if "$ref" in schema:
        return f"`{schema['$ref'].rsplit('/', 1)[-1]}`"
    if schema.get("type") == "array":
        return f"array of {_schema_name(schema.get('items'))}"
    if "anyOf" in schema:
        return " or ".join(filter(None, (_schema_name(option) for option in schema["anyOf"])))
    return f"`{schema.get('type', 'object')}`"


def api_markdown() -> str:
    from omniosint.api.app import create_app
    from omniosint.core.config import load_settings

    app = create_app(load_settings(use_files=False), manage_lifespan=False)
    spec = app.openapi()
    lines = [
        "# API reference",
        "",
        "Generated from the OpenAPI document by `scripts/dev/gen_docs.py`. Do not edit by",
        "hand. The live document is served at `/api/v1/openapi.json`; interactive",
        "documentation is available at `/api/docs` in development mode.",
        "",
        f"API version: `{spec['info']['version']}`",
        "",
        "## Conventions",
        "",
        "* Base path: `/api/v1`. All request and response bodies are JSON.",
        "* **Authentication**: a session cookie (browsers) or",
        "  `Authorization: Bearer <token>` (CLI, desktop, scripts). Obtain either from",
        "  `POST /api/v1/auth/login`.",
        "* **CSRF**: cookie-authenticated `POST`, `PUT`, `PATCH` and `DELETE` requests",
        "  must send the `X-CSRF-Token` header with the value returned by login or",
        "  `GET /api/v1/auth/me`. Bearer-authenticated requests do not need it.",
        "* **Errors** use one envelope:",
        "",
        "  ```json",
        '  { "error": { "code": "permission_denied", "message": "...",',
        '               "details": [], "request_id": "..." } }',
        "  ```",
        "",
        "  `code` is stable and safe to branch on; `message` is for people.",
        "* **Pagination**: list endpoints take `limit` (1 to 200, default 50) and an",
        "  opaque `cursor`, and return `items` and `next_cursor` (null on the last page).",
        "* Every response carries an `X-Request-ID` header; quote it when reporting a",
        "  problem.",
        "",
    ]

    by_tag: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            tag = (operation.get("tags") or ["other"])[0]
            by_tag.setdefault(tag, []).append((path, method.upper(), operation))

    tag_descriptions = {tag["name"]: tag.get("description", "") for tag in spec.get("tags", [])}
    for tag in [t["name"] for t in spec.get("tags", [])] + sorted(
        set(by_tag) - set(tag_descriptions)
    ):
        operations = by_tag.get(tag)
        if not operations:
            continue
        lines += [f"## {tag}", ""]
        if tag_descriptions.get(tag):
            lines += [tag_descriptions[tag], ""]
        for path, method, operation in operations:
            lines += [f"### `{method} {path}`", ""]
            summary = operation.get("summary", "")
            description = (operation.get("description") or "").strip()
            if summary:
                lines += [f"**{summary}**", ""]
            if description:
                lines += [description, ""]
            permission = operation.get("x-permission")
            access = operation.get("x-access", "authenticated")
            if permission:
                lines += [f"Requires permission: `{permission}`", ""]
            elif access == "public":
                lines += ["No authentication required.", ""]
            else:
                lines += ["Requires a signed-in user.", ""]

            parameters = operation.get("parameters") or []
            if parameters:
                lines += ["| Parameter | In | Required | Description |", "|---|---|---|---|"]
                for parameter in parameters:
                    lines.append(
                        f"| `{parameter['name']}` | {parameter['in']} "
                        f"| {'yes' if parameter.get('required') else 'no'} "
                        f"| {_cell(parameter.get('description', ''))} |"
                    )
                lines.append("")

            body = operation.get("requestBody", {}).get("content", {}).get("application/json")
            if body:
                lines += [f"Request body: {_schema_name(body.get('schema'))}", ""]

            responses = []
            for status, response in sorted(operation.get("responses", {}).items()):
                if status == "422":
                    continue
                schema = response.get("content", {}).get("application/json", {}).get("schema")
                label = _schema_name(schema)
                responses.append(f"`{status}`" + (f" {label}" if label else ""))
            if responses:
                lines += ["Responses: " + ", ".join(responses), ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def render_api() -> tuple[Path, str]:
    return DOCS / "API_REFERENCE.md", api_markdown()


# --------------------------------------------------------------------------- dependencies
def _python_dependencies() -> list[tuple[str, str, str]]:
    """Runtime distributions required (transitively) by the omniosint package."""
    import re

    def canonical(name: str) -> str:
        return re.sub(r"[-_.]+", "-", name).lower()

    def requirements(dist_name: str) -> list[str]:
        try:
            requires = metadata.requires(dist_name) or []
        except metadata.PackageNotFoundError:
            return []
        names = []
        for requirement in requires:
            if "extra ==" in requirement:
                continue
            match = re.match(r"^[A-Za-z0-9._-]+", requirement)
            if match:
                names.append(canonical(match.group(0)))
        return names

    seen: dict[str, tuple[str, str, str]] = {}
    queue = requirements("omniosint")
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue  # platform-specific dependency not installed here
        meta = dist.metadata
        licence = meta.get("License-Expression") or ""
        if not licence:
            classifiers = [
                value.rsplit("::", 1)[-1].strip()
                for value in meta.get_all("Classifier") or []
                if value.startswith("License ::")
            ]
            licence = ", ".join(classifiers) or (meta.get("License") or "").split("\n")[0][:60]
        seen[name] = (meta["Name"], dist.version, licence or "see package metadata")
        queue.extend(requirements(name))
    return sorted(seen.values(), key=lambda item: item[0].lower())


def _node_dependencies(project: str) -> list[tuple[str, str, str, bool]]:
    lock_path = ROOT / project / "package-lock.json"
    if not lock_path.is_file():
        return []
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    root = lock["packages"][""]
    direct = {**root.get("dependencies", {})}
    direct_dev = {**root.get("devDependencies", {})}
    rows = []
    for name in sorted({*direct, *direct_dev}):
        entry = lock["packages"].get(f"node_modules/{name}", {})
        rows.append(
            (name, entry.get("version", "?"), entry.get("license", "see package"), name in direct)
        )
    return rows


def dependencies_markdown() -> str:
    lines = [
        "# Dependency inventory",
        "",
        "Generated by `scripts/dev/gen_docs.py` from the installed Python packages and",
        "the frontend lock file. Do not edit by hand. Exact pinned versions, with",
        "hashes, are in `requirements.txt` and `frontend/package-lock.json`.",
        "",
        "Licence names are taken from each package's own metadata and have not been",
        "legally reviewed; a full licence review is a Phase 14 release task.",
        "",
        "## Backend runtime (Python)",
        "",
        "Includes transitive dependencies. Packages installed only on other",
        "platforms (for example `colorama` on Windows) are not listed here.",
        "",
        "| Package | Version | Licence |",
        "|---|---|---|",
    ]
    for name, version, licence in _python_dependencies():
        lines.append(f"| {name} | {version} | {_cell(licence)} |")

    for project, title in (("frontend", "Web interface"), ("desktop", "Desktop shell")):
        rows = _node_dependencies(project)
        if not rows:
            continue
        lines += ["", f"## {title} (npm, direct dependencies)", ""]
        lines += ["| Package | Version | Licence | Shipped to users |", "|---|---|---|---|"]
        for name, version, licence, runtime in rows:
            shipped = "yes" if runtime else "no (build/test)"
            lines.append(f"| {name} | {version} | {_cell(licence)} | {shipped} |")
    lines += [
        "",
        "## External programs",
        "",
        "Not bundled; each is installed by the user and detected at runtime.",
        "",
        "| Program | Needed for | Required |",
        "|---|---|---|",
        "| PostgreSQL 15+ | System of record | yes |",
        "| pg_dump / pg_restore | Backup and restore | for backups |",
        "| Node.js 20.19+ | Building the web interface | to build from source |",
        "| Rust toolchain, platform WebView | Building the desktop shell | optional |",
        "| Redis 6+ (or compatible) | Shared cache and rate limiting | optional |",
        "| Docker | Running PostgreSQL and Redis in containers | optional |",
    ]
    return "\n".join(lines) + "\n"


def render_dependencies() -> tuple[Path, str]:
    return DOCS / "DEPENDENCIES.md", dependencies_markdown()


RENDERERS = {
    "providers": render_providers,
    "api": render_api,
    "dependencies": render_dependencies,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("targets", nargs="*", choices=[*RENDERERS, []], default=[])
    parser.add_argument("--check", action="store_true", help="fail if anything would change")
    args = parser.parse_args()

    stale = []
    for name in args.targets or list(RENDERERS):
        path, content = RENDERERS[name]()
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current == content:
            continue
        if args.check:
            stale.append(path)
        else:
            path.write_text(content, encoding="utf-8", newline="\n")
            print(f"updated {path.relative_to(ROOT)}")
    if stale:
        for path in stale:
            print(f"out of date: {path.relative_to(ROOT)}", file=sys.stderr)
        print("Run: python scripts/dev/gen_docs.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
