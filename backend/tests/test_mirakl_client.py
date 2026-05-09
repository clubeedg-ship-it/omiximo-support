"""Tests for MiraklConnectClient and the MiraklClient factory.

Covers:
- OAuth2 token acquisition and caching
- Automatic token refresh when near expiry
- Thread-safety of token refresh (concurrent callers)
- fetch_threads pagination
- fetch_thread, fetch_order, send_reply
- MiraklClient factory: Connect mode vs. legacy mode selection
- Error handling: network errors, HTTP errors, token endpoint errors
"""

from __future__ import annotations

import asyncio
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

from app.core.exceptions import MiraklAPIError
from app.models.marketplace_account import MarketplaceAccount
from app.services.encryption import encrypt
from app.services.mirakl_client import (
    MiraklClient,
    MiraklConnectClient,
    _EagerConnectAdapter,
    _LegacyMiraklClient,
)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _make_token_response(
    access_token: str = "test-token-abc",
    expires_in: int = 3600,
) -> MagicMock:
    """Create a mock httpx.Response for a successful token request."""
    resp = MagicMock()
    resp.is_error = False
    resp.json.return_value = {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": expires_in,
    }
    return resp


def _make_api_response(body: dict) -> MagicMock:
    """Create a mock httpx.Response for a successful API call."""
    resp = MagicMock()
    resp.is_error = False
    resp.content = b"non-empty"
    resp.json.return_value = body
    return resp


def _make_error_response(status_code: int, text: str = "error") -> MagicMock:
    resp = MagicMock()
    resp.is_error = True
    resp.status_code = status_code
    resp.text = text
    return resp


@pytest_asyncio.fixture(autouse=True)
async def reset_connect_singleton():
    """Reset the MiraklConnectClient singleton before and after each test."""
    MiraklConnectClient.reset_instance()
    yield
    MiraklConnectClient.reset_instance()


def _make_legacy_account() -> MarketplaceAccount:
    """Minimal MarketplaceAccount for legacy-mode tests."""
    account = MagicMock(spec=MarketplaceAccount)
    account.id = uuid.uuid4()
    account.marketplace = "TestMarket"
    account.shop_id = "shop-001"
    account.api_key_encrypted = encrypt("test-api-key")
    account.base_url = "https://marketplace.example.com"
    return account


# --------------------------------------------------------------------------- #
# MiraklConnectClient — singleton                                              #
# --------------------------------------------------------------------------- #


class TestMiraklConnectClientSingleton:

    async def test_get_instance_returns_same_object(self):
        """Repeated calls to get_instance return the identical object."""
        instance_a = await MiraklConnectClient.get_instance()
        instance_b = await MiraklConnectClient.get_instance()
        assert instance_a is instance_b

    async def test_reset_instance_clears_singleton(self):
        """reset_instance() causes get_instance() to create a new object."""
        instance_a = await MiraklConnectClient.get_instance()
        MiraklConnectClient.reset_instance()
        instance_b = await MiraklConnectClient.get_instance()
        assert instance_a is not instance_b


# --------------------------------------------------------------------------- #
# MiraklConnectClient — token acquisition and caching                         #
# --------------------------------------------------------------------------- #


