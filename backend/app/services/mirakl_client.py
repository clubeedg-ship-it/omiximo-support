"""Mirakl REST API client.

Wraps the Mirakl Messaging and Orders API endpoints used by the support
automation pipeline. All HTTP calls are async via httpx.AsyncClient.

Mirakl API reference pattern (abbreviated):
  GET  /api/messages/threads          – List message threads for the shop
  GET  /api/orders/{order_id}         – Fetch order details
  POST /api/messages/threads/{id}/reply – Post a reply to a thread

Authentication uses the ``Authorization: <api_key>`` header pattern standard
across Mirakl marketplace instances.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.exceptions import MiraklAPIError
from app.models.marketplace_account import MarketplaceAccount
from app.services.encryption import decrypt


class MiraklClient:
    """Async HTTP client for the Mirakl Marketplace Seller API.

    A new instance should be created per-request or per-poll cycle because
    it opens (and should close) an httpx.AsyncClient.  Use as an async
    context manager::

        async with MiraklClient(account) as client:
            threads = await client.fetch_threads()
    """

    _DEFAULT_TIMEOUT = 30.0  # seconds

    def __init__(self, account: MarketplaceAccount) -> None:
        self._account = account
        self._base_url = account.base_url.rstrip("/")
        self._api_key = decrypt(account.api_key_encrypted)
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "MiraklClient":
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
                "MiraklClient must be used as an async context manager "
                "(async with MiraklClient(account) as client: ...)"
            )

    async def fetch_threads(
        self,
        *,
        page_size: int = 100,
        only_unanswered: bool = True,
    ) -> list[dict[str, Any]]:
        """Fetch all open message threads for the configured shop.

        Args:
            page_size:        Number of results per page (Mirakl default: 10, max: 100).
            only_unanswered:  When True, only threads awaiting a seller reply are returned.

        Returns:
            List of raw thread dicts as returned by the Mirakl API.

        Raises:
            MiraklAPIError: On any non-2xx HTTP response or network error.
        """
        self._assert_open()
        params: dict[str, Any] = {
            "max": page_size,
            "shop_id": self._account.shop_id,
        }
        if only_unanswered:
            params["waiting_for_response"] = "true"

        all_threads: list[dict[str, Any]] = []
        offset = 0

        while True:
            params["start_index"] = offset
            response = await self._request("GET", "/api/messages/threads", params=params)
            data = response.json()
            threads: list[dict[str, Any]] = data.get("threads", [])
            all_threads.extend(threads)

            # Mirakl uses total_count + offset-based pagination
            total_count: int = data.get("total_count", len(threads))
            offset += len(threads)
            if offset >= total_count or not threads:
                break

        return all_threads

    async def fetch_order(self, order_id: str) -> dict[str, Any]:
        """Fetch order details from the Mirakl Orders API.

        Args:
            order_id: The Mirakl order identifier (mirakl_order_id on SupportThread).

        Returns:
            Raw order dict as returned by the Mirakl API.

        Raises:
            MiraklAPIError: On any non-2xx HTTP response or network error.
        """
        self._assert_open()
        response = await self._request("GET", f"/api/orders/{order_id}")
        return response.json()

    async def send_reply(self, thread_id: str, body: str) -> dict[str, Any]:
        """Post a reply to a Mirakl message thread.

        This is the only write operation in the client. It must only be called
        after safety_rules validation has passed and audit logging is in place.

        Args:
            thread_id: The Mirakl thread identifier (mirakl_thread_id on SupportThread).
            body:      The message text to send.

        Returns:
            Raw confirmation dict as returned by the Mirakl API.

        Raises:
            MiraklAPIError: On any non-2xx HTTP response or network error.
        """
        self._assert_open()
        payload = {"body": body}
        response = await self._request(
            "POST",
            f"/api/messages/threads/{thread_id}/reply",
            json=payload,
        )
        return response.json()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Execute an HTTP request and raise MiraklAPIError on failure.

        Args:
            method: HTTP method string, e.g. "GET", "POST".
            path:   URL path relative to base_url.
            params: Query parameters.
            json:   JSON request body.

        Returns:
            The httpx.Response object (status already validated).

        Raises:
            MiraklAPIError: On HTTP errors or network connectivity issues.
        """
        assert self._client is not None  # guarded by _assert_open

        try:
            response = await self._client.request(
                method,
                path,
                params=params,
                json=json,
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
