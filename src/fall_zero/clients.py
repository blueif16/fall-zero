"""OpenAI-compatible clients for every provider.

Every provider here speaks the OpenAI protocol, so switching between Meta's hosted
models and the open weights on Baseten / Fireworks / Modal is a provider-name change.
"""

from dataclasses import dataclass

from openai import AsyncOpenAI, OpenAI

from fall_zero.config import get_settings


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: str
    model: str

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)


def _v1(url: str) -> str:
    url = url.rstrip("/")
    return url if not url or url.endswith("/v1") else f"{url}/v1"


def providers() -> dict[str, Provider]:
    s = get_settings()
    return {
        "meta": Provider("meta", s.meta_base_url, s.model_api_key, s.meta_text_model),
        "baseten": Provider("baseten", s.baseten_base_url, s.baseten_api_key, s.baseten_model),
        "fireworks": Provider("fireworks", s.fireworks_base_url, s.fireworks_api_key, s.fireworks_model),
        "modal": Provider("modal", _v1(s.modal_spark_open_url), s.modal_proxy_token, s.modal_spark_open_model),
        "glimmer": Provider("glimmer", _v1(s.glimmer_url), s.modal_proxy_token, s.glimmer_model),
    }


class NotConfigured(RuntimeError):
    pass


def get_provider(name: str) -> Provider:
    try:
        p = providers()[name]
    except KeyError:
        raise ValueError(f"Unknown provider {name!r}; choose from {sorted(providers())}") from None
    if not p.configured:
        raise NotConfigured(f"Provider {name!r} is not configured; fill in its values in .env")
    return p


def client(name: str = "meta") -> OpenAI:
    p = get_provider(name)
    return OpenAI(base_url=p.base_url, api_key=p.api_key)


def aclient(name: str = "meta") -> AsyncOpenAI:
    p = get_provider(name)
    return AsyncOpenAI(base_url=p.base_url, api_key=p.api_key)


def chat(prompt: str | list[dict], provider: str = "meta", model: str | None = None, **kwargs) -> str:
    """One Chat Completions call. Works on every provider; returns the answer text only."""
    messages = [{"role": "user", "content": prompt}] if isinstance(prompt, str) else prompt
    resp = client(provider).chat.completions.create(
        model=model or get_provider(provider).model, messages=messages, **kwargs
    )
    return resp.choices[0].message.content or ""