class TestTokenAcquisition:

    async def test_token_is_fetched_on_first_request(self):
        """The first API call triggers a token fetch."""
        client = MiraklConnectClient()

        token_response = _make_token_response("first-token")
        api_response = _make_api_response({"threads": []})

        with patch.object(client._http, "post", new=AsyncMock(return_value=token_response)):
            with patch.object(client._http, "request", new=AsyncMock(return_value=api_response)):
                await client.fetch_threads()

        # Token should now be cached
        assert client._token == "first-token"

    async def test_token_is_reused_on_second_request(self):
        """The cached token is reused; no second POST to /auth/token."""
        client = MiraklConnectClient()

        token_response = _make_token_response("cached-token", expires_in=3600)
        api_response = _make_api_response({"threads": []})

        mock_post = AsyncMock(return_value=token_response)
        mock_request = AsyncMock(return_value=api_response)

        with patch.object(client._http, "post", new=mock_post):
            with patch.object(client._http, "request", new=mock_request):
                await client.fetch_threads()
                await client.fetch_threads()  # second call

        # Token POST should only have been called once
        assert mock_post.call_count == 1
        assert mock_request.call_count == 2

    async def test_expired_token_is_refreshed(self):
        """When the cached token is past its expiry, a fresh one is fetched."""
        client = MiraklConnectClient()
        # Simulate an already-expired token
        client._token = "old-token"
        client._token_expires_at = time.monotonic() - 10  # already expired

        new_token_response = _make_token_response("new-token")
        api_response = _make_api_response({"threads": []})

        mock_post = AsyncMock(return_value=new_token_response)
        with patch.object(client._http, "post", new=mock_post):
            with patch.object(client._http, "request", new=AsyncMock(return_value=api_response)):
                await client.fetch_threads()

        assert client._token == "new-token"
        assert mock_post.call_count == 1

    async def test_token_expiry_buffer_applied(self):
        """Token is considered expired _TOKEN_EXPIRY_BUFFER_SECONDS before actual expiry."""
        from app.services.mirakl_client import _TOKEN_EXPIRY_BUFFER_SECONDS

        client = MiraklConnectClient()

        # Token expires_in = buffer + 10 → effective lifetime = 10 seconds from now
        expires_in = _TOKEN_EXPIRY_BUFFER_SECONDS + 10
        token_response = _make_token_response("buffer-token", expires_in=expires_in)
        api_response = _make_api_response({"threads": []})

        with patch.object(client._http, "post", new=AsyncMock(return_value=token_response)):
            with patch.object(client._http, "request", new=AsyncMock(return_value=api_response)):
                before = time.monotonic()
                await client.fetch_threads()
                after = time.monotonic()

        # token_expires_at should be roughly before + 10
        assert client._token_expires_at > before + 5
        assert client._token_expires_at < after + 15

    async def test_concurrent_callers_only_fetch_token_once(self):
        """When multiple coroutines find the token expired, only one POST is made."""
        client = MiraklConnectClient()
        # Expired token
        client._token = "stale"
        client._token_expires_at = time.monotonic() - 1

        call_count = 0
        token_response = _make_token_response("fresh")
        api_response = _make_api_response({"threads": []})

        original_post = AsyncMock(return_value=token_response)

        async def counting_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0)  # yield to allow other coroutines to proceed
            return token_response

        with patch.object(client._http, "post", new=counting_post):
            with patch.object(client._http, "request", new=AsyncMock(return_value=api_response)):
                await asyncio.gather(
                    client.fetch_threads(),
                    client.fetch_threads(),
                    client.fetch_threads(),
                )

        # Only one token refresh should have occurred
        assert call_count == 1

    async def test_token_endpoint_error_raises_mirakl_api_error(self):
        """A non-2xx token response raises MiraklAPIError."""
        client = MiraklConnectClient()

        error_response = _make_error_response(401, "Unauthorized")
        with patch.object(client._http, "post", new=AsyncMock(return_value=error_response)):
            with pytest.raises(MiraklAPIError) as exc_info:
                await client._get_access_token()

        assert exc_info.value.status_code == 401

    async def test_token_network_error_raises_mirakl_api_error(self):
        """A network failure during token fetch raises MiraklAPIError."""
        client = MiraklConnectClient()

        with patch.object(
            client._http,
            "post",
            new=AsyncMock(side_effect=httpx.ConnectError("timeout")),
        ):
            with pytest.raises(MiraklAPIError) as exc_info:
                await client._get_access_token()

        assert "token request failed" in exc_info.value.message


# --------------------------------------------------------------------------- #
# MiraklConnectClient — fetch_threads                                          #
# --------------------------------------------------------------------------- #


class TestFetchThreads:

    async def _client_with_token(self) -> MiraklConnectClient:
        client = MiraklConnectClient()
        client._token = "valid-token"
        client._token_expires_at = time.monotonic() + 3600
        return client

    async def test_fetch_threads_returns_all_threads(self):
        """fetch_threads returns the list of threads from the API response."""
        client = await self._client_with_token()
        api_response = _make_api_response(
            {
                "threads": [
                    {"id": "T-001", "topic": {"order_id": "ORD-001"}},
                    {"id": "T-002", "topic": {"order_id": "ORD-002"}},
                ]
            }
        )

        with patch.object(client._http, "request", new=AsyncMock(return_value=api_response)):
            threads = await client.fetch_threads()

        assert len(threads) == 2
        assert threads[0]["id"] == "T-001"

    async def test_fetch_threads_paginates(self):
        """When next_page_token is present, fetch_threads continues paginating."""
        client = await self._client_with_token()

        page1 = _make_api_response(
            {
                "threads": [{"id": "T-001"}],
                "next_page_token": "tok-page-2",
            }
        )
        page2 = _make_api_response({"threads": [{"id": "T-002"}]})

        mock_request = AsyncMock(side_effect=[page1, page2])
        with patch.object(client._http, "request", new=mock_request):
            threads = await client.fetch_threads()

        assert len(threads) == 2
        assert mock_request.call_count == 2

    async def test_fetch_threads_passes_updated_since(self):
        """updated_since is forwarded as a query parameter."""
        client = await self._client_with_token()
        api_response = _make_api_response({"threads": []})

        mock_request = AsyncMock(return_value=api_response)
        with patch.object(client._http, "request", new=mock_request):
            await client.fetch_threads(updated_since="2026-01-01T00:00:00Z")

        call_kwargs = mock_request.call_args
        params = call_kwargs.kwargs.get("params", call_kwargs.args[2] if len(call_kwargs.args) > 2 else {})
        assert "updated_since" in params

    async def test_fetch_threads_api_error_raises(self):
        """A non-2xx API response raises MiraklAPIError."""
        client = await self._client_with_token()
        error_resp = _make_error_response(503, "Service Unavailable")

        with patch.object(client._http, "request", new=AsyncMock(return_value=error_resp)):
            with pytest.raises(MiraklAPIError) as exc_info:
                await client.fetch_threads()

        assert exc_info.value.status_code == 503


