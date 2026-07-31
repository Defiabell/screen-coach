"""Send a screenshot to Claude and get a structured English-learning breakdown."""
from __future__ import annotations

import json

import config

SYSTEM_PROMPT = (
    "You are an English reading tutor for a Chinese native speaker whose "
    "vocabulary is about 2300 words. You are shown a screenshot. Read the "
    "English sentence(s) in it and produce a learning breakdown via the "
    "structured output only. Rules: write translation and every explanation "
    "in Simplified Chinese, using short sentences, one point per line. "
    "'breakdown' marks the main clause (主谓宾) and any 从句 or 非谓语. "
    "'words' lists only the harder words (at most 8); for each give the IPA "
    "and the meaning IN THIS sentence. 'usage' gives one or two collocation "
    "or sentence-pattern points worth learning. 'summary' is one line. "
    "If the image has no readable English, set translation to "
    "'未识别到英文' and leave the other fields empty."
)

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "sentence": {"type": "string"},
        "translation": {"type": "string"},
        "breakdown": {"type": "string"},
        "words": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "word": {"type": "string"},
                    "ipa": {"type": "string"},
                    "meaning": {"type": "string"},
                },
                "required": ["word", "ipa", "meaning"],
                "additionalProperties": False,
            },
        },
        "usage": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": ["sentence", "translation", "breakdown", "words", "usage", "summary"],
    "additionalProperties": False,
}


def analyze_image(client, image_b64: str, model: str = config.MODEL) -> dict:
    """Return a parsed learning breakdown for the English in a base64 PNG."""
    resp = client.messages.create(
        model=model,
        max_tokens=config.MAX_TOKENS,
        system=SYSTEM_PROMPT,
        # No "effort" key: measured at 3.8-4.5s with effort=low vs 2.8-2.9s
        # without it, same model, same image — it costs a second here rather
        # than saving one. It's also rejected outright by opus-4-1 and
        # haiku-4-5 ("This model does not support the effort parameter"),
        # so leaving it out keeps the model swappable.
        output_config={"format": {"type": "json_schema", "schema": ANALYSIS_SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64}},
                    {"type": "text", "text": "Analyze the English in this image."},
                ],
            }
        ],
    )
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return json.loads(text)
