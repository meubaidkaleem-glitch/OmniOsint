"""The outbound HTTP client refuses non-public destinations (SSRF defence)."""

from __future__ import annotations

import ipaddress
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpcore
import pytest

from omniosint.net.http import DestinationPolicy, GuardedNetworkBackend, SafeHttpClient
from omniosint.providers.errors import (
    DestinationBlocked,
    ProviderUnavailable,
    ResponseTooLarge,
)

LOOPBACK_ONLY = DestinationPolicy(allowed_networks=(ipaddress.ip_network("127.0.0.1/32"),))


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args: Any) -> None:
        return

    def do_GET(self) -> None:
        if self.path.startswith("/redirect?to="):
            self.send_response(302)
            self.send_header("Location", self.path.split("=", 1)[1])
            self.end_headers()
            return
        body = b"x" * 200_000 if self.path.startswith("/big") else b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if self.path != "/big-undeclared":
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


async def test_loopback_is_refused_by_default(server: str) -> None:
    client = SafeHttpClient()
    try:
        with pytest.raises(DestinationBlocked) as raised:
            await client.get(f"{server}/ok")
        assert raised.value.details["scope"] == "loopback"
    finally:
        await client.aclose()


async def test_an_allowed_network_is_reachable(server: str) -> None:
    client = SafeHttpClient(policy=LOOPBACK_ONLY)
    try:
        response = await client.get(f"{server}/ok")
        assert response.status_code == 200 and response.json() == {"ok": True}
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "addresses", [["127.0.0.1"], ["10.0.0.5"], ["169.254.169.254"], ["::1"], ["fd00::1"]]
)
async def test_names_resolving_to_internal_addresses_are_refused(
    server: str, addresses: list[str]
) -> None:
    async def resolver(_host: str, _port: int) -> list[str]:
        return addresses

    port = server.rsplit(":", 1)[1]
    client = SafeHttpClient(resolver=resolver)
    try:
        with pytest.raises(DestinationBlocked):
            await client.get(f"http://looks-public.example:{port}/ok")
    finally:
        await client.aclose()


async def test_only_checked_addresses_are_connected_to() -> None:
    """The socket layer gets the checked address, never the host name, so a
    second DNS answer (rebinding) cannot change where the connection goes."""
    connected: list[str] = []

    class Recording(httpcore.AsyncNetworkBackend):
        async def connect_tcp(self, host: str, port: int, **_kwargs: Any) -> Any:
            connected.append(host)
            raise httpcore.ConnectError("not really connecting")

    async def resolver(_host: str, _port: int) -> list[str]:
        return ["10.0.0.5", "93.184.215.14", "127.0.0.1"]

    backend = GuardedNetworkBackend(DestinationPolicy(), resolver=resolver, backend=Recording())
    with pytest.raises(httpcore.ConnectError):
        await backend.connect_tcp("rebinding.example", 443)
    assert connected == ["93.184.215.14"]


async def test_redirects_are_checked_too(server: str) -> None:
    port = server.rsplit(":", 1)[1]
    client = SafeHttpClient(policy=LOOPBACK_ONLY)
    try:
        with pytest.raises(DestinationBlocked):
            await client.get(f"{server}/redirect?to=http://127.0.0.2:{port}/ok")
        allowed = await client.get(f"{server}/redirect?to={server}/ok")
        assert allowed.status_code == 200 and allowed.redirects
    finally:
        await client.aclose()


@pytest.mark.parametrize("path", ["/big", "/big-undeclared"])
async def test_response_size_is_limited(server: str, path: str) -> None:
    client = SafeHttpClient(policy=LOOPBACK_ONLY, max_bytes=10_000)
    try:
        with pytest.raises(ResponseTooLarge):
            await client.get(f"{server}{path}")
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://198.51.100.1/file",
        "http://user:secret@127.0.0.1/",
        "gopher://127.0.0.1:70/",
    ],
)
async def test_other_schemes_and_embedded_credentials_are_refused(url: str) -> None:
    client = SafeHttpClient(policy=LOOPBACK_ONLY)
    try:
        with pytest.raises(DestinationBlocked):
            await client.get(url)
    finally:
        await client.aclose()


async def test_unresolvable_names_are_reported() -> None:
    async def resolver(_host: str, _port: int) -> list[str]:
        raise OSError("no such name")

    client = SafeHttpClient(resolver=resolver)
    try:
        with pytest.raises(ProviderUnavailable):
            await client.get("http://does-not-exist.example/")
    finally:
        await client.aclose()


def test_policy_scopes() -> None:
    policy = DestinationPolicy()
    policy.check(ipaddress.ip_address("8.8.8.8"))
    policy.check(ipaddress.ip_address("2606:4700:4700::1111"))
    for blocked in (
        "0.0.0.0",  # noqa: S104 - an address being refused, not bound
        "100.64.0.1",
        "192.0.2.1",
        "224.0.0.1",
        "::ffff:127.0.0.1",
        "fe80::1",
        "64:ff9b::a00:1",  # NAT64 of 10.0.0.1
        "2002:7f00:1::1",  # 6to4 through 127.0.0.1
        "2002:c0a8:101::1",  # 6to4 through 192.168.1.1
        "2001:0:4136:e378:8000:63bf:f5ff:fffe",  # Teredo to client 10.0.0.1
        "64:ff9b:1::1",
    ):
        with pytest.raises(DestinationBlocked):
            policy.check(ipaddress.ip_address(blocked))
