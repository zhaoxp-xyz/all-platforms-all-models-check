"""
GenericPlatformAdapter — config-driven platform adapter.

Reads a platform config dict (from platforms.yaml) and at runtime
instantiates the appropriate protocol adapter(s), wiring together
base_url, api_key, proxy, concurrency, model_filters, protocols,
and fallback_triggers.

No platform names are hardcoded here beyond the two protocol classes.
Adding a new platform only requires adding an entry to config/platforms.yaml.
"""

from __future__ import annotations

import re
from typing import Any

from src.base_adapter import AbstractBaseAdapter
from src.config_loader import AuthConfig, load_platforms


def _resolve_auth(auth_cfg: dict) -> AuthConfig:
    """Build an AuthConfig from a raw auth dict in the platform config."""
    return AuthConfig(
        key_index=auth_cfg.get("key_index", 0),
        key_split=auth_cfg.get("key_split"),
        api_key=auth_cfg.get("api_key"),
    )


def _resolve_base_url(raw: str, auth: AuthConfig) -> str:
    """
    Resolve base_url template by substituting {api_key} if present.
    """
    if "{api_key}" in raw:
        return raw.replace("{api_key}", auth.api_key or "")
    return raw


class GenericPlatformAdapter(AbstractBaseAdapter):
    """
    Config-driven adapter that assembles protocol adapters at runtime.

    Parameters (from config dict)
    -----------------------------
    name            : str               — platform name
    enabled         : bool              — whether to run this platform
    protocols       : list[str]         — ordered protocol list, e.g. ["openai", "anthropic"]
    base_url        : str               — API base URL (may contain {api_key} placeholder)
    auth            : dict              — key extraction rules
    proxy           : str | None        — proxy URL or None
    concurrency     : int               — parallel workers
    model_filters   : list[str]         — regex patterns for models to skip
    fallback_triggers: list[str]       — custom fallback triggers (HTTP codes or text patterns)
    """

    def __init__(self, config: dict) -> None:
        name = config["name"]
        concurrency = config.get("concurrency", 8)
        proxy = config.get("proxy")
        timeout = config.get("timeout", 30)
        retry = config.get("retry", 1)
        protocols = config.get("protocols", ["openai"])
        model_filters = config.get("model_filters", [])
        fallback_triggers = config.get("fallback_triggers", [])
        auth_raw = config.get("auth", {})
        auth = _resolve_auth(auth_raw)
        base_url_raw = config.get("base_url", "")
        base_url = _resolve_base_url(base_url_raw, auth)

        super().__init__(
            name=name,
            concurrency=concurrency,
            proxy=proxy,
            timeout=timeout,
            retry=retry,
            protocols=protocols,
            model_filters=model_filters,
            fallback_triggers=fallback_triggers,
            auth=auth,
        )

        # Wire base_url into each protocol adapter so they can build URLs.
        self._protocol_adapters: dict[str, AbstractBaseAdapter] = {}
        for proto in self.protocols:
            adapter = self._make_protocol_adapter(proto)
            if adapter is not None:
                adapter.base_url = base_url
                adapter.auth = auth
                self._protocol_adapters[proto] = adapter

    # ------------------------------------------------------------------
    # Protocol factory (overrides base to use pre-wired adapters)
    # ------------------------------------------------------------------

    def _make_protocol_adapter(self, protocol: str) -> AbstractBaseAdapter | None:
        """Return the pre-wired protocol adapter, or None if unknown."""
        if protocol in self._protocol_adapters:
            return self._protocol_adapters[protocol]
        # Fallback: create on the fly (used by base test_model before wiring)
        if protocol == "openai":
            from src.protocol_openai import OpenAICompatAdapter

            a = OpenAICompatAdapter(name=protocol)
            a.base_url = self.base_url
            a.auth = self.auth
            self._protocol_adapters[protocol] = a
            return a
        elif protocol == "anthropic":
            from src.protocol_anthropic import AnthropicAdapter

            a = AnthropicAdapter(name=protocol)
            a.base_url = self.base_url
            a.auth = self.auth
            self._protocol_adapters[protocol] = a
            return a
        return None

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    @property
    def base_url(self) -> str:
        """Return the resolved base URL (first protocol's base_url)."""
        first = next(iter(self._protocol_adapters.values()), None)
        if first is not None:
            return first.base_url
        return ""

    # ------------------------------------------------------------------
    # Abstract method implementations — delegate to first protocol adapter
    # ------------------------------------------------------------------

    def collect_models(self) -> list[str]:
        """
        Collect models using the first configured protocol adapter.
        Falls back to subsequent protocols if the first returns empty.
        """
        for proto in self.protocols:
            adapter = self._protocol_adapters.get(proto)
            if adapter is None:
                continue
            models = adapter.collect_models()
            if models:
                # Save collected models for this platform
                from pathlib import Path
                import json

                path = Path("results") / f"{self.name}_models.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps({"platform": self.name, "models": models}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                return models
        return []

    def _build_url(self, model_id: str) -> str:
        """Delegate to first protocol adapter."""
        first = next(iter(self._protocol_adapters.values()), None)
        if first is None:
            raise RuntimeError(f"No protocol adapter configured for platform {self.name}")
        return first._build_url(model_id)

    def _build_payload(self, model_id: str) -> dict:
        """Delegate to first protocol adapter."""
        first = next(iter(self._protocol_adapters.values()), None)
        if first is None:
            raise RuntimeError(f"No protocol adapter configured for platform {self.name}")
        return first._build_payload(model_id)

    def _parse_ok(self, resp: dict) -> str | None:
        """Delegate to first protocol adapter."""
        first = next(iter(self._protocol_adapters.values()), None)
        if first is None:
            return None
        return first._parse_ok(resp)

    def _extract_error(self, resp: dict) -> tuple[str, str]:
        """Delegate to first protocol adapter."""
        first = next(iter(self._protocol_adapters.values()), None)
        if first is None:
            return ("unknown", "no adapter")
        return first._extract_error(resp)

    def _extra_headers(self) -> dict[str, str]:
        """Return headers from first protocol adapter."""
        first = next(iter(self._protocol_adapters.values()), None)
        if first is None:
            return {}
        return first._extra_headers()


# ------------------------------------------------------------------
# Factory: build a GenericPlatformAdapter from a config dict
# ------------------------------------------------------------------

def create_adapter(config: dict) -> GenericPlatformAdapter:
    """
    Factory function. Takes a single platform config dict (from
    platforms.yaml, after enabled filter) and returns a
    GenericPlatformAdapter ready for use.
    """
    return GenericPlatformAdapter(config)


# ------------------------------------------------------------------
# Convenience: load all enabled platforms and return adapters
# ------------------------------------------------------------------

def load_adapters(config_path: str = "config/platforms.yaml") -> list[GenericPlatformAdapter]:
    """
    Load platforms.yaml, validate schema, filter enabled platforms,
    and return a list of GenericPlatformAdapter instances.
    """
    platforms = load_platforms(config_path)
    adapters: list[GenericPlatformAdapter] = []
    for cfg in platforms:
        adapters.append(GenericPlatformAdapter(cfg))
    return adapters
