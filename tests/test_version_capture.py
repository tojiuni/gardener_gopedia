"""Unit tests for _fetch_gopedia_version helper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from gardener_gopedia.eval.service import _fetch_gopedia_version


def _mock_response(status_code: int, json_data: dict) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}", request=MagicMock(), response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


class TestFetchGopediaVersion:
    def test_success_returns_version_dict(self):
        version_payload = {
            "service": "gopedia",
            "version": "1.2.3",
            "git_sha": "abc1234",
            "built_at": "2026-05-01T00:00:00Z",
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_response(200, version_payload)

        with patch("gardener_gopedia.eval.service.httpx.Client", return_value=mock_client):
            result = _fetch_gopedia_version("http://gopedia.example.com")

        mock_client.get.assert_called_once_with("http://gopedia.example.com/api/version")
        assert result == version_payload

    def test_trailing_slash_stripped_from_url(self):
        version_payload = {"service": "gopedia", "version": "0.9"}
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_response(200, version_payload)

        with patch("gardener_gopedia.eval.service.httpx.Client", return_value=mock_client):
            result = _fetch_gopedia_version("http://gopedia.example.com/")

        mock_client.get.assert_called_once_with("http://gopedia.example.com/api/version")
        assert result == version_payload

    def test_http_error_returns_error_dict_not_raises(self):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_response(404, {})

        with patch("gardener_gopedia.eval.service.httpx.Client", return_value=mock_client):
            result = _fetch_gopedia_version("http://gopedia.example.com")

        assert "error" in result
        assert "fetched_at" in result

    def test_connection_error_returns_error_dict_not_raises(self):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("refused")

        with patch("gardener_gopedia.eval.service.httpx.Client", return_value=mock_client):
            result = _fetch_gopedia_version("http://gopedia.example.com")

        assert "error" in result
        assert "fetched_at" in result

    def test_timeout_returns_error_dict_not_raises(self):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("timed out")

        with patch("gardener_gopedia.eval.service.httpx.Client", return_value=mock_client):
            result = _fetch_gopedia_version("http://gopedia.example.com")

        assert "error" in result
        assert "fetched_at" in result

    def test_client_timeout_set_to_5_seconds(self):
        """Ensure the httpx.Client is always created with timeout=5.0."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_response(200, {"version": "x"})

        with patch("gardener_gopedia.eval.service.httpx.Client", return_value=mock_client) as MockClient:
            _fetch_gopedia_version("http://gopedia.example.com")

        MockClient.assert_called_once_with(timeout=5.0)
