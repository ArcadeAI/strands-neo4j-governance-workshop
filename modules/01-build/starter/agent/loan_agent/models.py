"""Which model the agent thinks with: Amazon Bedrock, Anthropic, or the scripted one.

    MODEL_PROVIDER=bedrock     # AWS credentials from your usual chain (profile, SSO, env); AWS_REGION
    MODEL_PROVIDER=anthropic   # ANTHROPIC_API_KEY
    MODEL_PROVIDER=scripted    # no key: the default when nothing is set

MODEL_ID overrides the provider's default model. Nothing about governance depends on this
choice: the same calls reach the same hooks whichever model makes them.
"""

from __future__ import annotations

from strands.models.model import Model

from loan_agent.config import Settings
from loan_agent.scripted import ScriptedModel

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
        # TODO(module 01): return a `strands.models.bedrock.BedrockModel`.
        #   - region_name: settings.aws_region (None lets boto3 pick it from your AWS config)
        #   - temperature 0.0, so reruns are comparable
        #   - model_id: settings.model_id when it is set; otherwise leave it out and Strands uses its default
        raise NotImplementedError("module 01: build the Bedrock model")
    if provider == "anthropic":
        # TODO(module 01): return a `strands.models.anthropic.AnthropicModel`.
        #   - raise ValueError if settings.anthropic_api_key is empty
        #   - client_args={"api_key": ...}, model_id (settings.model_id or DEFAULT_ANTHROPIC_MODEL),
        #     max_tokens=4096 (required by Anthropic), params={"temperature": 0}
        raise NotImplementedError("module 01: build the Anthropic model")
    return ScriptedModel()
