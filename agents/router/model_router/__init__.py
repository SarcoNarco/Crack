"""Config-driven LLM client selection for future contained Crack agents."""

from .router import ModelClient, ModelRouterError, get_client

__all__ = ["ModelClient", "ModelRouterError", "get_client"]
