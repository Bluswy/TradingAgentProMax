import os
import re
from pathlib import Path
from typing import Any, Optional

from langchain_openai import ChatOpenAI

from .base_client import BaseLLMClient
from .validators import validate_model


class UnifiedChatOpenAI(ChatOpenAI):
    """ChatOpenAI subclass that strips temperature/top_p for GPT-5 family models.

    GPT-5 family models use reasoning natively. temperature/top_p are only
    accepted when reasoning.effort is 'none'; with any other effort level
    (or for older GPT-5/GPT-5-mini/GPT-5-nano which always reason) the API
    rejects these params. Langchain defaults temperature=0.7, so we must
    strip it to avoid errors.

    Non-GPT-5 models (GPT-4.1, xAI, Ollama, etc.) are unaffected.
    """

    def __init__(self, **kwargs):
        if "gpt-5" in kwargs.get("model", "").lower():
            kwargs.pop("temperature", None)
            kwargs.pop("top_p", None)
        super().__init__(**kwargs)


def _load_project_bailian_api_key(project_dir: Optional[str]) -> str | None:
    if not project_dir:
        return None

    config_path = Path(project_dir).parent / "config" / "bailian.toml"
    if not config_path.exists():
        return None

    content = config_path.read_text(encoding="utf-8")
    match = re.search(r'^\s*api_key\s*=\s*["\']([^"\']+)["\']\s*$', content, flags=re.MULTILINE)
    if not match:
        return None

    api_key = match.group(1).strip()
    return api_key or None


class OpenAIClient(BaseLLMClient):
    """Client for OpenAI-compatible providers."""

    def __init__(
        self,
        model: str,
        base_url: Optional[str] = None,
        provider: str = "openai",
        **kwargs,
    ):
        super().__init__(model, base_url, **kwargs)
        self.provider = provider.lower()

    def get_llm(self) -> Any:
        """Return configured ChatOpenAI instance."""
        llm_kwargs = {"model": self.model}

        if self.provider == "xai":
            llm_kwargs["base_url"] = "https://api.x.ai/v1"
            api_key = os.environ.get("XAI_API_KEY")
            if api_key:
                llm_kwargs["api_key"] = api_key
        elif self.provider == "openrouter":
            llm_kwargs["base_url"] = "https://openrouter.ai/api/v1"
            api_key = os.environ.get("OPENROUTER_API_KEY")
            if api_key:
                llm_kwargs["api_key"] = api_key
        elif self.provider == "ollama":
            llm_kwargs["base_url"] = "http://localhost:11434/v1"
            llm_kwargs["api_key"] = "ollama"  # Ollama doesn't require auth
        elif self.provider in ("bailian", "dashscope"):
            llm_kwargs["base_url"] = self.base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
            api_key = (
                self.kwargs.get("api_key")
                or _load_project_bailian_api_key(self.kwargs.get("project_dir"))
                or os.environ.get("BAILIAN_API_KEY")
                or os.environ.get("DASHSCOPE_API_KEY")
            )
            if not api_key:
                raise RuntimeError(
                    "Missing Bailian API key. Set config/bailian.toml, config['bailian_api_key'], "
                    "or BAILIAN_API_KEY / DASHSCOPE_API_KEY."
                )
            llm_kwargs["api_key"] = api_key
            extra_body = dict(self.kwargs.get("extra_body", {}) or {})
            if self.kwargs.get("bailian_enable_thinking") is not None:
                extra_body["enable_thinking"] = bool(self.kwargs.get("bailian_enable_thinking"))
            if self.kwargs.get("bailian_thinking_budget") is not None:
                extra_body["thinking_budget"] = int(self.kwargs.get("bailian_thinking_budget"))
            if extra_body:
                llm_kwargs["extra_body"] = extra_body
        elif self.base_url:
            llm_kwargs["base_url"] = self.base_url

        for key in ("timeout", "max_retries", "reasoning_effort", "api_key", "callbacks", "http_client", "http_async_client"):
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        return UnifiedChatOpenAI(**llm_kwargs)

    def validate_model(self) -> bool:
        """Validate model for the provider."""
        return validate_model(self.provider, self.model)
