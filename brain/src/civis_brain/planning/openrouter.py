"""Single OpenRouter JSON planning call. No tools, retries or paid-model fallback."""

import asyncio
import json

import httpx
from jsonschema import ValidationError as SchemaError
from jsonschema import validate
from pydantic import ValidationError

from civis_brain.contracts import Plan, PlanningContext
from civis_brain.errors import BrainError
from civis_brain.planning.gemini import SYSTEM_INSTRUCTION, response_schema

MODEL = "google/gemma-4-31b-it:free"
ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterPlanProvider:
    def __init__(
        self, api_key: str, model: str = MODEL, timeout_seconds: float = 30, *, client=None
    ):
        if model != MODEL:
            raise BrainError("AI_MODEL_UNVERIFIED", "Only the selected free Gemma model is enabled")
        self.api_key, self.model, self.timeout_seconds = api_key, model, timeout_seconds
        self._client = client
        self._owned = client is None

    async def generate(self, context: PlanningContext) -> Plan:
        if not self.api_key:
            raise BrainError("AI_KEY_MISSING", "Set OPENROUTER_API_KEY locally in brain/.env")
        schema = response_schema(context)
        data = {
            "run_id": context.batch.run_id,
            "tick": context.batch.tick,
            "incidents": [row.model_dump(mode="json") for row in context.incidents],
            "nodes": [row.model_dump(mode="json") for row in context.nodes],
            "allowed_actions": [row.model_dump(mode="json") for row in context.actions],
            "selected_evidence": [row.model_dump(mode="json") for row in context.evidence_readings],
            "required_json_schema": schema,
        }
        contents = json.dumps(data, ensure_ascii=False, allow_nan=False)
        if len(contents) > 32000:
            raise BrainError("AI_CONTEXT_TOO_LARGE", "Selected evidence exceeds the mock AI budget")
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False)
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": contents},
            ],
            "response_format": {"type": "json_object"},
            "provider": {
                "allow_fallbacks": False,
                "require_parameters": True,
                "max_price": {"prompt": 0, "completion": 0, "request": 0},
            },
            "reasoning": {"enabled": False},
            "max_tokens": 1024,
            "temperature": 0,
            "stream": False,
        }
        try:
            response = await asyncio.wait_for(
                self._client.post(
                    ENDPOINT,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "X-OpenRouter-Title": "CIVIS",
                    },
                    json=body,
                ),
                timeout=self.timeout_seconds,
            )
            if response.status_code != 200:
                code = {
                    401: "AI_AUTH_FAILED",
                    403: "AI_ACCESS_DENIED",
                    402: "AI_PAYMENT_REQUIRED",
                    429: "AI_QUOTA_EXCEEDED",
                    400: "AI_REQUEST_REJECTED",
                }.get(response.status_code, "AI_UNAVAILABLE")
                raise BrainError(code, "OpenRouter rejected the request; no fallback was used")
            if len(response.content) > 100000:
                raise BrainError("AI_OUTPUT_INVALID", "OpenRouter response exceeds the mock limit")
            result = response.json()
            if result.get("error"):
                raise BrainError("AI_UPSTREAM_ERROR", "OpenRouter returned an upstream failure")
            choice = result["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise BrainError("AI_OUTPUT_TRUNCATED", "AI response did not finish normally")
            content = choice["message"].get("content")
            if not isinstance(content, str) or not content.strip():
                raise BrainError("AI_OUTPUT_INVALID", "AI returned no JSON Plan")
            parsed = json.loads(content)
            # Gemma's free endpoint does not enforce JSON schema. Never trust JSON mode alone.
            validate(parsed, schema)
            return Plan.model_validate(parsed)
        except BrainError:
            raise
        except (TimeoutError, httpx.TimeoutException):
            raise BrainError(
                "AI_TIMEOUT", "OpenRouter call exceeded the configured timeout"
            ) from None
        except (ValueError, TypeError, KeyError, IndexError, SchemaError, ValidationError):
            raise BrainError(
                "AI_OUTPUT_INVALID", "AI output does not match the restricted Plan"
            ) from None
        except Exception:
            raise BrainError(
                "AI_UNAVAILABLE", "OpenRouter call failed; no fallback was used"
            ) from None

    async def aclose(self):
        if self._owned and self._client is not None:
            await self._client.aclose()
