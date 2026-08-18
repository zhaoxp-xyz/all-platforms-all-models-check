"""
OpenAI-compatible protocol adapter.

Handles:
  - URL: <base_url>/chat/completions
  - Payload: {model, messages}
  - Success: choices[0].message.content
  - Error:  {error: {code, message}}
"""

from __future__ import annotations

from typing import Any

from src.base_adapter import AbstractBaseAdapter


class OpenAICompatAdapter(AbstractBaseAdapter):
    """Adapter for OpenAI-compatible chat completions endpoints."""

    def __init__(self, name: str = "openai", **kwargs) -> None:
        # Accept and forward only kwargs we understand; rest goes to base.
        super().__init__(name=name, **kwargs)

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    def collect_models(self) -> list[str]:
        """
        Query the OpenAI-compatible /v1/models endpoint and return model IDs.
        """
        url = f"{self.base_url.rstrip('/')}/v1/models"
        try:
            resp = self._get(url)
            resp.raise_for_status()
            data = resp.json()
            return [m["id"] for m in data.get("data", [])]
        except Exception:
            return []

    def _build_url(self, model_id: str) -> str:
        """Return the chat completions URL."""
        base = self.base_url.rstrip("/")
        return f"{base}/v1/chat/completions"

    def _build_payload(self, model_id: str) -> dict[str, Any]:
        """
        Build the OpenAI chat completions payload.
        The test prompt is a simple system + user message.
        """
        return {
            "model": model_id,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Reply with exactly: OK"},
            ],
            "max_tokens": 16,
            "temperature": 0.0,
        }

    def _parse_ok(self, resp: dict) -> str | None:
        """Extract text from OpenAI-style response."""
        try:
            choices = resp.get("choices")
            if not choices:
                return None
            message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
            return message.get("content")
        except (AttributeError, IndexError, TypeError, KeyError):
            return None

    def _extract_error(self, resp: dict) -> tuple[str, str]:
        """Extract (code, message) from OpenAI error response."""
        err = resp.get("error", {})
        if isinstance(err, str):
            return ("unknown", err)
        code = err.get("code") or str(resp.get("status", ""))
        message = err.get("message", "unknown error")
        return (str(code), str(message))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def base_url(self) -> str:
        """Return base URL from config; required for OpenAICompatAdapter."""
        return getattr(self, "_base_url", "")

    @base_url.setter
    def base_url(self, value: str) -> None:
        self._base_url = value
