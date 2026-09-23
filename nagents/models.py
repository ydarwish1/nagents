"""Model clients. MockModel is deterministic and free; AnthropicModel and
OpenAIModel do real runs.

The `meta` dict passed to complete() is mock plumbing only (it carries the true
answer and seeds so the fake model can be reproducible). AnthropicModel ignores
it entirely — the real model never sees the answer.
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

DEFAULT_MODEL = "claude-opus-5"


@dataclass
class ModelReply:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = "end_turn"


def _unit(*parts) -> float:
    """Deterministic pseudo-uniform in [0, 1) from the given parts."""
    digest = hashlib.sha256(":".join(str(p) for p in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2.0 ** 64


class MockModel:
    """Fake model for tests and pipeline demos. No network, fully reproducible.

    Answers correctly with probability `accuracy`, decided by a hash of the
    call identity. In debate rounds it drifts toward the majority answer, so
    demo curves look like real help-then-saturate behavior. It makes no claims
    about real models — it exists to exercise and demo the pipeline.

    `correlation` (0..1) makes agents share mistakes, the way real models do:
    with that probability a call's right/wrong draw comes from one draw shared
    by every agent on the task, and a shared mistake is the same wrong number.
    Every agent's own accuracy stays `accuracy`; only the overlap changes.
    correlation=0 reproduces the independent mock exactly.
    """

    def __init__(self, accuracy: float = 0.65, debate_shift: float = 0.15, correlation: float = 0.0):
        if not 0.0 <= correlation <= 1.0:
            raise ValueError("correlation must be between 0 and 1")
        self.accuracy = accuracy
        self.debate_shift = debate_shift
        self.correlation = correlation

    def complete(self, system: str, prompt: str, meta: dict) -> ModelReply:
        acc = self.accuracy
        majority_correct = meta.get("majority_correct")
        if meta.get("round", 0) > 0 and majority_correct is not None:
            acc = acc + self.debate_shift if majority_correct else acc - self.debate_shift
            acc = min(0.99, max(0.01, acc))
        seed, task_id, agent, rnd = meta["seed"], meta["task_id"], meta["agent"], meta.get("round", 0)
        shared = self.correlation > 0 and _unit("mix", seed, task_id, agent, rnd) < self.correlation
        if shared:
            u = _unit("shared", seed, task_id, rnd)
            wrong_draw = _unit("shared-wrong", seed, task_id)
        else:
            u = _unit(seed, task_id, agent, rnd)
            wrong_draw = _unit("wrong", seed, task_id, agent)
        truth = int(meta["answer"])
        if u < acc:
            answer = truth
        else:
            answer = truth + 1 + int(wrong_draw * 7)
        text = f"I worked through the steps.\nAnswer: {answer}"
        return ModelReply(text, input_tokens=len(prompt) // 4, output_tokens=len(text) // 4)


class AnthropicModel:
    """Real Claude calls through the official SDK. Needs: pip install anthropic.

    Eval integrity: no refusal fallback to another model — a swapped model
    would contaminate the measurement. A refusal comes back with its
    stop_reason and gets scored as incorrect. No sampling overrides either
    (current models reject temperature); agent diversity comes from sampling.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 16000,
        effort: Optional[str] = None,
    ):
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "The anthropic package is not installed. "
                "Run: pip install anthropic  (or run with --mock)"
            ) from exc
        # Long grids hit transient 429/5xx; lean on the SDK's backoff harder
        # than the default 2 retries before a run aborts (resume covers aborts).
        self._client = anthropic.Anthropic(max_retries=5)
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort

    def complete(self, system: str, prompt: str, meta: dict) -> ModelReply:
        kwargs = {}
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return ModelReply(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            stop_reason=response.stop_reason or "end_turn",
        )


class OpenAIModel:
    """Real OpenAI calls through the Responses API, with no SDK dependency.

    Needs OPENAI_API_KEY and network access to api.openai.com. The same
    integrity rules as AnthropicModel apply: no fallback model, and a refusal
    or cut-off reply is recorded as such and scored as wrong.
    """

    URL = "https://api.openai.com/v1/responses"

    def __init__(self, model: str, max_tokens: int = 16000, effort: Optional[str] = None, post=None):
        self.api_key = os.environ.get("OPENAI_API_KEY")
        if not self.api_key and post is None:
            raise RuntimeError("OPENAI_API_KEY is not set (or run with --mock)")
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort
        self._post = post or self._http_post

    def _http_post(self, body: dict) -> dict:
        request = urllib.request.Request(
            self.URL,
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        for attempt in range(6):
            try:
                with urllib.request.urlopen(request, timeout=600) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                # Same policy as the Anthropic client: back off on rate limits
                # and server errors, fail fast on anything else.
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 5:
                    raise
            time.sleep(2 ** attempt)
        raise RuntimeError("unreachable")

    def complete(self, system: str, prompt: str, meta: dict) -> ModelReply:
        body = {
            "model": self.model,
            "instructions": system,
            "input": prompt,
            "max_output_tokens": self.max_tokens,
        }
        if self.effort:
            body["reasoning"] = {"effort": self.effort}
        data = self._post(body)
        texts, refused = [], False
        for item in data.get("output", []):
            if item.get("type") != "message":
                continue
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    texts.append(part.get("text", ""))
                elif part.get("type") == "refusal":
                    refused = True
        if refused:
            stop = "refusal"
        elif data.get("status") == "incomplete":
            stop = (data.get("incomplete_details") or {}).get("reason") or "incomplete"
        else:
            stop = "end_turn"
        usage = data.get("usage") or {}
        return ModelReply(
            text="".join(texts),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            stop_reason=stop,
        )
