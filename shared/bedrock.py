"""One way to call Bedrock, used by every project in this repository.

Extracted from P1 once it was clear the same three problems would recur in P2
and P3: retrying the errors that are worth retrying, coping with models that
reject a separate system prompt, and getting timing and token counts back in a
consistent shape.

Why Converse rather than InvokeModel: both reach the same models, but
InvokeModel takes a request body in each provider's own schema, so Anthropic,
Meta and Mistral all want differently shaped JSON. Converse takes one shape for
all of them and puts token counts in the same place every time. That is what
makes a mixed lineup fit in one loop.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

DEFAULT_PROFILE = "personal"
DEFAULT_REGION = "us-east-1"
MAX_ATTEMPTS = 5

# Worth retrying: the service is busy or briefly unwell, and the same request
# will likely succeed shortly. Everything else -- a bad model ID, a missing
# entitlement, a malformed request -- fails the same way on every attempt, so
# retrying it only wastes time and hides the real error.
RETRYABLE = {
    "ThrottlingException",
    "ModelTimeoutException",
    "ServiceUnavailableException",
    "InternalServerException",
}


@dataclass
class Response:
    """What one Converse call produced, or why it did not produce anything."""

    text: str = ""
    latency_ms: float = 0.0
    """Round trip measured on this machine. Includes client-side cost: on the
    first call through a fresh client that means credential resolution and the
    TLS handshake, which can be seconds and has nothing to do with the model."""

    server_latency_ms: float | None = None
    """What Bedrock reports it spent. The honest number for comparing models;
    `latency_ms` is the honest number for what a caller experiences."""

    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str | None = None
    attempts: int = 1
    system_folded: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def truncated(self) -> bool:
        """True when the reply hit the token ceiling, so the ceiling was measured."""
        return self.stop_reason == "max_tokens"

    def as_dict(self) -> dict:
        data = {
            "text": self.text,
            "latency_ms": round(self.latency_ms, 1),
            "server_latency_ms": self.server_latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "stop_reason": self.stop_reason,
            "attempts": self.attempts,
            "system_folded": self.system_folded,
        }
        if self.error:
            data = {"error": self.error, "attempts": self.attempts,
                    "system_folded": self.system_folded}
        return data


def client(profile: str = DEFAULT_PROFILE, region: str = DEFAULT_REGION):
    """A bedrock-runtime client with botocore's own retrying switched off.

    Retries are handled in this module instead, so that time spent waiting out
    a throttle never lands in the measured latency. botocore would retry inside
    the call and the delay would be invisible.
    """
    return boto3.Session(profile_name=profile, region_name=region).client(
        "bedrock-runtime",
        config=Config(retries={"max_attempts": 1}, read_timeout=120),
    )


def converse(
    bedrock,
    model_id: str,
    prompt: str,
    *,
    system: str = "",
    max_tokens: int = 512,
    temperature: float = 0.0,
    top_p: float | None = None,
    stop_sequences: list[str] | None = None,
) -> Response:
    """One call. Never raises for an API error; returns a Response carrying it.

    A benchmark that stops on the first unavailable model tells you nothing
    about the other seven, so failure is data here rather than an exception.
    """
    inference: dict = {"maxTokens": max_tokens, "temperature": temperature}
    if top_p is not None:
        inference["topP"] = top_p
    if stop_sequences:
        inference["stopSequences"] = stop_sequences

    kwargs: dict = {
        "modelId": model_id,
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": inference,
    }
    if system:
        kwargs["system"] = [{"text": system}]

    folded = False

    for attempt in range(1, MAX_ATTEMPTS + 1):
        started = time.perf_counter()
        try:
            raw = bedrock.converse(**kwargs)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]

            # Some models reject a separate system block. Fold it into the user
            # turn and record that it happened, because a model that needed the
            # workaround was not asked quite the same question as the others.
            if (code == "ValidationException" and "system" in kwargs
                    and not folded and "system" in str(exc).lower()):
                kwargs.pop("system")
                kwargs["messages"] = [
                    {"role": "user", "content": [{"text": f"{system}\n\n{prompt}"}]}
                ]
                folded = True
                continue

            if code in RETRYABLE and attempt < MAX_ATTEMPTS:
                time.sleep(min(2 ** attempt, 20) + random.random())
                continue

            message = exc.response["Error"].get("Message", "")
            return Response(error=f"{code}: {message[:200]}",
                            attempts=attempt, system_folded=folded)

        usage = raw["usage"]
        return Response(
            text="".join(b.get("text", "") for b in raw["output"]["message"]["content"]),
            latency_ms=(time.perf_counter() - started) * 1000,
            server_latency_ms=raw.get("metrics", {}).get("latencyMs"),
            input_tokens=usage["inputTokens"],
            output_tokens=usage["outputTokens"],
            stop_reason=raw.get("stopReason"),
            attempts=attempt,
            system_folded=folded,
        )

    return Response(error="exhausted retries", attempts=MAX_ATTEMPTS, system_folded=folded)
