"""MaiBot discovery entry point."""

from .neko_life.plugin import NekoLifePlugin


def create_plugin():
    return NekoLifePlugin()
