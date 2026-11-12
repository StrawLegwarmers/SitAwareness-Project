import pytest
import requests

import llm


def test_json_fences_are_stripped():
    assert llm._parse_json('```json\n{"narratives": []}\n```') == {"narratives": []}


@pytest.mark.parametrize("text", ['{"narratives": [', '[1, 2]', ''])
def test_bad_json_asks_for_a_smaller_call(text):
    with pytest.raises(llm.LLMError) as ex:
        llm._parse_json(text)
    assert ex.value.smaller


def test_cut_off_gemini_answer_is_reported(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(llm, "_post_with_retries", lambda *a: {
        "candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": '{"narr'}]}}]})
    with pytest.raises(llm.LLMError) as ex:
        llm._gemini("s", "p", {}, "model")
    assert ex.value.smaller and "cut off" in str(ex.value)


def test_network_errors_are_retried_then_reported(monkeypatch):
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise requests.ConnectionError("down")
    monkeypatch.setattr(llm.requests, "post", boom)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    with pytest.raises(llm.LLMError, match="network error"):
        llm._post_with_retries("https://example.invalid", {"x-goog-api-key": "secret"}, {})
    assert len(calls) == len(llm.RETRY_WAITS) + 1


def test_error_messages_never_contain_the_key(monkeypatch):
    class R:
        status_code, headers, text = 400, {}, "bad request"

        def json(self):
            return {"error": {"message": "API key not valid"}}
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: R())
    with pytest.raises(llm.LLMError) as ex:
        llm._post_with_retries("https://example.invalid", {"x-goog-api-key": "secret-123"}, {})
    assert "secret-123" not in str(ex.value)


def test_mock_can_pretend_to_be_cut_off(monkeypatch):
    monkeypatch.setenv("MOCK_MAX_GROUPS", "1")
    prompt = "### Group 1\n[1] A (x, en) | One\n### Group 2\n[2] B (x, en) | Two\n"
    with pytest.raises(llm.LLMError) as ex:
        llm._mock("", prompt, {}, "")
    assert ex.value.smaller


def test_error_messages_lose_project_identifiers():
    msg = ("Quota exceeded for quota metric 'Generate Content API requests per minute' of service "
           "'generativelanguage.googleapis.com' for consumer 'project_number:123456789012'. owner@example.com")
    out = llm.scrub(msg)
    assert "123456789012" not in out and "owner@example.com" not in out and "Quota exceeded" in out
    assert "AIza" not in llm.scrub("key AIza" + "x" * 35)
