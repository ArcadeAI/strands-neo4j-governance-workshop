"""Which model the agent thinks with: Amazon Bedrock, Anthropic, or the scripted one.

    MODEL_PROVIDER=bedrock     # AWS credentials from your usual chain (profile, SSO, env); AWS_REGION
    MODEL_PROVIDER=anthropic   # ANTHROPIC_API_KEY
    MODEL_PROVIDER=scripted    # no key: the default when nothing is set

MODEL_ID overrides the provider's default model. Nothing about governance depends on this
choice: the same calls reach the same hooks whichever model makes them.
"""

from __future__ import annotations

from strands.models.model import Model

from bank_agent.config import Settings
from bank_agent.scripted import ScriptedModel

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5-5"
PROVIDERS = ("bedrock", "anthropic", "scripted")


def provider_of(settings: Settings) -> str:
    if settings.model_provider:
        if settings.model_provider not in PROVIDERS:
            raise ValueError(f"MODEL_PROVIDER must be one of {', '.join(PROVIDERS)}, not {settings.model_provider!r}")
        return settings.model_provider
    if settings.anthropic_api_key:
        return "anthropic"
    return "scripted"


def make_model(settings: Settings) -> Model:
    provider = provider_of(settings)
    if provider == "bedrock":
        from strands.models.bedrock import BedrockModel

        options: dict = {"temperature": 0.0}
        if settings.model_id:
            options["model_id"] = settings.model_id
        return BedrockModel(region_name=settings.aws_region or None, **options)
    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError("MODEL_PROVIDER=anthropic needs ANTHROPIC_API_KEY in .env")
        from strands.models.anthropic import AnthropicModel

        return AnthropicModel(
            client_args={"api_key": settings.anthropic_api_key},
            model_id=settings.model_id or DEFAULT_ANTHROPIC_MODEL,
            max_tokens=4096,
            params={"temperature": 0},
        )
    return ScriptedModel()
