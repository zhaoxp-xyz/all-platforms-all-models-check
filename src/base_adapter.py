"""
Abstract base adapter — thread-safe HTTP client, proxy injection,
configurable timeout/retry, response parse dispatch, result writing,
protocol fallback in test_model(), model filtering.
"""

from __future__ import annotations

import json
import re
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import requests

from src.config_loader import AuthConfig


class AbstractBaseAdapter(ABC):
    """
    Abstract base for all protocol adapters.

    Public surface
    --------------
    name          – platform name (read-only)
    concurrency   – max parallel workers for this platform
    protocols     – ordered list of protocol names (e.g. ["openai", "anthropic"])
    auth          – parsed AuthConfig

    Abstract methods (implement in subclass)
    ----------------------------------------
    collect_models()          -> list[str]
    _build_url(model_id: str) -> str
    _build_payload(model_id: str) -> dict
    _parse_ok(resp: dict)     -> str | None
    _extract_error(resp: dict) -> tuple[str, str]

    test_model(model_id)      -> dict  (with protocol fallback)
    should_skip(model_id)     -> bool
    """

    def __init__(
        self,
        name: str,
        concurrency: int = 8,
        proxy: str | None = None,
        timeout: int = 30,
        retry: int = 1,
        protocols: list[str] | None = None,
        model_filters: list[str] | None = None,
        fallback_triggers: list[str] | None = None,
        auth: AuthConfig | None = None,
    ) -> None:
        self.name = name
        self._concurrency = concurrency
        self.proxy = proxy
        self.timeout = timeout
        self.retry = retry
        self.protocols = protocols or []
        self.model_filters = [re.compile(p) for p in (model_filters or [])]
        # Combine HTTP status codes and text patterns for fallback decisions.
        # Config format: "404" (int code) or "model_not_found" (substring match).
        self._fallback_codes: set[int] = set()
        self._fallback_patterns: list[re.Pattern] = []
        for trigger in (fallback_triggers or []):
            try:
                self._fallback_codes.add(int(trigger))
            except ValueError:
                self._fallback_patterns.append(re.compile(trigger, re.IGNORECASE))
        self.auth = auth or AuthConfig()
        self._http_lock = threading.Lock()
        self._session: requests.Session | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def concurrency(self) -> int:
        return self._concurrency

    # ------------------------------------------------------------------
    # Session management (thread-safe, one session per instance)
    # ------------------------------------------------------------------

    def _get_session(self) -> requests.Session:
        with self._http_lock:
            if self._session is None or self._session.closed:
                self._session = requests.Session()
                if self.proxy:
                    proxies = {
                        "http": self.proxy,
                        "https": self.proxy,
                    }
                    self._session.proxies.update(proxies)
            return self._session

    # ------------------------------------------------------------------
    # Core HTTP: inject proxy, apply timeout, retry
    # ------------------------------------------------------------------

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Send a request with proxy injection, timeout, and retry loop."""
        session = self._get_session()
        kwargs.setdefault("timeout", self.timeout)
        # Inject auth header (Bearer) when an API key is configured.
        headers = dict(kwargs.get("headers") or {})
        if self.auth and getattr(self.auth, "api_key", None):
            headers.setdefault("Authorization", f"Bearer {self.auth.api_key}")
        if headers:
            kwargs["headers"] = headers
        for attempt in range(1 + self.retry):
            try:
                with self._http_lock:
                    resp = session.request(method, url, **kwargs)
                return resp
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt == self.retry:
                    raise
        # Unreachable — should never get here
        raise RuntimeError("retry loop exited unexpectedly")  # pragma: no cover

    def _post(self, url: str, **kwargs) -> requests.Response:
        return self._request("POST", url, **kwargs)

    def _get(self, url: str, **kwargs) -> requests.Response:
        return self._request("GET", url, **kwargs)

    # ------------------------------------------------------------------
    # Response dispatch
    # ------------------------------------------------------------------

    def _parse_response(self, resp: requests.Response) -> dict:
        """Parse response body as JSON; fall back to raw text on error."""
        try:
            return resp.json()
        except (ValueError, requests.exceptions.JSONDecodeError):
            return {"_raw": resp.text, "_status": resp.status_code}

    def _should_fallback(self, resp_dict: dict, http_code: int) -> bool:
        """Decide whether an error response should trigger protocol fallback."""
        if http_code in self._fallback_codes:
            return True
        # Check text patterns against the whole response blob
        blob = json.dumps(resp_dict, ensure_ascii=False)
        for pat in self._fallback_patterns:
            if pat.search(blob):
                return True
        return False

    # ------------------------------------------------------------------
    # test_model — with per-model protocol fallback
    # ------------------------------------------------------------------

    def test_model(self, model_id: str) -> dict:
        """
        Test a single model, trying protocols in self.protocols order.

        Returns:
            {
                "model": str,
                "status": "ok" | "fail",
                "http_code": int,
                "response": dict | None,
                "elapsed": float,
                "protocol": str,        # which protocol succeeded
                "content": str | None,  # parsed content from _parse_ok
            }
        """
        import time

        result: dict[str, Any] = {
            "model": model_id,
            "status": "fail",
            "http_code": 0,
            "response": None,
            "elapsed": 0.0,
            "protocol": None,
            "content": None,
        }

        if self.should_skip(model_id):
            result["status"] = "skip"
            return result

        t0 = time.monotonic()
        last_error: tuple[str, str] | None = None
        last_http_code = 0
        last_resp_dict: dict | None = None
        last_protocol: str | None = None

        for proto in self.protocols:
            adapter = self._make_protocol_adapter(proto)
            if adapter is None:
                continue

            url = adapter._build_url(model_id)
            payload = adapter._build_payload(model_id)
            headers = adapter._extra_headers()
            headers.setdefault("Content-Type", "application/json")

            try:
                resp = self._post(url, json=payload, headers=headers)
                last_http_code = resp.status_code
                resp_dict = self._parse_response(resp)
                last_resp_dict = resp_dict
                last_protocol = proto

                if resp.status_code == 200:
                    ok_content = adapter._parse_ok(resp_dict)
                    result.update(
                        status="ok",
                        http_code=resp.status_code,
                        response=resp_dict,
                        content=ok_content,
                        protocol=proto,
                    )
                    result["elapsed"] = time.monotonic() - t0
                    return result

                # Non-200: extract error and decide whether to fallback
                last_error = adapter._extract_error(resp_dict)
                if not self._should_fallback(resp_dict, resp.status_code):
                    # Hard error — stop trying other protocols
                    break

            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = ("network_error", str(exc))
                # Network/connection errors are protocol-agnostic; still fallback
                continue

        # All protocols exhausted or hard error — report failure
        result["http_code"] = last_http_code
        result["response"] = last_resp_dict
        result["protocol"] = last_protocol
        result["elapsed"] = time.monotonic() - t0
        if last_error:
            result["error"] = {"code": last_error[0], "message": last_error[1]}
        return result

    def _make_protocol_adapter(self, protocol: str):
        """
        Instantiate the protocol adapter for the given name.
        Subclasses may override to inject config-specific parameters.
        Returns None if the protocol is not supported.
        """
        if protocol == "openai":
            from src.protocol_openai import OpenAICompatAdapter

            return OpenAICompatAdapter(name=protocol)
        elif protocol == "anthropic":
            from src.protocol_anthropic import AnthropicAdapter

            return AnthropicAdapter(name=protocol)
        return None

    # ------------------------------------------------------------------
    # Model filtering
    # ------------------------------------------------------------------

    def should_skip(self, model_id: str) -> bool:
        """Return True if the model should be skipped per model_filters."""
        for pat in self.model_filters:
            if pat.search(model_id):
                return True
        return False

    # ------------------------------------------------------------------
    # Abstract methods (must be implemented by protocol subclasses)
    # ------------------------------------------------------------------

    @abstractmethod
    def collect_models(self) -> list[str]:
        """Return list of available model IDs for this platform."""
        ...

    @abstractmethod
    def _build_url(self, model_id: str) -> str:
        """Build the full request URL for the given model."""
        ...

    @abstractmethod
    def _build_payload(self, model_id: str) -> dict:
        """Build the request payload for the given model."""
        ...

    @abstractmethod
    def _parse_ok(self, resp: dict) -> str | None:
        """Extract the response text from a successful (200) response."""
        ...

    @abstractmethod
    def _extract_error(self, resp: dict) -> tuple[str, str]:
        """Extract (error_code, error_message) from an error response."""
        ...

    # ------------------------------------------------------------------
    # Hook for extra headers (e.g. Anthropic requires anthropic-version)
    # ------------------------------------------------------------------

    def _extra_headers(self) -> dict[str, str]:
        """Return additional headers required by this protocol. Override in subclass."""
        return {}

    # ------------------------------------------------------------------
    # Result persistence
    # ------------------------------------------------------------------

    def save_result(self, model_id: str, result: dict) -> None:
        """Append a single test result to results/<platform>.json."""
        results_path = Path("results") / f"{self.name}.json"
        results_path.parent.mkdir(parents=True, exist_ok=True)

        if results_path.exists():
            try:
                data = json.loads(results_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {"all_results": [], "ok": [], "fail": []}
        else:
            data = {"all_results": [], "ok": [], "fail": []}

        data["all_results"].append(result)

        if result["status"] == "ok":
            data["ok"].append(result["model"])
        elif result["status"] == "fail":
            data["fail"].append(result["model"])

        results_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
