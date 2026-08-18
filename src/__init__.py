"""
src package — all-platforms-all-models-check.

Public API
----------
AbstractBaseAdapter   — base class for protocol adapters
OpenAICompatAdapter   — OpenAI-compatible chat completions
AnthropicAdapter      — Anthropic Messages API (/v1/messages)
GenericPlatformAdapter — config-driven platform adapter
Scheduler             — multi-platform concurrent executor
"""

from src.base_adapter import AbstractBaseAdapter
from src.protocol_openai import OpenAICompatAdapter
from src.protocol_anthropic import AnthropicAdapter
from src.generic_adapter import GenericPlatformAdapter, create_adapter, load_adapters
from src.scheduler import Scheduler
from src.collector import collect
from src.tester import test
from src.reporter import report as report_platform
from src.aggregator import aggregate
from src.diff import diff
from src.config_loader import load_platforms, validate_schema, AuthConfig

__all__ = [
    "AbstractBaseAdapter",
    "OpenAICompatAdapter",
    "AnthropicAdapter",
    "GenericPlatformAdapter",
    "create_adapter",
    "load_adapters",
    "Scheduler",
    "collect",
    "test",
    "report_platform",
    "aggregate",
    "diff",
    "load_platforms",
    "validate_schema",
    "AuthConfig",
]
