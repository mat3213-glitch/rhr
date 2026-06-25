"""Tests for collectors/base.py — register, get_collector, Collector ABC."""
import pytest

from collectors.base import Collector, CollectorError, _REGISTRY, get_collector, register
from models import RawItem


@register
class DummyCollector(Collector):
    type = "test_dummy"

    def fetch(self) -> list[RawItem]:
        return []


class TestRegister:
    def test_registers_collector(self):
        # DummyCollector is already registered at import time via @register
        assert "test_dummy" in _REGISTRY
        assert _REGISTRY["test_dummy"] is DummyCollector

    def test_duplicate_type_raises(self):
        with pytest.raises(CollectorError, match="Duplicate"):
            register(type("Dup", (Collector,), {"type": "test_dummy", "fetch": lambda s: []}))

    def test_empty_type_raises(self):
        with pytest.raises(CollectorError, match="non-empty"):
            register(type("Empty", (Collector,), {"type": "", "fetch": lambda s: []}))


class TestGetCollector:
    def test_returns_instance(self):
        c = get_collector("test_dummy", {"key": "value"})
        assert isinstance(c, DummyCollector)
        assert c.params == {"key": "value"}

    def test_unknown_type_raises(self):
        with pytest.raises(CollectorError, match="No collector"):
            get_collector("nonexistent", {})

    def test_includes_known_types_in_error(self):
        with pytest.raises(CollectorError, match="test_dummy"):
            get_collector("nonexistent", {})


class TestCollectorABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            Collector({})
