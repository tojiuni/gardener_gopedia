from unittest.mock import MagicMock

from gardener_gopedia.gopedia_client import GopediaClient, gopedia_json_search_failed


def test_gopedia_json_search_failed_parse_error():
    assert gopedia_json_search_failed({"_parse_error": True, "results": []}) is True


def test_gopedia_json_search_failed_failure_key():
    assert gopedia_json_search_failed({"failure": {"code": "x"}, "results": []}) is True


def test_gopedia_json_search_failed_ok_false():
    assert gopedia_json_search_failed({"ok": False, "results": []}) is True


def test_gopedia_json_search_failed_missing_results():
    assert gopedia_json_search_failed({"ok": True}) is True


def test_gopedia_json_search_failed_results_not_list():
    assert gopedia_json_search_failed({"results": {}}) is True


def test_gopedia_json_search_ok():
    assert gopedia_json_search_failed({"results": [{"l3_id": "a"}]}) is False


def test_search_json_query_params_and_header():
    client = GopediaClient("http://example.test", timeout_s=5.0)
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"results": []}
    resp.text = ""
    client._client.get = MagicMock(return_value=resp)

    client.search_json(
        "q1",
        7,
        detail="summary",
        fields=["title", "snippet", "l3_id"],
        request_id="req-abc",
    )

    client._client.get.assert_called_once()
    args, kwargs = client._client.get.call_args
    assert args[0] == "/api/search"
    assert kwargs["params"]["q"] == "q1"
    assert kwargs["params"]["format"] == "json"
    assert kwargs["params"]["project_id"] == "7"
    assert kwargs["params"]["detail"] == "summary"
    assert kwargs["params"]["fields"] == "title,snippet,l3_id"
    assert kwargs["headers"]["X-Request-ID"] == "req-abc"

    client.close()
