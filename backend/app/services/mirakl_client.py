"""Mirakl API client.

Supports two authentication modes:

1. **Mirakl Connect (preferred)** — OAuth2 client_credentials flow against
   https://connect-api.mirakl.net. A single set of credentials (client_id,
   client_secret) grants access to all linked marketplaces. Activated when
   ``MIRAKL_CONNECT_CLIENT_ID`` is set in the application config.

2. **Legacy per-account API key** — Uses the ``Authorization: <api_key>``
   header pattern against a per-marketplace base URL. Activated when the
   Connect credentials are absent and a ``MarketplaceAccount`` with an
   encrypted API key is provided. Preserved for backwards compatibility.

The module exposes:
  - ``MiraklConnectClient``: Singleton for the Connect API. Token caching and
    refresh are automatic and thread-safe via ``asyncio.Lock``.
  - ``MiraklClient``: Context-manager wrapper that transparently picks Connect
    or legacy mode. Callers use the same interface regardless of mode.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

from app.config import settings
from app.core.exceptions import MiraklAPIError
from app.models.marketplace_account import MarketplaceAccount
from app.services.encryption import decrypt

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Mirakl Connect singleton                                                     #
# --------------------------------------------------------------------------- #

_TOKEN_EXPIRY_BUFFER_SECONDS = 300  # refresh 5 min before actual expiry


class MiraklConnectClient:
    """Singleton HTTP client for the Mirakl Connect API.

    Manages OAuth2 token acquisition and caching. The token is refreshed
    automatically whenever it is within ``_TOKEN_EXPIRY_BUFFER_SECONDS`` of
    expiry. Access to the cached token is serialised with an ``asyncio.Lock``
    so that concurrent callers never race to refresh it.

    Usage::

        client = MiraklConnectClient.get_instance()
        threads = await client.fetch_threads(updated_since="2026-01-01T00:00:00Z")
    """

    _instance: MiraklConnectClient | None = None
    _instance_lock: asyncio.Lock = asyncio.Lock()

    def __init__(self) -> None:
        self._base_url = settings.MIRAKL_CONNECT_API_URL.rstrip("/")
        self._client_id = settings.MIRAKL_CONNECT_CLIENT_ID
        self._client_secret = settings.MIRAKL_CONNECT_CLIENT_SECRET
        self._token: str | None = None
        self._token_expires_at: float = 0.0  # unix timestamp
        self._token_lock: asyncio.Lock = asyncio.Lock()
        self._http: httpx.AsyncClient = httpx.AsyncClient(timeout=30.0)

    # ---------------------------------------------------------------------- #
    # Singleton access                                                         #
    # ---------------------------------------------------------------------- #

    @classmethod
    async def get_instance(cls) -> "MiraklConnectClient":
        """Return the process-wide singleton, creating it on first call."""
        async with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Destroy the singleton — intended for use in tests only."""
        cls._instance = None

    # ---------------------------------------------------------------------- #
    # Token management                                                         #
    # ---------------------------------------------------------------------- #

    async def _get_access_token(self) -> str:
        """Return a valid Bearer token, refreshing if necessary.

        The lock ensures that when two concurrent coroutines both detect an
        expired token, only the first one fetches a new one — the second
        re-checks after acquiring the lock and reuses the freshly cached token.
        """
        async with self._token_lock:
            now = time.monotonic()
            if self._token and now < self._token_expires_at:
                return self._token

            logger.debug("Mirakl Connect: acquiring new OAuth2 token")
            token_url = f"{self._base_url}/auth/token"
            try:
                response = await self._http.post(
                    token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            except httpx.RequestError as exc:
                raise MiraklAPIError(
                    "Mirakl Connect: token request failed",
                    detail=str(exc),
                ) from exc

            if response.is_error:
                raise MiraklAPIError(
                    f"Mirakl Connect: token endpoint returned {response.status_code}",
                    status_code=response.status_code,
                    detail=response.text[:500],
                )

            payload = response.json()
            self._token = payload["access_token"]
            expires_in: int = int(payload.get("expires_in", 3600))
            self._token_expires_at = (
                now + expires_in - _TOKEN_EXPIRY_BUFFER_SECONDS
            )
            logger.debug(
                "Mirakl Connect: token acquired, valid for ~%ds", expires_in
            )
            return self._token  # type: ignore[return-value]

    # ---------------------------------------------------------------------- #
    # Public API methods                                                       #
    # ---------------------------------------------------------------------- #

    async def fetch_threads(
        self,
        *,
        updated_since: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Fetch all threads across all channels, with automatic pagination.

        Args:
            updated_since: ISO-8601 datetime string; only threads updated after
                           this timestamp are returned. Pass ``None`` to fetch all.
            limit:         Page size (Connect API default: 50, max: 50).

        Returns:
            List of raw thread dicts as returned by the Connect API.

        Raises:
            MiraklAPIError: On any non-2xx HTTP response or network error.
        """
        all_threads: list[dict[str, Any]] = []
        page_token: str | None = None

        while True:
            params: dict[str, Any] = {"limit": limit}
            if updated_since:
                params["updated_since"] = updated_since
            if page_token:
                params["page_token"] = page_token

            data = await self._request("GET", "/channels/v1/threads", params=params)
            threads: list[dict[str, Any]] = data.get("threads", [])
            all_threads.extend(threads)

            page_token = data.get("next_page_token") or data.get("page_token")
            if not page_token or not threads:
                break

        return all_threads

    async def fetch_thread(self, thread_id: str) -> dict[str, Any]:
        """Fetch a single thread by its Connect thread ID.

        Args:
            thread_id: The Mirakl Connect thread identifier.

        Returns:
            Raw thread dict as returned by the Connect API.

        Raises:
            MiraklAPIError: On any non-2xx HTTP response or network error.
        """
        return await self._request(
            "GET", f"/channels/v1/threads/{thread_id}"
        )

    async def fetch_order(self, order_id: str) -> dict[str, Any]:
        """Fetch order details filtered by entity ID.

        The Connect Orders API lists orders across all channels. We filter by
        entity_id (the marketplace-specific order identifier) and return the
        first match.

        Args:
            order_id: The marketplace-specific order identifier stored on
                      ``SupportThread.mirakl_order_id``.

        Returns:
            Raw order dict, or an empty dict if no order was found.

        Raises:
            MiraklAPIError: On any non-2xx HTTP response or network error.
        """
        data = await self._request(
            "GET",
            "/channels/v1/orders",
            params={"entity_id": order_id, "limit": 1},
        )
        orders: list[dict[str, Any]] = data.get("orders", [])
        return orders[0] if orders else {}

    async def send_reply(self, thread_id: str, body: str) -> dict[str, Any]:
        """Post a reply to a Mirakl Connect conversation.

        Uses multipart/form-data with a ``message_input`` JSON part as required
        by the Mirakl conversations API. The Connect API infers the recipient
        from conversation context, so no ``to`` field is needed.

        This is the only write operation in the client. It must only be called
        after ``safety_rules`` validation has passed and ``audit_log`` is in
        place.

        Args:
            thread_id: The Mirakl Connect thread identifier.
            body:      The message text to send.

        Returns:
            Raw confirmation dict as returned by the Connect API.

        Raises:
            MiraklAPIError: On any non-2xx HTTP response or network error.
        """
        token = await self._get_access_token()
        url = f"{self._base_url}/conversations/{thread_id}/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        message_input = json.dumps({"body": body})
        files = {"message_input": (None, message_input, "application/json")}

        try:
            response = await self._http.request(
                "POST",
                url,
                files=files,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise MiraklAPIError(
                f"Mirakl Connect API request timed out: POST /conversations/{thread_id}/messages",
                detail=str(exc),
            ) from exc
        except httpx.RequestError as exc:
            raise MiraklAPIError(
                f"Mirakl Connect API network error: POST /conversations/{thread_id}/messages",
                detail=str(exc),
            ) from exc

        if response.is_error:
            raise MiraklAPIError(
                f"Mirakl Connect API returned {response.status_code}: POST /conversations/{thread_id}/messages",
                status_code=response.status_code,
                detail=response.text[:500],
            )

        if not response.content:
            return {}

        return response.json()  # type: ignore[no-any-return]

    # ---------------------------------------------------------------------- #
    # Internal helpers                                                         #
    # ---------------------------------------------------------------------- #

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute an authenticated Connect API request.

        Obtains a fresh Bearer token for each call (the token cache makes this
        cheap after the first request).

        Args:
            method: HTTP method string, e.g. "GET", "POST".
            path:   URL path relative to the Connect API base URL.
            params: Query parameters.
            json:   JSON request body.

        Returns:
            Parsed JSON response body as a dict.

        Raises:
            MiraklAPIError: On HTTP errors or network connectivity issues.
        """
        token = await self._get_access_token()
        url = f"{self._base_url}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        try:
            response = await self._http.request(
                method,
                url,
                params=params,
                json=json,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise MiraklAPIError(
                f"Mirakl Connect API request timed out: {method} {path}",
                detail=str(exc),
            ) from exc
        except httpx.RequestError as exc:
            raise MiraklAPIError(
                f"Mirakl Connect API network error: {method} {path}",
                detail=str(exc),
            ) from exc

        if response.is_error:
            raise MiraklAPIError(
                f"Mirakl Connect API returned {response.status_code}: {method} {path}",
                status_code=response.status_code,
                detail=response.text[:500],
            )

        # 204 No Content and similar responses have no body
        if not response.content:
            return {}

        return response.json()  # type: ignore[no-any-return]


# --------------------------------------------------------------------------- #
# Legacy per-account client (backwards compatibility)                         #
# --------------------------------------------------------------------------- #


class _LegacyMiraklClient:
    """Per-account Mirakl client using the shop API key authentication pattern.

    Retained for backwards compatibility. This class is used when
    ``MIRAKL_CONNECT_CLIENT_ID`` is not configured, enabling operators who
    manage individual marketplace API keys to continue using the system.
    """

    _DEFAULT_TIMEOUT = 30.0

    def __init__(self, account: MarketplaceAccount) -> None:
        self._account = account
        self._base_url = account.base_url.rstrip("/")
        api_key_enc = account.api_key_encrypted or ""
        self._api_key = decrypt(api_key_enc) if api_key_enc else ""
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "_LegacyMiraklClient":
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": self._api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=self._DEFAULT_TIMEOUT,
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _assert_open(self) -> None:
        if self._client is None:
            raise RuntimeError(
                "MiraklClient must be used as an async context manager"
            )

    async def fetch_threads(
        self,
        *,
        page_size: int = 100,
        only_unanswered: bool = True,
    ) -> list[dict[str, Any]]:
        self._assert_open()
        params: dict[str, Any] = {
            "limit": page_size,
            "with_messages": "true",
        }
        if only_unanswered:
            params["entity_type"] = "MMP_ORDER"

        all_threads: list[dict[str, Any]] = []

        while True:
            response = await self._raw_request("GET", "/api/inbox/threads", params=params)
            data = response.json()
            threads: list[dict[str, Any]] = data.get("data", [])
            all_threads.extend(threads)

            next_token = data.get("next_page_token")
            if not next_token or not threads:
                break
            params["page_token"] = next_token

        return all_threads

    async def fetch_order(self, order_id: str) -> dict[str, Any]:
        # Mirakl exposes orders via the list endpoint (OR11), not /api/orders/{id}
        # (which returns 410). Query by order id and take the single match.
        self._assert_open()
        response = await self._raw_request(
            "GET", "/api/orders", params={"order_ids": order_id}
        )
        orders = response.json().get("orders", [])
        return orders[0] if orders else {}

    async def send_reply(self, thread_id: str, body: str) -> dict[str, Any]:
        """Post a reply to a Mirakl thread using multipart/form-data.

        The Mirakl M12 inbox API requires a ``message_input`` multipart part
        containing JSON with ``body`` and ``to`` fields. This method bypasses
        ``_raw_request`` because that helper does not support the ``files=``
        parameter needed for multipart encoding.

        Args:
            thread_id: The Mirakl thread identifier.
            body:      The message text to send.

        Returns:
            Parsed JSON response body as a dict.

        Raises:
            MiraklAPIError: On any non-2xx HTTP response or network error.
        """
        self._assert_open()
        assert self._client is not None

        path = f"/api/inbox/threads/{thread_id}/message"
        message_input = json.dumps(
            {"body": body, "to": [{"type": "CUSTOMER"}]}
        )
        files = {"message_input": (None, message_input, "application/json")}
        headers = {
            "Authorization": self._api_key,
            "Accept": "application/json",
        }

        try:
            response = await self._client.request(
                "POST",
                path,
                files=files,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise MiraklAPIError(
                f"Mirakl API request timed out: POST {path}",
                account_id=str(self._account.id),
                detail=str(exc),
            ) from exc
        except httpx.RequestError as exc:
            raise MiraklAPIError(
                f"Mirakl API network error: POST {path}",
                account_id=str(self._account.id),
                detail=str(exc),
            ) from exc

        if response.is_error:
            raise MiraklAPIError(
                f"Mirakl API returned {response.status_code}: POST {path}",
                status_code=response.status_code,
                account_id=str(self._account.id),
                detail=response.text[:500],
            )

        return response.json()

    async def _raw_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        assert self._client is not None

        try:
            response = await self._client.request(
                method, path, params=params, json=json
            )
        except httpx.TimeoutException as exc:
            raise MiraklAPIError(
                f"Mirakl API request timed out: {method} {path}",
                account_id=str(self._account.id),
                detail=str(exc),
            ) from exc
        except httpx.RequestError as exc:
            raise MiraklAPIError(
                f"Mirakl API network error: {method} {path}",
                account_id=str(self._account.id),
                detail=str(exc),
            ) from exc

        if response.is_error:
            raise MiraklAPIError(
                f"Mirakl API returned {response.status_code}: {method} {path}",
                status_code=response.status_code,
                account_id=str(self._account.id),
                detail=response.text[:500],
            )

        return response


# --------------------------------------------------------------------------- #
# Unified MiraklClient facade                                                  #
# --------------------------------------------------------------------------- #


class _ConnectClientContextAdapter:
    """Wraps ``MiraklConnectClient`` in the async context-manager protocol.

    The Connect client is a long-lived singleton; callers in ``draft_pipeline``
    and ``auto_send`` use ``async with MiraklClient(account) as client:``.
    This adapter gives them the same interface while delegating to the
    singleton's methods.
    """

    def __init__(self, connect: MiraklConnectClient) -> None:
        self._connect = connect

    async def __aenter__(self) -> "_ConnectClientContextAdapter":
        return self

    async def __aexit__(self, *_: Any) -> None:
        pass  # singleton lifecycle is managed elsewhere

    async def fetch_threads(
        self,
        *,
        updated_since: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return await self._connect.fetch_threads(
            updated_since=updated_since, limit=limit
        )

    async def fetch_order(self, order_id: str) -> dict[str, Any]:
        return await self._connect.fetch_order(order_id)

    async def send_reply(self, thread_id: str, body: str) -> dict[str, Any]:
        return await self._connect.send_reply(thread_id, body)


def MiraklClient(account: MarketplaceAccount) -> Any:
    """Factory that returns the appropriate Mirakl client for the given account.

    When ``MIRAKL_CONNECT_CLIENT_ID`` is configured, returns a
    ``_ConnectClientContextAdapter`` backed by the process-wide
    ``MiraklConnectClient`` singleton. Otherwise returns a
    ``_LegacyMiraklClient`` that uses the account's encrypted per-shop API key.

    This preserves the existing call pattern throughout the codebase::

        async with MiraklClient(account) as client:
            threads = await client.fetch_threads()

    The returned object always supports: ``fetch_threads``, ``fetch_order``,
    ``send_reply``, and the async context-manager protocol.

    NOTE: Because ``MiraklConnectClient.get_instance()`` is a coroutine, the
    Connect path cannot be resolved inside this synchronous factory. The
    Connect singleton is initialised lazily on first use inside the adapter.
    To avoid ``await`` in a factory function, the adapter holds a reference
    to the class and resolves the singleton on first method call — but for
    simplicity in the current design, the singleton is created eagerly at
    module import via the private helper ``_get_connect_adapter``.
    """
    if settings.MIRAKL_CONNECT_CLIENT_ID:
        return _EagerConnectAdapter()
    return _LegacyMiraklClient(account)


class _EagerConnectAdapter:
    """Context-manager adapter that resolves the Connect singleton on enter.

    This is needed because ``MiraklConnectClient.get_instance()`` is a
    coroutine but ``MiraklClient(account)`` is a synchronous factory. The
    resolution is deferred to ``__aenter__``.
    """

    async def __aenter__(self) -> "_EagerConnectAdapter":
        self._connect = await MiraklConnectClient.get_instance()
        return self

    async def __aexit__(self, *_: Any) -> None:
        pass

    async def fetch_threads(
        self,
        *,
        updated_since: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return await self._connect.fetch_threads(
            updated_since=updated_since, limit=limit
        )

    async def fetch_order(self, order_id: str) -> dict[str, Any]:
        return await self._connect.fetch_order(order_id)

    async def send_reply(self, thread_id: str, body: str) -> dict[str, Any]:
        return await self._connect.send_reply(thread_id, body)
