"""`omniosint classify | search | investigate | jobs | evidence | scopes | providers test`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.integration.test_cli import cli_env, run_cli

pytestmark = pytest.mark.integration

SIMULATED = {"OMNIOSINT_COLLECTION__ENABLE_SIMULATED_PROVIDER": "true"}


def as_json(result: object) -> dict[str, object]:
    stdout = result.stdout  # type: ignore[attr-defined]
    assert stdout, result.stderr  # type: ignore[attr-defined]
    return dict(json.loads(stdout))


def test_classify_text_and_files(tmp_path: Path) -> None:
    env = cli_env(tmp_path)
    result = run_cli("classify", "hxxps://evil[.]example[.]com/x", "--json", env=env)
    assert result.returncode == 0, result.stderr
    classification = as_json(result)["classification"]
    assert classification["status"] == "recognized" and classification["refanged"] is True  # type: ignore[index]
    picture = tmp_path / "photo.pdf"
    picture.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(100))
    by_file = as_json(run_cli("classify", "--file", str(picture), "--json", env=env))[
        "classification"
    ]
    top = by_file["candidates"][0]  # type: ignore[index]
    assert top["type"] == "image" and any("misleading" in note for note in top["notes"])
    readable = run_cli("classify", "Acme Widgets", env=env)
    assert readable.returncode == 0 and "Choose the one you mean" in readable.stdout


def test_investigate_runs_collection_here(tmp_path: Path, clean_database: str) -> None:
    env = cli_env(tmp_path, clean_database, **SIMULATED)
    plan = as_json(run_cli("search", "example.org", "--json", env=env))["plan"]
    statuses = {
        step["capability_id"]: step["status"] for step in plan["steps"] if step["capability_id"]
    }  # type: ignore[index]
    assert statuses["simulated.lookup"] == "ready"

    result = run_cli("investigate", "example.org", "--run-here", "--json", env=env)
    assert result.returncode == 0, result.stderr
    body = as_json(result)
    assert body["request"]["status"] == "completed"  # type: ignore[index]
    (job,) = body["jobs"]  # type: ignore[misc]
    assert job["status"] == "succeeded" and len(job["evidence"]) == 3
    assert all(item["simulated"] for item in job["evidence"])

    shown = as_json(
        run_cli("evidence", "show", job["evidence"][0]["id"], "--raw", "--json", env=env)
    )
    assert shown["integrity"]["content_hash_valid"] is True  # type: ignore[index]
    assert shown["raw"]["body"]["simulated"] is True  # type: ignore[index]
    listed = as_json(run_cli("jobs", "list", "--json", env=env))["jobs"]
    assert [item["id"] for item in listed] == [job["id"]]  # type: ignore[union-attr]
    history = run_cli("jobs", "show", job["id"], env=env)
    assert history.returncode == 0 and "succeeded" in history.stdout


def test_failed_collection_exits_non_zero_with_the_reason(
    tmp_path: Path, clean_database: str
) -> None:
    env = cli_env(tmp_path, clean_database, **SIMULATED)
    result = run_cli(
        "investigate", "example.org", "--run-here", "--option", "simulate=quota", "--json", env=env
    )
    assert result.returncode == 1
    (job,) = as_json(result)["jobs"]  # type: ignore[misc]
    assert job["status"] == "failed" and job["error"]["code"] == "provider_quota_exceeded"


def test_without_a_worker_jobs_stay_queued(tmp_path: Path, clean_database: str) -> None:
    env = cli_env(tmp_path, clean_database, **SIMULATED)
    result = run_cli("investigate", "example.org", "--json", env=env)
    assert result.returncode == 0
    body = as_json(result)
    assert "worker is not running" in str(body["note"])
    assert body["jobs"][0]["status"] == "queued"  # type: ignore[index]


def test_ambiguous_input_is_refused_until_a_type_is_chosen(
    tmp_path: Path, clean_database: str
) -> None:
    env = cli_env(tmp_path, clean_database, **SIMULATED)
    digest = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    refused = run_cli("search", digest, env=env)
    assert refused.returncode == 1 and "several ways" in refused.stderr
    chosen = run_cli("search", digest, "--type", "file_hash", "--json", env=env)
    assert chosen.returncode == 0


def test_scopes_and_active_operations(tmp_path: Path, clean_database: str) -> None:
    env = cli_env(tmp_path, clean_database, **SIMULATED)
    unconfirmed = run_cli(
        "scopes", "create", "--name", "Engagement", "--authorized-by", "Network owner",
        "--rule", "cidr=198.51.100.0/24", env=env,
    )  # fmt: skip
    assert unconfirmed.returncode == 1 and "authorisation" in unconfirmed.stderr
    created = run_cli(
        "scopes", "create", "--name", "Engagement", "--authorized-by", "Network owner",
        "--rule", "cidr=198.51.100.0/24", "--exclude", "ip=198.51.100.66",
        "--confirm-authorization", "--json", env=env,
    )  # fmt: skip
    assert created.returncode == 0, created.stderr
    scope_id = as_json(created)["scope"]["id"]  # type: ignore[index]

    result = run_cli(
        "investigate", "198.51.100.7", "--mode", "active", "--scope", scope_id,
        "--provider", "simulated", "--run-here", "--json", env=env,
    )  # fmt: skip
    jobs = {job["capability"]: job for job in as_json(result)["jobs"]}  # type: ignore[union-attr]
    assert jobs["simulated.probe"]["status"] == "awaiting_approval"
    approved = run_cli("jobs", "approve", jobs["simulated.probe"]["id"], "--json", env=env)
    assert approved.returncode == 0 and as_json(approved)["job"]["status"] == "queued"  # type: ignore[index]

    scopes = as_json(run_cli("scopes", "list", "--json", env=env))["scopes"]
    assert [scope["status"] for scope in scopes] == ["active"]  # type: ignore[union-attr]
    revoked = run_cli("scopes", "revoke", scope_id, "--reason", "Engagement over.", env=env)
    assert revoked.returncode == 0


def test_providers_test_checks_adapters(tmp_path: Path) -> None:
    disabled = run_cli("providers", "test", "--json", env=cli_env(tmp_path))
    assert disabled.returncode == 2 and as_json(disabled)["tested"] == 0
    enabled = run_cli(
        "providers", "test", "simulated", "--json", env=cli_env(tmp_path, **SIMULATED)
    )
    assert enabled.returncode == 0
    (result,) = as_json(enabled)["results"]  # type: ignore[misc]
    assert result["tested"] and result["status"] == "ok"
    planned = run_cli("providers", "test", "shodan", "--json", env=cli_env(tmp_path, **SIMULATED))
    assert planned.returncode == 2
