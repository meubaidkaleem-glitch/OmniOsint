"""Generated artefacts must match their sources (ADR-014: OpenAPI is the contract)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from omniosint.api.app import create_app
from omniosint.core.config import load_settings

ROOT = Path(__file__).resolve().parents[2]


def test_frontend_api_contract_is_current() -> None:
    committed = json.loads((ROOT / "frontend/src/api/openapi.json").read_text(encoding="utf-8"))
    current = create_app(load_settings(use_files=False), manage_lifespan=False).openapi()
    assert committed == json.loads(json.dumps(current)), (
        "frontend/src/api/openapi.json is out of date. Run:\n"
        "  omniosint openapi -o frontend/src/api/openapi.json\n"
        "  (cd frontend && npm run gen:api)"
    )


def test_generated_provider_docs_are_current() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/dev/gen_docs.py"), "--check", "providers"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
