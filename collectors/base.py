"""Collector base class and registry.

Every source is implemented as a subclass of :class:`Collector`. A subclass:

* declares its ``type`` name (matches the ``type:`` field in config/sources.yaml)
* implements :meth:`fetch` to return a list of :class:`RawItem`

The registry lets ``run.py`` map a config entry to the right class without
imports being scattered around.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from models import RawItem


class CollectorError(Exception):
    """Raised when a collector fails in a way that should fail the run."""


class Collector(ABC):
    #: matches ``type:`` in config/sources.yaml
    type: str = ""

    def __init__(self, params: dict[str, Any]):
        self.params = params

    @abstractmethod
    def fetch(self) -> list[RawItem]:
        """Fetch raw items from the source. Must be idempotent across re-runs."""
        raise NotImplementedError


# ─── registry ───────────────────────────────────────────────────────────────
_REGISTRY: dict[str, type[Collector]] = {}


def register(cls: type[Collector]) -> type[Collector]:
    """Class decorator: register a Collector subclass by its ``type``."""
    if not cls.type:
        raise CollectorError(f"{cls.__name__} must set a non-empty `type`")
    if cls.type in _REGISTRY:
        raise CollectorError(f"Duplicate collector type {cls.type!r}")
    _REGISTRY[cls.type] = cls
    return cls


def get_collector(type_name: str, params: dict[str, Any]) -> Collector:
    """Instantiate the collector registered for ``type_name``."""
    try:
        cls = _REGISTRY[type_name]
    except KeyError:
        raise CollectorError(
            f"No collector registered for type {type_name!r}. "
            f"Known: {sorted(_REGISTRY)}"
        ) from None
    return cls(params)
