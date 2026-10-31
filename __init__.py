"""Native Git-root entry point; export the existing package registration unchanged."""

from .hermes_slack_agent_router import register

__all__ = ["register"]
