"""Start, inspect and stop the real application processes."""

from __future__ import annotations

import json
import socket
import time
from pathlib import Path

import httpx
import psutil
import pytest

from tests.helpers import free_port
from tests.integration.test_cli import cli_env, run_cli

pytestmark = pytest.mark.e2e


def alive(pid: int) -> bool:
    """Running, as opposed to gone or exited-but-not-yet-reaped (a zombie)."""
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def managed_pids(home: Path) -> list[int]:
    state_file = home / "run" / "state.json"
    if not state_file.is_file():
        return []
    return [item["pid"] for item in json.loads(state_file.read_text())["processes"]]


@pytest.fixture
def lifecycle_env(tmp_path: Path, clean_database: str):  # type: ignore[no-untyped-def]
    port = free_port()
    env = cli_env(
        tmp_path,
        clean_database,
        OMNIOSINT_SERVER__PORT=str(port),
        OMNIOSINT_RUNTIME__STARTUP_TIMEOUT_SECONDS="45",
        OMNIOSINT_WORKER__HEARTBEAT_SECONDS="2",
    )
    yield env, port, tmp_path
    run_cli("stop", env=env)
    for pid in managed_pids(tmp_path):
        if alive(pid):
            psutil.Process(pid).kill()


def test_start_status_stop(lifecycle_env):  # type: ignore[no-untyped-def]
    env, port, home = lifecycle_env
    started = run_cli("start", "--json", env=env, timeout=90)
    assert started.returncode == 0, started.stdout + started.stderr
    body = json.loads(started.stdout)
    assert body["already_running"] is False
    assert body["url"] == f"http://127.0.0.1:{port}"
    assert body["setup_required"] is True and "/setup#token=" in body["open_url"]
    assert body["status"]["healthy"] is True

    pids = managed_pids(home)
    assert len(pids) == 2 and all(alive(pid) for pid in pids)

    with httpx.Client(trust_env=False, timeout=5) as http:
        ready = http.get(f"http://127.0.0.1:{port}/api/v1/system/health/ready").json()
    components = {item["name"]: item["status"] for item in ready["components"]}
    assert components["database"] == "ok" and components["worker"] == "ok"

    # Listening on the loopback interface only.
    api = psutil.Process(pids[0])
    listening = [
        conn.laddr
        for proc in [api, *api.children(recursive=True)]
        for conn in proc.net_connections(kind="inet")
        if conn.status == psutil.CONN_LISTEN
    ]
    assert listening and all(address.ip in ("127.0.0.1", "::1") for address in listening)

    assert run_cli("status", "--check", env=env).returncode == 0
    again = json.loads(run_cli("start", "--json", env=env).stdout)
    assert again["already_running"] is True

    stopped = run_cli("stop", "--json", env=env, timeout=90)
    result = json.loads(stopped.stdout)
    assert result["was_running"] is True
    assert result["forced"] == [], "processes must stop gracefully"
    assert not any(alive(pid) for pid in pids)
    assert not (home / "run" / "state.json").exists()
    assert run_cli("status", "--check", env=env).returncode == 1
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))  # the port is free again


def test_start_recovers_after_a_process_dies(lifecycle_env):  # type: ignore[no-untyped-def]
    env, _port, home = lifecycle_env
    assert run_cli("start", env=env, timeout=90).returncode == 0
    api_pid, worker_pid = managed_pids(home)
    psutil.Process(worker_pid).kill()
    for _ in range(100):
        if not alive(worker_pid):
            break
        time.sleep(0.05)
    assert run_cli("status", "--check", env=env).returncode == 1

    restarted = json.loads(run_cli("start", "--json", env=env, timeout=90).stdout)
    assert restarted["already_running"] is False
    assert restarted["status"]["healthy"] is True
    assert not alive(api_pid), "the half-running set is stopped before restarting"


def test_start_refuses_a_port_in_use(lifecycle_env):  # type: ignore[no-untyped-def]
    env, port, home = lifecycle_env
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", port))
        blocker.listen()
        result = run_cli("start", "--json", env=env)
    assert result.returncode == 1
    assert json.loads(result.stdout)["error"]["code"] == "port_in_use"
    assert managed_pids(home) == []


def test_start_refuses_when_the_database_is_unreachable(tmp_path: Path):
    env = cli_env(
        tmp_path,
        "postgresql://nobody:nothing@127.0.0.1:1/omniosint_test",
        OMNIOSINT_SERVER__PORT=str(free_port()),
        OMNIOSINT_DATABASE__CONNECT_TIMEOUT_SECONDS="1",
    )
    result = run_cli("start", "--json", env=env)
    assert result.returncode == 4
    assert json.loads(result.stdout)["error"]["code"] == "database_unavailable"
    assert managed_pids(tmp_path) == []
