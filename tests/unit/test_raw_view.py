"""How raw responses are shown: masked unless asked otherwise, never pretending."""

from __future__ import annotations

import json

from omniosint.evidence.service import masked_raw_view, raw_view

DOCUMENT = {"api_key": "sk-live-1234", "results": [{"password": "hunter2", "ip": "192.0.2.1"}]}


def test_json_is_masked_by_field_name() -> None:
    view = masked_raw_view(json.dumps(DOCUMENT).encode(), "application/json")
    assert view is not None and view["redacted"] is True and view["format"] == "json"
    text = json.dumps(view["body"])
    assert "sk-live-1234" not in text and "hunter2" not in text
    assert view["body"]["results"][0]["ip"] == "192.0.2.1"


def test_unmasked_view_is_the_original() -> None:
    view = raw_view(json.dumps(DOCUMENT).encode(), "application/json", redacted=False)
    assert view["body"] == DOCUMENT and view["redacted"] is False


def test_content_that_cannot_be_masked_has_no_masked_view() -> None:
    assert masked_raw_view(b"api_key=sk-live-1234\n", "text/plain") is None
    assert masked_raw_view(b"{not json", "application/json") is None
    assert raw_view(b"plain", "text/plain", redacted=False)["body"] == "plain"