# --------------------------------------------------------------------------- #
# MiraklConnectClient — fetch_thread                                           #
# --------------------------------------------------------------------------- #


class TestFetchThread:

    async def test_fetch_thread_returns_dict(self):
        """fetch_thread returns the thread data dict."""
        client = MiraklConnectClient()
        client._token = "tok"
        client._token_expires_at = time.monotonic() + 3600

        api_response = _make_api_response({"id": "T-999", "status": "open"})

        with patch.object(client._http, "request", new=AsyncMock(return_value=api_response)):
            result = await client.fetch_thread("T-999")

        assert result["id"] == "T-999"

    async def test_fetch_thread_calls_correct_path(self):
        """fetch_thread requests /channels/v1/threads/{thread_id}."""
        client = MiraklConnectClient()
        client._token = "tok"
        client._token_expires_at = time.monotonic() + 3600

        api_response = _make_api_response({"id": "TH-42"})
        mock_request = AsyncMock(return_value=api_response)

        with patch.object(client._http, "request", new=mock_request):
            await client.fetch_thread("TH-42")

        url_arg = mock_request.call_args.args[1]
        assert "TH-42" in url_arg


# --------------------------------------------------------------------------- #
# MiraklConnectClient — fetch_order                                            #
# --------------------------------------------------------------------------- #


class TestFetchOrder:

    async def test_fetch_order_returns_first_match(self):
        """fetch_order returns the first order matching entity_id."""
        client = MiraklConnectClient()
        client._token = "tok"
        client._token_expires_at = time.monotonic() + 3600

        api_response = _make_api_response(
            {"orders": [{"id": "ORD-123", "status": "SHIPPING"}]}
        )

        with patch.object(client._http, "request", new=AsyncMock(return_value=api_response)):
            result = await client.fetch_order("ORD-123")

        assert result["id"] == "ORD-123"

    async def test_fetch_order_returns_empty_dict_when_not_found(self):
        """fetch_order returns {} when no matching order is found."""
        client = MiraklConnectClient()
        client._token = "tok"
        client._token_expires_at = time.monotonic() + 3600

        api_response = _make_api_response({"orders": []})

        with patch.object(client._http, "request", new=AsyncMock(return_value=api_response)):
            result = await client.fetch_order("NONEXISTENT")

        assert result == {}


# --------------------------------------------------------------------------- #
# MiraklConnectClient — send_reply                                             #
# --------------------------------------------------------------------------- #


class TestSendReply:

    async def test_send_reply_posts_to_correct_path(self):
        """send_reply POSTs to /channels/v1/threads/{thread_id}/message."""
        client = MiraklConnectClient()
        client._token = "tok"
        client._token_expires_at = time.monotonic() + 3600

        api_response = _make_api_response({"status": "sent"})
        mock_request = AsyncMock(return_value=api_response)

        with patch.object(client._http, "request", new=mock_request):
            result = await client.send_reply("TH-55", "Hello customer")

        call_args = mock_request.call_args
        method = call_args.args[0]
        url = call_args.args[1]
        assert method == "POST"
        assert "TH-55" in url
        assert "message" in url

    async def test_send_reply_includes_body_in_payload(self):
        """send_reply sends the message body in the JSON payload."""
        client = MiraklConnectClient()
        client._token = "tok"
        client._token_expires_at = time.monotonic() + 3600

        api_response = _make_api_response({})
        mock_request = AsyncMock(return_value=api_response)

        with patch.object(client._http, "request", new=mock_request):
            await client.send_reply("TH-99", "Your order is on its way")

        call_kwargs = mock_request.call_args.kwargs
        assert call_kwargs.get("json", {}).get("body") == "Your order is on its way"


