"""
Config loader — read platforms.yaml, validate schema, filter enabled.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import yaml


@dataclasses.dataclass
class AuthConfig:
    """Parsed auth configuration for a single platform."""

    key_index: int = 0
    key_split: str | None = None  # e.g. "tab_split_first"
    api_key: str | None = None

    def resolve(self, raw_keys: str | list[str] | None) -> str:
        """
        Extract the actual API key string from raw input using configured rules.

        raw_keys may be:
          - a single string (the key directly)
          - a list of strings (one per key rotation)
          - None (return api_key directly if set)
        """
        if self.api_key:
            return self.api_key
        if raw_keys is None:
            return ""
        if isinstance(raw_keys, list):
            idx = min(self.key_index, len(raw_keys) - 1) if raw_keys else 0
            raw = raw_keys[idx] if raw_keys else ""
        else:
            raw = raw_keys
        if not raw:
            return ""
        if self.key_split == "tab_split_first":
            return raw.split("\t")[0].strip()
        return raw.strip()


# ------------------------------------------------------------------
# Schema validation
# ------------------------------------------------------------------

REQUIRED_FIELDS = {
    "name": str,
    "enabled": bool,
    "protocols": list,
    "base_url": str,
    "auth": dict,
    "proxy": (str, type(None)),
    "concurrency": int,
}

OPTIONAL_FIELDS = {
    "model_filters": list,
    "fallback_triggers": list,
    "timeout": int,
    "retry": int,
}


def validate_schema(cfg: dict) -> None:
    """
    Validate a single platform config dict.
    Raises ValueError with platform name if any required field is missing
    or has the wrong type.
    """
    name = cfg.get("name", "<unknown>")
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in cfg:
            raise ValueError(f"Platform '{name}': missing required field '{field}'")
        value = cfg[field]
        if not isinstance(value, expected_type):
            # bool is subclass of int in Python — special-case concurrency
            if field == "concurrency" and isinstance(value, bool):
                raise ValueError(
                    f"Platform '{name}': field 'concurrency' must be int, got {type(value).__name__}"
                )
            raise ValueError(
                f"Platform '{name}': field '{field}' must be {expected_type.__name__}, "
                f"got {type(value).__name__}"
            )


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def load_platforms(path: str = "config/platforms.yaml") -> list[dict]:
    """
    Load platforms.yaml, validate schema for each entry, and return only
    the enabled platform configs.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")

    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"platforms.yaml must contain a YAML list at top level")

    result: list[dict] = []
    for cfg in data:
        if not isinstance(cfg, dict):
            continue
        validate_schema(cfg)
        if cfg.get("enabled", False):
            result.append(cfg)
    return result
