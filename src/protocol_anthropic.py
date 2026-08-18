"""
Anthropic protocol adapter.

Handles:
  - URL: <base_url>/v1/messages
  - Headers: x-api-key, anthropic-version, content-type
  - Payload: {model, max_tokens, messages}
  - Success: content[0].text
  - Error:  {error: {type, message}}  or plain string
"""

from __future__ import annotations

from typing import Any

from src.base_adapter import AbstractBaseAdapter


class AnthropicAdapter(AbstractBaseAdapter):
    """Adapter for Anthropic Messages API (/v1/messages)."""

    ANTHROPIC_VERSION = "2023-06-01"

    def __init__(self, name: str = "anthropic", **kwargs) -> None:
        super().__init__(name=name, **kwargs)

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    def collect_models(self) -> list[str]:
        """
        Query Anthropic's /v1/models endpoint and return model IDs.
        """
        url = f"{self.base_url.rstrip('/')}/v1/models"
        headers = self._auth_headers()
        headers["anthropic-version"] = self.ANTHROPIC_VERSION
        try:
            resp = self._get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return [m["id"] for m in data.get("data", [])]
        except Exception:
            return []

    def _build_url(self, model_id: str) -> str:
        """Return the Anthropic messages URL."""
        base = self.base_url.rstrip("/")
        return f"{base}/v1/messages"

    def _build_payload(self, model_id: str) -> dict[str, Any]:
        """
        Build the Anthropic Messages API payload.
        Uses the messages array format.
        """
        return {
            "model": model_id,
            "max_tokens": 16,
            "messages": [
                {"role": "user", "content": "Reply with exactly: OK"},
            ],
        }

    def _parse_ok(self, resp: dict) -> str | None:
        """Extract text from Anthropic response content array."""
        try:
            content = resp.get("content", [])
            if not content:
                return None
            # First text block
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    return block.get("text")
            # Fallback: first block's text if present
            first = content[0]
            if isinstance(first, dict):
                return first.get("text")
            return None
        except (AttributeError, IndexError, TypeError):
            return None

    def _extract_error(self, resp: dict) -> tuple[str, str]:
        """
        Extract (error_code, error_message) from Anthropic error response.
        Handles both dict {error: {type, message}} and string responses.
        """
        err = resp.get("error")
        if err is None:
            # Maybe the whole response is the error
            if isinstance(resp, str):
                return ("unknown", resp)
            return ("unknown", str(resp))
        if isinstance(err, str):
            return ("unknown", err)
        err_type = err.get("type") or err.get("code", "unknown")
        err_msg = err.get("message", "unknown error")
        return (str(err_type), str(err_msg))

    # ------------------------------------------------------------------
    # Header helpers
    # ------------------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        """Build auth headers for Anthropic API."""
        headers = {
            "x-api-key": self.auth.api_key or "",
            "anthropic-version": self.ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        return headers

    def _extra_headers(self) -> dict[str, str]:
        """Return Anthropic-specific headers."""
        return self._auth_headers()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def base_url(self) -> str:
        return getattr(self, "_base_url", "")

    @base_url.setter
    def base_url(self, value: str) -> None:
        self._base_url = value
