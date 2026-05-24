"""Provider-neutral AI calls for StudyBuddy."""
import base64
import json
import re

from anthropic import Anthropic
from openai import OpenAI

from model_config import (
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENAI,
    current_api_key,
    current_model,
    current_provider,
)


def _anthropic_client() -> Anthropic:
    api_key = current_api_key()
    return Anthropic(api_key=api_key) if api_key else Anthropic()


def _openai_client() -> OpenAI:
    api_key = current_api_key()
    return OpenAI(api_key=api_key) if api_key else OpenAI()


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text


def call_json(prompt: str, max_tokens: int = 4096) -> dict | list:
    """Send a text prompt to the selected provider and parse a JSON response."""
    provider = current_provider()
    model = current_model()
    if provider == PROVIDER_OPENAI:
        response = _openai_client().chat.completions.create(
            model=model,
            max_completion_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = (response.choices[0].message.content or "").strip()
    else:
        response = _anthropic_client().messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

    text = _strip_json_fences(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"⚠️  JSON parse failed: {e}")
        print(f"Raw start: {text[:500]}")
        raise


def call_vision_text(image_bytes: bytes, media_type: str, prompt: str, max_tokens: int = 2048) -> str:
    """Send one image plus text instructions to the selected provider."""
    img_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    provider = current_provider()
    model = current_model()

    if provider == PROVIDER_OPENAI:
        response = _openai_client().chat.completions.create(
            model=model,
            max_completion_tokens=max_tokens,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{img_b64}"},
                    },
                ],
            }],
        )
        return (response.choices[0].message.content or "").strip()

    response = _anthropic_client().messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    return response.content[0].text.strip()
