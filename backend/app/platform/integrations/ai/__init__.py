"""AI/LLM integration adapter for OpenAI-compatible APIs."""

from app.platform.integrations.ai.client import AIOutputError, AIService

__all__ = ["AIService", "AIOutputError"]
