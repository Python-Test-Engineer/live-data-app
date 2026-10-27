"""The harness around the model: tools, evidence ledger, bounded loop, LLM.

The model never executes Python. It can only ask the harness to call a named
tool. The harness validates the name, runs the function, stamps the result with
an evidence id, logs it, and hands it back.

Read this file after the talk: it is the part that makes the agent auditable.
"""

from __future__ import annotations

import inspect
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMError(RuntimeError):
    """Raised when the optional language model cannot be reached."""


class Ledger:
    """Every tool result gets an id, so prose can be traced back to a number."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}

    def record(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(payload)
        eid = f"ev_{len(self.items) + 1:03d}"
        payload["evidence_id"] = eid
        self.items[eid] = payload
        return payload

    def by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        return [self.items[i] for i in ids if i in self.items]

    def numbers(self, ids: list[str] | None = None) -> list[float]:
        """Flatten every number in the selected evidence (or all of it)."""
        payloads = self.by_ids(ids) if ids is not None else list(self.items.values())
        found: list[float] = []

        def walk(value: Any) -> None:
            if isinstance(value, bool):
                return
            if isinstance(value, (int, float)):
                found.append(float(value))
            elif isinstance(value, dict):
                for v in value.values():
                    walk(v)
            elif isinstance(value, list):
                for v in value:
                    walk(v)

        walk(payloads)
        return found

    def text(self, ids: list[str] | None = None) -> str:
        payloads = self.by_ids(ids) if ids is not None else list(self.items.values())
        return json.dumps(payloads, default=str, ensure_ascii=False)

    def summaries(self) -> list[dict[str, str]]:
        return [
            {
                "evidence_id": eid,
                "tool": str(p.get("tool", "")),
                "summary": str(p.get("summary", "")),
            }
            for eid, p in self.items.items()
        ]


@dataclass
class Harness:
    """A tiny, bounded tool-calling harness."""

    tools: dict[str, Callable[..., dict[str, Any]]]
    specs: list[dict[str, Any]]
    max_steps: int = 8
    verbose: bool = True
    ledger: Ledger = field(default_factory=Ledger)
    transcript: list[dict[str, Any]] = field(default_factory=list)

    def call(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        if name not in self.tools:
            raise KeyError(f"unknown tool: {name!r}; available: {sorted(self.tools)}")
        fn = self.tools[name]
        kwargs = dict(args or {})
        # Two tools need the ledger to resolve evidence ids. Keep that out of
        # the public JSON schema so the model cannot forge it.
        if "ledger" in inspect.signature(fn).parameters:
            kwargs["ledger"] = self.ledger

        started = time.perf_counter()
        payload = fn(**kwargs)
        if not isinstance(payload, dict):
            payload = {"data": payload}
        payload.setdefault("tool", name)
        payload.setdefault("caveats", [])
        payload = self.ledger.record(payload)
        payload["_ms"] = int((time.perf_counter() - started) * 1000)
        self.transcript.append(payload)

        if self.verbose:
            print(f"\n[tool] {name}({json.dumps(args or {}, default=str)})")
            print(f"       -> {payload['evidence_id']} in {payload['_ms']} ms")
            summary = payload.get("summary")
            if summary:
                print(f"       {summary}")
        return payload

    def reset(self) -> None:
        self.ledger = Ledger()
        self.transcript.clear()


# ---------------------------------------------------------------------------
# optional model layer
# ---------------------------------------------------------------------------


def _env_values() -> dict[str, str]:
    """Read the repo-root .env without adding a dotenv dependency."""
    root = Path(__file__).resolve().parents[1]
    values: dict[str, str] = {}
    for path in (root / ".env", Path.cwd() / ".env"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return values


def _normalise_model(name: str) -> str:
    if "/" in name:
        return name
    prefixes = (
        ("gpt", "openai/"),
        ("o1", "openai/"),
        ("o3", "openai/"),
        ("o4", "openai/"),
        ("claude", "anthropic/"),
        ("gemini", "google/"),
        ("deepseek", "deepseek/"),
        ("llama", "meta-llama/"),
        ("mistral", "mistralai/"),
        ("qwen", "qwen/"),
    )
    for prefix, vendor in prefixes:
        if name.startswith(prefix):
            return vendor + name
    return "openrouter/auto"


def have_api_key() -> bool:
    env = _env_values()
    return bool(env.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_KEY"))


class LLMClient:
    """Minimal OpenRouter client. Tool calling is the OpenAI-compatible format."""

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        env = _env_values()
        self.api_key = api_key or env.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_KEY")
        if not self.api_key:
            raise LLMError("No OPENROUTER_API_KEY / OPENROUTER_KEY found in .env or environment.")
        raw_model = model or env.get("OPENROUTER_MODEL") or env.get("MODEL") or "openrouter/auto"
        self.model = _normalise_model(raw_model)

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        response = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://craigwestai.com/",
                "X-Title": "Brighton data intelligence agent talk",
            },
            json=body,
            timeout=120,
        )
        if response.status_code != 200:
            raise LLMError(f"OpenRouter {response.status_code}: {response.text[:500]}")
        return response.json()


def run_llm(
    harness: Harness,
    system: str,
    question: str,
    client: LLMClient,
    max_steps: int | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """The agent loop: model -> tool call -> harness -> result -> model."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]
    for _ in range(max_steps or harness.max_steps):
        data = client.chat(messages, harness.specs)
        message = data["choices"][0]["message"]
        calls = message.get("tool_calls") or []
        if not calls:
            return message.get("content") or "", messages

        messages.append(
            {
                "role": "assistant",
                "content": message.get("content"),
                "tool_calls": calls,
            }
        )
        for call in calls:
            name = call["function"]["name"]
            raw = call["function"].get("arguments") or "{}"
            try:
                args = json.loads(raw)
            except json.JSONDecodeError:
                args = {}
            result = harness.call(name, args)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "name": name,
                    "content": json.dumps(result, default=str),
                }
            )
    return "Stopped: step limit reached before the model produced an answer.", messages
