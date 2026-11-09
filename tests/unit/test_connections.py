"""Messaging cleanup preserves other plugins and survives individual close failures."""

from types import SimpleNamespace
from unittest.mock import Mock

from colosseum_messaging import connections
from colosseum_messaging.connections import close_all


def test_close_all_isolates_failures_and_leaves_other_resources(monkeypatch):
    ctx = SimpleNamespace(resource_cache={})
    monkeypatch.setattr(connections, "get_context", lambda: ctx)
    broken = Mock()
    broken.close.side_effect = RuntimeError("close failed")
    healthy = Mock()
    unrelated = Mock()
    ctx.resource_cache.update({
        "messaging:http:1": broken,
        "messaging:redis:1": healthy,
        "messaging:ssh:1": object(),
        "equipment:psu:1": unrelated,
        "messaging:http-other:1": unrelated,
    })

    close_all()
    close_all()

    broken.close.assert_called_once()
    healthy.close.assert_called_once()
    unrelated.close.assert_not_called()
    assert ctx.resource_cache == {
        "equipment:psu:1": unrelated,
        "messaging:http-other:1": unrelated,
    }