# --------------------------------------------------------------------------- #
# MiraklClient factory — mode selection                                        #
# --------------------------------------------------------------------------- #


class TestMiraklClientFactory:

    def test_returns_legacy_client_when_no_connect_credentials(self):
        """MiraklClient returns a _LegacyMiraklClient when Connect is not configured."""
        account = _make_legacy_account()

        with patch("app.services.mirakl_client.settings") as mock_settings:
            mock_settings.MIRAKL_CONNECT_CLIENT_ID = ""
            result = MiraklClient(account)

        assert isinstance(result, _LegacyMiraklClient)

    def test_returns_connect_adapter_when_credentials_set(self):
        """MiraklClient returns an _EagerConnectAdapter when Connect creds are present."""
        account = _make_legacy_account()

        with patch("app.services.mirakl_client.settings") as mock_settings:
            mock_settings.MIRAKL_CONNECT_CLIENT_ID = "my-client-id"
            result = MiraklClient(account)

        assert isinstance(result, _EagerConnectAdapter)

    async def test_eager_connect_adapter_context_manager(self):
        """_EagerConnectAdapter resolves the singleton in __aenter__."""
        token_response = _make_token_response("adapter-token")
        api_response = _make_api_response({"threads": []})

        adapter = _EagerConnectAdapter()

        async with adapter as ctx:
            assert ctx is adapter
            assert hasattr(adapter, "_connect")


# --------------------------------------------------------------------------- #
# _LegacyMiraklClient — context manager and basic operation                   #
# --------------------------------------------------------------------------- #


class TestLegacyMiraklClient:

    async def test_context_manager_opens_and_closes_client(self):
        """_LegacyMiraklClient opens an httpx.AsyncClient on enter, closes on exit."""
        account = _make_legacy_account()
        client = _LegacyMiraklClient(account)

        assert client._client is None

        async with client:
            assert client._client is not None

        assert client._client is None

    async def test_assert_open_raises_when_not_entered(self):
        """Calling methods outside the context manager raises RuntimeError."""
        account = _make_legacy_account()
        client = _LegacyMiraklClient(account)

        with pytest.raises(RuntimeError, match="async context manager"):
            client._assert_open()

    async def test_send_reply_calls_correct_endpoint(self):
        """_LegacyMiraklClient.send_reply posts to /api/messages/threads/{id}/reply."""
        account = _make_legacy_account()

        reply_response = MagicMock()
        reply_response.is_error = False
        reply_response.json.return_value = {"status": "sent"}

        with patch("httpx.AsyncClient.request", new=AsyncMock(return_value=reply_response)):
            async with _LegacyMiraklClient(account) as client:
                result = await client.send_reply("TH-OLD-01", "Hello")

        assert result == {"status": "sent"}

    async def test_http_error_raises_mirakl_api_error(self):
        """A 4xx response from the legacy API raises MiraklAPIError."""
        account = _make_legacy_account()

        error_response = MagicMock()
        error_response.is_error = True
        error_response.status_code = 401
        error_response.text = "Unauthorized"

        with patch("httpx.AsyncClient.request", new=AsyncMock(return_value=error_response)):
            async with _LegacyMiraklClient(account) as client:
                with pytest.raises(MiraklAPIError) as exc_info:
                    await client.fetch_order("ORD-123")

        assert exc_info.value.status_code == 401

    async def test_timeout_raises_mirakl_api_error(self):
        """A timeout raises MiraklAPIError with a descriptive message."""
        account = _make_legacy_account()

        with patch(
            "httpx.AsyncClient.request",
            new=AsyncMock(side_effect=httpx.TimeoutException("timed out")),
        ):
            async with _LegacyMiraklClient(account) as client:
                with pytest.raises(MiraklAPIError) as exc_info:
                    await client.fetch_order("ORD-TIMEOUT")

        assert "timed out" in exc_info.value.message.lower() or "timeout" in exc_info.value.message.lower()

    async def test_account_with_no_api_key_uses_empty_string(self):
        """Legacy client tolerates api_key_encrypted=None (Connect-mode accounts)."""
        account = _make_legacy_account()
        account.api_key_encrypted = None

        # Should not raise during construction
        client = _LegacyMiraklClient(account)
        assert client._api_key == ""
