"""The agent's settings, from the environment and the repository's `.env`."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DESKS = ("assistant", "payments", "aml", "banker")
DEFAULT_USERS = {
    "assistant": "pat@bank.example",
    "payments": "pat@bank.example",
    "aml": "ava@bank.example",
    "banker": "ian@bank.example",
}


def load_env() -> None:
    """Read `.env` from the current directory or the nearest parent, without overriding the shell."""
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(usecwd=True))


def _get(env: Mapping[str, str], key: str) -> str:
    return (env.get(key) or "").strip()


@dataclass(frozen=True)
class Settings:
    user: str = DEFAULT_USERS["assistant"]
    desk: str = "assistant"
    connected_apps_user: str = ""
    arcade_api_key: str = ""
    arcade_base_url: str = ""
    toolkit: str = "Bank"
    tools_per_task: int = 5
    model_provider: str = ""
    model_id: str = ""
    aws_region: str = ""
    anthropic_api_key: str = ""

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, *, user: str | None = None, desk: str = "assistant") -> Settings:
        env = os.environ if env is None else env
        if desk not in DESKS:
            raise ValueError(f"desk must be one of {', '.join(DESKS)}, not {desk!r}")
        return cls(
            user=(user or _get(env, "BANK_USER") or DEFAULT_USERS[desk]).lower(),
            desk=desk,
            connected_apps_user=_get(env, "CONNECTED_APPS_USER").lower(),
            arcade_api_key=_get(env, "ARCADE_API_KEY"),
            arcade_base_url=_get(env, "ARCADE_BASE_URL"),
            toolkit=_get(env, "ARCADE_TOOLKIT") or "Bank",
            tools_per_task=int(_get(env, "ARCADE_TOOLS_PER_TASK") or 5),
            model_provider=_get(env, "MODEL_PROVIDER").lower(),
            model_id=_get(env, "MODEL_ID"),
            aws_region=_get(env, "AWS_REGION") or _get(env, "AWS_DEFAULT_REGION"),
            anthropic_api_key=_get(env, "ANTHROPIC_API_KEY"),
        )
