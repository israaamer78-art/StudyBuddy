"""AI provider, model, and browser-key selection shared by Flask routes and generators."""
from contextvars import ContextVar

PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OPENAI = "openai"

ANTHROPIC_MODEL_OPTIONS = {
    "claude-opus-4-7": "Claude Opus 4.7",
    "claude-sonnet-4-6": "Claude Sonnet 4.6",
    "claude-haiku-4-5": "Claude Haiku 4.5",
}
OPENAI_MODEL_OPTIONS = {
    "gpt-5.5": "GPT-5.5",
    "gpt-5.4-mini": "GPT-5.4 Mini",
    "gpt-5.4-nano": "GPT-5.4 Nano",
}
MODEL_OPTIONS = {**ANTHROPIC_MODEL_OPTIONS, **OPENAI_MODEL_OPTIONS}
MODEL_PROVIDERS = {
    **{model: PROVIDER_ANTHROPIC for model in ANTHROPIC_MODEL_OPTIONS},
    **{model: PROVIDER_OPENAI for model in OPENAI_MODEL_OPTIONS},
}
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_PROVIDER = PROVIDER_ANTHROPIC
DEFAULT_MODELS = {
    PROVIDER_ANTHROPIC: DEFAULT_MODEL,
    PROVIDER_OPENAI: "gpt-5.4-mini",
}

_current_provider = ContextVar("studybuddy_provider", default=DEFAULT_PROVIDER)
_current_model = ContextVar("studybuddy_model", default=DEFAULT_MODEL)
_current_api_key = ContextVar("studybuddy_api_key", default=None)


def normalize_provider(provider: str | None) -> str:
    provider = (provider or "").strip().lower()
    if provider in {PROVIDER_ANTHROPIC, PROVIDER_OPENAI}:
        return provider
    return DEFAULT_PROVIDER


def normalize_model(model: str | None) -> str:
    if model in MODEL_OPTIONS:
        return model
    return DEFAULT_MODEL


def provider_for_model(model: str | None) -> str:
    return MODEL_PROVIDERS.get(normalize_model(model), DEFAULT_PROVIDER)


def normalize_provider_model(provider: str | None, model: str | None) -> tuple[str, str]:
    normalized_provider = normalize_provider(provider)
    normalized_model = normalize_model(model)
    if provider_for_model(normalized_model) != normalized_provider:
        normalized_model = DEFAULT_MODELS[normalized_provider]
    return normalized_provider, normalized_model


def current_provider() -> str:
    return _current_provider.get()


def current_model() -> str:
    return _current_model.get()


def set_current_model(model: str | None):
    normalized_model = normalize_model(model)
    _current_provider.set(provider_for_model(normalized_model))
    return _current_model.set(normalized_model)


def set_current_provider_model(provider: str | None, model: str | None):
    normalized_provider, normalized_model = normalize_provider_model(provider, model)
    provider_token = _current_provider.set(normalized_provider)
    model_token = _current_model.set(normalized_model)
    return provider_token, model_token


def reset_current_model(token) -> None:
    _current_model.reset(token)


def reset_current_provider(token) -> None:
    _current_provider.reset(token)


def reset_current_provider_model(tokens) -> None:
    provider_token, model_token = tokens
    _current_model.reset(model_token)
    _current_provider.reset(provider_token)


def normalize_api_key(api_key: str | None, provider: str | None = None) -> str | None:
    api_key = (api_key or "").strip()
    normalized_provider = normalize_provider(provider)
    if normalized_provider == PROVIDER_ANTHROPIC and api_key.startswith("sk-ant-"):
        return api_key
    if normalized_provider == PROVIDER_OPENAI and api_key.startswith("sk-"):
        return api_key
    return None


def current_api_key() -> str | None:
    return _current_api_key.get()


def set_current_api_key(api_key: str | None):
    return _current_api_key.set(normalize_api_key(api_key, current_provider()))


def reset_current_api_key(token) -> None:
    _current_api_key.reset(token)
