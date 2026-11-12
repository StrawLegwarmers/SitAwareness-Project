"""
llm.py - the one place that talks to an AI model.

The rest of the pipeline only ever calls:

    ask_json(system, prompt, schema) -> dict

and never knows which company's model answered. Swapping Gemini for Claude is a
change to config/ai.yaml, not to the pipeline. (This is called an "adapter": one
plug shape on our side, a different adapter for each socket.)

Each provider is just an HTTPS POST with JSON in and JSON out. No SDK needed.
"""
from __future__ import annotations

import json
import os
import re
import time

import requests

from config import ROOT, load_ai

TIMEOUT = 180  # seconds; big prompts can take a while


class LLMError(RuntimeError):
    """
    An AI call failed. `smaller` is True when a smaller request might succeed: the answer was
    cut off at the output limit, wasn't valid JSON, or was blocked. narratives.py then splits
    the call in two and tries each half.
    """

    def __init__(self, message: str, smaller: bool = False):
        super().__init__(message)
        self.smaller = smaller


def _key(name: str) -> str:
    """
    Read an API key from the environment. In Codespaces and GitHub Actions it's set
    as a *secret*, so it never appears in your code or in Git. As a fallback for
    running on your own computer, a line like GEMINI_API_KEY=... in a .env file works
    (.env is in .gitignore, so it can't be committed by accident).
    """
    if os.environ.get(name):
        return os.environ[name]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise LLMError(f"{name} is not set. See docs/operations.md (API keys).")


RETRY_WAITS = [15, 30, 60]   # seconds between attempts: "exponential backoff"


def scrub(text: str) -> str:
    """
    Error messages end up in the public Actions log and the state file. Google's quota errors name
    your cloud project ("consumer 'project_number:123456789012'"): remove identifiers like that,
    and anything shaped like a key, before a message goes anywhere.
    """
    text = re.sub(r"AIza[0-9A-Za-z_\-]{35}|sk-ant-[0-9A-Za-z_\-]+", "[key removed]", str(text))
    text = re.sub(r"(project[_ ]?(?:number|id)?\s*[:=/]\s*)[\w-]+", r"\1[removed]", text, flags=re.I)
    text = re.sub(r"projects/[\w-]+", "projects/[removed]", text)
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[email removed]", text)
    return re.sub(r"\b\d{7,}\b", "[number removed]", text)


def _post_with_retries(url: str, headers: dict, body: dict) -> dict:
    """
    POST, retrying on 'too many requests' (429), temporary server errors (5xx) and network
    problems (timeouts, dropped connections). Each retry waits longer than the last (15s, 30s,
    60s), or as long as the server asks (Retry-After, up to 2 minutes). Free tiers have
    per-minute limits, so waiting is usually all it takes.
    Never puts the key in an error message: keys travel in headers, which are never printed.
    """
    for wait in [*RETRY_WAITS, None]:
        try:
            r = requests.post(url, headers=headers, json=body, timeout=TIMEOUT)
        except (requests.Timeout, requests.ConnectionError) as ex:
            if not wait:
                raise LLMError(f"network error: {type(ex).__name__}") from None
            print(f"    network problem ({type(ex).__name__}), retrying in {wait}s...")
            time.sleep(wait)
            continue
        if r.status_code == 200:
            try:
                return r.json()
            except ValueError:
                raise LLMError("the AI service returned something that isn't JSON", smaller=True) from None
        retryable = r.status_code == 429 or r.status_code >= 500
        if retryable and wait:
            asked = r.headers.get("Retry-After", "")
            wait = min(int(asked), 120) if asked.isdigit() else wait
            print(f"    AI busy or rate-limited (HTTP {r.status_code}), retrying in {wait}s...")
            time.sleep(wait)
            continue
        try:  # both Google and Anthropic put a readable message at error.message
            detail = r.json()["error"]["message"]
        except Exception:
            detail = r.text[:300]
        raise LLMError(f"HTTP {r.status_code}: {scrub(str(detail)[:300])}")
    raise LLMError("gave up after retries")


