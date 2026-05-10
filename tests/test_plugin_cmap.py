"""@plugin decorator carries an optional cmap= for default colormap."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def clear():
    from eggseis.plugin import _REGISTRY
    _REGISTRY.clear()
    yield
    _REGISTRY.clear()


def test_plugin_cmap_round_trips_through_registry():
    from eggseis.plugin import _REGISTRY, Param, plugin

    @plugin(name="pretty_attr", cmap="batlow")
    def pretty_attr(section, k: int = Param(default=3)):
        return section

    entry = _REGISTRY["pretty_attr"]
    assert entry.cmap == "batlow"


def test_plugin_without_cmap_has_none():
    from eggseis.plugin import _REGISTRY, plugin

    @plugin(name="plain_attr")
    def plain_attr(section):
        return section

    assert _REGISTRY["plain_attr"].cmap is None


def test_plugin_with_unknown_cmap_raises():
    from eggseis.plugin import PluginRegistrationError, plugin

    with pytest.raises(PluginRegistrationError):

        @plugin(name="bogus", cmap="not_a_real_cmap")
        def bogus(section):
            return section
