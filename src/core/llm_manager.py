"""LLM client management for OpenAI Agents SDK.

This module provides a centralized way to create OpenAIChatCompletionsModel
instances for different LLM providers using the agents SDK.
"""

import os

from loguru import logger
from openai import AsyncOpenAI

from agents import OpenAIChatCompletionsModel
from loguru import logger
from openai import AsyncOpenAI

from src.core.configs import AVAILABLE_LLMS, LLMConfig, LLMProvider, settings


class LLMManager:
    """Manages OpenAIChatCompletionsModel instances for different LLM providers.

    Uses the registry pattern from configs.py to dynamically create models
    for any configured provider, compatible with the OpenAI Agents SDK.
    """

    def __init__(self) -> None:
        self._models: dict[str, OpenAIChatCompletionsModel] = {}
        self._clients: dict[str, AsyncOpenAI] = {}

    def get_model(self, provider: LLMProvider) -> OpenAIChatCompletionsModel | None:
        """Get or create an OpenAIChatCompletionsModel for the specified provider.

        Args:
            provider: The LLM provider key from AVAILABLE_LLMS

        Returns:
            OpenAIChatCompletionsModel configured for the provider, or None if API key missing
        """
        if provider in self._models:
            return self._models[provider]

        config = AVAILABLE_LLMS.get(provider)
        if not config:
            logger.error(f"Unknown LLM provider: {provider}")
            return None

        # First try environment variables (os.environ). If the process was
        # started with keys loaded via Pydantic Settings (from a .env file),
        # they will be accessible through `settings` as well — so we use the
        # settings object as a fallback to avoid requiring manual env export.
        api_key = os.getenv(config.api_key_env_var)
        if not api_key:
            # config.api_key_env_var is like 'GOOGLE_API_KEY' -> attribute on
            # settings will be 'google_api_key' (Pydantic maps env var to field
            # name). Use lowercase to derive the attribute name.
            attr_name = config.api_key_env_var.lower()
            api_key = getattr(settings, attr_name, None)

        if not api_key:
            logger.warning(
                f"API key not found for provider '{provider}' "
                f"(env var: {config.api_key_env_var})"
            )
            return None

        # Create AsyncOpenAI client for the provider
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=config.base_url,
        )
        self._clients[provider] = client

        # Create OpenAIChatCompletionsModel wrapper for agents SDK
        model = OpenAIChatCompletionsModel(
            model=config.model_name,
            openai_client=client,
        )
        self._models[provider] = model
        logger.info(f"Created agents SDK model for provider: {provider} ({config.model_name})")

        return model

    def get_client(self, provider: LLMProvider) -> AsyncOpenAI | None:
        """Get or create an AsyncOpenAI client for the specified provider.

        Args:
            provider: The LLM provider key from AVAILABLE_LLMS

        Returns:
            AsyncOpenAI client configured for the provider, or None if API key missing
        """
        # Ensure model is created first (which also creates the client)
        if provider not in self._clients:
            self.get_model(provider)
        return self._clients.get(provider)

    def get_model_name(self, provider: LLMProvider) -> str | None:
        """Get the model name for a provider.

        Args:
            provider: The LLM provider key

        Returns:
            Model name string or None if provider not found
        """
        config = AVAILABLE_LLMS.get(provider)
        return config.model_name if config else None

    def get_config(self, provider: LLMProvider) -> LLMConfig | None:
        """Get the full configuration for a provider.

        Args:
            provider: The LLM provider key

        Returns:
            LLMConfig instance or None if provider not found
        """
        return AVAILABLE_LLMS.get(provider)

    @property
    def available_providers(self) -> list[str]:
        """List all available provider keys."""
        return list(AVAILABLE_LLMS.keys())

    def is_provider_configured(self, provider: LLMProvider) -> bool:
        """Check if a provider has its API key configured.

        Args:
            provider: The LLM provider key

        Returns:
            True if the provider's API key is set in environment
        """
        config = AVAILABLE_LLMS.get(provider)
        if not config:
            return False
        return bool(os.getenv(config.api_key_env_var))


# Global singleton instance
llm_manager = LLMManager()