def _parse_json(text: str) -> dict:
    """Models sometimes wrap JSON in ```json fences. Strip them, then parse."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as ex:
        raise LLMError(f"model did not return valid JSON ({ex.msg} at character {ex.pos} of {len(text)})",
                       smaller=True) from None
    if not isinstance(data, dict):
        raise LLMError("model returned JSON that isn't an object", smaller=True)
    return data


# Why a Gemini answer stopped. Anything but STOP means the JSON is cut off or missing.
GEMINI_STOPS = {
    "MAX_TOKENS": "the answer was cut off at the output limit",
    "SAFETY": "the answer was blocked by the safety filter",
    "RECITATION": "the answer was blocked for repeating source text",
    "BLOCKLIST": "the answer was blocked (blocklist)",
    "PROHIBITED_CONTENT": "the answer was blocked (prohibited content)",
    "SPII": "the answer was blocked (personal information)",
    "MALFORMED_FUNCTION_CALL": "the model produced a malformed answer",
}


# ── Providers ────────────────────────────────────────────────────────────────

def _gemini(system: str, prompt: str, schema: dict, model: str) -> dict:
    # Google's stable generateContent API. responseJsonSchema makes the model reply in
    # exactly our JSON shape ("structured output").
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
            "maxOutputTokens": int(load_ai().get("max_output_tokens", 16384)),
        },
    }
    data = _post_with_retries(url, {"x-goog-api-key": _key("GEMINI_API_KEY")}, body)
    usage = data.get("usageMetadata", {})
    print(f"    tokens: {usage.get('promptTokenCount', '?')} in, {usage.get('candidatesTokenCount', '?')} out"
          + (f", {usage['thoughtsTokenCount']} thinking" if usage.get("thoughtsTokenCount") else ""))
    blocked = (data.get("promptFeedback") or {}).get("blockReason")
    if blocked:
        raise LLMError(f"the prompt was blocked ({blocked})", smaller=True)
    cand = (data.get("candidates") or [{}])[0]
    reason = cand.get("finishReason", "STOP")
    if reason not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
        raise LLMError(GEMINI_STOPS.get(reason, f"the answer stopped early ({reason})"), smaller=True)
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text.strip():
        raise LLMError("the answer was empty", smaller=True)
    return _parse_json(text)


def _anthropic(system: str, prompt: str, schema: dict, model: str) -> dict:
    # Claude's Messages API. We describe the JSON shape in the prompt and parse the reply.
    body = {
        "model": model,
        "max_tokens": int(load_ai().get("max_output_tokens", 16000)),
        "system": system,
        "messages": [{"role": "user", "content": prompt + "\n\nReply with JSON only, matching this JSON Schema:\n"
                      + json.dumps(schema)}],
    }
    headers = {"x-api-key": _key("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"}
    data = _post_with_retries("https://api.anthropic.com/v1/messages", headers, body)
    u = data.get("usage", {})
    print(f"    tokens: {u.get('input_tokens', '?')} in, {u.get('output_tokens', '?')} out")
    if data.get("stop_reason") == "max_tokens":
        raise LLMError("the answer was cut off at the output limit", smaller=True)
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    return _parse_json(text)


def _mock(system: str, prompt: str, schema: dict, model: str) -> dict:
    """
    No AI at all: pretend. Lets you test everything else offline, for free. It turns every group
    in the prompt into a story (continuing the suggested one when there is a suggestion), and in
    the first group it deliberately writes some BAD reports (an analysis word, an article number
    that doesn't exist, a wrong number) so you can watch the guardrails remove them.
    """
    if "### Story " in prompt:     # maintenance.py's clean-up check: call every suspect different
        return {"stories": [{"id": sid, "different": [int(k) for k in re.findall(r"^\s+\[(\d+)\]", block, re.M)]}
                            for sid, block in re.findall(r"^### Story (\S+)\n(.*?)(?=^### Story |\Z)", prompt, re.M | re.S)]}
    heads = {int(n): h for n, h in re.findall(r"^\[(\d+)\] [^|]*\| ([^|\n]+)", prompt, re.M)}
    out = []
    blocks = re.split(r"^### Group \d+", prompt, flags=re.M)[1:]
    # MOCK_MAX_GROUPS=10: pretend the answer is cut off when a call has more groups (tests the split-and-retry)
    limit = int(os.environ.get("MOCK_MAX_GROUPS") or 0)
    if limit and len(blocks) > limit:
        raise LLMError("the answer was cut off at the output limit (mock)", smaller=True)
    for b, block in enumerate(blocks):
        cont = re.match(r" · continues: (\S+)", block)
        refs = [int(n) for n in re.findall(r"^\[(\d+)\]", block, re.M)]
        if not refs:
            continue
        item = {"id": cont.group(1) if cont else "", "title": " ".join(heads[refs[0]].split()[:6]),
                "country": "", "articles": refs,
                "reports": [{"text": f"[{refs[0]}] reported: {heads[refs[0]].strip()}", "articles": [refs[0]]}]}
        if len(refs) > 1:     # a second outlet saying the same thing: should become "also reported by"
            item["reports"].append({"text": f"[{refs[1]}] reported: {heads[refs[0]].strip()}", "articles": [refs[1]]})
        if b == 0:
            item["reports"] += [
                {"text": f"[{refs[0]}] reported a likely escalation.", "articles": [refs[0]]},
                {"text": f"[{refs[0]}] reported 987654 people were affected.", "articles": [refs[0]]},
                {"text": "[99999] reported something.", "articles": [99999]},
            ]
        out.append(item)
    return {"narratives": out}


PROVIDERS = {"gemini": _gemini, "anthropic": _anthropic, "mock": _mock}


def ask_json(system: str, prompt: str, schema: dict) -> dict:
    """Send a prompt to whichever model config/ai.yaml chooses, and return its JSON answer."""
    cfg = load_ai()
    # AI_PROVIDER=mock python pipeline/narratives.py   overrides the config for one run
    provider = os.environ.get("AI_PROVIDER") or cfg.get("provider", "gemini")
    if provider not in PROVIDERS:
        raise LLMError(f"unknown provider '{provider}' in config/ai.yaml; use one of {list(PROVIDERS)}")
    return PROVIDERS[provider](system, prompt, schema, cfg.get("model", ""))
