"""Hermes Slack Agent Router: context-aware multi-agent routing powered by Jev."""

__version__ = "0.1.0"


def register(ctx):
    """Directory and installed entry-point registration share one implementation."""
    from .plugin import register as register_plugin

    return register_plugin(ctx)
