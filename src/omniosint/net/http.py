"""The one HTTP client adapters use, with a destination policy (SSRF defence).

Every connection is made by a network backend that resolves the host name
itself, checks each address against the policy, and connects to an address it
has checked. Redirects therefore cannot lead somewhere the policy forbids, and
a host name that resolves to a public address when checked and a private one
when used (DNS rebinding) never reaches the private address: the connection
goes to the address that was checked. TLS still verifies the real host name.

By default only public Internet addresses are allowed. An approved scope
(Phase 8) can allow specific private networks.
"""

from __future__ import annotations

import ipaddress
import socket
import ssl
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import anyio
import httpcore
import httpx

from omniosint import __version__
from omniosint.net.addresses import IPAddress, IPNetwork, classify_address
from omniosint.providers.errors import (
    DestinationBlocked,
    ProviderTimeout,
    ProviderUnavailable,
    ResponseTooLarge,
)

USER_AGENT = f"OmniOSINT/{__version__}"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
_ALLOWED_SCHEMES = frozenset({"http", "https"})

Resolver = Callable[[str, int], Awaitable[list[str]]]


async def system_resolver(host: str, port: int) -> list[str]:
    infos = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses: list[str] = []
    for _family, _type, _proto, _canonical, sockaddr in infos:
        address = str(sockaddr[0]).split("%", 1)[0]
        if address not in addresses:
            addresses.append(address)
    return addresses


@dataclass(frozen=True, slots=True)
class DestinationPolicy:
    """Which addresses outbound requests may reach."""

    allowed_networks: tuple[IPNetwork, ...] = ()

    def check(self, address: IPAddress) -> None:
        info = classify_address(address)
        if info.is_public:
            return
        if any(address in network for network in self.allowed_networks):
            return
        raise DestinationBlocked(
            f"Refused to connect to {address}: {info.scope.value.replace('_', '-')} address.",
            details={"address": str(address), "scope": info.scope.value},
        )


class GuardedNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(
        self,
        policy: DestinationPolicy,
        *,
        resolver: Resolver = system_resolver,
        backend: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self._policy = policy
        self._resolver = resolver
        self._backend = backend or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore's interface
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            literal = ipaddress.ip_address(host.strip("[]"))
            candidates = [str(literal)]
        except ValueError:
            try:
                candidates = await self._resolver(host, port)
            except OSError as error:
                raise ProviderUnavailable(f"The name {host} could not be resolved.") from error
        allowed: list[str] = []
        refusal: DestinationBlocked | None = None
        for candidate in candidates:
            try:
                self._policy.check(ipaddress.ip_address(candidate))
            except DestinationBlocked as error:
                refusal = refusal or error
                continue
            allowed.append(candidate)
        if not allowed:
            raise refusal or DestinationBlocked(f"{host} did not resolve to any address.")
        last_error: Exception | None = None
        for address in allowed:
            try:
                return await self._backend.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout, OSError) as error:
                last_error = error
        assert last_error is not None
        raise last_error

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore's interface
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise DestinationBlocked("Unix sockets are not reachable through this client.")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class GuardedTransport(httpx.AsyncHTTPTransport):
    """``httpx`` transport whose connection pool uses ``GuardedNetworkBackend``."""

    def __init__(
        self,
        policy: DestinationPolicy,
        *,
        resolver: Resolver = system_resolver,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        context = ssl_context or ssl.create_default_context()
        super().__init__(verify=context, trust_env=False, retries=0)
        # Replace the pool httpx built with one that cannot reach blocked addresses.
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=context,
            max_connections=20,
            max_keepalive_connections=10,
            keepalive_expiry=30.0,
            network_backend=GuardedNetworkBackend(policy, resolver=resolver),
        )


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status_code: int
    url: str
    headers: Mapping[str, str]
    content: bytes
    content_type: str
    redirects: tuple[str, ...] = field(default_factory=tuple)

    def json(self) -> Any:
        import json

        return json.loads(self.content)


class SafeHttpClient:
    """Outbound HTTP for adapters: destination policy, timeouts, size limit."""

    def __init__(
        self,
        *,
        policy: DestinationPolicy | None = None,
        timeout_seconds: float = 30.0,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_redirects: int = 5,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver = system_resolver,
    ) -> None:
        self._max_bytes = max_bytes
        self._client = httpx.AsyncClient(
            transport=transport
            or GuardedTransport(policy or DestinationPolicy(), resolver=resolver),
            timeout=httpx.Timeout(timeout_seconds, connect=min(10.0, timeout_seconds)),
            follow_redirects=True,
            max_redirects=max_redirects,
            trust_env=False,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json, */*;q=0.5"},
        )

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str | int | float | Sequence[str]] | None = None,
        json: Any = None,
        max_bytes: int | None = None,
    ) -> HttpResponse:
        target = httpx.URL(url)
        if target.scheme not in _ALLOWED_SCHEMES:
            raise DestinationBlocked(f"Only http and https are allowed, not {target.scheme}.")
        if target.userinfo:
            raise DestinationBlocked("Credentials must not be placed in URLs.")
        limit = max_bytes or self._max_bytes
        try:
            async with self._client.stream(
                method, target, headers=headers, params=params, json=json
            ) as response:
                declared = response.headers.get("content-length")
                if declared is not None and declared.isdigit() and int(declared) > limit:
                    raise ResponseTooLarge(details={"limit": limit, "declared": int(declared)})
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise ResponseTooLarge(details={"limit": limit})
                    chunks.append(chunk)
                return HttpResponse(
                    status_code=response.status_code,
                    url=str(response.url),
                    headers=dict(response.headers),
                    content=b"".join(chunks),
                    content_type=response.headers.get("content-type", "application/octet-stream"),
                    redirects=tuple(str(item.url) for item in response.history),
                )
        except httpx.TimeoutException as error:
            raise ProviderTimeout() from error
        except httpx.TooManyRedirects as error:
            raise ProviderUnavailable("Too many redirects.") from error
        except httpx.TransportError as error:
            if isinstance(error.__cause__, DestinationBlocked | ProviderUnavailable):
                raise error.__cause__ from None
            raise ProviderUnavailable(f"The connection failed: {type(error).__name__}.") from error

    async def get(self, url: str, **kwargs: Any) -> HttpResponse:
        return await self.request("GET", url, **kwargs)

    async def aclose(self) -> None:
        await self._client.aclose()
